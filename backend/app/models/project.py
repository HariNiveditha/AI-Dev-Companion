from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class Project(BaseModel):
    id: str = Field(alias="_id", default=None)
    name: str
    description: Optional[str] = None
    language: str
    status: str
    createdAt: datetime = Field(default_factory=datetime.utcnow)

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    language: str
