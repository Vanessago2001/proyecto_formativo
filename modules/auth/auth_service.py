from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from core.logger import logger
from core.security import create_access_token, verify_password

INTENTOS_MAXIMOS = 5
TIEMPO_BLOQUEO_MINUTOS = 15


class AuthService:

  def __init__(self, db: AsyncSession) -> None:
    self.db = db

  async def _log_access(
      self,
      user_id: str | None,
      correo_intentado: str,
      ip_origen: str,
      exitoso: bool,
      motivo_fallo: str | None,
  ) -> None:
    try:
      await self.db.execute(
          text("""
                CREATE TABLE IF NOT EXISTS logs_acceso (
                    id SERIAL PRIMARY KEY,
                    usuario_id UUID,
                    correo_intentado VARCHAR(255) NOT NULL,
                    ip_origen VARCHAR(45) NOT NULL,
                    exitoso BOOLEAN NOT NULL,
                    motivo_fallo VARCHAR(100),
                    fecha_hora TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
      )
      # Si la tabla ya existía con usuario_id como entero, la alteramos a UUID.
      # Esto es necesario porque CREATE TABLE IF NOT EXISTS no modifica tablas existentes.
      # El try/except separado asegura que si la alteración falla (por ejemplo, si la
      # columna ya es UUID o hay datos incompatibles), el INSERT siga funcionando.
      try:
        await self.db.execute(
            text("""
                ALTER TABLE logs_acceso
                ALTER COLUMN usuario_id TYPE UUID USING usuario_id::TEXT::UUID;
            """)
        )
        await self.db.commit()
      except Exception as alter_exc:
        logger.warning("No fue posible alterar usuario_id a UUID: %s", alter_exc)
        await self.db.rollback()

      # Convertimos el UUID a string para evitar problemas de serialización
      usuario_id_str = str(user_id) if user_id is not None else None
      await self.db.execute(
          text("""
                INSERT INTO logs_acceso (usuario_id, correo_intentado, ip_origen, exitoso, motivo_fallo)
                VALUES (:usuario_id, :correo_intentado, :ip_origen, :exitoso, :motivo_fallo);
            """),
          {
              "usuario_id": usuario_id_str,
              "correo_intentado": correo_intentado,
              "ip_origen": ip_origen or "unknown",
              "exitoso": exitoso,
              "motivo_fallo": motivo_fallo,
          },
      )
      await self.db.commit()
    except Exception as exc:
      logger.exception("No fue posible registrar el log de acceso: %s", exc)
      await self.db.rollback()

  async def login(
      self, correo_in: str, password_in: str, client_ip: str | None = None
  ) -> str:
    client_ip = client_ip or "unknown"
    identifier = correo_in.strip().lower()
    logger.info("SQL Nativo: Intento de login para: %s", identifier)

    query = text("""
            SELECT 
                u.id, 
                u.nombre, 
                u.correo, 
                u.contrasena AS password_hash, 
                u.estado, 
                COALESCE(u.intentos_fallidos, 0) AS intentos_fallidos, 
                u.bloqueado_hasta, 
                u.rol_id,
                r.nombre AS rol_nombre
            FROM usuario u
            LEFT JOIN rol r ON u.rol_id = r.id_rol
            WHERE LOWER(u.correo) = LOWER(:identifier) OR LOWER(u.nombre) = LOWER(:identifier)
            LIMIT 1;
        """)

    result = await self.db.execute(query, {"identifier": identifier})
    user = result.mappings().first()

    # 1. Validación de existencia
    if not user:
      await self._log_access(
          None, identifier, client_ip, False, "Usuario no existente"
      )
      raise HTTPException(
          status_code=status.HTTP_401_UNAUTHORIZED,
          detail="Credenciales inválidas.",
          headers={"WWW-Authenticate": "Bearer"},
      )

    # 2. Validación del estado textual definido por la base de datos.
    estado = user["estado"]
    if estado == "Inactivo":
      await self._log_access(
          user["id"],
          user.get("correo") or identifier,
          client_ip,
          False,
          "Cuenta inactiva",
      )
      raise HTTPException(
          status_code=status.HTTP_403_FORBIDDEN,
          detail=(
              "La cuenta se encuentra inactiva. Contacte al administrador."
          ),
      )

    # 3. Validación de Bloqueo
    bloqueado_hasta = user["bloqueado_hasta"]
    ahora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    if bloqueado_hasta and bloqueado_hasta > ahora_utc:
      await self._log_access(
          user["id"],
          user.get("correo") or identifier,
          client_ip,
          False,
          "Intento en cuenta bloqueada",
      )
      raise HTTPException(
          status_code=status.HTTP_423_LOCKED,
          detail=(
              "Cuenta bloqueada por seguridad debido a múltiples intentos"
              " fallidos."
          ),
      )

    # Si ya pasó el tiempo de bloqueo, lo reactivamos
    if estado == "Bloqueado" and bloqueado_hasta and bloqueado_hasta <= ahora_utc:
      await self.db.execute(
          text(
              "UPDATE usuario SET estado = 'Activo', intentos_fallidos = 0,"
              " bloqueado_hasta = NULL WHERE id = :id;"
          ),
          {"id": user["id"]},
      )
      await self.db.commit()

    # 4. Verificación de Contraseña
    if not verify_password(password_in, user["password_hash"] or ""):
      nuevos_intentos = int(user["intentos_fallidos"] or 0) + 1

      if nuevos_intentos >= INTENTOS_MAXIMOS:
        tiempo_desbloqueo = datetime.utcnow() + timedelta(
            minutes=TIEMPO_BLOQUEO_MINUTOS
        )
        await self.db.execute(
            text("""
                    UPDATE usuario 
                    SET estado = 'Bloqueado', intentos_fallidos = :intentos, bloqueado_hasta = :bloqueado_hasta 
                    WHERE id = :id;
                """),
            {
                "intentos": nuevos_intentos,
                "bloqueado_hasta": tiempo_desbloqueo,
                "id": user["id"],
            },
        )
        await self.db.commit()
        await self._log_access(
            user["id"],
            user.get("correo") or identifier,
            client_ip,
            False,
            "Bloqueo alcanzado por contraseña errónea",
        )
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                "Ha superado el número máximo de intentos fallidos. Su cuenta"
                " ha sido bloqueada temporalmente."
            ),
        )

      await self.db.execute(
          text(
              "UPDATE usuario SET intentos_fallidos = :intentos WHERE id ="
              " :id;"
          ),
          {"intentos": nuevos_intentos, "id": user["id"]},
      )
      await self.db.commit()
      await self._log_access(
          user["id"],
          user.get("correo") or identifier,
          client_ip,
          False,
          "Contraseña errónea",
      )
      raise HTTPException(
          status_code=status.HTTP_401_UNAUTHORIZED,
          detail="Credenciales inválidas.",
          headers={"WWW-Authenticate": "Bearer"},
      )

    # 5. Login exitoso (reseteamos fallos)
    await self.db.execute(
        text(
            "UPDATE usuario SET estado = 'Activo', intentos_fallidos = 0,"
            " bloqueado_hasta = NULL WHERE id = :id;"
        ),
        {"id": user["id"]},
    )
    await self.db.commit()

    await self._log_access(
        user["id"],
        user.get("correo") or identifier,
        client_ip,
        True,
        "Autenticación exitosa",
    )

    # Generación de JWT
    return create_access_token(
        data={
            "sub": user.get("nombre") or user.get("correo") or identifier,
            "user_id": user["id"],
            "role_id": user.get("rol_id"),
            "role_name": user.get("rol_nombre"),
        }
    )
