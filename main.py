from contextlib import asynccontextmanager
import os
from fastapi import FastAPI
from sqlalchemy import text
from modules.roles.roles_router import router as role_router
from modules.users.user_router import router as users_router
from modules.auth.auth_router import router as auth_router
from core.database import AsyncSessionLocal
from core.logger import logger
from core.security import hash_password
from modules.tareas.tarea_router import router as tarea_router

async def ensure_login_security_schema(session) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS logs_acceso (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER,
            correo_intentado VARCHAR(255) NOT NULL,
            ip_origen VARCHAR(45) NOT NULL,
            exitoso BOOLEAN NOT NULL,
            motivo_fallo VARCHAR(100),
            fecha_hora TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """))

    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            nit VARCHAR(20) UNIQUE,
            correo VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            estado VARCHAR(20) NOT NULL DEFAULT 'Activo',
            intentos_fallidos INT DEFAULT 0,
            bloqueado_hasta TIMESTAMP WITH TIME ZONE DEFAULT NULL,
            creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """))

    await session.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS nit VARCHAR(20) UNIQUE;"))
    await session.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS correo VARCHAR(255) UNIQUE;"))
    await session.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);"))
    await session.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS estado VARCHAR(20) DEFAULT 'Activo';"))
    await session.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS intentos_fallidos INTEGER DEFAULT 0;"))
    await session.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS bloqueado_hasta TIMESTAMP WITH TIME ZONE;"))
    await session.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;"))

    await session.execute(text("""
        UPDATE usuarios
        SET estado = CASE
            WHEN estado IS NULL THEN 'Activo'
            ELSE estado
        END
        WHERE estado IS NULL;
    """))

    await session.execute(text("""
        UPDATE usuarios
        SET intentos_fallidos = COALESCE(intentos_fallidos, 0)
        WHERE intentos_fallidos IS NULL;
    """))

async def seed_initial_data() -> None:
    async with AsyncSessionLocal() as session:
        try:
            await ensure_login_security_schema(session)

            default_roles = [
                ("Administrador", "Acceso total al sistema"),
                ("Instructor", "Puede gestionar tareas y usuarios"),
                ("Aprendiz", "Usuario estándar"),
            ]

            for role_name, role_description in default_roles:
                existing_role = await session.execute(
                    text("SELECT id FROM roles WHERE name = :name;"),
                    {"name": role_name},
                )
                if existing_role.scalar_one_or_none() is None:
                    await session.execute(
                        text("INSERT INTO roles (name, description) VALUES (:name, :description);"),
                        {"name": role_name, "description": role_description},
                    )

            existing_admin = await session.execute(
                text("SELECT id FROM users WHERE username = :username;"),
                {"username": "admin"},
            )
            if existing_admin.scalar_one_or_none() is None:
                role_result = await session.execute(
                    text("SELECT id FROM roles WHERE name = :name;"),
                    {"name": "Administrador"},
                )
                admin_role_id = role_result.scalar_one_or_none()
                if admin_role_id is not None:
                    await session.execute(
                        text("""
                            INSERT INTO users (username, email, hashed_password, is_active, role_id)
                            VALUES (:username, :email, :hashed_password, TRUE, :role_id);
                        """),
                        {
                            "username": "admin",
                            "email": os.getenv("INITIAL_ADMIN_EMAIL", "admin@example.com"),
                            "hashed_password": hash_password(os.getenv("INITIAL_ADMIN_PASSWORD", "admin123")),
                            "role_id": admin_role_id,
                        },
                    )

            await session.commit()
            logger.info("Datos iniciales verificados correctamente.")
        except Exception as exc:
            await session.rollback()
            logger.exception("Error al crear datos iniciales: %s", exc)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("==========================================================")
    logger.info("  ¡API Modular Inicializada en Raíz con Éxito (Lifespan)!")
    logger.info("  Documentación interactiva: http://127.0.0.1:8000/docs")
    logger.info("==========================================================")
    await seed_initial_data()
    yield
    logger.info("Cerrando recursos de la API de forma segura.")

app = FastAPI(
    title="API FastAPI Modular sin SRC - SQL Puro",
    version="3.1.0",
    description="Estructura limpia basada en dominios directo en raíz sin Passlib",
    lifespan=lifespan
)

# Inyección directa de rutas modulares verificadas sin prefijos redundantes
app.include_router(auth_router)
app.include_router(role_router)
app.include_router(users_router)
app.include_router(tarea_router)