from contextlib import asynccontextmanager
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from modules.roles.roles_router import router as role_router
from modules.users.user_router import router as users_router
from modules.auth.auth_router import router as auth_router
# importamos password_reset_router para que sus rutas estén disponibles en la aplicación
from modules.password_reset.password_reset_router import (
    router as password_reset_router,
)
from core.database import AsyncSessionLocal
from core.logger import logger
from core.security import hash_password
from modules.tareas.tarea_router import router as tarea_router



async def ensure_login_security_schema(session) -> None:
    # Tabla de logs de acceso (auxiliar, no está en el dump original)
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS logs_acceso (
            id SERIAL PRIMARY KEY,
            usuario_id UUID,
            correo_intentado VARCHAR(255) NOT NULL,
            ip_origen VARCHAR(45) NOT NULL,
            exitoso BOOLEAN NOT NULL,
            motivo_fallo VARCHAR(100),
            fecha_hora TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """))

async def seed_initial_data() -> None:
    async with AsyncSessionLocal() as session:
        try:
            await ensure_login_security_schema(session)

            # Roles por defecto según la tabla rol (id_rol PK, nombre, descripcion)
            default_rol = [
                ("Administrador", "Acceso total al sistema"),
                ("Instructor", "Puede gestionar tareas y usuarios"),
                ("Aprendiz", "Usuario estándar"),
            ]

            for role_name, role_description in default_rol:
                existing_role = await session.execute(
                    text("SELECT id_rol FROM rol WHERE nombre = :nombre;"),
                    {"nombre": role_name},
                )
                if existing_role.scalar_one_or_none() is None:
                    await session.execute(
                        text("INSERT INTO rol (nombre, descripcion) VALUES (:nombre, :descripcion);"),
                        {"nombre": role_name, "descripcion": role_description},
                    )

            # Verificar si existe el usuario admin en la tabla usuario (id UUID, nombre, correo, contrasena, estado BOOLEAN, rol_id)
            existing_admin = await session.execute(
                text("SELECT id FROM usuario WHERE nombre = :nombre;"),
                {"nombre": "admin"},
            )
            if existing_admin.scalar_one_or_none() is None:
                role_result = await session.execute(
                    text("SELECT id_rol FROM rol WHERE nombre = :nombre;"),
                    {"nombre": "Administrador"},
                )
                admin_role_id = role_result.scalar_one_or_none()
                if admin_role_id is not None:
                    await session.execute(
                        text("""
                            INSERT INTO usuario (id, nombre, correo, contrasena, estado, intentos_fallidos, rol_id, tipo_doc, num_doc)
                            VALUES (gen_random_uuid(), :nombre, :correo, :contrasena, 'Activo', 0, :rol_id, :tipo_doc, :num_doc);
                        """),
                        {
                            "nombre": "admin",
                            "correo": os.getenv("INITIAL_ADMIN_EMAIL", "admin@example.com"),
                            "contrasena": hash_password(os.getenv("INITIAL_ADMIN_PASSWORD", "admin123")),
                            "rol_id": admin_role_id,
                            "tipo_doc": "Cédula de Ciudadanía",
                            "num_doc": "0000000000",
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

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

app = FastAPI(
    title="API FastAPI Modular sin SRC - SQL Puro",
    version="3.1.0",
    description="Estructura limpia basada en dominios directo en raíz sin Passlib",
    lifespan=lifespan
)

# Montaje de archivos estáticos (CSS, JS, imágenes)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Inyección directa de rutas modulares verificadas sin prefijos redundantes
app.include_router(auth_router)
app.include_router(role_router)
app.include_router(users_router)
app.include_router(tarea_router)
app.include_router(password_reset_router)


# ============================================================
# RUTAS DE INTERFAZ DE USUARIO
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    """Sirve la página principal de consulta de documentos."""
    return FileResponse("static/index.html")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Sirve la página de inicio de sesión desde archivos estáticos."""
    return FileResponse("static/login.html")


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Sirve la página de registro de usuarios."""
    return FileResponse("static/register.html")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Página de inicio después de iniciar sesión (placeholder)."""
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <title>CertiSENA - Dashboard</title>
      <link rel="stylesheet" href="/static/styles.css" />
      <style>
        .dashboard-header {
          background-color: #3BAA01;
          color: #ffffff;
          padding: 20px;
          text-align: center;
        }
        .dashboard-content {
          background-color: #ffffff;
          padding: 40px;
          border-radius: 10px;
          box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
          max-width: 800px;
          margin: 30px auto;
        }
        .dashboard-content h2 { color: #3BAA01; }
        .logout-btn {
          background-color: #3BAA01;
          color: #ffffff;
          border: none;
          padding: 10px 20px;
          border-radius: 6px;
          cursor: pointer;
          font-weight: 600;
        }
        .logout-btn:hover { background-color: #2e8a01; }
      </style>
    </head>
    <body>
      <header class="dashboard-header">
        <h1>CertiSENA</h1>
        <p>Panel principal</p>
      </header>
      <main class="login-container">
        <div class="dashboard-content">
          <h2>¡Bienvenido!</h2>
          <p>Has iniciado sesión correctamente.</p>
          <button class="logout-btn" onclick="logout()">Cerrar sesión</button>
        </div>
      </main>
      <footer class="login-footer">
        <p>&copy; 2026 CertiSENA - SENA. Todos los derechos reservados.</p>
      </footer>
      <script>
        function logout() {
          localStorage.removeItem('access_token');
          localStorage.removeItem('token_type');
          window.location.href = '/';
        }
      </script>
    </body>
    </html>
    """
    return html_content
