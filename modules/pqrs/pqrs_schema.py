"""Esquemas Pydantic V2 del módulo PQRS."""

from __future__ import annotations

import re
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from modules.pqrs.pqrs_reglas import (
    RADICADO_PATRON,
    TIPOS_DOCUMENTO,
    ReglaPqrsError,
    normalizar_canal,
    normalizar_tipo,
)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _limpiar(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None
    texto = _CONTROL.sub("", str(valor)).strip()
    return texto or None


class _Base(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")


class PqrsRadicar(_Base):
    """Datos del formulario de radicación (PQR-001)."""

    tipo: str
    asunto: str = Field(..., min_length=5, max_length=200)
    descripcion: str = Field(..., min_length=20, max_length=5000)
    nombre_peticionario: str = Field(..., min_length=3, max_length=150)
    tipo_documento: str
    numero_documento: str = Field(..., min_length=4, max_length=20)
    correo: EmailStr
    telefono: Optional[str] = Field(default=None, max_length=20)
    empresa_nombre: Optional[str] = Field(default=None, max_length=200)
    nit: Optional[str] = Field(default=None, max_length=20)
    acepta_tratamiento_datos: bool
    # Solo para usuarios con sesión: vínculo opcional con una empresa o una
    # auditoría (lo usa el auditor para ver las PQRS de sus auditorías).
    id_empresa: Optional[UUID] = None
    id_auditoria: Optional[UUID] = None
    # Canal de recepción: el auxiliar/administrador que radica en nombre de un
    # ciudadano indica si fue presencial, telefónico o por correo.
    canal: Optional[str] = None
    # Campo trampa: los formularios lo dejan oculto y vacío; un robot lo llena.
    sitio_web: Optional[str] = Field(default=None, max_length=200)

    @field_validator("tipo")
    @classmethod
    def _tipo(cls, valor: str) -> str:
        try:
            return normalizar_tipo(valor)
        except ReglaPqrsError as error:
            raise ValueError(str(error)) from error

    @field_validator("canal")
    @classmethod
    def _canal(cls, valor: Optional[str]) -> Optional[str]:
        if not valor:
            return None
        try:
            return normalizar_canal(valor)
        except ReglaPqrsError as error:
            raise ValueError(str(error)) from error

    @field_validator("tipo_documento")
    @classmethod
    def _tipo_documento(cls, valor: str) -> str:
        for opcion in TIPOS_DOCUMENTO:
            if opcion.lower() == (valor or "").strip().lower():
                return opcion
        raise ValueError("Tipo de documento no válido.")

    @field_validator("numero_documento")
    @classmethod
    def _numero_documento(cls, valor: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9\-]{4,20}", valor or ""):
            raise ValueError("El número de documento solo admite letras, números y guiones (4 a 20).")
        return valor.upper()

    @field_validator("telefono")
    @classmethod
    def _telefono(cls, valor: Optional[str]) -> Optional[str]:
        valor = _limpiar(valor)
        if valor and not re.fullmatch(r"[0-9+\-() ]{7,20}", valor):
            raise ValueError("El teléfono solo admite números, espacios, +, - y paréntesis.")
        return valor

    @field_validator("nit")
    @classmethod
    def _nit(cls, valor: Optional[str]) -> Optional[str]:
        valor = _limpiar(valor)
        if valor and not re.fullmatch(r"[0-9\-.]{5,20}", valor):
            raise ValueError("El NIT solo admite números, puntos y guion.")
        return valor

    @field_validator("asunto", "descripcion", "nombre_peticionario", "empresa_nombre")
    @classmethod
    def _texto(cls, valor: Optional[str]) -> Optional[str]:
        return _limpiar(valor)

    @field_validator("acepta_tratamiento_datos")
    @classmethod
    def _acepta(cls, valor: bool) -> bool:
        if valor is not True:
            raise ValueError("Debes aceptar la política de tratamiento de datos personales.")
        return valor


class ConsultaPublica(_Base):
    """Radicado + correo con el que se radicó (ambos deben coincidir)."""

    radicado: str = Field(..., min_length=10, max_length=30)
    correo: EmailStr

    @field_validator("radicado")
    @classmethod
    def _radicado(cls, valor: str) -> str:
        valor = (valor or "").strip().upper()
        if not RADICADO_PATRON.fullmatch(valor):
            raise ValueError("El radicado tiene la forma PQRS-AAAA-000001.")
        return valor


class ReaperturaPublica(ConsultaPublica):
    motivo: str = Field(..., min_length=10, max_length=2000)


class Comentario(_Base):
    comentario: Optional[str] = Field(default=None, max_length=2000)


class ComentarioObligatorio(_Base):
    comentario: str = Field(..., min_length=10, max_length=2000)


class AsignarResponsable(_Base):
    id_responsable: UUID
    comentario: Optional[str] = Field(default=None, max_length=2000)


class CambiarEstado(_Base):
    estado: str
    comentario: Optional[str] = Field(default=None, max_length=2000)


class RegistrarRespuesta(_Base):
    respuesta: str = Field(..., min_length=20, max_length=10000)


class Reabrir(_Base):
    motivo: str = Field(..., min_length=10, max_length=2000)


class PlazoTipo(_Base):
    dias_habiles: int = Field(..., ge=1, le=90)
    dias_alerta: int = Field(default=3, ge=0, le=30)
