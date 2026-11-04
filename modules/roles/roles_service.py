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
        query = text("SELECT id_rol, nombre, descripcion FROM rol ORDER BY id_rol ASC;")
        result = await self.db.execute(query)
        return [dict(row) for row in result.mappings().all()]
    
    async def get_role_by_name(self, el_nombre: str) -> List[Dict[str, Any]]:
        logger.info("SQL Nativo: Consultar un rol por su nombre.")
        query = text("SELECT id_rol, nombre, descripcion FROM rol WHERE nombre LIKE :nombre;")
        el_nombre_param = f"%{el_nombre}%"
        result = await self.db.execute(query, {"nombre": el_nombre_param})
        return [dict(row) for row in result.mappings().all()]

    async def get_role_by_id(self, el_id: int) -> Optional[Dict[str, Any]]:
        logger.info("SQL Nativo: Consultar un id con su número.")
        query = text("SELECT id_rol, nombre, descripcion FROM rol WHERE id_rol = :identificacion;")
        result = await self.db.execute(query, {"identificacion": el_id})
        row = result.mappings().first()
        return dict(row) if row else None

    async def create_role(self, role_data: RoleCreate) -> Dict[str, Any]:
        logger.info(f"SQL Nativo: Insertando rol {role_data.nombre}")
        
        check = await self.db.execute(
            text("SELECT id_rol FROM rol WHERE nombre = :nombre;"), 
            {"nombre": role_data.nombre}
        )
        if check.first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="El rol ya existe."
            )

        query = text(
            "INSERT INTO rol (nombre, descripcion) VALUES (:nombre, :descripcion) "
            "RETURNING id_rol, nombre, descripcion;"
        )
        try:
            result = await self.db.execute(
                query, 
                {"nombre": role_data.nombre, "descripcion": role_data.descripcion}
            )
            await self.db.commit()
            
            row = result.mappings().first()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                    detail="No se pudo recuperar el rol creado."
                )
            return dict(row)
        except HTTPException:
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error al insertar rol: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                detail="Error interno del servidor."
            )

    async def delete_role_by_id(self, el_id: int) -> Dict[str, str]:
        logger.info("SQL Nativo: Eliminar rol por id.")
        query_check = text("SELECT id_rol FROM rol WHERE id_rol = :identificacion;")
        check = await self.db.execute(query_check, {"identificacion": el_id})
        if not check.first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="El rol no existe."
            )
        
        query = text("DELETE FROM rol WHERE id_rol = :identy;")
        try:
            await self.db.execute(query, {"identy": el_id})
            await self.db.commit()
            return {"message": f"role {el_id} eliminado con exito."}
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error al eliminar el rol: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                detail="Error al eliminar el rol."
            )
