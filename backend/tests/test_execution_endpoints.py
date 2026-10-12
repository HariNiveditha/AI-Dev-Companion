"""End-to-end integration tests for Phase 9 execution (mocked container).

These verify the real request → validation → record → container
(mocked) → persistence → retrieval flow, including:
* per-test results and aggregate counts from the JUnit XML report;
* the exact artifact snapshot recorded with the execution;
* append-only history (no run overwrites an earlier run);
* retrieval of persisted executions after the request completes
  (simulating an application-level reload).
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.db.mongodb import get_db
from app.main import app
from app.services.execution import container as container_runtime
from app.services.execution import runner
from app.services.execution.container import ContainerRun
from app.models.execution import ExecutionCompileResult

JUNIT_TEST = """import org.junit.jupiter.api.Test;

public class LoginServiceTest {
    @Test
    void acceptsValidLogin() {}

    @Test
    void rejectsInvalidLogin() {}
}
"""


def _write_passing_report(workspace):
    (workspace.reports_dir / "TEST-junit-jupiter.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="LoginServiceTest" tests="2" failures="0" errors="0" skipped="0" time="0.05">
  <testcase name="acceptsValidLogin" classname="LoginServiceTest" time="0.02"/>
  <testcase name="rejectsInvalidLogin" classname="LoginServiceTest" time="0.03"/>
</testsuite>
""",
        encoding="utf-8",
    )


def _write_realistic_report(workspace):
    # Names as the real JUnit console launcher emits them: "method()".
    (workspace.reports_dir / "TEST-junit-jupiter.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="LoginServiceTest" tests="2" failures="0" errors="0" skipped="0" time="0.05">
  <testcase name="acceptsValidLogin()" classname="LoginServiceTest" time="0.02"/>
  <testcase name="rejectsInvalidLogin()" classname="LoginServiceTest" time="0.03"/>
</testsuite>
""",
        encoding="utf-8",
    )

def _write_failing_report(workspace):
    (workspace.reports_dir / "TEST-junit-jupiter.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="LoginServiceTest" tests="2" failures="1" errors="0" skipped="0" time="0.05">
  <testcase name="acceptsValidLogin" classname="LoginServiceTest" time="0.02"/>
  <testcase name="rejectsInvalidLogin" classname="LoginServiceTest" time="0.03">
    <failure message="expected [false] but was [true]" type="AssertionFailedError">java.lang.AssertionError</failure>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        db = get_db()
        for collection in (
            "executions",
            "executable_tests",
            "code_artifacts",
            "test_cases",
            "requirements",
        ):
            asyncio.run(db[collection].delete_many({}))
        from app.api.executions import _IN_FLIGHT

        _IN_FLIGHT.clear()
        yield test_client
        _IN_FLIGHT.clear()


def _seed_project(client):
    db = get_db()
    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": "req-int-1",
                "projectId": "project-int",
                "title": "Login",
                "description": "Users log in.",
                "status": "CONFIRMED",
                "analysis": {},
            }
        )
    )
    asyncio.run(
        db.code_artifacts.insert_one(
            {
                "artifact_id": "artifact-int",
                "project_id": "project-int",
                "requirement_id": "req-int-1",
                "file_name": "LoginService.java",
                "language": "Java",
                "content": "public class LoginService {}",
                "version": 1,
                "source": "AI_GENERATED",
                "status": "AI_GENERATED",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )
    for case_id, title in (
        ("case-1", "valid login accepted"),
        ("case-2", "invalid login rejected"),
    ):
        asyncio.run(
            db.test_cases.insert_one(
                {
                    "test_case_id": case_id,
                    "requirement_id": "req-int-1",
                    "project_id": "project-int",
                    "title": title,
                    "description": "d",
                    "input": "i",
                    "expected_output": "e",
                    "priority": "HIGH",
                    "type": "FUNCTIONAL",
                    "created_at": "2024-01-01T00:00:00",
                }
            )
        )
    asyncio.run(
        db.executable_tests.insert_one(
            {
                "executable_test_id": "exec-test-int",
                "project_id": "project-int",
                "requirement_id": "req-int-1",
                "class_name": "LoginServiceTest",
                "file_name": "LoginServiceTest.java",
                "content": JUNIT_TEST,
                "version": 1,
                "method_map": {
                    "case-1": "acceptsValidLogin",
                    "case-2": "rejectsInvalidLogin",
                },
                "source": "AI_GENERATED",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )


def _enable_mocked_runner(monkeypatch, report_writer, *, compile_ok=True):
    monkeypatch.setattr(
        runner,
        "check_availability",
        lambda: runner.Availability(
            available=True, reason="", runner_label="docker image=eclipse-temurin:21-jdk"
        ),
    )
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: "/usr/bin/docker")

    def mock_compile(cli, image, execution_id, workspace, junit_jar, timeout_seconds):
        return ExecutionCompileResult(
            status="PASSED", exit_code=0, stdout="", stderr="", duration_ms=10
        )

    monkeypatch.setattr(container_runtime, "compile_tests", mock_compile)

    def mock_run(cli, image, execution_id, workspace, junit_jar, timeout_seconds):
        report_writer(workspace)
        return ContainerRun(exit_code=0, stdout="", stderr="", duration_ms=50)

    monkeypatch.setattr(container_runtime, "run_junit", mock_run)


def test_full_passing_execution_flow(client, monkeypatch):
    _seed_project(client)
    _enable_mocked_runner(monkeypatch, _write_passing_report)

    response = client.post(
        "/requirements/req-int-1/executions",
        json={
            "artifact_id": "artifact-int",
            "test_case_ids": ["case-1", "case-2"],
            "executable_test_id": "exec-test-int",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "PASSED"
    assert payload["counts"] == {
        "total": 2, "passed": 2, "failed": 0, "skipped": 0, "error": 0,
    }
    assert payload["runner"] == "docker image=eclipse-temurin:21-jdk"
    assert payload["executable_test_id"] == "exec-test-int"
    assert payload["executable_test_version"] == 1
    assert payload["requested_test_case_ids"] == ["case-1", "case-2"]
    assert payload["duration_ms"] >= 0
    assert payload["completed_at"] is not None

    # Per-test results are mapped back to the descriptive cases.
    results = payload["test_results"]
    assert len(results) == 2
    by_case = {result["test_case_id"]: result for result in results}
    assert by_case["case-1"]["title"] == "valid login accepted"
    assert by_case["case-1"]["method"] == "acceptsValidLogin"
    assert by_case["case-1"]["status"] == "PASSED"
    assert by_case["case-1"]["execution_id"] == payload["execution_id"]
    assert by_case["case-1"]["error_details"] is None

    # The snapshot records the exact artifact version executed.
    snapshot = payload["source_snapshot"]
    assert len(snapshot) == 1
    assert snapshot[0]["artifact_id"] == "artifact-int"
    assert snapshot[0]["version"] == 1
    assert snapshot[0]["file_name"] == "LoginService.java"


def test_execution_is_persisted_and_retrievable(client, monkeypatch):
    """Simulates an application-level reload: data comes from Mongo."""
    _seed_project(client)
    _enable_mocked_runner(monkeypatch, _write_passing_report)

    response = client.post(
        "/requirements/req-int-1/executions",
        json={
            "artifact_id": "artifact-int",
            "test_case_ids": ["case-1", "case-2"],
            "executable_test_id": "exec-test-int",
        },
    )
    execution_id = response.json()["execution_id"]

    by_id = client.get(f"/executions/{execution_id}")
    results = client.get(f"/executions/{execution_id}/results")
    history = client.get("/requirements/req-int-1/executions")

    assert by_id.status_code == 200
    assert by_id.json()["status"] == "PASSED"
    assert results.status_code == 200
    assert len(results.json()) == 2
    assert history.status_code == 200
    assert len(history.json()) == 1


def test_realistic_junit_method_names_map_to_test_cases(client, monkeypatch):
    """The real launcher reports name='method()'; mapping must still work."""
    _seed_project(client)
    _enable_mocked_runner(monkeypatch, _write_realistic_report)

    response = client.post(
        "/requirements/req-int-1/executions",
        json={
            "artifact_id": "artifact-int",
            "test_case_ids": ["case-1", "case-2"],
            "executable_test_id": "exec-test-int",
        },
    )

    payload = response.json()
    assert payload["status"] == "PASSED"
    assert payload["counts"]["total"] == 2
    by_case = {result["test_case_id"]: result for result in payload["test_results"]}
    assert by_case["case-1"]["method"] == "acceptsValidLogin()"
    assert by_case["case-2"]["method"] == "rejectsInvalidLogin()"


def test_history_is_append_only(client, monkeypatch):
    _seed_project(client)
    _enable_mocked_runner(monkeypatch, _write_passing_report)

    request = {
        "artifact_id": "artifact-int",
        "test_case_ids": ["case-1", "case-2"],
        "executable_test_id": "exec-test-int",
    }
    first = client.post("/requirements/req-int-1/executions", json=request).json()
    second = client.post("/requirements/req-int-1/executions", json=request).json()

    assert first["execution_id"] != second["execution_id"]
    history = client.get("/requirements/req-int-1/executions").json()
    assert len(history) == 2
    # Newest first, both intact.
    assert history[0]["execution_id"] == second["execution_id"]
    assert history[1]["execution_id"] == first["execution_id"]
    assert history[1]["status"] == "PASSED"


def test_failing_run_reports_failure_details(client, monkeypatch):
    _seed_project(client)
    _enable_mocked_runner(monkeypatch, _write_failing_report)

    response = client.post(
        "/requirements/req-int-1/executions",
        json={
            "artifact_id": "artifact-int",
            "test_case_ids": ["case-1", "case-2"],
            "executable_test_id": "exec-test-int",
        },
    )

    payload = response.json()
    assert payload["status"] == "FAILED"
    assert payload["counts"]["failed"] == 1
    failed = next(r for r in payload["test_results"] if r["status"] == "FAILED")
    assert failed["test_case_id"] == "case-2"
    assert "expected [false] but was [true]" in failed["error_details"]
    assert "java.lang.AssertionError" in failed["error_details"]


def test_compilation_failure_is_error_with_diagnostics(client, monkeypatch):
    _seed_project(client)
    _enable_mocked_runner(monkeypatch, _write_passing_report)

    def mock_compile(cli, image, execution_id, workspace, junit_jar, timeout_seconds):
        return ExecutionCompileResult(
            status="FAILED",
            exit_code=1,
            stdout="",
            stderr="LoginServiceTest.java:4: error: cannot find symbol",
            duration_ms=10,
        )

    monkeypatch.setattr(container_runtime, "compile_tests", mock_compile)

    response = client.post(
        "/requirements/req-int-1/executions",
        json={
            "artifact_id": "artifact-int",
            "test_case_ids": ["case-1", "case-2"],
            "executable_test_id": "exec-test-int",
        },
    )

    payload = response.json()
    assert payload["status"] == "ERROR"
    assert "compilation failed" in payload["error_message"].lower()
    assert payload["compile_result"]["status"] == "FAILED"
    assert "cannot find symbol" in payload["compile_result"]["stderr"]
    assert payload["counts"]["total"] == 0
    assert payload["test_results"] == []


def test_new_artifact_version_is_used_by_next_execution(client, monkeypatch):
    """A new artifact version after an earlier execution is picked up."""
    _seed_project(client)
    _enable_mocked_runner(monkeypatch, _write_passing_report)

    request = {
        "artifact_id": "artifact-int",
        "test_case_ids": ["case-1", "case-2"],
        "executable_test_id": "exec-test-int",
    }
    client.post("/requirements/req-int-1/executions", json=request)

    db = get_db()
    asyncio.run(
        db.code_artifacts.insert_one(
            {
                "artifact_id": "artifact-int-v2",
                "project_id": "project-int",
                "requirement_id": "req-int-1",
                "file_name": "LoginService.java",
                "language": "Java",
                "content": "public class LoginService { /* v2 */ }",
                "version": 2,
                "source": "DEVELOPER_EDITED",
                "status": "EDITED",
                "created_at": "2024-01-02T00:00:00",
                "updated_at": "2024-01-02T00:00:00",
            }
        )
    )

    second = client.post("/requirements/req-int-1/executions", json=request).json()

    assert second["source_snapshot"][0]["version"] == 2
    assert second["source_snapshot"][0]["artifact_id"] == "artifact-int-v2"


def test_disabled_execution_persists_requested_scope(client, monkeypatch):
    """The legacy disabled contract: truthful record, no run attempted."""
    _seed_project(client)
    monkeypatch.delenv("ENABLE_JAVA_EXECUTION", raising=False)

    response = client.post(
        "/requirements/req-int-1/executions",
        json={
            "artifact_id": "artifact-int",
            "test_case_ids": ["case-1", "case-2"],
        },
    )

    payload = response.json()
    assert payload["status"] == "DISABLED"
    assert payload["requested_test_case_ids"] == ["case-1", "case-2"]
    assert len(payload["source_snapshot"]) == 1
    assert "secure sandbox" in payload["error_message"].lower()
    assert payload["test_results"] == []
