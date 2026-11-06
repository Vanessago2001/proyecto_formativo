"""
PQRS · rutas HTTP bajo /api/pqrs.

Rutas públicas (sin sesión) bajo /api/pqrs/publica: radicar, consultar con
radicado + correo, adjuntar, reabrir y descargar adjuntos. Tienen límite de
peticiones por IP. El resto exige sesión; los permisos por rol los decide
PqrsService (ver su docstring).
"""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from modules.pqrs.pqrs_exportacion import formatos_disponibles, respuesta_reporte
from modules.pqrs.pqrs_rate_limit import limitar
from modules.pqrs.pqrs_schema import (
    AsignarResponsable,
    CambiarEstado,
    Comentario,
    ComentarioObligatorio,
    ConsultaPublica,
    PlazoTipo,
    PqrsRadicar,
    Reabrir,
    ReaperturaPublica,
    RegistrarRespuesta,
)
from modules.pqrs.pqrs_service import PqrsService

router = APIRouter(prefix="/api/pqrs", tags=["PQRS"])


def obtener_servicio(db: AsyncSession = Depends(get_db)) -> PqrsService:
    return PqrsService(db)


def _filtros(estado, tipo, desde, hasta, q, semaforo, solo_abiertas=False) -> dict:
    return {
        "estado": estado, "tipo": tipo, "desde": desde, "hasta": hasta,
        "q": (q or "").strip()[:100] or None, "semaforo": semaforo, "abiertas": solo_abiertas,
    }


def _archivos(archivos: list[UploadFile] | None) -> list[UploadFile]:
    return [a for a in (archivos or []) if a is not None and a.filename]


# ======================================================================
# Públicas (sin sesión)
# ======================================================================

@router.get("/catalogos")
async def catalogos(servicio: PqrsService = Depends(obtener_servicio)):
    """Tipos, estados, canales, plazos y reglas de adjuntos (para formularios)."""
    return await servicio.catalogos()


@router.post("/publica/radicar", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(limitar("radicar"))])
async def radicar_publica(datos: PqrsRadicar, servicio: PqrsService = Depends(obtener_servicio)):
    """PQR-001 (PUB): radicar sin sesión. Devuelve el número de radicado."""
    return await servicio.radicar(datos.model_dump(), None)


@router.post("/publica/consultar", dependencies=[Depends(limitar("consultar"))])
async def consultar_publica(datos: ConsultaPublica, servicio: PqrsService = Depends(obtener_servicio)):
    """PQR-003/004/010 (PUB «Propias»): radicado + correo con el que se radicó."""
    return await servicio.consultar_publica(datos.radicado, str(datos.correo))


@router.post("/publica/reabrir", dependencies=[Depends(limitar("reabrir"))])
async def reabrir_publica(datos: ReaperturaPublica, servicio: PqrsService = Depends(obtener_servicio)):
    """PQR-013 (PUB Cond.): 15 días calendario desde el cierre, una sola vez."""
    return await servicio.reabrir_publica(datos.radicado, str(datos.correo), datos.motivo)


@router.post("/publica/adjuntos", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(limitar("adjuntar"))])
async def adjuntar_publica(
    radicado: str = Form(...),
    correo: str = Form(...),
    comentario: Optional[str] = Form(default=None, max_length=2000),
    archivos: list[UploadFile] = File(default=[]),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-011 (PUB Cond.): adjuntar mientras no esté cerrada."""
    consulta = _consulta_publica(radicado, correo)
    return await servicio.adjuntar_publica(consulta.radicado, str(consulta.correo), _archivos(archivos), comentario)


@router.post("/publica/adjuntos/{id_adjunto}", response_class=FileResponse,
             dependencies=[Depends(limitar("consultar"))])
async def descargar_adjunto_publico(
    id_adjunto: UUID,
    datos: ConsultaPublica,
    servicio: PqrsService = Depends(obtener_servicio),
):
    ruta, nombre, tipo = await servicio.archivo_adjunto_publico(datos.radicado, str(datos.correo), id_adjunto)
    return FileResponse(ruta, filename=nombre, media_type=tipo)


def _consulta_publica(radicado: str, correo: str) -> ConsultaPublica:
    try:
        return ConsultaPublica(radicado=radicado, correo=TypeAdapter(EmailStr).validate_python(correo))
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="Radicado o correo con formato no válido.") from error


# ======================================================================
# Con sesión
# ======================================================================

@router.get("/mis-permisos")
async def mis_permisos(
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """Qué códigos PQR puede usar la sesión (la pantalla lo usa para mostrar vistas)."""
    datos = await servicio.permisos_de_sesion(usuario)
    datos["formatos_reporte"] = formatos_disponibles()
    return datos


@router.post("", status_code=status.HTTP_201_CREATED)
async def radicar(
    datos: PqrsRadicar,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-001: empresa, administrador o auxiliar con el permiso delegado."""
    return await servicio.radicar(datos.model_dump(), usuario)


@router.get("")
async def listar(
    estado: Optional[str] = None,
    tipo: Optional[str] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    q: Optional[str] = Query(default=None, max_length=100),
    semaforo: Optional[str] = None,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-003: listado según el alcance del rol."""
    return await servicio.listar(usuario, _filtros(estado, tipo, desde, hasta, q, semaforo))


@router.get("/responsables")
async def responsables(
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-005: personas a las que la sesión puede asignar una PQRS."""
    return await servicio.responsables_disponibles(usuario)


@router.get("/tiempos")
async def tiempos(
    tipo: Optional[str] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-014: semáforo de vencimientos y promedios."""
    return await servicio.tiempos(usuario, _filtros(None, tipo, desde, hasta, None, None))


@router.get("/reporte")
async def reporte(
    formato: str = "json",
    estado: Optional[str] = None,
    tipo: Optional[str] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-015: listado filtrable; formato json, pdf o xlsx (si openpyxl está instalado)."""
    filas = await servicio.reporte(usuario, _filtros(estado, tipo, desde, hasta, None, None))
    if (formato or "json").lower() == "json":
        return {"filas": filas, "total": len(filas), "formatos": formatos_disponibles()}
    partes = [f"Estado: {estado}" if estado else None, f"Tipo: {tipo}" if tipo else None,
              f"Desde: {desde:%d/%m/%Y}" if desde else None, f"Hasta: {hasta:%d/%m/%Y}" if hasta else None]
    subtitulo = " · ".join(p for p in partes if p) or "Todas las PQRS de tu alcance"
    return respuesta_reporte(formato, filas, subtitulo)


@router.get("/plazos")
async def plazos(
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    return (await servicio.catalogos())["plazos"]


@router.put("/plazos/{tipo}")
async def actualizar_plazo(
    tipo: str,
    datos: PlazoTipo,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """Configura el plazo de respuesta (días hábiles) de un tipo. Solo administrador."""
    return await servicio.actualizar_plazo(tipo, datos.dias_habiles, datos.dias_alerta, usuario)


@router.get("/{id_pqrs}")
async def detalle(
    id_pqrs: UUID,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-003: detalle con historial, adjuntos y acciones disponibles."""
    return await servicio.detalle(id_pqrs, usuario)


@router.get("/{id_pqrs}/estado")
async def estado(
    id_pqrs: UUID,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-004."""
    return await servicio.estado(id_pqrs, usuario)


@router.get("/{id_pqrs}/historial")
async def historial(
    id_pqrs: UUID,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-010."""
    return await servicio.historial(id_pqrs, usuario)


@router.post("/{id_pqrs}/asignar")
async def asignar(
    id_pqrs: UUID,
    datos: AsignarResponsable,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-005."""
    return await servicio.asignar(id_pqrs, datos.id_responsable, datos.comentario, usuario)


@router.post("/{id_pqrs}/estado")
async def cambiar_estado(
    id_pqrs: UUID,
    datos: CambiarEstado,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-006."""
    return await servicio.cambiar_estado(id_pqrs, datos.estado, datos.comentario, usuario)


@router.post("/{id_pqrs}/solicitar-informacion")
async def solicitar_informacion(
    id_pqrs: UUID,
    datos: ComentarioObligatorio,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-007 (notifica por correo al peticionario)."""
    return await servicio.solicitar_informacion(id_pqrs, datos.comentario, usuario)


@router.post("/{id_pqrs}/responder")
async def responder(
    id_pqrs: UUID,
    datos: RegistrarRespuesta,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-008 + PQR-009 (correo automático con la respuesta)."""
    return await servicio.responder(id_pqrs, datos.respuesta, usuario)


@router.post("/{id_pqrs}/cerrar")
async def cerrar(
    id_pqrs: UUID,
    datos: Comentario,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-012."""
    return await servicio.cerrar(id_pqrs, datos.comentario, usuario)


@router.post("/{id_pqrs}/reabrir")
async def reabrir(
    id_pqrs: UUID,
    datos: Reabrir,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-013."""
    return await servicio.reabrir(id_pqrs, datos.motivo, usuario)


@router.post("/{id_pqrs}/adjuntos", status_code=status.HTTP_201_CREATED)
async def adjuntar(
    id_pqrs: UUID,
    comentario: Optional[str] = Form(default=None, max_length=2000),
    archivos: list[UploadFile] = File(default=[]),
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    """PQR-011: PDF, JPG, PNG o DOCX de hasta 5 MB."""
    return await servicio.adjuntar(id_pqrs, _archivos(archivos), comentario, usuario)


@router.get("/{id_pqrs}/adjuntos/{id_adjunto}", response_class=FileResponse)
async def descargar_adjunto(
    id_pqrs: UUID,
    id_adjunto: UUID,
    usuario: dict = Depends(get_current_user),
    servicio: PqrsService = Depends(obtener_servicio),
):
    ruta, nombre, tipo = await servicio.archivo_adjunto(id_pqrs, id_adjunto, usuario)
    return FileResponse(ruta, filename=nombre, media_type=tipo)
