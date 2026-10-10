from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DocumentationGenerateRequest(BaseModel):
    project_id: str = Field(min_length=1)
    document_type: Literal[
        "README",
        "JAVA_DOCS",
        "SETUP",
        "API_DOCS",
    ] = "README"


class DocumentationResponse(BaseModel):
    documentation_id: str
    project_id: str
    document_type: str
    title: str
    content: str
    created_at: datetime
    updated_at: datetime


class DocumentationGenerateResponse(BaseModel):
    success: bool
    message: str
    documentation: Optional[DocumentationResponse] = None


class DocumentationRecord(BaseModel):
    documentation_id: str
    project_id: str
    document_type: str
    title: str
    content: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )