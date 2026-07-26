from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from core.logger import logger
from core.security import hash_password
from modules.users.user_schema import UserCreate, UserUpdate


class UserService:

  def __init__(self, db: AsyncSession) -> None:
    self.db = db

  async def get_all_users(self) -> list[dict]:
    # Consulta directo a la tabla 'usuario' con sus campos en español
    query = text(
        'SELECT id, nombre, correo, estado, rol FROM usuario ORDER BY id ASC;'
    )
    result = await self.db.execute(query)
    return [dict(row) for row in result.mappings().all()]

  async def create_user(self, user_data: UserCreate) -> dict:
    logger.info(f'SQL Nativo: Registrando usuario {user_data.nombre}')

    dup = await self.db.execute(
        text(
            'SELECT id FROM usuario WHERE nombre = :nombre OR correo = :correo;'
        ),
        {'nombre': user_data.nombre, 'correo': user_data.correo},
    )
    if dup.first():
      raise HTTPException(
          status_code=status.HTTP_400_BAD_REQUEST,
          detail='El usuario o correo ya existen.',
      )

    role_check = await self.db.execute(
        text('SELECT id FROM rol WHERE id = :rol;'), {'rol': user_data.rol}
    )
    if not role_check.first():
      raise HTTPException(
          status_code=status.HTTP_400_BAD_REQUEST,
          detail='El rol proveído no existe.',
      )

    hashed_pwd = hash_password(user_data.contrasena)

    query = text("""
            INSERT INTO usuario (nombre, correo, contrasena, estado, intentos_fallidos, rol)
            VALUES (:nombre, :correo, :contrasena, 'Activo', 0, :rol)
            RETURNING id, nombre, correo, estado, rol;
        """)
    try:
      result = await self.db.execute(
          query,
          {
              'nombre': user_data.nombre,
              'correo': user_data.correo,
              'contrasena': hashed_pwd,
              'rol': user_data.rol,
          },
      )
      await self.db.commit()
      return dict(result.mappings().first())
    except Exception as e:
      await self.db.rollback()
      logger.error(f'Error al guardar usuario: {str(e)}')
      raise HTTPException(
          status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
          detail='Error al crear el usuario.',
      )

  async def update_user(
      self, target_user_id: int, user_update: UserUpdate, current_user: dict
  ) -> dict:
    # Soporta tanto 'nombre' como 'username' para leer el usuario actual
    usuario_actual_nom = current_user.get(
        'nombre'
    ) or current_user.get('username', 'Desconocido')
    logger.info(
        f"Usuario '{usuario_actual_nom}' intenta modificar el usuario ID:"
        f' {target_user_id}'
    )

    if (
        current_user.get('role_name') != 'Administrador'
        and current_user.get('id') != target_user_id
    ):
      raise HTTPException(
          status_code=status.HTTP_403_FORBIDDEN,
          detail=(
              'Permiso denegado. No tienes autorización para modificar datos de'
              ' otros usuarios.'
          ),
      )

    if current_user.get('role_name') != 'Administrador':
      if user_update.rol is not None or user_update.estado is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                'Permiso denegado. Solo un Administrador puede alterar rol o'
                ' estados.'
            ),
        )

    check = await self.db.execute(
        text('SELECT id FROM usuario WHERE id = :id;'), {'id': target_user_id}
    )
    if not check.first():
      raise HTTPException(
          status_code=status.HTTP_404_NOT_FOUND,
          detail='El usuario a modificar no existe.',
      )

    update_fields = []
    params = {'id': target_user_id}

    if user_update.correo is not None:
      dup_email = await self.db.execute(
          text('SELECT id FROM usuario WHERE correo = :correo AND id != :id;'),
          {'correo': user_update.correo, 'id': target_user_id},
      )
      if dup_email.first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='El correo ya está registrado.',
        )
      update_fields.append('correo = :correo')
      params['correo'] = user_update.correo

    if user_update.contrasena is not None:
      update_fields.append('contrasena = :contrasena')
      params['contrasena'] = hash_password(user_update.contrasena)

    if user_update.rol is not None:
      role_exist = await self.db.execute(
          text('SELECT id FROM rol WHERE id = :r_id;'),
          {'r_id': user_update.rol},
      )
      if not role_exist.first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='El rol asignado no existe.',
        )
      update_fields.append('rol = :rol')
      params['rol'] = user_update.rol

    if user_update.estado is not None:
      update_fields.append('estado = :estado')
      params['estado'] = user_update.estado

    if not update_fields:
      raise HTTPException(
          status_code=status.HTTP_400_BAD_REQUEST,
          detail='No se enviaron datos para actualizar.',
      )

    query_str = f"""
            UPDATE usuario 
            SET {', '.join(update_fields)} 
            WHERE id = :id 
            RETURNING id, nombre, correo, estado, rol;
        """

    try:
      result = await self.db.execute(text(query_str), params)
      await self.db.commit()
      return dict(result.mappings().first())
    except Exception as e:
      await self.db.rollback()
      logger.error(f'Error crítico en actualización SQL: {str(e)}')
      raise HTTPException(
          status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
          detail='Error al procesar los datos.',
      )