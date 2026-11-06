"""
Permisos delegados por el Administrador a usuarios Auxiliares.

La matriz de permisos marca algunas acciones del Auxiliar como REQ: las pide
y un superior las aprueba una por una (modules/aprobaciones). El
Administrador puede, además, otorgar a un auxiliar concreto un permiso
delegado sobre uno de esos códigos. Mientras el permiso esté activo y
vigente, ese auxiliar ejecuta la acción directamente; el uso queda anotado
en `permiso_auxiliar_uso`.

Interfaz pública que usan otros módulos:

    await auxiliar_tiene_permiso(session, id_usuario, "EMP-006") -> bool
    registrar_permiso_delegable("PQR-005", "Asignar responsable", "PQRS")
    permisos_delegables() -> list[dict]
    await usar_permiso_delegado(session, usuario, "USR-CLAVE", "detalle") -> bool
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import logger
from modules.permisos_auxiliar.permisos_auxiliar_catalogo import CATALOGO_BASE, MODULOS_POR_PREFIJO

ROL_AUXILIAR = "auxiliar"

# ============================================================
# CATÁLOGO EN MEMORIA
# ============================================================

_CATALOGO: dict[str, dict[str, str]] = {}


def registrar_permiso_delegable(codigo: str, descripcion: str, modulo: str) -> None:
    """Agrega (o actualiza) un código que el Administrador puede otorgar."""
    codigo = (codigo or "").strip().upper()
    if not codigo:
        return
    # Cada prefijo cae siempre en el mismo grupo aunque el módulo que lo
    # registra lo nombre distinto ("Usuarios" -> "M2 — Gestión de usuarios").
    prefijo = codigo.split("-", 1)[0]
    _CATALOGO[codigo] = {
        "codigo": codigo,
        "descripcion": (descripcion or codigo).strip(),
        "modulo": MODULOS_POR_PREFIJO.get(prefijo) or (modulo or "Otros").strip(),
    }


def permisos_delegables() -> list[dict]:
    """Catálogo ordenado por módulo y código."""
    return [dict(v) for v in sorted(_CATALOGO.values(), key=lambda x: (_orden_modulo(x["modulo"]), x["modulo"], x["codigo"]))]


def _orden_modulo(modulo: str) -> int:
    """M1, M2 ... M12 en orden numérico; lo demás (PQRS, Otros) al final."""
    import re

    coincidencia = re.match(r"M(\d+)", modulo or "")
    return int(coincidencia.group(1)) if coincidencia else 999


def es_delegable(codigo: str) -> bool:
    return (codigo or "").strip().upper() in _CATALOGO


for _codigo, _descripcion, _modulo in CATALOGO_BASE:
    registrar_permiso_delegable(_codigo, _descripcion, _modulo)


def _es_rol_auxiliar(nombre_rol: str | None) -> bool:
    # Import diferido: core.security importa la configuración completa.
    from core.security import _normalize_role_name

    return _normalize_role_name(nombre_rol) == ROL_AUXILIAR


# ============================================================
# CONSULTA DE PERMISO (punto de integración con REQ)
# ============================================================

_SQL_PERMISO_VIGENTE = """
    SELECT p.id_permiso, p.activo, p.fecha_vencimiento, p.fecha_revocado,
           u.estado AS estado_usuario, r.nombre AS role_name
    FROM permiso_auxiliar p
    JOIN usuario u ON u.id_usuario = p.id_usuario
    LEFT JOIN rol r ON r.id_rol = u.rol_id
    WHERE p.id_usuario = CAST(:id_usuario AS UUID)
      AND p.codigo_permiso = :codigo
      AND p.activo = TRUE
"""


def _hoy() -> date:
    from core.datetime_utils import system_now

    return system_now().date()


def permiso_es_vigente(fila: dict | None, hoy: date | None = None) -> bool:
    """
    Regla de vigencia, separada de la consulta para poder probarla:
    activo, no revocado, sin vencer (vale hasta el día de vencimiento
    inclusive), usuario activo y con rol Auxiliar.
    """
    if not fila:
        return False
    if fila.get("activo") is not True or fila.get("fecha_revocado") is not None:
        return False
    if fila.get("estado_usuario") != "Activo" or not _es_rol_auxiliar(fila.get("role_name")):
        return False
    vence = fila.get("fecha_vencimiento")
    if vence is not None:
        if hasattr(vence, "date"):
            vence = vence.date()
        if vence < (hoy or _hoy()):
            return False
    return True


async def _permiso_vigente(session, id_usuario, codigo_permiso: str) -> Any | None:
    """Id del permiso vigente o None. Nunca lanza: ante cualquier error, None."""
    # Solo sesiones reales: un doble de prueba (MagicMock/AsyncMock) nunca
    # concede permisos y tampoco deja corrutinas sin esperar.
    if not isinstance(session, AsyncSession) or not id_usuario or not codigo_permiso:
        return None
    codigo = codigo_permiso.strip().upper()
    try:
        # Savepoint: si la tabla aún no existe o la consulta falla, la
        # transacción de la petición sigue utilizable.
        async with session.begin_nested():
            resultado = await session.execute(
                text(_SQL_PERMISO_VIGENTE), {"id_usuario": str(id_usuario), "codigo": codigo}
            )
            filas = [dict(f) for f in resultado.mappings().all()]
    except Exception as error:  # noqa: BLE001 - la falta de permiso es el valor seguro
        logger.debug("No se pudo consultar permiso delegado %s: %s", codigo, error)
        return None
    hoy = _hoy()
    for fila in filas:
        if permiso_es_vigente(fila, hoy):
            return fila.get("id_permiso")
    return None


async def auxiliar_tiene_permiso(session, id_usuario, codigo_permiso: str) -> bool:
    """True si ese usuario es auxiliar activo y tiene ese código otorgado y vigente."""
    return await _permiso_vigente(session, id_usuario, codigo_permiso) is not None


async def registrar_uso(
    session,
    id_usuario,
    codigo_permiso: str,
    detalle: str | None = None,
    id_aprobacion=None,
) -> None:
    """Anota que el auxiliar ejecutó una acción gracias al permiso delegado."""
    codigo = (codigo_permiso or "").strip().upper()
    if not isinstance(session, AsyncSession):
        return
    id_permiso = await _permiso_vigente(session, id_usuario, codigo)
    try:
        async with session.begin_nested():
            await session.execute(
                text("""
                    INSERT INTO permiso_auxiliar_uso (id_permiso, id_usuario, codigo_permiso, detalle, id_aprobacion)
                    VALUES (:id_permiso, CAST(:id_usuario AS UUID), :codigo, :detalle, :id_aprobacion)
                """),
                {
                    "id_permiso": id_permiso,
                    "id_usuario": str(id_usuario),
                    "codigo": codigo,
                    "detalle": (detalle or "")[:500] or None,
                    "id_aprobacion": str(id_aprobacion) if id_aprobacion else None,
                },
            )
    except Exception as error:  # noqa: BLE001 - el registro no debe tumbar la acción
        logger.warning("No se pudo registrar el uso del permiso delegado %s: %s", codigo, error)
    logger.info("Auxiliar %s ejecutó %s con permiso delegado. %s", id_usuario, codigo, detalle or "")


async def usar_permiso_delegado(session, usuario: dict, codigo_permiso: str, detalle: str | None = None) -> bool:
    """
    Atajo para los módulos: si el usuario (dict de get_current_user) es un
    auxiliar con el permiso vigente, anota el uso y devuelve True. El llamador
    hace commit junto con su propia acción.
    """
    if not usuario or not _es_rol_auxiliar(usuario.get("role_name")):
        return False
    id_usuario = usuario.get("id_usuario")
    if not await auxiliar_tiene_permiso(session, id_usuario, codigo_permiso):
        return False
    await registrar_uso(session, id_usuario, codigo_permiso, detalle)
    return True


# ============================================================
# GESTIÓN (la usa el router, solo para el Administrador)
# ============================================================

_COLUMNAS_PERMISO = """
    p.id_permiso, p.id_usuario, p.codigo_permiso, p.otorgado_por, p.fecha_otorgado,
    p.fecha_vencimiento, p.activo, p.motivo, p.revocado_por, p.fecha_revocado,
    p.motivo_revocacion,
    uo.nombre AS otorgado_por_nombre, ur.nombre AS revocado_por_nombre,
    (p.activo AND (p.fecha_vencimiento IS NULL OR p.fecha_vencimiento >= CURRENT_DATE)) AS vigente
"""

_ORIGEN_PERMISO = """
    FROM permiso_auxiliar p
    LEFT JOIN usuario uo ON uo.id_usuario = p.otorgado_por
    LEFT JOIN usuario ur ON ur.id_usuario = p.revocado_por
"""


def _con_catalogo(fila: dict) -> dict:
    datos = dict(fila)
    info = _CATALOGO.get(datos.get("codigo_permiso") or "", {})
    datos["descripcion"] = info.get("descripcion", datos.get("codigo_permiso"))
    datos["modulo"] = info.get("modulo", "Otros")
    return datos


class PermisosAuxiliarService:
    def __init__(self, db):
        self.db = db

    async def listar_auxiliares(self) -> list[dict]:
        resultado = await self.db.execute(text("""
            SELECT u.id_usuario, u.nombre, u.correo, u.estado, r.nombre AS role_name,
                   (SELECT COUNT(*) FROM permiso_auxiliar p
                     WHERE p.id_usuario = u.id_usuario AND p.activo = TRUE
                       AND (p.fecha_vencimiento IS NULL OR p.fecha_vencimiento >= CURRENT_DATE)
                   ) AS permisos_vigentes
            FROM usuario u
            JOIN rol r ON r.id_rol = u.rol_id
            ORDER BY u.nombre
        """))
        return [dict(f) for f in resultado.mappings().all() if _es_rol_auxiliar(f.get("role_name"))]

    async def _auxiliar(self, id_usuario) -> dict:
        resultado = await self.db.execute(
            text("""
                SELECT u.id_usuario, u.nombre, u.correo, u.estado, r.nombre AS role_name
                FROM usuario u LEFT JOIN rol r ON r.id_rol = u.rol_id
                WHERE u.id_usuario = CAST(:id AS UUID)
            """),
            {"id": str(id_usuario)},
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario no existe.")
        if not _es_rol_auxiliar(fila.get("role_name")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Solo se pueden delegar permisos a usuarios con rol Auxiliar.",
            )
        return dict(fila)

    async def permisos_de(self, id_usuario) -> dict:
        auxiliar = await self._auxiliar(id_usuario)
        resultado = await self.db.execute(
            text(f"""
                SELECT {_COLUMNAS_PERMISO} {_ORIGEN_PERMISO}
                WHERE p.id_usuario = CAST(:id AS UUID) AND p.activo = TRUE
            """),
            {"id": str(id_usuario)},
        )
        activos = {f["codigo_permiso"]: _con_catalogo(f) for f in resultado.mappings().all()}
        permisos = []
        for item in permisos_delegables():
            otorgado = activos.pop(item["codigo"], None)
            permisos.append({
                **item,
                "otorgado": bool(otorgado and otorgado["vigente"]),
                "vencido": bool(otorgado and not otorgado["vigente"]),
                "detalle": otorgado,
            })
        # Permisos activos cuyo código ya no está en el catálogo: se muestran
        # igual para poder revocarlos.
        for codigo, otorgado in activos.items():
            permisos.append({
                "codigo": codigo, "descripcion": otorgado["descripcion"], "modulo": otorgado["modulo"],
                "otorgado": bool(otorgado["vigente"]), "vencido": not otorgado["vigente"], "detalle": otorgado,
            })
        return {"auxiliar": auxiliar, "permisos": permisos}

    async def mios(self, usuario: dict) -> list[dict]:
        if not _es_rol_auxiliar(usuario.get("role_name")):
            return []
        resultado = await self.db.execute(
            text(f"""
                SELECT {_COLUMNAS_PERMISO} {_ORIGEN_PERMISO}
                WHERE p.id_usuario = CAST(:id AS UUID) AND p.activo = TRUE
                  AND (p.fecha_vencimiento IS NULL OR p.fecha_vencimiento >= CURRENT_DATE)
                ORDER BY p.codigo_permiso
            """),
            {"id": str(usuario.get("id_usuario"))},
        )
        return [_con_catalogo(f) for f in resultado.mappings().all()]

    async def otorgar(
        self, id_usuario, codigo: str, motivo: str, fecha_vencimiento: date | None, admin: dict
    ) -> dict:
        codigo = (codigo or "").strip().upper()
        if not es_delegable(codigo):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El permiso {codigo} no está en el catálogo de permisos delegables.",
            )
        if fecha_vencimiento is not None and fecha_vencimiento < date.today():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La fecha de vencimiento no puede ser anterior a hoy.",
            )
        auxiliar = await self._auxiliar(id_usuario)
        if auxiliar.get("estado") != "Activo":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El auxiliar no está activo; actívelo antes de delegarle permisos.",
            )

        # Si hay uno activo pero vencido, se cierra para poder otorgar el nuevo.
        await self.db.execute(
            text("""
                UPDATE permiso_auxiliar
                SET activo = FALSE, fecha_revocado = NOW(),
                    revocado_por = CAST(:admin AS UUID),
                    motivo_revocacion = 'Vencido; reemplazado por un nuevo otorgamiento.'
                WHERE id_usuario = CAST(:id AS UUID) AND codigo_permiso = :codigo AND activo = TRUE
                  AND fecha_vencimiento IS NOT NULL AND fecha_vencimiento < CURRENT_DATE
            """),
            {"id": str(id_usuario), "codigo": codigo, "admin": str(admin.get("id_usuario"))},
        )
        try:
            resultado = await self.db.execute(
                text("""
                    INSERT INTO permiso_auxiliar (id_usuario, codigo_permiso, otorgado_por, fecha_vencimiento, motivo)
                    VALUES (CAST(:id AS UUID), :codigo, CAST(:admin AS UUID), :vence, :motivo)
                    RETURNING id_permiso
                """),
                {
                    "id": str(id_usuario),
                    "codigo": codigo,
                    "admin": str(admin.get("id_usuario")),
                    "vence": fecha_vencimiento,
                    "motivo": motivo.strip(),
                },
            )
            id_permiso = resultado.scalar()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El auxiliar ya tiene el permiso {codigo} otorgado.",
            )
        await self.db.commit()
        logger.info("Administrador %s otorgó %s al auxiliar %s.", admin.get("id_usuario"), codigo, id_usuario)
        return await self._permiso(id_permiso)

    async def revocar(self, id_usuario, codigo: str, motivo: str, admin: dict) -> dict:
        codigo = (codigo or "").strip().upper()
        await self._auxiliar(id_usuario)
        resultado = await self.db.execute(
            text("""
                UPDATE permiso_auxiliar
                SET activo = FALSE, revocado_por = CAST(:admin AS UUID),
                    fecha_revocado = NOW(), motivo_revocacion = :motivo
                WHERE id_usuario = CAST(:id AS UUID) AND codigo_permiso = :codigo AND activo = TRUE
                RETURNING id_permiso
            """),
            {"id": str(id_usuario), "codigo": codigo, "admin": str(admin.get("id_usuario")), "motivo": motivo.strip()},
        )
        id_permiso = resultado.scalar()
        if id_permiso is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"El auxiliar no tiene el permiso {codigo} activo.",
            )
        await self.db.commit()
        logger.info("Administrador %s revocó %s al auxiliar %s.", admin.get("id_usuario"), codigo, id_usuario)
        return await self._permiso(id_permiso)

    async def _permiso(self, id_permiso) -> dict:
        resultado = await self.db.execute(
            text(f"SELECT {_COLUMNAS_PERMISO} {_ORIGEN_PERMISO} WHERE p.id_permiso = :id"),
            {"id": id_permiso},
        )
        fila = resultado.mappings().first()
        return _con_catalogo(fila) if fila else {"id_permiso": id_permiso}

    async def historial(self, id_usuario=None, limite: int = 200) -> list[dict]:
        """Otorgamientos, revocaciones y usos, del más reciente al más antiguo."""
        filtro = "WHERE h.id_usuario = CAST(:id AS UUID)" if id_usuario else ""
        resultado = await self.db.execute(
            text(f"""
                SELECT h.* FROM (
                    SELECT 'Otorgado' AS evento, p.fecha_otorgado AS fecha, p.id_usuario, p.codigo_permiso,
                           p.otorgado_por AS id_actor, p.motivo AS detalle, p.fecha_vencimiento
                    FROM permiso_auxiliar p
                    UNION ALL
                    SELECT 'Revocado', p.fecha_revocado, p.id_usuario, p.codigo_permiso,
                           p.revocado_por, p.motivo_revocacion, p.fecha_vencimiento
                    FROM permiso_auxiliar p WHERE p.fecha_revocado IS NOT NULL
                    UNION ALL
                    SELECT 'Usado', x.fecha, x.id_usuario, x.codigo_permiso,
                           x.id_usuario, x.detalle, NULL
                    FROM permiso_auxiliar_uso x
                ) h
                {filtro}
                ORDER BY h.fecha DESC
                LIMIT :limite
            """),
            {"id": str(id_usuario) if id_usuario else None, "limite": limite},
        )
        filas = [dict(f) for f in resultado.mappings().all()]
        ids = {str(f["id_usuario"]) for f in filas} | {str(f["id_actor"]) for f in filas if f.get("id_actor")}
        nombres: dict[str, str] = {}
        if ids:
            res = await self.db.execute(
                text("SELECT id_usuario, nombre FROM usuario WHERE CAST(id_usuario AS TEXT) = ANY(:ids)"),
                {"ids": list(ids)},
            )
            nombres = {str(r["id_usuario"]): r["nombre"] for r in res.mappings().all()}
        for f in filas:
            f["usuario_nombre"] = nombres.get(str(f["id_usuario"]))
            f["actor_nombre"] = nombres.get(str(f.get("id_actor"))) if f.get("id_actor") else None
            f.update({k: v for k, v in _con_catalogo(f).items() if k in ("descripcion", "modulo")})
        return filas
