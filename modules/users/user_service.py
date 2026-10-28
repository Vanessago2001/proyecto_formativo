from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from core.logger import logger
from core.security import hash_password, validar_password_segura
from modules.auditores_registrados.auditores_registrados_service import (
    AuditoresRegistradosService,
)
from modules.users.user_schema import UserCreate, UserUpdate

class UserService:

  def __init__(self, db: AsyncSession) -> None:
    self.db = db

  async def get_all_users(self) -> list[dict]:
    # Consulta con JOIN a rol para obtener el nombre del rol
    query = text("""
        SELECT u.id_usuario, u.nombre, u.correo, u.estado, u.rol_id, u.tipo_doc, u.num_doc,
               r.nombre AS rol_nombre
        FROM usuario u
        LEFT JOIN rol r ON u.rol_id = r.id_rol
        ORDER BY u.id_usuario ASC;
    """)
    result = await self.db.execute(query)
    rows = result.mappings().all()
    return [{k: v for k, v in row.items()} for row in rows]

  async def create_user(self, user_data: UserCreate) -> dict:
    logger.info(f'SQL Nativo: Registrando usuario {user_data.nombre}')

    dup = await self.db.execute(
        text(
            'SELECT id_usuario FROM usuario '
            'WHERE nombre = :nombre OR LOWER(correo) = LOWER(:correo);'
        ),
        {'nombre': user_data.nombre, 'correo': user_data.correo},
    )
    if dup.first():
      raise HTTPException(
          status_code=status.HTTP_400_BAD_REQUEST,
          detail='El usuario o correo ya existen.',
      )

    # num_doc tiene restricción UNIQUE; sin esta verificación el INSERT fallaba
    # con un 500 genérico al repetir una cédula o un NIT.
    dup_doc = await self.db.execute(
        text('SELECT id_usuario FROM usuario WHERE num_doc = :num_doc;'),
        {'num_doc': user_data.num_doc},
    )
    if dup_doc.first():
      raise HTTPException(
          status_code=status.HTTP_400_BAD_REQUEST,
          detail='El número de documento ya está registrado.',
      )

    role_check = await self.db.execute(
        text('SELECT id_rol FROM rol WHERE id_rol = :rol;'), {'rol': user_data.rol}
    )
    if not role_check.first():
      raise HTTPException(
          status_code=status.HTTP_400_BAD_REQUEST,
          detail='El rol proveído no existe.',
      )

    password = user_data.contrasena

    valida, mensaje = validar_password_segura(password)

    if not valida:
      raise HTTPException(
          status_code=400,
          detail=mensaje
      )

    hashed_pwd = hash_password(password)

    query = text("""
            INSERT INTO usuario (id_usuario, nombre, correo, contrasena, estado, intentos_fallidos, rol_id, tipo_doc, num_doc)
            VALUES (gen_random_uuid(), :nombre, :correo, :contrasena, 'Activo', 0, :rol, :tipo_doc, :num_doc)
            RETURNING id_usuario, nombre, correo, estado, rol_id, tipo_doc, num_doc;
        """)
    try:
      result = await self.db.execute(
          query,
          {
              'nombre': user_data.nombre,
              'correo': user_data.correo,
              'contrasena': hashed_pwd,
              'rol': user_data.rol,
              'tipo_doc': user_data.tipo_doc,
              'num_doc': user_data.num_doc,
          },
      )
      await self.db.commit()
      row = result.mappings().first()
      return {k: v for k, v in row.items()} if row else {}
    except IntegrityError as e:
      await self.db.rollback()
      detalle = str(getattr(e, 'orig', e))
      logger.warning('Registro rechazado por restricción única: %s', detalle)
      if 'uq_usuario_num_doc' in detalle:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='El número de documento ya está registrado.',
        )
      if 'usuario_correo_key' in detalle:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='El correo ya está registrado.',
        )
      raise HTTPException(
          status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
          detail='Error al crear el usuario.',
      )
    except Exception as e:
      await self.db.rollback()
      logger.exception(f'Error al guardar usuario: {str(e)}')
      raise HTTPException(
          status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
          detail='Error al crear el usuario.',
      )

  async def update_user(
      self, target_user_id: str, user_update: UserUpdate, current_user: dict
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
        text('SELECT id_usuario FROM usuario WHERE id_usuario = :id_usuario;'),
        {'id_usuario': target_user_id},
    )
    if not check.first():
      raise HTTPException(
          status_code=status.HTTP_404_NOT_FOUND,
          detail='El usuario a modificar no existe.',
      )

    rol_result = await self.db.execute(
        text(
            """
            SELECT r.nombre AS rol
            FROM usuario u
            LEFT JOIN rol r ON r.id_rol = u.rol_id
            WHERE u.id_usuario = :id_usuario
            LIMIT 1
            """
        ),
        {"id_usuario": target_user_id},
    )
    rol_fila = rol_result.mappings().first()
    es_auditor = (
        rol_fila is not None
        and str(rol_fila.get("rol") or "").strip().lower() == "auditor"
    )

    estado_gestionado_por_auditor = False
    if es_auditor and user_update.estado in ("Activo", "Inactivo"):
        actor = (
            current_user.get("id_usuario")
            or current_user.get("id")
            or current_user.get("user_id")
        )
        actor_uuid = None
        if actor is not None:
            try:
                actor_uuid = UUID(str(actor))
            except (TypeError, ValueError):
                actor_uuid = None
        await AuditoresRegistradosService(self.db).cambiar_estado(
            UUID(str(target_user_id)),
            user_update.estado,
            id_usuario_actor=actor_uuid,
        )
        estado_gestionado_por_auditor = True
        user_update = user_update.model_copy(update={"estado": None})

    update_fields: list[str] = []
    params: dict[str, object] = {'id_usuario': target_user_id}

    if user_update.correo is not None:
      dup_email = await self.db.execute(
          text(
              'SELECT id_usuario FROM usuario '
              'WHERE correo = :correo AND id_usuario != :id_usuario;'
          ),
          {'correo': user_update.correo, 'id_usuario': target_user_id},
      )
      if dup_email.first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='El correo ya está registrado.',
        )
      update_fields.append('correo = :correo')
      params['correo'] = user_update.correo

    if user_update.contrasena is not None:
      password = user_update.contrasena
      
      valida, mensaje = validar_password_segura(password)
      
      if not valida:
        raise HTTPException(
            status_code=400,
            detail=mensaje
          )
      update_fields.append('contrasena = :contrasena')
      params['contrasena'] = hash_password(password)

    if user_update.rol is not None:
      role_exist = await self.db.execute(
          text('SELECT id_rol FROM rol WHERE id_rol = :r_id;'),
          {'r_id': user_update.rol},
      )
      if not role_exist.first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='El rol asignado no existe.',
        )
      update_fields.append('rol_id = :rol')
      params['rol'] = user_update.rol

    if user_update.estado is not None and not estado_gestionado_por_auditor:
      update_fields.append('estado = :estado')
      params['estado'] = user_update.estado

    if user_update.tipo_doc is not None:
      update_fields.append('tipo_doc = :tipo_doc')
      params['tipo_doc'] = user_update.tipo_doc

    if user_update.num_doc is not None:
      update_fields.append('num_doc = :num_doc')
      params['num_doc'] = user_update.num_doc

    if not update_fields:
      if estado_gestionado_por_auditor:
        result = await self.db.execute(
            text(
                """
                SELECT id_usuario, nombre, correo, estado, rol_id, tipo_doc, num_doc
                FROM usuario
                WHERE id_usuario = :id_usuario
                """
            ),
            {'id_usuario': target_user_id},
        )
        row = result.mappings().first()
        return {k: v for k, v in row.items()} if row else {}
      raise HTTPException(
          status_code=status.HTTP_400_BAD_REQUEST,
          detail='No se enviaron datos para actualizar.',
      )

    query_str = f"""
            UPDATE usuario 
            SET {', '.join(update_fields)} 
            WHERE id_usuario = :id_usuario 
            RETURNING id_usuario, nombre, correo, estado, rol_id, tipo_doc, num_doc;
        """

    try:
      result = await self.db.execute(text(query_str), params)
      await self.db.commit()
      row = result.mappings().first()
      return {k: v for k, v in row.items()} if row else {}
    except Exception as e:
      await self.db.rollback()
      logger.error(f'Error crítico en actualización SQL: {str(e)}')
      raise HTTPException(
          status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
          detail='Error al procesar los datos.',
      )