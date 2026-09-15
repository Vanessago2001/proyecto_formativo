from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


# ============================================================
# INICIAR REGISTRO
# ============================================================

class IniciarRegistroAuditor(BaseModel):
    nombre: str
    tipo_doc: str
    num_doc: str
    correo: str
    password: str

    @field_validator(
        "nombre",
        "tipo_doc",
        "num_doc",
        "correo",
        "password",
    )
    @classmethod
    def limpiar_texto(cls, value):
        return value.strip()


class RegistroAuditorRespuesta(BaseModel):
    id_usuario: UUID
    estado: str
    estado_auditor: str
    mensaje: str


# ============================================================
# DATOS PERSONALES
# ============================================================

class DatosPersonalesAuditor(BaseModel):
    nombre: str
    tipo_doc: str
    num_doc: str
    correo: str

    @field_validator(
        "nombre",
        "tipo_doc",
        "num_doc",
        "correo",
    )
    @classmethod
    def limpiar_texto(cls, value):
        return value.strip()


class DatosPersonalesAuditorRespuesta(BaseModel):
    id_usuario: UUID
    nombre: str
    tipo_doc: str
    num_doc: str
    correo: str
    estado_auditor: str
    mensaje: str


# ============================================================
# PERFIL
# ============================================================

class PerfilAuditorCrear(BaseModel):
    ciudad_residencia: str
    departamento_residencia: str
    modalidad_preferida: str
    foto_url: str
    resumen_profesional: str

    @field_validator(
        "ciudad_residencia",
        "departamento_residencia",
        "modalidad_preferida",
        "foto_url",
        "resumen_profesional",
    )
    @classmethod
    def limpiar_texto(cls, value):
        return value.strip()


# ============================================================
# COMPETENCIAS
# ============================================================

class CompetenciaAuditorCrear(BaseModel):
    id_norma: UUID
    tipo_competencia: str
    codigo_sector_iaf: str
    titulo_institucion: str
    descripcion: str
    fecha_inicio: date
    fecha_fin: date
    es_vigente: bool = False

    @field_validator(
        "tipo_competencia",
        "codigo_sector_iaf",
        "titulo_institucion",
        "descripcion",
    )
    @classmethod
    def limpiar_texto(cls, value):
        return value.strip()

    @model_validator(mode="after")
    def validar_fechas(self):
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError(
                "La fecha de finalización no puede ser anterior "
                "a la fecha de inicio."
            )
        return self


class CompetenciaAuditorActualizar(CompetenciaAuditorCrear):
    pass


# ============================================================
# CONFLICTOS
# ============================================================

class ConflictoInteresCrear(BaseModel):
    id_empresa: UUID
    tipo_conflicto: str
    descripcion: str
    bloquea_asignacion: bool = True

    @field_validator(
        "tipo_conflicto",
        "descripcion",
    )
    @classmethod
    def limpiar_texto(cls, value):
        return value.strip()


class ConflictoInteresActualizar(ConflictoInteresCrear):
    pass


# ============================================================
# DOCUMENTOS
# ============================================================

class DocumentoAuditorCrear(BaseModel):
    nombre_archivo: str
    tipo_documento: str
    url_archivo: str

    @field_validator(
        "nombre_archivo",
        "tipo_documento",
        "url_archivo",
    )
    @classmethod
    def limpiar_texto(cls, value):
        return value.strip()


# ============================================================
# ENVÍO FINAL
# ============================================================

class EnviarSolicitudAuditor(BaseModel):
    id_usuario: UUID
    documento_url_soporte: str

    @field_validator("documento_url_soporte")
    @classmethod
    def limpiar_url(cls, value):
        return value.strip()


class EnviarSolicitudRespuesta(BaseModel):
    id_usuario: UUID
    id_postulacion: UUID
    estado: str
    estado_auditor: str
    mensaje: str
    faltantes: list[str] = Field(default_factory=list)


# ============================================================
# RESPUESTAS DE BORRADOR
# ============================================================

class PerfilAuditorRespuesta(BaseModel):
    ciudad_residencia: str
    departamento_residencia: str
    modalidad_preferida: str
    foto_url: str
    resumen_profesional: str


class CompetenciaAuditorRespuesta(BaseModel):
    id_competencia: UUID
    id_norma: UUID
    tipo_competencia: str
    codigo_sector_iaf: str
    titulo_institucion: str
    descripcion: str
    fecha_inicio: date
    fecha_fin: date
    es_vigente: bool


class ConflictoInteresRespuesta(BaseModel):
    id_conflicto: UUID
    id_empresa: UUID
    tipo_conflicto: str
    descripcion: str
    bloquea_asignacion: bool


class DocumentoAuditorRespuesta(BaseModel):
    id_documento: UUID
    nombre_archivo: str
    tipo_documento: str
    url_archivo: str


class BorradorAuditorRespuesta(BaseModel):
    id_usuario: UUID
    estado: str
    estado_auditor: str

    nombre: str
    tipo_doc: str
    num_doc: str
    correo: str

    perfil: PerfilAuditorRespuesta | None = None

    competencias: list[CompetenciaAuditorRespuesta] = Field(
        default_factory=list
    )

    conflictos: list[ConflictoInteresRespuesta] = Field(
        default_factory=list
    )

    documentos: list[DocumentoAuditorRespuesta] = Field(
        default_factory=list
    )

    documento_url_soporte: str | None = None


# ============================================================
# CONSULTA DE ESTADO
# ============================================================

class ConsultaEstadoAuditorRespuesta(BaseModel):
    id_usuario: UUID | None = None
    id_postulacion: UUID | None = None

    nombre: str
    correo: str
    estado: str

    estado_auditor: str | None = None
    estado_postulacion: str | None = None
    rol: str | None = None


class EstadoAuditorRespuesta(BaseModel):
    id_usuario: UUID
    id_postulacion: UUID

    nombre: str
    correo: str

    estado_usuario: str
    estado_auditor: str | None = None
    estado_postulacion: str