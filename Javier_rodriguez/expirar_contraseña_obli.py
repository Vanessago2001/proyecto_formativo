#VALIDAR CORREO

# from pydantic import BaseModel, EmailStr

# class UsuarioCreate(BaseModel):
#     correo: EmailStr
#     password: str
    
    
    
#Esto va en el enpoint de registro
# usuario = db.query(Usuario).filter(
#     Usuario.correo == datos.correo
# ).first()

# if usuario:
#     raise HTTPException(
#         status_code=400,
#         detail="El correo ya está registrado"
#     )



#VALIDAR TOKEN DE RECUPERACION

#toca crear una tabla en la base de datos para los tokens
# CREATE TABLE password_reset_tokens (
#     id SERIAL PRIMARY KEY,
#     usuario_id INTEGER NOT NULL REFERENCES usuario(id),
#     token VARCHAR(255) UNIQUE NOT NULL,
#     fecha_expiracion TIMESTAMP NOT NULL,
#     utilizado BOOLEAN DEFAULT FALSE
# );
#Agregar un método en auth_service.py
# import secrets
# from datetime import datetime, timedelta
# from sqlalchemy import text

# async def solicitar_recuperacion(self, correo: str):

#     usuario = await self.db.execute(
#         text("""
#             SELECT id, correo
#             FROM usuario
#             WHERE correo=:correo
#         """),
#         {"correo": correo}
#     )

#     usuario = usuario.mappings().first()

#     if not usuario:
#         return

#     token = secrets.token_urlsafe(32)

#     expiracion = datetime.utcnow() + timedelta(minutes=30)

#     await self.db.execute(
#         text("""
#             INSERT INTO password_reset_tokens
#             (
#                 usuario_id,
#                 token,
#                 fecha_expiracion
#             )

#             VALUES
#             (
#                 :usuario_id,
#                 :token,
#                 :fecha
#             )
#         """),
#         {
#             "usuario_id": usuario["id"],
#             "token": token,
#             "fecha": expiracion
#         }
#     )

#     await self.db.commit()

#     return token

#crear un endpoint 
#agregar un modelo

#class RecuperarPassword(BaseModel):

    #correo:str

#despues agregar un endpoimnt
# @router.post("/forgot-password")
# async def forgot_password(
#     data: RecuperarPassword,
#     db: AsyncSession = Depends(get_db)
# ):

#     service = AuthService(db)

#     token = await service.solicitar_recuperacion(data.correo)

#     return {
#         "mensaje":"Si el correo existe, se enviará un enlace.",
#         "token":token
#     }


#crear otro metodo en autservice
# async def validar_token(self, token:str):

#     resultado = await self.db.execute(
#         text("""
#             SELECT *

#             FROM password_reset_tokens

#             WHERE token=:token
#         """),
#         {
#             "token":token
#         }
#     )

#     registro = resultado.mappings().first()

#     if not registro:

#         raise HTTPException(
#             status_code=400,
#             detail="Token inválido"
#         )

#     if registro["utilizado"]:

#         raise HTTPException(
#             status_code=400,
#             detail="Token ya utilizado"
#         )

#     if registro["fecha_expiracion"] < datetime.utcnow():

#         raise HTTPException(
#             status_code=400,
#             detail="Token expirado"
#         )

#     return registro



# En modules/auth/auth_router.py agrega:

# from pydantic import BaseModel

# class ResetPasswordRequest(BaseModel):
#     token: str
#     nueva_password: str

# En el mismo archivo agrega:

# @router.post("/reset-password")
# async def reset_password(
#     data: ResetPasswordRequest,
#     db: AsyncSession = Depends(get_db)
# ):

#     service = AuthService(db)

#     await service.reset_password(
#         data.token,
#         data.nueva_password
#     )

#     return {
#         "mensaje": "Contraseña actualizada correctamente"
#     }


#En modules/auth/auth_service.py agrega este método:

# from datetime import datetime
# from sqlalchemy import text
# from fastapi import HTTPException

# async def reset_password(self, token: str, nueva_password: str):

#     registro = await self.validar_token(token)

#     usuario_id = registro["usuario_id"]

#     # Aquí debes encriptar la contraseña si tu proyecto ya lo hace
#     password_hash = self.hash_password(nueva_password)

#     await self.db.execute(
#         text("""
#             UPDATE usuario
#             SET password_hash = :password
#             WHERE id = :id
#         """),
#         {
#             "password": password_hash,
#             "id": usuario_id
#         }
#     )

#     await self.db.execute(
#         text("""
#             UPDATE password_reset_tokens
#             SET utilizado = TRUE
#             WHERE id = :id
#         """),
#         {
#             "id": registro["id"]
#         }
#     )

#     await self.db.commit()


#expirar contraseña obligatoriamente
# Agregar un campo en la tabla usuario
# Debes guardar la fecha en la que vence la contraseña.
# Ejecuta este SQL en PostgreSQL:
# ALTER TABLE usuario
# ADD COLUMN password_expira TIMESTAMP;

# Cuando un usuario se registra, además de guardar la contraseña, guarda la fecha en que expirará.
# from datetime import datetime, timedelta
# password_expira = datetime.utcnow() + timedelta(days=90)

# En el INSERT del usuario agrega ese campo:

# INSERT INTO usuario (
#     correo,
#     password_hash,
#     password_expira
# )
# VALUES (
#     :correo,
#     :password,
#     :password_expira
# )

# . Revisar la fecha al iniciar sesión
# En tu proyecto busca el método donde haces el login (en AuthService.login()).
# Después de comprobar que el usuario existe y que la contraseña es correcta, agrega esta validación:

# from datetime import datetime

# if usuario["password_expira"] < datetime.utcnow():
#     raise HTTPException(
#         status_code=403,
#         detail="Su contraseña ha expirado. Debe cambiarla."
#     )

# Crear el modelo de entrada

# Abre:

# modules/auth/auth_router.py
# Agrega este modelo (si no tienes uno parecido):

# from pydantic import BaseModel

# class CambiarPasswordRequest(BaseModel):
#     password_actual: str
#     password_nueva: str

# Crear el endpoint

# En el mismo archivo agrega:

# @router.post("/cambiar-password")
# async def cambiar_password(
#     data: CambiarPasswordRequest,
#     usuario_actual = Depends(obtener_usuario_actual),
#     db: AsyncSession = Depends(get_db)
# ):

#     service = AuthService(db)

#     await service.cambiar_password(
#         usuario_actual["id"],
#         data.password_actual,
#         data.password_nueva
#     )

#     return {
#         "mensaje": "Contraseña actualizada correctamente"
#     }

# Crear el método en auth_service.py

# Abre:

# modules/auth/auth_service.py

# Agrega un método como este:

# from datetime import datetime, timedelta
# from fastapi import HTTPException
# from sqlalchemy import text

# async def cambiar_password(
#     self,
#     usuario_id: int,
#     password_actual: str,
#     password_nueva: str
# ):

# Buscar el usuario

# Dentro del método:

# resultado = await self.db.execute(
#     text("""
#         SELECT id,
#                password_hash
#         FROM usuario
#         WHERE id = :id
#     """),
#     {
#         "id": usuario_id
#     }
# )

# usuario = resultado.mappings().first()

# Verificar la contraseña actual

# Aquí debes usar la misma función que ya utiliza tu login para comparar la contraseña.

# Algo parecido a:

# if not verificar_password(
#     password_actual,
#     usuario["password_hash"]
# ):
#     raise HTTPException(
#         status_code=400,
#         detail="La contraseña actual es incorrecta."
#     )

# Actualizar la base de datos
# nueva_fecha = datetime.utcnow() + timedelta(days=90)

# await self.db.execute(
#     text("""
#         UPDATE usuario
#         SET
#             password_hash = :password,
#             password_expira = :fecha
#         WHERE id = :id
#     """),
#     {
#         "password": password_hash,
#         "fecha": nueva_fecha,
#         "id": usuario_id
#     }
# )

# await self.db.commit()