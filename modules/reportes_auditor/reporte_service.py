from io import BytesIO
from uuid import UUID

from sqlalchemy import text
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from modules.auditores.auditor_service import AuditorService


class ReporteAuditorService(AuditorService):
    async def reporte_conflictos(self):
        return await self.consultar_empresas_restringidas()

    async def reporte_historial_academico(self, id_usuario: UUID):
        return await self.consultar_historial_academico(id_usuario)

    async def reporte_conflictos_por_auditor(self, id_usuario: UUID):
        return await self.listar_conflictos(id_usuario)

    async def reporte_conflictos_por_auditor_pdf(self, id_usuario: UUID) -> bytes:
        conflictos = await self.listar_conflictos(id_usuario)
        result = await self.db.execute(text("""
            SELECT nombre, correo, tipo_doc, num_doc
            FROM usuario WHERE id_usuario = :id_usuario
        """), {"id_usuario": str(id_usuario)})
        auditor = dict(result.mappings().first() or {})
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []
        elements.append(Paragraph("Reporte de Conflictos de Interés", styles["Title"]))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(f"<b>Auditor:</b> {auditor.get('nombre', '-')}", styles["Normal"]))
        elements.append(Paragraph(f"<b>Documento:</b> {auditor.get('tipo_doc', '')} {auditor.get('num_doc', '')}", styles["Normal"]))
        elements.append(Paragraph(f"<b>Correo:</b> {auditor.get('correo', '-')}", styles["Normal"]))
        elements.append(Spacer(1, 12))
        if not conflictos:
            elements.append(Paragraph("No se encontraron conflictos registrados.", styles["Normal"]))
        else:
            data = [["Empresa", "NIT", "Tipo", "Descripción", "Bloquea", "Estado", "Fecha"]]
            for c in conflictos:
                data.append([
                    c.get("empresa", "-"),
                    c.get("nit", "-"),
                    c.get("tipo_conflicto", "-"),
                    c.get("descripcion", "-"),
                    "Sí" if c.get("bloquea_asignacion") else "No",
                    c.get("estado", "-"),
                    c.get("fecha_declaracion", "-"),
                ])
            t = Table(data, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3baa01")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            elements.append(t)
        doc.build(elements)
        buffer.seek(0)
        return buffer.read()
