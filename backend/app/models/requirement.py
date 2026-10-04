from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class Requirement(BaseModel):
    id: str = Field(alias="_id", default=None)
    projectId: str
    title: str
    description: str
    status: str = "PENDING"
    createdAt: datetime = Field(default_factory=datetime.utcnow)

class RequirementCreate(BaseModel):
    title: str
    description: str
