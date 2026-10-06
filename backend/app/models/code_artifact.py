from datetime import datetime
from typing import List, Literal, Optional

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


class CompileResult(BaseModel):
    artifact_id: str
    status: Literal["PASSED", "FAILED", "TOOL_ERROR"]
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = Field(ge=0)
    timestamp: datetime


class AnalysisFinding(BaseModel):
    tool: Literal["Checkstyle", "SpotBugs", "Semgrep"]
    severity: str
    file: str
    line: Optional[int] = None
    column: Optional[int] = None
    rule: Optional[str] = None
    message: str


class AnalysisToolResult(BaseModel):
    status: Literal["COMPLETED", "UNAVAILABLE", "NOT_RUN", "FAILED"]
    findings: List[AnalysisFinding] = []


class StaticAnalysisResult(BaseModel):
    analysis_id: str
    artifact_id: str
    status: Literal["COMPLETED", "PARTIAL", "TOOL_ERROR"]
    checkstyle: AnalysisToolResult
    spotbugs: AnalysisToolResult
    security: AnalysisToolResult
    created_at: datetime