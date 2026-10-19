from datetime import date, datetime, time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).confirmar_programacion(id_programacion)


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


@router.post("/programacion/{id_programacion}/notificar")
async def notificar_programacion(
    id_programacion: UUID,
    usuario: dict = Depends(_validar_administrador),
    db: AsyncSession = Depends(get_db),
):
    return await AgendaAuditorService(db).notificar_programacion(id_programacion)
