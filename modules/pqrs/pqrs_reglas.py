"""
PQRS · reglas puras del módulo (sin base de datos).

Aquí vive todo lo que se puede decidir sin consultar la base: la matriz de
permisos de la hoja "pqr" de documentacion/permisos.xlsx, los roles, el flujo
de estados, el cálculo de días hábiles y el semáforo de tiempos. El servicio
(pqrs_service.py) consulta la base y delega en estas funciones, de modo que
las pruebas cubren las reglas sin tocar la base real.

La interpretación de las celdas "Cond." y "Propias" está documentada en el
docstring de `modules/pqrs/pqrs_service.py`.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from functools import lru_cache

from core.security import _normalize_role_name

# ---------------------------------------------------------------------------
# Matriz de permisos: transcripción literal de la hoja "pqr".
# Columnas: SUPERADM ADM AUX EMP AUD COM APR PUB
# Una prueba la compara celda por celda con el Excel.
# ---------------------------------------------------------------------------

COLUMNAS_MATRIZ = ("SUPERADM", "ADM", "AUX", "EMP", "AUD", "COM", "APR", "PUB")

SI = "✓"
NO = "—"
COND = "Cond."
PROPIAS = "Propias"
SISTEMA = "Sistema"

PERMISOS_PQR: dict[str, tuple[str, tuple[str, ...]]] = {
    #                                                SUPERADM ADM   AUX   EMP      AUD   COM APR PUB
    "PQR-001": ("Registrar PQRS",                   (SI, SI, COND, SI, NO, NO, NO, SI)),
    "PQR-002": ("Generar número de radicado",       (SISTEMA, SISTEMA, SISTEMA, SISTEMA, NO, NO, NO, SISTEMA)),
    "PQR-003": ("Consultar PQRS",                   (SI, SI, COND, PROPIAS, COND, NO, NO, PROPIAS)),
    "PQR-004": ("Consultar estado",                 (SI, SI, COND, PROPIAS, COND, NO, NO, PROPIAS)),
    "PQR-005": ("Asignar responsable",              (SI, COND, COND, NO, NO, NO, NO, NO)),
    "PQR-006": ("Cambiar estado",                   (SI, COND, COND, NO, NO, NO, NO, NO)),
    "PQR-007": ("Solicitar información adicional",  (SI, COND, COND, NO, NO, NO, NO, NO)),
    "PQR-008": ("Registrar respuesta",              (SI, COND, COND, NO, NO, NO, NO, NO)),
    "PQR-009": ("Notificar respuesta",              (SISTEMA, SISTEMA, SISTEMA, NO, NO, NO, NO, NO)),
    "PQR-010": ("Consultar historial",              (SI, SI, COND, PROPIAS, COND, NO, NO, PROPIAS)),
    "PQR-011": ("Adjuntar evidencia",               (SI, COND, COND, COND, NO, NO, NO, COND)),
    "PQR-012": ("Cerrar PQRS",                      (SI, COND, COND, NO, NO, NO, NO, NO)),
    "PQR-013": ("Reabrir PQRS",                     (SI, COND, COND, COND, NO, NO, NO, COND)),
    "PQR-014": ("Consultar tiempos de atención",    (SI, SI, COND, COND, SI, NO, NO, NO)),
    "PQR-015": ("Generar reporte de PQRS",          (SI, SI, COND, NO, SI, NO, NO, NO)),
}

# Roles del módulo. El super administrador ya no se usa: el administrador
# hace todo lo que la hoja concede a SUPERADM.
ROL_ADMIN = "admin"
ROL_AUXILIAR = "auxiliar"
ROL_EMPRESA = "empresa"
ROL_AUDITOR = "auditor"
ROL_PUBLICO = "publico"
ROL_SIN_ACCESO = "sin_acceso"

# Columna de la matriz que manda para cada rol del módulo.
COLUMNA_DE_ROL = {
    ROL_ADMIN: "SUPERADM",
    ROL_AUXILIAR: "AUX",
    ROL_EMPRESA: "EMP",
    ROL_AUDITOR: "AUD",
    ROL_PUBLICO: "PUB",
}


def rol_pqrs(usuario: dict | None) -> str:
    """Traduce el rol de la sesión al rol del módulo (None = visitante)."""
    if usuario is None:
        return ROL_PUBLICO
    rol = _normalize_role_name(usuario.get("role_name"))
    if rol in ("admin", "superadmin"):
        return ROL_ADMIN
    if rol in (ROL_AUXILIAR, ROL_EMPRESA):
        return rol
    # El auditor no gestiona ni consulta PQRS (decisión del equipo, 06/11/2026):
    # solo las gestionan el Administrador y los auxiliares a los que él les
    # delega el permiso. La columna AUD de la hoja "pqr" queda sin efecto.
    return ROL_SIN_ACCESO


def valor_matriz(codigo: str, rol: str) -> str:
    columna = COLUMNA_DE_ROL.get(rol)
    if columna is None:
        return NO
    return PERMISOS_PQR[codigo][1][COLUMNAS_MATRIZ.index(columna)]


def tiene_permiso(codigo: str, rol: str) -> bool:
    """La celda concede algo (✓, Cond., Propias o Sistema). Las condiciones
    concretas las aplica el servicio."""
    return valor_matriz(codigo, rol) != NO


# ---------------------------------------------------------------------------
# Catálogos
# ---------------------------------------------------------------------------

TIPOS = ("Petición", "Queja", "Reclamo", "Sugerencia", "Felicitación")

RADICADA = "Radicada"
ASIGNADA = "Asignada"
EN_TRAMITE = "En trámite"
INFO_SOLICITADA = "Información solicitada"
RESPONDIDA = "Respondida"
CERRADA = "Cerrada"
REABIERTA = "Reabierta"

ESTADOS = (RADICADA, ASIGNADA, EN_TRAMITE, INFO_SOLICITADA, RESPONDIDA, CERRADA, REABIERTA)
ESTADOS_ABIERTOS = (RADICADA, ASIGNADA, EN_TRAMITE, INFO_SOLICITADA, REABIERTA)

CANALES = ("Web", "Presencial", "Telefónico", "Correo electrónico")
CANALES_ASISTIDOS = ("Presencial", "Telefónico", "Correo electrónico")

TIPOS_DOCUMENTO = (
    "Cédula de Ciudadanía",
    "Cédula de Extranjería",
    "Tarjeta de Identidad",
    "Pasaporte",
    "NIT",
    "PPT",
)

# Flujo: estado actual -> estados a los que se puede pasar.
TRANSICIONES: dict[str, frozenset[str]] = {
    RADICADA: frozenset({ASIGNADA}),
    ASIGNADA: frozenset({EN_TRAMITE}),
    EN_TRAMITE: frozenset({INFO_SOLICITADA, RESPONDIDA}),
    INFO_SOLICITADA: frozenset({EN_TRAMITE, CERRADA}),
    RESPONDIDA: frozenset({CERRADA, EN_TRAMITE}),
    CERRADA: frozenset({REABIERTA}),
    REABIERTA: frozenset({EN_TRAMITE}),
}

# Lo que se puede elegir en "Cambiar estado" (PQR-006). El resto de estados
# tiene su propia acción porque exige datos: Asignada (responsable),
# Información solicitada (qué se pide), Respondida (la respuesta),
# Cerrada (cierre) y Reabierta (motivo).
ESTADOS_CAMBIO_MANUAL = frozenset({EN_TRAMITE})

PLAZO_DIAS_HABILES_POR_DEFECTO = 15
DIAS_ALERTA_POR_DEFECTO = 3
DIAS_PARA_REABRIR = 15                # calendario, contados desde el cierre
REAPERTURAS_PETICIONARIO = 1

EXTENSIONES_ADJUNTO = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
TAMANO_MAXIMO_ADJUNTO = 5 * 1024 * 1024
MAX_ADJUNTOS_POR_ENVIO = 5

RADICADO_PATRON = re.compile(r"^PQRS-\d{4}-\d{6,}$")


class ReglaPqrsError(ValueError):
    """Una regla de negocio impide la operación. `codigo` es el HTTP sugerido."""

    def __init__(self, mensaje: str, codigo: int = 409):
        super().__init__(mensaje)
        self.codigo = codigo


def _sin_tildes(texto: str) -> str:
    base = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in base if unicodedata.category(c) != "Mn").strip().lower()


def _buscar(catalogo, valor: str | None, que: str) -> str:
    buscado = _sin_tildes(str(valor or "")).replace("_", " ")
    for opcion in catalogo:
        if _sin_tildes(opcion) == buscado:
            return opcion
    raise ReglaPqrsError(f"{que} no válido: {valor}.", 422)


def normalizar_tipo(valor: str | None) -> str:
    return _buscar(TIPOS, valor, "Tipo de PQRS")


def normalizar_estado(valor: str | None) -> str:
    return _buscar(ESTADOS, valor, "Estado")


def normalizar_canal(valor: str | None) -> str:
    return _buscar(CANALES, valor, "Canal")


def generar_radicado(anio: int, consecutivo: int) -> str:
    """PQRS-AAAA-000001. La unicidad la garantizan la secuencia de la base
    (nunca repite un número) y la restricción UNIQUE de la columna."""
    return f"PQRS-{anio:04d}-{consecutivo:06d}"


def validar_transicion(actual: str, nuevo: str) -> None:
    if nuevo not in TRANSICIONES.get(actual, frozenset()):
        raise ReglaPqrsError(
            f"No se puede pasar una PQRS de «{actual}» a «{nuevo}».", 409
        )


def validar_reapertura(
    pqrs: dict, rol: str, ahora: datetime | None = None
) -> None:
    """PQR-013. Solo se reabre lo cerrado; el peticionario (EMP/PUB) tiene
    15 días calendario desde el cierre y una sola reapertura."""
    validar_transicion(pqrs.get("estado"), REABIERTA)
    if rol not in (ROL_EMPRESA, ROL_PUBLICO):
        return
    if int(pqrs.get("veces_reabierta") or 0) >= REAPERTURAS_PETICIONARIO:
        raise ReglaPqrsError("Esta PQRS ya fue reabierta una vez; radica una nueva si lo necesitas.", 409)
    cierre = pqrs.get("fecha_cierre")
    if cierre is None:
        raise ReglaPqrsError("La PQRS no tiene fecha de cierre registrada.", 409)
    if ahora is None:
        ahora = datetime.now(cierre.tzinfo) if isinstance(cierre, datetime) else datetime.now()
    if isinstance(cierre, datetime) and isinstance(ahora, datetime) and cierre.tzinfo and ahora.tzinfo:
        # Se compara en la hora oficial del sistema para no correr el día.
        from core.datetime_utils import SYSTEM_TIMEZONE
        cierre = cierre.astimezone(SYSTEM_TIMEZONE)
        ahora = ahora.astimezone(SYSTEM_TIMEZONE)
    dia_cierre = cierre.date() if isinstance(cierre, datetime) else cierre
    dia_actual = ahora.date() if isinstance(ahora, datetime) else ahora
    if (dia_actual - dia_cierre).days > DIAS_PARA_REABRIR:
        raise ReglaPqrsError(
            f"El plazo para reabrir venció: son {DIAS_PARA_REABRIR} días calendario desde el cierre.", 409
        )


def validar_adjunto(nombre: str | None, contenido: bytes) -> tuple[str, str, str]:
    """Devuelve (nombre_seguro, extension, tipo_mime) o lanza ReglaPqrsError."""
    from pathlib import Path

    nombre_seguro = Path(nombre or "").name.strip()
    nombre_seguro = re.sub(r"[^\w.\- ()áéíóúÁÉÍÓÚñÑ]", "_", nombre_seguro)[:200]
    extension = Path(nombre_seguro).suffix.lower()
    if not nombre_seguro or extension not in EXTENSIONES_ADJUNTO:
        raise ReglaPqrsError("Formato no permitido. Solo se aceptan PDF, JPG, PNG o DOCX.", 415)
    if not contenido:
        raise ReglaPqrsError(f"El archivo «{nombre_seguro}» está vacío.", 400)
    if len(contenido) > TAMANO_MAXIMO_ADJUNTO:
        raise ReglaPqrsError(f"El archivo «{nombre_seguro}» supera el máximo de 5 MB.", 413)
    # El contenido debe corresponder a la extensión (evita un .exe renombrado).
    firmas = {
        ".pdf": (b"%PDF",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".docx": (b"PK\x03\x04",),
    }
    if not contenido.startswith(firmas[extension]):
        raise ReglaPqrsError(
            f"El contenido de «{nombre_seguro}» no corresponde a un archivo {extension[1:].upper()} válido.", 415
        )
    return nombre_seguro, extension, EXTENSIONES_ADJUNTO[extension]


# ---------------------------------------------------------------------------
# Días hábiles (Colombia): lunes a viernes sin festivos nacionales.
# ---------------------------------------------------------------------------

def _pascua(anio: int) -> date:
    """Domingo de Pascua (algoritmo anónimo gregoriano)."""
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(anio, mes, dia)


def _siguiente_lunes(dia: date) -> date:
    return dia + timedelta(days=(7 - dia.weekday()) % 7)


@lru_cache(maxsize=64)
def festivos_colombia(anio: int) -> frozenset[date]:
    """Festivos nacionales (Ley 51 de 1983, «ley Emiliani»)."""
    fijos = [date(anio, 1, 1), date(anio, 5, 1), date(anio, 7, 20),
             date(anio, 8, 7), date(anio, 12, 8), date(anio, 12, 25)]
    trasladables = [date(anio, 1, 6), date(anio, 3, 19), date(anio, 6, 29),
                    date(anio, 8, 15), date(anio, 10, 12), date(anio, 11, 1),
                    date(anio, 11, 11)]
    pascua = _pascua(anio)
    religiosos = [pascua - timedelta(days=3), pascua - timedelta(days=2)]
    religiosos_trasladables = [pascua + timedelta(days=39), pascua + timedelta(days=60),
                               pascua + timedelta(days=68)]
    dias = set(fijos) | set(religiosos)
    dias |= {_siguiente_lunes(d) for d in trasladables + religiosos_trasladables}
    return frozenset(dias)


def es_dia_habil(dia: date) -> bool:
    return dia.weekday() < 5 and dia not in festivos_colombia(dia.year)


def sumar_dias_habiles(inicio: date, dias: int) -> date:
    """Fecha límite: `dias` hábiles después de `inicio` (no cuenta el día de
    radicación, como en el derecho de petición)."""
    actual = inicio
    restantes = max(int(dias), 0)
    while restantes > 0:
        actual += timedelta(days=1)
        if es_dia_habil(actual):
            restantes -= 1
    return actual


def dias_habiles_entre(inicio: date, fin: date) -> int:
    """Días hábiles transcurridos de `inicio` (excluido) a `fin` (incluido)."""
    if fin <= inicio:
        return 0
    total = 0
    actual = inicio
    while actual < fin:
        actual += timedelta(days=1)
        if es_dia_habil(actual):
            total += 1
    return total


def semaforo(pqrs: dict, hoy: date, dias_alerta: int = DIAS_ALERTA_POR_DEFECTO) -> str:
    """
    vencida · proxima (a `dias_alerta` hábiles o menos) · en_termino para las
    abiertas; atendida_a_tiempo / atendida_tarde para respondidas o cerradas.
    """
    limite = _a_fecha(pqrs.get("fecha_limite"))
    estado = pqrs.get("estado")
    if estado in (RESPONDIDA, CERRADA):
        atendida = _a_fecha(pqrs.get("fecha_respuesta")) or _a_fecha(pqrs.get("fecha_cierre"))
        if limite and atendida and atendida > limite:
            return "atendida_tarde"
        return "atendida_a_tiempo"
    if estado == INFO_SOLICITADA:
        # El plazo corre por cuenta del peticionario mientras no responda.
        return "en_espera"
    if not limite:
        return "en_termino"
    if hoy > limite:
        return "vencida"
    if dias_habiles_entre(hoy, limite) <= dias_alerta:
        return "proxima"
    return "en_termino"


def _a_fecha(valor) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None
