"""
El Comité ya no tiene "Gestión de certificados" (18/11/2026) y, al aprobar o
rechazar, el líder firma el acta en el mismo detalle (static/comite.html).
Pruebas estáticas: no usan la base ni el lifespan de la app.
"""

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NAV = (RAIZ / "static" / "nav.js").read_text(encoding="utf-8")
COMITE = (RAIZ / "static" / "comite.html").read_text(encoding="utf-8")
CERTIFICADOS = (RAIZ / "static" / "certificados.html").read_text(encoding="utf-8")
PERFIL = (RAIZ / "static" / "profile.html").read_text(encoding="utf-8")


def _bloque(nombre: str) -> str:
    return NAV.split(f"var {nombre}", 1)[1].split("\n  };", 1)[0]


def test_menu_del_comite_sin_gestion_de_certificados():
    menu = _bloque("MENU_COMITE")
    lineas_codigo = [l for l in menu.splitlines() if l.strip() and not l.strip().startswith("//")]
    assert not any("GRUPO_CERTIFICADOS" in l for l in lineas_codigo)
    # El Coordinador y el Auxiliar la conservan.
    assert "GRUPO_CERTIFICADOS," in _bloque("MENU_ADMINISTRACION")


def test_comite_y_perfil_no_enlazan_a_gestion_de_certificados():
    assert 'href="/gestion-certificados"' not in COMITE
    assert 'href="/gestion-certificados"' not in PERFIL
    assert 'href="/comite#firmas"' in PERFIL


def test_gestion_certificados_redirige_al_comite():
    assert 'role === "comite"' in CERTIFICADOS
    assert '"/comite#firmas" : "/comite"' in CERTIFICADOS
    # La consulta pública no se redirige.
    assert "if (!publicMode && role === \"comite\")" in CERTIFICADOS


def test_firma_del_acta_tras_aprobar_o_rechazar():
    assert 'const DICTAMENES_CON_ACTA = ["/comite/aprobar", "/comite/rechazar"];' in COMITE
    assert "/comite/acta-estado/" in COMITE and "trasDictamen(path" in COMITE
    assert 'id="avisoDictamen" class="aviso-firmas" role="status"' in COMITE
    assert "pendiente de que el Coordinador asigne el líder" in COMITE
    assert "/comite/firmar-acta" in COMITE and "firmaTrasDictamenError" in COMITE
