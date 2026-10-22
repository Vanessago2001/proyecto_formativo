"""
M5 — GESTIÓN DE SOLICITUDES · Bloques 5, 6 y 7.

    Bloque 5  SOL-041 a SOL-050  asignación de auditores
    Bloque 6  SOL-051 a SOL-060  trazabilidad, bitácora y cierre
    Bloque 7  SOL-061 a SOL-070  cálculo del tiempo de auditoría

Los roles salen de la hoja "M5 — GESTIÓN DE SOLICITUDES" y se comprueban
contra la misma matriz que usa la aplicación, así que si el Excel cambia y
alguien actualiza `PERMISOS_M5`, estas pruebas se mueven con él.

Donde la hoja marca REQ para el Auxiliar en una acción con efecto, la
respuesta es 202: la acción queda pendiente de aprobación y no se ejecuta.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.solicitudes.calculo_service import VARIABLES_BASE, CalculoAuditoriaService
from modules.solicitudes.solicitud_permissions import PERMISOS_M5, nivel_permiso
from modules.solicitudes.trazabilidad_service import esta_cerrada

ID_SOLICITUD = str(uuid.uuid4())
ID_EMPRESA = str(uuid.uuid4())
ID_AUDITOR = str(uuid.uuid4())
ID_OTRO_AUDITOR = str(uuid.uuid4())
ID_ASIGNACION = str(uuid.uuid4())
ID_NORMA = str(uuid.uuid4())

BASE = f"/solicitudes/{ID_SOLICITUD}"


def solicitud(estado: str = "Radicada") -> dict:
    return {
        "id_solicitud": ID_SOLICITUD,
        "id_empresa": ID_EMPRESA,
        "id_norma": ID_NORMA,
        "estado": estado,
        "numero_radicado": "SOL-2026-0001",
        "numero_empleados": 25,
        "numero_sedes": 2,
        "fecha_radicacion": "2026-09-10",
        "deleted_at": None,
    }


def asignacion(estado: str = "Propuesto") -> dict:
    return {
        "id": ID_ASIGNACION,
        "id_solicitud": ID_SOLICITUD,
        "id_auditor": ID_AUDITOR,
        "especialidad": "Ambiental",
        "estado_asignacion": estado,
        "fecha_inicio_planificada": None,
        "fecha_fin_planificada": None,
        "fecha_propuesta": None,
        "fecha_asignacion": None,
        "fecha_aprobacion": None,
        "fecha_cancelacion": None,
        "motivo_cancelacion": None,
        "motivo_reasignacion": None,
        "usuario_asigna": None,
        "usuario_aprueba": None,
        "usuario_cancela": None,
    }


def calculo(**cambios) -> dict:
    base = {
        "id_calculo": str(uuid.uuid4()),
        "id_solicitud": ID_SOLICITUD,
        "version": 1,
        "variables": {"numero_empleados": 25, "numero_sedes": 2, "complejidad": "Media"},
        "desglose": {"total_sin_ajuste": "11", "constantes": {}},
        "horas_base": Decimal("11"),
        "resultado_horas": Decimal("11"),
        "ajuste_horas": Decimal("0"),
        "justificacion_ajuste": None,
        "estado": "Borrador",
        "validado": False,
        "bloqueado": False,
        "usuario_calculo": None,
        "usuario_ajuste": None,
        "usuario_validacion": None,
        "fecha_calculo": None,
        "fecha_validacion": None,
        "fecha_bloqueo": None,
    }
    base.update(cambios)
    return base


class Respuesta:
    """Resultado de `execute` con lo que cada consulta necesita devolver."""

    def __init__(self, primera=None, todas=None, escalar=None):
        self._primera, self._todas, self._escalar = primera, todas or [], escalar

    def mappings(self):
        return self

    def first(self):
        return self._primera

    def all(self):
        return self._todas

    def scalar(self):
        return self._escalar


class BaseFalsa:
    """
    Responde según el texto de la consulta y guarda lo ejecutado.

    Separa a propósito la fila de la solicitud de la del registro que se está
    probando (una asignación, un cálculo...): casi todas las operaciones leen
    primero la solicitud para comprobar el acceso.
    """

    def __init__(self, registro=None, filas=None, escalar=None,
                 fila_solicitud=None, documentos=None, conflicto=None, duplicado=None):
        self.registro = registro if registro is not None else solicitud()
        self.fila_solicitud = fila_solicitud or (
            registro if (registro and "numero_radicado" in registro) else solicitud()
        )
        self.filas = filas or []
        self.escalar = escalar
        self.documentos = documentos if documentos is not None else {"aprobados": 1, "total": 2}
        self.conflicto = conflicto
        self.duplicado = duplicado
        self.sentencias: list[tuple[str, dict]] = []

    async def execute(self, sentencia, parametros=None):
        sql = " ".join(str(sentencia).split())
        self.sentencias.append((sql, parametros or {}))

        if "FROM user_empresa" in sql:
            return Respuesta(todas=[{"id_empresa": ID_EMPRESA}], escalar=ID_EMPRESA)
        if "FROM documento_solicitud" in sql:
            return Respuesta(primera=self.documentos)
        # La comprobacion de conflicto es una consulta propia; la busqueda de
        # candidatos tambien nombra la tabla, pero dentro de un EXISTS.
        if sql.startswith("SELECT descripcion FROM conflicto_interes") or sql.startswith(
            "SELECT 1 FROM conflicto_interes"
        ):
            return Respuesta(escalar=self.conflicto)
        if sql.startswith("SELECT id FROM auditores_solicitud"):
            return Respuesta(escalar=self.duplicado)
        if "FROM solicitud" in sql or sql.startswith("UPDATE solicitud"):
            return Respuesta(primera=self.fila_solicitud, todas=[self.fila_solicitud])
        if sql.startswith("INSERT INTO bitacora_solicitud") or sql.startswith("INSERT INTO historial"):
            return Respuesta()
        return Respuesta(primera=self.registro, todas=self.filas, escalar=self.escalar)

    async def commit(self):
        pass

    async def rollback(self):
        pass


async def pedir(db, rol, metodo, ruta, **kwargs):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "id_usuario": str(uuid.uuid4()),
        "role_name": rol,
        "nombre": rol,
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            return await getattr(cliente, metodo)(ruta, **kwargs)
    finally:
        app.dependency_overrides.clear()


def sentencias(db) -> list[tuple[str, dict]]:
    return db.sentencias


def parametros_de(db, prefijo: str) -> dict:
    return next(p for sql, p in db.sentencias if sql.startswith(prefijo))


# ============================================================
# LA MATRIZ: LOS TRES BLOQUES ESTÁN EN EL CATÁLOGO
# ============================================================

@pytest.mark.parametrize("codigo", [f"SOL-{n:03d}" for n in range(41, 71)])
def test_los_treinta_permisos_nuevos_estan_en_la_matriz(codigo):
    assert codigo in PERMISOS_M5


def test_la_empresa_no_asigna_auditores_ni_cambia_estados():
    """La hoja se lo niega: eso lo decide la administración."""
    for codigo in ("SOL-041", "SOL-047", "SOL-048", "SOL-054", "SOL-060", "SOL-062"):
        assert nivel_permiso(codigo, "Empresa").value == "F"


def test_reasignar_auditor_es_exclusivo_del_superadministrador():
    """SOL-049: SA para el SuperAdministrador y F para el Administrador."""
    assert nivel_permiso("SOL-049", "Super Administrador").value == "SA"
    assert nivel_permiso("SOL-049", "Administrador").value == "F"
    assert nivel_permiso("SOL-049", "Auxiliar").value == "REQ"


# ============================================================
# BLOQUE 5 · BUSCAR Y PROPONER
# ============================================================

@pytest.mark.parametrize(
    "rol,esperado",
    [
        ("Super Administrador", 200),
        ("Administrador", 200),
        ("Auxiliar", 200),
        ("Empresa", 403),
        ("Auditor", 403),
        ("Comité", 403),
        ("Publico", 403),
    ],
)
async def test_buscar_candidatos_segun_la_hoja(rol, esperado):
    db = BaseFalsa(filas=[])

    respuesta = await pedir(db, rol, "get", f"{BASE}/auditores/candidatos")

    assert respuesta.status_code == esperado


async def test_la_busqueda_marca_por_que_un_auditor_no_es_apto():
    db = BaseFalsa(filas=[{
        "id_usuario": ID_AUDITOR, "nombre": "Ana", "correo": "ana@sena.edu.co",
        "ciudad_residencia": "Manizales", "departamento_residencia": "Caldas",
        "calificacion_promedio": None,
        "competente_en_norma": False, "competente_en_sector": True,
        "tiene_conflicto": True, "tiene_disponibilidad": False,
        "ya_en_la_solicitud": False,
    }])

    respuesta = await pedir(db, "Administrador", "get", f"{BASE}/auditores/candidatos")

    candidato = respuesta.json()["candidatos"][0]
    assert candidato["apto"] is False
    assert any("competencia vigente" in m for m in candidato["motivos"])
    assert any("conflicto de interés" in m for m in candidato["motivos"])


async def test_la_busqueda_sin_filtros_no_exige_los_permisos_de_filtro():
    """Cada filtro es un permiso distinto; solo se piden los que se usan."""
    db = BaseFalsa(filas=[])

    respuesta = await pedir(
        db, "Administrador", "get",
        f"{BASE}/auditores/candidatos?norma=false&excluir_conflictos=false",
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["filtros"]["norma"] is False


async def test_proponer_un_auditor_lo_deja_propuesto_no_asignado():
    db = BaseFalsa(registro=asignacion())

    await pedir(db, "Administrador", "post", f"{BASE}/auditores",
                json={"id_auditor": ID_AUDITOR, "especialidad": "Ambiental"})

    parametros = parametros_de(db, "INSERT INTO auditores_solicitud")
    assert parametros["estado"] == "Propuesto"


async def test_no_se_propone_un_auditor_con_conflicto_de_interes():
    db = BaseFalsa(conflicto="Es socio de la empresa")

    respuesta = await pedir(db, "Administrador", "post", f"{BASE}/auditores",
                            json={"id_auditor": ID_AUDITOR})

    assert respuesta.status_code == 409
    assert "conflicto de interés" in respuesta.json()["detail"]


# ============================================================
# BLOQUE 5 · APROBAR, REASIGNAR Y CANCELAR
# ============================================================

@pytest.mark.parametrize(
    "rol,esperado",
    [("Super Administrador", 200), ("Administrador", 200), ("Auxiliar", 202), ("Empresa", 403)],
)
async def test_aprobar_asignacion_segun_la_hoja(rol, esperado):
    """El Auxiliar tiene REQ: su petición queda pendiente (202)."""
    db = BaseFalsa(registro=asignacion("Propuesto"))

    respuesta = await pedir(db, rol, "post", f"{BASE}/auditores/{ID_ASIGNACION}/aprobar")

    assert respuesta.status_code == esperado


async def test_el_auxiliar_no_ejecuta_la_aprobacion_solo_la_pide():
    db = BaseFalsa(registro=asignacion("Propuesto"))

    await pedir(db, "Auxiliar", "post", f"{BASE}/auditores/{ID_ASIGNACION}/aprobar")

    assert not any(s.startswith("UPDATE auditores_solicitud") for s, _ in sentencias(db))
    assert any("INSERT INTO aprobacion_pendiente" in s for s, _ in sentencias(db))


async def test_solo_se_aprueba_lo_que_esta_propuesto():
    db = BaseFalsa(registro=asignacion("Cancelada"))

    respuesta = await pedir(db, "Administrador", "post", f"{BASE}/auditores/{ID_ASIGNACION}/aprobar")

    assert respuesta.status_code == 409


@pytest.mark.parametrize(
    "rol,esperado",
    [("Super Administrador", 200), ("Administrador", 403), ("Auxiliar", 202), ("Empresa", 403)],
)
async def test_reasignar_segun_la_hoja(rol, esperado):
    """SOL-049 es SA: ni siquiera el Administrador reasigna por su cuenta."""
    db = BaseFalsa(registro=asignacion("Asignado"))

    respuesta = await pedir(
        db, rol, "post", f"{BASE}/auditores/{ID_ASIGNACION}/reasignar",
        json={"id_nuevo_auditor": ID_OTRO_AUDITOR, "motivo": "Quedó sin disponibilidad."},
    )

    assert respuesta.status_code == esperado


async def test_reasignar_cierra_la_anterior_y_propone_la_nueva():
    db = BaseFalsa(registro=asignacion("Asignado"))

    await pedir(
        db, "Super Administrador", "post", f"{BASE}/auditores/{ID_ASIGNACION}/reasignar",
        json={"id_nuevo_auditor": ID_OTRO_AUDITOR, "motivo": "Quedó sin disponibilidad."},
    )

    ejecutadas = [s for s, _ in sentencias(db)]
    assert any(s.startswith("UPDATE auditores_solicitud") for s in ejecutadas)
    assert any(s.startswith("INSERT INTO auditores_solicitud") for s in ejecutadas)
    assert parametros_de(db, "INSERT INTO auditores_solicitud")["estado"] == "Propuesto"


async def test_cancelar_exige_motivo():
    db = BaseFalsa(registro=asignacion("Asignado"))

    respuesta = await pedir(db, "Administrador", "post",
                            f"{BASE}/auditores/{ID_ASIGNACION}/cancelar", json={})

    assert respuesta.status_code == 422


async def test_cancelar_guarda_el_motivo_y_quien_lo_hizo():
    db = BaseFalsa(registro=asignacion("Asignado"))

    await pedir(db, "Administrador", "post", f"{BASE}/auditores/{ID_ASIGNACION}/cancelar",
                json={"motivo": "La empresa aplazó la auditoría."})

    parametros = parametros_de(db, "UPDATE auditores_solicitud")
    assert parametros["motivo"] == "La empresa aplazó la auditoría."
    assert parametros["usuario"]


async def test_cada_movimiento_de_la_asignacion_deja_historial_y_bitacora():
    db = BaseFalsa(registro=asignacion("Propuesto"))

    await pedir(db, "Administrador", "post", f"{BASE}/auditores/{ID_ASIGNACION}/aprobar")

    ejecutadas = [s for s, _ in sentencias(db)]
    assert any(s.startswith("INSERT INTO historial_asignacion_auditor") for s in ejecutadas)
    assert any(s.startswith("INSERT INTO bitacora_solicitud") for s in ejecutadas)


# ============================================================
# BLOQUE 6 · TRAZABILIDAD
# ============================================================

@pytest.mark.parametrize(
    "rol,esperado",
    [
        ("Super Administrador", 200), ("Administrador", 200), ("Auxiliar", 200),
        ("Empresa", 200), ("Auditor", 200), ("Comité", 200), ("Publico", 403),
    ],
)
async def test_el_historial_lo_consulta_todo_el_mundo_menos_el_publico(rol, esperado):
    db = BaseFalsa(filas=[])

    respuesta = await pedir(db, rol, "get", f"{BASE}/historial")

    assert respuesta.status_code == esperado


@pytest.mark.parametrize(
    "rol,esperado",
    [("Administrador", 201), ("Auxiliar", 201), ("Auditor", 201), ("Empresa", 403), ("Comité", 403)],
)
async def test_la_observacion_de_control_la_registra_quien_dice_la_hoja(rol, esperado):
    """SOL-052 incluye al Auditor y deja fuera a la empresa y al Comité."""
    db = BaseFalsa(registro={"id_observacion": str(uuid.uuid4()), "id_solicitud": ID_SOLICITUD,
                             "texto": "Falta el alcance.", "tipo": "Control",
                             "id_usuario": None, "fecha": None})

    respuesta = await pedir(db, rol, "post", f"{BASE}/observaciones",
                            json={"texto": "Falta revisar el alcance."})

    assert respuesta.status_code == esperado


async def test_no_se_admite_un_tipo_de_observacion_inventado():
    db = BaseFalsa()

    respuesta = await pedir(db, "Administrador", "post", f"{BASE}/observaciones",
                            json={"texto": "Texto suficiente", "tipo": "Inventada"})

    assert respuesta.status_code == 400


async def test_cambiar_el_estado_guarda_historial_con_el_usuario():
    db = BaseFalsa(fila_solicitud=solicitud("Radicada"))

    await pedir(db, "Administrador", "patch", f"{BASE}/estado",
                json={"estado": "En revision", "motivo": "Pasa a revisión."})

    parametros = parametros_de(db, "INSERT INTO historial_estado")
    assert parametros["id_usuario"]
    assert "SOL-054" in parametros["observacion"]


async def test_no_se_admite_un_estado_fuera_del_catalogo():
    db = BaseFalsa()

    respuesta = await pedir(db, "Administrador", "patch", f"{BASE}/estado",
                            json={"estado": "Lo que sea"})

    assert respuesta.status_code == 400


async def test_una_solicitud_cerrada_no_admite_mas_cambios():
    db = BaseFalsa(registro=solicitud("Cerrada"))

    respuesta = await pedir(db, "Administrador", "patch", f"{BASE}/estado",
                            json={"estado": "Radicada"})

    assert respuesta.status_code == 409
    assert "cerrada" in respuesta.json()["detail"]


@pytest.mark.parametrize("estado", ["Cerrada", "CERRADA", "cerrada"])
def test_el_cierre_se_reconoce_escrito_de_varias_formas(estado):
    assert esta_cerrada(estado) is True


@pytest.mark.parametrize("estado", ["Radicada", "APROBADO", "En revision", None])
def test_no_se_confunde_el_cierre_con_otros_estados(estado):
    assert esta_cerrada(estado) is False


@pytest.mark.parametrize(
    "rol,esperado",
    [("Administrador", 200), ("Auxiliar", 200), ("Empresa", 403), ("Auditor", 403), ("Comité", 403)],
)
async def test_la_bitacora_es_para_la_administracion(rol, esperado):
    db = BaseFalsa(filas=[])

    respuesta = await pedir(db, rol, "get", f"{BASE}/bitacora")

    assert respuesta.status_code == esperado


async def test_cerrar_la_solicitud_exige_motivo_y_la_deja_cerrada():
    db = BaseFalsa(fila_solicitud=solicitud("Radicada"))

    sin_motivo = await pedir(db, "Administrador", "post", f"{BASE}/cerrar", json={})
    assert sin_motivo.status_code == 422

    db = BaseFalsa(registro=solicitud("Radicada"))
    await pedir(db, "Administrador", "post", f"{BASE}/cerrar",
                json={"motivo": "Proceso terminado."})
    assert parametros_de(db, "UPDATE solicitud")["estado"] == "Cerrada"


async def test_no_se_comparte_con_el_comite_una_solicitud_sin_documentos():
    db = BaseFalsa(documentos={"aprobados": 0, "total": 0})

    respuesta = await pedir(db, "Administrador", "post", f"{BASE}/comite")

    assert respuesta.status_code == 409


# ============================================================
# BLOQUE 7 · LA FÓRMULA
# ============================================================

def servicio_calculo():
    return CalculoAuditoriaService(AsyncMock())


@pytest.mark.parametrize(
    "empleados,sedes,complejidad,esperado",
    [
        (0, 1, "Baja", Decimal("8")),        # solo las horas de la norma
        (25, 1, "Baja", Decimal("10")),      # 8 + 25*0.08
        (25, 1, "Media", Decimal("11")),     # 10 + 10%
        (25, 1, "Alta", Decimal("12.5")),    # 10 + 25%
        (25, 3, "Baja", Decimal("18")),      # 10 + 2 sedes * 4
    ],
)
def test_la_formula_da_lo_que_dice_el_desglose(empleados, sedes, complejidad, esperado):
    horas, _ = servicio_calculo().aplicar_formula(
        {"numero_empleados": empleados, "numero_sedes": sedes, "complejidad": complejidad},
        dict(VARIABLES_BASE),
    )
    assert horas == esperado


def test_el_resultado_se_redondea_a_media_jornada():
    horas, _ = servicio_calculo().aplicar_formula(
        {"numero_empleados": 33, "numero_sedes": 1, "complejidad": "Media"},
        dict(VARIABLES_BASE),
    )
    assert (horas * 2) % 1 == 0


def test_el_desglose_explica_de_donde_sale_cada_hora():
    _, desglose = servicio_calculo().aplicar_formula(
        {"numero_empleados": 25, "numero_sedes": 2, "complejidad": "Alta"},
        dict(VARIABLES_BASE),
    )
    assert set(desglose) >= {
        "horas_por_la_norma", "horas_por_empleados",
        "horas_por_sedes_adicionales", "horas_por_complejidad", "total_sin_ajuste",
    }


@pytest.mark.parametrize("complejidad", ["Altisima", "media alta", "ALTA"])
def test_la_complejidad_tiene_que_ser_una_de_las_tres(complejidad):
    with pytest.raises(HTTPException) as error:
        servicio_calculo().aplicar_formula(
            {"numero_empleados": 1, "numero_sedes": 1, "complejidad": complejidad},
            dict(VARIABLES_BASE),
        )
    assert error.value.status_code == 400


def test_no_se_calcula_con_datos_imposibles():
    with pytest.raises(HTTPException):
        servicio_calculo().aplicar_formula(
            {"numero_empleados": -5, "numero_sedes": 1, "complejidad": "Media"},
            dict(VARIABLES_BASE),
        )


# ============================================================
# BLOQUE 7 · ENDPOINTS
# ============================================================

@pytest.mark.parametrize(
    "rol,esperado",
    [("Administrador", 201), ("Auxiliar", 201), ("Empresa", 403), ("Auditor", 403), ("Comité", 403)],
)
async def test_calcular_el_tiempo_segun_la_hoja(rol, esperado):
    db = BaseFalsa(registro=None)
    db.registro = solicitud()

    class Base(BaseFalsa):
        async def execute(self, sentencia, parametros=None):
            sql = " ".join(str(sentencia).split())
            self.sentencias.append((sql, parametros or {}))
            if "FROM user_empresa" in sql:
                return Respuesta(todas=[{"id_empresa": ID_EMPRESA}], escalar=ID_EMPRESA)
            if sql.startswith("SELECT") and "FROM calculo_auditoria" in sql:
                return Respuesta(primera=None)
            if sql.startswith("SELECT nom_variable"):
                return Respuesta(todas=[])
            if sql.startswith("INSERT INTO calculo_auditoria"):
                return Respuesta(primera=calculo())
            return Respuesta(primera=solicitud())

    respuesta = await pedir(Base(), rol, "post", f"{BASE}/calculo", json={"complejidad": "Media"})

    assert respuesta.status_code == esperado


@pytest.mark.parametrize(
    "rol,esperado",
    [("Super Administrador", 200), ("Administrador", 200), ("Auxiliar", 202), ("Empresa", 403)],
)
async def test_recalcular_segun_la_hoja(rol, esperado):
    class Base(BaseFalsa):
        async def execute(self, sentencia, parametros=None):
            sql = " ".join(str(sentencia).split())
            self.sentencias.append((sql, parametros or {}))
            if "FROM user_empresa" in sql:
                return Respuesta(todas=[{"id_empresa": ID_EMPRESA}], escalar=ID_EMPRESA)
            if sql.startswith("SELECT") and "FROM calculo_auditoria" in sql:
                return Respuesta(primera=calculo())
            if sql.startswith("SELECT nom_variable"):
                return Respuesta(todas=[])
            if sql.startswith("INSERT INTO calculo_auditoria"):
                return Respuesta(primera=calculo(version=2))
            return Respuesta(primera=solicitud())

    respuesta = await pedir(Base(), rol, "post", f"{BASE}/calculo/recalcular",
                            json={"complejidad": "Alta"})

    assert respuesta.status_code == esperado


async def test_el_ajuste_exige_una_justificacion_larga():
    db = BaseFalsa(registro=calculo())

    respuesta = await pedir(db, "Super Administrador", "post", f"{BASE}/calculo/ajuste",
                            json={"horas": 4, "justificacion": "corto"})

    assert respuesta.status_code == 422


@pytest.mark.parametrize(
    "rol,esperado",
    [("Super Administrador", 200), ("Administrador", 403), ("Auxiliar", 202), ("Empresa", 403)],
)
async def test_justificar_ajustes_es_exclusivo_del_superadministrador(rol, esperado):
    """SOL-065: SA para el SuperAdministrador, F para el Administrador."""
    class Base(BaseFalsa):
        async def execute(self, sentencia, parametros=None):
            sql = " ".join(str(sentencia).split())
            self.sentencias.append((sql, parametros or {}))
            if "FROM user_empresa" in sql:
                return Respuesta(todas=[{"id_empresa": ID_EMPRESA}], escalar=ID_EMPRESA)
            if "FROM calculo_auditoria" in sql or sql.startswith("UPDATE calculo_auditoria"):
                return Respuesta(primera=calculo())
            return Respuesta(primera=solicitud())

    respuesta = await pedir(Base(), rol, "post", f"{BASE}/calculo/ajuste",
                            json={"horas": 4, "justificacion": "La empresa trabaja en dos turnos."})

    assert respuesta.status_code == esperado


async def test_no_se_valida_un_ajuste_sin_justificacion():
    class Base(BaseFalsa):
        async def execute(self, sentencia, parametros=None):
            sql = " ".join(str(sentencia).split())
            self.sentencias.append((sql, parametros or {}))
            if "FROM user_empresa" in sql:
                return Respuesta(todas=[{"id_empresa": ID_EMPRESA}], escalar=ID_EMPRESA)
            if "FROM calculo_auditoria" in sql:
                return Respuesta(primera=calculo(ajuste_horas=Decimal("4"), justificacion_ajuste=None))
            return Respuesta(primera=solicitud())

    respuesta = await pedir(Base(), "Administrador", "post", f"{BASE}/calculo/validar")

    assert respuesta.status_code == 409
    assert "justificación" in respuesta.json()["detail"]


async def test_no_se_bloquea_un_calculo_sin_validar():
    class Base(BaseFalsa):
        async def execute(self, sentencia, parametros=None):
            sql = " ".join(str(sentencia).split())
            self.sentencias.append((sql, parametros or {}))
            if "FROM user_empresa" in sql:
                return Respuesta(todas=[{"id_empresa": ID_EMPRESA}], escalar=ID_EMPRESA)
            if "FROM calculo_auditoria" in sql:
                return Respuesta(primera=calculo(validado=False))
            return Respuesta(primera=solicitud())

    respuesta = await pedir(Base(), "Administrador", "post", f"{BASE}/calculo/bloquear")

    assert respuesta.status_code == 409


async def test_un_calculo_bloqueado_no_se_recalcula():
    class Base(BaseFalsa):
        async def execute(self, sentencia, parametros=None):
            sql = " ".join(str(sentencia).split())
            self.sentencias.append((sql, parametros or {}))
            if "FROM user_empresa" in sql:
                return Respuesta(todas=[{"id_empresa": ID_EMPRESA}], escalar=ID_EMPRESA)
            if "FROM calculo_auditoria" in sql:
                return Respuesta(primera=calculo(bloqueado=True, validado=True))
            return Respuesta(primera=solicitud())

    respuesta = await pedir(Base(), "Administrador", "post", f"{BASE}/calculo/recalcular", json={})

    assert respuesta.status_code == 409
    assert "bloqueado" in respuesta.json()["detail"]


async def test_el_resultado_del_calculo_lo_ve_tambien_el_auditor_y_el_comite():
    """SOL-064 los incluye: necesitan saber cuántas horas se planificaron."""
    class Base(BaseFalsa):
        async def execute(self, sentencia, parametros=None):
            sql = " ".join(str(sentencia).split())
            self.sentencias.append((sql, parametros or {}))
            if "FROM user_empresa" in sql:
                return Respuesta(todas=[{"id_empresa": ID_EMPRESA}], escalar=ID_EMPRESA)
            if "FROM calculo_auditoria" in sql:
                return Respuesta(primera=calculo())
            return Respuesta(primera=solicitud())

    for rol in ("Auditor", "Comité", "Administrador"):
        assert (await pedir(Base(), rol, "get", f"{BASE}/calculo")).status_code == 200
    assert (await pedir(Base(), "Empresa", "get", f"{BASE}/calculo")).status_code == 403


async def test_las_variables_base_de_la_norma_solo_las_cambia_el_superadministrador():
    db = BaseFalsa(filas=[])

    ruta = f"/solicitudes/calculo/normas/{ID_NORMA}/variables"
    cuerpo = {"valores": {"horas_base": 10}}

    assert (await pedir(db, "Super Administrador", "put", ruta, json=cuerpo)).status_code == 200
    assert (await pedir(db, "Administrador", "put", ruta, json=cuerpo)).status_code == 403
    assert (await pedir(db, "Auxiliar", "put", ruta, json=cuerpo)).status_code == 403


async def test_no_se_admiten_variables_inventadas_para_la_norma():
    db = BaseFalsa(filas=[])

    respuesta = await pedir(
        db, "Super Administrador", "put", f"/solicitudes/calculo/normas/{ID_NORMA}/variables",
        json={"valores": {"horas_magicas": 3}},
    )

    assert respuesta.status_code == 400
    assert "horas_magicas" in respuesta.json()["detail"]
