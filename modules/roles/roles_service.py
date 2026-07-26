from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from modules.roles.roles_schema import RoleCreate
from core.logger import logger
from typing import List, Dict, Any, Optional

class rolervice:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all_rol(self) -> List[Dict[str, Any]]:
        logger.info("SQL Nativo: Consultando todos los rol.")
        query = text("SELECT id, name, description FROM rol ORDER BY id ASC;")
        result = await self.db.execute(query)
        # Usamos row._asdict() o mapeo explícito para que Pylance reconozca el formato dict
        return [dict(row) for row in result.mappings().all()]
    
    async def get_role_by_name(self, el_nombre: str) -> List[Dict[str, Any]]:
        logger.info("SQL Nativo: Consultar un rol por su nombre.")
        query = text("SELECT id, name, description FROM rol WHERE name LIKE :nombre;")
        el_nombre_param = f"%{el_nombre}%"
        result = await self.db.execute(query, {"nombre": el_nombre_param})
        return [dict(row) for row in result.mappings().all()]

    async def get_role_by_id(self, el_id: int) -> Optional[Dict[str, Any]]:
        logger.info("SQL Nativo: Consultar un id con su número.")
        query = text("SELECT id, name, description FROM rol WHERE id = :identificacion;")
        result = await self.db.execute(query, {"identificacion": el_id})
        row = result.mappings().first()
        # Si existe el rol lo devuelve como dict, si no, devuelve None
        return dict(row) if row else None

    async def create_role(self, role_data: RoleCreate) -> Dict[str, Any]:
        logger.info(f"SQL Nativo: Insertando rol {role_data.name}")
        
        check = await self.db.execute(text("SELECT id FROM rol WHERE name = :name;"), {"name": role_data.name})
        if check.first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El rol ya existe.")

        query = text("INSERT INTO rol (name, description) VALUES (:name, :description) RETURNING id, name, description;")
        try:
            result = await self.db.execute(query, {"name": role_data.name, "description": role_data.description})
            await self.db.commit()
            
            row = result.mappings().first()
            if not row:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No se pudo recuperar el rol creado.")
            return dict(row)
        except HTTPException:
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error al insertar rol: {str(e)}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno del servidor.")

    async def delete_role_by_id(self, el_id: int) -> Dict[str, str]:
        logger.info("SQL Nativo: Consultar un id con su número.")
        query_check = text("SELECT id FROM rol WHERE id = :identificacion;")
        check = await self.db.execute(query_check, {"identificacion": el_id})
        if not check.first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El rol no existe.")
        
        query = text("DELETE FROM rol WHERE id = :identy;")
        try:
            await self.db.execute(query, {"identy": el_id})
            await self.db.commit()
            return {"message": f"role {el_id} eliminado con exito."} # Corregido typo 'messange'
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error al eliminar el rol: {str(e)}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error al eliminar el rol.")