"""
M3/M5 — Requisitos de la empresa para radicar y aprobar una solicitud.

Flujo acordado (18/11/2026):

  1. La empresa sube sus documentos legales obligatorios (EMP-011) y
     registra al menos una sede.
  2. Solo puede RADICAR (SOL-005) si:
       · tiene todos los documentos legales obligatorios subidos y vigentes
         (no rechazados, sin corrección pendiente, no vencidos), y
       · la solicitud incluye al menos una sede activa de la empresa.
  3. El Coordinador solo puede APROBAR la solicitud (SOL-054 -> Aprobada) si
     esos documentos legales obligatorios están **aprobados** y la solicitud
     sigue teniendo al menos una sede incluida.
  4. La visita (M6) solo se programa en una sede incluida en la solicitud.

Documentos obligatorios: la base no marca ningún tipo como obligatorio (la
tabla `documento_empresa` solo tiene la restricción `chk_tipo_documento`
con RUT, RUNT, Cámara de Comercio, Representación Legal, Certificación y
Otro). Se toman como obligatorios los tres tipos existentes que son
documentos legales de cualquier empresa colombiana; RUNT, Certificación y
Otro quedan opcionales. Cambiar la lista es cambiar esta constante.
Confirmado por el equipo el 20/11/2026: RUT, Cámara de Comercio y
Representación Legal.

Sede principal (20/11/2026): toda solicitud debe incluir la sede principal
de la empresa. Se exige al radicar, al aprobar y al asignar auditor
(exigir_sede_principal_para_asignar).
"""

from datetime import date
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DOCUMENTOS_LEGALES_OBLIGATORIOS = (
    "RUT",
    "Cámara de Comercio",
    "Representación Legal",
)

# Para radicar basta con que el documento esté subido y no tenga problemas.
ESTADOS_VALIDOS_PARA_RADICAR = {"Pendiente", "Aprobado"}
ESTADO_APROBADO = "Aprobado"

MOTIVOS = {
    None: "sin subir",
    "Rechazado": "rechazado: debe subir uno nuevo",
    "Correccion": "con corrección pedida: debe reemplazarlo",
    "Vencido": "vencido: debe subir uno vigente",
    "Pendiente": "pendiente de revisión",
}

# Prioridad cuando la empresa tiene varias filas del mismo tipo: cuenta la
# mejor (un aprobado vigente gana a un pendiente, y este a un rechazado).
_PRIORIDAD = {"Aprobado": 0, "Pendiente": 1, "Correccion": 2, "Rechazado": 3, "Vencido": 4}


def _estado_efectivo(fila: dict) -> str:
    vence = fila.get("fecha_vencimiento")
    if vence and isinstance(vence, date) and vence < date.today():
        return "Vencido"
    return fila.get("estado_validacion") or "Pendiente"


async def requisitos_empresa(db: AsyncSession, id_empresa) -> dict:
    """Lista de verificación de la empresa: documentos legales y sedes."""
    resultado = await db.execute(
        text("""
            SELECT id_documento, tipo_documento, nombre_archivo, version,
                   estado_validacion, observaciones, fecha_vencimiento, fecha_subida
            FROM documento_empresa
            WHERE id_empresa = :id_empresa
            ORDER BY fecha_subida DESC NULLS LAST;
        """),
        {"id_empresa": str(id_empresa)},
    )
    filas = [dict(f) for f in resultado.mappings().all()]

    sedes = await db.execute(
        text("""
            SELECT COUNT(*)
            FROM sede_empresa
            WHERE id_empresa = :id_empresa AND estado = 'Activa';
        """),
        {"id_empresa": str(id_empresa)},
    )
    sedes_activas = int(sedes.scalar() or 0)

    documentos = []
    for tipo in DOCUMENTOS_LEGALES_OBLIGATORIOS:
        del_tipo = [f for f in filas if f.get("tipo_documento") == tipo]
        del_tipo.sort(key=lambda f: _PRIORIDAD.get(_estado_efectivo(f), 9))
        mejor = del_tipo[0] if del_tipo else None
        estado = _estado_efectivo(mejor) if mejor else None
        documentos.append({
            "tipo_documento": tipo,
            "id_documento": mejor["id_documento"] if mejor else None,
            "nombre_archivo": mejor.get("nombre_archivo") if mejor else None,
            "version": mejor.get("version") if mejor else None,
            "estado": estado,
            "observaciones": mejor.get("observaciones") if mejor else None,
            "fecha_vencimiento": mejor.get("fecha_vencimiento") if mejor else None,
            "subido": mejor is not None,
            "valido_para_radicar": estado in ESTADOS_VALIDOS_PARA_RADICAR,
            "aprobado": estado == ESTADO_APROBADO,
            "situacion": "aprobado" if estado == ESTADO_APROBADO else MOTIVOS.get(estado, estado),
        })

    al_dia = sum(1 for d in documentos if d["valido_para_radicar"])
    aprobados = sum(1 for d in documentos if d["aprobado"])
    faltantes = [
        f"{d['tipo_documento']} ({d['situacion']})"
        for d in documentos
        if not d["valido_para_radicar"]
    ]
    return {
        "id_empresa": str(id_empresa),
        "documentos_obligatorios": list(DOCUMENTOS_LEGALES_OBLIGATORIOS),
        "documentos": documentos,
        "documentos_total": len(DOCUMENTOS_LEGALES_OBLIGATORIOS),
        "documentos_al_dia": al_dia,
        "documentos_aprobados": aprobados,
        "documentos_faltantes": faltantes,
        "sedes_activas": sedes_activas,
        "completo": not faltantes and sedes_activas > 0,
    }


async def sedes_incluidas(db: AsyncSession, id_solicitud) -> int:
    """Sedes activas de la empresa incluidas (no excluidas) en la solicitud."""
    resultado = await db.execute(
        text("""
            SELECT COUNT(*)
            FROM solicitud_sede ss
            JOIN sede_empresa se ON se.id_sede = ss.id_sede
            WHERE ss.id_solicitud = :id_solicitud
              AND ss.estado <> 'Excluida'
              AND se.estado = 'Activa';
        """),
        {"id_solicitud": str(id_solicitud)},
    )
    return int(resultado.scalar() or 0)


async def sedes_principales_incluidas(db: AsyncSession, id_solicitud) -> int:
    """Sedes principales (activas) de la empresa incluidas en la solicitud."""
    resultado = await db.execute(
        text("""
            SELECT COUNT(*)
            FROM solicitud_sede ss
            JOIN sede_empresa se ON se.id_sede = ss.id_sede
            WHERE ss.id_solicitud = :id_solicitud
              AND ss.estado <> 'Excluida'
              AND se.estado = 'Activa'
              AND se.es_principal IS TRUE;
        """),
        {"id_solicitud": str(id_solicitud)},
    )
    return int(resultado.scalar() or 0)


def faltantes_para_radicar(
    requisitos: dict, sedes_en_solicitud: int, principales: int | None = None
) -> list[str]:
    """Lo que le falta a la empresa/solicitud para poder radicar.

    `principales` es el número de sedes principales incluidas; None = no se
    revisa (llamadas antiguas).
    """
    faltan = []
    if requisitos["documentos_faltantes"]:
        faltan.append(
            "documentos legales obligatorios: " + "; ".join(requisitos["documentos_faltantes"])
        )
    if sedes_en_solicitud < 1:
        faltan.append("incluir al menos una sede activa de la empresa en la solicitud")
    elif principales is not None and principales < 1:
        faltan.append("incluir la sede principal de la empresa en la solicitud")
    return faltan


def faltantes_para_aprobar(
    requisitos: dict, sedes_en_solicitud: int, principales: int | None = None
) -> list[str]:
    """Lo que falta para que el Coordinador pueda aprobar la solicitud."""
    faltan = []
    sin_aprobar = [
        f"{d['tipo_documento']} ({d['situacion']})"
        for d in requisitos["documentos"]
        if not d["aprobado"]
    ]
    if sin_aprobar:
        faltan.append("aprobar los documentos legales obligatorios: " + "; ".join(sin_aprobar))
    if sedes_en_solicitud < 1:
        faltan.append("la solicitud no tiene ninguna sede incluida")
    elif principales is not None and principales < 1:
        faltan.append("la solicitud no incluye la sede principal de la empresa")
    return faltan


async def exigir_requisitos_para_radicar(db: AsyncSession, id_empresa, id_solicitud) -> None:
    requisitos = await requisitos_empresa(db, id_empresa)
    faltan = faltantes_para_radicar(
        requisitos,
        await sedes_incluidas(db, id_solicitud),
        await sedes_principales_incluidas(db, id_solicitud),
    )
    if faltan:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No se puede enviar (radicar) la solicitud. Falta: " + " | ".join(faltan) + ".",
        )


async def exigir_requisitos_para_aprobar(db: AsyncSession, id_empresa, id_solicitud) -> None:
    requisitos = await requisitos_empresa(db, id_empresa)
    faltan = faltantes_para_aprobar(
        requisitos,
        await sedes_incluidas(db, id_solicitud),
        await sedes_principales_incluidas(db, id_solicitud),
    )
    if faltan:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede aprobar la solicitud. Falta: " + " | ".join(faltan) + ".",
        )


async def exigir_sede_principal_para_asignar(db: AsyncSession, id_solicitud) -> None:
    """El auditor se asigna a una solicitud que incluye su sede principal.

    La visita de cada sede se programa luego en la Agenda con ese auditor
    (exigir_sede_de_la_solicitud), así que la asignación siempre llega a una
    sede de la solicitud.
    """
    if await sedes_principales_incluidas(db, id_solicitud) < 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No se puede asignar auditor: la solicitud no incluye la sede "
                "principal de la empresa. Agregue la sede principal a la solicitud."
            ),
        )


async def exigir_sede_de_la_solicitud(db: AsyncSession, id_solicitud, id_sede) -> None:
    """La visita se programa en una sede activa incluida en la solicitud."""
    if not id_sede:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Seleccione la sede de la visita: debe ser una de las sedes "
                "incluidas en la solicitud."
            ),
        )
    resultado = await db.execute(
        text("""
            SELECT 1
            FROM solicitud_sede ss
            JOIN sede_empresa se ON se.id_sede = ss.id_sede
            WHERE ss.id_solicitud = :id_solicitud
              AND ss.id_sede = :id_sede
              AND ss.estado <> 'Excluida'
              AND se.estado = 'Activa'
            LIMIT 1;
        """),
        {"id_solicitud": str(id_solicitud), "id_sede": str(UUID(str(id_sede)))},
    )
    if resultado.first() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "La sede elegida no está incluida en la solicitud (o está inactiva). "
                "La visita solo se programa en una sede de la solicitud."
            ),
        )
