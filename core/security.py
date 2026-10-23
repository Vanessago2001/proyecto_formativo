
from fastapi import Depends, HTTPException, status
import bcrypt
import jwt
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from core.config import settings
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from typing import Any
from typing import Callable, List
import uuid
import jwt
import re
 

def validar_password_segura(password: str) -> tuple[bool, str]:
    """Verifica la creación de contraseña segura."""
    if not password:
        return False, "La contraseña es obligatoria."
    if len(password) < 8:
        return False, "La contraseña contener 8 caracteres, una mayuscula, una minuscula, un numero y un caracter especial."
    if not re.search(r"[A-Z]", password):
        return False, "La contraseña contener 8 caracteres, una mayuscula, una minuscula, un numero y un caracter especial."
    if not re.search(r"[a-z]", password):
        return False, "La contraseña contener 8 caracteres, una mayuscula, una minuscula, un numero y un caracter especial."
    if not re.search(r"\d", password):
        return False, "La contraseña contener 8 caracteres, una mayuscula, una minuscula, un numero y un caracter especial."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-]", password):
        return False, "La contraseña contener 8 caracteres, una mayuscula, una minuscula, un numero y un caracter especial."
    return True, ""


def hash_password(password: str) -> str:
    """Usa bcrypt nativo para convertir un texto plano en un hash binario y decodificarlo a string"""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # \"\"\"Compara el texto plano con el hash almacenado en la base de datos transformando ambos a bytes\"\"\"
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def hash_verification_code(codigo: str) -> str:
    """
    Convierte el código de verificación en un hash SHA-256.
    """
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


def verify_verification_code(
    codigo_plano: str,
    codigo_hash: str
) -> bool:
    """
    Compara un código ingresado con el hash almacenado.
    """
    return secrets.compare_digest(
        hashlib.sha256(
            codigo_plano.encode("utf-8")
        ).hexdigest(),
        codigo_hash
    )

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    # Convertimos cualquier UUID a string para evitar errores de JSON serialization
    for key, value in to_encode.items():
        if isinstance(value, uuid.UUID):
            to_encode[key] = str(value)
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

# Define el endpoint donde los aprendices obtienen el token por primera vez
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Dependencia reutilizable que valida el token JWT y extrae la 
    identidad completa del usuario directamente desde la base de datos.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudo validar el token de acceso o ha expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Decodificar el token firmado con nuestra firma del .env
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

        username: Any = payload.get("sub")
        user_id: Any = payload.get("user_id")
        
        if username is None or user_id is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
        
    # Consulta SQL Nativa para traer el usuario activo junto con su ROL asignado
    query = text("""
    SELECT
        u.id_usuario,
        u.nombre,
        u.correo,
        u.estado,
        u.rol_id,
        r.nombre AS role_name
    FROM usuario u
    LEFT JOIN rol r
        ON u.rol_id = r.id_rol
    WHERE
        u.id_usuario = :user_id
        AND u.estado = 'Activo';
""")
    
    result = await db.execute(query, {"user_id": user_id})
    user_row = result.mappings().first()
    
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Usuario inexistente o inhabilitado en el sistema."
        )
        
    return dict(user_row)

def _normalize_role_name(role_name: str) -> str:
    if role_name is None:
        return ""

    normalized = role_name.strip().lower()
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ü": "u", "ñ": "n",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)

    normalized = re.sub(r"[\s_\-]+", "", normalized)

    aliases = {
        "superadmin": "superadmin",
        "superadministrador": "superadmin",
        "superadm": "superadmin",
        "adm": "admin",
        "administrador": "admin",
        "admin": "admin",
        "auxiliar": "auxiliar",
        "aux": "auxiliar",
        "empresa": "empresa",
        "empresario": "empresa",
        "auditor": "auditor",
        "aud": "auditor",
        "comite": "comite",
        "instructor": "instructor",
        "aprendiz": "aprendiz",
        "usuario": "usuario",
        "pub": "public",
        "public": "public",
    }
    return aliases.get(normalized, normalized)


def require_role(allowed_roles: List[str]) -> Callable:
    """
    Fábrica de dependencias reutilizable.
    Acepta variaciones de nombre de rol tanto en español como en inglés.
    """
    roles_lower = {_normalize_role_name(role) for role in allowed_roles}

    async def role_dependency(current_user: dict = Depends(get_current_user)) -> dict:
        rol = _normalize_role_name(current_user.get("role_name"))

        if rol not in roles_lower:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No cuenta con los permisos necesarios para realizar esta acción.",
            )
        return current_user

    return role_dependency