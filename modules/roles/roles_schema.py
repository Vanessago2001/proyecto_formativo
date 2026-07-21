from pydantic import BaseModel, Field, ConfigDict
from typing import Optional

class RoleBase(BaseModel):
    name: str = Field(..., min_length=3, max_length=50, description="Nombre del rol")
    description: Optional[str] = Field(None, max_length=200)

class RoleCreate(RoleBase):
    pass

class RoleResponse(RoleBase):
    id: int

    model_config = ConfigDict(from_attributes=True)