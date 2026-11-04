import os
from dotenv import load_dotenv

load_dotenv()


class Settings:

    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # La base de Aiven es compartida y tiene pocos cupos de conexión.
    # El pool por defecto (5 + 10 extra) agotaba esos cupos, así que se
    # deja un margen pequeño y configurable.
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "1"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "1"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "600"))

    # Imprimir cada sentencia SQL sirve para depurar, pero llena la
    # consola y hace lento el arranque. Se activa con SQL_ECHO=1.
    SQL_ECHO: bool = os.getenv("SQL_ECHO", "0").strip().lower() in ("1", "true", "si", "sí")

    # Preparar la base al arrancar: auto (solo si hace falta),
    # siempre o nunca. Ver core/arranque.py.
    PREPARAR_BASE: str = os.getenv("PREPARAR_BASE", "auto")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    SECRET_KEY: str = os.getenv(
        "SECRET_KEY",
        "fallback_secret_key_por_defecto"
    )

    ALGORITHM: str = os.getenv(
        "ALGORITHM",
        "HS256"
    )

    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    )

    # URL base de la aplicación (usada para armar el enlace de restablecimiento
    # de contraseña que se envía por correo).
    APP_BASE_URL: str = os.getenv(
        "APP_BASE_URL",
        "http://127.0.0.1:8000"
    )

    # ==========================
    # CONFIGURACIÓN DE MAILTRAP
    # ==========================

    MAIL_USERNAME: str = os.getenv("MAIL_USERNAME", "")

    MAIL_PASSWORD: str = os.getenv("MAIL_PASSWORD", "")

    MAIL_FROM: str = os.getenv("MAIL_FROM", "")

    MAIL_PORT: int = int(
        os.getenv("MAIL_PORT", "587")
    )

    MAIL_SERVER: str = os.getenv("MAIL_SERVER", "")

    MAIL_STARTTLS: bool = (
        os.getenv("MAIL_STARTTLS", "True").lower() == "true"
    )

    MAIL_SSL_TLS: bool = (
        os.getenv("MAIL_SSL_TLS", "False").lower() == "true"
    )

    MAIL_FROM_NAME: str = os.getenv(
        "MAIL_FROM_NAME",
        "CertiSENA ISO"
    )

    CERTIFICADOS_FIRMA_DIR: str = os.getenv("CERTIFICADOS_FIRMA_DIR", "")
    CERTIFICADOS_FIRMA_PASSWORDS_JSON: str = os.getenv(
        "CERTIFICADOS_FIRMA_PASSWORDS_JSON", "{}"
    )
    CERTIFICADOS_FIRMA_TRUST_ROOTS_JSON: str = os.getenv(
        "CERTIFICADOS_FIRMA_TRUST_ROOTS_JSON", "[]"
    )
    CERTIFICADOS_STORAGE_DIR: str = os.getenv(
        "CERTIFICADOS_STORAGE_DIR", "storage/certificados_firmados"
    )

    def __init__(self) -> None:

        if not self.DATABASE_URL:
            raise ValueError(
                "CRÍTICO: La variable DATABASE_URL no está configurada en el .env"
            )


settings = Settings()