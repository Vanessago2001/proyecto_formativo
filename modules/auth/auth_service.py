from datetime import datetime, timedelta, timezone
import random
import secrets

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from modules.mfa.mfa_service import MFAService

from core.config import settings
from core.logger import logger
from core.security import (
    create_access_token,
    verify_password,
    hash_password,
    hash_verification_code,
    verify_verification_code,
    validar_password_segura,
)
from core.datetime_utils import system_now

from modules.auth.mail_service import MailService

# Fase 1: tras 3 intentos fallidos se exige el código de verificación por correo.
INTENTOS_ANTES_DE_CODIGO = 3
# Fase 2: tras verificar el código, se dan 5 intentos más; al agotarlos se envía
# un enlace de restablecimiento de contraseña.
INTENTOS_ANTES_DE_RESET = 5
# Tiempo que la cuenta queda bloqueada tras enviar el enlace de restablecimiento.
TIEMPO_BLOQUEO_MINUTOS = 15
# Vigencia del enlace de restablecimiento de contraseña.
RESET_TOKEN_MINUTOS = 30
# Días de vigencia de la contraseña antes de exigir cambio (0 = sin expiración).
# Roles Auditor y Empresa: 60 días. Los demás: 90 días.
DIAS_EXPIRACION_POR_ROL = {
    "Auditor": 60,
    "Empresa": 60,
}
DIAS_EXPIRACION_DEFAULT = 120


class AuthService:

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _ahora(self) -> datetime:
        """
        Devuelve la fecha y hora actual en UTC (naive) para comparar con fechas de la BD.
        """
        return system_now()

    def _a_naive_utc(self, valor: datetime) -> datetime:
        """
        Convierte cualquier fecha a UTC sin zona horaria.
        """
        if valor.tzinfo is not None:
            return valor.astimezone(timezone.utc).replace(tzinfo=None)

        return valor

    def _generar_codigo(self) -> str:
        """
        Genera un código aleatorio de seis dígitos.
        """
        return str(random.randint(100000, 999999))

    async def _log_access(
        self,
        user_id: str | None,
        correo_intentado: str,
        ip_origen: str,
        exitoso: bool,
        motivo_fallo: str | None,
    ) -> None:
        """
        Registra todos los intentos de acceso al sistema.
        """
        try:
            # Crear la tabla si aún no existe.
            # usuario_id es UUID porque usuario.id es UUID en este proyecto.
            await self.db.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS logs_acceso (
                        id SERIAL PRIMARY KEY,
                        usuario_id UUID NULL,
                        correo_intentado VARCHAR(255) NOT NULL,
                        ip_origen VARCHAR(45) NOT NULL,
                        exitoso BOOLEAN NOT NULL,
                        motivo_fallo VARCHAR(100),
                        fecha_hora TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            )

            await self.db.execute(
                text("""
                    INSERT INTO logs_acceso
                    (
                        usuario_id,
                        correo_intentado,
                        ip_origen,
                        exitoso,
                        motivo_fallo
                    )
                    VALUES
                    (
                        :usuario_id,
                        :correo_intentado,
                        :ip_origen,
                        :exitoso,
                        :motivo_fallo
                    );
                """),
                {
                    "usuario_id": str(user_id) if user_id is not None else None,
                    "correo_intentado": correo_intentado,
                    "ip_origen": ip_origen or "unknown",
                    "exitoso": exitoso,
                    "motivo_fallo": motivo_fallo,
                },
            )

            await self.db.commit()

        except Exception as exc:
            logger.exception(
                "No fue posible registrar el log de acceso: %s",
                exc,
            )
            if self.db.in_transaction():
                await self.db.rollback()

    async def verificar_codigo(
        self,
        correo: str,
        codigo: str,
    ):
        resultado = await self.db.execute(
            text("""
                SELECT
                    id,
                    correo,
                    codigo_verificacion,
                    codigo_expira,
                    COALESCE(intentos_codigo,0) AS intentos_codigo
                FROM usuario
                WHERE LOWER(correo)=LOWER(:correo)
            """),
            {
                "correo": correo,
            },
        )

        usuario = resultado.mappings().first()

        if not usuario:
            raise HTTPException(
                status_code=404,
                detail="Usuario no encontrado.",
            )

        if not usuario["codigo_verificacion"]:
            raise HTTPException(
                status_code=400,
                detail="No existe ningún código pendiente.",
            )

        if self._a_naive_utc(usuario["codigo_expira"]) < self._ahora():
            raise HTTPException(
                status_code=400,
                detail="El código expiró.",
            )

        intentos_codigo = usuario["intentos_codigo"]

        if not verify_verification_code(
            codigo,
            usuario["codigo_verificacion"],
        ):
            intentos_codigo += 1

            if intentos_codigo >= 3:
                nuevo_codigo = self._generar_codigo()
                nuevo_codigo_hash = hash_verification_code(nuevo_codigo)

                nueva_expiracion = self._ahora() + timedelta(minutes=5)

                await self.db.execute(
                    text("""
                        UPDATE usuario
                        SET
                            codigo_verificacion=:codigo,
                            codigo_expira=:expira,
                            intentos_codigo=0,
                            ultimo_envio_codigo=:ahora
                        WHERE id=:id
                    """),
                    {
                        "codigo": nuevo_codigo_hash,
                        "expira": nueva_expiracion,
                        "ahora": self._ahora().replace(tzinfo=None),
                        "id": usuario["id"],
                    },
                )

                await self.db.commit()

                await MailService.enviar_codigo(
                    destinatario=correo,
                    codigo=nuevo_codigo,
                )

                raise HTTPException(
                    status_code=403,
                    detail=(
                        "Ha superado el número máximo de intentos del código. "
                        "Se generó y envió un nuevo código a su correo."
                    ),
                )

            await self.db.execute(
                text("""
                    UPDATE usuario
                    SET intentos_codigo=:intentos
                    WHERE id=:id
                """),
                {
                    "intentos": intentos_codigo,
                    "id": usuario["id"],
                },
            )

            await self.db.commit()

            raise HTTPException(
                status_code=400,
                detail=f"Código incorrecto. Intento {intentos_codigo} de 3.",
            )

        # Código correcto
        await self.db.execute(
            text("""
                UPDATE usuario
                SET
                    intentos_fallidos=0,
                    ultimo_intento=NULL,
                    codigo_verificacion=NULL,
                    codigo_expira=NULL,
                    intentos_codigo=0,
                    ultimo_envio_codigo=NULL,
                    codigo_verificado=TRUE
                WHERE id=:id
            """),
            {
                "id": usuario["id"],
            },
        )

        await self.db.commit()

        return {
            "mensaje": "Código verificado correctamente. Ya puede volver a iniciar sesión."
        }

    async def login(
        self,
        correo_in: str,
        password_in: str,
        client_ip: str | None = None,
    ) -> str:
        client_ip = client_ip or "unknown"
        identifier = correo_in.strip().lower()

        logger.info(
            "SQL Nativo: Intento de login para: %s",
            identifier,
        )

        query = text("""
            SELECT
                u.id,
                u.nombre,
                u.correo,
                u.contrasena AS password_hash,
                u.estado,
                COALESCE(u.intentos_fallidos,0) AS intentos_fallidos,
                u.ultimo_intento,
                u.codigo_verificacion,
                u.codigo_expira,
                u.bloqueado_hasta,
                u.rol_id,
                COALESCE(u.codigo_verificado, FALSE) AS codigo_verificado,
                u.fecha_cambio_password,
                u.mfa_activado,
                u.mfa_codigo,
                u.mfa_expira,
                u.mfa_verificado,
                r.nombre AS rol_nombre
            FROM usuario u
            LEFT JOIN rol r ON u.rol_id = r.id_rol
            WHERE LOWER(u.correo)=LOWER(:identifier)
                OR LOWER(u.nombre)=LOWER(:identifier)
            LIMIT 1
        """)

        result = await self.db.execute(
            query,
            {"identifier": identifier},
        )

        user = result.mappings().first()

        if not user:
            await self._log_access(
                None,
                identifier,
                client_ip,
                False,
                "Usuario no existente",
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales inválidas.",
                headers={
                    "WWW-Authenticate": "Bearer"
                },
            )

        codigo = user.get("codigo_verificacion")
        expira = user.get("codigo_expira")

        if codigo and expira:
            if self._a_naive_utc(expira) > self._ahora():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "accion": "codigo",
                        "mensaje": (
                            "Debe ingresar el código de verificación "
                            "que fue enviado a su correo."
                        ),
                    },
                )

            await self.db.execute(
                text("""
                    UPDATE usuario
                    SET
                        codigo_verificacion=NULL,
                        codigo_expira=NULL,
                        intentos_codigo=0
                    WHERE id=:id
                """),
                {
                    "id": user["id"],
                },
            )

            await self.db.commit()
        if user["estado"] and user["estado"].strip().lower() == "inactivo":
            await self._log_access(
                user["id"],
                user["correo"],
                client_ip,
                False,
                "Cuenta inactiva",
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="La cuenta se encuentra inactiva.",
            )

        bloqueado_hasta = user.get("bloqueado_hasta")
        if bloqueado_hasta is not None:
            bloqueado_hasta = self._a_naive_utc(bloqueado_hasta)

        if (
            bloqueado_hasta is not None
            and bloqueado_hasta > self._ahora()
        ):
            await self._log_access(
                user["id"],
                user["correo"],
                client_ip,
                False,
                "Cuenta bloqueada",
            )

            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=(
                    "La cuenta continúa bloqueada temporalmente."
                ),
            )

        if bloqueado_hasta is not None:
            await self.db.execute(
                text("""
                    UPDATE usuario
                    SET
                        bloqueado_hasta=NULL,
                        intentos_fallidos=0,
                        ultimo_intento=NULL
                    WHERE id=:id
                """),
                {
                    "id": user["id"],
                },
            )

            await self.db.commit()
        # ===== AQUÍ COMIENZA LA VERIFICACIÓN DE LA CONTRASEÑA =====

        if not verify_password(password_in, user["password_hash"] or ""):
            ahora = self._ahora()
            ultimo_intento = user.get("ultimo_intento")
            if ultimo_intento is not None:
                ultimo_intento = self._a_naive_utc(ultimo_intento)
            ya_verifico = bool(user.get("codigo_verificado"))

            # Fase 1 (sin código verificado): 3 intentos -> se exige un código.
            # Fase 2 (código ya verificado): 5 intentos -> se envía enlace de reset.
            limite = (
                INTENTOS_ANTES_DE_RESET
                if ya_verifico
                else INTENTOS_ANTES_DE_CODIGO
            )

            if (
                ultimo_intento is None
                or (ahora - ultimo_intento).total_seconds() > 300
            ):
                nuevos_intentos = 1
            else:
                nuevos_intentos = int(user["intentos_fallidos"] or 0) + 1

            # ¿Alcanzó el límite de la fase actual?
            if nuevos_intentos >= limite:

                if not ya_verifico:
                    # ----- FASE 1: enviar código de verificación al correo -----
                    codigo = self._generar_codigo()
                    codigo_hash = hash_verification_code(codigo)
                    expira = ahora + timedelta(minutes=5)

                    await self.db.execute(
                        text("""
                            UPDATE usuario
                            SET
                                intentos_fallidos = :intentos,
                                ultimo_intento = :ultimo_intento,
                                codigo_verificacion = :codigo,
                                codigo_expira = :expira
                            WHERE id = :id
                        """),
                        {
                            "intentos": nuevos_intentos,
                            "ultimo_intento": ahora,
                            "codigo": codigo_hash,
                            "expira": expira,
                            "id": user["id"],
                        },
                    )
                    await self.db.commit()

                    await MailService.enviar_codigo(
                        destinatario=user["correo"],
                        codigo=codigo,
                    )

                    await self._log_access(
                        user["id"],
                        user["correo"],
                        client_ip,
                        False,
                        "Código de verificación enviado",
                    )

                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail={
                            "accion": "codigo",
                            "mensaje": (
                                "Ha superado los 3 intentos permitidos. "
                                "Se envió un código de verificación a su correo."
                            ),
                        },
                    )

                # ----- FASE 2: enviar enlace de restablecimiento de contraseña -----
                enlace = await self._crear_enlace_reset(user["id"], ahora)

                # Bloquear la cuenta temporalmente y limpiar contadores de intentos.
                bloqueo = ahora + timedelta(minutes=TIEMPO_BLOQUEO_MINUTOS)
                await self.db.execute(
                    text("""
                        UPDATE usuario
                        SET
                            intentos_fallidos = 0,
                            ultimo_intento = NULL,
                            bloqueado_hasta = :bloqueo
                        WHERE id = :id
                    """),
                    {
                        "bloqueo": bloqueo,
                        "id": user["id"],
                    },
                )
                await self.db.commit()

                await MailService.enviar_enlace_reset(
                    destinatario=user["correo"],
                    enlace=enlace,
                )

                await self._log_access(
                    user["id"],
                    user["correo"],
                    client_ip,
                    False,
                    "Enlace de restablecimiento enviado",
                )

                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "accion": "reset",
                        "mensaje": (
                            "Ha superado el número máximo de intentos. "
                            "Se envió un enlace a su correo para restablecer la contraseña."
                        ),
                    },
                )

            # Guardar intento fallido (aún no alcanza el límite de la fase)
            await self.db.execute(
                text("""
                    UPDATE usuario
                    SET
                        intentos_fallidos = :intentos,
                        ultimo_intento = :ultimo_intento
                    WHERE id = :id
                """),
                {
                    "intentos": nuevos_intentos,
                    "ultimo_intento": ahora,
                    "id": user["id"],
                },
            )
            await self.db.commit()

            await self._log_access(
                user["id"],
                user["correo"],
                client_ip,
                False,
                "Contraseña incorrecta",
            )

            intentos_restantes = limite - nuevos_intentos
            siguiente_paso = (
                "tener que restablecer su contraseña"
                if ya_verifico
                else "requerir un código de verificación"
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    f"Credenciales inválidas. "
                    f"Le quedan {intentos_restantes} intento(s) antes de {siguiente_paso}."
                ),
                headers={
                    "WWW-Authenticate": "Bearer"
                },
            )
        # 5. Login exitoso (reseteamos fallos)
        fecha_cambio = user.get("fecha_cambio_password")
        ultimo_inicio = user.get("ultimo_inicio_sesion")
        rol_nombre = user.get("rol_nombre", "")
        dias_expiracion = DIAS_EXPIRACION_POR_ROL.get(rol_nombre, DIAS_EXPIRACION_DEFAULT)

        if dias_expiracion > 0 and fecha_cambio is not None:
            fecha_limite = self._a_naive_utc(fecha_cambio) + timedelta(days=dias_expiracion)

            if self._a_naive_utc(self._ahora()) > fecha_limite:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Su contraseña ha expirado. Debe cambiarla antes de iniciar sesión."
                )

        # 5.1 Para roles que no son Auditor ni Empresa, verificar inactividad (90 días)
        if rol_nombre not in ("Auditor", "Empresa") and ultimo_inicio is not None:
            dias_inactividad = 90
            fecha_limite_inactividad = self._a_naive_utc(ultimo_inicio) + timedelta(days=dias_inactividad)

            if self._ahora() > fecha_limite_inactividad:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Su contraseña ha expirado por inactividad. Debe cambiarla antes de iniciar sesión."
                )

        await self.db.execute(
            text("""
                UPDATE usuario
                SET
                    intentos_fallidos = 0,
                    ultimo_intento = NULL,
                    codigo_verificacion = NULL,
                    codigo_expira = NULL,
                    intentos_codigo = 0,
                    ultimo_envio_codigo = NULL,
                    codigo_verificado = FALSE,
                    bloqueado_hasta = NULL,
                    ultimo_inicio_sesion = NOW()
                WHERE id = :id
            """),
            {
                "id": user["id"],
            },
        )

        await self.db.commit()
        # nuevo Sneider
        if user["mfa_activado"]:
          mfa = MFAService(self.db)

          await mfa.login_request(user["correo"])

          raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "accion": "mfa",
                "mensaje": "Se envió un código de verificación a su correo.",
                "correo": user["correo"]
            }
        )

        await self._log_access(
            user["id"],
            user["correo"],
            client_ip,
            True,
            "Autenticación exitosa",
        )

        return create_access_token(
            data={
                "sub": user.get("nombre") or user.get("correo") or identifier,
                "user_id": str(user["id"]),
                "role_id": int(user["rol_id"]) if user.get("rol_id") is not None else None,
                "role_name": user.get("rol_nombre"),
            }
        )

    # nuevo Sneider
    # nuevo Sneider login MFA
    
    async def login_mfa(self,correo: str,codigo: str,):
             # --------------------------------------------------------
        # Buscar usuario
        # --------------------------------------------------------
            result = await self.db.execute(
                text("""
                SELECT
                    u.id,
                    u.nombre,
                    u.correo,
                    u.rol_id,
                    u.mfa_codigo,
                    u.mfa_expira,
                    r.nombre AS rol_nombre
                FROM usuario u
                LEFT JOIN rol r
                    ON r.id_rol = u.rol_id
                WHERE LOWER(u.correo)=LOWER(:correo)
                LIMIT 1
                """),
                {
                    "correo": correo
                }
            )
    
            user = result.mappings().first()
    
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Usuario no encontrado."
                )
    
            # --------------------------------------------------------
            # Verificar que exista un código MFA pendiente
    
            print("=== LOGIN MFA ===")
            print("Correo recibido:", correo)
            print("Usuario:", user)
            print("mfa_codigo:", user["mfa_codigo"])
            print("mfa_expira:", user["mfa_expira"])
            if user["mfa_codigo"] is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No existe un código MFA pendiente."
                )
    
            # --------------------------------------------------------
            # Verificar expiración
            # --------------------------------------------------------
    
            if user["mfa_expira"] is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El código MFA expiró."
                )
    
            if self._a_naive_utc(user["mfa_expira"]) < self._a_naive_utc(self._ahora()):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El código MFA expiró."
                )
    
            # --------------------------------------------------------
            # Verificar código
            # --------------------------------------------------------
    
            if user["mfa_codigo"] != codigo:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Código MFA incorrecto."
                )
    
            # --------------------------------------------------------
            # Limpiar el código MFA para que no pueda reutilizarse
            # --------------------------------------------------------
    
            await self.db.execute(
                text("""
                    UPDATE usuario
                    SET
                        mfa_codigo = NULL,
                        mfa_expira = NULL,
                        mfa_verificado = TRUE
                    WHERE id = :id
                """),
                {
                    "id": user["id"]
                }
            )
    
            await self.db.commit()
    
            # --------------------------------------------------------
            # Generar JWT
            # --------------------------------------------------------
    
            token = create_access_token(
                data={
                    "sub": user["nombre"],
                    "user_id": str(user["id"]),
                    "role_id": user["rol_id"],
                    "role_name": user["rol_nombre"],
                }
            )
    
            return {
                "access_token": token,
                "token_type": "bearer",
            }

    # historial de accesos
    async def obtener_historial_accesos(
        self,
        limite: int = 100,
        pagina: int = 1,
    ):

        offset = (pagina - 1) * limite

        resultado = await self.db.execute(
            text("""
                SELECT
                    l.id,
                    l.usuario_id,
                    l.correo_intentado,
                    l.ip_origen,
                    l.exitoso,
                    l.motivo_fallo,
                    l.fecha_hora,
                    u.nombre,
                    r.nombre AS rol
                FROM logs_acceso l
                LEFT JOIN usuario u
                    ON u.id = l.usuario_id
                LEFT JOIN rol r
                    ON r.id_rol = u.rol_id
                ORDER BY l.fecha_hora DESC
                LIMIT :limite
                OFFSET :offset
            """),
            {
                "limite": limite,
                "offset": offset,
            },
        )

        registros = resultado.mappings().all()

        return registros

    async def _ensure_reset_table(self) -> None:
        """
        Crea la tabla de tokens de restablecimiento si aún no existe.
        usuario_id es UUID porque usuario.id es UUID en este proyecto.
        """
        await self.db.execute(
            text("""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id SERIAL PRIMARY KEY,
                    usuario_id UUID NOT NULL,
                    token VARCHAR(255) UNIQUE NOT NULL,
                    fecha_expiracion TIMESTAMPTZ NOT NULL,
                    utilizado BOOLEAN NOT NULL DEFAULT FALSE,
                    creado_en TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
        )

    async def _crear_enlace_reset(
        self,
        user_id,
        ahora: datetime,
    ) -> str:
        """
        Genera un token seguro de un solo uso, lo guarda en la base de datos y
        devuelve el enlace completo que se enviará al correo del usuario.
        """
        await self._ensure_reset_table()

        token = secrets.token_urlsafe(32)
        expira = ahora + timedelta(minutes=RESET_TOKEN_MINUTOS)

        await self.db.execute(
            text("""
                INSERT INTO password_reset_tokens
                    (usuario_id, token, fecha_expiracion)
                VALUES
                    (:usuario_id, :token, :fecha_expiracion)
            """),
            {
                "usuario_id": str(user_id),
                "token": token,
                "fecha_expiracion": expira,
            },
        )

        # Escribir también en Redis, con TTL igual a la vigencia del token
        from core.redis_client import get_redis_client
        redis_client = get_redis_client()
        ttl_segundos = RESET_TOKEN_MINUTOS * 60
        await redis_client.set(f"password_reset_token:{token}", str(user_id), ex=ttl_segundos)

        base_url = settings.APP_BASE_URL.rstrip("/")
        return f"{base_url}/reset-password?token={token}"

    async def _validar_token_reset(self, token: str):
        """
        Valida que el token exista, no haya sido usado y no esté expirado.
        Devuelve el registro del token.
        """
        await self._ensure_reset_table()

        resultado = await self.db.execute(
            text("""
                SELECT id, usuario_id, fecha_expiracion, utilizado
                FROM password_reset_tokens
                WHERE token = :token
            """),
            {"token": token},
        )

        registro = resultado.mappings().first()

        if not registro:
            raise HTTPException(
                status_code=400,
                detail="El enlace de restablecimiento no es válido.",
            )

        if registro["utilizado"]:
            raise HTTPException(
                status_code=400,
                detail="Este enlace ya fue utilizado. Solicite uno nuevo.",
            )

        if self._a_naive_utc(registro["fecha_expiracion"]) < self._ahora():
            raise HTTPException(
                status_code=400,
                detail="El enlace de restablecimiento expiró. Solicite uno nuevo.",
            )

        return registro

    async def reset_password(
        self,
        token: str,
        nueva_password: str,
    ) -> dict:
        """Restablece la contraseña del usuario asociado a un token válido,

        verificando que la nueva contraseña no sea igual a la actual.
        """
        # 1. Validar el token y obtener los datos del usuario
        registro = await self._validar_token_reset(token)
        usuario_id = registro.get("usuario_id") or registro.get("user_id")

        # 2. Consultar la contraseña actual almacenada en la base de datos
        query_usuario = text("SELECT contrasena FROM usuario WHERE id = :usuario_id;")
        result = await self.db.execute(query_usuario, {"usuario_id": usuario_id})
        usuario = result.mappings().first()

        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")

        # 3. Validar que la nueva contraseña no sea igual a la contraseña actual
        if verify_password(nueva_password, usuario["contrasena"]):
            raise HTTPException(
                status_code=400,
                detail=(
                    "La nueva contraseña no puede ser igual a la contraseña actual."
                ),
            )
        """
        Restablece la contraseña del usuario asociado a un token válido.
        Aplica la política de contraseña segura, actualiza el hash y deja la
        cuenta lista para iniciar sesión (limpia bloqueos y contadores).
        """

        es_valida, mensaje = validar_password_segura(nueva_password)
        if not es_valida:
            raise HTTPException(
                status_code=400,
                detail=mensaje,
            )

        nuevo_hash = hash_password(nueva_password)

        await self.db.execute(
            text("""
                UPDATE usuario
                SET
                    contrasena = :contrasena,
                    fecha_cambio_password = NOW(),
                    intentos_fallidos = 0,
                    ultimo_intento = NULL,
                    codigo_verificacion = NULL,
                    codigo_expira = NULL,
                    intentos_codigo = 0,
                    ultimo_envio_codigo = NULL,
                    codigo_verificado = FALSE,
                    bloqueado_hasta = NULL
                WHERE id = :id
            """),
            {
                "contrasena": nuevo_hash,
                "id": registro["usuario_id"],
            },
        )

        # Marcar el token como utilizado para que no pueda reusarse.
        await self.db.execute(
            text("""
                UPDATE password_reset_tokens
                SET utilizado = TRUE
                WHERE token = :token
            """),
            {"token": token},
        )

        await self.db.commit()

        # Invalidar también en Redis (evita reutilización mientras dure el TTL)
        from core.redis_client import get_redis_client
        redis_client = get_redis_client()
        await redis_client.delete(f"password_reset_token:{token}")

        return {
            "mensaje": (
                "Contraseña restablecida correctamente. "
                "Ya puede iniciar sesión con su nueva contraseña."
            )
        }

    async def solicitar_reset_password(
        self,
        correo: str,
    ):
        """
        Genera y envía un enlace de restablecimiento cuando el usuario usa la
        opción "¿Olvidó su contraseña?".

        Por seguridad, SIEMPRE responde con el mismo mensaje genérico, exista o no
        el correo (evita revelar qué correos están registrados = anti-enumeración).
        """
        mensaje_generico = {
            "mensaje": (
                "Si el correo está registrado, se enviará un enlace para "
                "restablecer la contraseña. Revise su bandeja de entrada."
            )
        }

        identifier = correo.strip().lower()

        resultado = await self.db.execute(
            text("""
                SELECT id, correo
                FROM usuario
                WHERE LOWER(correo) = LOWER(:correo)
                LIMIT 1
            """),
            {"correo": identifier},
        )

        usuario = resultado.mappings().first()

        # Si no existe, no revelamos nada: respondemos igual.
        if not usuario:
            return mensaje_generico

        ahora = self._ahora()
        enlace = await self._crear_enlace_reset(usuario["id"], ahora)

        await self.db.commit()

        await MailService.enviar_enlace_reset(
            destinatario=usuario["correo"],
            enlace=enlace,
        )

        return mensaje_generico

    async def cambiar_password(
        self,
        user_id,
        password_actual: str,
        password_nueva: str,
    ):
        resultado = await self.db.execute(
            text("SELECT id, contrasena FROM usuario WHERE id = :id"),
            {"id": user_id},
        )
        usuario = resultado.mappings().first()

        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")

        if not verify_password(password_actual, usuario["contrasena"]):
            raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta.")

        es_valida, mensaje = validar_password_segura(password_nueva)
        if not es_valida:
            raise HTTPException(status_code=400, detail=mensaje)

        nuevo_hash = hash_password(password_nueva)

        await self.db.execute(
            text("""
                UPDATE usuario
                SET contrasena = :contrasena, fecha_cambio_password = NOW()
                WHERE id = :id
            """),
            {"contrasena": nuevo_hash, "id": user_id},
        )
        await self.db.commit()

        return {"mensaje": "Contraseña cambiada correctamente."}

    async def cambiar_password_expirada(
        self,
        correo: str,
        password_actual: str,
        password_nueva: str,
    ):
        resultado = await self.db.execute(
            text("SELECT id, contrasena FROM usuario WHERE LOWER(correo) = LOWER(:correo)"),
            {"correo": correo},
        )
        usuario = resultado.mappings().first()

        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")

        if not verify_password(password_actual, usuario["contrasena"]):
            raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta.")

        es_valida, mensaje = validar_password_segura(password_nueva)
        if not es_valida:
            raise HTTPException(status_code=400, detail=mensaje)

        nuevo_hash = hash_password(password_nueva)

        await self.db.execute(
            text("""
                UPDATE usuario
                SET contrasena = :contrasena, fecha_cambio_password = NOW()
                WHERE id = :id
            """),
            {"contrasena": nuevo_hash, "id": usuario["id"]},
        )
        await self.db.commit()

        return {"mensaje": "Contraseña cambiada correctamente. Ya puede iniciar sesión."}
