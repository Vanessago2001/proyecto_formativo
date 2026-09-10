from contextlib import asynccontextmanager
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from modules.mfa.mfa_router import router as mfa_router
from modules.roles.roles_router import router as role_router
from modules.users.user_router import router as users_router
from modules.auth.auth_router import router as auth_router
from core.database import AsyncSessionLocal
from core.logger import logger
from core.security import hash_password
from modules.security_policy.policy_router import router as security_router
from modules.empresas.empresas_router import router as empresas_router
from modules.comite.comite_router import router as comite_router
from modules.apelaciones.apelaciones_router import router as apelaciones_router

from modules.alejandra.router import router as alejandra_router

from core.redis_client import redis_pool

from modules.system.system_router import router as system_router
from modules.asignacion_auditores.asignacion_router import router as asignacion_auditores_router


# Modulo heredado de otro proyecto: su tabla `tareas` no existe en esta base
# de datos, asi que sus endpoints devolvian 500. El codigo se conserva en
# modules/tareas/ por si se quiere reaprovechar; para reactivarlo hay que
# crear la tabla y descomentar estas dos lineas (la de abajo tambien).
# from modules.tareas.tarea_router import router as tarea_router

# ============================================================
# M5 - GESTION DE SOLICITUDES
# ============================================================
from modules.solicitudes.solicitud_router import router as solicitud_router
from modules.solicitudes.documento_router import router as documento_router
from modules.solicitudes.solicitud_bootstrap import preparar_modulo_solicitudes





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

    # Tabla de tokens para restablecer la contraseña (enlace enviado por correo)
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id SERIAL PRIMARY KEY,
            usuario_id UUID NOT NULL,
            token VARCHAR(255) UNIQUE NOT NULL,
            fecha_expiracion TIMESTAMP WITH TIME ZONE NOT NULL,
            utilizado BOOLEAN NOT NULL DEFAULT FALSE,
            creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """))

    # Columna que marca si el usuario ya verificó un código (fase 2 del login).
    await session.execute(text("""
        ALTER TABLE usuario
        ADD COLUMN IF NOT EXISTS codigo_verificado BOOLEAN DEFAULT FALSE;
    """))


async def ensure_apelaciones_schema(session) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS apelacion (
            id SERIAL PRIMARY KEY,
            id_solicitud INTEGER NOT NULL,
            estado VARCHAR(50) NOT NULL DEFAULT 'RADICADA',
            fecha TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            motivo TEXT NOT NULL,
            fallo TEXT
        );
    """))

    for column_sql in [
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS id_solicitud INTEGER;",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'RADICADA';",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS fecha TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS motivo TEXT;",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS fallo TEXT;",
    ]:
        await session.execute(text(column_sql))

    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS evidencia_apelacion (
            id_evidencia SERIAL PRIMARY KEY,
            id_apelacion INTEGER NOT NULL,
            id_usuario INTEGER NOT NULL,
            nombre_archivo VARCHAR(255) NOT NULL,
            tipo_evidencia VARCHAR(100),
            url_archivo TEXT NOT NULL,
            descripcion TEXT,
            fecha_subida TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_evidencia_apelacion FOREIGN KEY (id_apelacion) REFERENCES apelacion(id)
        );
    """))

    for column_sql in [
        "ALTER TABLE evidencia_apelacion ADD COLUMN IF NOT EXISTS id_apelacion INTEGER;",
        "ALTER TABLE evidencia_apelacion ADD COLUMN IF NOT EXISTS id_usuario INTEGER;",
        "ALTER TABLE evidencia_apelacion ADD COLUMN IF NOT EXISTS nombre_archivo VARCHAR(255);",
        "ALTER TABLE evidencia_apelacion ADD COLUMN IF NOT EXISTS tipo_evidencia VARCHAR(100);",
        "ALTER TABLE evidencia_apelacion ADD COLUMN IF NOT EXISTS url_archivo TEXT;",
        "ALTER TABLE evidencia_apelacion ADD COLUMN IF NOT EXISTS descripcion TEXT;",
        "ALTER TABLE evidencia_apelacion ADD COLUMN IF NOT EXISTS fecha_subida TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;",
    ]:
        await session.execute(text(column_sql))


async def ensure_empresa_sedes_schema(session) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS sede (
            id_sede SERIAL PRIMARY KEY,
            id_empresa INTEGER NOT NULL,
            nombre_sede VARCHAR(200) NOT NULL,
            direccion VARCHAR(255) NOT NULL,
            ciudad VARCHAR(100) NOT NULL,
            departamento VARCHAR(100),
            pais VARCHAR(100),
            es_principal BOOLEAN NOT NULL DEFAULT FALSE,
            estado VARCHAR(50) NOT NULL DEFAULT 'Activo',
            fecha_registro TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_sede_empresa FOREIGN KEY (id_empresa) REFERENCES empresa(id_empresa)
        );
    """))

    await session.execute(text("""
        ALTER TABLE sede
        ADD COLUMN IF NOT EXISTS id_empresa INTEGER;
    """))

    await session.execute(text("""
        ALTER TABLE sede
        ADD COLUMN IF NOT EXISTS nombre_sede VARCHAR(200);
    """))

    await session.execute(text("""
        ALTER TABLE sede
        ADD COLUMN IF NOT EXISTS direccion VARCHAR(255);
    """))

    await session.execute(text("""
        ALTER TABLE sede
        ADD COLUMN IF NOT EXISTS ciudad VARCHAR(100);
    """))

    await session.execute(text("""
        ALTER TABLE sede
        ADD COLUMN IF NOT EXISTS departamento VARCHAR(100);
    """))

    await session.execute(text("""
        ALTER TABLE sede
        ADD COLUMN IF NOT EXISTS pais VARCHAR(100);
    """))

    await session.execute(text("""
        ALTER TABLE sede
        ADD COLUMN IF NOT EXISTS es_principal BOOLEAN DEFAULT FALSE;
    """))

    await session.execute(text("""
        ALTER TABLE sede
        ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'Activo';
    """))

    await session.execute(text("""
        ALTER TABLE sede
        ADD COLUMN IF NOT EXISTS fecha_registro TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
    """))

async def seed_initial_data() -> None:
    async with AsyncSessionLocal() as session:
        try:
            await ensure_login_security_schema(session)
            await ensure_apelaciones_schema(session)
            await ensure_empresa_sedes_schema(session)

            # Roles por defecto según la tabla rol (id_rol PK, nombre, descripcion)
            default_rol = [
                ("Auditor", "Puede completar su registro y cargar documentos"),
                ("Empresa", "Puede registrar documentos y solicitudes"),
                ("Auxiliar", "Cuenta interna creada por el administrador"),
                ("Administrador", "Acceso total al sistema"),
                ("Instructor", "Rol heredado; sin permisos en los modulos de certificacion"),
                ("Aprendiz", "Usuario estándar"),
            ]

            for role_name, role_description in default_rol:
                existing_role = await session.execute(
                    text("SELECT id_rol FROM rol WHERE nombre = :nombre;"),
                    {"nombre": role_name},
                )
                # if existing_role.scalar_one_or_none() is None: ANTES
                # CAMBIO: Usamos .scalar() en lugar de .scalar_one_or_none() 
                # para que retorne la primera coincidencia sin fallar si hay roles duplicados.
                if existing_role.scalar() is None:
                    await session.execute(
                        text("INSERT INTO rol (nombre, descripcion) VALUES (:nombre, :descripcion);"),
                        {"nombre": role_name, "descripcion": role_description},
                    )

            # Verificar si existe el usuario admin en la tabla usuario (id UUID, nombre, correo, contrasena, estado BOOLEAN, rol_id)
            existing_admin = await session.execute(
                text("SELECT id_usuario FROM usuario WHERE nombre = :nombre;"),
                {"nombre": "admin"},
            )
            # if existing_admin.scalar_one_or_none() is None: ANTES
            # CAMBIO: Se usa .scalar() para evitar la excepción MultipleResultsFound
            # en caso de que existan múltiples registros con el nombre 'admin'.
            if existing_admin.scalar() is None:
                role_result = await session.execute(
                    text("SELECT id_rol FROM rol WHERE nombre = :nombre;"),
                    {"nombre": "Administrador"},
                )
                # admin_role_id = role_result.scalar_one_or_none() ANTES
                # CAMBIO: Obtenemos el id_rol del primer registro retornado de la tabla rol.
                admin_role_id = role_result.scalar()
                if admin_role_id is not None:
                    await session.execute(
                        text("""
                            INSERT INTO usuario (id_usuario, nombre, correo, contrasena, estado, intentos_fallidos, rol_id, tipo_doc, num_doc)
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
    try:
        yield
    finally:
        logger.info("Cerrando recursos de la API de forma segura.")
        await redis_pool.disconnect()

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
app.include_router(security_router)
app.include_router(empresas_router)
app.include_router(comite_router)
app.include_router(apelaciones_router)
app.include_router(alejandra_router)
app.include_router(mfa_router)
app.include_router(system_router)
app.include_router(asignacion_auditores_router)
# app.include_router(tarea_router)   # modulo heredado, ver nota arriba

# M5 - Gestion de solicitudes
app.include_router(solicitud_router)
app.include_router(documento_router)

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


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    """Sirve la página para crear una nueva contraseña (enlace del correo)."""
    return FileResponse("static/reset-password.html")

@app.get("/asignacion-auditores")
async def asignacion_auditores_page():
    return FileResponse(
        "static/asignacion-auditores.html"
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return FileResponse("static/dashboard.html")
    # La antigua plantilla se conserva debajo como referencia no ejecutable.
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


@app.get("/empresas", response_class=HTMLResponse)
async def empresas_page(request: Request):
    return FileResponse("static/empresas.html")


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    return FileResponse("static/profile.html")


@app.get("/auditor", response_class=HTMLResponse)
async def auditor_page(request: Request):
    return FileResponse("static/auditor.html")


@app.get("/empresa", response_class=HTMLResponse)
async def empresa_page(request: Request):
    return FileResponse("static/empresa.html")


@app.get("/buscar_empresa", response_class=HTMLResponse)
async def buscar_empresa_page(request: Request):
    return FileResponse("static/buscar_e.html")

@app.on_event("shutdown")
async def shutdown_redis_pool():
    await redis_pool.disconnect()
