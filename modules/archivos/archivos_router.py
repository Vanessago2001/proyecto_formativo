"""Entrega protegida de los archivos de ``uploads/`` (antes carpeta pública).

Ver ``core/archivos_firmados.py`` para el formato del enlace.

REGLAS PARA FIRMAR (``GET /archivos/firmar?ruta=...``)
-----------------------------------------------------
Hoy en ``uploads/`` solo hay archivos de auditores (los de empresas,
solicitudes, apelaciones, PQRS, evidencias y actas viven en ``storage/`` y
cada módulo los entrega por su propio endpoint con sesión):

=============================================  ==========================================
Archivo                                        Quién puede obtener el enlace
=============================================  ==========================================
uploads/auditores/*.pdf  (documento_auditor)   Coordinador; Auxiliar (consulta hojas de
uploads/auditores/certificaciones/*            vida, igual que /admin/auditores-
uploads/auditores/perfiles/*  (foto_url)       registrados); el auditor dueño del archivo.
cualquier otra ruta dentro de uploads/         Solo el Coordinador.
=============================================  ==========================================

Empresa, Comité, Instructor y Público no reciben enlaces: ninguna de sus
pantallas usa archivos de auditores. Las fotos que ve el Coordinador en la
asignación o la agenda llegan ya firmadas en el JSON del endpoint que las
devuelve (y ese endpoint exige su propio rol).

No hay archivos públicos a propósito en ``uploads/``: los logos están en
``static/`` y la constancia y el certificado públicos se generan en
``/api/consultas-publicas/constancia/{nit}/pdf`` y
``/certificados/publico/{codigo}/pdf``.
"""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.archivos_firmados import (
    VIGENCIA_SEGUNDOS,
    firmar_url,
    resolver_en_uploads,
    ruta_relativa,
    verificar,
)
from core import almacen_archivos, archivos_firmados
from core.database import get_db
from core.security import _normalize_role_name, get_current_user

router = APIRouter(prefix="/archivos", tags=["Archivos"])

_PROHIBIDO = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="El enlace del archivo no es válido o ya venció. Vuelva a abrir la pantalla.",
)


async def _es_dueno(db: AsyncSession, id_usuario, url: str) -> bool:
    resultado = await db.execute(
        text("""
            SELECT 1 FROM documento_auditor
             WHERE url_archivo = :url AND id_usuario = :id_usuario
            UNION ALL
            SELECT 1 FROM certificacion_auditor
             WHERE url_archivo = :url AND id_usuario = :id_usuario
            UNION ALL
            SELECT 1 FROM perfil_auditor
             WHERE foto_url = :url AND id_usuario = :id_usuario
            LIMIT 1;
        """),
        {"url": url, "id_usuario": str(id_usuario)},
    )
    return resultado.first() is not None


async def puede_firmar(db: AsyncSession, usuario: dict, relativo: str) -> bool:
    rol = _normalize_role_name(usuario.get("role_name"))
    if rol == "admin":
        return True
    es_de_auditor = relativo.startswith("auditores/")
    if rol == "auxiliar" and es_de_auditor:
        return True
    if es_de_auditor and usuario.get("id_usuario"):
        return await _es_dueno(db, usuario["id_usuario"], f"/uploads/{relativo}")
    return False


@router.get("/firmar")
async def firmar_archivo(
    ruta: str = Query(..., description="'/uploads/...' tal como está guardada en la base."),
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    relativo = ruta_relativa(ruta)
    if relativo is None:
        raise HTTPException(status_code=422, detail="La ruta no corresponde a un archivo subido.")
    if not await puede_firmar(db, usuario, relativo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permiso para consultar este archivo.",
        )
    return {"url": firmar_url(f"/uploads/{relativo}"), "vigencia_segundos": VIGENCIA_SEGUNDOS}


@router.get("/{exp}/{firma}/{ruta:path}", response_class=FileResponse)
async def descargar_archivo(exp: int, firma: str, ruta: str, db: AsyncSession = Depends(get_db)):
    relativo = ruta_relativa(f"/uploads/{ruta}")
    if relativo is None or not verificar(relativo, exp, firma):
        raise _PROHIBIDO
    archivo = resolver_en_uploads(relativo)
    if archivo is None:
        # No está en este computador: se trae de la base compartida (y queda en caché).
        # La sesión solo toma una conexión si de verdad hay que consultar.
        await almacen_archivos.ruta_local(
            f"uploads/{relativo}", db=db, disco=archivos_firmados.RAIZ_UPLOADS / relativo
        )
        archivo = resolver_en_uploads(relativo)
    if archivo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El archivo no existe.")
    tipo = mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
    # Un SVG o HTML en línea ejecutaría scripts con el origen de la aplicación.
    en_linea = tipo not in ("image/svg+xml", "text/html", "application/xhtml+xml")
    return FileResponse(
        path=str(archivo),
        media_type=tipo,
        filename=archivo.name,
        content_disposition_type="inline" if en_linea else "attachment",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
