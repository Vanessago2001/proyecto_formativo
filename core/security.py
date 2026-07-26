from fastapi import Depends, HTTPException, status
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from core.config import settings
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from typing import Any
import jwt

def hash_password(password: str) -> str:
    """Usa bcrypt nativo para convertir un texto plano en un hash binario y decodificarlo a string"""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # \"\"\"Compara el texto plano con el hash almacenado en la base de datos transformando ambos a bytes\"\"\"
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
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
        SELECT u.id, u.username, u.email, u.is_active, u.role_id, r.name as role_name 
        FROM users u
        INNER JOIN rol r ON u.role_id = r.id
        WHERE u.id = :user_id AND u.is_active = TRUE;
    """)
    
    result = await db.execute(query, {"user_id": user_id})
    user_row = result.mappings().first()
    
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Usuario inexistente o inhabilitado en el sistema."
        )
        
    return dict(user_row)
