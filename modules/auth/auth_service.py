from datetime import datetime, timedelta, timezone
import random

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import logger
from core.security import (
    create_access_token,
    verify_password,
    hash_verification_code,
    verify_verification_code,
)

from modules.auth.mail_service import MailService


INTENTOS_MAXIMOS = 5
TIEMPO_BLOQUEO_MINUTOS = 5


class AuthService:

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _ahora(self) -> datetime:
        """
        Devuelve la fecha y hora actual en UTC.
        """
        return datetime.now(timezone.utc)

    def _generar_codigo(self) -> str:
        """
        Genera un código aleatorio de seis dígitos.
        """
        return str(random.randint(100000, 999999))

    async def _log_access(
        self,
        user_id: int | None,
        correo_intentado: str,
        ip_origen: str,
        exitoso: bool,
        motivo_fallo: str | None,
    ) -> None:
        """
        Registra todos los intentos de acceso al sistema.
        """

        try:
            # Crear la tabla si aún no existe
            await self.db.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS logs_acceso (
                        id SERIAL PRIMARY KEY,
                        usuario_id INTEGER NULL,
                        correo_intentado VARCHAR(255) NOT NULL,
                        ip_origen VARCHAR(45) NOT NULL,
                        exitoso BOOLEAN NOT NULL,
                        motivo_fallo VARCHAR(100),
                        fecha_hora TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            )

            # Registrar el intento
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
                    "usuario_id": user_id,
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

        if usuario["codigo_expira"] < self._ahora():
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

            # Llegó al máximo de intentos del código
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
                        "ahora": self._ahora(),
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
                    ultimo_envio_codigo=NULL
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
                id,
                nombre,
                correo,
                contrasena AS password_hash,
                estado,
                COALESCE(intentos_fallidos,0) AS intentos_fallidos,
                ultimo_intento,
                codigo_verificacion,
                codigo_expira,
                bloqueado_hasta,
                rol_id
            FROM usuario
            WHERE LOWER(correo)=LOWER(:identifier)
                OR LOWER(nombre)=LOWER(:identifier)
            LIMIT 1
        """)

        result = await self.db.execute(
            query,
            {"identifier": identifier},
        )

        user = result.mappings().first()

        # Usuario inexistente
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

        # ¿Existe un código pendiente?
        codigo = user.get("codigo_verificacion")
        expira = user.get("codigo_expira")

        if codigo and expira:

            if expira > self._ahora():

                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Debe ingresar el código de verificación "
                        "que fue enviado a su correo."
                    ),
                )

            # Si expiró lo eliminamos
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

        # Validar que la cuenta esté activa
        if not user["estado"]:

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

        # Validar si existe un bloqueo temporal
        bloqueado_hasta = user.get("bloqueado_hasta")

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

        # Si el bloqueo ya expiró, limpiar los datos
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

            # Reiniciar contador si pasaron más de 5 minutos
            if (
                ultimo_intento is None
                or (ahora - ultimo_intento).total_seconds() > 300
            ):
                nuevos_intentos = 1
            else:
                nuevos_intentos = int(user["intentos_fallidos"] or 0) + 1

            # Llegó al máximo de intentos
            if nuevos_intentos >= INTENTOS_MAXIMOS:

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

                # Enviar código por correo
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
                    detail=(
                        "Ha superado el número máximo de intentos. "
                        "Se envió un código de verificación a su correo."
                    ),
                )

            # Guardar intento fallido
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

            intentos_restantes = INTENTOS_MAXIMOS - nuevos_intentos

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    f"Credenciales inválidas. "
                    f"Le quedan {intentos_restantes} intento(s) antes de requerir un código de verificación."
                ),
                headers={
                    "WWW-Authenticate": "Bearer"
                },
            )
            
        # 5. Login exitoso (reseteamos fallos)
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
                    bloqueado_hasta = NULL
                WHERE id = :id
            """),
            {
                "id": user["id"],
            },
        )

        await self.db.commit()

        await self._log_access(
            user["id"],
            user["correo"],
            client_ip,
            True,
            "Autenticación exitosa",
        )

        # Generación de JWT con los nombres de campos mapeados en español
        return create_access_token(
            data={
                "sub": user.get("nombre") or user.get("correo") or identifier,
                "user_id": int(user["id"]),
                "role_id": int(user["rol_id"]) if user.get("rol_id") is not None else None,
            }
        )