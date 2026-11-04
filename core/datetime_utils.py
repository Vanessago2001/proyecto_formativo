from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SYSTEM_TIMEZONE = ZoneInfo("America/Bogota")


def system_now() -> datetime:
    """
    Retorna la fecha actual en la zona horaria oficial del sistema.
    """
    return datetime.now(SYSTEM_TIMEZONE)


def system_now_utc_naive() -> datetime:
    """
    Retorna fecha UTC sin tzinfo para comparar con columnas antiguas.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def system_now_utc() -> datetime:
    """
    Retorna la fecha y hora actual en UTC **con zona horaria**.

    Debe usarse para escribir en columnas TIMESTAMPTZ: al enviar un valor
    naive, el motor lo interpreta en la zona horaria local (Bogota) y lo
    guarda desplazado (por ejemplo, +5 horas).
    """
    return datetime.now(timezone.utc)