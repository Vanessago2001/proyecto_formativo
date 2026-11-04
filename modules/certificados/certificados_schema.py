from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class CertificadoCrear(BaseModel):
    id_solicitud: UUID
    id_alcance: UUID
    fecha_vencimiento: date


class CertificadoMotivo(BaseModel):
    motivo: str = Field(min_length=5, max_length=1000)


class CertificadoRenovar(BaseModel):
    fecha_vencimiento: date


class CertificadoAlcance(BaseModel):
    id_alcance: UUID


class LiderComiteAsignar(BaseModel):
    id_usuario: UUID


class FirmaConfigurar(BaseModel):
    password_login: str = Field(min_length=1, max_length=128)
    password_firma: str = Field(min_length=8, max_length=128)


class CertificadoFirmar(BaseModel):
    password_firma: str = Field(min_length=1, max_length=128)