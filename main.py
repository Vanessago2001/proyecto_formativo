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
from modules.consultas_p.consultas_router import router as consultas_publicas_router
from modules.consultas_p.paginas_router import router as consultas_publicas_paginas
from modules.aprobaciones.aprobacion_router import router as aprobaciones_router
from modules.aprobaciones.aprobacion_bootstrap import preparar_aprobaciones
from modules.comite.comite_router import router as comite_router
from modules.comite.comite_bootstrap import preparar_modulo_comite
from modules.apelaciones.apelaciones_router import router as apelaciones_router
from modules.certificados.certificados_bootstrap import preparar_modulo_certificados
from modules.certificados.certificados_router import router as certificados_router

from modules.alejandra.router import router as alejandra_router

from core.redis_client import redis_pool
from uuid import UUID

from modules.system.system_router import router as system_router
from modules.asignacion_auditores.asignacion_router import router as asignacion_auditores_router

from modules.administrar_auditores.administrar_auditores_router import router as administrar_auditores_router
from modules.auditores.auditor_router import router as auditor_router
from modules.competencias_auditor.competencias_router import router as competencias_auditor_router
from modules.conflictos_auditor.conflictos_router import router as conflictos_auditor_router
from modules.agenda_auditor.agenda_router import router as agenda_auditor_router
from modules.agenda_auditor.agenda_bootstrap import preparar_modulo_agenda
from modules.perfiles_auditor.perfil_router import router as perfil_auditor_router
from modules.reportes_auditor.reporte_router import router as reporte_auditor_router
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
from modules.solicitudes.informacion_router import router as informacion_router
from modules.solicitudes.sede_router import router as sede_router

# ============================================================
# M12 - REPORTES POR ROL
# ============================================================
from modules.reportes.reportes_router import router as reportes_router
from modules.solicitudes.solicitud_bootstrap import preparar_modulo_solicitudes
from modules.empresas.empresas_bootstrap import preparar_modulo_empresas





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
    # Aqui habia un bloque DO $$ que, si encontraba una columna con un tipo
    # distinto al esperado, hacia DROP TABLE de apelacion, apelacion_comite y
    # evidencia_apelacion, borrando sus datos sin aviso. Se elimino: los ajustes
    # de esquema de apelaciones se hacen directamente en la base de datos.
    # Lo que queda abajo solo crea lo que falte; nunca borra ni altera datos.

    await session.execute(text("""
        CREATE SEQUENCE IF NOT EXISTS apelacion_radicado_seq START WITH 1;
    """))

    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS apelacion (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            id_solicitud UUID NOT NULL REFERENCES solicitud(id_solicitud),
            id_usuario_presenta UUID NOT NULL REFERENCES usuario(id_usuario),
            id_empresa UUID NOT NULL,
            id_auditor_evaluador UUID,
            estado VARCHAR(50) NOT NULL DEFAULT 'ENVIADA',
            radicado VARCHAR(50) NOT NULL UNIQUE,
            fecha TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            motivo TEXT NOT NULL,
            razones_rechazo TEXT,
            fallo BOOLEAN NOT NULL DEFAULT FALSE,
            observaciones TEXT,
            fecha_decision TIMESTAMP WITH TIME ZONE
        );
    """))

    for column_sql in [
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS id_solicitud UUID;",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS id_usuario_presenta UUID;",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS id_empresa UUID;",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS id_auditor_evaluador UUID;",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS estado VARCHAR(50) NOT NULL DEFAULT 'ENVIADA';",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS radicado VARCHAR(50);",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS fecha TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS motivo TEXT;",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS razones_rechazo TEXT;",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS fallo BOOLEAN NOT NULL DEFAULT FALSE;",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS observaciones TEXT;",
        "ALTER TABLE apelacion ADD COLUMN IF NOT EXISTS fecha_decision TIMESTAMP WITH TIME ZONE;",
    ]:
        await session.execute(text(column_sql))

    await session.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_apelacion_solicitud ON apelacion (id_solicitud);"
    ))

    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS apelacion_comite (
            id_asignacion UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            id_apelacion UUID NOT NULL REFERENCES apelacion(id) ON DELETE CASCADE,
            id_usuario UUID NOT NULL REFERENCES usuario(id_usuario),
            asignado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (id_apelacion, id_usuario)
        );
    """))

    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS evidencia_apelacion (
            id_evidencia UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            id_apelacion UUID NOT NULL REFERENCES apelacion(id) ON DELETE CASCADE,
            id_usuario UUID NOT NULL REFERENCES usuario(id_usuario),
            nombre_archivo VARCHAR(255) NOT NULL,
            tipo_evidencia VARCHAR(100),
            url_archivo TEXT NOT NULL,
            descripcion TEXT,
            fecha_subida TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """))


# Las sedes de las empresas viven en la tabla `sede_empresa`, que ya existe en
# la base. Antes aqui se intentaba crear una tabla `sede` con id_empresa
# INTEGER, incompatible con empresa.id_empresa (UUID).

async def seed_initial_data() -> None:
    async with AsyncSessionLocal() as session:
        try:
            await ensure_login_security_schema(session)
            await ensure_apelaciones_schema(session)

            # Roles por defecto según la tabla rol (id_rol PK, nombre, descripcion)
            default_rol = [
                ("Auditor", "Puede completar su registro y cargar documentos"),
                ("Empresa", "Puede registrar documentos y solicitudes"),
                ("Auxiliar", "Cuenta interna creada por el administrador"),
                ("Administrador", "Acceso total al sistema"),
                ("Comité", "Puede revisar expedientes y registrar decisiones de certificación"),
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
    # Cada modulo prepara su parte de la base con su propia sesion.
    await preparar_modulo_agenda()
    await preparar_modulo_solicitudes()
    await preparar_modulo_comite()
    await preparar_modulo_empresas()
    await preparar_aprobaciones()
    await preparar_modulo_certificados()
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
# Montaje de directorio para archivos subidos por los usuarios (PDF, imágenes, etc.)
app.mount(
    "/uploads",
    StaticFiles(directory="uploads"),
    name="uploads",
)

# Montaje de archivos estáticos (CSS, JS, imágenes)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Inyección directa de rutas modulares verificadas sin prefijos redundantes
app.include_router(auth_router)
app.include_router(role_router)
app.include_router(users_router)
app.include_router(security_router)
app.include_router(empresas_router)
app.include_router(consultas_publicas_router)
app.include_router(consultas_publicas_paginas)
app.include_router(aprobaciones_router)
app.include_router(comite_router)
app.include_router(certificados_router)
app.include_router(apelaciones_router)
app.include_router(alejandra_router)
app.include_router(mfa_router)
app.include_router(system_router)
app.include_router(asignacion_auditores_router)
app.include_router(auditor_router)
app.include_router(competencias_auditor_router)
app.include_router(conflictos_auditor_router)
app.include_router(agenda_auditor_router)
app.include_router(perfil_auditor_router)
app.include_router(reporte_auditor_router)
# app.include_router(tarea_router)   # modulo heredado, ver nota arriba


@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    """Evita que el navegador sirva HTML desactualizado."""
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type or "application/javascript" in content_type:
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# M5 - Gestion de solicitudes
app.include_router(solicitud_router)
app.include_router(documento_router)
app.include_router(informacion_router)
app.include_router(sede_router)
app.include_router(reportes_router)

# M5 - Administrar Auditores
app.include_router(administrar_auditores_router)
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


@app.get("/comite", response_class=HTMLResponse)
async def comite_page(request: Request):
    return FileResponse("static/comite.html")

@app.get("/consultar-estado")
async def consultar_estado():
    return FileResponse("static/consultar_estado_registro.html")

@app.get("/gestion-certificados", response_class=HTMLResponse)
async def gestion_certificados_page(request: Request):
    return FileResponse("static/certificados.html")


@app.get("/verificar-certificado", response_class=HTMLResponse)
async def verificar_certificado_page(request: Request):
    return FileResponse("static/certificados.html")


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


@app.get("/perfil-auditor", response_class=HTMLResponse)
async def perfil_auditor_page():
    return FileResponse("static/perfil_auditor.html")

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    return FileResponse("static/profile.html")


@app.get("/auditor", response_class=HTMLResponse)
async def auditor_page(request: Request):
    return FileResponse("static/auditor.html")

# banco de auditores
@app.get("/banco-auditores", response_class=HTMLResponse)
async def banco_auditores_page(request: Request):
    return FileResponse("static/banco_auditores.html")

# detalle de una solicitud
@app.get("/conflictos-auditor", response_class=HTMLResponse)
async def conflictos_auditor():
    return FileResponse("static/conflictos_auditor.html")

@app.get("/catalogo-competencias-auditor", response_class=HTMLResponse)
async def catalogo_competencias_auditor():
    return FileResponse("static/catalogo_competencias_auditor.html")

@app.get("/consultar-agenda-auditor-vista", response_class=HTMLResponse)
async def consultar_agenda_auditor_vista():
    return FileResponse("static/consultar_agenda_auditor_vista.html")

@app.get("/notificaciones-auditor", response_class=HTMLResponse)
async def notificaciones_auditor():
    return FileResponse("static/notificaciones_auditor.html")

@app.get("/disponibilidad-auditor", response_class=HTMLResponse)
async def disponibilidad_auditor():
    return FileResponse("static/disponibilidad_auditor.html")

@app.get("/programaciones-futuras-auditor", response_class=HTMLResponse)
async def programaciones_futuras_auditor_page():
    return FileResponse("static/programaciones_futuras_auditor.html")

@app.get("/consultar-auditorias-programadas", response_class=HTMLResponse)
async def consultar_auditorias_programadas_page():
    """Vista del auditor: solo las auditorías que le fueron asignadas."""
    return FileResponse("static/consultar_auditorias_programadas.html")


@app.get("/consultar-auditorias-programadas-admin", response_class=HTMLResponse)
async def consultar_auditorias_programadas_admin_page():
    """Vista del administrador: todas las auditorías programadas del sistema."""
    return FileResponse("static/consultar_auditorias_programadas_admin.html")

@app.get("/consultar-agenda-auditor", response_class=HTMLResponse)
async def consultar_agenda_auditor():
    return FileResponse("static/consultar_agenda_auditor.html")

@app.get("/conflictos-administrador", response_class=HTMLResponse)
async def conflictos_administrador():
    return FileResponse("static/conflictos_administrador.html")

@app.get("/banco-auditores/solicitud/{id_postulacion}")
async def banco_auditores_solicitud(
    id_postulacion: UUID,
):
    return FileResponse(
        "static/banco_auditores_solicitud.html"
    )

@app.get("/empresa", response_class=HTMLResponse)
async def empresa_page(request: Request):
    return FileResponse("static/empresa.html")


@app.get("/apelacion", response_class=HTMLResponse)
async def apelacion_page(request: Request):
    return FileResponse("static/apelacion.html")


@app.get("/buscar_empresa", response_class=HTMLResponse)
async def buscar_empresa_page(request: Request):
    return FileResponse("static/buscar_e.html")
@app.get("/revision-solicitudes", response_class=HTMLResponse)
async def revision_solicitudes_page(request: Request):
    """M5: Administración revisa las solicitudes radicadas y valida sus sedes."""
    return FileResponse("static/revision-solicitudes.html")


@app.get("/reportes", response_class=HTMLResponse)
async def reportes_page(request: Request):
    """M12: el catálogo de reportes lo arma la API según el rol de la sesión."""
    return FileResponse("static/reportes.html")


# /buscar_empresa lo sirve modules/consultas_p/paginas_router.py: la página del
# portal público vive junto a los endpoints que la alimentan.


@app.on_event("shutdown")
async def shutdown_redis_pool():
    await redis_pool.disconnect()
