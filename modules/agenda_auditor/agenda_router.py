from datetime import date, datetime, time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.agenda_auditor.agenda_schema import (
    CancelarProgramacion,
    DisponibilidadEditar,
    DisponibilidadExtraordinariaCrear,
    DisponibilidadSemanalCrear,
    FechaNoDisponibleCrear,
    ProgramacionAuditoriaCrear,
    ReprogramarProgramacion,
)
from modules.agenda_auditor.agenda_service import AgendaAuditorService
from modules.solicitudes.solicitud_permissions import (
    ROL_SUPERADM,
    normalizar_rol,
    requiere_permiso,
)

router = APIRouter(prefix="/agenda-auditor", tags=["Agenda del auditor"])

_ROLES_ADMIN_AGENDA = {"ADM", "ADMIN", "ADMINISTRADOR", str(ROL_SUPERADM).upper(), "SUPERADM"}


def _es_administrador(usuario: dict) -> bool:
    rol = normalizar_rol(usuario.get("role_name") or usuario.get("rol") or "")
    return str(rol).strip().upper() in _ROLES_ADMIN_AGENDA


async def _validar_administrador(usuario: dict = Depends(requiere_permiso("SOL-006"))):
    """Reutiliza autenticación/permisos del proyecto y restringe la programación a administración."""
    if not _es_administrador(usuario):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un administrador puede administrar la programación de auditorías.",
        )
    return usuario


async def _validar_admin_o_propio_auditor(
    id_usuario: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-006")),
):
    if _es_administrador(usuario):
        return usuario
    id_autenticado = usuario.get("id_usuario")
    if not id_autenticado or str(id_autenticado) != str(id_usuario):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes consultar o administrar tu propia agenda.",
        )
    return usuario


# Las rutas literales van antes de /{id_usuario} para evitar conflictos.
@router.get("/bloqueos/vigentes")
async def listar_bloqueos_vigentes(
    usuario: dict = Depends(requiere_permiso("SOL-006")),
    db: AsyncSession = Depends(get_db),
):
    return {"bloqueos": await AgendaAuditorService(db).listar_bloqueos_activos()}


@router.get("/disponibilidad-mensual-general")
async def disponibilidad_mensual_general(
    anio: int = Query(..., ge=2000, le=2100),
    mes: int = Query(..., ge=1, le=12),
    ciudad: str | None = Query(None, max_length=150),
    modalidad: str | None = Query(None, max_length=30),
    usuario: dict = Depends(requiere_permiso("SOL-006")),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).ver_disponibilidad_mensual_general(
        anio=anio, mes=mes, ciudad=ciudad, modalidad=modalidad
    )


@router.get("/solicitudes-asignadas/{id_usuario}")
async def solicitudes_asignadas_auditor(
    id_usuario: UUID,
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    return {"asignaciones": await AgendaAuditorService(db).listar_asignaciones_programables_auditor(id_usuario)}

@router.get("/programaciones")
async def listar_todas_programaciones(
    desde: date | None = None,
    hasta: date | None = None,
    ciudad: str | None = None,
    modalidad: str | None = None,
    estado: str | None = None,
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    return {"programaciones": await AgendaAuditorService(db).listar_todas_programaciones(desde, hasta, ciudad, modalidad, estado)}


@router.get(
    "/programaciones-futuras",
    summary="Programaciones futuras (hoy + N días) de todos los auditores",
)
async def listar_programaciones_futuras(
    dias: int = Query(7, ge=1, le=365, description="Días desde hoy a partir de los cuales se consideran futuras"),
    estado: str | None = Query(None, max_length=40),
    ciudad: str | None = Query(None, max_length=150),
    modalidad: str | None = Query(None, max_length=40),
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    """
    Programaciones cuya fecha de inicio sea igual o superior a hoy + `dias`.

    Alcance administrativo: incluye la programación de todos los auditores.
    """
    return {
        "programaciones": await AgendaAuditorService(db).listar_programaciones_futuras(
            dias=dias, estado=estado, ciudad=ciudad, modalidad=modalidad
        ),
        "dias": dias,
    }


@router.get(
    "/{id_usuario}/programaciones-futuras",
    summary="Programaciones futuras asignadas a un auditor",
)
async def listar_programaciones_futuras_auditor(
    id_usuario: UUID,
    dias: int = Query(7, ge=1, le=365, description="Días desde hoy a partir de los cuales se consideran futuras"),
    estado: str | None = Query(None, max_length=40),
    ciudad: str | None = Query(None, max_length=150),
    modalidad: str | None = Query(None, max_length=40),
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    """
    Programaciones futuras del auditor indicado.

    Un auditor solo puede consultar las suyas propias; el administrador puede
    consultar las de cualquier auditor.
    """
    return {
        "programaciones": await AgendaAuditorService(db).listar_programaciones_futuras(
            dias=dias, id_usuario=id_usuario, estado=estado, ciudad=ciudad, modalidad=modalidad
        ),
        "dias": dias,
    }


@router.get(
    "/programacion/{id_programacion}/detalle",
    summary="Detalle completo de una programación",
)
async def detalle_programacion(
    id_programacion: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-006")),
    db: AsyncSession = Depends(get_db),
):
    """
    Detalle de la programación: solicitud, empresa, sede y auditores.

    El administrador puede ver cualquier programación; el auditor solo las
    que tiene asignadas.
    """
    if not _es_administrador(usuario):
        id_autenticado = usuario.get("id_usuario")
        asignado = await db.execute(
            text("""
                SELECT 1
                FROM detalle_programacion_auditor
                WHERE id_programacion = :id_programacion
                  AND id_usuario = :id_usuario
                LIMIT 1
            """),
            {"id_programacion": str(id_programacion), "id_usuario": str(id_autenticado)},
        )
        if not asignado.first():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes consultar las programaciones donde estás asignado.",
            )
    return await AgendaAuditorService(db).consultar_detalle_programacion(id_programacion)

@router.get("/auditores")
async def listar_auditores(
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    return {"auditores": await AgendaAuditorService(db).listar_auditores_activos()}


@router.get("/solicitudes-disponibles")
async def solicitudes_disponibles(
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    return {"asignaciones": await AgendaAuditorService(db).listar_asignaciones_programables()}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def crear_programacion(
    data: ProgramacionAuditoriaCrear,
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).crear_programacion(data)


@router.get(
    "/programacion/auditores-disponibles",
    summary="Auditores disponibles para asignar a una sede concreta",
)
async def listar_auditores_disponibles_para_sede(
    id_solicitud: UUID,
    id_sede: UUID | None = Query(default=None),
    fecha: date | None = Query(default=None),
    hora_inicio: time | None = Query(default=None),
    hora_fin: time | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    buscar: str | None = Query(default=None, max_length=120),
    ciudad: str | None = Query(default=None, max_length=100),
    modalidad: str | None = Query(default=None, max_length=40),
    competencia: str | None = Query(default=None, pattern="^(si|no)$"),
    conflicto: str | None = Query(default=None, pattern="^(si|no)$"),
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    """
    Lista los auditores que pueden asignarse a la sede seleccionada.

    Aplica las mismas validaciones de "Asignación de Auditores" (competencia
    en la norma y conflicto de interés) y las de la Agenda (disponibilidad y
    cruces de horario) cuando se informa la fecha/hora de la visita.
    """
    return await AgendaAuditorService(db).listar_auditores_disponibles_para_sede(
        id_solicitud=id_solicitud,
        id_sede=id_sede,
        fecha=fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        page=page,
        page_size=page_size,
        buscar=buscar,
        ciudad=ciudad,
        modalidad=modalidad,
        competencia=competencia,
        conflicto=conflicto,
    )


@router.get("/{id_usuario}/disponibilidad")
async def consultar_disponibilidad(
    id_usuario: UUID,
    fecha: date,
    hora_inicio: time = Query(..., description="Hora local HH:MM"),
    hora_fin: time = Query(..., description="Hora local HH:MM"),
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    inicio = datetime.combine(fecha, hora_inicio)
    fin = datetime.combine(fecha, hora_fin)
    return await AgendaAuditorService(db).consultar_disponibilidad(id_usuario, fecha, inicio, fin)


@router.post("/{id_usuario}/disponibilidad-semanal", status_code=status.HTTP_201_CREATED)
async def configurar_disponibilidad_semanal(
    id_usuario: UUID,
    data: DisponibilidadSemanalCrear,
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).configurar_disponibilidad_semanal(id_usuario, data)


@router.post("/{id_usuario}/no-disponible", status_code=status.HTTP_201_CREATED)
async def registrar_fecha_no_disponible(
    id_usuario: UUID,
    data: FechaNoDisponibleCrear,
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).registrar_fecha_no_disponible(id_usuario, data)


@router.delete("/{id_usuario}/no-disponible", status_code=status.HTTP_200_OK)
async def desbloquear_fecha_no_disponible(
    id_usuario: UUID,
    fecha: date = Query(..., description="Fecha a desbloquear"),
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).desbloquear_fecha_no_disponible(id_usuario, fecha)


@router.post("/{id_usuario}/disponibilidad-extraordinaria", status_code=status.HTTP_201_CREATED)
async def registrar_disponibilidad_extraordinaria(
    id_usuario: UUID,
    data: DisponibilidadExtraordinariaCrear,
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).registrar_disponibilidad_extraordinaria(id_usuario, data)


@router.get("/{id_usuario}/disponibilidades")
async def consultar_disponibilidades(
    id_usuario: UUID,
    desde: date | None = None,
    hasta: date | None = None,
    tipo_registro: str | None = None,
    incluir_inactivos: bool = True,
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    if desde and hasta and hasta < desde:
        raise HTTPException(status_code=422, detail="La fecha 'hasta' no puede ser anterior a 'desde'.")
    return {
        "disponibilidad": await AgendaAuditorService(db).consultar_agenda(
            id_usuario, desde, hasta, tipo_registro, incluir_inactivos
        )
    }


@router.put("/{id_usuario}/disponibilidad/{id_disponibilidad}")
async def editar_disponibilidad(
    id_usuario: UUID,
    id_disponibilidad: UUID,
    data: DisponibilidadEditar,
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).editar_disponibilidad(id_usuario, id_disponibilidad, data)


@router.delete("/{id_usuario}/disponibilidad/{id_disponibilidad}", status_code=status.HTTP_200_OK)
async def eliminar_disponibilidad(
    id_usuario: UUID,
    id_disponibilidad: UUID,
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).eliminar_disponibilidad(id_usuario, id_disponibilidad)


@router.get("/{id_usuario}/bitacora-validacion")
async def consultar_bitacora_validacion(
    id_usuario: UUID,
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).consultar_bitacora_validacion(id_usuario)


@router.get("/{id_usuario}/historial-disponibilidad")
async def historial_disponibilidad(
    id_usuario: UUID,
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    return {"historial": await AgendaAuditorService(db).consultar_historial_disponibilidad(id_usuario)}


@router.get("/{id_usuario}/disponibilidad-mensual")
async def disponibilidad_mensual(
    id_usuario: UUID,
    anio: int = Query(..., ge=2000, le=2100),
    mes: int = Query(..., ge=1, le=12),
    ciudad: str | None = Query(None, max_length=150),
    modalidad: str | None = Query(None, max_length=30),
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    if modalidad and modalidad.strip().lower() not in {"presencial", "remota", "híbrida"}:
        raise HTTPException(status_code=422, detail="La modalidad debe ser Presencial, Remota o Híbrida.")
    return await AgendaAuditorService(db).ver_disponibilidad_mensual(
        id_usuario, anio, mes, ciudad, modalidad
    )


@router.get("/{id_usuario}/programacion/{id_programacion}/dias")
async def dias_programacion(
    id_usuario: UUID,
    id_programacion: UUID,
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).consultar_dias_programacion(id_usuario, id_programacion)


@router.get("/{id_usuario}")
async def agenda(
    id_usuario: UUID,
    desde: date | None = None,
    hasta: date | None = None,
    ciudad: str | None = Query(None, max_length=150),
    modalidad: str | None = Query(None, max_length=30),
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    if desde and hasta and hasta < desde:
        raise HTTPException(status_code=422, detail="La fecha 'hasta' no puede ser anterior a 'desde'.")
    service = AgendaAuditorService(db)
    disponibilidad = await service.consultar_agenda(id_usuario, desde, hasta)
    auditorias = await service.consultar_auditorias_programadas(
        id_usuario, desde, hasta, ciudad, modalidad
    )
    # "agenda" conserva la clave que exponía la ruta original.
    return {
        "agenda": disponibilidad,
        "disponibilidad": disponibilidad,
        "auditorias": auditorias,
    }


@router.get("/{id_usuario}/auditorias-programadas")
async def auditorias_programadas(
    id_usuario: UUID,
    desde: date | None = None,
    hasta: date | None = None,
    ciudad: str | None = Query(None, max_length=150),
    modalidad: str | None = Query(None, max_length=30),
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    if desde and hasta and hasta < desde:
        raise HTTPException(status_code=422, detail="La fecha 'hasta' no puede ser anterior a 'desde'.")
    if modalidad and modalidad.strip().lower() not in {"presencial", "remota", "híbrida"}:
        raise HTTPException(status_code=422, detail="La modalidad debe ser Presencial, Remota o Híbrida.")
    return {
        "auditorias": await AgendaAuditorService(db).consultar_auditorias_programadas(
            id_usuario, desde, hasta, ciudad, modalidad
        )
    }


@router.get("/{id_usuario}/notificaciones")
async def notificaciones_auditor(
    id_usuario: UUID,
    usuario: dict = Depends(_validar_admin_o_propio_auditor),
    db: AsyncSession = Depends(get_db),
):
    return {"notificaciones": await AgendaAuditorService(db).consultar_notificaciones(id_usuario)}


@router.post("/programacion/{id_programacion}/confirmar")
async def confirmar_programacion(
    id_programacion: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-006")),
    db: AsyncSession = Depends(get_db),
):
    es_admin = _es_administrador(usuario)
    id_usuario = usuario.get("id_usuario")
    try:
        id_usuario_uuid = UUID(str(id_usuario)) if id_usuario else None
    except (ValueError, TypeError):
        id_usuario_uuid = None
    return await AgendaAuditorService(db).confirmar_programacion(
        id_programacion, id_usuario_uuid, es_admin
    )


@router.post("/programacion/{id_programacion}/solicitar-reprogramacion")
async def solicitar_reprogramacion(
    id_programacion: UUID,
    data: dict,
    usuario: dict = Depends(requiere_permiso("SOL-006")),
    db: AsyncSession = Depends(get_db),
):
    es_admin = _es_administrador(usuario)
    id_usuario = usuario.get("id_usuario")
    try:
        id_usuario_uuid = UUID(str(id_usuario)) if id_usuario else None
    except (ValueError, TypeError):
        id_usuario_uuid = None
    return await AgendaAuditorService(db).solicitar_reprogramacion(
        id_programacion,
        id_usuario_uuid,
        es_admin,
        str(data.get("motivo") or "").strip(),
    )


@router.post("/programacion/{id_programacion}/cancelar")
async def cancelar_programacion(
    id_programacion: UUID,
    data: CancelarProgramacion,
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).cancelar_programacion(id_programacion, data.motivo)


@router.post("/programacion/{id_programacion}/reprogramar")
async def reprogramar_programacion(
    id_programacion: UUID,
    data: ReprogramarProgramacion,
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).reprogramar_programacion(
        id_programacion, data.fecha_inicio, data.fecha_fin, data.motivo
    )


@router.put("/programacion/{id_programacion}")
async def editar_programacion(
    id_programacion: UUID,
    data: dict,
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    try:
        fecha_inicio = datetime.fromisoformat(data["fecha_inicio"]) if data.get("fecha_inicio") else None
        fecha_fin = datetime.fromisoformat(data["fecha_fin"]) if data.get("fecha_fin") else None
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Formato de fecha/hora inválido: {exc}",
        )
    return await AgendaAuditorService(db).editar_programacion(
        id_programacion,
        data.get("modalidad"),
        data.get("ciudad_servicio"),
        fecha_inicio,
        fecha_fin,
        data.get("direccion_servicio"),
        data.get("observacion"),
    )


@router.post("/programacion/{id_programacion}/rechazar-reprogramacion")
async def rechazar_reprogramacion(
    id_programacion: UUID,
    data: dict,
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).rechazar_solicitud_reprogramacion(
        id_programacion, str(data.get("motivo") or "").strip()
    )


@router.post("/programacion/{id_programacion}/resolver-reprogramacion")
async def resolver_reprogramacion(
    id_programacion: UUID,
    data: dict,
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    id_usuario = data.get("id_usuario")
    fecha = data.get("fecha")
    fecha_parsed = None
    if fecha:
        try:
            fecha_parsed = date.fromisoformat(str(fecha)[:10])
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="La fecha indicada no es válida.")
    id_usuario_uuid = None
    if id_usuario:
        try:
            id_usuario_uuid = UUID(str(id_usuario))
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="El auditor indicado no es válido.")
    return await AgendaAuditorService(db).resolver_solicitud_reprogramacion(
        id_programacion,
        str(data.get("accion") or "").strip(),
        id_usuario_uuid,
        fecha_parsed,
        str(data.get("motivo") or "").strip(),
    )


@router.post("/programacion/{id_programacion}/notificar")
async def notificar_programacion(
    id_programacion: UUID,
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).notificar_programacion(id_programacion)
