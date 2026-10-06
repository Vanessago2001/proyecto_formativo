"""Firma PAdES usando el PKCS#12 externo de la persona autenticada."""

import json
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pyhanko import stamp
from pyhanko.keys import load_certs_from_pemder
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers
from pyhanko.sign.fields import SigSeedSubFilter
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

from core.config import settings


class FirmaPadesError(Exception):
    """Error de configuración o validación del certificado del firmante."""


def _correo_certificado(certificado: x509.Certificate) -> str | None:
    try:
        nombres = certificado.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        correos = nombres.get_values_for_type(x509.RFC822Name)
        if correos:
            return correos[0].strip().lower()
    except x509.ExtensionNotFound:
        pass

    correos_sujeto = certificado.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)
    return correos_sujeto[0].value.strip().lower() if correos_sujeto else None


def _cargar_firmante(id_usuario: UUID | str, correo_usuario: str):
    directorio_configurado = settings.CERTIFICADOS_FIRMA_DIR
    if not directorio_configurado:
        raise FirmaPadesError("No está configurado CERTIFICADOS_FIRMA_DIR.")

    try:
        claves = json.loads(settings.CERTIFICADOS_FIRMA_PASSWORDS_JSON)
    except json.JSONDecodeError as exc:
        raise FirmaPadesError("La configuración de claves de firma no es válida.") from exc

    clave_id = str(id_usuario)
    password = claves.get(clave_id)
    if not isinstance(password, str) or not password:
        raise FirmaPadesError("No hay contraseña PKCS#12 configurada para el líder asignado.")

    directorio = Path(directorio_configurado).expanduser().resolve()
    archivo = (directorio / f"{clave_id}.p12").resolve()
    if archivo.parent != directorio or not archivo.is_file():
        raise FirmaPadesError("No se encontró el PKCS#12 del líder asignado.")

    try:
        contenido = archivo.read_bytes()
        clave_privada, certificado, _cadena = pkcs12.load_key_and_certificates(
            contenido, password.encode("utf-8")
        )
    except (OSError, ValueError, TypeError) as exc:
        raise FirmaPadesError("No fue posible abrir el PKCS#12 del líder.") from exc

    if clave_privada is None or certificado is None:
        raise FirmaPadesError("El PKCS#12 debe contener certificado y llave privada.")

    ahora = datetime.now(timezone.utc)
    if certificado.not_valid_before_utc > ahora or certificado.not_valid_after_utc < ahora:
        raise FirmaPadesError("El certificado de firma está vencido o aún no es válido.")

    correo_certificado = _correo_certificado(certificado)
    if not correo_certificado or correo_certificado != correo_usuario.strip().lower():
        raise FirmaPadesError("El correo del certificado no coincide con la cuenta líder asignada.")

    try:
        firmante = signers.SimpleSigner.load_pkcs12(
            pfx_file=str(archivo),
            passphrase=password.encode("utf-8"),
        )
    except Exception as exc:
        raise FirmaPadesError("El PKCS#12 no se pudo cargar para firmar el PDF.") from exc

    huella_certificado = certificado.fingerprint(hashes.SHA256()).hex()
    return firmante, certificado, huella_certificado


def _raices_confiables():
    try:
        rutas = json.loads(settings.CERTIFICADOS_FIRMA_TRUST_ROOTS_JSON)
    except json.JSONDecodeError as exc:
        raise FirmaPadesError("La configuración de raíces confiables no es válida.") from exc
    if not isinstance(rutas, list) or not rutas or not all(isinstance(ruta, str) for ruta in rutas):
        raise FirmaPadesError("Configure las raíces CA de confianza antes de firmar.")
    try:
        raices = list(load_certs_from_pemder(rutas))
    except Exception as exc:
        raise FirmaPadesError("No se pudieron cargar las raíces CA configuradas.") from exc
    if not raices:
        raise FirmaPadesError("No hay raíces CA de confianza disponibles.")
    return raices


def firmar_pdf_pades(
    pdf_sin_firma: bytes,
    id_usuario: UUID | str,
    correo_usuario: str,
) -> tuple[bytes, str, str]:
    """Firma los bytes del PDF; devuelve PDF firmado, huella del archivo y del certificado."""
    firmante, certificado, huella_certificado = _cargar_firmante(
        id_usuario, correo_usuario
    )
    nombre = certificado.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    nombre_firmante = nombre[0].value if nombre else correo_usuario

    entrada = BytesIO(pdf_sin_firma)
    escritor = IncrementalPdfFileWriter(entrada)
    fields.append_signature_field(
        escritor,
        sig_field_spec=fields.SigFieldSpec(
            sig_field_name="FirmaLiderComite",
            box=(48, 52, 390, 112),
        ),
    )
    metadatos = signers.PdfSignatureMetadata(
        field_name="FirmaLiderComite",
        md_algorithm="sha256",
        subfilter=SigSeedSubFilter.PADES,
    )
    estilo = stamp.TextStampStyle(
        stamp_text=(
            "Firmado digitalmente por %(signer)s\n"
            "Fecha: %(ts)s\n"
            "Huella certificado: " + huella_certificado[:24]
        )
    )
    salida = BytesIO()
    try:
        signers.PdfSigner(
            metadatos,
            signer=firmante,
            stamp_style=estilo,
        ).sign_pdf(escritor, output=salida)
    except Exception as exc:
        raise FirmaPadesError("El proveedor criptográfico no pudo firmar el PDF.") from exc

    pdf_firmado = salida.getvalue()
    try:
        lector = PdfFileReader(BytesIO(pdf_firmado))
        firmas = lector.embedded_signatures
        if not firmas:
            raise FirmaPadesError("El PDF generado no contiene un campo de firma PAdES.")
        estado = validate_pdf_signature(
            firmas[-1],
            signer_validation_context=ValidationContext(
                trust_roots=_raices_confiables(),
                allow_fetching=False,
            ),
        )
        if (
            not estado.intact
            or not estado.valid
            or not estado.trusted
            or not estado.bottom_line
        ):
            raise FirmaPadesError("La firma PAdES no es íntegra o la cadena no es confiable.")
    except FirmaPadesError:
        raise
    except Exception as exc:
        raise FirmaPadesError("No fue posible validar la firma PAdES contra las raíces CA configuradas.") from exc
    return pdf_firmado, sha256(pdf_firmado).hexdigest(), huella_certificado