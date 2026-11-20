"""
Configura una firma digital de PRUEBA para el líder vigente del Comité o,
con --todos-comite, para TODOS los miembros activos del Comité (el líder se
elige por expediente y cualquiera de ellos puede tener que firmar).

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
    venv\\Scripts\\python.exe -m modules.scripts.configurar_firma_prueba --todos-comite

Con --todos-comite crea el .p12 de cada miembro activo del Comité que aún no
lo tenga (con --forzar los reemplaza) y AÑADE sus contraseñas a
CERTIFICADOS_FIRMA_PASSWORDS_JSON y la CA nueva a
CERTIFICADOS_FIRMA_TRUST_ROOTS_JSON, sin borrar lo que ya hubiera.

Solo lee la base de datos (SELECT del líder vigente o de los miembros del
Comité); no la modifica.
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


def _persona(fila) -> dict:
    return {"id": str(fila["id_usuario"]), "correo": fila["correo"].strip().lower(), "nombre": fila["nombre"] or fila["correo"]}


async def miembros_del_comite() -> list[dict]:
    """Usuarios activos con rol Comité (candidatos a líder de algún expediente)."""
    async with AsyncSessionLocal() as sesion:
        resultado = await sesion.execute(text("""
            SELECT u.id_usuario, u.correo, u.nombre
            FROM usuario u
            JOIN rol r ON r.id_rol = u.rol_id
            WHERE u.estado = 'Activo'
              AND u.correo IS NOT NULL
              AND LOWER(TRANSLATE(r.nombre, 'ÁÉÍÓÚáéíóú', 'AEIOUaeiou'))
                  IN ('comite', 'comite de certificacion')
            ORDER BY u.nombre;
        """))
        filas = resultado.mappings().all()
    if not filas:
        sys.exit("No hay miembros activos del Comité.")
    return [_persona(fila) for fila in filas]


async def lider_vigente() -> dict:
    async with AsyncSessionLocal() as sesion:
        # Líder global (las filas con id_solicitud son líderes por expediente).
        resultado = await sesion.execute(text("""
            SELECT u.id_usuario, u.correo, u.nombre
            FROM asignacion_lider_comite a
            JOIN usuario u ON u.id_usuario = a.id_usuario
            WHERE a.fecha_fin IS NULL
              AND (to_jsonb(a)->>'id_solicitud') IS NULL
            ORDER BY a.fecha_inicio DESC
            LIMIT 1;
        """))
        fila = resultado.mappings().first()
    if not fila:
        sys.exit("No hay un líder del Comité asignado. Asígnelo en Gestión de certificados y vuelva a intentarlo.")
    return _persona(fila)


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


def leer_json_env(clave: str, defecto, archivo: Path | None = None):
    """Valor JSON actual de una variable del .env (sin comillas), o `defecto`."""
    archivo = archivo or ARCHIVO_ENV
    texto = archivo.read_text(encoding="utf-8") if archivo.exists() else ""
    coincidencia = re.search(rf"^{clave}=(.*)$", texto, re.M)
    if not coincidencia:
        return defecto
    valor = coincidencia.group(1).strip()
    if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ("'", '"'):
        valor = valor[1:-1]
    try:
        dato = json.loads(valor)
    except ValueError:
        return defecto
    return dato if isinstance(dato, type(defecto)) else defecto


def escribir_env(valores: dict, archivo: Path | None = None) -> None:
    archivo = archivo or ARCHIVO_ENV
    texto = archivo.read_text(encoding="utf-8") if archivo.exists() else ""
    for clave, valor in valores.items():
        linea = f"{clave}={valor}"
        if re.search(rf"^{clave}=", texto, re.M):
            texto = re.sub(rf"^{clave}=.*$", lambda _: linea, texto, flags=re.M)
        else:
            if MARCA_ENV not in texto:
                texto = texto.rstrip("\n") + "\n" + MARCA_ENV + "\n"
            texto = texto.rstrip("\n") + "\n" + linea + "\n"
    archivo.write_text(texto, encoding="utf-8")


def crear_p12(persona: dict, llave_ca, certificado_ca, ahora: datetime, directorio: Path) -> str:
    """Crea <id>.p12 de la persona firmado por la CA dada; devuelve la contraseña (no se muestra)."""
    llave, certificado = crear_certificado_lider(persona, llave_ca, certificado_ca, ahora)
    contrasena = secrets.token_urlsafe(24)
    (directorio / f"{persona['id']}.p12").write_bytes(pkcs12.serialize_key_and_certificates(
        persona["nombre"].encode("utf-8"), llave, certificado, [certificado_ca],
        BestAvailableEncryption(contrasena.encode("utf-8")),
    ))
    return contrasena


def configurar_todos(miembros: list[dict], directorio: Path, forzar: bool, sin_env: bool,
                     archivo_env: Path, ahora: datetime | None = None) -> dict:
    """
    Firma de prueba para todos los miembros del Comité. Conserva las
    contraseñas y CA que ya estén en el .env y solo añade las nuevas.
    """
    ahora = ahora or datetime.now(timezone.utc)
    directorio.mkdir(parents=True, exist_ok=True)
    pendientes = [m for m in miembros if forzar or not (directorio / f"{m['id']}.p12").exists()]
    omitidos = [m for m in miembros if m not in pendientes]
    if not pendientes:
        return {"creados": [], "omitidos": omitidos, "ca": None}
    llave_ca, certificado_ca = crear_ca(ahora)
    nuevas = {m["id"]: crear_p12(m, llave_ca, certificado_ca, ahora, directorio) for m in pendientes}
    # Una CA por ejecución; las anteriores siguen siendo raíz de confianza de
    # los .p12 que ya existían.
    raiz = directorio / "ca_prueba.pem"
    if raiz.exists():
        raiz = directorio / f"ca_prueba_{ahora.strftime('%Y%m%d%H%M%S')}.pem"
    raiz.write_bytes(certificado_ca.public_bytes(serialization.Encoding.PEM))
    if not sin_env:
        claves = leer_json_env("CERTIFICADOS_FIRMA_PASSWORDS_JSON", {}, archivo_env)
        claves.update(nuevas)
        raices = leer_json_env("CERTIFICADOS_FIRMA_TRUST_ROOTS_JSON", [], archivo_env)
        if raiz.as_posix() not in raices:
            raices.append(raiz.as_posix())
        escribir_env({
            "CERTIFICADOS_FIRMA_DIR": directorio.as_posix(),
            "CERTIFICADOS_FIRMA_PASSWORDS_JSON": "'" + json.dumps(claves) + "'",
            "CERTIFICADOS_FIRMA_TRUST_ROOTS_JSON": "'" + json.dumps(raices) + "'",
        }, archivo_env)
    return {"creados": pendientes, "omitidos": omitidos, "ca": raiz}


def principal() -> None:
    lector = argparse.ArgumentParser(description="Configura una firma digital de PRUEBA para el líder del Comité.")
    lector.add_argument("--directorio", default=str(Path.home() / ".certisena_firma"),
                        help="carpeta fuera del proyecto donde guardar la CA y el .p12")
    lector.add_argument("--forzar", action="store_true", help="reemplaza la firma de prueba si ya existe")
    lector.add_argument("--sin-env", action="store_true", help="no modifica el .env (solo crea los archivos)")
    lector.add_argument("--todos-comite", action="store_true",
                        help="crea la firma de todos los miembros activos del Comité y la añade al .env sin borrar las existentes")
    opciones = lector.parse_args()

    if opciones.todos_comite:
        directorio = Path(opciones.directorio).expanduser().resolve()
        resultado = configurar_todos(
            asyncio.run(miembros_del_comite()), directorio, opciones.forzar, opciones.sin_env, ARCHIVO_ENV
        )
        for persona in resultado["creados"]:
            print(f"Firma de prueba creada para {persona['correo']}")
        for persona in resultado["omitidos"]:
            print(f"Ya tenía firma de prueba (use --forzar para reemplazarla): {persona['correo']}")
        if not resultado["creados"]:
            print("No se creó ninguna firma nueva.")
        elif opciones.sin_env:
            print(f"Archivos en {directorio}. No se modificó el .env (--sin-env).")
        else:
            print(".env actualizado (contraseñas añadidas, no se muestran). Reinicie el servidor para aplicarlo.")
        return

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
