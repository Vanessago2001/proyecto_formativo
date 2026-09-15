from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import _normalize_role_name, get_current_user, require_role
from modules.aprobaciones.aprobacion_service import AprobacionService
from modules.empresas import empresas_aprobaciones  # noqa: F401  (registra las acciones REQ)
from modules.empresas.constancia_pdf import generar_pdf_constancia
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


# ============================================================
# CONSULTA PUBLICA (M11) - sin autenticacion
# ============================================================
# Estos tres endpoints se perdieron al integrar los modulos de empresa y
# apelaciones; se restauran tal cual estaban en el commit 353ea89.
#
# OJO: el prefijo del router cambio de "/empresas" a "/api/empresas", asi que
# ahora responden en /api/empresas/... El frontend que los llame debe usar la
# ruta nueva.

@router.get("/consulta-publica")
async def consulta_publica(
    codigo: str = "",
    nit: str = "",
    db: AsyncSession = Depends(get_db),
):
    return await EmpresasService(db).consulta_publica(codigo=codigo, nit=nit)


@router.get("/buscar/{nit}")
async def buscar_empresa_por_nit(
    nit: str,
    db: AsyncSession = Depends(get_db),
):
    return await EmpresasService(db).buscar_por_nit(nit)


@router.get(
    "/constancia/{nit}/pdf",
    summary="Descargar constancia de la empresa en PDF (público)",
    response_class=Response,
)
async def descargar_constancia_pdf(
    nit: str,
    db: AsyncSession = Depends(get_db),
):
    """Devuelve la constancia con los datos de la tarjeta como PDF descargable."""
    empresas = await EmpresasService(db).buscar_por_nit(nit)
    if not empresas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay empresas registradas con ese NIT.",
        )
    empresa = empresas[0]
    pdf = generar_pdf_constancia(empresa)
    nombre_archivo = f"constancia-{empresa.get('nit') or 'empresa'}.pdf"

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre_archivo}"',
        },
    )


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


@router.put("/{id_empresa}/sedes/{id_sede}")
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


@router.get("/{id_empresa}/documentos")
async def get_documentos_empresa(
    id_empresa: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_CONSULTA))
):
    servicio = EmpresasService(db)
    await servicio.exigir_acceso(current_user, id_empresa)
    return await servicio.get_documentos_by_empresa(id_empresa)
