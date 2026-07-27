import secrets
import string

class PasswordResetService:
    def __init__(self, db_adapter=None):
        """
        db_adapter: Objeto o función para interactuar con la BD.
        Si es None, usará un diccionario en memoria para pruebas independientes.
        """
        self.db = db_adapter

    def reset_password(self, admin_user: dict, target_user: dict) -> dict:
        """
        Lógica pura para restablecer la contraseña de un usuario por parte de un Admin.
        """
        # 1. Validar permisos del administrador
        if admin_user.get("role") != "ADMIN":
            raise PermissionError("Acceso denegado: Solo administradores pueden realizar esta acción.")

        # 2. Validar que el usuario objetivo exista
        if not target_user:
            raise ValueError("El usuario objetivo no fue encontrado.")

        # 3. Generar nueva contraseña temporal segura (12 caracteres)
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        temp_password = "".join(secrets.choice(alphabet) for _ in range(12))

        # 4. Modificar el objeto del usuario (se simula la actualización del hash)
        target_user["password_hash"] = f"hashed_{temp_password}"
        target_user["must_change_password"] = True

        return {
            "status": "success",
            "message": f"Contraseña restablecida exitosamente para {target_user.get('id')}.",
            "temporary_password": temp_password,
            "updated_user": target_user
        }