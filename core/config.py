import os
from dotenv import load_dotenv

load_dotenv()


class Settings:

    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

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

    def __init__(self) -> None:

        if not self.DATABASE_URL:
            raise ValueError(
                "CRÍTICO: La variable DATABASE_URL no está configurada en el .env"
            )


settings = Settings()