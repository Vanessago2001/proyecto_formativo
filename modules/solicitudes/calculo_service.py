"""
M5 — GESTIÓN DE SOLICITUDES
Bloque 7: cálculo del tiempo de auditoría (SOL-061 a SOL-070).

La duración de una auditoría no se inventa: sale de unas variables de
entrada (empleados, sedes, turnos, complejidad) y de unas constantes por
norma que la administración mantiene en `variables_norma` (SOL-066), no en
el programa. Cada cálculo se guarda con su versión, sus variables y su
desglose, de modo que siempre se pueda explicar de dónde salió un número
(SOL-067, historial matemático).

La fórmula, en resumen:

    base        = horas_base_norma + empleados * horas_por_empleado
    sedes       = (nº de sedes - 1) * horas_por_sede
    complejidad = (base + sedes) * factor_complejidad
    total       = redondeo(base + sedes + complejidad) + ajuste justificado

El ajuste (SOL-065) es la única entrada manual, y exige justificación por
escrito. Validar el cálculo (SOL-069) lo deja listo para asignar auditores,
y bloquearlo (SOL-070) impide recalcular cuando ya se aprobó.
"""

import json
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.solicitudes import bitacora
from modules.solicitudes.solicitud_service import SolicitudService

# Constantes por defecto cuando la norma todavía no tiene las suyas en
# `variables_norma`. Son las que la administración puede cambiar con SOL-066.
VARIABLES_BASE = {
    "horas_base": Decimal("8"),
    "horas_por_empleado": Decimal("0.08"),
    "horas_por_sede": Decimal("4"),
    "factor_complejidad_baja": Decimal("0"),
    "factor_complejidad_media": Decimal("0.10"),
    "factor_complejidad_alta": Decimal("0.25"),
}

COMPLEJIDADES = ("Baja", "Media", "Alta")

ESTADO_BORRADOR = "Borrador"
ESTADO_VALIDADO = "Validado"
ESTADO_BLOQUEADO = "Bloqueado"

COLUMNAS = """
    id_calculo, id_solicitud, version, variables, desglose,
    horas_base, resultado_horas, ajuste_horas, justificacion_ajuste,
    estado, validado, bloqueado,
    usuario_calculo, usuario_ajuste, usuario_validacion,
    fecha_calculo, fecha_validacion, fecha_bloqueo
"""

# La misma lista, pero con el alias de la tabla: hace falta cuando la consulta
# une `calculo_auditoria` con `usuario`.
COLUMNAS_CON_ALIAS = ", ".join(
    f"c.{columna.strip()}" for columna in COLUMNAS.strip().split(",") if columna.strip()
)


def _decimal(valor, por_defecto="0") -> Decimal:
    try:
        return Decimal(str(valor))
    except Exception:
        return Decimal(por_defecto)


def _redondear(valor: Decimal) -> Decimal:
    """Media jornada arriba: las auditorías se planifican en medias jornadas."""
    return (valor * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2


class CalculoAuditoriaService:
    """Cálculo, ajuste y validación del tiempo de auditoría."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.solicitudes = SolicitudService(db)

    # ========================================================
    # AYUDANTES
    # ========================================================

    async def _solicitud(self, id_solicitud: UUID, usuario: dict) -> dict:
        return await self.solicitudes.consultar(id_solicitud, usuario)

    async def variables_de_norma(self, id_norma) -> dict:
        """SOL-066: las constantes de la norma, con las de serie como respaldo."""
        valores = dict(VARIABLES_BASE)
        if not id_norma:
            return valores

        resultado = await self.db.execute(
            text("""
                SELECT nom_variable, valor FROM variables_norma
                WHERE id_norma = :id_norma AND valor IS NOT NULL;
            """),
            {"id_norma": str(id_norma)},
        )
        for fila in resultado.mappings().all():
            if fila["nom_variable"] in valores:
                valores[fila["nom_variable"]] = _decimal(fila["valor"])
        return valores

    async def _ultimo(self, id_solicitud: UUID) -> dict | None:
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS} FROM calculo_auditoria
                WHERE id_solicitud = :id_solicitud
                ORDER BY version DESC LIMIT 1;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        fila = resultado.mappings().first()
        return dict(fila) if fila else None

    @staticmethod
    def _exigir_desbloqueado(calculo: dict | None) -> None:
        """SOL-070: tras la aprobación el cálculo no se vuelve a tocar."""
        if calculo and calculo.get("bloqueado"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El cálculo está bloqueado porque la auditoría ya fue aprobada. "
                    "Para cambiarlo hay que desbloquearlo primero."
                ),
            )

    # ========================================================
    # SOL-061 / SOL-062 · VARIABLES Y CÁLCULO
    # ========================================================

    def aplicar_formula(self, variables: dict, constantes: dict) -> tuple[Decimal, dict]:
        """
        Devuelve (horas, desglose). Separada del acceso a la base para poder
        comprobarla sola: es la parte que de verdad hay que verificar.
        """
        empleados = _decimal(variables.get("numero_empleados"), "0")
        sedes = _decimal(variables.get("numero_sedes"), "1")
        complejidad = str(variables.get("complejidad") or "Media")
        if complejidad not in COMPLEJIDADES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Complejidad no válida. Se aceptan: {', '.join(COMPLEJIDADES)}.",
            )
        if empleados < 0 or sedes < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El número de empleados no puede ser negativo y debe haber al menos una sede.",
            )

        horas_base = constantes["horas_base"] + empleados * constantes["horas_por_empleado"]
        horas_sedes = (sedes - 1) * constantes["horas_por_sede"]
        factor = constantes[f"factor_complejidad_{complejidad.lower()}"]
        horas_complejidad = (horas_base + horas_sedes) * factor
        total = _redondear(horas_base + horas_sedes + horas_complejidad)

        desglose = {
            "horas_por_la_norma": str(_redondear(constantes["horas_base"])),
            "horas_por_empleados": str(_redondear(empleados * constantes["horas_por_empleado"])),
            "horas_por_sedes_adicionales": str(_redondear(horas_sedes)),
            "factor_complejidad": str(factor),
            "horas_por_complejidad": str(_redondear(horas_complejidad)),
            "total_sin_ajuste": str(total),
        }
        return total, desglose

    async def calcular(
        self, id_solicitud: UUID, variables: dict, usuario: dict, recalculo: bool = False
    ) -> dict:
        """SOL-062 (primer cálculo) y SOL-063 (recalcular con otras variables)."""
        solicitud = await self._solicitud(id_solicitud, usuario)
        anterior = await self._ultimo(id_solicitud)
        self._exigir_desbloqueado(anterior)

        if anterior and not recalculo:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"La solicitud ya tiene un cálculo (versión {anterior['version']}). "
                    "Para cambiarlo use el recálculo."
                ),
            )

        # Lo que no se indique se toma de la propia solicitud (SOL-061).
        entradas = {
            "numero_empleados": variables.get("numero_empleados", solicitud.get("numero_empleados") or 0),
            "numero_sedes": variables.get("numero_sedes", solicitud.get("numero_sedes") or 1),
            "complejidad": variables.get("complejidad") or "Media",
            "observaciones": variables.get("observaciones"),
        }

        constantes = await self.variables_de_norma(solicitud.get("id_norma"))
        horas, desglose = self.aplicar_formula(entradas, constantes)
        desglose["constantes"] = {k: str(v) for k, v in constantes.items()}

        version = (anterior["version"] + 1) if anterior else 1
        resultado = await self.db.execute(
            text(f"""
                INSERT INTO calculo_auditoria (
                    id_solicitud, version, variables, desglose,
                    horas_base, resultado_horas, ajuste_horas,
                    estado, validado, bloqueado, usuario_calculo, fecha_calculo
                )
                VALUES (
                    :id_solicitud, :version,
                    CAST(CAST(:variables AS TEXT) AS JSONB),
                    CAST(CAST(:desglose AS TEXT) AS JSONB),
                    :horas, :horas, 0,
                    :estado, FALSE, FALSE, :usuario, CURRENT_TIMESTAMP
                )
                RETURNING {COLUMNAS};
            """),
            {
                "id_solicitud": str(id_solicitud),
                "version": version,
                "variables": json.dumps(entradas, ensure_ascii=False, default=str),
                "desglose": json.dumps(desglose, ensure_ascii=False),
                "horas": str(horas),
                "estado": ESTADO_BORRADOR,
                "usuario": str(usuario["id_usuario"]),
            },
        )
        calculo = dict(resultado.mappings().first())

        await bitacora.registrar(
            self.db, id_solicitud,
            "Recálculo del tiempo de auditoría" if recalculo else "Cálculo del tiempo de auditoría",
            usuario, {"version": version, "horas": str(horas), "variables": entradas},
        )
        await self.db.commit()
        return calculo

    # ========================================================
    # SOL-064 / SOL-067 · CONSULTAR
    # ========================================================

    async def consultar(self, id_solicitud: UUID, usuario: dict) -> dict:
        await self._solicitud(id_solicitud, usuario)
        calculo = await self._ultimo(id_solicitud)
        if not calculo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La solicitud todavía no tiene un cálculo de tiempo.",
            )
        return calculo

    async def historial(self, id_solicitud: UUID, usuario: dict) -> list[dict]:
        """SOL-067: todas las versiones, con quién las hizo."""
        await self._solicitud(id_solicitud, usuario)
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_CON_ALIAS},
                       COALESCE(u.nombre, u.correo) AS calculado_por
                FROM calculo_auditoria c
                LEFT JOIN usuario u ON u.id_usuario = c.usuario_calculo
                WHERE c.id_solicitud = :id_solicitud
                ORDER BY c.version;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    # ========================================================
    # SOL-065 · AJUSTE JUSTIFICADO
    # ========================================================

    async def ajustar(
        self, id_solicitud: UUID, horas_ajuste, justificacion: str, usuario: dict
    ) -> dict:
        await self._solicitud(id_solicitud, usuario)
        calculo = await self.consultar(id_solicitud, usuario)
        self._exigir_desbloqueado(calculo)

        ajuste = _decimal(horas_ajuste)
        base = _decimal(calculo["horas_base"])
        total = base + ajuste
        if total <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El ajuste dejaría la auditoría en cero horas o menos.",
            )

        resultado = await self.db.execute(
            text(f"""
                UPDATE calculo_auditoria
                SET ajuste_horas = :ajuste,
                    justificacion_ajuste = :justificacion,
                    resultado_horas = :total,
                    usuario_ajuste = :usuario,
                    estado = :estado,
                    validado = FALSE,
                    usuario_validacion = NULL,
                    fecha_validacion = NULL
                WHERE id_calculo = :id_calculo
                RETURNING {COLUMNAS};
            """),
            {
                "ajuste": str(ajuste),
                "justificacion": justificacion,
                "total": str(_redondear(total)),
                "usuario": str(usuario["id_usuario"]),
                "estado": ESTADO_BORRADOR,
                "id_calculo": str(calculo["id_calculo"]),
            },
        )
        ajustado = dict(resultado.mappings().first())

        await bitacora.registrar(
            self.db, id_solicitud, "Ajuste del tiempo de auditoría", usuario,
            {"ajuste_horas": str(ajuste), "justificacion": justificacion,
             "total": str(_redondear(total))},
        )
        await self.db.commit()
        return ajustado

    # ========================================================
    # SOL-066 · VARIABLES BASE DE LA NORMA
    # ========================================================

    async def guardar_variables_norma(
        self, id_norma: UUID, valores: dict, usuario: dict
    ) -> list[dict]:
        desconocidas = [k for k in valores if k not in VARIABLES_BASE]
        if desconocidas:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Variables no reconocidas: " + ", ".join(desconocidas) +
                    ". Se admiten: " + ", ".join(VARIABLES_BASE)
                ),
            )

        for nombre, valor in valores.items():
            await self.db.execute(
                text("""
                    UPDATE variables_norma
                    SET valor = :valor,
                        actualizado_por = :usuario,
                        fecha_actualizacion = CURRENT_TIMESTAMP
                    WHERE id_norma = :id_norma AND nom_variable = :nombre;
                """),
                {
                    "valor": str(_decimal(valor)),
                    "usuario": str(usuario["id_usuario"]),
                    "id_norma": str(id_norma),
                    "nombre": nombre,
                },
            )
            await self.db.execute(
                text("""
                    INSERT INTO variables_norma (
                        id_norma, nom_variable, valor, actualizado_por, fecha_actualizacion
                    )
                    SELECT :id_norma, :nombre, :valor, :usuario, CURRENT_TIMESTAMP
                    WHERE NOT EXISTS (
                        SELECT 1 FROM variables_norma
                        WHERE id_norma = :id_norma AND nom_variable = :nombre
                    );
                """),
                {
                    "id_norma": str(id_norma),
                    "nombre": nombre,
                    "valor": str(_decimal(valor)),
                    "usuario": str(usuario["id_usuario"]),
                },
            )

        await self.db.commit()
        return await self.listar_variables_norma(id_norma)

    async def listar_variables_norma(self, id_norma: UUID) -> list[dict]:
        constantes = await self.variables_de_norma(id_norma)
        resultado = await self.db.execute(
            text("""
                SELECT nom_variable, valor, descripcion, fecha_actualizacion
                FROM variables_norma WHERE id_norma = :id_norma;
            """),
            {"id_norma": str(id_norma)},
        )
        guardadas = {f["nom_variable"]: dict(f) for f in resultado.mappings().all()}
        return [
            {
                "nom_variable": nombre,
                "valor": str(valor),
                "origen": "Norma" if nombre in guardadas else "Valor de serie",
                "fecha_actualizacion": guardadas.get(nombre, {}).get("fecha_actualizacion"),
            }
            for nombre, valor in constantes.items()
        ]

    # ========================================================
    # SOL-069 / SOL-070 · VALIDAR Y BLOQUEAR
    # ========================================================

    async def validar(self, id_solicitud: UUID, usuario: dict) -> dict:
        """SOL-069: deja el cálculo listo para asignar auditores."""
        await self._solicitud(id_solicitud, usuario)
        calculo = await self.consultar(id_solicitud, usuario)
        self._exigir_desbloqueado(calculo)

        problemas = []
        if _decimal(calculo["resultado_horas"]) <= 0:
            problemas.append("El resultado no puede ser cero horas.")
        if _decimal(calculo["ajuste_horas"]) != 0 and not calculo["justificacion_ajuste"]:
            problemas.append("El ajuste manual no tiene justificación escrita.")
        if problemas:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El cálculo no se puede validar: " + " ".join(problemas),
            )

        resultado = await self.db.execute(
            text(f"""
                UPDATE calculo_auditoria
                SET validado = TRUE,
                    estado = :estado,
                    usuario_validacion = :usuario,
                    fecha_validacion = CURRENT_TIMESTAMP
                WHERE id_calculo = :id_calculo
                RETURNING {COLUMNAS};
            """),
            {
                "estado": ESTADO_VALIDADO,
                "usuario": str(usuario["id_usuario"]),
                "id_calculo": str(calculo["id_calculo"]),
            },
        )
        validado = dict(resultado.mappings().first())

        await bitacora.registrar(
            self.db, id_solicitud, "Cálculo validado", usuario,
            {"version": calculo["version"], "horas": str(calculo["resultado_horas"])},
        )
        await self.db.commit()
        return validado

    async def bloquear(self, id_solicitud: UUID, usuario: dict, bloquear: bool = True) -> dict:
        """SOL-070: tras la aprobación, el cálculo deja de admitir cambios."""
        await self._solicitud(id_solicitud, usuario)
        calculo = await self.consultar(id_solicitud, usuario)

        if bloquear and not calculo["validado"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Primero hay que validar el cálculo (SOL-069).",
            )

        resultado = await self.db.execute(
            text(f"""
                UPDATE calculo_auditoria
                SET bloqueado = :bloqueado,
                    estado = :estado,
                    fecha_bloqueo = CASE WHEN :bloqueado THEN CURRENT_TIMESTAMP ELSE NULL END
                WHERE id_calculo = :id_calculo
                RETURNING {COLUMNAS};
            """),
            {
                "bloqueado": bloquear,
                "estado": ESTADO_BLOQUEADO if bloquear else ESTADO_VALIDADO,
                "id_calculo": str(calculo["id_calculo"]),
            },
        )
        actualizado = dict(resultado.mappings().first())

        await bitacora.registrar(
            self.db, id_solicitud,
            "Cálculo bloqueado tras la aprobación" if bloquear else "Cálculo desbloqueado",
            usuario, {"version": calculo["version"]},
        )
        await self.db.commit()
        return actualizado
