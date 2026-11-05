"""Generación, firma PAdES y descarga de actas definitivas del Comité."""

import asyncio
import hashlib
import hmac
import json
import os
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4
from xml.sax.saxutils import escape

from fastapi import HTTPException, status
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.logger import logger
from modules.certificados.firma_pades import FirmaPadesError, firmar_pdf_pades
from modules.certificados.firma_service import FirmaService
from modules.solicitudes import estado_solicitud as estados


class ComiteActaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _ruta(id_acta: UUID | str, firmada: bool = False) -> Path:
        sufijo = "-firmada" if firmada else ""
        return Path(settings.COMITE_ACTAS_STORAGE_DIR).expanduser().resolve() / f"{id_acta}{sufijo}.pdf"

    @staticmethod
    def _crear_pdf(datos: dict) -> bytes:
        salida = BytesIO()
        documento = SimpleDocTemplate(
            salida,
            pagesize=letter,
            rightMargin=22 * mm,
            leftMargin=22 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
            title=f"Acta del Comité - {datos['codigo']}",
            author="CertiSENA",
        )
        estilos = getSampleStyleSheet()
        titulo = ParagraphStyle(
            "ActaTitle",
            parent=estilos["Title"],
            alignment=TA_CENTER,
            textColor=colors.HexColor("#256D00"),
            spaceAfter=12,
        )
        cuerpo = estilos["BodyText"]
        cuerpo.leading = 14
        elementos = [
            Paragraph("ACTA DEFINITIVA DEL COMITÉ DE CERTIFICACIÓN", titulo),
            Paragraph(f"Expediente: {escape(str(datos['codigo']))}", cuerpo),
            Spacer(1, 8),
        ]
        filas = [
            ["Empresa", datos.get("empresa")],
            ["NIT", datos.get("nit")],
            ["Norma", datos.get("norma")],
            ["Alcance", datos.get("alcance")],
            ["Dictamen", datos.get("dictamen")],
            ["Fecha de elaboración", datos.get("fecha")],
        ]
        tabla = Table(
            [[Paragraph(f"<b>{escape(str(etiqueta))}</b>", cuerpo),
              Paragraph(escape(str(valor or "No registrado")), cuerpo)]
             for etiqueta, valor in filas],
            colWidths=[42 * mm, 122 * mm],
            hAlign="LEFT",
        )
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F8ED")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elementos.extend([tabla, Spacer(1, 12)])

        for titulo_seccion, contenido in datos["secciones"]:
            elementos.append(Paragraph(escape(titulo_seccion), estilos["Heading3"]))
            elementos.append(Paragraph(escape(str(contenido or "Sin observaciones.")), cuerpo))
            elementos.append(Spacer(1, 8))

        elementos.append(Spacer(1, 18))
        elementos.append(Paragraph(
            "Documento generado por CertiSENA. La firma electrónica se incorpora "
            "al PDF cuando el líder asignado lo firma.",
            estilos["Italic"],
        ))
        documento.build(elementos)
        return salida.getvalue()

    async def generar(self, id_solicitud: UUID, comentario: str, usuario: dict) -> dict:
        resultado = await self.db.execute(text("""
            SELECT s.id_solicitud, s.estado, s.numero_radicado,
                   s.alcance_certificacion, s.observaciones,
                   e.nombre AS empresa, e.nit,
                   n.codigo AS norma_codigo, n.nombre AS norma_nombre,
                   n.version AS norma_version
            FROM solicitud s
            LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
            LEFT JOIN norma n ON n.id_norma = s.id_norma
            WHERE s.id_solicitud = :id_solicitud
              AND s.deleted_at IS NULL
            FOR UPDATE OF s;
        """), {"id_solicitud": str(id_solicitud)})
        expediente = resultado.mappings().first()
        if not expediente:
            raise HTTPException(status_code=404, detail="El expediente no existe o fue eliminado.")
        if estados.normalizar(expediente["estado"]) not in {estados.APROBADA, estados.RECHAZADA}:
            raise HTTPException(status_code=409, detail="El expediente debe tener un dictamen aprobado o rechazado.")

        acciones_resultado = await self.db.execute(text("""
            SELECT accion, datos, fecha
            FROM comite_accion
            WHERE id_solicitud = :id_solicitud
            ORDER BY fecha, id_accion;
        """), {"id_solicitud": str(id_solicitud)})
        acciones = [dict(fila) for fila in acciones_resultado.mappings().all()]
        decisiones = [accion for accion in acciones if accion["accion"] in {"aprobar", "rechazar"}]
        decision = decisiones[-1] if decisiones else None
        if not decision:
            raise HTTPException(status_code=409, detail="No hay una decisión del Comité registrada para generar el acta.")
        datos_decision = decision.get("datos") or {}
        if isinstance(datos_decision, str):
            datos_decision = json.loads(datos_decision)
        justificacion = str(datos_decision.get("comentario") or comentario or "").strip()
        if not justificacion:
            raise HTTPException(status_code=422, detail="La decisión debe tener una justificación para el acta.")

        etiquetas = {
            "observaciones-acta": "Observaciones del acta",
            "restricciones-alcance": "Restricciones de alcance",
            "comentarios-debate": "Comentarios del debate",
            "solicitar-info-adicional": "Solicitudes de información adicional",
        }
        secciones = [("Justificación del dictamen", justificacion)]
        for accion in acciones:
            titulo_seccion = etiquetas.get(accion["accion"])
            if not titulo_seccion:
                continue
            contenido = accion.get("datos") or {}
            if isinstance(contenido, str):
                contenido = json.loads(contenido)
            detalle = str(contenido.get("comentario") or "").strip()
            if detalle:
                secciones.append((titulo_seccion, detalle))
        if expediente.get("observaciones"):
            secciones.append(("Observaciones del expediente", str(expediente["observaciones"])))

        codigo = expediente["numero_radicado"] or str(expediente["id_solicitud"])
        norma = " ".join(filter(None, (
            expediente.get("norma_codigo"),
            expediente.get("norma_nombre"),
            expediente.get("norma_version"),
        )))
        datos = {
            "codigo": str(codigo),
            "empresa": expediente.get("empresa"),
            "nit": expediente.get("nit"),
            "norma": norma,
            "alcance": expediente.get("alcance_certificacion"),
            "dictamen": "Aprobado" if estados.normalizar(expediente["estado"]) == estados.APROBADA else "Rechazado",
            "fecha": datetime.now().astimezone().strftime("%d/%m/%Y %H:%M %Z"),
            "secciones": secciones,
        }
        pdf = await asyncio.to_thread(self._crear_pdf, datos)
        max_version_resultado = await self.db.execute(text("""
            SELECT COALESCE(MAX(version), 0)
            FROM comite_acta
            WHERE id_solicitud = :id_solicitud;
        """), {"id_solicitud": str(id_solicitud)})
        version = int(max_version_resultado.scalar_one()) + 1
        id_acta = uuid4()
        huella_pdf = hashlib.sha256(pdf).hexdigest()
        ruta_final = self._ruta(id_acta)
        ruta_final.parent.mkdir(parents=True, exist_ok=True)
        descriptor, ruta_temporal = tempfile.mkstemp(
            prefix=f"{id_acta}-", suffix=".pdf.tmp", dir=ruta_final.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as archivo:
                archivo.write(pdf)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(ruta_temporal, ruta_final)
            await self.db.execute(text("""
                INSERT INTO comite_acta (
                    id_acta, id_solicitud, version, estado, huella_pdf,
                    datos, id_usuario_genero, fecha_generacion
                ) VALUES (
                    :id_acta, :id_solicitud, :version, 'GENERADA', :huella_pdf,
                    CAST(:datos AS JSONB), :id_usuario, CURRENT_TIMESTAMP
                );
            """), {
                "id_acta": str(id_acta),
                "id_solicitud": str(id_solicitud),
                "version": version,
                "huella_pdf": huella_pdf,
                "datos": json.dumps(datos, ensure_ascii=False),
                "id_usuario": str(usuario["id_usuario"]),
            })
            await self.db.execute(text("""
                INSERT INTO comite_accion (id_solicitud, accion, datos, id_usuario)
                VALUES (:id_solicitud, 'acta-definitiva', CAST(:datos AS JSONB), :id_usuario);
            """), {
                "id_solicitud": str(id_solicitud),
                "datos": json.dumps({
                    "comentario": comentario,
                    "id_acta": str(id_acta),
                    "version": version,
                    "huella_pdf": huella_pdf,
                }, ensure_ascii=False),
                "id_usuario": str(usuario["id_usuario"]),
            })
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            ruta_final.unlink(missing_ok=True)
            raise
        finally:
            Path(ruta_temporal).unlink(missing_ok=True)
        return {
            "id_acta": str(id_acta),
            "expediente_id": str(id_solicitud),
            "version": version,
            "estado": "GENERADA",
            "huella_pdf": huella_pdf,
            "mensaje": "Acta definitiva generada; está pendiente de firma del líder del Comité.",
        }

    async def estado(self, id_solicitud: UUID, usuario: dict) -> dict:
        resultado = await self.db.execute(text("""
            SELECT id_solicitud
            FROM solicitud
            WHERE id_solicitud = :id_solicitud AND deleted_at IS NULL;
        """), {"id_solicitud": str(id_solicitud)})
        if not resultado.mappings().first():
            raise HTTPException(status_code=404, detail="El expediente no existe o fue eliminado.")
        acta_resultado = await self.db.execute(text("""
            SELECT id_acta, version, estado, huella_pdf, huella_firmante,
                   id_usuario_firmante, fecha_generacion, fecha_firma
            FROM comite_acta
            WHERE id_solicitud = :id_solicitud
            ORDER BY version DESC
            LIMIT 1;
        """), {"id_solicitud": str(id_solicitud)})
        acta = acta_resultado.mappings().first()
        lider_resultado = await self.db.execute(text("""
            SELECT a.id_usuario
            FROM asignacion_lider_comite a
            JOIN usuario u ON u.id_usuario = a.id_usuario
            JOIN rol r ON r.id_rol = u.rol_id
            WHERE a.fecha_fin IS NULL
              AND u.estado = 'Activo'
              AND LOWER(TRANSLATE(r.nombre, 'ÁÉÍÓÚáéíóú', 'AEIOUaeiou'))
                  IN ('comite', 'comite de certificacion')
            ORDER BY a.fecha_inicio DESC
            LIMIT 1;
        """))
        lider = lider_resultado.mappings().first()
        return {
            "acta": dict(acta) if acta else None,
            "puede_firmar": bool(
                acta
                and acta["estado"] == "GENERADA"
                and lider
                and str(lider["id_usuario"]) == str(usuario.get("id_usuario"))
            ),
        }

    async def firmar(self, id_solicitud: UUID, password_firma: str, usuario: dict) -> dict:
        lider_previo = await self.db.execute(text("""
            SELECT a.id_usuario
            FROM asignacion_lider_comite a
            JOIN usuario u ON u.id_usuario = a.id_usuario
            JOIN rol r ON r.id_rol = u.rol_id
            WHERE a.fecha_fin IS NULL
              AND u.estado = 'Activo'
              AND LOWER(TRANSLATE(r.nombre, 'ÁÉÍÓÚáéíóú', 'AEIOUaeiou'))
                  IN ('comite', 'comite de certificacion')
            ORDER BY a.fecha_inicio DESC
            LIMIT 1;
        """))
        lider = lider_previo.mappings().first()
        if not lider or str(lider["id_usuario"]) != str(usuario.get("id_usuario")):
            raise HTTPException(status_code=403, detail="Solo el líder activo del Comité puede firmar el acta.")
        firma = await FirmaService(self.db).verificar(usuario, password_firma)
        await self.db.execute(text("SELECT pg_advisory_xact_lock(76139521, 11);"))
        asignacion_resultado = await self.db.execute(text("""
            SELECT a.id_usuario, u.correo
            FROM asignacion_lider_comite a
            JOIN usuario u ON u.id_usuario = a.id_usuario
            JOIN rol r ON r.id_rol = u.rol_id
            WHERE a.fecha_fin IS NULL
              AND u.estado = 'Activo'
              AND LOWER(TRANSLATE(r.nombre, 'ÁÉÍÓÚáéíóú', 'AEIOUaeiou'))
                  IN ('comite', 'comite de certificacion')
            ORDER BY a.fecha_inicio DESC
            LIMIT 1
            FOR SHARE OF a, u;
        """))
        lider = asignacion_resultado.mappings().first()
        if not lider or str(lider["id_usuario"]) != str(usuario.get("id_usuario")):
            raise HTTPException(status_code=403, detail="Solo el líder activo del Comité puede firmar el acta.")

        acta_resultado = await self.db.execute(text("""
            SELECT id_acta, version, estado, huella_pdf
            FROM comite_acta
            WHERE id_solicitud = :id_solicitud
            ORDER BY version DESC
            LIMIT 1
            FOR UPDATE;
        """), {"id_solicitud": str(id_solicitud)})
        acta = acta_resultado.mappings().first()
        if not acta:
            raise HTTPException(status_code=404, detail="Primero debe generarse el acta definitiva.")
        if acta["estado"] != "GENERADA":
            raise HTTPException(status_code=409, detail="El acta no está pendiente de firma.")
        contenido = self._leer_pdf(acta["id_acta"], acta["huella_pdf"])
        try:
            pdf_firmado, huella_pdf, huella_firmante = await asyncio.to_thread(
                firmar_pdf_pades,
                contenido,
                lider["id_usuario"],
                lider["correo"],
            )
        except FirmaPadesError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        ruta_final = self._ruta(acta["id_acta"], firmada=True)
        descriptor, ruta_temporal = tempfile.mkstemp(
            prefix=f"{acta['id_acta']}-", suffix=".pdf.tmp", dir=ruta_final.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as archivo:
                archivo.write(pdf_firmado)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(ruta_temporal, ruta_final)
            await self.db.execute(text("""
                UPDATE comite_acta
                SET estado = 'FIRMADA',
                    huella_pdf = :huella_pdf,
                    huella_firmante = :huella_firmante,
                    id_usuario_firmante = :id_usuario,
                    fecha_firma = CURRENT_TIMESTAMP
                WHERE id_acta = :id_acta;
            """), {
                "huella_pdf": huella_pdf,
                "huella_firmante": huella_firmante,
                "id_usuario": str(firma["id_usuario"]),
                "id_acta": str(acta["id_acta"]),
            })
            await self.db.execute(text("""
                INSERT INTO comite_accion (id_solicitud, accion, datos, id_usuario)
                VALUES (:id_solicitud, 'firmar-acta', CAST(:datos AS JSONB), :id_usuario);
            """), {
                "id_solicitud": str(id_solicitud),
                "datos": json.dumps({
                    "id_acta": str(acta["id_acta"]),
                    "version": acta["version"],
                    "huella_pdf": huella_pdf,
                    "huella_firmante": huella_firmante,
                }),
                "id_usuario": str(firma["id_usuario"]),
            })
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            ruta_final.unlink(missing_ok=True)
            raise
        finally:
            Path(ruta_temporal).unlink(missing_ok=True)
        try:
            self._ruta(acta["id_acta"]).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("No se pudo retirar el borrador firmado del acta %s: %s", acta["id_acta"], exc)
        return {
            "id_acta": str(acta["id_acta"]),
            "version": acta["version"],
            "estado": "FIRMADA",
            "huella_pdf": huella_pdf,
            "mensaje": "Acta firmada digitalmente y validada.",
        }

    def _leer_pdf(
        self,
        id_acta: UUID | str,
        huella_esperada: str | None,
        firmada: bool = False,
    ) -> bytes:
        try:
            contenido = self._ruta(id_acta, firmada=firmada).read_bytes()
        except OSError as exc:
            raise HTTPException(status_code=404, detail="No se encontró el PDF del acta.") from exc
        huella_real = hashlib.sha256(contenido).hexdigest()
        if not huella_esperada or not hmac.compare_digest(huella_real, huella_esperada):
            raise HTTPException(status_code=409, detail="La huella del acta no coincide; se bloqueó la descarga.")
        return contenido

    async def descargar_firmada(self, id_solicitud: UUID) -> tuple[bytes, int]:
        resultado = await self.db.execute(text("""
            SELECT id_acta, version, estado, huella_pdf
            FROM comite_acta
            WHERE id_solicitud = :id_solicitud
            ORDER BY version DESC
            LIMIT 1;
        """), {"id_solicitud": str(id_solicitud)})
        acta = resultado.mappings().first()
        if not acta or acta["estado"] != "FIRMADA":
            raise HTTPException(status_code=404, detail="No hay un acta firmada para este expediente.")
        return self._leer_pdf(
            acta["id_acta"], acta["huella_pdf"], firmada=True
        ), acta["version"]
