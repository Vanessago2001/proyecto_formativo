"""
Validación de acceso por rol y de los dashboards (tarea secundaria).

Comprueba tres cosas:
  1. Que cada destino al que el login redirige exista de verdad como ruta y
     como archivo estático (nadie debe caer en un 404 tras iniciar sesión).
  2. Que todos los roles de la matriz de permisos tengan un dashboard asignado.
  3. Que las rutas de dashboard no queden abiertas por accidente a datos de
     la API sin autenticar.

El mapa rol -> destino se lee del propio `static/login.html`, así que si
alguien cambia la redirección y no actualiza el resto, el test lo detecta.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app
from modules.solicitudes.solicitud_permissions import (
    ROL_PUB,
    ROLES_DEL_SISTEMA,
    normalizar_rol,
)

RAIZ = Path(__file__).resolve().parent.parent
LOGIN_HTML = RAIZ / "static" / "login.html"
ESTATICOS = RAIZ / "static"

# Dashboard que recibe cualquier rol sin destino propio.
DESTINO_POR_DEFECTO = "/dashboard"

cliente = TestClient(app)


# ============================================================
# LECTURA DEL MAPA ROL -> DASHBOARD
# ============================================================

def leer_mapa_de_redireccion() -> dict[str, str]:
    """
    Extrae el mapa rol -> ruta del ternario de `login.html`.

    Busca los pares `payload.role_name === "X" ? "/y"` que decide a dónde
    va el usuario después de autenticarse.
    """
    html = LOGIN_HTML.read_text(encoding="utf-8")

    pares = re.findall(
        r'role_name\s*===\s*"([^"]+)"\s*\?\s*"([^"]+)"',
        html,
    )

    mapa = {rol: destino for rol, destino in pares}
    mapa.setdefault("__default__", DESTINO_POR_DEFECTO)
    return mapa


MAPA = leer_mapa_de_redireccion()


def destino_de(rol: str) -> str:
    """Ruta a la que el login envía a un rol dado."""
    return MAPA.get(rol, MAPA["__default__"])


def rutas_get_de_la_app() -> set[str]:
    return {
        ruta.path
        for ruta in app.routes
        if "GET" in getattr(ruta, "methods", set())
    }


# ============================================================
# 1. LOS DESTINOS EXISTEN
# ============================================================

def test_el_login_define_al_menos_un_dashboard_por_rol():
    """Si el ternario desaparece del login, este test avisa."""
    assert len(MAPA) > 1, (
        "No se encontró ninguna redirección por rol en static/login.html; "
        "revise si cambió la forma de decidir el dashboard."
    )


@pytest.mark.parametrize("destino", sorted(set(MAPA.values())))
def test_cada_destino_del_login_es_una_ruta_registrada(destino):
    """Ningún rol puede terminar en una ruta que no existe."""
    assert destino in rutas_get_de_la_app(), (
        f"El login redirige a '{destino}', pero esa ruta no está registrada "
        f"en main.py."
    )


@pytest.mark.parametrize("destino", sorted(set(MAPA.values())))
def test_cada_destino_del_login_responde_html(destino):
    """La página del dashboard debe servirse, no dar 404 ni 500."""
    respuesta = cliente.get(destino)

    assert respuesta.status_code == 200, (
        f"'{destino}' respondió {respuesta.status_code} en lugar de 200."
    )
    assert "text/html" in respuesta.headers["content-type"]


@pytest.mark.parametrize("destino", sorted(set(MAPA.values())))
def test_el_archivo_estatico_del_destino_existe(destino):
    """El FileResponse apunta a un archivo real dentro de static/."""
    nombre = f"{destino.strip('/')}.html"
    assert (ESTATICOS / nombre).is_file(), (
        f"Falta el archivo static/{nombre} que sirve la ruta '{destino}'."
    )


# ============================================================
# 2. COBERTURA DE LOS ROLES DE LA MATRIZ
# ============================================================

ROLES_AUTENTICADOS = [rol for rol in ROLES_DEL_SISTEMA if rol != ROL_PUB]


@pytest.mark.parametrize("rol", ROLES_AUTENTICADOS)
def test_todo_rol_autenticado_llega_a_un_dashboard_existente(rol):
    """
    Ningún rol de la matriz puede quedarse sin destino tras iniciar sesión.

    Los roles sin dashboard propio caen en el genérico `/dashboard`, que sí
    debe existir.
    """
    destino = destino_de(rol)

    assert destino in rutas_get_de_la_app(), (
        f"El rol '{rol}' sería enviado a '{destino}', que no existe."
    )
    assert cliente.get(destino).status_code == 200


def test_el_rol_publico_no_tiene_dashboard_propio():
    """
    'Publico' es el portal de consulta abierta (M11), no un rol con sesión.

    Este test deja constancia de que hoy comparte el dashboard genérico: si
    en el futuro se le asigna una vista propia, habrá que actualizarlo.
    """
    assert destino_de(ROL_PUB) == DESTINO_POR_DEFECTO


def test_los_nombres_de_rol_del_login_son_reconocidos_por_la_matriz():
    """
    Los roles escritos en login.html deben existir en la matriz de permisos.

    Evita que el front redirija por un nombre de rol que el backend no
    reconoce (por ejemplo 'Empresas' en plural).
    """
    for rol in MAPA:
        if rol == "__default__":
            continue
        assert normalizar_rol(rol) is not None, (
            f"login.html redirige por el rol '{rol}', que la matriz de "
            f"permisos no reconoce."
        )


# ============================================================
# 3. LAS RUTAS DE LA API SÍ EXIGEN AUTENTICACIÓN
# ============================================================

def test_la_api_de_solicitudes_no_responde_sin_token():
    """El dashboard es HTML público, pero sus datos no pueden serlo."""
    respuesta = cliente.get("/solicitudes/")
    assert respuesta.status_code == 401


def test_ninguna_pagina_lleva_credenciales_incrustadas():
    """
    Las vistas se sirven sin token (son HTML estático), así que no pueden
    traer credenciales ni tokens quemados en el código.
    """
    sospechosos = re.compile(
        r"(eyJ[A-Za-z0-9_-]{10,}\.)"        # un JWT literal
        r"|(bearer\s+[A-Za-z0-9._-]{20,})"  # una cabecera Authorization fija
        r"|(secret_key\s*[:=])",            # una clave del servidor
        re.IGNORECASE,
    )

    for destino in sorted(set(MAPA.values())):
        cuerpo = cliente.get(destino).text
        encontrado = sospechosos.search(cuerpo)
        assert not encontrado, (
            f"La página '{destino}' contiene una credencial incrustada: "
            f"{encontrado.group(0)[:40]}"
        )
