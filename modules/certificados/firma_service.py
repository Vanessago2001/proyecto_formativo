"""Firma digital básica: contraseña de firma independiente de la de inicio de sesión."""

import hashlib
import hmac
import json
import secrets
from uuid import uuid4

from fastapi import HTTPException
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password, validar_password_segura, verify_password

MAX_INTENTOS = 5
MINUTOS_BLOQUEO = 15
MAX_BYTES_BCRYPT = 72


def generar_qr_svg(contenido: str) -> str:
    widget = QrCodeWidget(contenido)
    x1, y1, x2, y2 = widget.getBounds()
    lado = 200
    dibujo = Drawing(lado, lado, transform=[lado / (x2 - x1), 0, 0, lado / (y2 - y1), 0, 0])
    dibujo.add(widget)
    return renderSVG.drawToString(dibujo)


def _validar_largo(password: str) -> None:
    if len(password.encode("utf-8")) > MAX_BYTES_BCRYPT:
        raise HTTPException(status_code=422, detail="La contraseña de firma es demasiado larga.")


def codigo_firma(hash_firma: str, numero_documento: str, id_usuario: str, datos_generales: str) -> str:
    """Código cifrado (HMAC-SHA256) que liga la firma al documento y al usuario."""
    mensaje = f"{numero_documento}|{id_usuario}|{datos_generales}".encode("utf-8")
    return hmac.new(hash_firma.encode("utf-8"), mensaje, hashlib.sha256).hexdigest()


class FirmaService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def estado(self, usuario: dict) -> dict:
        resultado = await self.db.execute(text("""
            SELECT fecha_creacion, fecha_actualizacion
            FROM firma_usuario WHERE id_usuario = :id_usuario;
        """), {"id_usuario": str(usuario["id_usuario"])})
        fila = resultado.mappings().first()
        return {"configurada": fila is not None, "fecha_actualizacion": fila["fecha_actualizacion"] if fila else None}

    async def configurar(self, usuario: dict, password_login: str, password_firma: str) -> dict:
        id_usuario = str(usuario["id_usuario"])
        _validar_largo(password_firma)
        resultado = await self.db.execute(text(
            "SELECT contrasena FROM usuario WHERE id_usuario = :id_usuario;"
        ), {"id_usuario": id_usuario})
        cuenta = resultado.mappings().first()
        if not cuenta or not verify_password(password_login, cuenta["contrasena"]):
            raise HTTPException(status_code=401, detail="La contraseña de inicio de sesión no es correcta.")
        valida, mensaje = validar_password_segura(password_firma)
        if not valida:
            raise HTTPException(status_code=422, detail=mensaje.replace("La contraseña", "La contraseña de firma", 1))

        qr_token = secrets.token_urlsafe(32)
        await self.db.execute(text("""
            INSERT INTO firma_usuario (id_usuario, hash_firma, qr_token)
            VALUES (:id_usuario, :hash_firma, :qr_token)
            ON CONFLICT (id_usuario) DO UPDATE
            SET hash_firma = EXCLUDED.hash_firma,
                qr_token = EXCLUDED.qr_token,
                intentos_fallidos = 0,
                bloqueada_hasta = NULL,
                fecha_actualizacion = CURRENT_TIMESTAMP;
        """), {
            "id_usuario": id_usuario,
            "hash_firma": hash_password(password_firma),
            "qr_token": qr_token,
        })
        await self.db.commit()
        return {"configurada": True, "qr_svg": generar_qr_svg(f"CERTISENA-FIRMA:{qr_token}")}

    async def qr(self, usuario: dict) -> dict:
        resultado = await self.db.execute(text(
            "SELECT qr_token FROM firma_usuario WHERE id_usuario = :id_usuario;"
        ), {"id_usuario": str(usuario["id_usuario"])})
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(status_code=404, detail="Aún no has configurado tu contraseña de firma.")
        return {"qr_svg": generar_qr_svg(f"CERTISENA-FIRMA:{fila['qr_token']}")}

    async def verificar(self, usuario: dict, password_firma: str) -> dict:
        """Compara la contraseña de firma con el hash del usuario autenticado."""
        id_usuario = str(usuario["id_usuario"])
        resultado = await self.db.execute(text("""
            SELECT hash_firma, intentos_fallidos,
                   (bloqueada_hasta IS NOT NULL AND bloqueada_hasta > CURRENT_TIMESTAMP) AS bloqueada
            FROM firma_usuario WHERE id_usuario = :id_usuario
            FOR UPDATE;
        """), {"id_usuario": id_usuario})
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=409,
                detail="Debes configurar tu contraseña de firma antes de firmar documentos.",
            )
        if fila["bloqueada"]:
            await self.db.rollback()
            raise HTTPException(
                status_code=423,
                detail="La firma está bloqueada temporalmente por intentos fallidos. Inténtalo más tarde.",
            )
        valida = len(password_firma.encode("utf-8")) <= MAX_BYTES_BCRYPT and verify_password(
            password_firma, fila["hash_firma"]
        )
        if not valida:
            await self.db.execute(text("""
                UPDATE firma_usuario
                SET intentos_fallidos = intentos_fallidos + 1,
                    bloqueada_hasta = CASE
                        WHEN intentos_fallidos + 1 >= :maximo
                        THEN CURRENT_TIMESTAMP + make_interval(mins => :minutos)
                        ELSE bloqueada_hasta END
                WHERE id_usuario = :id_usuario;
            """), {"id_usuario": id_usuario, "maximo": MAX_INTENTOS, "minutos": MINUTOS_BLOQUEO})
            await self.db.commit()
            raise HTTPException(status_code=401, detail="La contraseña de firma no es correcta.")
        await self.db.execute(text("""
            UPDATE firma_usuario SET intentos_fallidos = 0, bloqueada_hasta = NULL
            WHERE id_usuario = :id_usuario;
        """), {"id_usuario": id_usuario})
        await self.db.commit()
        return {"id_usuario": id_usuario, "hash_firma": fila["hash_firma"]}

    async def registrar_firma(self, id_certificado, certificado: dict, firma: dict) -> None:
        """Guarda el registro de firma asociado al documento (sin hacer commit)."""
        datos = json.dumps({
            "empresa": certificado.get("empresa"),
            "nit": certificado.get("nit"),
            "norma": certificado.get("norma_codigo"),
            "radicado": certificado.get("numero_radicado"),
            "fecha_vencimiento": str(certificado.get("fecha_vencimiento")),
        }, ensure_ascii=False, sort_keys=True)
        numero = str(certificado.get("codigo_verificacion"))
        await self.db.execute(text("""
            INSERT INTO firma_certificado (
                id_firma, id_certificado, id_usuario, numero_documento,
                datos_generales, codigo_firma
            ) VALUES (
                :id_firma, :id_certificado, :id_usuario, :numero, :datos, :codigo
            );
        """), {
            "id_firma": str(uuid4()),
            "id_certificado": str(id_certificado),
            "id_usuario": firma["id_usuario"],
            "numero": numero,
            "datos": datos,
            "codigo": codigo_firma(firma["hash_firma"], numero, firma["id_usuario"], datos),
        })
