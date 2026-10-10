from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CodeArtifactVersionReference(BaseModel):
    artifact_id: str
    project_id: str
    requirement_id: str
    file_name: str
    version: int = Field(ge=1)
    source: Optional[Literal["AI_GENERATED", "DEVELOPER_EDITED"]] = None


class StartExecutionRequest(BaseModel):
    artifact_id: str
    test_case_ids: list[str] = Field(default_factory=list)


class ExecutionTestResult(BaseModel):
    test_id: str
    title: str
    status: Literal["PASSED", "FAILED", "ERROR", "SKIPPED"]
    expected_output: Optional[str] = None
    actual_output: Optional[str] = None
    error_details: Optional[str] = None
    duration_ms: Optional[int] = Field(default=None, ge=0)


class ExecutionRun(BaseModel):
    execution_id: str
    requirement_id: str
    project_id: str
    artifact: CodeArtifactVersionReference
    status: Literal["PENDING", "RUNNING", "PASSED", "FAILED", "ERROR", "SKIPPED", "CANCELLED", "DISABLED"] = "PENDING"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    test_results: list[ExecutionTestResult] = Field(default_factory=list)
    error_message: Optional[str] = None
