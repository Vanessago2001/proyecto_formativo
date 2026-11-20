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
from modules.permisos_auxiliar.regla_auxiliar import exigir_permiso_auxiliar
from modules.solicitudes import estado_solicitud as estados
from modules.comite.comite_service import (
    FILTRO_ESTADO_PENDIENTES,
    FILTRO_ESTADO_TODOS,
    ComiteService,
    construir_filtro_expedientes,
)
from modules.reportes.exportacion_tabular import Columna, respuesta_exportacion
from modules.comite.comite_acta_service import ComiteActaService
from modules.comite.imparcialidad import MENSAJES as MENSAJES_IMPARCIALIDAD
from modules.comite.imparcialidad import aplica_a as imparcialidad_aplica_a
from modules.comite.imparcialidad import exigir_imparcialidad, filtro_visible, id_de, sql_impedimento
from modules.comite import lider_expediente
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
    ciudad: str | None = Query(default=None, max_length=100, description="Ciudad de la empresa o de una sede"),
    departamento: str | None = Query(default=None, max_length=100, description="Departamento de alguna sede"),
    pais: str | None = Query(default=None, max_length=100, description="País de alguna sede"),
    decision: str | None = Query(default=None, description="aprobada o rechazada"),
    firma: str | None = Query(default=None, description="pendiente, firmado, certificado-pendiente o lider-pendiente"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Permiso COM-001: vista unificada de expedientes (pendientes y decididos).

    El filtro de estado decide qué se ve ('pendientes' por defecto, 'todos' o
    un estado). Cada fila trae además la decisión del Comité (quién y
    cuándo), la firma del dictamen y del certificado, y si el miembro del
    Comité está impedido para evaluarla (regla de imparcialidad). Reúne lo
    que antes eran "Expedientes pendientes" e "Historial de decisiones".
    """
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-001", "COM-019")
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_CERTIFICACION_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar expedientes pendientes del comité de certificación.",
        )

    condiciones, params = construir_filtro_expedientes(
        estado, q, norma, fecha_desde, fecha_hasta, ciudad=ciudad, departamento=departamento, pais=pais
    )
    # Imparcialidad: al miembro del Comité impedido no le aparece la fila (ni
    # en los contadores ni en la paginación). Excepción: el líder del comité
    # de ese expediente la ve para firmar (solo_firma).
    if imparcialidad_aplica_a(current_user):
        columna_impedimento = sql_impedimento("s.id_solicitud")
        condiciones += filtro_visible(current_user, "s.id_solicitud", params, permitir_lider=True)
    else:
        columna_impedimento = "CAST(NULL AS TEXT)"
    resultado = await db.execute(text(f"""
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
            s.id_solicitud AS id,
            COALESCE(s.numero_radicado, s.id_solicitud::TEXT) AS codigo,
            e.nombre AS empresa,
            e.nit,
            e.ciudad AS empresa_ciudad,
            -- Ubicación de las sedes incluidas (para las sugerencias de los filtros).
            COALESCE(ARRAY(SELECT DISTINCT se.departamento FROM solicitud_sede ss
                           JOIN sede_empresa se ON se.id_sede = ss.id_sede
                           WHERE ss.id_solicitud = s.id_solicitud AND ss.estado <> 'Excluida'
                             AND se.departamento IS NOT NULL), '{{}}') AS sedes_departamentos,
            COALESCE(ARRAY(SELECT DISTINCT se.pais FROM solicitud_sede ss
                           JOIN sede_empresa se ON se.id_sede = ss.id_sede
                           WHERE ss.id_solicitud = s.id_solicitud AND ss.estado <> 'Excluida'
                             AND se.pais IS NOT NULL), '{{}}') AS sedes_paises,
            n.codigo AS norma,
            s.estado,
            s.fecha_creacion,
            COALESCE(s.fecha_radicacion, s.fecha_creacion) AS fecha_radicacion,
            d.accion, d.comentario, d.fecha AS fecha_decision, d.decidio,
            acta.estado_acta, acta.fecha_firma,
            cert.id_certificado, cert.codigo_verificacion, cert.estado_certificado, cert.certificado_firmado,
            lider.lider_id, lider.lider_nombre, lider.lider_por_expediente,
            {columna_impedimento} AS impedimento
        FROM solicitud s
        LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
        LEFT JOIN norma n ON n.id_norma = s.id_norma
        LEFT JOIN decision d ON d.id_solicitud = s.id_solicitud
        LEFT JOIN acta ON acta.id_solicitud = s.id_solicitud
        -- Un certificado se liga por id_solicitud o por solicitud.id_certificado.
        LEFT JOIN LATERAL (
            SELECT c.id_certificado, c.codigo_verificacion, TRIM(c.estado_certificado) AS estado_certificado,
                   (c.id_firmante IS NOT NULL AND c.huella_firmante IS NOT NULL
                    AND c.codigo_hash IS NOT NULL AND c.huella_pdf IS NOT NULL) AS certificado_firmado
            FROM certificado c
            WHERE c.id_solicitud = s.id_solicitud OR c.id_certificado = s.id_certificado
            ORDER BY c.fecha_registro DESC NULLS LAST
            LIMIT 1
        ) cert ON TRUE
        -- Líder del comité que firma este expediente (o el global sin el SQL).
        LEFT JOIN LATERAL {lider_expediente.sql_lateral_lider('s.id_solicitud')} lider ON TRUE
        WHERE s.deleted_at IS NULL
          -- Los estados vienen del catalogo de M5, no de una lista a mano.{condiciones}
        ORDER BY COALESCE(s.fecha_radicacion, s.fecha_creacion) DESC;
    """), params)
    expedientes = [_fila_expediente_unificada(dict(fila)) for fila in resultado.mappings().all()]
    _marcar_mi_liderazgo(expedientes, current_user)
    expedientes = _filtrar_por_decision_y_firma(expedientes, decision, firma)
    total = len(expedientes)
    inicio = (page - 1) * page_size
    normas = await db.execute(text("SELECT codigo, nombre FROM norma ORDER BY codigo;"))
    # El Coordinador asigna el líder de cada expediente: la pantalla necesita
    # saber si ya se aplicó el SQL (si no, muestra el aviso).
    lider_disponible = None
    if role_name in COMITE_SUPERADMIN_ONLY_PERMISOS:
        lider_disponible = await lider_expediente.modo_por_expediente(db)
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
            "ciudad": ciudad,
            "departamento": departamento,
            "pais": pais,
            "decision": decision,
            "firma": firma,
        },
        "estados_disponibles": [FILTRO_ESTADO_PENDIENTES, FILTRO_ESTADO_TODOS, *estados.ESTADOS],
        "normas": [dict(fila) for fila in normas.mappings().all()],
        "total": total,
        "page": page,
        "page_size": page_size,
        "paginas": max(1, -(-total // page_size)),
        "expedientes": expedientes[inicio:inicio + page_size],
        "lider_por_expediente": lider_disponible,
        "aviso_lider": lider_expediente.MENSAJE_FALTA_SQL if lider_disponible is False else None,
    }


ESTADOS_PENDIENTES_EVALUACION = {estados.RADICADA, estados.EN_REVISION}


def _fila_expediente_unificada(item: dict) -> dict:
    """Completa una fila de la vista unificada: decisión, firmas e imparcialidad."""
    canonico = estados.normalizar(item.get("estado"))
    # Una apelación aprobada revoca el rechazo: la solicitud queda Aprobada.
    item["por_apelacion"] = item.get("accion") == "rechazar" and canonico == estados.APROBADA
    if item["por_apelacion"]:
        item["decision"] = "Aprobada"
    elif item.get("accion") in ("aprobar", "rechazar"):
        item["decision"] = "Aprobada" if item["accion"] == "aprobar" else "Rechazada"
    elif canonico in (estados.APROBADA, estados.RECHAZADA):
        item["decision"] = "Aprobada" if canonico == estados.APROBADA else "Rechazada"
    else:
        item["decision"] = None
    if item["decision"]:
        item["firma_dictamen"] = _estado_firma_dictamen(item.get("estado_acta"))
        item["firma_certificado"] = _estado_firma_certificado(
            item["decision"], item.get("estado_certificado"), item.get("certificado_firmado")
        )
        item["pendiente_firma"] = item["firma_dictamen"] != "Firmado" or item["firma_certificado"] in ("Pendiente de firma", "Sin certificado")
    else:
        item["firma_dictamen"] = item["firma_certificado"] = None
        item["pendiente_firma"] = False
    item["certificado_pendiente_firma"] = str(item.get("estado_certificado") or "").strip().upper() == "PENDIENTE_FIRMA"
    # El acta se puede generar si hay dictamen del Comité (aprobar/rechazar),
    # la solicitud sigue Aprobada o Rechazada y aún no existe acta.
    item["acta_generable"] = bool(
        item["decision"]
        and item.get("accion") in ("aprobar", "rechazar")
        and canonico in (estados.APROBADA, estados.RECHAZADA)
        and not str(item.get("estado_acta") or "").strip()
    )
    # Mismos nombres que el historial (el modal "Ver dictamen" los usa).
    item["expediente_id"] = item.get("id")
    item["codigo_expediente"] = item.get("codigo")
    item["fecha"] = item.get("fecha_decision")
    motivo = item.get("impedimento")
    item["impedimento"] = MENSAJES_IMPARCIALIDAD.get(motivo) if motivo else None
    item["pendiente_evaluacion"] = canonico in ESTADOS_PENDIENTES_EVALUACION
    item["puede_evaluar"] = item["pendiente_evaluacion"] and not item["impedimento"]
    # Un impedido solo ve la fila si es el líder del expediente: para firmar.
    item["solo_firma"] = bool(item["impedimento"])
    item["lider"] = (
        {"id_usuario": str(item["lider_id"]), "nombre": item.get("lider_nombre"),
         "por_expediente": bool(item.get("lider_por_expediente"))}
        if item.get("lider_id") else None
    )
    return item


def _marcar_mi_liderazgo(filas: list[dict], usuario: dict) -> None:
    """
    Marca las filas donde quien consulta es el líder del comité del
    expediente y lo que le toca: generar el acta, firmarla o firmar el
    certificado. Solo el líder ve esas acciones.
    """
    mi_id = str((usuario or {}).get("id_usuario") or (usuario or {}).get("id") or "")
    for item in filas:
        lider = item.get("lider") or {}
        mio = bool(mi_id and str(lider.get("id_usuario") or "") == mi_id)
        estado_acta = str(item.get("estado_acta") or "").strip().upper()
        item["es_mi_liderazgo"] = mio
        item["lider_acta_por_generar"] = mio and item.get("acta_generable", False)
        item["lider_acta_por_firmar"] = mio and estado_acta == "GENERADA"
        item["lider_certificado_por_firmar"] = mio and item.get("certificado_pendiente_firma", False)
        item["lider_pendiente"] = (
            item["lider_acta_por_generar"] or item["lider_acta_por_firmar"] or item["lider_certificado_por_firmar"]
        )


def _filtrar_por_decision_y_firma(filas: list[dict], decision: str | None, firma: str | None) -> list[dict]:
    if decision and decision.strip():
        prefijo = decision.strip().lower()[:6]
        filas = [f for f in filas if f.get("decision") and f["decision"].lower().startswith(prefijo)]
    valor = (firma or "").strip().lower()
    if valor == "firmado":
        filas = [f for f in filas if f.get("decision") and not f["pendiente_firma"]]
    elif valor == "pendiente":
        filas = [f for f in filas if f.get("pendiente_firma")]
    elif valor == "certificado-pendiente":
        filas = [f for f in filas if f.get("certificado_pendiente_firma")]
    elif valor == "lider-pendiente":
        # Lo que espera al líder del comité: actas por generar o firmar y certificados.
        filas = [f for f in filas if f.get("lider_pendiente")]
    return filas


@router.get("/expediente-completo/{expediente_id}")
async def consultar_expediente_completo(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-002: consultar expediente completo."""
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-002")
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_CERTIFICACION_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar el expediente completo del comité de certificación.",
        )
    # Imparcialidad: el miembro del Comité impedido recibe 404 (no se revela que existe).
    await exigir_imparcialidad(db, expediente_id, current_user)

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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-003")
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_DESCARGA_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para descargar el expediente digital del comité de certificación.",
        )
    # Imparcialidad: el miembro del Comité impedido recibe 404 (no se revela que existe).
    await exigir_imparcialidad(db, expediente_id, current_user)

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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-004")
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_INFORME_AUDITOR_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar el informe del auditor del comité de certificación.",
        )
    # Imparcialidad: el miembro del Comité impedido recibe 404 (no se revela que existe).
    await exigir_imparcialidad(db, expediente_id, current_user)

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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-005")
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_EVIDENCIAS_FISICAS_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar evidencias físicas del comité de certificación.",
        )
    # Imparcialidad: el miembro del Comité impedido recibe 404 (no se revela que existe).
    await exigir_imparcialidad(db, expediente_id, current_user)

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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-006")
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_NO_CONFORMIDADES_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar las no conformidades del comité de certificación.",
        )
    # Imparcialidad: el miembro del Comité impedido recibe 404 (no se revela que existe).
    await exigir_imparcialidad(db, expediente_id, current_user)

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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-007")
    role_name = _normalize_role_name(current_user.get("role_name"))

    if role_name not in COMITE_HISTORIAL_SOLICITUDES_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar el historial de solicitudes previas del comité de certificación.",
        )

    params = {"usuario_id": usuario_id}
    oculto = filtro_visible(current_user, "s.id_solicitud", params)
    resultado = await db.execute(text(f"""
        SELECT s.id_solicitud AS id,
               COALESCE(s.numero_radicado, s.id_solicitud::TEXT) AS codigo,
               s.fecha_creacion AS fecha,
               s.estado
        FROM solicitud s
        WHERE s.usuario_creador = :usuario_id
          AND s.deleted_at IS NULL{oculto}
        ORDER BY s.fecha_creacion DESC
        LIMIT 100;
    """), params)
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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-008")
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar observaciones de técnicos del comité.",
        )
    # Imparcialidad: el miembro del Comité impedido recibe 404 (no se revela que existe).
    await exigir_imparcialidad(db, expediente_id, current_user)
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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-009")
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para buscar expedientes del comité.",
        )
    params = {"query": f"%{query.strip()}%"}
    oculto = filtro_visible(current_user, "s.id_solicitud", params)
    resultado = await db.execute(text(f"""
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
          ){oculto}
        ORDER BY s.fecha_creacion DESC
        LIMIT 100;
    """), params)
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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-010")
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
    params = {"norma": f"%{norma.strip()}%" if norma and norma.strip() else None}
    oculto = filtro_visible(current_user, "s.id_solicitud", params)
    resultado = await db.execute(text(f"""
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
          AND (CAST(:norma AS TEXT) IS NULL OR n.codigo ILIKE :norma OR n.nombre ILIKE :norma){oculto}
        ORDER BY s.fecha_creacion DESC
        LIMIT 200;
    """), params)
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
    if borrador.get("creado") and borrador.get("sin_lider"):
        resultado["mensaje"] = (
            f"Solicitud aprobada. Se creó el borrador del certificado {borrador['codigo_verificacion']}, "
            "sin líder del comité: el Coordinador debe elegir el líder de este expediente para que lo firme."
        )
    elif borrador.get("creado"):
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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-019")
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar decisiones históricas.")
    params: dict = {}
    oculto = filtro_visible(current_user, "a.id_solicitud", params)
    resultado = await db.execute(text(f"""
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
        WHERE TRUE{oculto}
        ORDER BY a.fecha DESC, a.id_accion DESC
        LIMIT 500;
    """), params)
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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-019")
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar decisiones históricas.")
    params: dict = {}
    oculto = filtro_visible(current_user, "s.id_solicitud", params)
    resultado = await db.execute(text(f"""
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
          AND (d.id_solicitud IS NOT NULL OR s.estado IN ('Aprobada', 'Rechazada')){oculto}
        ORDER BY COALESCE(d.fecha, s.fecha) DESC NULLS LAST
        LIMIT 2000;
    """), params)
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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-020")
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS and role_name not in {"req", "requerimiento"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para exportar decisiones consolidadas.")
    # Imparcialidad: al miembro impedido no le salen esas decisiones.
    params: dict = {}
    oculto = filtro_visible(current_user, "a.id_solicitud", params)
    resultado = await db.execute(text(f"""
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
        WHERE TRUE{oculto}
        ORDER BY a.fecha DESC, a.id_accion DESC;
    """), params)
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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-021")
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar historial por empresa.")
    params = {"empresa_id": empresa_id}
    oculto = filtro_visible(current_user, "s.id_solicitud", params)
    resultado = await db.execute(text(f"""
        SELECT s.id_solicitud AS id,
               COALESCE(s.numero_radicado, s.id_solicitud::TEXT) AS codigo,
               s.estado,
               s.fecha_creacion,
               s.fecha_radicacion
        FROM solicitud s
        WHERE s.id_empresa = :empresa_id
          AND s.deleted_at IS NULL{oculto}
        ORDER BY s.fecha_creacion DESC
        LIMIT 200;
    """), params)
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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-022")
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar auditor responsable.")
    # Imparcialidad: el miembro del Comité impedido recibe 404 (no se revela que existe).
    await exigir_imparcialidad(db, expediente_id, current_user)
    resultado = await db.execute(text("""
        SELECT u.id_usuario, u.nombre, u.correo,
               'Auditor' AS especialidad, a.estado_asignacion
        FROM auditores_solicitud a
        JOIN solicitud s ON s.id_solicitud = a.id_solicitud
        JOIN usuario u ON u.id_usuario = a.id_auditor
        WHERE a.id_solicitud = :expediente_id
          AND s.deleted_at IS NULL
          AND a.estado_asignacion IN ('Activo', 'Asignado', 'Confirmado')
        ORDER BY a.id
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
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-023")
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
    # El líder del comité del expediente siempre puede generar su acta.
    await exigir_imparcialidad(db, expediente_id, current_user, permitir_lider=True)
    return await ComiteActaService(db).generar(expediente_id, comentario.strip(), current_user)


@router.get("/acta-estado/{expediente_id}")
async def consultar_estado_acta(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-026", "COM-002")
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar el estado del acta.")
    # Vista de firmas: el impedido no la ve (404), salvo el líder del expediente.
    await exigir_imparcialidad(db, expediente_id, current_user, permitir_lider=True)
    return await ComiteActaService(db).estado(expediente_id, current_user)


@router.get("/acta-firmada/{expediente_id}")
async def descargar_acta_firmada(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permiso COM-026: descargar acta firmada."""
    # Auxiliar: solo con el permiso delegado por el Coordinador.
    exigir_permiso_auxiliar(current_user, "COM-026")
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para descargar el acta firmada.")
    await exigir_imparcialidad(db, expediente_id, current_user, permitir_lider=True)
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


# ---------------------------------------------------------------- líder por expediente

@router.get("/lider-expediente/{expediente_id}")
async def consultar_lider_del_expediente(
    expediente_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Líder del comité de este expediente y los candidatos (miembros del Comité
    que participaron en su evaluación en la ronda vigente). Solo Coordinador.
    """
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_SUPERADMIN_ONLY_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el Coordinador elige el líder del comité.")
    return await lider_expediente.consultar(db, expediente_id)


@router.put("/lider-expediente")
async def asignar_lider_del_expediente(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """El Coordinador elige el líder del comité de un expediente (firma su acta y certificado)."""
    role_name = _normalize_role_name(current_user.get("role_name"))
    if role_name not in COMITE_SUPERADMIN_ONLY_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el Coordinador elige el líder del comité.")
    try:
        expediente_id = UUID(str(payload.get("expediente_id")))
        id_usuario = UUID(str(payload.get("id_usuario")))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="expediente_id e id_usuario deben ser UUID válidos.",
        )
    return await lider_expediente.asignar(db, expediente_id, id_usuario, current_user)
