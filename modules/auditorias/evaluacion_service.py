"""
M7 — AUDITORÍAS
Evaluación por requisito (AUT-011 a AUT-020).

Cada requisito de la norma (`variable_requisito`) se evalúa una vez por
auditoría y queda en `evaluacion_requisito` con uno de tres resultados que
impone la propia base: CUMPLE, NO_CUMPLE o NO_APLICA.

El autoguardado de AUT-012 es justo eso: registrar y editar son la misma
operación mientras la evaluación siga en borrador, así que la pantalla puede
guardar mientras el auditor escribe sin crear filas repetidas.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.auditorias.auditoria_service import AuditoriaService

RESULTADO_CUMPLE = "CUMPLE"
RESULTADO_NO_CUMPLE = "NO_CUMPLE"
RESULTADO_NO_APLICA = "NO_APLICA"
RESULTADOS = (RESULTADO_CUMPLE, RESULTADO_NO_CUMPLE, RESULTADO_NO_APLICA)

ESTADO_BORRADOR = "Borrador"
ESTADO_REGISTRADA = "Registrada"

COLUMNAS = """
    id_evaluacion, id_auditoria, id_variable, resultado,
    observacion, comentario_tecnico, estado, id_usuario, fecha_evaluacion
"""


class EvaluacionService:
    """Evaluación de los requisitos de la norma durante la auditoría."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.auditorias = AuditoriaService(db)

    async def _evaluacion(self, id_auditoria: UUID, id_evaluacion: UUID) -> dict:
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS} FROM evaluacion_requisito
                WHERE id_evaluacion = :id AND id_auditoria = :id_auditoria;
            """),
            {"id": str(id_evaluacion), "id_auditoria": str(id_auditoria)},
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La evaluación no existe para esta auditoría.",
            )
        return dict(fila)

    @staticmethod
    def _validar_resultado(resultado: str) -> str:
        if resultado not in RESULTADOS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Resultado no válido. Se aceptan: {', '.join(RESULTADOS)}.",
            )
        return resultado

    # ========================================================
    # AUT-014 · REQUISITOS DE CONTROL DE LA NORMA
    # ========================================================

    async def requisitos_de_la_auditoria(self, id_auditoria: UUID) -> list[dict]:
        """Los requisitos de la norma de la solicitud, con su evaluación si la hay."""
        await self.auditorias.obtener(id_auditoria)
        resultado = await self.db.execute(
            text("""
                SELECT v.id_variable, v.numeral, v.descripcion,
                       e.id_evaluacion, e.resultado, e.observacion,
                       e.comentario_tecnico, e.estado, e.fecha_evaluacion
                FROM auditoria a
                JOIN solicitud s ON s.id_solicitud = a.id_solicitud
                JOIN variable_requisito v ON v.id_norma = s.id_norma
                LEFT JOIN evaluacion_requisito e
                       ON e.id_variable = v.id_variable AND e.id_auditoria = a.id_auditoria
                WHERE a.id_auditoria = :id_auditoria
                ORDER BY v.numeral;
            """),
            {"id_auditoria": str(id_auditoria)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def registrar_requisito(
        self, id_auditoria: UUID, numeral: str, descripcion: str, usuario: dict
    ) -> dict:
        """
        AUT-014: añade un requisito de control a la norma de esta auditoría
        cuando el catálogo no lo tenía.
        """
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)

        resultado = await self.db.execute(
            text("""
                INSERT INTO variable_requisito (id_norma, numeral, descripcion)
                SELECT s.id_norma, :numeral, :descripcion
                FROM solicitud s
                WHERE s.id_solicitud = :id_solicitud
                RETURNING id_variable, id_norma, numeral, descripcion;
            """),
            {
                "numeral": numeral,
                "descripcion": descripcion,
                "id_solicitud": str(auditoria["id_solicitud"]),
            },
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La solicitud de esta auditoría no tiene norma asociada.",
            )
        await self.db.commit()
        return dict(fila)

    # ========================================================
    # AUT-011 / AUT-012 · REGISTRAR Y EDITAR (AUTOGUARDADO)
    # ========================================================

    async def guardar(
        self,
        id_auditoria: UUID,
        id_variable: UUID,
        resultado_evaluacion: str,
        usuario: dict,
        observacion: str | None = None,
        comentario_tecnico: str | None = None,
        definitiva: bool = False,
    ) -> dict:
        """
        AUT-011 la primera vez y AUT-012 las siguientes.

        `definitiva=True` la deja Registrada: a partir de ahí no se edita ni
        se borra, que es lo que separa el borrador del acta.
        """
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        self._validar_resultado(resultado_evaluacion)

        existente = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS} FROM evaluacion_requisito
                WHERE id_auditoria = :id_auditoria AND id_variable = :id_variable;
            """),
            {"id_auditoria": str(id_auditoria), "id_variable": str(id_variable)},
        )
        actual = existente.mappings().first()

        parametros = {
            "id_auditoria": str(id_auditoria),
            "id_variable": str(id_variable),
            "resultado": resultado_evaluacion,
            "observacion": observacion,
            "comentario": comentario_tecnico,
            "estado": ESTADO_REGISTRADA if definitiva else ESTADO_BORRADOR,
            "usuario": str(usuario["id_usuario"]),
        }

        if actual is None:
            consulta = text(f"""
                INSERT INTO evaluacion_requisito (
                    id_auditoria, id_variable, resultado, observacion,
                    comentario_tecnico, estado, id_usuario, fecha_evaluacion
                )
                VALUES (
                    :id_auditoria, :id_variable, :resultado, :observacion,
                    :comentario, :estado, :usuario, CURRENT_TIMESTAMP
                )
                RETURNING {COLUMNAS};
            """)
        else:
            if actual["estado"] == ESTADO_REGISTRADA:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="La evaluación ya está registrada y no admite cambios.",
                )
            consulta = text(f"""
                UPDATE evaluacion_requisito
                SET resultado = :resultado,
                    observacion = :observacion,
                    comentario_tecnico = :comentario,
                    estado = :estado,
                    id_usuario = :usuario,
                    fecha_evaluacion = CURRENT_TIMESTAMP
                WHERE id_auditoria = :id_auditoria AND id_variable = :id_variable
                RETURNING {COLUMNAS};
            """)

        resultado = await self.db.execute(consulta, parametros)
        await self.db.commit()
        return dict(resultado.mappings().first())

    # ========================================================
    # AUT-013 · ELIMINAR UNA EVALUACIÓN PENDIENTE
    # ========================================================

    async def eliminar(self, id_auditoria: UUID, id_evaluacion: UUID, usuario: dict) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        evaluacion = await self._evaluacion(id_auditoria, id_evaluacion)

        if evaluacion["estado"] == ESTADO_REGISTRADA:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Solo se elimina una evaluación pendiente, no una ya registrada.",
            )

        hallazgos = await self.db.execute(
            text("SELECT COUNT(*) FROM hallazgo WHERE id_evaluacion = :id;"),
            {"id": str(id_evaluacion)},
        )
        if hallazgos.scalar():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La evaluación tiene hallazgos asociados: elimínelos primero.",
            )

        await self.db.execute(
            text("DELETE FROM evaluacion_requisito WHERE id_evaluacion = :id;"),
            {"id": str(id_evaluacion)},
        )
        await self.db.commit()
        return {"mensaje": "Evaluación eliminada.", "evaluacion": evaluacion}

    # ========================================================
    # AUT-015 a AUT-019 · MARCAS Y COMENTARIOS
    # ========================================================

    async def marcar(
        self, id_auditoria: UUID, id_variable: UUID, resultado_evaluacion: str, usuario: dict
    ) -> dict:
        """AUT-015 (Cumple), AUT-016 (No Cumple) y AUT-017 (No Aplica)."""
        return await self.guardar(id_auditoria, id_variable, resultado_evaluacion, usuario)

    async def registrar_comentario(
        self, id_auditoria: UUID, id_evaluacion: UUID, comentario: str, usuario: dict
    ) -> dict:
        """AUT-019: comentario técnico sobre una evaluación."""
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        await self._evaluacion(id_auditoria, id_evaluacion)

        resultado = await self.db.execute(
            text(f"""
                UPDATE evaluacion_requisito
                SET comentario_tecnico = :comentario
                WHERE id_evaluacion = :id
                RETURNING {COLUMNAS};
            """),
            {"comentario": comentario, "id": str(id_evaluacion)},
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    # ========================================================
    # AUT-020 · ESTADO DE LA EVALUACIÓN EN TIEMPO REAL
    # ========================================================

    async def avance(self, id_auditoria: UUID) -> dict:
        await self.auditorias.obtener(id_auditoria)
        resultado = await self.db.execute(
            text("""
                SELECT
                    COUNT(v.id_variable) AS requisitos,
                    COUNT(e.id_evaluacion) AS evaluados,
                    COUNT(*) FILTER (WHERE e.resultado = 'CUMPLE') AS cumple,
                    COUNT(*) FILTER (WHERE e.resultado = 'NO_CUMPLE') AS no_cumple,
                    COUNT(*) FILTER (WHERE e.resultado = 'NO_APLICA') AS no_aplica,
                    COUNT(*) FILTER (WHERE e.estado = 'Borrador') AS en_borrador
                FROM auditoria a
                JOIN solicitud s ON s.id_solicitud = a.id_solicitud
                JOIN variable_requisito v ON v.id_norma = s.id_norma
                LEFT JOIN evaluacion_requisito e
                       ON e.id_variable = v.id_variable AND e.id_auditoria = a.id_auditoria
                WHERE a.id_auditoria = :id_auditoria;
            """),
            {"id_auditoria": str(id_auditoria)},
        )
        fila = dict(resultado.mappings().first() or {})
        requisitos = fila.get("requisitos") or 0
        evaluados = fila.get("evaluados") or 0
        fila["porcentaje_avance"] = round(evaluados * 100 / requisitos, 1) if requisitos else 0.0
        return fila

    # ========================================================
    # AUT-018 · OPORTUNIDAD DE MEJORA DESDE LA EVALUACIÓN
    # ========================================================

    async def registrar_mejora(
        self, id_auditoria: UUID, id_evaluacion: UUID, descripcion: str, usuario: dict
    ) -> dict:
        """
        AUT-018: una mejora (OFI) es un hallazgo de tipo oportunidad; se crea
        aquí para que el auditor no tenga que cambiar de pantalla.
        """
        from modules.auditorias.hallazgo_service import TIPO_MEJORA, HallazgoService

        await self._evaluacion(id_auditoria, id_evaluacion)
        return await HallazgoService(self.db).registrar(
            id_auditoria,
            tipo=TIPO_MEJORA,
            titulo="Oportunidad de mejora",
            descripcion=descripcion,
            usuario=usuario,
            id_evaluacion=id_evaluacion,
        )
