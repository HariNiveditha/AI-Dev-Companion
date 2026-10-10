import os
import shutil
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.db.mongodb import get_db
from app.models.execution import CodeArtifactVersionReference, ExecutionRun, ExecutionTestResult, StartExecutionRequest

router = APIRouter()


def _secure_execution_available() -> bool:
    enabled = os.getenv("ENABLE_JAVA_EXECUTION", "false").lower() == "true"
    sandbox = shutil.which("docker") or shutil.which("podman")
    return enabled and bool(sandbox)


@router.post("/requirements/{requirement_id}/executions", response_model=ExecutionRun)
async def start_execution(requirement_id: str, payload: StartExecutionRequest):
    db = get_db()
    requirement = await db.requirements.find_one({"_id": requirement_id})
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    artifact = await db.code_artifacts.find_one({"artifact_id": payload.artifact_id})
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.get("requirement_id") != requirement_id:
        raise HTTPException(status_code=400, detail="Artifact does not belong to the selected requirement")

    artifact_reference = CodeArtifactVersionReference(
        artifact_id=artifact["artifact_id"],
        project_id=artifact["project_id"],
        requirement_id=artifact["requirement_id"],
        file_name=artifact["file_name"],
        version=artifact["version"],
        source=artifact.get("source"),
    )

    execution_id = str(uuid.uuid4())
    now = datetime.utcnow()
    status = "PENDING"
    error_message = None
    if not _secure_execution_available():
        status = "DISABLED"
        error_message = "Java/JUnit execution is disabled until a secure sandbox with Docker or Podman is configured."

    execution = ExecutionRun(
        execution_id=execution_id,
        requirement_id=requirement_id,
        project_id=requirement["projectId"],
        artifact=artifact_reference,
        status=status,
        created_at=now,
        updated_at=now,
        test_results=[],
        error_message=error_message,
    )

    await db.executions.insert_one(execution.model_dump(mode="json"))
    return execution


@router.get("/requirements/{requirement_id}/executions", response_model=list[ExecutionRun])
async def get_requirement_executions(requirement_id: str):
    db = get_db()
    requirement = await db.requirements.find_one({"_id": requirement_id})
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    runs = await db.executions.find({"requirement_id": requirement_id}).sort([("created_at", -1)]).to_list(1000)
    return [ExecutionRun.model_validate(run) for run in runs]


@router.get("/executions/{execution_id}", response_model=ExecutionRun)
async def get_execution(execution_id: str):
    db = get_db()
    execution = await db.executions.find_one({"execution_id": execution_id})
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return ExecutionRun.model_validate(execution)


@router.get("/executions/{execution_id}/results", response_model=list[ExecutionTestResult])
async def get_execution_results(execution_id: str):
    db = get_db()
    execution = await db.executions.find_one({"execution_id": execution_id})
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return [ExecutionTestResult.model_validate(result) for result in execution.get("test_results", [])]
