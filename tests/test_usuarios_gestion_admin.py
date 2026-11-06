"""
Pantallas del administrador · correcciones del documento de pruebas.

  · Control de usuarios: el cambio de estado de una cuenta Auditor se confirma.
  · El rol "Super Administrador" no se ofrece ni se puede asignar.
  · Registrar empresa: NIT/correo repetido o datos demasiado largos ya no dan 500.
  · Asignación de auditores: fecha inicio > fecha fin se rechaza.
  · USR-CORREO / USR-CLAVE: cambiar correo y restablecer contraseña de cuentas
    Empresa/Auditor (admin siempre; auxiliar solo con permiso delegado).
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from core.database import get_db
from core.security import get_current_user
from main import app

ID_OBJETIVO = str(uuid.uuid4())
ID_ACTOR = str(uuid.uuid4())


class Resultado:
    def __init__(self, primera=None, todas=None):
        self._primera, self._todas = primera, todas or []

    def mappings(self):
        return self

    def first(self):
        return self._primera

    def all(self):
        return self._todas

    def scalar(self):
        return None


class BaseFalsa:
    """Responde según el texto de la consulta; guarda todo lo ejecutado."""

    def __init__(self, respuestas=None, errores=None):
        # respuestas: lista de (fragmento_sql, Resultado)
        self.respuestas = respuestas or []
        self.errores = errores or {}
        self.sentencias: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, consulta, params=None):
        sql = " ".join(str(consulta).split())
        self.sentencias.append((sql, dict(params or {})))
        for fragmento, error in self.errores.items():
            if fragmento in sql:
                raise error
        for fragmento, resultado in self.respuestas:
            if fragmento in sql:
                return resultado
        return Resultado()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def close(self):
        pass

    def ejecuto(self, fragmento):
        return [(sql, p) for sql, p in self.sentencias if fragmento in sql]


async def pedir(db, rol, metodo, ruta, **kwargs):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "id_usuario": ID_ACTOR,
        "id": ID_ACTOR,
        "nombre": "Actor",
        "role_name": rol,
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            return await getattr(cliente, metodo)(ruta, **kwargs)
    finally:
        app.dependency_overrides.clear()


# ============================================================
# 1. CONTROL DE USUARIOS: ESTADO DE UNA CUENTA AUDITOR
# ============================================================

async def test_cambiar_estado_de_un_auditor_confirma_la_transaccion():
    fila_auditor = {"id_usuario": ID_OBJETIVO, "nombre": "Aud", "estado": "Activo", "rol": "Auditor"}
    db = BaseFalsa(respuestas=[
        ("SELECT id_usuario FROM usuario WHERE id_usuario", Resultado({"id_usuario": ID_OBJETIVO})),
        ("SELECT r.nombre AS rol", Resultado({"rol": "Auditor"})),
        ("FOR UPDATE", Resultado(fila_auditor)),
        ("SELECT id_usuario, nombre, correo, estado", Resultado({
            "id_usuario": ID_OBJETIVO, "nombre": "Auditor Uno", "correo": "a@b.co", "estado": "Inactivo",
            "rol_id": str(uuid.uuid4()), "tipo_doc": "CC", "num_doc": "1",
        })),
    ])

    with patch(
        "modules.auditores_registrados.auditores_registrados_service."
        "AuditoresRegistradosService._retirar_asignaciones_por_desactivacion",
        new=AsyncMock(return_value={"retiros_realizados": 0}),
    ):
        respuesta = await pedir(db, "Administrador", "put", f"/users/{ID_OBJETIVO}", json={"estado": "Inactivo"})

    assert respuesta.status_code == 200, respuesta.text
    assert db.ejecuto("UPDATE usuario SET estado = :estado")
    # Antes no se hacia commit y el cambio se perdia al cerrar la sesion.
    assert db.commits >= 1


# ============================================================
# 4. ROL SUPER ADMINISTRADOR RETIRADO
# ============================================================

async def test_la_lista_de_roles_no_incluye_super_administrador():
    roles = [
        {"id_rol": str(uuid.uuid4()), "nombre": "Administrador", "descripcion": None},
        {"id_rol": str(uuid.uuid4()), "nombre": "Super Administrador", "descripcion": None},
        {"id_rol": str(uuid.uuid4()), "nombre": "Auditor", "descripcion": None},
    ]
    db = BaseFalsa(respuestas=[("FROM rol ORDER BY", Resultado(todas=roles))])

    respuesta = await pedir(db, "Administrador", "get", "/rol/")

    assert respuesta.status_code == 200, respuesta.text
    assert [r["nombre"] for r in respuesta.json()] == ["Administrador", "Auditor"]


async def test_no_se_puede_asignar_el_rol_super_administrador():
    db = BaseFalsa(respuestas=[
        ("SELECT id_usuario FROM usuario WHERE id_usuario", Resultado({"id_usuario": ID_OBJETIVO})),
        ("SELECT r.nombre AS rol", Resultado({"rol": "Auxiliar"})),
        ("SELECT id_rol, nombre FROM rol", Resultado({"id_rol": "x", "nombre": "Super Administrador"})),
    ])

    respuesta = await pedir(db, "Administrador", "put", f"/users/{ID_OBJETIVO}", json={"rol": str(uuid.uuid4())})

    assert respuesta.status_code == 400
    assert "Super Administrador" in respuesta.json()["detail"]
    assert not db.ejecuto("UPDATE usuario")


# ============================================================
# 11. REGISTRAR EMPRESA SIN 500
# ============================================================

EMPRESA = {"nombre": "Cafe del Eje", "nit": "900123456-7", "ciudad": "Manizales",
           "direccion": "Calle 1", "correo": "cafe@eje.co"}


@pytest.mark.parametrize(
    "restriccion,texto",
    [("uq_empresa_nit", "NIT"), ("empresa_correo_key", "correo")],
)
async def test_registrar_empresa_repetida_responde_409_y_no_500(restriccion, texto):
    error = IntegrityError("INSERT", {}, Exception(f'duplicate key value violates unique constraint "{restriccion}"'))
    db = BaseFalsa(errores={"INSERT INTO empresa": error})

    respuesta = await pedir(db, "Administrador", "post", "/api/empresas/", json=EMPRESA)

    assert respuesta.status_code == 409, respuesta.text
    assert texto in respuesta.json()["detail"]
    assert db.rollbacks == 1


async def test_registrar_empresa_con_nombre_demasiado_largo_responde_422():
    db = BaseFalsa()
    respuesta = await pedir(db, "Administrador", "post", "/api/empresas/", json={**EMPRESA, "nombre": "x" * 71})
    assert respuesta.status_code == 422
    assert not db.sentencias


# ============================================================
# 5. ASIGNACION DE AUDITORES: FECHA INICIO <= FECHA FIN
# ============================================================

async def test_filtro_de_solicitudes_rechaza_fecha_inicio_posterior_a_fecha_fin():
    db = BaseFalsa()
    respuesta = await pedir(
        db, "Administrador", "get",
        "/asignacion-auditores/solicitudes?desde=2026-05-10&hasta=2026-05-01",
    )
    assert respuesta.status_code == 422
    assert "fecha inicio" in respuesta.json()["detail"].lower()
    assert not db.sentencias


# ============================================================
# 13. USR-CORREO / USR-CLAVE
# ============================================================

def cuenta(rol="Empresa", correo="vieja@empresa.co"):
    return Resultado({"id_usuario": ID_OBJETIVO, "nombre": "Cuenta", "correo": correo, "rol": rol})


def base_gestion(rol_objetivo="Empresa", duplicado=False, empresas=None):
    return BaseFalsa(respuestas=[
        ("SELECT u.id_usuario, u.nombre, u.correo, r.nombre AS rol", cuenta(rol_objetivo)),
        ("WHERE LOWER(correo) = LOWER(:correo)", Resultado({"x": 1} if duplicado else None)),
        ("FROM user_empresa ue JOIN empresa e", Resultado(todas=empresas or [])),
        ("INSERT INTO historial_gestion_cuenta", Resultado({"id_historial": str(uuid.uuid4())})),
    ])


CORREO = {"correo": "nueva@empresa.co", "motivo": "Perdió acceso a su correo"}
CLAVE = {"motivo": "Perdió acceso a su correo"}


@pytest.fixture
def correos():
    with patch("modules.users.gestion_cuenta_service.MailService.enviar_aviso_cuenta", new=AsyncMock()) as aviso, \
         patch("modules.users.gestion_cuenta_service.MailService.enviar_enlace_reset", new=AsyncMock()) as enlace, \
         patch("modules.auth.auth_service.AuthService._crear_enlace_reset",
               new=AsyncMock(return_value="http://x/reset-password?token=SECRETO")):
        yield aviso, enlace


@pytest.mark.parametrize("rol_objetivo", ["Empresa", "Auditor"])
async def test_el_administrador_cambia_el_correo_y_queda_en_el_historial(correos, rol_objetivo):
    aviso, _ = correos
    db = base_gestion(rol_objetivo)

    respuesta = await pedir(db, "Administrador", "put", f"/users/{ID_OBJETIVO}/correo", json=CORREO)

    assert respuesta.status_code == 200, respuesta.text
    (_, params), = db.ejecuto("UPDATE usuario SET correo = :correo")
    assert params["correo"] == "nueva@empresa.co"
    (_, hist), = db.ejecuto("INSERT INTO historial_gestion_cuenta")
    assert hist["accion"] == "CAMBIO_CORREO"
    assert hist["valor_anterior"] == "vieja@empresa.co"
    assert hist["motivo"] == CORREO["motivo"]
    assert hist["id_actor"] == ID_ACTOR
    # Se avisa al correo anterior.
    assert "vieja@empresa.co" in [c.args[0] for c in aviso.call_args_list]


async def test_el_correo_propio_de_la_empresa_no_se_cambia(correos):
    db = base_gestion(empresas=[{"id_empresa": uuid.uuid4(), "nombre": "Cafe", "correo": "contacto@cafe.co"}])

    respuesta = await pedir(db, "Administrador", "put", f"/users/{ID_OBJETIVO}/correo", json=CORREO)

    assert respuesta.status_code == 200
    assert respuesta.json()["empresas_con_correo_propio"][0]["correo"] == "contacto@cafe.co"
    assert not db.ejecuto("UPDATE empresa")


async def test_si_falla_el_aviso_el_cambio_de_correo_igual_queda(correos):
    aviso, _ = correos
    aviso.side_effect = RuntimeError("smtp caido")
    db = base_gestion()

    respuesta = await pedir(db, "Administrador", "put", f"/users/{ID_OBJETIVO}/correo", json=CORREO)

    assert respuesta.status_code == 200
    assert db.ejecuto("UPDATE usuario SET correo")
    (_, anotacion), = db.ejecuto("SET resultado_envio")
    assert "Falló" in anotacion["resultado"]


async def test_correo_en_uso_por_otra_cuenta_responde_409(correos):
    db = base_gestion(duplicado=True)

    respuesta = await pedir(db, "Administrador", "put", f"/users/{ID_OBJETIVO}/correo", json=CORREO)

    assert respuesta.status_code == 409
    assert not db.ejecuto("UPDATE usuario")
    assert not db.ejecuto("INSERT INTO historial_gestion_cuenta")


async def test_correo_invalido_o_sin_motivo_responde_422(correos):
    db = base_gestion()
    malo = await pedir(db, "Administrador", "put", f"/users/{ID_OBJETIVO}/correo",
                       json={"correo": "no-es-correo", "motivo": "motivo valido"})
    sin_motivo = await pedir(db, "Administrador", "put", f"/users/{ID_OBJETIVO}/correo",
                             json={"correo": "a@b.co", "motivo": ""})
    assert malo.status_code == 422 and sin_motivo.status_code == 422


@pytest.mark.parametrize("ruta,cuerpo", [("correo", CORREO), ("restablecer-password", CLAVE)])
@pytest.mark.parametrize("rol", ["Empresa", "Auditor", "Comité", "Instructor"])
async def test_otros_roles_no_pueden_gestionar_cuentas(correos, ruta, cuerpo, rol):
    db = base_gestion()
    metodo = "put" if ruta == "correo" else "post"

    respuesta = await pedir(db, rol, metodo, f"/users/{ID_OBJETIVO}/{ruta}", json=cuerpo)

    assert respuesta.status_code == 403
    assert not db.ejecuto("UPDATE usuario")


@pytest.mark.parametrize("ruta,cuerpo,codigo", [
    ("correo", CORREO, "USR-CORREO"),
    ("restablecer-password", CLAVE, "USR-CLAVE"),
])
@pytest.mark.parametrize("tiene_permiso,esperado", [(True, 200), (False, 403)])
async def test_el_auxiliar_solo_puede_con_permiso_delegado(correos, ruta, cuerpo, codigo, tiene_permiso, esperado):
    db = base_gestion()
    metodo = "put" if ruta == "correo" else "post"
    permiso = AsyncMock(return_value=tiene_permiso)

    with patch("modules.users.gestion_cuenta_service._auxiliar_tiene_permiso", new=permiso):
        respuesta = await pedir(db, "Auxiliar", metodo, f"/users/{ID_OBJETIVO}/{ruta}", json=cuerpo)

    assert respuesta.status_code == esperado, respuesta.text
    assert permiso.call_args.args[1] == ID_ACTOR
    assert permiso.call_args.args[2] == codigo
    assert bool(db.ejecuto("UPDATE usuario")) is tiene_permiso


@pytest.mark.parametrize("ruta,cuerpo", [("correo", CORREO), ("restablecer-password", CLAVE)])
@pytest.mark.parametrize("rol_objetivo", ["Administrador", "Auxiliar", "Comité"])
async def test_no_se_gestiona_un_administrador_ni_otros_roles(correos, ruta, cuerpo, rol_objetivo):
    db = base_gestion(rol_objetivo)
    metodo = "put" if ruta == "correo" else "post"

    respuesta = await pedir(db, "Administrador", metodo, f"/users/{ID_OBJETIVO}/{ruta}", json=cuerpo)

    assert respuesta.status_code == 403
    assert not db.ejecuto("UPDATE usuario")


async def test_restablecer_password_envia_enlace_y_no_guarda_la_contrasena(correos):
    _, enlace = correos
    db = base_gestion("Auditor")

    respuesta = await pedir(db, "Administrador", "post", f"/users/{ID_OBJETIVO}/restablecer-password", json=CLAVE)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["enviado"] is True
    # El enlace va al correo de la cuenta y nunca vuelve al administrador.
    assert enlace.call_args.kwargs["destinatario"] == "vieja@empresa.co"
    assert "SECRETO" not in respuesta.text
    # Contrasena vencida para obligar a cambiarla; no se escribe ninguna.
    (sql, _), = db.ejecuto("SET fecha_cambio_password")
    assert "contrasena" not in sql
    (_, hist), = db.ejecuto("INSERT INTO historial_gestion_cuenta")
    assert hist["accion"] == "RESTABLECER_PASSWORD"
    assert all("SECRETO" not in str(v) for v in hist.values())
    assert all("contrasena" not in k for k in hist)
