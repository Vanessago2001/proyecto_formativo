"""
M7 — AUDITORÍAS
Informe de auditoría (AUT-041 a AUT-050) y su envío al Comité (AUT-067 a
AUT-070).

El informe nace como borrador con lo que ya hay registrado (evaluaciones,
hallazgos y evidencias), se edita mientras siga en borrador y se finaliza una
sola vez: al finalizarlo se calcula su hash y la auditoría queda bloqueada.
Eso es la inmutabilidad que pide AUT-044, y lo que permite que la firma
(AUT-050) y el envío al Comité (AUT-047) signifiquen algo.
"""

import hashlib
import json
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.pdf import construir_pdf
from modules.auditorias.auditoria_service import AuditoriaService
from modules.auditorias.evaluacion_service import EvaluacionService
from modules.auditorias.hallazgo_service import HallazgoService

ESTADO_BORRADOR = "Borrador"
ESTADO_FINALIZADO = "Finalizado"
ESTADO_FIRMADO = "Firmado"
ESTADO_ENVIADO = "Enviado"

TIPO_PRELIMINAR = "Preliminar"
TIPO_DEFINITIVO = "Definitivo"

COLUMNAS = """
    id_informe, id_auditoria, version, tipo, contenido, url_archivo, estado,
    fecha_generacion, fecha_finalizacion, fecha_envio_comite,
    usuario_generacion, usuario_finalizacion, hash_documento,
    firma_digital, fecha_firma
"""


class InformeService:
    """Borrador, finalización, firma y envío del informe de auditoría."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.auditorias = AuditoriaService(db)

    # ========================================================
    # AYUDANTES
    # ========================================================

    async def _ultimo(self, id_auditoria: UUID) -> dict | None:
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS} FROM informe_auditoria
                WHERE id_auditoria = :id ORDER BY version DESC LIMIT 1;
            """),
            {"id": str(id_auditoria)},
        )
        fila = resultado.mappings().first()
        return dict(fila) if fila else None

    async def obtener(self, id_auditoria: UUID) -> dict:
        informe = await self._ultimo(id_auditoria)
        if not informe:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La auditoría todavía no tiene informe.",
            )
        return informe

    async def _armar_contenido(self, id_auditoria: UUID) -> dict:
        """Lo que se registró durante la auditoría, listo para el informe."""
        auditoria = await self.auditorias.obtener(id_auditoria)
        expediente = await self.auditorias.expediente_previo(id_auditoria)
        avance = await EvaluacionService(self.db).avance(id_auditoria)
        consolidado = await HallazgoService(self.db).consolidado(id_auditoria)
        jornadas = await self.auditorias.jornadas(id_auditoria)

        return {
            "empresa": expediente["empresa"],
            "solicitud": {
                "radicado": expediente["solicitud"].get("numero_radicado"),
                "norma": expediente["alcance"].get("norma"),
                "alcance": expediente["alcance"].get("alcance_certificacion"),
            },
            "auditoria": {
                "estado": auditoria["estado"],
                "fecha_inicio": str(auditoria.get("fecha_inicio") or ""),
                "fecha_fin": str(auditoria.get("fecha_fin") or ""),
                "observaciones_iniciales": auditoria.get("observaciones_iniciales"),
            },
            "evaluacion": avance,
            "hallazgos": consolidado["resumen"],
            "detalle_hallazgos": [
                {
                    "tipo": h["tipo"],
                    "clasificacion": h["clasificacion"],
                    "titulo": h["titulo"],
                    "requisito": h.get("numeral") or h.get("requisito_relacionado"),
                    "evidencias": h["evidencias"],
                }
                for h in consolidado["hallazgos"]
            ],
            "jornadas": {
                "total": jornadas["total_jornadas"],
                "horas_en_campo": jornadas["horas_en_campo"],
            },
        }

    @staticmethod
    def _exigir_borrador(informe: dict) -> None:
        if informe["estado"] != ESTADO_BORRADOR:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El informe está '{informe['estado']}' y ya no se edita.",
            )

    # ========================================================
    # AUT-041 / AUT-043 · GENERAR Y GUARDAR EL BORRADOR
    # ========================================================

    async def generar_borrador(self, id_auditoria: UUID, usuario: dict) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)

        anterior = await self._ultimo(id_auditoria)
        if anterior and anterior["estado"] != ESTADO_BORRADOR:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El informe de esta auditoría ya fue finalizado.",
            )

        contenido = await self._armar_contenido(id_auditoria)
        version = (anterior["version"] + 1) if anterior else 1

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO informe_auditoria (
                    id_auditoria, version, tipo, contenido, estado,
                    fecha_generacion, usuario_generacion
                )
                VALUES (
                    :id_auditoria, :version, :tipo,
                    CAST(CAST(:contenido AS TEXT) AS JSONB),
                    :estado, CURRENT_TIMESTAMP, :usuario
                )
                RETURNING {COLUMNAS};
            """),
            {
                "id_auditoria": str(id_auditoria),
                "version": version,
                "tipo": TIPO_PRELIMINAR,
                "contenido": json.dumps(contenido, ensure_ascii=False, default=str),
                "estado": ESTADO_BORRADOR,
                "usuario": str(usuario["id_usuario"]),
            },
        )
        informe = dict(resultado.mappings().first())
        await self._historial(informe, "Borrador generado", usuario)
        await self.db.commit()
        return informe

    async def guardar_borrador(
        self, id_auditoria: UUID, contenido: dict, usuario: dict
    ) -> dict:
        """AUT-042 (editar en redacción) y AUT-043 (guardar)."""
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        informe = await self.obtener(id_auditoria)
        self._exigir_borrador(informe)

        combinado = {**(informe["contenido"] or {}), **contenido}
        resultado = await self.db.execute(
            text(f"""
                UPDATE informe_auditoria
                SET contenido = CAST(CAST(:contenido AS TEXT) AS JSONB)
                WHERE id_informe = :id
                RETURNING {COLUMNAS};
            """),
            {
                "contenido": json.dumps(combinado, ensure_ascii=False, default=str),
                "id": str(informe["id_informe"]),
            },
        )
        actualizado = dict(resultado.mappings().first())
        await self._historial(actualizado, "Borrador editado", usuario)
        await self.db.commit()
        return actualizado

    async def _historial(self, informe: dict, accion: str, usuario: dict) -> None:
        await self.db.execute(
            text("""
                INSERT INTO historial_informe_auditoria (
                    id_informe, version, estado, contenido_json, url_archivo,
                    observacion_cambio, id_usuario, fecha
                )
                VALUES (
                    :id_informe, :version, :estado,
                    CAST(CAST(:contenido AS TEXT) AS JSONB),
                    :url, :accion, :id_usuario, CURRENT_TIMESTAMP
                );
            """),
            {
                "id_informe": str(informe["id_informe"]),
                "version": informe["version"],
                "estado": informe["estado"],
                "contenido": json.dumps(informe.get("contenido") or {}, ensure_ascii=False, default=str),
                "url": informe.get("url_archivo"),
                "accion": accion,
                "id_usuario": str(usuario["id_usuario"]) if usuario.get("id_usuario") else None,
            },
        )

    # ========================================================
    # AUT-044 · FINALIZAR (INMUTABILIDAD)
    # ========================================================

    async def finalizar(self, id_auditoria: UUID, usuario: dict) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        informe = await self.obtener(id_auditoria)
        self._exigir_borrador(informe)

        pendientes = await self.db.execute(
            text("""
                SELECT COUNT(*) FROM hallazgo
                WHERE id_auditoria = :id AND tipo = 'NO_CONFORMIDAD' AND clasificacion IS NULL;
            """),
            {"id": str(id_auditoria)},
        )
        if pendientes.scalar():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Hay no conformidades sin clasificar como Mayor o Menor.",
            )

        contenido = json.dumps(informe["contenido"] or {}, ensure_ascii=False, sort_keys=True, default=str)
        hash_documento = hashlib.sha256(contenido.encode("utf-8")).hexdigest()

        resultado = await self.db.execute(
            text(f"""
                UPDATE informe_auditoria
                SET estado = :estado,
                    tipo = :tipo,
                    hash_documento = :hash,
                    fecha_finalizacion = CURRENT_TIMESTAMP,
                    usuario_finalizacion = :usuario
                WHERE id_informe = :id
                RETURNING {COLUMNAS};
            """),
            {
                "estado": ESTADO_FINALIZADO,
                "tipo": TIPO_DEFINITIVO,
                "hash": hash_documento,
                "usuario": str(usuario["id_usuario"]),
                "id": str(informe["id_informe"]),
            },
        )
        finalizado = dict(resultado.mappings().first())

        # El informe definitivo congela la auditoría: nada más se registra.
        await self.db.execute(
            text("UPDATE auditoria SET bloqueada = TRUE WHERE id_auditoria = :id;"),
            {"id": str(id_auditoria)},
        )
        await self._historial(finalizado, "Informe finalizado", usuario)
        await self.db.commit()
        return finalizado

    # ========================================================
    # AUT-045 / AUT-046 / AUT-049 · PDF
    # ========================================================

    async def pdf(self, id_auditoria: UUID) -> tuple[bytes, str]:
        informe = await self.obtener(id_auditoria)
        contenido = informe["contenido"] or {}
        empresa = contenido.get("empresa", {})
        solicitud = contenido.get("solicitud", {})
        hallazgos = contenido.get("hallazgos", {})
        evaluacion = contenido.get("evaluacion", {})
        jornadas = contenido.get("jornadas", {})

        campos = [
            ("Radicado de la solicitud", solicitud.get("radicado")),
            ("Empresa auditada", empresa.get("nombre")),
            ("NIT", empresa.get("nit")),
            ("Norma evaluada", solicitud.get("norma")),
            ("Alcance", solicitud.get("alcance")),
            ("Version del informe", informe["version"]),
            ("Estado", informe["estado"]),
            ("Requisitos evaluados", f"{evaluacion.get('evaluados', 0)} de {evaluacion.get('requisitos', 0)}"),
            ("No conformidades mayores", hallazgos.get("no_conformidades_mayores", 0)),
            ("No conformidades menores", hallazgos.get("no_conformidades_menores", 0)),
            ("Observaciones", hallazgos.get("observaciones", 0)),
            ("Oportunidades de mejora", hallazgos.get("oportunidades_de_mejora", 0)),
            ("Jornadas en campo", jornadas.get("total")),
            ("Horas en campo", jornadas.get("horas_en_campo")),
            ("Hash del documento", informe.get("hash_documento") or "Sin finalizar"),
            ("Firmado por", informe.get("firma_digital") or "Sin firmar"),
        ]

        contenido_pdf = construir_pdf(
            titulo="CertiSENA - Informe de auditoria",
            subtitulo=str(empresa.get("nombre") or "Auditoria"),
            campos=campos,
        )
        nombre = f"informe-auditoria-{solicitud.get('radicado') or informe['version']}.pdf"
        return contenido_pdf, nombre

    # ========================================================
    # AUT-050 / AUT-069 · FIRMA DEL AUDITOR
    # ========================================================

    async def firmar(self, id_auditoria: UUID, usuario: dict) -> dict:
        informe = await self.obtener(id_auditoria)

        if informe["estado"] == ESTADO_BORRADOR:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Primero hay que finalizar el informe (AUT-044).",
            )
        if informe.get("firma_digital"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El informe ya está firmado.",
            )

        # La firma ata el hash del documento al usuario que lo firma: si el
        # contenido cambiara, la firma dejaria de corresponder.
        firma = hashlib.sha256(
            f"{informe['hash_documento']}:{usuario['id_usuario']}".encode("utf-8")
        ).hexdigest()

        resultado = await self.db.execute(
            text(f"""
                UPDATE informe_auditoria
                SET firma_digital = :firma,
                    fecha_firma = CURRENT_TIMESTAMP,
                    estado = :estado
                WHERE id_informe = :id
                RETURNING {COLUMNAS};
            """),
            {
                "firma": firma,
                "estado": ESTADO_FIRMADO,
                "id": str(informe["id_informe"]),
            },
        )
        firmado = dict(resultado.mappings().first())
        await self._historial(firmado, "Informe firmado", usuario)
        await self.db.commit()
        return firmado

    # ========================================================
    # AUT-047 / AUT-068 / AUT-070 · ENVÍO AL COMITÉ
    # ========================================================

    async def enviar_al_comite(self, id_auditoria: UUID, usuario: dict) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        informe = await self.obtener(id_auditoria)

        if informe["estado"] == ESTADO_BORRADOR:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se envía al Comité un informe en borrador.",
            )
        if not informe.get("firma_digital"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El informe debe estar firmado antes de enviarlo (AUT-050).",
            )
        if informe.get("fecha_envio_comite"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El informe ya fue enviado al Comité.",
            )

        resultado = await self.db.execute(
            text(f"""
                UPDATE informe_auditoria
                SET fecha_envio_comite = CURRENT_TIMESTAMP,
                    estado = :estado
                WHERE id_informe = :id
                RETURNING {COLUMNAS};
            """),
            {"estado": ESTADO_ENVIADO, "id": str(informe["id_informe"])},
        )
        enviado = dict(resultado.mappings().first())

        # El expediente de la solicitud queda marcado para el Comité (AUT-070).
        await self.db.execute(
            text("""
                UPDATE solicitud SET fecha_envio_comite = CURRENT_TIMESTAMP
                WHERE id_solicitud = :id_solicitud;
            """),
            {"id_solicitud": str(auditoria["id_solicitud"])},
        )
        await self._historial(enviado, "Informe enviado al Comité", usuario)
        await self.db.commit()
        return enviado

    async def confirmar_envio(self, id_auditoria: UUID) -> dict:
        """AUT-068: constancia de que el envío quedó registrado."""
        informe = await self.obtener(id_auditoria)
        return {
            "id_informe": informe["id_informe"],
            "version": informe["version"],
            "estado": informe["estado"],
            "firmado": bool(informe.get("firma_digital")),
            "hash_documento": informe.get("hash_documento"),
            "fecha_envio_comite": informe.get("fecha_envio_comite"),
            "enviado": bool(informe.get("fecha_envio_comite")),
        }

    # ========================================================
    # AUT-048 · CONSULTAR / AUT-067 · VERIFICAR INTEGRIDAD
    # ========================================================

    async def verificar_integridad(self, id_auditoria: UUID) -> dict:
        informe = await self.obtener(id_auditoria)
        if not informe.get("hash_documento"):
            return {"integro": False, "motivo": "El informe aún no está finalizado."}

        contenido = json.dumps(informe["contenido"] or {}, ensure_ascii=False, sort_keys=True, default=str)
        actual = hashlib.sha256(contenido.encode("utf-8")).hexdigest()
        return {
            "id_informe": informe["id_informe"],
            "integro": actual == informe["hash_documento"],
            "hash_registrado": informe["hash_documento"],
            "hash_actual": actual,
            "firma_digital": informe.get("firma_digital"),
        }

    async def historial(self, id_auditoria: UUID) -> list[dict]:
        await self.auditorias.obtener(id_auditoria)
        resultado = await self.db.execute(
            text("""
                SELECT h.id_historial, h.version, h.estado, h.observacion_cambio,
                       h.fecha, COALESCE(u.nombre, u.correo) AS usuario
                FROM historial_informe_auditoria h
                JOIN informe_auditoria i ON i.id_informe = h.id_informe
                LEFT JOIN usuario u ON u.id_usuario = h.id_usuario
                WHERE i.id_auditoria = :id_auditoria
                ORDER BY h.fecha;
            """),
            {"id_auditoria": str(id_auditoria)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]
