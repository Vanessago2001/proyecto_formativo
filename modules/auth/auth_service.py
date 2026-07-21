from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from core.security import verify_password, create_access_token
from core.logger import logger

INTENTOS_MAXIMOS = 5
TIEMPO_BLOQUEO_MINUTOS = 15


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _log_access(self, user_id: int | None, correo_intentado: str, ip_origen: str, exitoso: bool, motivo_fallo: str | None) -> None:
        try:
            await self.db.execute(text("""
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
            await self.db.execute(text("""
                INSERT INTO logs_acceso (usuario_id, correo_intentado, ip_origen, exitoso, motivo_fallo)
                VALUES (:usuario_id, :correo_intentado, :ip_origen, :exitoso, :motivo_fallo);
            """), {
                "usuario_id": user_id,
                "correo_intentado": correo_intentado,
                "ip_origen": ip_origen or "unknown",
                "exitoso": exitoso,
                "motivo_fallo": motivo_fallo,
            })
            await self.db.commit()
        except Exception as exc:
            logger.exception("No fue posible registrar el log de acceso: %s", exc)
            await self.db.rollback()

    async def login(self, correo_in: str, password_in: str, client_ip: str | None = None) -> str:
        client_ip = client_ip or "unknown"
        identifier = correo_in.strip().lower()
        logger.info("SQL Nativo: Intento de login para: %s", identifier)

        table_name = "usuarios"
        query = text("""
            SELECT
                id,
                correo AS email,
                password_hash,
                estado,
                intentos_fallidos,
                bloqueado_hasta,
                TRUE AS is_active,
                NULL AS role_id
            FROM usuarios
            WHERE LOWER(correo) = LOWER(:identifier)
            LIMIT 1;
        """)
        try:
            result = await self.db.execute(query, {"identifier": identifier})
            user = result.mappings().first()
        except Exception as exc:
            logger.warning("No se encontró la tabla usuarios; intentando con users: %s", exc)
            table_name = "users"
            query = text("""
                SELECT
                    id,
                    username,
                    email,
                    COALESCE(password_hash, hashed_password) AS password_hash,
                    COALESCE(estado, CASE WHEN is_active THEN 'Activo' ELSE 'Inactivo' END) AS estado,
                    COALESCE(intentos_fallidos, 0) AS intentos_fallidos,
                    bloqueado_hasta,
                    is_active,
                    role_id
                FROM users
                WHERE LOWER(username) = LOWER(:identifier)
                   OR LOWER(email) = LOWER(:identifier)
                LIMIT 1;
            """)
            result = await self.db.execute(query, {"identifier": identifier})
            user = result.mappings().first()

        if not user:
            await self._log_access(None, identifier, client_ip, False, "Usuario no existente")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales inválidas.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        estado = user["estado"] or ("Activo" if user.get("is_active", True) else "Inactivo")
        if not user.get("is_active", True) or estado == "Inactivo":
            await self._log_access(user["id"], user.get("email") or identifier, client_ip, False, "Cuenta inactiva")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="La cuenta se encuentra inactiva. Contacte al administrador.",
            )

        if estado == "Bloqueado":
            bloqueado_hasta = user["bloqueado_hasta"]
            if bloqueado_hasta and bloqueado_hasta > datetime.now(timezone.utc):
                await self._log_access(user["id"], user.get("email") or identifier, client_ip, False, "Intento en cuenta bloqueada")
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="Cuenta bloqueada por seguridad debido a múltiples intentos fallidos.",
                )
            await self.db.execute(
                text(f"UPDATE {table_name} SET estado = 'Activo', intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = :id;"),
                {"id": user["id"]},
            )
            await self.db.commit()

        if not verify_password(password_in, user["password_hash"] or ""):
            nuevos_intentos = int(user["intentos_fallidos"] or 0) + 1
            if nuevos_intentos >= INTENTOS_MAXIMOS:
                tiempo_desbloqueo = datetime.now(timezone.utc) + timedelta(minutes=TIEMPO_BLOQUEO_MINUTOS)
                await self.db.execute(
                    text(f"UPDATE {table_name} SET estado = 'Bloqueado', intentos_fallidos = :intentos, bloqueado_hasta = :bloqueado_hasta WHERE id = :id;"),
                    {
                        "intentos": nuevos_intentos,
                        "bloqueado_hasta": tiempo_desbloqueo,
                        "id": user["id"],
                    },
                )
                await self.db.commit()
                await self._log_access(user["id"], user.get("email") or identifier, client_ip, False, "Bloqueo alcanzado por contraseña errónea")
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="Ha superado el número máximo de intentos fallidos. Su cuenta ha sido bloqueada temporalmente.",
                )

            await self.db.execute(
                text(f"UPDATE {table_name} SET intentos_fallidos = :intentos WHERE id = :id;"),
                {"intentos": nuevos_intentos, "id": user["id"]},
            )
            await self.db.commit()
            await self._log_access(user["id"], user.get("email") or identifier, client_ip, False, "Contraseña errónea")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales inválidas.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        await self.db.execute(
            text(f"UPDATE {table_name} SET estado = 'Activo', intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = :id;"),
            {"id": user["id"]},
        )
        await self.db.commit()
        await self._log_access(user["id"], user.get("email") or identifier, client_ip, True, "Autenticación exitosa")
        return create_access_token(data={"sub": user.get("username") or user.get("email") or identifier, "user_id": user["id"], "role_id": user.get("role_id")})
