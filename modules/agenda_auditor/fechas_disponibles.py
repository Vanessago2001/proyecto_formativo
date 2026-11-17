"""
Disponibilidad del equipo de auditores: explicación del rechazo y sugerencias.

· `explicar_no_disponible` dice POR QUÉ un auditor no cubre una franja (sin
  disponibilidad declarada, vigencia vencida, día no declarado, horas fuera
  del horario o día bloqueado) a partir de sus registros de
  `disponibilidad_auditor`.
· `sugerir_fechas` busca las próximas franjas en que TODO el equipo está
  disponible. Primero filtra en memoria con las mismas reglas que la consulta
  SQL de `_tiene_disponibilidad_fecha`, y luego CADA sugerencia se confirma
  con las funciones que usa `crear_programacion` (`_tiene_disponibilidad_fecha`
  y `_buscar_cruce`, más el estado del auditor). Así una sugerencia nunca es
  rechazada al programar: si el filtro en memoria y la validación real
  discreparan, la franja simplemente no se ofrece.

Solo hace SELECT.
"""

from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import text

# Mismas listas que las consultas SQL de agenda_service.
TIPOS_DISPONIBLE = {
    "disponible", "disponibilidad", "horario disponible", "availability",
    "semanal", "horario semanal", "disponibilidad extra", "disponibilidad_extra",
}
TIPOS_EXTRA = {"disponibilidad extra", "disponibilidad_extra"}
TIPOS_BLOQUEO = {"no disponible", "no_disponible", "indisponible", "bloqueo", "bloqueo fecha"}
ESTADOS_ACTIVOS = {"ACTIVO", "ACTIVA"}
ESTADOS_AUDITOR_OK = {"ACTIVO", "APROBADO", "APROBADA"}

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

MAX_DIAS_BUSQUEDA = 180
DIAS_BUSQUEDA_DEFECTO = 90
DURACION_DEFECTO_MIN = 240
HORA_JORNADA = time(8, 0)
ULTIMA_HORA = time(23, 59)


# ------------------------------------------------------------ reglas puras


def _tipo(registro: dict) -> str:
    return str(registro.get("tipo_registro") or "").strip().lower()


def _activo(registro: dict) -> bool:
    return str(registro.get("estado") or "").strip().upper() in ESTADOS_ACTIVOS


def _como_fecha(valor) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def _como_hora(valor) -> time | None:
    if valor is None or isinstance(valor, time):
        return valor
    return time.fromisoformat(str(valor)[:8])


def _vigente_en(registro: dict, fecha: date) -> bool:
    inicio = _como_fecha(registro.get("fecha_inicio"))
    fin = _como_fecha(registro.get("fecha_fin"))
    return inicio is not None and inicio <= fecha and (fin is None or fin >= fecha)


def _dia_coincide(registro: dict, fecha: date) -> bool:
    """dia_semana ISO (lunes=1 … domingo=7; 0 también es domingo)."""
    dia = registro.get("dia_semana")
    if dia is None or _tipo(registro) in TIPOS_EXTRA:
        return True
    numero = fecha.weekday() + 1
    return int(dia) == numero or (numero == 7 and int(dia) == 0)


def es_disponibilidad(registro: dict) -> bool:
    return _activo(registro) and _tipo(registro) in TIPOS_DISPONIBLE


def es_bloqueo(registro: dict) -> bool:
    return _activo(registro) and _tipo(registro) in TIPOS_BLOQUEO


def _cubre_horas(registro: dict, inicio: time, fin: time) -> bool:
    h_ini, h_fin = _como_hora(registro.get("hora_inicio")), _como_hora(registro.get("hora_fin"))
    return h_ini is None or h_fin is None or (h_ini <= inicio and h_fin >= fin)


def _bloquea(registro: dict, fecha: date, inicio: time, fin: time) -> bool:
    if not (es_bloqueo(registro) and _vigente_en(registro, fecha)):
        return False
    h_ini, h_fin = _como_hora(registro.get("hora_inicio")), _como_hora(registro.get("hora_fin"))
    return h_ini is None or h_fin is None or (h_ini < fin and h_fin > inicio)


def cubre_franja(registros: list[dict], fecha: date, inicio: time, fin: time) -> bool:
    """Réplica en memoria de `_tiene_disponibilidad_fecha` (misma regla SQL)."""
    declarado = any(
        es_disponibilidad(r) and _vigente_en(r, fecha) and _dia_coincide(r, fecha)
        and _cubre_horas(r, inicio, fin)
        for r in registros
    )
    return declarado and not any(_bloquea(r, fecha, inicio, fin) for r in registros)


def _fmt(fecha: date) -> str:
    return fecha.strftime("%d/%m/%Y")


def _hhmm(valor) -> str:
    hora = _como_hora(valor)
    return hora.strftime("%H:%M") if hora else ""


def fin_de_vigencia(registros: list[dict]) -> date | None:
    """Último día cubierto por la disponibilidad declarada (None = sin fin)."""
    disponibles = [r for r in registros if es_disponibilidad(r)]
    if not disponibles or any(r.get("fecha_fin") is None for r in disponibles):
        return None
    return max(_como_fecha(r["fecha_fin"]) for r in disponibles)


def explicar_no_disponible(
    registros: list[dict], fecha: date, inicio: time, fin: time, nombre: str = "El auditor"
) -> str | None:
    """Motivo concreto por el que `nombre` no cubre la franja (None si la cubre)."""
    disponibles = [r for r in registros if es_disponibilidad(r)]
    franja = f"{inicio:%H:%M} a {fin:%H:%M}"
    dia = DIAS[fecha.weekday()]
    if not disponibles:
        return (
            f"{nombre} no ha declarado disponibilidad (ni horario semanal ni disponibilidad "
            "extraordinaria). Debe registrarla en «Mi disponibilidad»."
        )
    vigentes = [r for r in disponibles if _vigente_en(r, fecha)]
    if not vigentes:
        posteriores = sorted(
            _como_fecha(r["fecha_inicio"]) for r in disponibles
            if _como_fecha(r.get("fecha_inicio")) and _como_fecha(r["fecha_inicio"]) > fecha
        )
        if posteriores:
            return (
                f"{nombre} no tiene disponibilidad vigente el {_fmt(fecha)}: su próxima "
                f"disponibilidad declarada comienza el {_fmt(posteriores[0])}."
            )
        vence = fin_de_vigencia(disponibles)
        if vence:
            return (
                f"La disponibilidad declarada de {nombre} vence el {_fmt(vence)}; no cubre el "
                f"{_fmt(fecha)}. El auditor debe ampliar su vigencia en «Mi disponibilidad»."
            )
        return f"{nombre} no tiene disponibilidad vigente el {_fmt(fecha)}."
    del_dia = [r for r in vigentes if _dia_coincide(r, fecha)]
    if not del_dia:
        dias = sorted({int(r["dia_semana"]) % 7 or 7 for r in vigentes if r.get("dia_semana") is not None})
        lista = ", ".join(DIAS[d - 1] for d in dias)
        return (
            f"{nombre} no declaró disponibilidad los {dia} para el {_fmt(fecha)}"
            + (f" (días declarados vigentes: {lista})." if lista else ".")
        )
    if not any(_cubre_horas(r, inicio, fin) for r in del_dia):
        horarios = sorted({f"{_hhmm(r.get('hora_inicio'))}–{_hhmm(r.get('hora_fin'))}" for r in del_dia})
        return (
            f"El horario declarado de {nombre} el {dia} {_fmt(fecha)} es {', '.join(horarios)}; "
            f"la franja de {franja} queda fuera."
        )
    bloqueos = [r for r in registros if _bloquea(r, fecha, inicio, fin)]
    if bloqueos:
        motivo = str(bloqueos[0].get("motivo") or "").strip()
        return f"{nombre} registró el {_fmt(fecha)} como no disponible" + (f" ({motivo})." if motivo else ".")
    return None


# ------------------------------------------------------------ consultas


async def registros_disponibilidad(db, ids: list[str]) -> dict[str, list[dict]]:
    """Registros activos (disponibilidad y bloqueos) de los auditores indicados."""
    if not ids:
        return {}
    result = await db.execute(text("""
        SELECT da.id_usuario, da.tipo_registro, da.dia_semana, da.fecha_inicio, da.fecha_fin,
               da.hora_inicio, da.hora_fin, da.estado, da.motivo
        FROM disponibilidad_auditor da
        WHERE da.id_usuario = ANY(CAST(:ids AS UUID[]))
          AND UPPER(TRIM(COALESCE(da.estado, ''))) IN ('ACTIVO', 'ACTIVA')
    """), {"ids": ids})
    por_auditor: dict[str, list[dict]] = {i: [] for i in ids}
    for fila in result.mappings().all():
        por_auditor.setdefault(str(fila["id_usuario"]), []).append(dict(fila))
    return por_auditor


async def motivo_no_disponible(db, id_usuario, fecha: date, inicio: time, fin: time, nombre: str) -> str | None:
    """Motivo legible; None si no se pudo determinar (nunca rompe la validación)."""
    try:
        registros = (await registros_disponibilidad(db, [str(id_usuario)])).get(str(id_usuario), [])
        return explicar_no_disponible(registros, fecha, inicio, fin, nombre)
    except Exception:  # noqa: BLE001 - el motivo es informativo
        return None


# ------------------------------------------------------------ sugerencias


def _inicios_candidatos(
    fecha: date, duracion: timedelta, preferida: time | None,
    registros_equipo: list[list[dict]], ocupaciones: list[tuple[datetime, datetime]],
) -> list[time]:
    """Horas de inicio a probar: la preferida, el inicio de cada horario declarado
    y el final de cada ocupación/bloqueo (la franja más temprana posible siempre
    empieza en uno de esos puntos)."""
    candidatas = {HORA_JORNADA}
    for registros in registros_equipo:
        for r in registros:
            if _vigente_en(r, fecha):
                for clave in ("hora_inicio", "hora_fin") if es_bloqueo(r) else ("hora_inicio",):
                    hora = _como_hora(r.get(clave))
                    if hora:
                        candidatas.add(hora)
    for ini, fin in ocupaciones:
        if fin.date() == fecha:
            candidatas.add(fin.time().replace(second=0, microsecond=0))
    limite = datetime.combine(fecha, ULTIMA_HORA)
    validas = sorted(h for h in candidatas if datetime.combine(fecha, h) + duracion <= limite)
    if preferida and datetime.combine(fecha, preferida) + duracion <= limite:
        validas = [preferida] + [h for h in validas if h != preferida]
    return validas


def _libre(ocupaciones: list[tuple[datetime, datetime]], inicio: datetime, fin: datetime) -> bool:
    return not any(o_ini < fin and o_fin > inicio for o_ini, o_fin in ocupaciones)


def _franja_del_dia(
    fecha: date, duracion: timedelta, preferida: time | None, equipo: list[str],
    registros: dict[str, list[dict]], ocupacion: dict[str, list[tuple[datetime, datetime]]],
    descartadas: set[tuple[date, time]] | None = None,
) -> tuple[datetime, datetime] | None:
    todas = [o for i in equipo for o in ocupacion.get(i, [])]
    for hora in _inicios_candidatos(fecha, duracion, preferida, [registros.get(i, []) for i in equipo], todas):
        if descartadas and (fecha, hora) in descartadas:
            continue
        inicio = datetime.combine(fecha, hora)
        fin = inicio + duracion
        if all(
            cubre_franja(registros.get(i, []), fecha, inicio.time(), fin.time())
            and _libre(ocupacion.get(i, []), inicio, fin)
            for i in equipo
        ):
            return inicio, fin
    return None


async def sugerir_fechas(
    servicio,
    auditores: list,
    hora_inicio: time | None = None,
    hora_fin: time | None = None,
    duracion_minutos: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = 10,
    excluir_programacion=None,
    hoy: date | None = None,
) -> dict:
    """Próximas franjas en que todo el equipo está disponible."""
    db = servicio.db
    ids = list(dict.fromkeys(str(a) for a in auditores if a))
    if not ids:
        raise HTTPException(status_code=422, detail="Seleccione al menos un auditor del equipo.")
    hoy = hoy or date.today()
    if hora_inicio and hora_fin:
        if hora_fin <= hora_inicio:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="La hora final debe ser posterior a la hora inicial.",
            )
        duracion = datetime.combine(hoy, hora_fin) - datetime.combine(hoy, hora_inicio)
    else:
        duracion = timedelta(minutes=duracion_minutos or DURACION_DEFECTO_MIN)
        if duracion <= timedelta(0) or duracion > timedelta(hours=16):
            raise HTTPException(status_code=422, detail="La duración debe estar entre 1 minuto y 16 horas.")
    desde = max(desde or (hoy + timedelta(days=1)), hoy)
    hasta = hasta or (desde + timedelta(days=DIAS_BUSQUEDA_DEFECTO))
    if hasta < desde:
        raise HTTPException(status_code=422, detail="El final del rango no puede ser anterior al inicio.")
    hasta = min(hasta, desde + timedelta(days=MAX_DIAS_BUSQUEDA))
    limite = max(1, min(int(limite or 10), 30))

    usuarios_res = await db.execute(text("""
        SELECT id_usuario, nombre, estado, estado_auditor
        FROM usuario
        WHERE id_usuario = ANY(CAST(:ids AS UUID[]))
    """), {"ids": ids})
    usuarios = {str(u["id_usuario"]): dict(u) for u in usuarios_res.mappings().all()}
    registros = await registros_disponibilidad(db, ids)
    ocupacion_res = await db.execute(text("""
        SELECT d.id_usuario, p.fecha_inicio, p.fecha_fin
        FROM detalle_programacion_auditor d
        INNER JOIN programacion_visita p ON p.id_programacion = d.id_programacion
        WHERE d.id_usuario = ANY(CAST(:ids AS UUID[]))
          AND UPPER(TRIM(COALESCE(p.estado, ''))) NOT IN
              ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')
          AND p.fecha_inicio < :hasta
          AND p.fecha_fin > :desde
          AND (CAST(:excluir AS UUID) IS NULL OR p.id_programacion <> CAST(:excluir AS UUID))
    """), {
        "ids": ids,
        "desde": datetime.combine(desde, time.min),
        "hasta": datetime.combine(hasta + timedelta(days=1), time.min),
        "excluir": str(excluir_programacion) if excluir_programacion else None,
    })
    ocupacion: dict[str, list[tuple[datetime, datetime]]] = {i: [] for i in ids}
    for fila in ocupacion_res.mappings().all():
        ocupacion.setdefault(str(fila["id_usuario"]), []).append((fila["fecha_inicio"], fila["fecha_fin"]))

    def nombre_de(i: str) -> str:
        return (usuarios.get(i) or {}).get("nombre") or "El auditor"

    # Estado del auditor: misma regla que crear_programacion.
    inactivos = {
        i: f"{nombre_de(i)} no está activo/aprobado como auditor, por eso no puede programarse."
        for i in ids
        if i not in usuarios
        or str(usuarios[i].get("estado") or "").strip().upper() != "ACTIVO"
        or str(usuarios[i].get("estado_auditor") or "").strip().upper() not in ESTADOS_AUDITOR_OK
    }

    # La comprobación de columnas de _tiene_disponibilidad_fecha no cambia
    # durante la búsqueda: se memoriza solo en esta instancia del servicio.
    original_columna = getattr(servicio, "_tabla_tiene_columna", None)
    if original_columna is not None:
        columnas: dict = {}

        async def columna_memo(tabla, columna):
            if (tabla, columna) not in columnas:
                columnas[(tabla, columna)] = await original_columna(tabla, columna)
            return columnas[(tabla, columna)]

        servicio._tabla_tiene_columna = columna_memo

    opciones: list[dict] = []
    descartadas: set[tuple[date, time]] = set()
    if not inactivos:
        fecha = desde
        while fecha <= hasta and len(opciones) < limite:
            franja = _franja_del_dia(fecha, duracion, hora_inicio, ids, registros, ocupacion, descartadas)
            if franja is None:
                fecha += timedelta(days=1)
                continue
            inicio, fin = franja
            # Confirmación con las MISMAS funciones que crear_programacion.
            confirmada = True
            for i in ids:
                if not await servicio._tiene_disponibilidad_fecha(i, fecha, inicio.time(), fin.time()):
                    confirmada = False
                    break
                if await servicio._buscar_cruce(i, inicio, fin, excluir_programacion):
                    confirmada = False
                    break
            if not confirmada:
                descartadas.add((fecha, inicio.time()))
                continue  # prueba la siguiente hora del mismo día
            opciones.append({
                "fecha": fecha.isoformat(),
                "dia_semana": DIAS[fecha.weekday()],
                "hora_inicio": inicio.strftime("%H:%M"),
                "hora_fin": fin.strftime("%H:%M"),
                "auditores": [{"id_usuario": i, "nombre": nombre_de(i)} for i in ids],
            })
            fecha += timedelta(days=1)

    # Diagnóstico por auditor (siempre: avisa de vigencias que vencen pronto).
    detalle = []
    for i in ids:
        info = {"id_usuario": i, "nombre": nombre_de(i), "dias_disponibles": 0, "proxima_fecha": None, "motivo": None}
        if i in inactivos:
            info["motivo"] = inactivos[i]
            detalle.append(info)
            continue
        propios = registros.get(i, [])
        fecha = desde
        while fecha <= hasta:
            if _franja_del_dia(fecha, duracion, hora_inicio, [i], registros, ocupacion):
                info["dias_disponibles"] += 1
                info["proxima_fecha"] = info["proxima_fecha"] or fecha.isoformat()
            fecha += timedelta(days=1)
        vence = fin_de_vigencia(propios)
        if not any(es_disponibilidad(r) for r in propios):
            info["motivo"] = explicar_no_disponible(propios, desde, time(8), time(9), nombre_de(i))
        elif vence and vence < hasta:
            info["motivo"] = (
                f"La disponibilidad declarada de {nombre_de(i)} vence el {_fmt(vence)}"
                + ("." if vence >= desde else "; no cubre ninguna fecha del rango buscado.")
            )
        elif info["dias_disponibles"] == 0:
            info["motivo"] = (
                f"{nombre_de(i)} no tiene ninguna franja de {_duracion_texto(duracion)} libre "
                "en el rango (horario declarado más corto, días bloqueados u ocupados)."
            )
        detalle.append(info)

    if opciones:
        mensaje = f"{len(opciones)} opción(es) en que todo el equipo está disponible."
    elif inactivos:
        mensaje = "Hay auditores del equipo que no pueden programarse; revise el detalle por auditor."
    elif all(d["dias_disponibles"] for d in detalle):
        mensaje = (
            "Cada auditor tiene días disponibles, pero no coinciden entre sí en el rango. "
            "Pruebe con menos auditores, una duración menor o un rango más amplio."
        )
    else:
        mensaje = "No hay fechas en que todo el equipo esté disponible en el rango; revise el detalle por auditor."
    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "duracion_minutos": int(duracion.total_seconds() // 60),
        "opciones": opciones,
        "auditores": detalle,
        "mensaje": mensaje,
    }


def _duracion_texto(duracion: timedelta) -> str:
    minutos = int(duracion.total_seconds() // 60)
    horas, resto = divmod(minutos, 60)
    if horas and resto:
        return f"{horas} h {resto} min"
    return f"{horas} h" if horas else f"{resto} min"
