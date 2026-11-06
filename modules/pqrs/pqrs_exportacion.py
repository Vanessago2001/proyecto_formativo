"""
Exportación del reporte de PQRS (PQR-015): PDF y, si openpyxl está
instalado, Excel. El CSV se quitó: no se usa.

El PDF y el Excel reutilizan modules/reportes/exportacion_tabular.py, la
utilidad compartida de listados con la identidad institucional.
"""

from __future__ import annotations

import importlib.util
from datetime import date, datetime

from fastapi import HTTPException, Response, status

from core.datetime_utils import SYSTEM_TIMEZONE, system_now

COLUMNAS = (
    ("radicado", "Radicado", 20),
    ("tipo", "Tipo", 13),
    ("estado", "Estado", 16),
    ("canal", "Canal", 12),
    ("asunto", "Asunto", 34),
    ("nombre_peticionario", "Peticionario", 24),
    ("empresa_nombre", "Empresa", 22),
    ("responsable", "Responsable", 22),
    ("fecha_radicacion", "Radicada", 16),
    ("fecha_limite", "Fecha límite", 13),
    ("fecha_respuesta", "Respondida", 16),
    ("dias_habiles_transcurridos", "Días hábiles", 10),
    ("semaforo_texto", "Tiempo de atención", 18),
)

TEXTO_SEMAFORO = {
    "vencida": "Vencida",
    "proxima": "Próxima a vencer",
    "en_termino": "En término",
    "en_espera": "Esperando al peticionario",
    "atendida_a_tiempo": "Atendida a tiempo",
    "atendida_tarde": "Atendida fuera de término",
}


def excel_disponible() -> bool:
    return importlib.util.find_spec("openpyxl") is not None


def formatos_disponibles() -> list[str]:
    return ["pdf"] + (["xlsx"] if excel_disponible() else [])


def respuesta_reporte(formato: str, filas: list[dict], subtitulo: str) -> Response:
    formato = (formato or "").strip().lower()
    if formato in ("excel", "xls"):
        formato = "xlsx"
    if formato not in formatos_disponibles():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Formato no disponible. Usa: {', '.join(formatos_disponibles())}.",
        )
    filas = [dict(f, semaforo_texto=TEXTO_SEMAFORO.get(f.get("semaforo"), "")) for f in filas]
    nombre = f"reporte_pqrs_{system_now():%Y%m%d_%H%M}.{formato}"

    from modules.reportes.exportacion_tabular import Columna, generar_pdf_tabla, generar_xlsx

    columnas = [Columna(clave, titulo, ancho) for clave, titulo, ancho in COLUMNAS]
    if formato == "pdf":
        contenido = generar_pdf_tabla("Reporte de PQRS", columnas, filas, subtitulo=subtitulo)
        tipo = "application/pdf"
    else:
        contenido = generar_xlsx("Reporte de PQRS", columnas, filas, subtitulo=subtitulo, hoja="PQRS")
        tipo = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return Response(
        content=contenido,
        media_type=tipo,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
