"""Identidad visual compartida por comprobantes y exportaciones de agenda.

La constancia pública es la referencia: franja verde, isotipo blanco y pie de
página institucional. Estos tests protegen que los PDF y las impresiones de
agenda no vuelvan a un encabezado genérico.
"""

from pathlib import Path

from reportlab.lib.units import mm

from core.pdf_institucional import construir_pdf_institucional, tabla_institucional

RAIZ = Path(__file__).resolve().parents[1]


def test_el_pdf_institucional_incrusta_el_logo_y_conserva_los_datos():
    pdf = construir_pdf_institucional(
        titulo="Comprobante de registro de auditor",
        subtitulo="Ana Auditora · Cédula de Ciudadanía 1010101010",
        chip=("Estado de la postulación", "Correcciones"),
        secciones=[
            (
                "Información del auditor",
                [
                    ("Nombre completo", "Ana Auditora"),
                    ("Correo electrónico", "ana@example.com"),
                ],
            ),
        ],
        elementos_extra=[
            (
                "Documentos asociados",
                tabla_institucional(
                    ["Archivo", "Tipo", "Estado", "Fecha"],
                    [["foto.jpg", "Foto Profesional", "Pendiente", "25/10/2026 10:30"]],
                    anchos=[76 * mm, 42 * mm, 28 * mm, 34 * mm],
                ),
            ),
        ],
        nota="Documento de prueba.",
    )

    assert pdf.startswith(b"%PDF")
    assert b"/Subtype /Image" in pdf, "el comprobante no incrusta el logo del SENA"


def test_las_impresiones_de_agenda_usan_la_cabecera_institucional():
    for nombre in (
        "static/consultar_auditorias_programadas.html",
        "static/consultar_auditorias_programadas_admin.html",
    ):
        html = (RAIZ / nombre).read_text(encoding="utf-8")

        assert 'class="brand-band"' in html
        assert "#39A900" in html
        assert "Servicio Nacional de Aprendizaje" in html
        assert "function imprimirProgramacion" in html
        assert "function exportarAgendaIndividual" in html
        assert "function exportarProgramacionAgenda" in html
