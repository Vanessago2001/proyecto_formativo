from fastapi import APIRouter, Depends, HTTPException, status

from core.security import get_current_user

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
}

COMITE_DECISION_PERMISOS = {
    "superadm",
    "superadmin",
    "superadministrador",
    "adm",
    "admin",
    "administrador",
}

COMITE_SUPERADMIN_ONLY_PERMISOS = {
    "superadm",
    "superadmin",
    "superadministrador",
}


@router.get("/expedientes-pendientes")
async def consultar_expedientes_pendientes(
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-001: consultar expedientes pendientes."""
    role_name = (current_user.get("role_name") or "").strip().lower()

    if role_name not in COMITE_CERTIFICACION_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar expedientes pendientes del comité de certificación.",
        )

    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-001",
        "permiso": "Consultar expedientes pendientes",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expedientes": [],
    }


@router.get("/expediente-completo/{expediente_id}")
async def consultar_expediente_completo(
    expediente_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-002: consultar expediente completo."""
    role_name = (current_user.get("role_name") or "").strip().lower()

    if role_name not in COMITE_CERTIFICACION_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar el expediente completo del comité de certificación.",
        )

    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-002",
        "permiso": "Consultar expediente completo",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expediente_id": expediente_id,
        "expediente": {
            "id": expediente_id,
            "estado": "Pendiente",
            "solicitante": "Empresa demo",
            "documentos": [],
            "observaciones": [],
        },
    }


@router.get("/expediente-descargar/{expediente_id}")
async def descargar_expediente_digital(
    expediente_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-003: descargar expediente digital."""
    role_name = (current_user.get("role_name") or "").strip().lower()

    if role_name not in COMITE_DESCARGA_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para descargar el expediente digital del comité de certificación.",
        )

    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-003",
        "permiso": "Descargar expediente digital",
        "roles_autorizados": ["SUPERADM", "ADM", "REQ"],
        "expediente_id": expediente_id,
        "archivo": {
            "nombre": f"expediente-{expediente_id}.zip",
            "tipo": "application/zip",
            "url": f"/files/{expediente_id}.zip",
        },
    }


@router.get("/informe-auditor/{expediente_id}")
async def consultar_informe_auditor(
    expediente_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-004: consultar informe del auditor."""
    role_name = (current_user.get("role_name") or "").strip().lower()

    if role_name not in COMITE_INFORME_AUDITOR_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar el informe del auditor del comité de certificación.",
        )

    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-004",
        "permiso": "Consultar informe del auditor",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expediente_id": expediente_id,
        "informe": {
            "auditor": "Auditor principal",
            "fecha": "2026-09-07",
            "resultado": "Revisión completada",
            "hallazgos": [],
        },
    }


@router.get("/evidencias-fisicas/{expediente_id}")
async def consultar_evidencias_fisicas(
    expediente_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-005: consultar evidencias físicas."""
    role_name = (current_user.get("role_name") or "").strip().lower()

    if role_name not in COMITE_EVIDENCIAS_FISICAS_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar evidencias físicas del comité de certificación.",
        )

    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-005",
        "permiso": "Consultar evidencias físicas",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expediente_id": expediente_id,
        "evidencias": [
            {
                "tipo": "fotografia",
                "descripcion": "Evidencia física del expediente",
                "ubicacion": "Bodega certificación",
            }
        ],
    }


@router.get("/no-conformidades/{expediente_id}")
async def consultar_no_conformidades(
    expediente_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-006: consultar no conformidades."""
    role_name = (current_user.get("role_name") or "").strip().lower()

    if role_name not in COMITE_NO_CONFORMIDADES_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar las no conformidades del comité de certificación.",
        )

    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-006",
        "permiso": "Consultar no conformidades",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expediente_id": expediente_id,
        "no_conformidades": [
            {
                "codigo": "NC-001",
                "descripcion": "Documentación incompleta",
                "estado": "Abierta",
            }
        ],
    }


@router.get("/historial-solicitudes-previas/{usuario_id}")
async def consultar_historial_solicitudes_previas(
    usuario_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-007: consultar historial de solicitudes previas."""
    role_name = (current_user.get("role_name") or "").strip().lower()

    if role_name not in COMITE_HISTORIAL_SOLICITUDES_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar el historial de solicitudes previas del comité de certificación.",
        )

    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-007",
        "permiso": "Consultar historial solicitudes previas",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "usuario_id": usuario_id,
        "solicitudes_previas": [
            {
                "codigo": "SOL-001",
                "fecha": "2026-08-10",
                "estado": "Aprobada",
            }
        ],
    }


@router.get("/observaciones-tecnicos/{expediente_id}")
async def consultar_observaciones_tecnicos(
    expediente_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-008: consultar observaciones de técnicos."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para consultar observaciones de técnicos del comité.",
        )
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-008",
        "permiso": "Consultar observaciones de técnicos",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "expediente_id": expediente_id,
        "observaciones": [{"tecnico": "Técnico 1", "comentario": "Revisión técnica completada"}],
    }


@router.get("/buscar-expediente")
async def buscar_expediente_por_nit_o_codigo(
    query: str,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-009: buscar expediente por NIT o código."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para buscar expedientes del comité.",
        )
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-009",
        "permiso": "Buscar expediente por NIT o código",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "query": query,
        "resultados": [{"id": "EXP-123", "nit": "900123456-1", "codigo": query}],
    }


@router.get("/filtrar-expedientes")
async def filtrar_expedientes_por_norma_sector(
    norma: str | None = None,
    sector: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-010: filtrar expedientes por norma/sector."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para filtrar expedientes del comité.",
        )
    return {
        "modulo": "M8 — Comité de certificación",
        "codigo": "COM-010",
        "permiso": "Filtrar expedientes por norma/sector",
        "roles_autorizados": ["SUPERADM", "ADM", "AUX"],
        "filtro": {"norma": norma, "sector": sector},
        "resultados": [{"id": "EXP-123", "norma": norma or "ISO 9001", "sector": sector or "Manufactura"}],
    }


@router.post("/decisiones")
async def registrar_decision_certificacion(
    decision: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-011: registrar decisión de certificación."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para registrar decisiones de certificación.",
        )
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-011", "permiso": "Registrar decisión de certificación", "roles_autorizados": ["SUPERADM", "ADM"], "decision": decision}


@router.post("/aprobar")
async def aprobar_otorgamiento(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-012: aprobar otorgamiento."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para aprobar otorgamiento.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-012", "permiso": "Aprobar otorgamiento", "roles_autorizados": ["SUPERADM", "ADM"], "payload": payload}


@router.post("/rechazar")
async def rechazar_otorgamiento(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-013: rechazar / negar otorgamiento."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para rechazar otorgamiento.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-013", "permiso": "Rechazar / Negar otorgamiento", "roles_autorizados": ["SUPERADM", "ADM"], "payload": payload}


@router.post("/solicitar-info-adicional")
async def solicitar_info_adicional_al_auditor(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-014: solicitar info adicional al auditor."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para solicitar información adicional.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-014", "permiso": "Solicitar info adicional al auditor", "roles_autorizados": ["SUPERADM", "ADM"], "payload": payload}


@router.post("/observaciones-acta")
async def registrar_observaciones_en_acta(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-015: registrar observaciones en acta."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para registrar observaciones en acta.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-015", "permiso": "Registrar observaciones en acta", "roles_autorizados": ["SUPERADM", "ADM"], "payload": payload}


@router.post("/restricciones-alcance")
async def registrar_restricciones_de_alcance(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-016: registrar restricciones de alcance."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para registrar restricciones de alcance.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-016", "permiso": "Registrar restricciones de alcance", "roles_autorizados": ["SUPERADM", "ADM"], "payload": payload}


@router.post("/decision-borrador")
async def guardar_decision_borrador(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-017: guardar decisión borrador."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para guardar borrador de decisión.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-017", "permiso": "Guardar decisión borrador", "roles_autorizados": ["SUPERADM", "ADM"], "payload": payload}


@router.post("/decision-definitiva")
async def confirmar_decision_definitiva(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-018: confirmar decisión definitiva."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para confirmar decisión definitiva.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-018", "permiso": "Confirmar decisión definitiva", "roles_autorizados": ["SUPERADM", "ADM"], "payload": payload}


@router.get("/decisiones-historicas")
async def consultar_decisiones_historicas(
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-019: consultar decisiones históricas."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar decisiones históricas.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-019", "permiso": "Consultar decisiones históricas", "roles_autorizados": ["SUPERADM", "ADM", "AUX"], "decisiones": []}


@router.get("/exportar-decisiones")
async def exportar_decisiones_consolidadas(
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-020: exportar decisiones consolidadas."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_CONSULTA_PERMISOS and role_name not in {"req", "requerimiento"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para exportar decisiones consolidadas.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-020", "permiso": "Exportar decisiones consolidadas", "roles_autorizados": ["SUPERADM", "ADM", "REQ"], "archivo": "decisiones_consolidadas.xlsx"}


@router.get("/historial-por-empresa/{empresa_id}")
async def consultar_historial_por_empresa(
    empresa_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-021: consultar historial por empresa."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar historial por empresa.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-021", "permiso": "Consultar historial por empresa", "roles_autorizados": ["SUPERADM", "ADM", "AUX"], "empresa_id": empresa_id, "historial": []}


@router.get("/auditor-responsable/{expediente_id}")
async def consultar_auditor_responsable(
    expediente_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-022: consultar auditor responsable."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar auditor responsable.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-022", "permiso": "Consultar auditor responsable", "roles_autorizados": ["SUPERADM", "ADM", "AUX"], "expediente_id": expediente_id, "auditor": "Auditor principal"}


@router.get("/empresa-evaluada/{empresa_id}")
async def consultar_datos_empresa_evaluada(
    empresa_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-023: consultar datos empresa evaluada."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para consultar datos de la empresa evaluada.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-023", "permiso": "Consultar datos empresa evaluada", "roles_autorizados": ["SUPERADM", "ADM", "AUX"], "empresa_id": empresa_id, "empresa": {"nombre": "Empresa demo", "nit": "900123456-1"}}


@router.post("/comentarios-debate")
async def registrar_comentarios_al_debate(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-024: registrar comentarios al debate."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para registrar comentarios al debate.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-024", "permiso": "Registrar comentarios al debate", "roles_autorizados": ["SUPERADM", "ADM"], "payload": payload}


@router.post("/acta-definitiva")
async def generar_acta_del_comite_definitiva(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-025: generar acta del comité definitiva."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para generar acta definitiva.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-025", "permiso": "Generar acta del comité definitiva", "roles_autorizados": ["SUPERADM", "ADM"], "payload": payload}


@router.get("/acta-firmada/{expediente_id}")
async def descargar_acta_firmada(
    expediente_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-026: descargar acta firmada."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_CONSULTA_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para descargar el acta firmada.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-026", "permiso": "Descargar acta firmada", "roles_autorizados": ["SUPERADM", "ADM", "AUX"], "expediente_id": expediente_id, "archivo": "acta-firmada.pdf"}


@router.post("/firmar-acta")
async def firmar_electronicamente_acta(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-027: firmar electrónicamente acta."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para firmar electrónicamente acta.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-027", "permiso": "Firmar electrónicamente acta", "roles_autorizados": ["SUPERADM", "ADM"], "payload": payload}


@router.post("/cerrar-expediente")
async def cerrar_expediente_de_dictamen(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-028: cerrar expediente de dictamen."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_DECISION_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para cerrar expediente de dictamen.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-028", "permiso": "Cerrar expediente de dictamen", "roles_autorizados": ["SUPERADM", "ADM"], "payload": payload}


@router.post("/reabrir-dictamen")
async def reabrir_dictamen_por_error(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Permiso COM-029: reabrir dictamen por error."""
    role_name = (current_user.get("role_name") or "").strip().lower()
    if role_name not in COMITE_SUPERADMIN_ONLY_PERMISOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este permiso solo lo puede ejecutar un superadministrador.")
    return {"modulo": "M8 — Comité de certificación", "codigo": "COM-029", "permiso": "Reabrir dictamen por error", "roles_autorizados": ["SUPERADM"], "payload": payload}
