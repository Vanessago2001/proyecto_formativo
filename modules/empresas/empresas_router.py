from datetime import date
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import _normalize_role_name, get_current_user, require_role
from modules.aprobaciones.aprobacion_service import AprobacionService
from modules.empresas import empresas_aprobaciones  # noqa: F401  (registra las acciones REQ)
from modules.empresas.documento_empresa_service import (
    ESTADO_APROBADO,
    ESTADO_CORRECCION,
    ESTADO_RECHAZADO,
    TIPOS_DOCUMENTO,
    DocumentoEmpresaService,
)
from modules.empresas.empresas_service import EmpresasService

router = APIRouter(prefix="/api/empresas", tags=["Empresas"])


# ============================================================
# ROLES POR PERMISO (hoja "M3 — EMPRESAS" de permisos.xlsx)
# ============================================================
# APR es el administrador. Una cuenta Empresa, además, solo accede a sus
# propias empresas (EmpresasService.exigir_acceso).

# EMP-003 consultar, EMP-009 historial, EMP-014/015 documentos, EMP-024/030 sedes
ROLES_CONSULTA = ["superadmin", "admin", "auxiliar", "empresa", "auditor", "comite"]
# EMP-004 buscar / EMP-005 filtrar (la empresa usa /mias)
ROLES_BUSQUEDA = ["superadmin", "admin", "auxiliar", "auditor", "comite"]
# EMP-001/002 empresa, EMP-021/022/025/026 sedes, EMP-027/028 contactos
ROLES_GESTION = ["superadmin", "admin", "auxiliar", "empresa"]
# EMP-023 eliminar sede, EMP-029 eliminar contacto
ROLES_ELIMINACION = ["superadmin", "admin", "empresa"]
# EMP-006 cambiar estado, EMP-007 inactivar
ROLES_ESTADO = ["superadmin", "admin"]
# EMP-008 reactivar: exclusivo del SuperAdministrador
ROLES_REACTIVACION = ["superadmin"]
# EMP-016 validar, EMP-017 rechazar, EMP-018 aprobar, EMP-019 pedir corrección:
# la revisión la hace la administración, nunca la propia empresa.
ROLES_REVISION_DOC = ["superadmin", "admin", "auxiliar"]
# Roles con REQ en esas acciones: piden la acción y un superior la aprueba.
ROLES_CON_APROBACION = ["auxiliar"]


def _requiere_aprobacion(usuario: dict) -> bool:
    return _normalize_role_name(usuario.get("role_name")) in ROLES_CON_APROBACION


async def _solicitar_aprobacion(db, usuario: dict, codigo: str, id_empresa: str, datos: dict) -> JSONResponse:
    """Registra la acción como pendiente (REQ) y responde 202 sin ejecutarla."""
    detalle = await EmpresasService(db).validar_accion(codigo, id_empresa, datos)
    aprobacion = await AprobacionService(db).solicitar(codigo, id_empresa, datos, detalle, usuario)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=jsonable_encoder({
            "mensaje": "La acción requiere aprobación de un superior. Quedó registrada como pendiente.",
            "aprobacion": aprobacion,
        }),
    )


class EmpresaCreate(BaseModel):
    nombre: str
    nit: str
    ciudad: str
    direccion: str
    correo: EmailStr


class EmpresaUpdate(BaseModel):
    nombre: str
    nit: str
    ciudad: str
    direccion: str
    correo: EmailStr


class EstadoEmpresaUpdate(BaseModel):
    # 'Inactiva' no se asigna aquí: tiene sus rutas propias (inactivar/reactivar).
    estado: Literal["Activa", "Suspendida"]


class SedeCreate(BaseModel):
    nombre_sede: str
    direccion: str
    ciudad: str
    departamento: Optional[str] = None
    pais: Optional[str] = None
    es_principal: bool = False
    estado: str = "Activa"


class SedeUpdate(BaseModel):
    nombre_sede: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    departamento: Optional[str] = None
    pais: Optional[str] = None
    es_principal: Optional[bool] = None
    estado: Optional[str] = None


class ContactoCreate(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=150)
    cargo: Optional[str] = Field(default=None, max_length=100)
    telefono: Optional[str] = Field(default=None, max_length=30)
    correo: Optional[EmailStr] = None


class ContactoUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=3, max_length=150)
    cargo: Optional[str] = Field(default=None, max_length=100)
    telefono: Optional[str] = Field(default=None, max_length=30)
    correo: Optional[EmailStr] = None


class RevisionDocumento(BaseModel):
    """Cuerpo de EMP-017 (rechazar) y EMP-019 (solicitar corrección)."""

    observaciones: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Motivo del rechazo o corrección pedida. Lo ve la empresa.",
    )


class AprobacionDocumento(BaseModel):
    """Cuerpo de EMP-018 (aprobar). Las observaciones son opcionales."""

    observaciones: Optional[str] = Field(default=None, max_length=1000)


class DireccionSede(BaseModel):
    """Cuerpo de EMP-025 (agregar dirección) y EMP-026 (editarla)."""

    direccion: str = Field(..., min_length=5, max_length=255)


@router.get("/")
async def get_empresas(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_BUSQUEDA))
):
    return await EmpresasService(db).get_all_empresas()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_empresa(
    data: EmpresaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_GESTION))
):
    # Si la registra una cuenta de empresa, queda vinculada a ella (user_empresa).
    es_empresa = _normalize_role_name(current_user.get("role_name")) == "empresa"
    id_usuario = str(current_user.get("id_usuario")) if es_empresa else None
    return await EmpresasService(db).create_empresa(data.model_dump(), id_usuario)


# Debe declararse antes de "/{id_empresa}": si no, "mias" se tomaría como id.
@router.get("/mias")
async def get_mis_empresas(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Empresas a las que está vinculado el usuario autenticado."""
    return await EmpresasService(db).get_empresas_de_usuario(str(current_user.get("id_usuario")))


# La consulta pública (M11) se movió a `modules/consultas_p/`, donde responde
# bajo `/api/consultas-publicas/...` en vez de colgar del prefijo de empresas.


@router.get("/{id_empresa}")
async def get_empresa(
    id_empresa: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_CONSULTA))
):
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    empresa = await servicio.get_empresa_by_id(id_empresa)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return empresa


@router.put("/{id_empresa}")
async def update_empresa(
    id_empresa: str,
    data: EmpresaUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_GESTION))
):
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    updated = await servicio.update_empresa(id_empresa, data.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return updated


# ============================================================
# ESTADO DE LA EMPRESA (EMP-006 / EMP-007 / EMP-008)
# ============================================================

@router.patch("/{id_empresa}/estado", summary="EMP-006 · Cambiar estado de la empresa")
async def cambiar_estado_empresa(
    id_empresa: str,
    data: EstadoEmpresaUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_ESTADO + ROLES_CON_APROBACION))
):
    """Pasa la empresa entre 'Activa' y 'Suspendida'. El Auxiliar solo lo solicita."""
    if _requiere_aprobacion(current_user):
        return await _solicitar_aprobacion(db, current_user, "EMP-006", id_empresa, {"estado": data.estado})
    return await EmpresasService(db).cambiar_estado(id_empresa, data.estado)


@router.post("/{id_empresa}/inactivar", summary="EMP-007 · Inactivar empresa")
async def inactivar_empresa(
    id_empresa: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_ESTADO + ROLES_CON_APROBACION))
):
    if _requiere_aprobacion(current_user):
        return await _solicitar_aprobacion(db, current_user, "EMP-007", id_empresa, {})
    return await EmpresasService(db).inactivar(id_empresa)


@router.post("/{id_empresa}/reactivar", summary="EMP-008 · Reactivar empresa")
async def reactivar_empresa(
    id_empresa: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_REACTIVACION + ROLES_CON_APROBACION))
):
    if _requiere_aprobacion(current_user):
        return await _solicitar_aprobacion(db, current_user, "EMP-008", id_empresa, {})
    return await EmpresasService(db).reactivar(id_empresa)


@router.get("/{id_empresa}/solicitudes")
async def get_historial_empresa(
    id_empresa: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_CONSULTA))
):
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    return await servicio.get_historial_solicitudes_by_empresa(id_empresa)


@router.get("/{id_empresa}/sedes")
async def get_sedes_empresa(
    id_empresa: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_CONSULTA))
):
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    return await servicio.get_sedes_by_empresa(id_empresa)


@router.post("/{id_empresa}/sedes", status_code=status.HTTP_201_CREATED)
async def create_sede_empresa(
    id_empresa: str,
    data: SedeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_GESTION))
):
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    sede = await servicio.create_sede(id_empresa, data.model_dump())
    if not sede:
        raise HTTPException(status_code=404, detail="No se pudo crear la sede")
    return sede


@router.get("/{id_empresa}/sedes/{id_sede}")
async def get_sede_empresa(
    id_empresa: str,
    id_sede: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_CONSULTA))
):
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    sede = await servicio.get_sede_by_id(id_empresa, id_sede)
    if not sede:
        raise HTTPException(status_code=404, detail="Sede no encontrada")
    return sede


@router.put("/{id_empresa}/sedes/{id_sede}", summary="EMP-022 · Editar sede")
async def update_sede_empresa(
    id_empresa: str,
    id_sede: str,
    data: SedeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_GESTION))
):
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    updated = await servicio.update_sede(id_empresa, id_sede, data.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Sede no encontrada")
    return updated


@router.patch(
    "/{id_empresa}/sedes/{id_sede}/direccion",
    summary="EMP-025 · Agregar dirección de sede (EMP-026 si ya tenía)",
)
async def set_direccion_sede(
    id_empresa: str,
    id_sede: str,
    data: DireccionSede,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_GESTION))
):
    """
    Deja la dirección de la sede. La hoja separa registrarla (EMP-025) de
    editarla (EMP-026); aquí es la misma ruta y la respuesta dice cuál de las
    dos ocurrió, para que la pantalla no tenga que adivinarlo.
    """
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)

    sede = await servicio.get_sede_by_id(id_empresa, id_sede)
    if not sede:
        raise HTTPException(status_code=404, detail="Sede no encontrada")

    tenia_direccion = bool((sede.get("direccion") or "").strip())
    actualizada = await servicio.update_sede(id_empresa, id_sede, {"direccion": data.direccion})
    return {
        "permiso": "EMP-026" if tenia_direccion else "EMP-025",
        "accion": "Dirección actualizada" if tenia_direccion else "Dirección registrada",
        "sede": actualizada,
    }


@router.delete("/{id_empresa}/sedes/{id_sede}")
async def delete_sede_empresa(
    id_empresa: str,
    id_sede: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_ELIMINACION + ROLES_CON_APROBACION))
):
    if _requiere_aprobacion(current_user):
        return await _solicitar_aprobacion(db, current_user, "EMP-023", id_empresa, {"id_sede": id_sede})

    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    deleted = await servicio.delete_sede(id_empresa, id_sede)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sede no encontrada")
    return {"message": "Sede eliminada correctamente", "sede": deleted}


# ============================================================
# CONTACTOS DE SEDE (EMP-027 / EMP-028 / EMP-029)
# ============================================================

@router.get("/{id_empresa}/sedes/{id_sede}/contactos", summary="EMP-024 · Consultar contactos de la sede")
async def get_contactos_sede(
    id_empresa: str,
    id_sede: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_CONSULTA))
):
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    return await servicio.get_contactos(id_empresa, id_sede)


@router.post(
    "/{id_empresa}/sedes/{id_sede}/contactos",
    status_code=status.HTTP_201_CREATED,
    summary="EMP-027 · Registrar contacto de sede",
)
async def create_contacto_sede(
    id_empresa: str,
    id_sede: str,
    data: ContactoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_GESTION))
):
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    return await servicio.create_contacto(id_empresa, id_sede, data.model_dump())


@router.put("/{id_empresa}/sedes/{id_sede}/contactos/{id_contacto}", summary="EMP-028 · Editar contacto")
async def update_contacto_sede(
    id_empresa: str,
    id_sede: str,
    id_contacto: str,
    data: ContactoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_GESTION))
):
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    return await servicio.update_contacto(
        id_empresa, id_sede, id_contacto, data.model_dump(exclude_unset=True)
    )


@router.delete("/{id_empresa}/sedes/{id_sede}/contactos/{id_contacto}", summary="EMP-029 · Eliminar contacto")
async def delete_contacto_sede(
    id_empresa: str,
    id_sede: str,
    id_contacto: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_ELIMINACION + ROLES_CON_APROBACION))
):
    if _requiere_aprobacion(current_user):
        return await _solicitar_aprobacion(
            db, current_user, "EMP-029", id_empresa, {"id_sede": id_sede, "id_contacto": id_contacto}
        )

    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    contacto = await servicio.delete_contacto(id_empresa, id_sede, id_contacto)
    return {"message": "Contacto eliminado correctamente", "contacto": contacto}


# ============================================================
# DOCUMENTOS DE SOPORTE (EMP-011 a EMP-020)
# ============================================================


@router.get("/{id_empresa}/documentos", summary="EMP-015 · Consultar documentos de la empresa")
async def get_documentos_empresa(
    id_empresa: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_CONSULTA))
):
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    return await servicio.get_documentos_by_empresa(id_empresa)


@router.get("/{id_empresa}/documentos/tipos", summary="EMP-011 · Tipos de documento admitidos")
async def get_tipos_documento(
    id_empresa: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_CONSULTA))
):
    await EmpresasService(db).exigir_acceso(current_user, id_empresa)
    return {"tipos": list(TIPOS_DOCUMENTO)}


@router.get("/{id_empresa}/documentos/historial", summary="EMP-020 · Historial documental")
async def get_historial_documental(
    id_empresa: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_GESTION))
):
    await EmpresasService(db).exigir_acceso(current_user, id_empresa)
    return await DocumentoEmpresaService(db).historial(UUID(id_empresa))


@router.post(
    "/{id_empresa}/documentos",
    status_code=status.HTTP_201_CREATED,
    summary="EMP-011 · Subir documento de soporte",
)
async def subir_documento_empresa(
    id_empresa: str,
    archivo: UploadFile = File(...),
    tipo_documento: str = Form(...),
    numero_documento: Optional[str] = Form(default=None),
    fecha_expedicion: Optional[date] = Form(default=None),
    fecha_vencimiento: Optional[date] = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_GESTION))
):
    await EmpresasService(db).exigir_acceso(current_user, id_empresa)
    return await DocumentoEmpresaService(db).subir(
        UUID(id_empresa),
        archivo,
        tipo_documento,
        current_user,
        numero_documento=numero_documento,
        fecha_expedicion=fecha_expedicion,
        fecha_vencimiento=fecha_vencimiento,
    )


@router.put("/{id_empresa}/documentos/{id_documento}", summary="EMP-012 · Reemplazar documento")
async def reemplazar_documento_empresa(
    id_empresa: str,
    id_documento: UUID,
    archivo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_GESTION))
):
    await EmpresasService(db).exigir_acceso(current_user, id_empresa)
    return await DocumentoEmpresaService(db).reemplazar(
        UUID(id_empresa), id_documento, archivo, current_user
    )


@router.get(
    "/{id_empresa}/documentos/{id_documento}/archivo",
    response_class=FileResponse,
    summary="EMP-014 · Descargar documento",
)
async def descargar_documento_empresa(
    id_empresa: str,
    id_documento: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_CONSULTA))
):
    await EmpresasService(db).exigir_acceso(current_user, id_empresa)
    servicio = DocumentoEmpresaService(db)
    documento = await servicio._obtener(UUID(id_empresa), id_documento)
    ruta = servicio.ruta_absoluta(documento["url_archivo"] or "")
    if not documento["url_archivo"] or not ruta.is_file():
        raise HTTPException(status_code=404, detail="El archivo ya no está disponible.")
    return FileResponse(path=ruta, filename=documento["nombre_archivo"] or ruta.name)


@router.get(
    "/{id_empresa}/documentos/{id_documento}/validar",
    summary="EMP-016 · Validar documento (automático/manual)",
)
async def validar_documento_empresa(
    id_empresa: str,
    id_documento: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_REVISION_DOC))
):
    await EmpresasService(db).exigir_acceso(current_user, id_empresa)
    return await DocumentoEmpresaService(db).validar(UUID(id_empresa), id_documento)


@router.post("/{id_empresa}/documentos/{id_documento}/aprobar", summary="EMP-018 · Aprobar documento")
async def aprobar_documento_empresa(
    id_empresa: str,
    id_documento: UUID,
    data: AprobacionDocumento,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_REVISION_DOC))
):
    await EmpresasService(db).exigir_acceso(current_user, id_empresa)
    return await DocumentoEmpresaService(db).revisar(
        UUID(id_empresa), id_documento, ESTADO_APROBADO, data.observaciones, current_user
    )


@router.post(
    "/{id_empresa}/documentos/{id_documento}/rechazar",
    summary="EMP-017 · Rechazar documento con motivo",
)
async def rechazar_documento_empresa(
    id_empresa: str,
    id_documento: UUID,
    data: RevisionDocumento,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_REVISION_DOC))
):
    await EmpresasService(db).exigir_acceso(current_user, id_empresa)
    return await DocumentoEmpresaService(db).revisar(
        UUID(id_empresa), id_documento, ESTADO_RECHAZADO, data.observaciones, current_user
    )


@router.post(
    "/{id_empresa}/documentos/{id_documento}/correccion",
    summary="EMP-019 · Solicitar corrección del documento",
)
async def solicitar_correccion_documento(
    id_empresa: str,
    id_documento: UUID,
    data: RevisionDocumento,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_REVISION_DOC))
):
    await EmpresasService(db).exigir_acceso(current_user, id_empresa)
    return await DocumentoEmpresaService(db).revisar(
        UUID(id_empresa), id_documento, ESTADO_CORRECCION, data.observaciones, current_user
    )


@router.get(
    "/{id_empresa}/documentos/{id_documento}/historial",
    summary="EMP-020 · Historial de un documento",
)
async def get_historial_de_documento(
    id_empresa: str,
    id_documento: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_GESTION))
):
    await EmpresasService(db).exigir_acceso(current_user, id_empresa)
    return await DocumentoEmpresaService(db).historial(UUID(id_empresa), id_documento)
