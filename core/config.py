import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "fallback_secret_key_por_defecto")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

    def __init__(self) -> None:
        if not self.DATABASE_URL:
            raise ValueError("CRÍTICO: La variable DATABASE_URL no está configurada en el .env")

settings = Settings()
