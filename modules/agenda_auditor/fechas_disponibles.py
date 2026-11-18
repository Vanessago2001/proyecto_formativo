"""
Regla única de disponibilidad para programar auditorías (18/11/2026).

Un auditor activo y aprobado está DISPONIBLE en una franja salvo que:
  (a) tenga ese día (o parte de la franja) BLOQUEADO en `disponibilidad_auditor`
      (registros activos de tipo 'Bloqueo Fecha' y equivalentes), o
  (b) ya tenga OTRA visita no cancelada ni finalizada que se cruce
      (`programacion_visita` + `detalle_programacion_auditor`).

La disponibilidad semanal o extraordinaria declarada YA NO restringe: no
importa si el auditor no declaró nada, si su vigencia venció o si la franja
queda fuera de su horario. Se sigue mostrando como información.

· `bloqueo_en_franja` es la regla del punto (a) (pura, sin base de datos);
  la usa `AgendaAuditorService.verificar_franja_auditor`, que añade el punto
  (b) con `_buscar_cruce` y es la función que valida programar, reprogramar,
  editar, agregar auditor, comprobar disponibilidad y cada sugerencia.
· `sugerir_fechas` busca las próximas franjas en que TODO el equipo está libre
  de bloqueos y choques; cada opción se confirma con `verificar_franja_auditor`.

Solo hace SELECT.
"""

from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import text

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


def es_bloqueo(registro: dict) -> bool:
    return _activo(registro) and _tipo(registro) in TIPOS_BLOQUEO


def _bloquea(registro: dict, fecha: date, inicio: time, fin: time) -> bool:
    if not (es_bloqueo(registro) and _vigente_en(registro, fecha)):
        return False
    h_ini, h_fin = _como_hora(registro.get("hora_inicio")), _como_hora(registro.get("hora_fin"))
    return h_ini is None or h_fin is None or (h_ini < fin and h_fin > inicio)


def tramos_por_dia(inicio: datetime, fin: datetime) -> list[tuple[date, time, time]]:
    """Parte la franja en un tramo por día (una visita puede durar varios días)."""
    tramos = []
    dia = inicio.date()
    while dia <= fin.date():
        h_ini = inicio.time() if dia == inicio.date() else time.min
        h_fin = fin.time() if dia == fin.date() else time.max
        if dia == fin.date() and dia != inicio.date() and h_fin == time.min:
            break  # termina a las 00:00: no ocupa ese día
        tramos.append((dia, h_ini, h_fin))
        dia += timedelta(days=1)
    return tramos


def bloqueo_en_franja(registros: list[dict], inicio: datetime, fin: datetime) -> tuple[date, dict] | None:
    """Primer bloqueo activo que toca la franja: (fecha, registro); None si no hay.

    Solo cuentan los bloqueos: la disponibilidad declarada no restringe."""
    for dia, h_ini, h_fin in tramos_por_dia(inicio, fin):
        for registro in registros:
            if _bloquea(registro, dia, h_ini, h_fin):
                return dia, registro
    return None


def cubre_franja(registros: list[dict], fecha: date, inicio: time, fin: time) -> bool:
    """La franja del día está libre de bloqueos (las visitas se miran aparte)."""
    return bloqueo_en_franja(registros, datetime.combine(fecha, inicio), datetime.combine(fecha, fin)) is None


def _fmt(fecha: date) -> str:
    return fecha.strftime("%d/%m/%Y")


def mensaje_bloqueo(nombre: str, fecha: date, registro: dict) -> str:
    """'X tiene bloqueado el dd/mm/aaaa (motivo).'"""
    h_ini, h_fin = _como_hora(registro.get("hora_inicio")), _como_hora(registro.get("hora_fin"))
    horas = f" de {h_ini:%H:%M} a {h_fin:%H:%M}" if h_ini and h_fin else ""
    motivo = str(registro.get("motivo") or "").strip()
    return f"{nombre} tiene bloqueado el {_fmt(fecha)}{horas}" + (f" ({motivo})." if motivo else ".")


def mensaje_cruce(nombre: str, cruce: dict) -> str:
    """'X ya tiene la visita SOL-… el dd/mm/aaaa de hh:mm a hh:mm.'"""
    radicado = str(cruce.get("numero_radicado") or "").strip()
    visita = f"la visita {radicado}" if radicado else "otra visita"
    inicio, fin = cruce.get("fecha_inicio"), cruce.get("fecha_fin")
    cuando = ""
    if isinstance(inicio, datetime) and isinstance(fin, datetime):
        if inicio.date() == fin.date():
            cuando = f" el {_fmt(inicio.date())} de {inicio:%H:%M} a {fin:%H:%M}"
        else:
            cuando = f" del {inicio:%d/%m/%Y %H:%M} al {fin:%d/%m/%Y %H:%M}"
    return f"{nombre} ya tiene {visita}{cuando}."


def explicar_no_disponible(
    registros: list[dict], fecha: date, inicio: time, fin: time, nombre: str = "El auditor"
) -> str | None:
    """Motivo por bloqueo de la franja del día (None si no hay bloqueo)."""
    hallado = bloqueo_en_franja(registros, datetime.combine(fecha, inicio), datetime.combine(fecha, fin))
    return mensaje_bloqueo(nombre, *hallado) if hallado else None


# ------------------------------------------------------------ consultas


async def registros_bloqueo(
    db, ids: list[str], desde: date | None = None, hasta: date | None = None
) -> dict[str, list[dict]]:
    """Bloqueos activos de los auditores indicados (opcionalmente en un rango)."""
    if not ids:
        return {}
    result = await db.execute(text("""
        SELECT da.id_usuario, da.tipo_registro, da.dia_semana, da.fecha_inicio, da.fecha_fin,
               da.hora_inicio, da.hora_fin, da.estado, da.motivo
        FROM disponibilidad_auditor da
        WHERE da.id_usuario = ANY(CAST(:ids AS UUID[]))
          AND UPPER(TRIM(COALESCE(da.estado, ''))) IN ('ACTIVO', 'ACTIVA')
          AND LOWER(TRIM(COALESCE(da.tipo_registro, ''))) IN
              ('no disponible', 'no_disponible', 'indisponible', 'bloqueo', 'bloqueo fecha')
          AND (CAST(:hasta AS DATE) IS NULL OR CAST(da.fecha_inicio AS DATE) <= CAST(:hasta AS DATE))
          AND (CAST(:desde AS DATE) IS NULL OR da.fecha_fin IS NULL
               OR CAST(da.fecha_fin AS DATE) >= CAST(:desde AS DATE))
    """), {"ids": ids, "desde": desde, "hasta": hasta})
    por_auditor: dict[str, list[dict]] = {i: [] for i in ids}
    for fila in result.mappings().all():
        por_auditor.setdefault(str(fila["id_usuario"]), []).append(dict(fila))
    return por_auditor


# ------------------------------------------------------------ sugerencias


def _inicios_candidatos(
    fecha: date, duracion: timedelta, preferida: time | None,
    registros_equipo: list[list[dict]], ocupaciones: list[tuple[datetime, datetime]],
    minima: time | None = None,
) -> list[time]:
    """Horas de inicio a probar: la preferida, el inicio de jornada y el final
    de cada bloqueo parcial u ocupación (la franja más temprana posible
    siempre empieza en uno de esos puntos)."""
    # Hora más temprana a la que puede empezar la visita (la elige quien
    # programa; por defecto el inicio de jornada). Toda la semana cuenta.
    minima = minima or HORA_JORNADA
    candidatas = {minima}
    for registros in registros_equipo:
        for r in registros:
            if es_bloqueo(r) and _vigente_en(r, fecha):
                hora = _como_hora(r.get("hora_fin"))
                if hora:
                    candidatas.add(hora)
    for ini, fin in ocupaciones:
        if fin.date() == fecha:
            candidatas.add(fin.time().replace(second=0, microsecond=0))
    limite = datetime.combine(fecha, ULTIMA_HORA)
    validas = sorted(
        h for h in candidatas
        if h >= minima and datetime.combine(fecha, h) + duracion <= limite
    )
    if preferida and preferida >= minima and datetime.combine(fecha, preferida) + duracion <= limite:
        validas = [preferida] + [h for h in validas if h != preferida]
    return validas


def _libre(ocupaciones: list[tuple[datetime, datetime]], inicio: datetime, fin: datetime) -> bool:
    return not any(o_ini < fin and o_fin > inicio for o_ini, o_fin in ocupaciones)


def _franja_del_dia(
    fecha: date, duracion: timedelta, preferida: time | None, equipo: list[str],
    registros: dict[str, list[dict]], ocupacion: dict[str, list[tuple[datetime, datetime]]],
    descartadas: set[tuple[date, time]] | None = None,
    minima: time | None = None,
) -> tuple[datetime, datetime] | None:
    todas = [o for i in equipo for o in ocupacion.get(i, [])]
    for hora in _inicios_candidatos(fecha, duracion, preferida, [registros.get(i, []) for i in equipo], todas, minima):
        if descartadas and (fecha, hora) in descartadas:
            continue
        inicio = datetime.combine(fecha, hora)
        fin = inicio + duracion
        if all(
            bloqueo_en_franja(registros.get(i, []), inicio, fin) is None
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
    desde_hora: time | None = None,
) -> dict:
    """Próximas franjas en que todo el equipo no tiene bloqueos ni choques.

    `desde_hora`: hora más temprana de inicio de la visita (por defecto 08:00).
    Se buscan todos los días de la semana, incluidos sábados y domingos.
    """
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
    registros = await registros_bloqueo(db, ids, desde, hasta)
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

    opciones: list[dict] = []
    descartadas: set[tuple[date, time]] = set()
    if not inactivos:
        fecha = desde
        while fecha <= hasta and len(opciones) < limite:
            franja = _franja_del_dia(fecha, duracion, hora_inicio, ids, registros, ocupacion, descartadas, minima=desde_hora)
            if franja is None:
                fecha += timedelta(days=1)
                continue
            inicio, fin = franja
            # Confirmación con la MISMA función que valida programar.
            confirmada = True
            for i in ids:
                if await servicio.verificar_franja_auditor(i, inicio, fin, excluir_programacion, nombre_de(i)):
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

    # Diagnóstico por auditor: solo causas reales (bloqueos y visitas).
    detalle = []
    for i in ids:
        info = {"id_usuario": i, "nombre": nombre_de(i), "dias_disponibles": 0, "proxima_fecha": None, "motivo": None}
        if i in inactivos:
            info["motivo"] = inactivos[i]
            detalle.append(info)
            continue
        fecha = desde
        while fecha <= hasta:
            if _franja_del_dia(fecha, duracion, hora_inicio, [i], registros, ocupacion, minima=desde_hora):
                info["dias_disponibles"] += 1
                info["proxima_fecha"] = info["proxima_fecha"] or fecha.isoformat()
            fecha += timedelta(days=1)
        if info["dias_disponibles"] == 0:
            info["motivo"] = (
                f"{nombre_de(i)} no tiene ninguna franja de {_duracion_texto(duracion)} libre "
                "en el rango: todos los días están bloqueados u ocupados con visitas."
            )
        detalle.append(info)

    if opciones:
        mensaje = f"{len(opciones)} opción(es) en que todo el equipo está disponible."
    elif inactivos:
        mensaje = "Hay auditores del equipo que no pueden programarse; revise el detalle por auditor."
    elif all(d["dias_disponibles"] for d in detalle):
        mensaje = (
            "Cada auditor tiene días libres, pero no coinciden entre sí en el rango (bloqueos o visitas). "
            "Pruebe con menos auditores, una duración menor o un rango más amplio."
        )
    else:
        mensaje = "No hay fechas en que todo el equipo esté libre en el rango; revise el detalle por auditor."
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
