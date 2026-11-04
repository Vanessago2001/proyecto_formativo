from datetime import date, datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)


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
    nombre: str = ""
    ciudad_residencia: str
    departamento_residencia: str
    modalidad_preferida: str
    foto_url: str = ""
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


class PerfilAuditorRespuesta(BaseModel):
    ciudad_residencia: str
    departamento_residencia: str
    modalidad_preferida: str
    foto_url: str
    resumen_profesional: str


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


class CompetenciaAuditorRespuesta(BaseModel):
    id_competencia: UUID
    id_postulacion: UUID | None = None
    id_norma: UUID
    tipo_competencia: str
    codigo_sector_iaf: str
    titulo_institucion: str
    descripcion: str
    fecha_inicio: date
    fecha_fin: date
    es_vigente: bool
    estado_validacion: str | None = None
    observacion_validacion: str | None = None


# ============================================================
# CONFLICTOS DE INTERÉS
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


class ConflictoInteresRespuesta(BaseModel):
    id_conflicto: UUID
    id_empresa: UUID
    tipo_conflicto: str
    descripcion: str
    bloquea_asignacion: bool


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


class DocumentoAuditorRespuesta(BaseModel):
    id_documento: UUID
    id_postulacion: UUID
    nombre_archivo: str
    tipo_documento: str
    url_archivo: str

    # Estos campos permiten mostrar el estado y
    # la observación del administrador.
    fecha_subida: datetime | None = None
    estado_revision: str = "Pendiente"
    observacion_revision: str | None = None


# ============================================================
# TÍTULOS ACADÉMICOS
# ============================================================

class TituloAcademicoCrear(BaseModel):
    nivel: str = Field(
        ...,
        min_length=2,
        max_length=80,
    )

    titulo: str = Field(
        ...,
        min_length=2,
        max_length=255,
    )

    institucion: str = Field(
        ...,
        min_length=2,
        max_length=255,
    )

    fecha_grado: date | None = None

    @field_validator(
        "nivel",
        "titulo",
        "institucion",
    )
    @classmethod
    def limpiar_texto(cls, value):
        return value.strip()


class TituloAcademicoRespuesta(BaseModel):
    id_titulo: UUID
    id_usuario: UUID
    nivel: str
    titulo: str
    institucion: str
    fecha_grado: date | None = None


# ============================================================
# EXPERIENCIA LABORAL
# ============================================================

class ExperienciaLaboralCrear(BaseModel):
    empresa: str = Field(
        ...,
        min_length=2,
        max_length=255,
    )

    cargo: str = Field(
        ...,
        min_length=2,
        max_length=255,
    )

    fecha_inicio: date
    fecha_fin: date | None = None
    descripcion: str = ""

    @field_validator(
        "empresa",
        "cargo",
        "descripcion",
    )
    @classmethod
    def limpiar_texto(cls, value):
        return value.strip()

    @model_validator(mode="after")
    def validar_fechas(self):
        if self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValueError(
                "La fecha final no puede ser anterior "
                "a la fecha inicial."
            )
        return self


class ExperienciaLaboralRespuesta(BaseModel):
    id_experiencia: UUID
    id_usuario: UUID
    empresa: str
    cargo: str
    fecha_inicio: date
    fecha_fin: date | None = None
    descripcion: str = ""


# ============================================================
# EXPERIENCIA EN AUDITORÍA
# ============================================================

class ExperienciaAuditoriaCrear(BaseModel):
    organizacion: str = Field(
        ...,
        min_length=2,
        max_length=255,
    )

    rol_auditoria: str = Field(
        ...,
        min_length=2,
        max_length=150,
    )

    tipo_auditoria: str = Field(
        default="",
        max_length=150,
    )

    fecha_inicio: date
    fecha_fin: date | None = None
    descripcion: str = ""

    @field_validator(
        "organizacion",
        "rol_auditoria",
        "tipo_auditoria",
        "descripcion",
    )
    @classmethod
    def limpiar_texto(cls, value):
        return value.strip()

    @model_validator(mode="after")
    def validar_fechas(self):
        if self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValueError(
                "La fecha final no puede ser anterior "
                "a la fecha inicial."
            )
        return self


class ExperienciaAuditoriaRespuesta(BaseModel):
    id_experiencia: UUID
    id_usuario: UUID
    organizacion: str
    rol_auditoria: str
    tipo_auditoria: str = ""
    fecha_inicio: date
    fecha_fin: date | None = None
    descripcion: str = ""


# ============================================================
# NUEVA POSTULACIÓN
# ============================================================

class NuevaPostulacionRequest(BaseModel):
    id_usuario: UUID


# ============================================================
# ENVÍO FINAL
# ============================================================

class EnviarSolicitudAuditor(BaseModel):
    id_usuario: UUID


class EnviarSolicitudRespuesta(BaseModel):
    id_usuario: UUID
    id_postulacion: UUID
    estado: str
    estado_auditor: str
    mensaje: str
    faltantes: list[str] = Field(
        default_factory=list
    )


# ============================================================
# REENVÍO DE CORRECCIONES
# ============================================================

class ReenviarCorreccionesRequest(BaseModel):
    id_usuario: UUID


# ============================================================
# ESTADO DE POSTULACIÓN
# ============================================================

class PostulacionAuditorEstadoRespuesta(BaseModel):
    id_postulacion: UUID
    estado_postulacion: str
    fecha_postulacion: datetime | None = None


# ============================================================
# BORRADOR
# ============================================================

class BorradorAuditorRespuesta(BaseModel):
    id_usuario: UUID
    id_postulacion: UUID

    estado: str
    estado_auditor: str

    nombre: str
    tipo_doc: str
    num_doc: str
    correo: str

    observaciones_tecnicas: str = ""

    fecha_postulacion: datetime | None = None
    fecha_revision: datetime | None = None

    perfil: PerfilAuditorRespuesta | None = None

    competencias: list[
        CompetenciaAuditorRespuesta
    ] = Field(default_factory=list)

    conflictos: list[
        ConflictoInteresRespuesta
    ] = Field(default_factory=list)

    documentos: list[
        DocumentoAuditorRespuesta
    ] = Field(default_factory=list)

    titulos: list[
        TituloAcademicoRespuesta
    ] = Field(default_factory=list)

    experiencias_laborales: list[
        ExperienciaLaboralRespuesta
    ] = Field(default_factory=list)

    experiencias_auditoria: list[
        ExperienciaAuditoriaRespuesta
    ] = Field(default_factory=list)


# ============================================================
# CONSULTA DE ESTADO POR CORREO
# ============================================================

class ConsultaEstadoAuditorRespuesta(BaseModel):

    id_usuario: UUID | None = None
    id_postulacion: UUID | None = None

    nombre: str
    correo: str

    estado: str | None = None
    estado_usuario: str | None = None
    estado_auditor: str | None = None
    estado_postulacion: str | None = None
    rol: str | None = None

    fecha_postulacion: datetime | None = None
    fecha_revision: datetime | None = None

    tiene_correcciones: bool = False

    observaciones_correccion: str | None = None

    observaciones_rechazo: str | None = None

    administrador_correccion: str | None = None

    fecha_correccion: datetime | None = None

    estado_anterior_correccion: str | None = None


# ============================================================
# ESTADO POR ID DE POSTULACIÓN
# ============================================================

class EstadoAuditorRespuesta(BaseModel):
    id_usuario: UUID
    id_postulacion: UUID

    nombre: str
    correo: str

    estado_usuario: str
    estado_auditor: str | None = None
    estado_postulacion: str