from io import BytesIO
from pathlib import Path
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import _normalize_role_name, get_current_user
from modules.comite.comite_service import ComiteService
from modules.solicitudes.documento_service import CARPETA_ARCHIVOS, DocumentoService

router = APIRouter(prefix="/comite", tags=["Comité de certificación"])

COMITE_CERTIFICACION_PERMISOS = {
    "superadm",
    "superadmin",
    "superadministrador",
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "comite",
    "comité",
}

COMITE_DESCARGA_PERMISOS = {
    "superadm",
    "superadmin",
    "superadministrador",
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "req",
    "requerimiento",
    "comite",
    "comité",
}

COMITE_INFORME_AUDITOR_PERMISOS = {
    "superadm",
    "superadmin",
    "superadministrador",
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "comite",
    "comité",
}

COMITE_EVIDENCIAS_FISICAS_PERMISOS = {
    "superadm",
    "superadmin",
    "superadministrador",
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "comite",
    "comité",
}

COMITE_NO_CONFORMIDADES_PERMISOS = {
    "superadm",
    "superadmin",
    "superadministrador",
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "comite",
    "comité",
}

COMITE_HISTORIAL_SOLICITUDES_PERMISOS = {
    "superadm",
    "superadmin",
    "superadministrador",
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "comite",
    "comité",
}

COMITE_CONSULTA_PERMISOS = {
    "superadm",
    "superadmin",
    "superadministrador",
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "comite",
    "comité",
}

COMITE_DECISION_PERMISOS = {
    "superadm",
    "superadmin",
    "superadministrador",
    "adm",
    "admin",
    "administrador",
    "comite",
    "comité",
}

COMITE_SUPERADMIN_ONLY_PERMISOS = {
    "superadm",
    "superadmin",
    "superadministrador",
}


@router.get("/expedientes-pendientes")
async def consultar_expedientes_pendientes(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-001: consultar expedientes pendientes."""
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_CERTIFICACION_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar expedientes pendientes del comité de certificación.",
        )

    resultado = await db.execute(text("""
        SELECT
            s.id_solicitud AS id,
            COALESCE(s.numero_radicado, s.id_solicitud::TEXT) AS codigo,
            e.nombre AS empresa,
            e.nit,
            n.codigo AS norma,
            s.estado,
            s.fecha_creacion
        FROM solicitud s
        LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
        LEFT JOIN norma n ON n.id_norma = s.id_norma
        WHERE s.deleted_at IS NULL
          AND UPPER(s.estado) IN ('RADICADA', 'EN REVISION', 'EN_REVISION', 'PENDIENTE')
        ORDER BY s.fecha_creacion DESC;
    """))
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-001",
        "permiso": "Consultar expedientes pendientes",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expedientes": [dict(fila) for fila in resultado.mappings().all()],
    }


@router.get("/expediente-completo/{expediente_id}")
async def consultar_expediente_completo(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-002: consultar expediente completo."""
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_CERTIFICACION_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar el expediente completo del comité de certificación.",
        )

    resultado = await db.execute(text("""
        SELECT
            s.id_solicitud AS id,
            COALESCE(s.numero_radicado, s.id_solicitud::TEXT) AS codigo,
            s.estado,
            s.alcance_certificacion,
            s.numero_empleados,
            s.numero_sedes,
            s.persona_contacto,
            s.observaciones,
            s.usuario_creador,
            s.id_empresa,
            s.fecha_creacion,
            e.nombre AS solicitante,
            e.nit,
            n.codigo AS norma,
            n.nombre AS norma_nombre,
            n.version AS norma_version
        FROM solicitud s
        LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
        LEFT JOIN norma n ON n.id_norma = s.id_norma
        WHERE s.id_solicitud = :expediente_id
          AND s.deleted_at IS NULL;
    """), {"expediente_id": expediente_id})
    expediente = resultado.mappings().first()
    if not expediente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no existe o fue eliminado.")
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-002",
        "permiso": "Consultar expediente completo",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expediente_id": expediente_id,
        "expediente": dict(expediente),
    }


@router.get("/expediente-descargar/{expediente_id}")
async def descargar_expediente_digital(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-003: descargar expediente digital."""
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_DESCARGA_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para descargar el expediente digital del comité de certificación.",
        )

    resultado = await db.execute(text("""
        SELECT d.id_documento, d.tipo_documento, d.nombre_archivo, d.estado,
               d.observaciones, d.fecha_subida, d.url_archivo
        FROM documento_solicitud d
        JOIN solicitud s ON s.id_solicitud = d.id_solicitud
        WHERE d.id_solicitud = :expediente_id
          AND d.url_archivo IS NOT NULL
          AND s.deleted_at IS NULL
        ORDER BY d.fecha_subida, d.id_documento;
    """), {"expediente_id": expediente_id})
    documentos = [dict(fila) for fila in resultado.mappings().all()]
    if not documentos:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no tiene documentos adjuntos.")

    archivo_zip = BytesIO()
    carpeta_raiz = CARPETA_ARCHIVOS.resolve()
    try:
        with ZipFile(archivo_zip, "w", compression=ZIP_DEFLATED) as expediente_zip:
            for documento in documentos:
                archivo = DocumentoService.ruta_absoluta(documento["url_archivo"]).resolve()
                archivo.relative_to(carpeta_raiz)
                if not archivo.is_file():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"No se encuentra el archivo {documento['nombre_archivo']} en el almacenamiento.",
                    )
                nombre = Path(documento["nombre_archivo"]).name
                expediente_zip.write(archivo, arcname=f"{documento['id_documento']}_{nombre}")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="La ruta de un documento del expediente está fuera del almacenamiento permitido.",
        ) from exc

    return Response(
        content=archivo_zip.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="expediente-{expediente_id}.zip"'},
    )


@router.get("/informe-auditor/{expediente_id}")
async def consultar_informe_auditor(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-004: consultar informe del auditor."""
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_INFORME_AUDITOR_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar el informe del auditor del comité de certificación.",
        )

    existencia = await db.execute(text("""
        SELECT id_solicitud
        FROM solicitud
        WHERE id_solicitud = :expediente_id AND deleted_at IS NULL;
    """), {"expediente_id": expediente_id})
    if not existencia.mappings().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no existe o fue eliminado.")
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-004",
        "permiso": "Consultar informe del auditor",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expediente_id": expediente_id,
        "informe": None,
        "disponible": False,
    }


@router.get("/evidencias-fisicas/{expediente_id}")
async def consultar_evidencias_fisicas(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-005: consultar evidencias físicas."""
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_EVIDENCIAS_FISICAS_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar evidencias físicas del comité de certificación.",
        )

    resultado = await db.execute(text("""
        SELECT d.id_documento, d.tipo_documento AS tipo, d.nombre_archivo,
               d.observaciones AS descripcion, d.fecha_subida, d.url_archivo
        FROM documento_solicitud d
        JOIN solicitud s ON s.id_solicitud = d.id_solicitud
        WHERE d.id_solicitud = :expediente_id
          AND s.deleted_at IS NULL
        ORDER BY d.fecha_subida DESC;
    """), {"expediente_id": expediente_id})
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-005",
        "permiso": "Consultar evidencias físicas",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expediente_id": expediente_id,
        "evidencias": [dict(fila) for fila in resultado.mappings().all()],
    }


@router.get("/no-conformidades/{expediente_id}")
async def consultar_no_conformidades(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-006: consultar no conformidades."""
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_NO_CONFORMIDADES_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar las no conformidades del comité de certificación.",
        )

    existencia = await db.execute(text("""
        SELECT id_solicitud
        FROM solicitud
        WHERE id_solicitud = :expediente_id AND deleted_at IS NULL;
    """), {"expediente_id": expediente_id})
    if not existencia.mappings().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no existe o fue eliminado.")
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-006",
        "permiso": "Consultar no conformidades",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expediente_id": expediente_id,
        "no_conformidades": [],
        "disponible": False,
    }


@router.get("/historial-solicitudes-previas/{usuario_id}")
async def consultar_historial_solicitudes_previas(
    usuario_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-007: consultar historial de solicitudes previas."""
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_HISTORIAL_SOLICITUDES_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar el historial de solicitudes previas del comité de certificación.",
        )

    resultado = await db.execute(text("""
        SELECT id_solicitud AS id,
               COALESCE(numero_radicado, id_solicitud::TEXT) AS codigo,
               fecha_creacion AS fecha,
               estado
        FROM solicitud
        WHERE usuario_creador = :usuario_id
          AND deleted_at IS NULL
        ORDER BY fecha_creacion DESC
        LIMIT 100;
    """), {"usuario_id": usuario_id})
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-007",
        "permiso": "Consultar historial solicitudes previas",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "usuario_id": usuario_id,
        "solicitudes_previas": [dict(fila) for fila in resultado.mappings().all()],
    }


@router.get("/observaciones-tecnicos/{expediente_id}")
async def consultar_observaciones_tecnicos(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-008: consultar observaciones de técnicos."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar observaciones de técnicos del comité.",
        )
    existencia = await db.execute(text("""
        SELECT id_solicitud
        FROM solicitud
        WHERE id_solicitud = :expediente_id AND deleted_at IS NULL;
    """), {"expediente_id": expediente_id})
    if not existencia.mappings().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no existe o fue eliminado.")
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-008",
        "permiso": "Consultar observaciones de técnicos",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expediente_id": expediente_id,
        "observaciones": [],
        "disponible": False,
    }


@router.get("/buscar-expediente")
async def buscar_expediente_por_nit_o_codigo(
    query: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-009: buscar expediente por NIT o código."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para buscar expedientes del comité.",
        )
    resultado = await db.execute(text("""
        SELECT
            s.id_solicitud AS id,
            COALESCE(s.numero_radicado, s.id_solicitud::TEXT) AS codigo,
            e.nombre AS empresa,
            e.nit,
            n.codigo AS norma,
            s.estado
        FROM solicitud s
        LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
        LEFT JOIN norma n ON n.id_norma = s.id_norma
        WHERE s.deleted_at IS NULL
          AND (
              s.numero_radicado ILIKE :query
              OR e.nit ILIKE :query
              OR e.nombre ILIKE :query
          )
        ORDER BY s.fecha_creacion DESC
        LIMIT 100;
    """), {"query": f"%{query.strip()}%"})
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-009",
        "permiso": "Buscar expediente por NIT o código",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "query": query,
        "resultados": [dict(fila) for fila in resultado.mappings().all()],
    }


@router.get("/filtrar-expedientes")
async def filtrar_expedientes_por_norma_sector(
    norma: str | None = None,
    sector: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-010: filtrar expedientes por norma/sector."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para filtrar expedientes del comité.",
        )
    if sector:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El esquema de empresas no contiene un campo de sector para filtrar expedientes.",
        )
    resultado = await db.execute(text("""
        SELECT
            s.id_solicitud AS id,
            COALESCE(s.numero_radicado, s.id_solicitud::TEXT) AS codigo,
            e.nombre AS empresa,
            e.nit,
            n.codigo AS norma,
            s.estado
        FROM solicitud s
        LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
        LEFT JOIN norma n ON n.id_norma = s.id_norma
        WHERE s.deleted_at IS NULL
          AND (CAST(:norma AS TEXT) IS NULL OR n.codigo ILIKE :norma OR n.nombre ILIKE :norma)
        ORDER BY s.fecha_creacion DESC
        LIMIT 200;
    """), {"norma": f"%{norma.strip()}%" if norma and norma.strip() else None})
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-010",
        "permiso": "Filtrar expedientes por norma/sector",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "filtro": {"norma": norma, "sector": sector},
        "resultados": [dict(fila) for fila in resultado.mappings().all()],
    }


@router.post("/decisiones")
async def registrar_decision_certificacion(
    decision: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-011: registrar decisión de certificación."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para registrar decisiones de certificación.",
        )
    return await ComiteService(db).registrar_accion("decisiones", decision, current_user)


@router.post("/aprobar")
async def aprobar_otorgamiento(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-012: aprobar otorgamiento."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para aprobar otorgamiento.")
    return await ComiteService(db).registrar_accion("aprobar", payload, current_user)


@router.post("/rechazar")
async def rechazar_otorgamiento(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-013: rechazar / negar otorgamiento."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para rechazar otorgamiento.")
    return await ComiteService(db).registrar_accion("rechazar", payload, current_user)


@router.post("/solicitar-info-adicional")
async def solicitar_info_adicional_al_auditor(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-014: solicitar info adicional al auditor."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para solicitar información adicional.")
    return await ComiteService(db).registrar_accion("solicitar-info-adicional", payload, current_user)


@router.post("/observaciones-acta")
async def registrar_observaciones_en_acta(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-015: registrar observaciones en acta."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para registrar observaciones en acta.")
    return await ComiteService(db).registrar_accion("observaciones-acta", payload, current_user)


@router.post("/restricciones-alcance")
async def registrar_restricciones_de_alcance(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-016: registrar restricciones de alcance."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para registrar restricciones de alcance.")
    return await ComiteService(db).registrar_accion("restricciones-alcance", payload, current_user)


@router.post("/decision-borrador")
async def guardar_decision_borrador(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-017: guardar decisión borrador."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para guardar borrador de decisión.")
    return await ComiteService(db).registrar_accion("decision-borrador", payload, current_user)


@router.post("/decision-definitiva")
async def confirmar_decision_definitiva(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-018: confirmar decisión definitiva."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para confirmar decisión definitiva.")
    return await ComiteService(db).registrar_accion("decision-definitiva", payload, current_user)


@router.get("/decisiones-historicas")
async def consultar_decisiones_historicas(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-019: consultar decisiones históricas."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar decisiones históricas.")
    resultado = await db.execute(text("""
        SELECT
            a.id_accion,
            a.id_solicitud AS expediente_id,
            COALESCE(s.numero_radicado, s.id_solicitud::TEXT) AS codigo_expediente,
            a.accion,
            CAST(a.datos AS TEXT) AS datos,
            a.id_usuario,
            a.fecha
        FROM comite_accion a
        JOIN solicitud s ON s.id_solicitud = a.id_solicitud
        ORDER BY a.fecha DESC, a.id_accion DESC
        LIMIT 500;
    """))
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-019",
        "permiso": "Consultar decisiones históricas",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "decisiones": [dict(fila) for fila in resultado.mappings().all()],
    }


@router.get("/exportar-decisiones")
async def exportar_decisiones_consolidadas(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-020: exportar decisiones consolidadas."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS and role_name not in {"req", "requerimiento"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para exportar decisiones consolidadas.")
    resultado = await db.execute(text("""
        SELECT
            a.id_accion,
            a.id_solicitud AS expediente_id,
            COALESCE(s.numero_radicado, s.id_solicitud::TEXT) AS codigo_expediente,
            a.accion,
            CAST(a.datos AS TEXT) AS datos,
            a.id_usuario,
            a.fecha
        FROM comite_accion a
        JOIN solicitud s ON s.id_solicitud = a.id_solicitud
        ORDER BY a.fecha DESC, a.id_accion DESC;
    """))
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-020",
        "permiso": "Exportar decisiones consolidadas",
        "roles_autorizados": ["SUPERADM", "ADM", "REQ"],
        "decisiones": [dict(fila) for fila in resultado.mappings().all()],
    }


@router.get("/historial-por-empresa/{empresa_id}")
async def consultar_historial_por_empresa(
    empresa_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-021: consultar historial por empresa."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar historial por empresa.")
    resultado = await db.execute(text("""
        SELECT id_solicitud AS id,
               COALESCE(numero_radicado, id_solicitud::TEXT) AS codigo,
               estado,
               fecha_creacion,
               fecha_radicacion
        FROM solicitud
        WHERE id_empresa = :empresa_id
          AND deleted_at IS NULL
        ORDER BY fecha_creacion DESC
        LIMIT 200;
    """), {"empresa_id": empresa_id})
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-021",
        "permiso": "Consultar historial por empresa",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "empresa_id": empresa_id,
        "historial": [dict(fila) for fila in resultado.mappings().all()],
    }


@router.get("/auditor-responsable/{expediente_id}")
async def consultar_auditor_responsable(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-022: consultar auditor responsable."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar auditor responsable.")
    resultado = await db.execute(text("""
        SELECT u.id_usuario, u.nombre, u.correo,
               a.especialidad, a.estado_asignacion
        FROM auditores_solicitud a
        JOIN solicitud s ON s.id_solicitud = a.id_solicitud
        JOIN usuario u ON u.id_usuario = a.id_auditor
        WHERE a.id_solicitud = :expediente_id
          AND s.deleted_at IS NULL
          AND a.estado_asignacion IN ('Activo', 'Asignado', 'Confirmado')
        ORDER BY CASE WHEN a.especialidad = 'Auditor líder' THEN 0 ELSE 1 END,
                 a.id
        LIMIT 1;
    """), {"expediente_id": expediente_id})
    auditor = resultado.mappings().first()
    if not auditor:
        solicitud = await db.execute(text("""
            SELECT id_solicitud
            FROM solicitud
            WHERE id_solicitud = :expediente_id AND deleted_at IS NULL;
        """), {"expediente_id": expediente_id})
        if not solicitud.mappings().first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no existe o fue eliminado.")
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-022",
        "permiso": "Consultar auditor responsable",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expediente_id": expediente_id,
        "auditor": dict(auditor) if auditor else None,
    }


@router.get("/empresa-evaluada/{empresa_id}")
async def consultar_datos_empresa_evaluada(
    empresa_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-023: consultar datos empresa evaluada."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar datos de la empresa evaluada.")
    resultado = await db.execute(text("""
        SELECT id_empresa, nombre, nit, ciudad, direccion, correo, estado
        FROM empresa
        WHERE id_empresa = :empresa_id;
    """), {"empresa_id": empresa_id})
    empresa = resultado.mappings().first()
    if not empresa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La empresa no existe.")
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-023",
        "permiso": "Consultar datos empresa evaluada",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "empresa_id": empresa_id,
        "empresa": dict(empresa),
    }


@router.post("/comentarios-debate")
async def registrar_comentarios_al_debate(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-024: registrar comentarios al debate."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para registrar comentarios al debate.")
    return await ComiteService(db).registrar_accion("comentarios-debate", payload, current_user)


@router.post("/acta-definitiva")
async def generar_acta_del_comite_definitiva(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-025: generar acta del comité definitiva."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para generar acta definitiva.")
    return await ComiteService(db).registrar_accion("acta-definitiva", payload, current_user)


@router.get("/acta-firmada/{expediente_id}")
async def descargar_acta_firmada(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-026: descargar acta firmada."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para descargar el acta firmada.")
    resultado = await db.execute(text("""
        SELECT id_accion
        FROM comite_accion
        WHERE id_solicitud = :expediente_id AND accion = 'firmar-acta'
        ORDER BY fecha DESC
        LIMIT 1;
    """), {"expediente_id": expediente_id})
    if not resultado.mappings().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay un acta firmada para este expediente.")
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="La firma quedó registrada, pero el sistema aún no genera el archivo PDF del acta.",
    )


@router.post("/firmar-acta")
async def firmar_electronicamente_acta(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-027: firmar electrónicamente acta."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para firmar electrónicamente acta.")
    return await ComiteService(db).registrar_accion("firmar-acta", payload, current_user)


@router.post("/cerrar-expediente")
async def cerrar_expediente_de_dictamen(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-028: cerrar expediente de dictamen."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para cerrar expediente de dictamen.")
    return await ComiteService(db).registrar_accion("cerrar-expediente", payload, current_user)


@router.post("/reabrir-dictamen")
async def reabrir_dictamen_por_error(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-029: reabrir dictamen por error."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_SUPERADMIN_ONLY_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este permiso solo lo puede ejecutar un superadministrador.")
    return await ComiteService(db).registrar_accion("reabrir-dictamen", payload, current_user)
