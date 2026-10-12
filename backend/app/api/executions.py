"""Phase 9 execution endpoints.

Contract summary (see README, Phase 9):

* ``POST /requirements/{rid}/executions`` validates the whole request,
  then creates an execution record that is *never* left in PENDING:
    - execution disabled  -> DISABLED (terminal, persisted)
    - enabled but safe runner unavailable -> ERROR (terminal, persisted)
    - enabled and available -> RUNNING, then the test suite is compiled
      and executed inside a container and the record is updated to
      PASSED/FAILED/ERROR with counts taken from the JUnit XML report.
* Descriptive test cases (Phase 6) are never executed directly; an
  executable JUnit 5 source (``executable_tests`` collection) must be
  selected and must implement every requested test case id.
* Execution history is append-only: every run creates a new document.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.db.mongodb import get_db
from app.models.execution import (
    CodeArtifactVersionReference,
    ExecutionCounts,
    ExecutionRun,
    ExecutionTestResult,
    StartExecutionRequest,
)
from app.models.test_case import (
    ExecutableTest,
    ExecutableTestCreate,
    ExecutableTestGenerateRequest,
)
from app.services.ai.service import generate_executable_test_source
from app.services.execution import runner
from app.services.execution.validation import (
    file_name_for,
    validate_executable_test,
)
from app.services.execution.junit_report import normalize_method_name
from app.services.execution.workspace import derive_class_name

router = APIRouter()

logger = logging.getLogger(__name__)

# Cap for provider diagnostics echoed back to the client: actionable for the
# user, but never a stack trace and never source content (provider errors
# originate from the AI API, not from project sources).

# Single-process duplicate-request guard (requirement_id -> execution_id).
# The database check below covers multi-request races within one process;
# this set closes the gap between the check and the insert.
_IN_FLIGHT: dict[str, str] = {}

_JAVA_FILE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.java$")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _latest_artifacts(artifacts: list[dict]) -> list[dict]:
    latest_by_file: dict[str, dict] = {}
    for artifact in artifacts:
        current = latest_by_file.get(artifact["file_name"])
        if not current or artifact.get("version", 0) > current.get("version", 0):
            latest_by_file[artifact["file_name"]] = artifact
    return list(latest_by_file.values())


def _artifact_reference(artifact: dict) -> CodeArtifactVersionReference:
    return CodeArtifactVersionReference(
        artifact_id=artifact["artifact_id"],
        project_id=artifact["project_id"],
        requirement_id=artifact["requirement_id"],
        file_name=artifact["file_name"],
        version=artifact["version"],
        source=artifact.get("source"),
    )


def _require_executable_test(executable_test: dict) -> tuple[str, str, str, dict]:
    """Validate linkage between the executable test and requested cases.

    Returns (class_name, file_name, content, method_map).
    Raises HTTPException on invalid stored data.
    """
    method_map = executable_test.get("method_map") or {}
    if not isinstance(method_map, dict) or not method_map:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Executable test {executable_test['executable_test_id']} has no "
                "method_map; it does not implement any descriptive test case."
            ),
        )
    class_name = executable_test.get("class_name")
    file_name = executable_test.get("file_name")
    content = executable_test.get("content", "")
    if not class_name or not file_name or not content:
        raise HTTPException(
            status_code=400,
            detail=f"Executable test {executable_test['executable_test_id']} is incomplete.",
        )
    return class_name, file_name, content, method_map


def _assemble_results(
    execution_id: str,
    outcome,
    requested_cases: dict[str, dict],
    method_map: dict[str, str],
    executable_test: dict,
) -> tuple[list[ExecutionTestResult], list[str]]:
    """Map raw JUnit cases onto the requested descriptive test cases.

    Returns (results, missing_case_ids).
    """
    case_by_method = {method: case_id for case_id, method in method_map.items()}
    seen_methods: set[str] = set()
    results: list[ExecutionTestResult] = []

    for raw in outcome.raw_cases:
        # JUnit reports "acceptsValidLogin()"; method_map holds "acceptsValidLogin".
        normalized = normalize_method_name(raw.name)
        case_id = case_by_method.get(normalized)
        case = requested_cases.get(case_id) if case_id else None
        seen_methods.add(normalized)
        details = None
        if raw.status in ("FAILED", "ERROR"):
            parts = [part for part in (raw.message, raw.stacktrace) if part]
            details = "\n".join(parts) if parts else f"JUnit method ended with status {raw.status}."
        results.append(
            ExecutionTestResult(
                test_id=case_id or f"{raw.classname}#{raw.name}",
                title=case["title"] if case else f"{raw.classname}#{raw.name}",
                status=raw.status,
                expected_output=case.get("expected_output") if case else None,
                actual_output=None,
                error_details=details,
                duration_ms=raw.duration_ms,
                execution_id=execution_id,
                method=raw.name,
                test_case_id=case_id,
            )
        )

    missing = [
        case_id
        for case_id, method in method_map.items()
        if method not in seen_methods
    ]
    return results, missing


async def _persist_terminal(execution_id: str, **fields) -> dict:
    db = get_db()
    fields["updated_at"] = datetime.utcnow()
    await db.executions.update_one(
        {"execution_id": execution_id}, {"$set": fields}
    )
    updated = await db.executions.find_one({"execution_id": execution_id})
    return updated


# ---------------------------------------------------------------------------
# Startup reconciliation: no run may survive a restart as PENDING/RUNNING.
# ---------------------------------------------------------------------------

async def reconcile_interrupted_executions() -> int:
    db = get_db()
    result = await db.executions.update_many(
        {"status": {"$in": ["PENDING", "RUNNING"]}},
        {
            "$set": {
                "status": "ERROR",
                "error_message": (
                    "Execution was interrupted (backend restart or crash) "
                    "before results were collected."
                ),
                "updated_at": datetime.utcnow(),
            }
        },
    )
    return getattr(result, "modified_count", 0)


# ---------------------------------------------------------------------------
# Execution lifecycle
# ---------------------------------------------------------------------------

@router.post("/requirements/{requirement_id}/executions", response_model=ExecutionRun)
async def start_execution(requirement_id: str, payload: StartExecutionRequest):
    db = get_db()

    # --- existence and ownership checks (explicit failures, no record) ---
    requirement = await db.requirements.find_one({"_id": requirement_id})
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    artifact = await db.code_artifacts.find_one({"artifact_id": payload.artifact_id})
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if artifact.get("requirement_id") != requirement_id:
        raise HTTPException(status_code=400, detail="Artifact does not belong to the selected requirement")

    # --- requested test cases: required, unique, and owned by the requirement ---
    requested_ids = [str(case_id) for case_id in payload.test_case_ids]
    if not requested_ids:
        raise HTTPException(
            status_code=400,
            detail="test_case_ids must contain at least one test case id.",
        )
    if len(set(requested_ids)) != len(requested_ids):
        raise HTTPException(
            status_code=400,
            detail="test_case_ids contains duplicate ids.",
        )

    owned_cases = await db.test_cases.find(
        {"requirement_id": requirement_id}
    ).to_list(10000)
    owned_by_id = {str(case["test_case_id"]): case for case in owned_cases}
    unknown = [case_id for case_id in requested_ids if case_id not in owned_by_id]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown or foreign test case id(s) for this requirement: "
                f"{', '.join(unknown)}. Test cases must belong to requirement "
                f"{requirement_id}."
            ),
        )
    requested_cases = {case_id: owned_by_id[case_id] for case_id in requested_ids}

    # --- executable test: required whenever execution can run ---
    availability = runner.check_availability()

    executable_test = None
    method_map: dict = {}
    if payload.executable_test_id:
        executable_test = await db.executable_tests.find_one(
            {"executable_test_id": payload.executable_test_id}
        )
        if not executable_test:
            raise HTTPException(status_code=404, detail="Executable test not found")
        if executable_test.get("requirement_id") != requirement_id:
            raise HTTPException(
                status_code=400,
                detail="Executable test does not belong to the selected requirement",
            )
        class_name, file_name, content, method_map = _require_executable_test(executable_test)
        unlinked = [case_id for case_id in requested_ids if case_id not in method_map]
        if unlinked:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Executable test does not implement the following requested "
                    f"test case id(s): {', '.join(unlinked)}. Its method_map must "
                    "contain every requested test case id."
                ),
            )
    elif availability.available:
        raise HTTPException(
            status_code=400,
            detail=(
                "No executable test selected. Descriptive test cases are not "
                "executable Java code; select or generate an executable JUnit 5 "
                "test (POST /requirements/{rid}/executable-tests) and pass its "
                "executable_test_id."
            ),
        )

    # --- duplicate-request guard ---
    in_flight = _IN_FLIGHT.get(requirement_id)
    if in_flight:
        raise HTTPException(
            status_code=409,
            detail=f"An execution ({in_flight}) is already in progress for this requirement.",
        )
    running = await db.executions.find_one(
        {"requirement_id": requirement_id, "status": {"$in": ["PENDING", "RUNNING"]}}
    )
    if running:
        raise HTTPException(
            status_code=409,
            detail=(
                f"An execution ({running['execution_id']}) is already in progress "
                "for this requirement."
            ),
        )

    # --- source snapshot: latest version of every Java file of the requirement ---
    related = await db.code_artifacts.find(
        {"project_id": requirement["projectId"], "requirement_id": requirement_id, "language": "Java"}
    ).to_list(1000)
    latest_docs = _latest_artifacts(related)
    if not latest_docs:
        raise HTTPException(
            status_code=400,
            detail="No Java source artifacts exist for this requirement yet.",
        )
    snapshot = [_artifact_reference(item) for item in latest_docs]

    execution_id = str(uuid.uuid4())
    now = datetime.utcnow()

    # --- disabled: terminal record, honest message ---
    if not availability.available:
        execution = ExecutionRun(
            execution_id=execution_id,
            requirement_id=requirement_id,
            project_id=requirement["projectId"],
            artifact=_artifact_reference(artifact),
            status="DISABLED",
            created_at=now,
            updated_at=now,
            requested_test_case_ids=requested_ids,
            source_snapshot=snapshot,
            executable_test_id=payload.executable_test_id,
            error_message=availability.reason,
        )
        await db.executions.insert_one(execution.model_dump(mode="json"))
        return execution

    # --- enabled but safe runner unavailable: terminal ERROR record ---
    if not executable_test:
        # Availability was re-checked; defensive, should not happen.
        raise HTTPException(status_code=400, detail="No executable test selected.")

    execution = ExecutionRun(
        execution_id=execution_id,
        requirement_id=requirement_id,
        project_id=requirement["projectId"],
        artifact=_artifact_reference(artifact),
        status="RUNNING",
        created_at=now,
        updated_at=now,
        requested_test_case_ids=requested_ids,
        source_snapshot=snapshot,
        executable_test_id=executable_test["executable_test_id"],
        executable_test_version=executable_test.get("version"),
        executable_test_class=executable_test.get("class_name"),
        runner=availability.runner_label,
        started_at=now,
    )
    await db.executions.insert_one(execution.model_dump(mode="json"))
    _IN_FLIGHT[requirement_id] = execution_id

    try:
        try:
            outcome = await asyncio.to_thread(
                runner.execute,
                execution_id,
                latest_docs,
                content,
                file_name,
            )
        except runner.RunnerUnavailableError as exc:
            outcome_status = "ERROR"
            outcome_counts = ExecutionCounts()
            outcome_results: list[ExecutionTestResult] = []
            outcome_compile = None
            outcome_error = str(exc)
            outcome_exit = None
            missing: list[str] = []
        except Exception as exc:  # unexpected runner failure: fail closed
            outcome_status = "ERROR"
            outcome_counts = ExecutionCounts()
            outcome_results = []
            outcome_compile = None
            outcome_error = (
                f"Unexpected runner failure ({type(exc).__name__}): {exc}"
            )
            outcome_exit = None
            missing = []
        else:
            outcome_results, missing = _assemble_results(
                execution_id, outcome, requested_cases, method_map, executable_test
            )
            outcome_status = outcome.status
            outcome_counts = outcome.counts
            outcome_compile = outcome.compile_result
            outcome_error = outcome.error_message
            outcome_exit = outcome.runner_exit_code

            if missing and outcome_status in ("PASSED", "FAILED"):
                # The report did not cover every requested case: we cannot
                # confirm what happened to it, so the run is not trustworthy.
                outcome_status = "ERROR"
                outcome_error = (
                    "The runner report did not include JUnit methods for "
                    f"requested test case id(s): {', '.join(missing)}."
                )

        completed = datetime.utcnow()
        duration_ms = round((completed - now).total_seconds() * 1000)
        await _persist_terminal(
            execution_id,
            status=outcome_status,
            test_results=[result.model_dump(mode="json") for result in outcome_results],
            counts=outcome_counts.model_dump(mode="json"),
            compile_result=outcome_compile.model_dump(mode="json") if outcome_compile else None,
            runner_exit_code=outcome_exit,
            completed_at=completed,
            duration_ms=duration_ms,
            error_message=outcome_error,
        )
    finally:
        _IN_FLIGHT.pop(requirement_id, None)

    updated = await db.executions.find_one({"execution_id": execution_id})
    return ExecutionRun.model_validate(updated)


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


# ---------------------------------------------------------------------------
# Executable tests (JUnit 5 sources that implement descriptive cases)
# ---------------------------------------------------------------------------

@router.get("/requirements/{requirement_id}/executable-tests", response_model=list[ExecutableTest])
async def list_executable_tests(requirement_id: str):
    db = get_db()
    requirement = await db.requirements.find_one({"_id": requirement_id})
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    tests = await db.executable_tests.find(
        {"requirement_id": requirement_id}
    ).sort([("version", 1)]).to_list(1000)
    return [ExecutableTest.model_validate(test) for test in tests]


@router.post("/requirements/{requirement_id}/executable-tests", response_model=ExecutableTest)
async def create_executable_test(requirement_id: str, payload: ExecutableTestCreate):
    db = get_db()
    requirement = await db.requirements.find_one({"_id": requirement_id})
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    class_name = derive_class_name(payload.content)
    file_name = file_name_for(class_name)
    if not file_name:
        raise HTTPException(
            status_code=400,
            detail="Test source does not declare a valid top-level class.",
        )

    errors = validate_executable_test(payload.content, payload.method_map)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    previous = await db.executable_tests.find(
        {"requirement_id": requirement_id}
    ).to_list(1000)
    next_version = max((test.get("version", 0) for test in previous), default=0) + 1
    now = datetime.utcnow()

    test = ExecutableTest(
        executable_test_id=str(uuid.uuid4()),
        project_id=requirement["projectId"],
        requirement_id=requirement_id,
        class_name=class_name,
        file_name=file_name,
        content=payload.content,
        version=next_version,
        method_map={str(k): str(v) for k, v in payload.method_map.items()},
        source="DEVELOPER_EDITED",
        created_at=now,
        updated_at=now,
    )
    await db.executable_tests.insert_one(test.model_dump(mode="json"))
    return test


@router.post("/requirements/{requirement_id}/executable-tests/generate", response_model=ExecutableTest)
async def generate_executable_test(requirement_id: str, payload: ExecutableTestGenerateRequest):
    db = get_db()
    requirement = await db.requirements.find_one({"_id": requirement_id})
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    requested_ids = [str(case_id) for case_id in payload.test_case_ids]
    if not requested_ids:
        raise HTTPException(
            status_code=400,
            detail="test_case_ids must contain at least one test case id.",
        )
    if len(set(requested_ids)) != len(requested_ids):
        raise HTTPException(status_code=400, detail="test_case_ids contains duplicate ids.")

    owned_cases = await db.test_cases.find(
        {"requirement_id": requirement_id}
    ).to_list(10000)
    owned_by_id = {str(case["test_case_id"]): case for case in owned_cases}
    unknown = [case_id for case_id in requested_ids if case_id not in owned_by_id]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown or foreign test case id(s) for this requirement: "
                f"{', '.join(unknown)}."
            ),
        )

    # Context: the descriptive cases to implement + latest production sources.
    selected_cases = [
        {
            "test_case_id": case_id,
            "title": owned_by_id[case_id]["title"],
            "description": owned_by_id[case_id].get("description", ""),
            "input": owned_by_id[case_id].get("input", ""),
            "expected_output": owned_by_id[case_id].get("expected_output", ""),
        }
        for case_id in requested_ids
    ]
    related = await db.code_artifacts.find(
        {"project_id": requirement["projectId"], "requirement_id": requirement_id, "language": "Java"}
    ).to_list(1000)
    source_files = {
        item["file_name"]: item["content"] for item in _latest_artifacts(related)
    }
    if not source_files:
        raise HTTPException(
            status_code=400,
            detail="No Java source artifacts exist for this requirement yet; generate code first.",
        )

    try:
        generated = generate_executable_test_source(
            requirement["title"],
            requirement["description"],
            selected_cases,
            source_files,
        )
    except ValueError as exc:
        logger.warning(
            "executable-test generation not configured for requirement %s: %s",
            requirement_id,
            type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="AI executable-test generation is not configured")
    except RuntimeError as exc:
        # The provider message carries the API-side reason (e.g. quota,
        # invalid schema, transport failure). Log it server-side and echo a
        # truncated copy so the UI can show something actionable.
        logger.warning(
            "executable-test generation provider failure for requirement %s (%s): %s",
            requirement_id,
            type(exc).__name__,
            str(exc)[:300],
        )
        raise HTTPException(
            status_code=502,
            detail=f"AI executable-test generation failed: {str(exc)[:300]}",
        )

    test_class = generated.test_class
    # The AI returns links; the stored record keeps the method_map dict.
    # Detect duplicate case ids before dict conversion collapses them.
    link_case_ids = [link.test_case_id for link in test_class.method_links]
    if len(set(link_case_ids)) != len(link_case_ids):
        raise HTTPException(
            status_code=502,
            detail="AI returned duplicate test_case_id entries in method_links.",
        )
    method_map = {link.test_case_id: link.method for link in test_class.method_links}
    class_name = derive_class_name(test_class.content)
    file_name = file_name_for(class_name)
    if not file_name:
        raise HTTPException(
            status_code=502,
            detail="AI returned a test class without a valid class declaration.",
        )

    errors = validate_executable_test(test_class.content, method_map)
    if errors:
        raise HTTPException(
            status_code=502,
            detail="AI returned an invalid JUnit test source: " + "; ".join(errors),
        )

    returned_ids = set(method_map.keys())
    if returned_ids != set(requested_ids):
        missing = sorted(set(requested_ids) - returned_ids)
        extra = sorted(returned_ids - set(requested_ids))
        raise HTTPException(
            status_code=502,
            detail=(
                "AI returned a method_map that does not match the requested test "
                f"cases (missing: {missing or 'none'}, unexpected: {extra or 'none'})."
            ),
        )

    previous = await db.executable_tests.find(
        {"requirement_id": requirement_id}
    ).to_list(1000)
    next_version = max((test.get("version", 0) for test in previous), default=0) + 1
    now = datetime.utcnow()

    test = ExecutableTest(
        executable_test_id=str(uuid.uuid4()),
        project_id=requirement["projectId"],
        requirement_id=requirement_id,
        class_name=class_name,
        file_name=file_name,
        content=test_class.content,
        version=next_version,
        method_map={str(k): str(v) for k, v in method_map.items()},
        source="AI_GENERATED",
        created_at=now,
        updated_at=now,
    )
    try:
        await db.executable_tests.insert_one(test.model_dump(mode="json"))
    except Exception as exc:
        logger.error(
            "failed to persist generated executable test for requirement %s: %s",
            requirement_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="AI generated a valid test but it could not be saved. Please retry.",
        )
    return test
