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
    # Descriptive test cases (Phase 6 records) that this execution is meant to
    # cover. Required and validated against the requirement's own test cases.
    test_case_ids: list[str] = Field(default_factory=list)
    # The executable JUnit 5 test source that implements the requested cases.
    # Required whenever execution is enabled; descriptive test-case records are
    # never executed directly.
    executable_test_id: Optional[str] = None


class ExecutionTestResult(BaseModel):
    test_id: str
    title: str
    status: Literal["PASSED", "FAILED", "ERROR", "SKIPPED"]
    expected_output: Optional[str] = None
    actual_output: Optional[str] = None
    error_details: Optional[str] = None
    duration_ms: Optional[int] = Field(default=None, ge=0)
    # New in Phase 9 real-execution: provenance for each collected result.
    execution_id: Optional[str] = None
    # JUnit method (and class) that produced this result, e.g. "acceptsValidLogin".
    method: Optional[str] = None
    # The descriptive test case this method implements (None for unlinked methods).
    test_case_id: Optional[str] = None


class ExecutionCounts(BaseModel):
    """Aggregates derived exclusively from the validated JUnit XML report."""

    total: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    error: int = Field(default=0, ge=0)


class ExecutionCompileResult(BaseModel):
    """Result of compiling production + test sources inside the runner container."""

    status: Literal["PASSED", "FAILED", "ERROR"]
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
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

    # --- Phase 9 real execution (all optional so legacy documents still validate) ---
    # Test cases the caller requested; validated to belong to this requirement.
    requested_test_case_ids: list[str] = Field(default_factory=list)
    # Exact artifact versions whose sources were compiled and executed.
    source_snapshot: list[CodeArtifactVersionReference] = Field(default_factory=list)
    # Executable JUnit test source that was compiled and run.
    executable_test_id: Optional[str] = None
    executable_test_version: Optional[int] = None
    executable_test_class: Optional[str] = None
    # Counts from the runner's structured report (never guessed).
    counts: ExecutionCounts = Field(default_factory=ExecutionCounts)
    compile_result: Optional[ExecutionCompileResult] = None
    # Runner identity, e.g. "docker image=eclipse-temurin:21-jdk".
    runner: Optional[str] = None
    runner_exit_code: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = Field(default=None, ge=0)
