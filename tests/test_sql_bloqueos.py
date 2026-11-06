"""Regresión: `FOR UPDATE` sin `OF` junto a un LEFT JOIN rompe en PostgreSQL.

PostgreSQL responde "FOR UPDATE cannot be applied to the nullable side of an
outer join". Ese error impedía inactivar o reactivar auditores (Gestionar
usuarios y Auditores registrados respondían 500). Hay que indicar qué tabla
se bloquea: `FOR UPDATE OF u`.
"""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "modules"
CONSULTA = re.compile(r'"""(.*?)"""', re.S)
BLOQUEO_SIN_OF = re.compile(r"\bFOR\s+UPDATE\b(?!\s+OF\b)", re.I)
JOIN_EXTERNO = re.compile(r"\b(LEFT|RIGHT|FULL)\s+(OUTER\s+)?JOIN\b", re.I)


def test_ningun_for_update_sin_of_en_consultas_con_join_externo():
    problemas = []
    for archivo in RAIZ.rglob("*.py"):
        texto = archivo.read_text(encoding="utf-8")
        for consulta in CONSULTA.finditer(texto):
            sql = consulta.group(1)
            if BLOQUEO_SIN_OF.search(sql) and JOIN_EXTERNO.search(sql):
                linea = texto[: consulta.start()].count("\n") + 1
                problemas.append(f"{archivo.relative_to(RAIZ.parent)}:{linea}")
    assert not problemas, "Use 'FOR UPDATE OF <tabla>' en: " + ", ".join(problemas)


def test_inactivar_auditor_bloquea_solo_la_fila_del_usuario():
    texto = (RAIZ / "auditores_registrados" / "auditores_registrados_service.py").read_text(encoding="utf-8")
    assert "FOR UPDATE OF u" in texto
