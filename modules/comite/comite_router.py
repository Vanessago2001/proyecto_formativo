from datetime import date
from io import BytesIO
from pathlib import Path
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import _normalize_role_name, get_current_user
from modules.solicitudes import estado_solicitud as estados
from modules.comite.comite_service import (
    FILTRO_ESTADO_PENDIENTES,
    FILTRO_ESTADO_TODOS,
    ComiteService,
    construir_filtro_expedientes,
)
from modules.reportes.exportacion_tabular import Columna, respuesta_exportacion
from modules.comite.comite_acta_service import ComiteActaService
from modules.solicitudes.documento_service import CARPETA_ARCHIVOS, DocumentoService

router = APIRouter(prefix="/comite", tags=["Comité de certificación"])

COMITE_CERTIFICACION_PERMISOS = {
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "comite",
    "comité",
}

COMITE_DESCARGA_PERMISOS = {
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
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "comite",
    "comité",
}

COMITE_EVIDENCIAS_FISICAS_PERMISOS = {
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "comite",
    "comité",
}

COMITE_NO_CONFORMIDADES_PERMISOS = {
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "comite",
    "comité",
}

COMITE_HISTORIAL_SOLICITUDES_PERMISOS = {
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "comite",
    "comité",
}

COMITE_CONSULTA_PERMISOS = {
    "adm",
    "admin",
    "administrador",
    "aux",
    "auxiliar",
    "comite",
    "comité",
}

COMITE_DECISION_PERMISOS = {
    "adm",
    "admin",
    "administrador",
    "comite",
    "comité",
}

# Reabrir un dictamen (COM-029) era exclusivo del Super Administrador, que se
# retiró del sistema: ahora lo hace el Coordinador.
COMITE_SUPERADMIN_ONLY_PERMISOS = {
    "adm",
    "admin",
    "administrador",
    "coordinador",
}


@router.get("/expedientes-pendientes")
async def consultar_expedientes_pendientes(
    estado: str | None = Query(default=FILTRO_ESTADO_PENDIENTES, description="pendientes, todos o un estado de M5"),
    q: str | None = Query(default=None, description="NIT, radicado o empresa"),
    norma: str | None = Query(default=None, description="Código de la norma (ISO-9001)"),
    fecha_desde: date | None = Query(default=None, description="Radicado desde (AAAA-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="Radicado hasta (AAAA-MM-DD)"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-001: consultar expedientes pendientes (con filtros combinables)."""
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_CERTIFICACION_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar expedientes pendientes del comité de certificación.",
        )

    condiciones, params = construir_filtro_expedientes(estado, q, norma, fecha_desde, fecha_hasta)
    resultado = await db.execute(text(f"""
        SELECT
            s.id_solicitud AS id,
            COALESCE(s.numero_radicado, s.id_solicitud::TEXT) AS codigo,
            e.nombre AS empresa,
            e.nit,
            n.codigo AS norma,
            s.estado,
            s.fecha_creacion,
            COALESCE(s.fecha_radicacion, s.fecha_creacion) AS fecha_radicacion
        FROM solicitud s
        LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
        LEFT JOIN norma n ON n.id_norma = s.id_norma
        WHERE s.deleted_at IS NULL
          -- Los estados vienen del catalogo de M5, no de una lista a mano.{condiciones}
        ORDER BY COALESCE(s.fecha_radicacion, s.fecha_creacion) DESC;
    """), params)
    expedientes = [dict(fila) for fila in resultado.mappings().all()]
    normas = await db.execute(text("SELECT codigo, nombre FROM norma ORDER BY codigo;"))
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-001",
        "permiso": "Consultar expedientes pendientes",
        "roles_autorizados": ["ADM", "AUX"],
        "filtro": {
            "estado": estado or FILTRO_ESTADO_PENDIENTES,
            "q": q,
            "norma": norma,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
        },
        "estados_disponibles": [FILTRO_ESTADO_PENDIENTES, FILTRO_ESTADO_TODOS, *estados.ESTADOS],
        "normas": [dict(fila) for fila in normas.mappings().all()],
        "expedientes": expedientes,
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
        "roles_autorizados": ["ADM", "AUX"],
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

    resultado = await db.execute(text("""
        SELECT i.id_informe, i.id_auditoria, i.version, i.tipo, i.contenido,
               i.estado, i.fecha_generacion, i.fecha_finalizacion,
               i.fecha_envio_comite, i.hash_documento, i.firma_digital,
               a.estado AS estado_auditoria
        FROM auditoria a
        JOIN informe_auditoria i ON i.id_auditoria = a.id_auditoria
        JOIN solicitud s ON s.id_solicitud = a.id_solicitud
        WHERE a.id_solicitud = :expediente_id
          AND s.deleted_at IS NULL
          AND i.fecha_envio_comite IS NOT NULL
        ORDER BY i.fecha_envio_comite DESC, i.version DESC
        LIMIT 1;
    """), {"expediente_id": expediente_id})
    informe = resultado.mappings().first()
    if not informe:
        existencia = await db.execute(text("""
            SELECT id_solicitud
            FROM solicitud
            WHERE id_solicitud = :expediente_id AND deleted_at IS NULL;
        """), {"expediente_id": expediente_id})
        if not existencia.mappings().first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no existe o fue eliminado.")
    contenido = (informe["contenido"] or {}) if informe else {}
    resumen_hallazgos = contenido.get("hallazgos") or {}
    mayores = resumen_hallazgos.get("no_conformidades_mayores", 0)
    menores = resumen_hallazgos.get("no_conformidades_menores", 0)
    resumen_resultado = (
        f"{mayores} no conformidad{'es' if mayores != 1 else ''} "
        f"mayor{'es' if mayores != 1 else ''}, "
        f"{menores} menor{'es' if menores != 1 else ''}"
    ) if resumen_hallazgos else None
    resultado_informe = (
        contenido.get("resultado")
        or contenido.get("conclusion")
        or resumen_resultado
        or (informe["estado"] if informe else None)
    )
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-004",
        "permiso": "Consultar informe del auditor",
        "roles_autorizados": ["ADM", "AUX"],
        "expediente_id": expediente_id,
        "informe": ({
            **dict(informe),
            "resultado": resultado_informe,
            "fecha": informe["fecha_finalizacion"] or informe["fecha_envio_comite"],
            "firmado": bool(informe["firma_digital"]),
        } if informe else None),
        "disponible": informe is not None,
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
        SELECT e.id_evidencia, e.id_auditoria, e.id_hallazgo,
               e.nombre_archivo, e.tipo_archivo, e.version, e.estado,
               e.observaciones AS descripcion, e.fecha_subida,
               e.hash_archivo, COALESCE(u.nombre, u.correo) AS subida_por
        FROM auditoria a
        JOIN solicitud s ON s.id_solicitud = a.id_solicitud
        JOIN evidencia e ON e.id_auditoria = a.id_auditoria
        LEFT JOIN usuario u ON u.id_usuario = e.id_usuario_subida
        WHERE a.id_solicitud = :expediente_id
          AND s.deleted_at IS NULL
        ORDER BY e.fecha_subida DESC;
    """), {"expediente_id": expediente_id})
    evidencias = [dict(fila) for fila in resultado.mappings().all()]
    if not evidencias:
        existencia = await db.execute(text("""
            SELECT id_solicitud FROM solicitud
            WHERE id_solicitud = :expediente_id AND deleted_at IS NULL;
        """), {"expediente_id": expediente_id})
        if not existencia.mappings().first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no existe o fue eliminado.")
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-005",
        "permiso": "Consultar evidencias físicas",
        "roles_autorizados": ["ADM", "AUX"],
        "expediente_id": expediente_id,
        "evidencias": evidencias,
        "disponible": True,
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

    resultado = await db.execute(text("""
        SELECT h.id_hallazgo AS id, h.clasificacion,
               h.titulo AS codigo, h.descripcion, h.requisito_relacionado, h.estado,
               h.fecha_registro, h.fecha_cierre, v.numeral,
               v.descripcion AS requisito_descripcion
        FROM auditoria a
        JOIN solicitud s ON s.id_solicitud = a.id_solicitud
        JOIN hallazgo h ON h.id_auditoria = a.id_auditoria
        LEFT JOIN evaluacion_requisito e ON e.id_evaluacion = h.id_evaluacion
        LEFT JOIN variable_requisito v ON v.id_variable = e.id_variable
        WHERE a.id_solicitud = :expediente_id
          AND s.deleted_at IS NULL
          AND h.tipo = 'NO_CONFORMIDAD'
        ORDER BY h.fecha_registro DESC;
    """), {"expediente_id": expediente_id})
    hallazgos = [dict(fila) for fila in resultado.mappings().all()]
    if not hallazgos:
        existencia = await db.execute(text("""
            SELECT id_solicitud FROM solicitud
            WHERE id_solicitud = :expediente_id AND deleted_at IS NULL;
        """), {"expediente_id": expediente_id})
        if not existencia.mappings().first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no existe o fue eliminado.")
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-006",
        "permiso": "Consultar no conformidades",
        "roles_autorizados": ["ADM", "AUX"],
        "expediente_id": expediente_id,
        "no_conformidades": hallazgos,
        "disponible": True,
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
        "roles_autorizados": ["ADM", "AUX"],
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
    resultado = await db.execute(text("""
        SELECT o.id_observacion, o.texto AS descripcion, o.tipo,
               o.fecha, COALESCE(u.nombre, u.correo) AS tecnico
        FROM observacion_solicitud o
        JOIN solicitud s ON s.id_solicitud = o.id_solicitud
        LEFT JOIN usuario u ON u.id_usuario = o.id_usuario
        WHERE o.id_solicitud = :expediente_id
          AND s.deleted_at IS NULL
          AND LOWER(o.tipo) = 'tecnica'
        ORDER BY o.fecha DESC;
    """), {"expediente_id": expediente_id})
    observaciones = [dict(fila) for fila in resultado.mappings().all()]
    if not observaciones:
        existencia = await db.execute(text("""
            SELECT id_solicitud FROM solicitud
            WHERE id_solicitud = :expediente_id AND deleted_at IS NULL;
        """), {"expediente_id": expediente_id})
        if not existencia.mappings().first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no existe o fue eliminado.")
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-008",
        "permiso": "Consultar observaciones de técnicos",
        "roles_autorizados": ["ADM", "AUX"],
        "expediente_id": expediente_id,
        "observaciones": observaciones,
        "disponible": True,
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
        "roles_autorizados": ["ADM", "AUX"],
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
        "roles_autorizados": ["ADM", "AUX"],
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
    resultado = await ComiteService(db).registrar_accion("aprobar", payload, current_user)
    # La aprobación ya quedó guardada; ahora se crea solo el borrador del
    # certificado para que llegue al panel del líder para la firma.
    from modules.certificados.certificados_service import CertificadosService

    borrador = await CertificadosService(db).crear_borrador_automatico(
        UUID(str(resultado["expediente_id"])), current_user
    )
    resultado["certificado"] = borrador
    if borrador.get("creado"):
        resultado["mensaje"] = (
            f"Solicitud aprobada. Se creó el borrador del certificado {borrador['codigo_verificacion']} "
            "y quedó en el panel del líder del Comité para su firma."
        )
    else:
        resultado["mensaje"] = (
            "Solicitud aprobada. No se pudo crear el borrador del certificado: "
            f"{borrador['motivo']} El Coordinador puede generarlo desde Gestión de certificados."
        )
    return resultado


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
            e.nombre AS empresa,
            a.accion,
            a.datos->>'comentario' AS comentario,
            CAST(a.datos AS TEXT) AS datos,
            a.id_usuario,
            COALESCE(u.nombre, u.correo, a.id_usuario) AS usuario,
            s.estado AS estado_expediente,
            a.fecha
        FROM comite_accion a
        JOIN solicitud s ON s.id_solicitud = a.id_solicitud
        LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
        LEFT JOIN usuario u ON u.id_usuario::TEXT = a.id_usuario
        ORDER BY a.fecha DESC, a.id_accion DESC
        LIMIT 500;
    """))
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-019",
        "permiso": "Consultar decisiones históricas",
        "roles_autorizados": ["ADM", "AUX"],
        "decisiones": [dict(fila) for fila in resultado.mappings().all()],
    }


def _estado_firma_dictamen(estado_acta: str | None) -> str:
    estado = (estado_acta or "").strip().upper()
    if estado == "FIRMADA":
        return "Firmado"
    if estado == "GENERADA":
        return "Pendiente de firma"
    return "Sin acta"


def _estado_firma_certificado(decision: str, estado_certificado: str | None, firmado: bool | None) -> str:
    if decision != "Aprobada":
        return "No aplica"
    estado = (estado_certificado or "").strip().upper()
    if not estado:
        return "Sin certificado"
    if firmado:
        return "Firmado"
    return "Pendiente de firma"


@router.get("/historial-dictamenes")
async def consultar_historial_dictamenes(
    decision: str | None = Query(default=None, description="aprobada o rechazada"),
    firma: str | None = Query(default=None, description="firmado o pendiente"),
    q: str | None = Query(default=None, max_length=120, description="Radicado, empresa o NIT"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Historial de decisiones (COM-019) con una fila por expediente decidido:
    decisión final, quién y cuándo, y si el dictamen (acta) y el certificado
    ya están firmados. Con filtro y paginación.
    """
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar decisiones históricas.")
    resultado = await db.execute(text("""
        WITH decision AS (
            SELECT DISTINCT ON (a.id_solicitud)
                a.id_solicitud, a.accion, a.datos->>'comentario' AS comentario, a.fecha,
                COALESCE(u.nombre, u.correo, a.id_usuario) AS decidio
            FROM comite_accion a
            LEFT JOIN usuario u ON u.id_usuario::TEXT = a.id_usuario
            WHERE a.accion IN ('aprobar', 'rechazar')
            ORDER BY a.id_solicitud, a.fecha DESC, a.id_accion DESC
        ),
        acta AS (
            SELECT DISTINCT ON (id_solicitud) id_solicitud, estado AS estado_acta, fecha_firma
            FROM comite_acta
            ORDER BY id_solicitud, version DESC
        )
        SELECT
            s.id_solicitud AS expediente_id,
            COALESCE(s.numero_radicado, s.id_solicitud::TEXT) AS codigo_expediente,
            e.nombre AS empresa, e.nit,
            s.estado AS estado_expediente,
            d.accion, d.comentario, COALESCE(d.fecha, s.fecha) AS fecha, d.decidio,
            acta.estado_acta, acta.fecha_firma,
            cert.codigo_verificacion, cert.estado_certificado, cert.certificado_firmado
        FROM solicitud s
        LEFT JOIN decision d ON d.id_solicitud = s.id_solicitud
        LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
        LEFT JOIN acta ON acta.id_solicitud = s.id_solicitud
        -- Un certificado se liga por id_solicitud o por solicitud.id_certificado.
        LEFT JOIN LATERAL (
            SELECT c.codigo_verificacion, TRIM(c.estado_certificado) AS estado_certificado,
                   (c.id_firmante IS NOT NULL AND c.huella_firmante IS NOT NULL
                    AND c.codigo_hash IS NOT NULL AND c.huella_pdf IS NOT NULL) AS certificado_firmado
            FROM certificado c
            WHERE c.id_solicitud = s.id_solicitud OR c.id_certificado = s.id_certificado
            ORDER BY c.fecha_registro DESC NULLS LAST
            LIMIT 1
        ) cert ON TRUE
        -- Decididas por el Comité o ya aprobadas/rechazadas en la base.
        WHERE s.deleted_at IS NULL
          AND (d.id_solicitud IS NOT NULL OR s.estado IN ('Aprobada', 'Rechazada'))
        ORDER BY COALESCE(d.fecha, s.fecha) DESC NULLS LAST
        LIMIT 2000;
    """))
    filas = []
    for fila in resultado.mappings().all():
        item = dict(fila)
        if item["accion"]:
            item["decision"] = "Aprobada" if item["accion"] == "aprobar" else "Rechazada"
        else:
            item["decision"] = "Aprobada" if str(item["estado_expediente"]).lower().startswith("aprob") else "Rechazada"
        item["firma_dictamen"] = _estado_firma_dictamen(item.get("estado_acta"))
        item["firma_certificado"] = _estado_firma_certificado(
            item["decision"], item.get("estado_certificado"), item.get("certificado_firmado")
        )
        # Pendiente si a lo que le corresponde firma todavía le falta.
        item["pendiente_firma"] = item["firma_dictamen"] != "Firmado" or item["firma_certificado"] in ("Pendiente de firma", "Sin certificado")
        filas.append(item)

    if decision:
        filas = [f for f in filas if f["decision"].lower().startswith(decision.strip().lower()[:6])]
    if firma == "firmado":
        filas = [f for f in filas if not f["pendiente_firma"]]
    elif firma == "pendiente":
        filas = [f for f in filas if f["pendiente_firma"]]
    if q and q.strip():
        texto = q.strip().lower()
        filas = [f for f in filas if any(texto in str(f.get(c) or "").lower() for c in ("codigo_expediente", "empresa", "nit"))]

    total = len(filas)
    inicio = (page - 1) * page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "paginas": max(1, -(-total // page_size)),
        "dictamenes": filas[inicio:inicio + page_size],
    }


# Nombre legible de cada acción del Comité (el mismo que muestra comite.html).
NOMBRE_ACCION_COMITE = {
    "aprobar": "Aprobó el otorgamiento",
    "rechazar": "Rechazó el expediente",
    "decisiones": "Registró la decisión",
    "decision-borrador": "Guardó un borrador",
    "decision-definitiva": "Registró la decisión definitiva",
    "solicitar-info-adicional": "Solicitó información adicional",
    "observaciones-acta": "Agregó una observación al acta",
    "restricciones-alcance": "Registró una restricción de alcance",
    "comentarios-debate": "Comentó el debate",
    "acta-definitiva": "Generó el acta definitiva",
    "firmar-acta": "Firmó el acta",
    "cerrar-expediente": "Cerró el expediente",
    "reabrir-dictamen": "Reabrió el dictamen",
}

COLUMNAS_EXPORTACION_DECISIONES = [
    Columna("fecha", "Fecha", 17),
    Columna("codigo_expediente", "Expediente", 20),
    Columna("empresa", "Empresa", 28),
    Columna("accion", "Acción", 30, lambda v: NOMBRE_ACCION_COMITE.get(str(v or ""), v)),
    Columna("comentario", "Comentario", 50),
    Columna("usuario", "Registrada por", 24),
    Columna("estado_expediente", "Estado actual del expediente", 18),
]


@router.get("/exportar-decisiones")
async def exportar_decisiones_consolidadas(
    formato: str | None = Query(default=None, description="xlsx (Excel) o pdf; sin valor devuelve JSON"),
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
            e.nombre AS empresa,
            a.accion,
            a.datos->>'comentario' AS comentario,
            CAST(a.datos AS TEXT) AS datos,
            a.id_usuario,
            COALESCE(u.nombre, u.correo, a.id_usuario) AS usuario,
            s.estado AS estado_expediente,
            a.fecha
        FROM comite_accion a
        JOIN solicitud s ON s.id_solicitud = a.id_solicitud
        LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
        LEFT JOIN usuario u ON u.id_usuario::TEXT = a.id_usuario
        ORDER BY a.fecha DESC, a.id_accion DESC;
    """))
    decisiones = [dict(fila) for fila in resultado.mappings().all()]
    if formato:
        return respuesta_exportacion(
            formato,
            titulo="Historial de decisiones del Comité de certificación",
            columnas=COLUMNAS_EXPORTACION_DECISIONES,
            filas=decisiones,
            nombre_base="decisiones-comite",
            hoja="Decisiones",
        )
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-020",
        "permiso": "Exportar decisiones consolidadas",
        "roles_autorizados": ["ADM", "REQ"],
        "decisiones": decisiones,
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
        "roles_autorizados": ["ADM", "AUX"],
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
        "roles_autorizados": ["ADM", "AUX"],
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
        "roles_autorizados": ["ADM", "AUX"],
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
    try:
        expediente_id = UUID(str(payload.get("expediente_id") or payload.get("id_solicitud")))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El campo expediente_id debe ser un UUID válido.",
        )
    comentario = payload.get("comentario")
    if not isinstance(comentario, str) or not comentario.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El comentario es obligatorio para generar el acta.",
        )
    return await ComiteActaService(db).generar(expediente_id, comentario.strip(), current_user)


@router.get("/acta-estado/{expediente_id}")
async def consultar_estado_acta(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar el estado del acta.")
    return await ComiteActaService(db).estado(expediente_id, current_user)


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
    contenido, version = await ComiteActaService(db).descargar_firmada(expediente_id)
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="acta-{expediente_id}-v{version}.pdf"',
            "Cache-Control": "no-store",
        },
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
    try:
        expediente_id = UUID(str(payload.get("expediente_id") or payload.get("id_solicitud")))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El campo expediente_id debe ser un UUID válido.",
        )
    password_firma = payload.get("password_firma")
    if not isinstance(password_firma, str) or not password_firma:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El campo password_firma es obligatorio.",
        )
    return await ComiteActaService(db).firmar(expediente_id, password_firma, current_user)


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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este permiso solo lo puede ejecutar el Coordinador.")
    return await ComiteService(db).registrar_accion("reabrir-dictamen", payload, current_user)
