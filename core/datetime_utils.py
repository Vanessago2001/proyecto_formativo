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