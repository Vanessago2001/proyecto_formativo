import asyncio
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi import HTTPException
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, Encoding, pkcs12
from cryptography.x509.oid import NameOID

from modules.certificados.certificados_permissions import (
    PERMISOS_M9,
    NivelPermiso,
    marcar_aprobacion,
    nivel_permiso,
    tiene_permiso,
)
from modules.certificados.certificados_service import (
    certificado_esta_vigente,
    es_usuario_empresa,
    validar_transicion,
)
from modules.certificados.certificados_pdf import generar_pdf_certificado
from modules.certificados.certificados_router import _csv_response


class FakeResult:
    def __init__(self, rows):
        self.rows = rows if isinstance(rows, list) else [rows]

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def one(self):
        return self.rows[0]


class FakeDatabase:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.commits = 0
        self.executions = []

    async def execute(self, *args, **kwargs):
        self.executions.append((args, kwargs))
        return FakeResult(self.responses.pop(0))

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None


def _public_certificate_row(**overrides):
    return {
        "id_certificado": "11111111-1111-4111-8111-111111111111",
        "codigo_verificacion": "CS-2026-000001",
        "id_comite": "22222222-2222-4222-8222-222222222222",
        "url_certificado": None,
        "fecha_vencimiento": date.today() + timedelta(days=30),
        "estado_certificado": "VIGENTE",
        "fecha_emision": date.today(),
        "publico_certificado": True,
        "id_solicitud": "33333333-3333-4333-8333-333333333333",
        "id_alcance": "44444444-4444-4444-8444-444444444444",
        "fecha_registro": date.today(),
        "fecha_revocacion": None,
        "id_firmante": "66666666-6666-4666-8666-666666666666",
        "codigo_hash": "a" * 64,
        "huella_pdf": "c" * 64,
        "huella_firmante": "b" * 64,
        "nombre_firmante": "Líder de prueba",
        "numero_radicado": "RAD-2026-000001",
        "id_empresa": "55555555-5555-4555-8555-555555555555",
        "empresa": "Empresa pública",
        "nit": "900123456",
        "correo": "privado@example.com",
        "norma_codigo": "ISO 9001",
        "norma": "Sistemas de gestión de calidad",
        "norma_version": "2015",
        "alcance": "Fabricación",
        **overrides,
    }


@pytest.mark.parametrize(
    ("codigo", "expected"),
    [
        ("CER-001", ("V", "V", "V", "F", "F", "F", "F", "F")),
        ("CER-010", ("V", "V", "REQ", "F", "F", "F", "F", "F")),
        ("CER-016", ("SA", "V", "F", "F", "F", "V", "F", "F")),
        ("CER-022", ("SA", "F", "F", "F", "F", "F", "F", "F")),
        ("CER-030", ("SA", "F", "F", "F", "F", "F", "F", "F")),
    ],
)
def test_matriz_m9_transcribe_celdas(codigo, expected):
    assert tuple(value.value for value in PERMISOS_M9[codigo][1]) == expected


def test_req_concede_permiso_y_sa_es_exclusivo_de_superadministrador():
    assert nivel_permiso("CER-010", "Auxiliar") is NivelPermiso.REQUIERE_APROBACION
    assert tiene_permiso("CER-010", "Auxiliar")
    assert tiene_permiso("CER-022", "Super Administrador")
    assert not tiene_permiso("CER-022", "Administrador")


def test_cer010_no_concede_firma_al_rol_comite_en_general():
    assert nivel_permiso("CER-010", "Comité") is NivelPermiso.DENEGADO
    assert not tiene_permiso("CER-010", "Comité")


def test_excepcion_de_firma_solo_entrega_contexto_comite_al_servicio_asignado():
    from modules.certificados.certificados_router import requiere_firma_lider_o_permiso

    dependencia = requiere_firma_lider_o_permiso()
    usuario_comite = asyncio.run(dependencia({
        "id_usuario": "11111111-1111-4111-8111-111111111111",
        "role_name": "Comité",
    }))
    usuario_auxiliar = asyncio.run(dependencia({
        "id_usuario": "22222222-2222-4222-8222-222222222222",
        "role_name": "Auxiliar",
    }))

    assert usuario_comite["id_usuario"] == "11111111-1111-4111-8111-111111111111"
    assert usuario_auxiliar["requiere_aprobacion"] is True


def test_comite_puede_registrar_motivo_sin_suspender():
    assert tiene_permiso("CER-018", "Comité")
    assert not tiene_permiso("CER-015", "Comité")


def test_marcar_aprobacion_identifica_acciones_req():
    respuesta = marcar_aprobacion({"id": "cert-1"}, {"requiere_aprobacion": True})

    assert respuesta == {"id": "cert-1", "requiere_aprobacion": True}


def test_alias_de_empresa_se_reconoce_para_restringir_titularidad():
    assert es_usuario_empresa({"role_name": "Empresario"})
    assert not es_usuario_empresa({"role_name": "Administrador"})


def test_vigencia_requiere_estado_y_fecha_no_vencidos():
    assert certificado_esta_vigente({"estado_certificado": "VIGENTE", "fecha_vencimiento": date.today()})
    assert not certificado_esta_vigente({"estado_certificado": "VIGENTE", "fecha_vencimiento": date.today() - timedelta(days=1)})
    assert not certificado_esta_vigente({"estado_certificado": "SUSPENDIDO", "fecha_vencimiento": date.today() + timedelta(days=1)})
    assert not certificado_esta_vigente({"estado_certificado": "VIGENTE", "fecha_vencimiento": None})


def test_detalle_para_rol_publico_no_expone_identificadores_ni_correo():
    from modules.certificados.certificados_service import CertificadosService

    servicio = CertificadosService(FakeDatabase(_public_certificate_row()))
    detalle = asyncio.run(servicio._obtener("11111111-1111-4111-8111-111111111111", {"role_name": "Publico"}))

    assert detalle["codigo_verificacion"] == "CS-2026-000001"
    assert "correo" not in detalle
    assert "id_certificado" not in detalle
    assert "id_empresa" not in detalle
    assert "id_solicitud" not in detalle


def test_rol_publico_no_puede_consultar_certificado_no_publicado():
    from modules.certificados.certificados_service import CertificadosService

    servicio = CertificadosService(FakeDatabase(_public_certificate_row(publico_certificado=False)))
    with pytest.raises(HTTPException) as error:
        asyncio.run(servicio._obtener("11111111-1111-4111-8111-111111111111", {"role_name": "Publico"}))

    assert error.value.status_code == 404


def test_historial_publico_no_incluye_motivo_ni_nombre_interno():
    from modules.certificados.certificados_service import CertificadosService

    rows = _public_certificate_row()
    historial = [{
        "estado_nuevo": "VIGENTE",
        "fecha": date.today(),
    }]
    servicio = CertificadosService(FakeDatabase(rows, historial))
    resultado = asyncio.run(servicio.historial("11111111-1111-4111-8111-111111111111", {"role_name": "Publico"}))

    assert resultado == historial


def test_metricas_publicas_solo_contabilizan_resultado_publico():
    from modules.certificados.certificados_service import CertificadosService

    resultado = asyncio.run(
        CertificadosService(FakeDatabase({"total": 4, "proximos_a_vencer": 1})).metricas_publicas()
    )

    assert resultado == {
        "total": 4,
        "vigentes": 4,
        "publicados": 4,
        "proximos_a_vencer": 1,
    }


def test_no_se_publica_sin_archivo_oficial_registrado():
    from uuid import UUID

    from modules.certificados.certificados_service import CertificadosService

    servicio = CertificadosService(FakeDatabase({
        "estado_certificado": "VIGENTE",
        "fecha_vencimiento": date.today() + timedelta(days=10),
        "url_certificado": None,
    }))

    with pytest.raises(HTTPException) as error:
        asyncio.run(servicio.cambiar_publicacion(
            UUID("11111111-1111-4111-8111-111111111111"), True, {"id_usuario": "admin"}
        ))

    assert error.value.status_code == 409


def test_no_se_publica_si_falta_la_firma_o_una_de_sus_huellas():
    from uuid import UUID

    from modules.certificados.certificados_service import CertificadosService

    servicio = CertificadosService(FakeDatabase({
        "estado_certificado": "VIGENTE",
        "fecha_vencimiento": date.today() + timedelta(days=10),
        "url_certificado": "/certificados/test/pdf",
        "id_firmante": "66666666-6666-4666-8666-666666666666",
        "huella_firmante": "b" * 64,
        "codigo_hash": "a" * 64,
        "huella_pdf": None,
    }))

    with pytest.raises(HTTPException) as error:
        asyncio.run(servicio.cambiar_publicacion(
            UUID("11111111-1111-4111-8111-111111111111"), True, {"id_usuario": "admin"}
        ))

    assert error.value.status_code == 409


def test_solo_la_cuenta_del_lider_asignado_puede_firmar():
    from uuid import UUID

    from modules.certificados.certificados_service import CertificadosService

    servicio = CertificadosService(FakeDatabase(
        [],
        {
            "estado_certificado": "PENDIENTE_FIRMA",
            "id_asignacion_lider": "33333333-3333-4333-8333-333333333333",
            "id_lider": "11111111-1111-4111-8111-111111111111",
            "nombre_lider": "Líder asignado",
            "correo_lider": "lider@example.test",
        },
    ))

    with pytest.raises(HTTPException) as error:
        asyncio.run(servicio.firmar_con_lider_asignado(
            UUID("22222222-2222-4222-8222-222222222222"),
            {"id_usuario": "99999999-9999-4999-8999-999999999999", "role_name": "Comité"},
        ))

    assert error.value.status_code == 403


def test_reasignacion_actualiza_snapshot_de_certificados_pendientes():
    from modules.certificados.certificados_service import CertificadosService

    id_nuevo_lider = "11111111-1111-4111-8111-111111111111"
    db = FakeDatabase(
        [],
        {"id_usuario": id_nuevo_lider, "nombre": "Nuevo líder", "correo": "nuevo@example.test"},
        {"id_asignacion": "22222222-2222-4222-8222-222222222222", "id_usuario": "33333333-3333-4333-8333-333333333333"},
        {},
        {},
        [{"id_certificado": "44444444-4444-4444-8444-444444444444", "codigo_verificacion": "CS-2026-000001"}],
        {},
        {"id_asignacion": "55555555-5555-4555-8555-555555555555", "id_usuario": id_nuevo_lider, "nombre": "Nuevo líder", "correo": "nuevo@example.test"},
    )

    lider = asyncio.run(CertificadosService(db).asignar_lider_comite(
        UUID(id_nuevo_lider), {"id_usuario": "66666666-6666-4666-8666-666666666666"}
    ))

    assert str(lider["id_usuario"]) == id_nuevo_lider
    query_update, parametros_update = db.executions[5][0]
    assert "UPDATE certificado" in str(query_update)
    assert parametros_update["estado"] == "PENDIENTE_FIRMA"
    assert parametros_update["id_asignacion"]


def test_no_invalida_firma_si_no_cambio_el_alcance():
    from modules.certificados.certificados_service import CertificadosService

    certificado = _public_certificate_row(publico_certificado=True)
    servicio = CertificadosService(FakeDatabase(certificado))
    with pytest.raises(HTTPException) as error:
        asyncio.run(servicio.actualizar_alcance(
            UUID(certificado["id_certificado"]),
            UUID(certificado["id_alcance"]),
            {"id_usuario": "admin"},
        ))

    assert error.value.status_code == 409


def test_firma_pades_usa_el_p12_del_lider_y_devuelve_huellas(tmp_path, monkeypatch):
    from core.config import settings
    from core.pdf import construir_pdf
    from modules.certificados.firma_pades import firmar_pdf_pades

    id_lider = UUID("11111111-1111-4111-8111-111111111111")
    correo = "lider.comite@example.test"
    password = b"solo-para-prueba"
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeto = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Lider de prueba"),
        x509.NameAttribute(NameOID.EMAIL_ADDRESS, correo),
    ])
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    certificado = (
        x509.CertificateBuilder()
        .subject_name(sujeto)
        .issuer_name(sujeto)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(minutes=1))
        .not_valid_after(ahora + timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.RFC822Name(correo)]), critical=False)
        .sign(clave, hashes.SHA256())
    )
    p12 = pkcs12.serialize_key_and_certificates(
        b"lider-prueba",
        clave,
        certificado,
        None,
        BestAvailableEncryption(password),
    )
    (tmp_path / f"{id_lider}.p12").write_bytes(p12)
    raiz_ca = tmp_path / "raiz-prueba.pem"
    raiz_ca.write_bytes(certificado.public_bytes(Encoding.PEM))
    monkeypatch.setattr(settings, "CERTIFICADOS_FIRMA_DIR", str(tmp_path))
    monkeypatch.setattr(
        settings,
        "CERTIFICADOS_FIRMA_PASSWORDS_JSON",
        f'{{"{id_lider}": "{password.decode()}"}}',
    )
    monkeypatch.setattr(
        settings,
        "CERTIFICADOS_FIRMA_TRUST_ROOTS_JSON",
        json.dumps([str(raiz_ca)]),
    )

    pdf = construir_pdf("Certificado", "Empresa de prueba", [("Código", "CS-2026-000001")])
    firmado, huella_pdf, huella_certificado = firmar_pdf_pades(pdf, id_lider, correo)

    assert firmado.startswith(b"%PDF-")
    assert firmado != pdf
    assert len(huella_pdf) == 64
    assert huella_certificado == certificado.fingerprint(hashes.SHA256()).hex()

    from modules.certificados.certificados_service import CertificadosService

    id_asignacion = UUID("33333333-3333-4333-8333-333333333333")
    certificado_pendiente = _public_certificate_row(
        estado_certificado="PENDIENTE_FIRMA",
        fecha_emision=None,
        publico_certificado=False,
        id_asignacion_lider=str(id_asignacion),
        id_firmante=None,
        huella_firmante=None,
        huella_pdf=None,
    )
    certificado_firmado = {
        **certificado_pendiente,
        "estado_certificado": "VIGENTE",
        "id_firmante": str(id_lider),
        "huella_firmante": huella_certificado,
    }
    db = FakeDatabase(
        [],
        {
            "estado_certificado": "PENDIENTE_FIRMA",
            "id_asignacion_lider": str(id_asignacion),
            "id_lider": str(id_lider),
            "nombre_lider": "Lider de prueba",
            "correo_lider": correo,
        },
        certificado_pendiente,
        {},
        {},
        certificado_firmado,
    )
    carpeta_salida = tmp_path / "firmados"
    monkeypatch.setattr(settings, "CERTIFICADOS_STORAGE_DIR", str(carpeta_salida))
    resultado = asyncio.run(CertificadosService(db).firmar_con_lider_asignado(
        UUID(certificado_pendiente["id_certificado"]),
        {"id_usuario": str(id_lider), "role_name": "Comité"},
    ))
    archivo_final = carpeta_salida / f"{certificado_pendiente['id_certificado']}.pdf"

    assert resultado["estado_certificado"] == "VIGENTE"
    assert resultado["id_firmante"] == str(id_lider)
    assert resultado["huella_firmante"] == huella_certificado
    parametros_actualizacion = db.executions[3][0][1]
    assert parametros_actualizacion["huella_firmante"] == huella_certificado
    assert parametros_actualizacion["huella_pdf"] == hashlib.sha256(archivo_final.read_bytes()).hexdigest()
    assert db.commits == 1


def test_firma_pades_rechaza_p12_de_otro_correo(tmp_path, monkeypatch):
    from core.config import settings
    from core.pdf import construir_pdf
    from modules.certificados.firma_pades import FirmaPadesError, firmar_pdf_pades

    id_lider = UUID("22222222-2222-4222-8222-222222222222")
    password = b"solo-para-prueba"
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeto = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Otra persona"),
        x509.NameAttribute(NameOID.EMAIL_ADDRESS, "otra.persona@example.test"),
    ])
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    certificado = (
        x509.CertificateBuilder()
        .subject_name(sujeto)
        .issuer_name(sujeto)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(minutes=1))
        .not_valid_after(ahora + timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName([x509.RFC822Name("otra.persona@example.test")]),
            critical=False,
        )
        .sign(clave, hashes.SHA256())
    )
    p12 = pkcs12.serialize_key_and_certificates(
        b"otra-persona",
        clave,
        certificado,
        None,
        BestAvailableEncryption(password),
    )
    (tmp_path / f"{id_lider}.p12").write_bytes(p12)
    monkeypatch.setattr(settings, "CERTIFICADOS_FIRMA_DIR", str(tmp_path))
    monkeypatch.setattr(
        settings,
        "CERTIFICADOS_FIRMA_PASSWORDS_JSON",
        f'{{"{id_lider}": "{password.decode()}"}}',
    )

    with pytest.raises(FirmaPadesError, match="no coincide"):
        firmar_pdf_pades(
            construir_pdf("Certificado", "Empresa", []),
            id_lider,
            "lider.comite@example.test",
        )


def test_apr_usa_el_permiso_de_administrador():
    assert nivel_permiso("CER-011", "Administrador") is NivelPermiso.CONCEDIDO


def test_matriz_tiene_los_treinta_requisitos():
    assert len(PERMISOS_M9) == 30
    assert set(PERMISOS_M9) == {f"CER-{number:03}" for number in range(1, 31)}


@pytest.mark.parametrize(
    ("actual", "nuevo"),
    [("VIGENTE", "SUSPENDIDO"), ("VIGENTE", "CANCELADO"), ("SUSPENDIDO", "VIGENTE")],
)
def test_transiciones_de_estado_permitidas(actual, nuevo):
    validar_transicion(actual, nuevo)


@pytest.mark.parametrize(
    ("actual", "nuevo"),
    [("PENDIENTE_FIRMA", "VIGENTE"), ("CANCELADO", "VIGENTE"), ("VIGENTE", "VIGENTE")],
)
def test_transiciones_de_estado_invalidas(actual, nuevo):
    with pytest.raises(HTTPException) as error:
        validar_transicion(actual, nuevo)
    assert error.value.status_code == 409


def test_pdf_pendiente_de_firma_se_identifica_como_borrador():
    pdf = generar_pdf_certificado({"estado_certificado": "PENDIENTE_FIRMA"})

    assert pdf.startswith(b"%PDF-1.4")
    assert b"BORRADOR DE CERTIFICADO - PENDIENTE DE FIRMA" in pdf
    assert b"No constituye un certificado oficial" in pdf


def test_exportacion_csv_neutraliza_formulas_de_celdas():
    respuesta = _csv_response(
        [{"empresa": "=HYPERLINK(\"https://ejemplo.test\")"}],
        ("empresa",),
        "certificados.csv",
    )

    contenido = respuesta.body.decode("utf-8")
    assert contenido.startswith("empresa\r\n")
    assert "\"'=HYPERLINK" in contenido