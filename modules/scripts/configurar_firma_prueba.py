"""
Configura una firma digital de PRUEBA para el líder vigente del Comité.

Solo para desarrollo y demostraciones: crea, en este computador,
  - una autoridad certificadora de prueba (ca_prueba.pem),
  - el certificado PKCS#12 del líder (<id_usuario>.p12) con su correo,
y escribe en el .env las tres variables que usa la firma PAdES:
  CERTIFICADOS_FIRMA_DIR, CERTIFICADOS_FIRMA_PASSWORDS_JSON y
  CERTIFICADOS_FIRMA_TRUST_ROOTS_JSON.

Los archivos quedan FUERA del proyecto (por defecto en ~/.certisena_firma),
así que nunca se suben a git. La contraseña del .p12 se genera al azar y no
se muestra. En producción el .p12 lo emite una entidad certificadora real.

Uso (desde la carpeta del proyecto):
    venv\\Scripts\\python.exe -m modules.scripts.configurar_firma_prueba
    venv\\Scripts\\python.exe -m modules.scripts.configurar_firma_prueba --forzar
    venv\\Scripts\\python.exe -m modules.scripts.configurar_firma_prueba --directorio D:/firma --sin-env

Solo lee la base de datos (SELECT del líder vigente); no la modifica.
Después de ejecutarlo, reinicie el servidor para que lea el .env.
"""

import argparse
import asyncio
import json
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from sqlalchemy import text

from core.database import AsyncSessionLocal

ARCHIVO_ENV = Path(".env")
MARCA_ENV = "# Firma digital de PRUEBA (solo desarrollo)"


async def lider_vigente() -> dict:
    async with AsyncSessionLocal() as sesion:
        resultado = await sesion.execute(text("""
            SELECT u.id_usuario, u.correo, u.nombre
            FROM asignacion_lider_comite a
            JOIN usuario u ON u.id_usuario = a.id_usuario
            WHERE a.fecha_fin IS NULL
            ORDER BY a.fecha_inicio DESC
            LIMIT 1;
        """))
        fila = resultado.mappings().first()
    if not fila:
        sys.exit("No hay un líder del Comité asignado. Asígnelo en Gestión de certificados y vuelva a intentarlo.")
    return {"id": str(fila["id_usuario"]), "correo": fila["correo"].strip().lower(), "nombre": fila["nombre"] or fila["correo"]}


def crear_ca(ahora: datetime):
    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "CertiSENA CA de PRUEBA (solo desarrollo)"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CertiSENA - desarrollo"),
    ])
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nombre).issuer_name(nombre)
        .public_key(llave.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(days=1)).not_valid_after(ahora + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=False, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
            encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(llave.public_key()), critical=False)
        .sign(llave, hashes.SHA256())
    )
    return llave, certificado


def crear_certificado_lider(lider: dict, llave_ca, certificado_ca, ahora: datetime):
    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeto = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, lider["nombre"]),
        x509.NameAttribute(NameOID.EMAIL_ADDRESS, lider["correo"]),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CertiSENA - desarrollo"),
    ])
    certificado = (
        x509.CertificateBuilder()
        .subject_name(sujeto).issuer_name(certificado_ca.subject)
        .public_key(llave.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(days=1)).not_valid_after(ahora + timedelta(days=730))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.RFC822Name(lider["correo"])]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(llave_ca.public_key()), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(llave.public_key()), critical=False)
        .sign(llave_ca, hashes.SHA256())
    )
    return llave, certificado


def escribir_env(valores: dict) -> None:
    texto = ARCHIVO_ENV.read_text(encoding="utf-8") if ARCHIVO_ENV.exists() else ""
    for clave, valor in valores.items():
        linea = f"{clave}={valor}"
        if re.search(rf"^{clave}=", texto, re.M):
            texto = re.sub(rf"^{clave}=.*$", lambda _: linea, texto, flags=re.M)
        else:
            if MARCA_ENV not in texto:
                texto = texto.rstrip("\n") + "\n" + MARCA_ENV + "\n"
            texto = texto.rstrip("\n") + "\n" + linea + "\n"
    ARCHIVO_ENV.write_text(texto, encoding="utf-8")


def principal() -> None:
    lector = argparse.ArgumentParser(description="Configura una firma digital de PRUEBA para el líder del Comité.")
    lector.add_argument("--directorio", default=str(Path.home() / ".certisena_firma"),
                        help="carpeta fuera del proyecto donde guardar la CA y el .p12")
    lector.add_argument("--forzar", action="store_true", help="reemplaza la firma de prueba si ya existe")
    lector.add_argument("--sin-env", action="store_true", help="no modifica el .env (solo crea los archivos)")
    opciones = lector.parse_args()

    lider = asyncio.run(lider_vigente())
    directorio = Path(opciones.directorio).expanduser().resolve()
    archivo_p12 = directorio / f"{lider['id']}.p12"
    if archivo_p12.exists() and not opciones.forzar:
        sys.exit(f"Ya existe la firma de prueba de {lider['correo']} en {directorio}. Use --forzar para reemplazarla.")

    directorio.mkdir(parents=True, exist_ok=True)
    ahora = datetime.now(timezone.utc)
    llave_ca, certificado_ca = crear_ca(ahora)
    llave, certificado = crear_certificado_lider(lider, llave_ca, certificado_ca, ahora)
    contrasena = secrets.token_urlsafe(24)
    archivo_p12.write_bytes(pkcs12.serialize_key_and_certificates(
        lider["nombre"].encode("utf-8"), llave, certificado, [certificado_ca],
        BestAvailableEncryption(contrasena.encode("utf-8")),
    ))
    raiz = directorio / "ca_prueba.pem"
    raiz.write_bytes(certificado_ca.public_bytes(serialization.Encoding.PEM))

    print(f"Firma de prueba creada para {lider['correo']} en {directorio}")
    if opciones.sin_env:
        print("No se modificó el .env (--sin-env).")
        return
    carpeta = directorio.as_posix()
    escribir_env({
        "CERTIFICADOS_FIRMA_DIR": carpeta,
        "CERTIFICADOS_FIRMA_PASSWORDS_JSON": "'" + json.dumps({lider["id"]: contrasena}) + "'",
        "CERTIFICADOS_FIRMA_TRUST_ROOTS_JSON": "'" + json.dumps([raiz.as_posix()]) + "'",
    })
    print(".env actualizado (la contraseña del .p12 no se muestra). Reinicie el servidor para aplicarlo.")


if __name__ == "__main__":
    principal()
