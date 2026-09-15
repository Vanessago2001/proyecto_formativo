"""
Flujo de aprobación para los permisos marcados REQ en permisos.xlsx.

REQ significa que el rol puede pedir la acción, pero no ejecutarla por su
cuenta. En lugar de ejecutarse, la acción queda registrada como 'Pendiente'.
Un rol con el permiso concedido (V o SA) la revisa:

  · Aprobar  -> la acción se ejecuta en ese momento, con las mismas
                validaciones que si la hiciera él directamente.
  · Rechazar -> no se ejecuta y queda anotado el motivo.

Cada módulo registra sus acciones con `registrar_accion(...)`, indicando qué
roles pueden aprobarlas y qué función las ejecuta.
"""

import json
from dataclasses import dataclass
from typing import Awaitable, Callable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import _normalize_role_name

ESTADO_PENDIENTE = "Pendiente"
ESTADO_APROBADA = "Aprobada"
ESTADO_RECHAZADA = "Rechazada"

NOMBRES_ROL = {"superadmin": "Super Administrador", "admin": "Administrador"}


@dataclass(frozen=True)
class AccionAprobable:
    codigo: str
    descripcion: str
    aprobadores: tuple[str, ...]
    ejecutar: Callable[[AsyncSession, dict], Awaitable[dict]]


_ACCIONES: dict[str, AccionAprobable] = {}


def registrar_accion(codigo: str, descripcion: str, aprobadores: list[str], ejecutar) -> None:
    _ACCIONES[codigo] = AccionAprobable(codigo, descripcion, tuple(aprobadores), ejecutar)


def obtener_accion(codigo: str) -> AccionAprobable:
    if codigo not in _ACCIONES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La acción {codigo} no admite aprobación.",
        )
    return _ACCIONES[codigo]


COLUMNAS = """
    a.id_aprobacion, a.codigo_permiso, a.descripcion, a.detalle, a.id_empresa,
    CAST(a.datos AS TEXT) AS datos, a.estado, a.id_solicitante, a.fecha_solicitud,
    a.id_revisor, a.fecha_revision, a.observacion_revision,
    e.nombre AS empresa_nombre, us.nombre AS solicitante_nombre, ur.nombre AS revisor_nombre
"""

ORIGEN = """
    FROM aprobacion_pendiente a
    LEFT JOIN empresa e ON e.id_empresa = a.id_empresa
    LEFT JOIN usuario us ON us.id_usuario = a.id_solicitante
    LEFT JOIN usuario ur ON ur.id_usuario = a.id_revisor
"""


def _fila(fila) -> dict:
    datos = dict(fila)
    if isinstance(datos.get("datos"), str):
        datos["datos"] = json.loads(datos["datos"])
    return datos


class AprobacionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def solicitar(
        self,
        codigo: str,
        id_empresa: str | None,
        datos: dict,
        detalle: str,
        usuario: dict,
    ) -> dict:
        """Registra la acción como pendiente. No la ejecuta."""
        definicion = obtener_accion(codigo)
        datos_json = json.dumps(datos, sort_keys=True)

        repetida = await self.db.execute(
            text("""
                SELECT COUNT(*) FROM aprobacion_pendiente
                WHERE codigo_permiso = :codigo
                  AND id_empresa = :id_empresa
                  AND datos = CAST(CAST(:datos AS TEXT) AS JSONB)
                  AND estado = :pendiente;
            """),
            {"codigo": codigo, "id_empresa": id_empresa, "datos": datos_json, "pendiente": ESTADO_PENDIENTE},
        )
        if repetida.scalar():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya hay una solicitud pendiente de aprobación para esta acción.",
            )

        resultado = await self.db.execute(
            text("""
                INSERT INTO aprobacion_pendiente (
                    codigo_permiso, descripcion, detalle, id_empresa, datos, estado, id_solicitante
                )
                VALUES (
                    :codigo, :descripcion, :detalle, :id_empresa,
                    CAST(CAST(:datos AS TEXT) AS JSONB), :pendiente, :id_solicitante
                )
                RETURNING id_aprobacion, codigo_permiso, descripcion, detalle, id_empresa,
                          CAST(datos AS TEXT) AS datos, estado, id_solicitante, fecha_solicitud;
            """),
            {
                "codigo": codigo,
                "descripcion": definicion.descripcion,
                "detalle": detalle[:255],
                "id_empresa": id_empresa,
                "datos": datos_json,
                "pendiente": ESTADO_PENDIENTE,
                "id_solicitante": str(usuario.get("id_usuario")),
            },
        )
        aprobacion = _fila(resultado.mappings().first())
        await self.db.commit()
        return aprobacion

    async def listar(self, usuario: dict, estado: str | None = None) -> list[dict]:
        """Quien aprueba ve todas; el Auxiliar solo las que él pidió."""
        condiciones = ["1 = 1"]
        parametros: dict = {}

        if estado:
            condiciones.append("a.estado = :estado")
            parametros["estado"] = estado

        if _normalize_role_name(usuario.get("role_name")) not in NOMBRES_ROL:
            condiciones.append("a.id_solicitante = :id_usuario")
            parametros["id_usuario"] = str(usuario.get("id_usuario"))

        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS}
                {ORIGEN}
                WHERE {' AND '.join(condiciones)}
                ORDER BY a.fecha_solicitud DESC
                LIMIT 200;
            """),
            parametros,
        )
        return [_fila(fila) for fila in resultado.mappings().all()]

    async def _pendiente_para(self, id_aprobacion: UUID, usuario: dict) -> tuple[dict, AccionAprobable]:
        resultado = await self.db.execute(
            text(f"SELECT {COLUMNAS} {ORIGEN} WHERE a.id_aprobacion = :id_aprobacion;"),
            {"id_aprobacion": str(id_aprobacion)},
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La solicitud de aprobación no existe.")

        aprobacion = _fila(fila)
        if aprobacion["estado"] != ESTADO_PENDIENTE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La solicitud ya fue revisada: está {aprobacion['estado']}.",
            )

        definicion = obtener_accion(aprobacion["codigo_permiso"])
        if _normalize_role_name(usuario.get("role_name")) not in definicion.aprobadores:
            quienes = " o ".join(NOMBRES_ROL.get(r, r) for r in definicion.aprobadores)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Solo {quienes} puede aprobar o rechazar {definicion.codigo} ({definicion.descripcion}).",
            )

        return aprobacion, definicion

    async def _cerrar(self, id_aprobacion: UUID, estado: str, usuario: dict, observacion: str | None) -> dict:
        resultado = await self.db.execute(
            text("""
                UPDATE aprobacion_pendiente
                SET estado = :estado,
                    id_revisor = :id_revisor,
                    fecha_revision = NOW(),
                    observacion_revision = :observacion
                WHERE id_aprobacion = :id_aprobacion
                  AND estado = :pendiente
                RETURNING id_aprobacion, codigo_permiso, descripcion, detalle, id_empresa,
                          CAST(datos AS TEXT) AS datos, estado, id_solicitante, fecha_solicitud,
                          id_revisor, fecha_revision, observacion_revision;
            """),
            {
                "estado": estado,
                "id_revisor": str(usuario.get("id_usuario")),
                "observacion": observacion,
                "id_aprobacion": str(id_aprobacion),
                "pendiente": ESTADO_PENDIENTE,
            },
        )
        aprobacion = _fila(resultado.mappings().first())
        await self.db.commit()
        return aprobacion

    async def aprobar(self, id_aprobacion: UUID, usuario: dict) -> dict:
        """Ejecuta la acción pedida y marca la solicitud como aprobada."""
        aprobacion, definicion = await self._pendiente_para(id_aprobacion, usuario)

        # Si la acción ya no es válida (por ejemplo, alguien inactivó la empresa
        # mientras tanto), la validación lanza el error y la solicitud sigue
        # pendiente para que se rechace con el motivo.
        resultado = await definicion.ejecutar(self.db, aprobacion)

        cerrada = await self._cerrar(id_aprobacion, ESTADO_APROBADA, usuario, None)
        return {"aprobacion": cerrada, "resultado": resultado}

    async def rechazar(self, id_aprobacion: UUID, usuario: dict, observacion: str) -> dict:
        await self._pendiente_para(id_aprobacion, usuario)
        return await self._cerrar(id_aprobacion, ESTADO_RECHAZADA, usuario, observacion)
