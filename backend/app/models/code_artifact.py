from datetime import datetime
from typing import List, Literal

from pydantic import BaseModel, Field


class GeneratedCodeFile(BaseModel):
    file_name: str
    language: Literal["Java"]
    content: str


class GeneratedCodeResponse(BaseModel):
    files: List[GeneratedCodeFile] = Field(min_length=1)


class CodeArtifact(BaseModel):
    artifact_id: str
    project_id: str
    requirement_id: str
    file_name: str
    language: Literal["Java"]
    content: str
    version: int = Field(ge=1)
    source: Literal["AI_GENERATED", "DEVELOPER_EDITED"]
    status: Literal["AI_GENERATED", "EDITED"]
    created_at: datetime
    updated_at: datetime


class CodeArtifactEdit(BaseModel):
    content: str = Field(min_length=1)