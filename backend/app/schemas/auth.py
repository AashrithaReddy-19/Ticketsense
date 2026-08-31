from uuid import UUID

from pydantic import BaseModel, EmailStr


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str


class UserPublic(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    department_id: UUID | None
    tenant_id: UUID | None
    permissions: list[str] = []

    model_config = {"from_attributes": True}
