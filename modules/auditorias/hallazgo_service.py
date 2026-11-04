"""
M7 — AUDITORÍAS
Hallazgos de la auditoría (AUT-021 a AUT-030).

Un hallazgo es lo que el auditor encuentra y debe quedar escrito. La base
admite tres tipos —no conformidad, observación y oportunidad de mejora— y,
para las no conformidades, una clasificación Mayor o Menor.

Cada cambio queda en `historial_hallazgo`: un hallazgo no se reescribe en
silencio, porque de él dependen el informe y las acciones correctivas.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.auditorias.auditoria_service import AuditoriaService

TIPO_NO_CONFORMIDAD = "NO_CONFORMIDAD"
TIPO_OBSERVACION = "OBSERVACION"
TIPO_MEJORA = "OPORTUNIDAD_MEJORA"
TIPOS = (TIPO_NO_CONFORMIDAD, TIPO_OBSERVACION, TIPO_MEJORA)

CLASIFICACION_MAYOR = "MAYOR"
CLASIFICACION_MENOR = "MENOR"
CLASIFICACIONES = (CLASIFICACION_MAYOR, CLASIFICACION_MENOR)

ESTADO_PENDIENTE = "Pendiente"
ESTADO_CONFIRMADO = "Confirmado"
ESTADO_CERRADO = "Cerrado"

COLUMNAS = """
    id_hallazgo, id_auditoria, id_evaluacion, tipo, clasificacion,
    titulo, descripcion, requisito_relacionado, estado,
    fecha_registro, fecha_cierre, usuario_registra
"""


class HallazgoService:
    """Registro, clasificación y consulta de los hallazgos."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.auditorias = AuditoriaService(db)

    async def _hallazgo(self, id_auditoria: UUID, id_hallazgo: UUID) -> dict:
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS} FROM hallazgo
                WHERE id_hallazgo = :id AND id_auditoria = :id_auditoria;
            """),
            {"id": str(id_hallazgo), "id_auditoria": str(id_auditoria)},
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El hallazgo no existe para esta auditoría.",
            )
        return dict(fila)

    async def _historial(
        self,
        id_hallazgo: UUID,
        accion: str,
        usuario: dict,
        estado_anterior: str | None = None,
        estado_nuevo: str | None = None,
        clasificacion_anterior: str | None = None,
        clasificacion_nueva: str | None = None,
        observacion: str | None = None,
    ) -> None:
        await self.db.execute(
            text("""
                INSERT INTO historial_hallazgo (
                    id_hallazgo, accion, estado_anterior, estado_nuevo,
                    clasificacion_anterior, clasificacion_nueva,
                    observacion, id_usuario, fecha
                )
                VALUES (
                    :id_hallazgo, :accion, :estado_anterior, :estado_nuevo,
                    :clasificacion_anterior, :clasificacion_nueva,
                    :observacion, :id_usuario, CURRENT_TIMESTAMP
                );
            """),
            {
                "id_hallazgo": str(id_hallazgo),
                "accion": accion,
                "estado_anterior": estado_anterior,
                "estado_nuevo": estado_nuevo,
                "clasificacion_anterior": clasificacion_anterior,
                "clasificacion_nueva": clasificacion_nueva,
                "observacion": observacion,
                "id_usuario": str(usuario["id_usuario"]) if usuario.get("id_usuario") else None,
            },
        )

    @staticmethod
    def _validar(tipo: str, clasificacion: str | None) -> None:
        if tipo not in TIPOS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tipo de hallazgo no válido. Se aceptan: {', '.join(TIPOS)}.",
            )
        if clasificacion is not None and clasificacion not in CLASIFICACIONES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Clasificación no válida. Se aceptan: {', '.join(CLASIFICACIONES)}.",
            )
        if tipo != TIPO_NO_CONFORMIDAD and clasificacion is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Solo las no conformidades se clasifican en Mayor o Menor.",
            )

    # ========================================================
    # AUT-021 / AUT-025 / AUT-026 / AUT-027 · REGISTRAR
    # ========================================================

    async def registrar(
        self,
        id_auditoria: UUID,
        tipo: str,
        titulo: str,
        descripcion: str,
        usuario: dict,
        clasificacion: str | None = None,
        requisito_relacionado: str | None = None,
        id_evaluacion: UUID | None = None,
    ) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        self._validar(tipo, clasificacion)

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO hallazgo (
                    id_auditoria, id_evaluacion, tipo, clasificacion, titulo,
                    descripcion, requisito_relacionado, estado,
                    fecha_registro, usuario_registra
                )
                VALUES (
                    :id_auditoria, :id_evaluacion, :tipo, :clasificacion, :titulo,
                    :descripcion, :requisito, :estado, CURRENT_TIMESTAMP, :usuario
                )
                RETURNING {COLUMNAS};
            """),
            {
                "id_auditoria": str(id_auditoria),
                "id_evaluacion": str(id_evaluacion) if id_evaluacion else None,
                "tipo": tipo,
                "clasificacion": clasificacion,
                "titulo": titulo,
                "descripcion": descripcion,
                "requisito": requisito_relacionado,
                "estado": ESTADO_PENDIENTE,
                "usuario": str(usuario["id_usuario"]),
            },
        )
        hallazgo = dict(resultado.mappings().first())

        await self._historial(
            hallazgo["id_hallazgo"], "Hallazgo registrado", usuario,
            None, ESTADO_PENDIENTE, None, clasificacion,
        )
        await self.db.commit()
        return hallazgo

    # ========================================================
    # AUT-022 · EDITAR
    # ========================================================

    async def editar(
        self, id_auditoria: UUID, id_hallazgo: UUID, cambios: dict, usuario: dict
    ) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        hallazgo = await self._hallazgo(id_auditoria, id_hallazgo)

        if hallazgo["estado"] == ESTADO_CERRADO:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Un hallazgo cerrado ya no se edita.",
            )

        tipo = cambios.get("tipo", hallazgo["tipo"])
        clasificacion = cambios.get("clasificacion", hallazgo["clasificacion"])
        self._validar(tipo, clasificacion)

        resultado = await self.db.execute(
            text(f"""
                UPDATE hallazgo
                SET tipo = :tipo,
                    clasificacion = :clasificacion,
                    titulo = COALESCE(:titulo, titulo),
                    descripcion = COALESCE(:descripcion, descripcion),
                    requisito_relacionado = COALESCE(:requisito, requisito_relacionado)
                WHERE id_hallazgo = :id
                RETURNING {COLUMNAS};
            """),
            {
                "tipo": tipo,
                "clasificacion": clasificacion,
                "titulo": cambios.get("titulo"),
                "descripcion": cambios.get("descripcion"),
                "requisito": cambios.get("requisito_relacionado"),
                "id": str(id_hallazgo),
            },
        )
        editado = dict(resultado.mappings().first())

        await self._historial(
            id_hallazgo, "Hallazgo editado", usuario,
            hallazgo["estado"], editado["estado"],
            hallazgo["clasificacion"], editado["clasificacion"],
        )
        await self.db.commit()
        return editado

    # ========================================================
    # AUT-023 · ELIMINAR UN HALLAZGO PENDIENTE
    # ========================================================

    async def eliminar(self, id_auditoria: UUID, id_hallazgo: UUID, usuario: dict) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        hallazgo = await self._hallazgo(id_auditoria, id_hallazgo)

        if hallazgo["estado"] != ESTADO_PENDIENTE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El hallazgo está '{hallazgo['estado']}' y ya no se puede eliminar.",
            )

        evidencias = await self.db.execute(
            text("SELECT COUNT(*) FROM evidencia WHERE id_hallazgo = :id;"),
            {"id": str(id_hallazgo)},
        )
        if evidencias.scalar():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El hallazgo tiene evidencias asociadas: quítelas primero.",
            )

        await self._historial(id_hallazgo, "Hallazgo eliminado", usuario, ESTADO_PENDIENTE, None)
        await self.db.execute(
            text("DELETE FROM hallazgo WHERE id_hallazgo = :id;"), {"id": str(id_hallazgo)}
        )
        await self.db.commit()
        return {"mensaje": "Hallazgo eliminado.", "hallazgo": hallazgo}

    # ========================================================
    # AUT-024 · CLASIFICAR
    # ========================================================

    async def clasificar(
        self, id_auditoria: UUID, id_hallazgo: UUID, clasificacion: str, usuario: dict
    ) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        hallazgo = await self._hallazgo(id_auditoria, id_hallazgo)

        if hallazgo["tipo"] != TIPO_NO_CONFORMIDAD:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Solo las no conformidades se clasifican en Mayor o Menor.",
            )
        if clasificacion not in CLASIFICACIONES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Clasificación no válida. Se aceptan: {', '.join(CLASIFICACIONES)}.",
            )

        resultado = await self.db.execute(
            text(f"""
                UPDATE hallazgo
                SET clasificacion = :clasificacion, estado = :estado
                WHERE id_hallazgo = :id
                RETURNING {COLUMNAS};
            """),
            {"clasificacion": clasificacion, "estado": ESTADO_CONFIRMADO, "id": str(id_hallazgo)},
        )
        clasificado = dict(resultado.mappings().first())

        await self._historial(
            id_hallazgo, "Hallazgo clasificado", usuario,
            hallazgo["estado"], ESTADO_CONFIRMADO,
            hallazgo["clasificacion"], clasificacion,
        )
        await self.db.commit()
        return clasificado

    # ========================================================
    # AUT-028 · ASOCIAR EL REQUISITO
    # ========================================================

    async def asociar_requisito(
        self, id_auditoria: UUID, id_hallazgo: UUID, requisito: str, usuario: dict
    ) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        await self._hallazgo(id_auditoria, id_hallazgo)

        resultado = await self.db.execute(
            text(f"""
                UPDATE hallazgo SET requisito_relacionado = :requisito
                WHERE id_hallazgo = :id
                RETURNING {COLUMNAS};
            """),
            {"requisito": requisito, "id": str(id_hallazgo)},
        )
        await self._historial(id_hallazgo, "Requisito relacionado", usuario, observacion=requisito)
        await self.db.commit()
        return dict(resultado.mappings().first())

    # ========================================================
    # AUT-029 / AUT-030 · CONSOLIDADO
    # ========================================================

    async def listar(self, id_auditoria: UUID, tipo: str | None = None) -> list[dict]:
        await self.auditorias.obtener(id_auditoria)
        resultado = await self.db.execute(
            text("""
                SELECT h.id_hallazgo, h.tipo, h.clasificacion, h.titulo, h.descripcion,
                       h.requisito_relacionado, h.estado, h.fecha_registro, h.fecha_cierre,
                       v.numeral, v.descripcion AS requisito_descripcion,
                       COALESCE(u.nombre, u.correo) AS registrado_por,
                       (SELECT COUNT(*) FROM evidencia ev WHERE ev.id_hallazgo = h.id_hallazgo)
                           AS evidencias
                FROM hallazgo h
                LEFT JOIN evaluacion_requisito e ON e.id_evaluacion = h.id_evaluacion
                LEFT JOIN variable_requisito v ON v.id_variable = e.id_variable
                LEFT JOIN usuario u ON u.id_usuario = h.usuario_registra
                WHERE h.id_auditoria = :id_auditoria
                  AND (CAST(:tipo AS VARCHAR) IS NULL OR h.tipo = CAST(:tipo AS VARCHAR))
                ORDER BY h.fecha_registro;
            """),
            {"id_auditoria": str(id_auditoria), "tipo": tipo},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def consolidado(self, id_auditoria: UUID) -> dict:
        """AUT-029 y AUT-030: lo que se lleva al informe preliminar."""
        hallazgos = await self.listar(id_auditoria)
        resumen = {
            "no_conformidades_mayores": 0,
            "no_conformidades_menores": 0,
            "observaciones": 0,
            "oportunidades_de_mejora": 0,
        }
        for h in hallazgos:
            if h["tipo"] == TIPO_NO_CONFORMIDAD:
                if h["clasificacion"] == CLASIFICACION_MAYOR:
                    resumen["no_conformidades_mayores"] += 1
                else:
                    resumen["no_conformidades_menores"] += 1
            elif h["tipo"] == TIPO_OBSERVACION:
                resumen["observaciones"] += 1
            else:
                resumen["oportunidades_de_mejora"] += 1

        return {"total": len(hallazgos), "resumen": resumen, "hallazgos": hallazgos}

    async def historial(self, id_auditoria: UUID, id_hallazgo: UUID) -> list[dict]:
        await self._hallazgo(id_auditoria, id_hallazgo)
        resultado = await self.db.execute(
            text("""
                SELECT h.id_historial, h.accion, h.estado_anterior, h.estado_nuevo,
                       h.clasificacion_anterior, h.clasificacion_nueva, h.observacion,
                       h.fecha, COALESCE(u.nombre, u.correo) AS usuario
                FROM historial_hallazgo h
                LEFT JOIN usuario u ON u.id_usuario = h.id_usuario
                WHERE h.id_hallazgo = :id
                ORDER BY h.fecha;
            """),
            {"id": str(id_hallazgo)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]
