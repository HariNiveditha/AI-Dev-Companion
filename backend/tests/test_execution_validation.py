"""Endpoint validation tests for Phase 9 execution requests.

Every invalid request must fail explicitly (4xx) *without*
creating an execution record.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.db.mongodb import get_db
from app.main import app
from app.services.execution import container as container_runtime
from app.services.execution import runner


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        db = get_db()
        asyncio.run(db.executions.delete_many({}))
        asyncio.run(db.executable_tests.delete_many({}))
        asyncio.run(db.code_artifacts.delete_many({}))
        asyncio.run(db.test_cases.delete_many({}))
        asyncio.run(db.requirements.delete_many({}))
        yield test_client


def _seed(client, requirement_id="req-val-1", with_cases=True):
    db = get_db()
    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": requirement_id,
                "projectId": "project-val",
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
                "artifact_id": "artifact-val",
                "project_id": "project-val",
                "requirement_id": requirement_id,
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
    if with_cases:
        for case_id in ("case-1", "case-2"):
            asyncio.run(
                db.test_cases.insert_one(
                    {
                        "test_case_id": case_id,
                        "requirement_id": requirement_id,
                        "project_id": "project-val",
                        "title": f"Case {case_id}",
                        "description": "d",
                        "input": "i",
                        "expected_output": "e",
                        "priority": "HIGH",
                        "type": "FUNCTIONAL",
                        "created_at": "2024-01-01T00:00:00",
                    }
                )
            )


def _executable_test_doc(requirement_id="req-val-1"):
    return {
        "executable_test_id": "exec-test-1",
        "project_id": "project-val",
        "requirement_id": requirement_id,
        "class_name": "LoginServiceTest",
        "file_name": "LoginServiceTest.java",
        "content": (
            "import org.junit.jupiter.api.Test;\n\n"
            "public class LoginServiceTest {\n"
            "    @Test\n    void acceptsValidLogin() {}\n"
            "    @Test\n    void rejectsInvalidLogin() {}\n}\n"
        ),
        "version": 1,
        "method_map": {"case-1": "acceptsValidLogin", "case-2": "rejectsInvalidLogin"},
        "source": "AI_GENERATED",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }


def test_empty_test_case_ids_rejected(client):
    _seed(client)

    response = client.post(
        "/requirements/req-val-1/executions",
        json={"artifact_id": "artifact-val", "test_case_ids": []},
    )

    assert response.status_code == 400
    assert "at least one" in response.json()["detail"]


def test_duplicate_test_case_ids_rejected(client):
    _seed(client)

    response = client.post(
        "/requirements/req-val-1/executions",
        json={"artifact_id": "artifact-val", "test_case_ids": ["case-1", "case-1"]},
    )

    assert response.status_code == 400
    assert "duplicate" in response.json()["detail"].lower()


def test_unknown_test_case_id_rejected(client):
    _seed(client)

    response = client.post(
        "/requirements/req-val-1/executions",
        json={"artifact_id": "artifact-val", "test_case_ids": ["case-1", "nope"]},
    )

    assert response.status_code == 400
    assert "nope" in response.json()["detail"]


def test_foreign_test_case_id_rejected(client):
    _seed(client)
    db = get_db()
    # A test case belonging to a different requirement.
    asyncio.run(
        db.test_cases.insert_one(
            {
                "test_case_id": "other-case",
                "requirement_id": "req-other",
                "project_id": "project-val",
                "title": "Other",
                "description": "d",
                "input": "i",
                "expected_output": "e",
                "priority": "HIGH",
                "type": "FUNCTIONAL",
                "created_at": "2024-01-01T00:00:00",
            }
        )
    )

    response = client.post(
        "/requirements/req-val-1/executions",
        json={"artifact_id": "artifact-val", "test_case_ids": ["other-case"]},
    )

    assert response.status_code == 400
    assert "other-case" in response.json()["detail"]


def test_artifact_from_other_requirement_rejected(client):
    _seed(client)
    db = get_db()
    asyncio.run(
        db.code_artifacts.insert_one(
            {
                "artifact_id": "artifact-other",
                "project_id": "project-val",
                "requirement_id": "req-other",
                "file_name": "Other.java",
                "language": "Java",
                "content": "public class Other {}",
                "version": 1,
                "source": "AI_GENERATED",
                "status": "AI_GENERATED",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )

    response = client.post(
        "/requirements/req-val-1/executions",
        json={
            "artifact_id": "artifact-other",
            "test_case_ids": ["case-1"],
        },
    )

    assert response.status_code == 400
    assert "does not belong" in response.json()["detail"]


def test_executable_test_from_other_requirement_rejected(client):
    _seed(client)
    db = get_db()
    doc = _executable_test_doc(requirement_id="req-other")
    asyncio.run(db.executable_tests.insert_one(doc))

    response = client.post(
        "/requirements/req-val-1/executions",
        json={
            "artifact_id": "artifact-val",
            "test_case_ids": ["case-1"],
            "executable_test_id": "exec-test-1",
        },
    )

    assert response.status_code == 400
    assert "does not belong" in response.json()["detail"]


def test_executable_test_not_implementing_requested_case_rejected(client):
    _seed(client)
    db = get_db()
    doc = _executable_test_doc()
    doc["method_map"] = {"case-1": "acceptsValidLogin"}  # case-2 missing
    asyncio.run(db.executable_tests.insert_one(doc))

    response = client.post(
        "/requirements/req-val-1/executions",
        json={
            "artifact_id": "artifact-val",
            "test_case_ids": ["case-1", "case-2"],
            "executable_test_id": "exec-test-1",
        },
    )

    assert response.status_code == 400
    assert "case-2" in response.json()["detail"]


def test_enabled_without_executable_test_rejected(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(
        runner,
        "check_availability",
        lambda: runner.Availability(
            available=True, reason="", runner_label="docker image=x"
        ),
    )

    response = client.post(
        "/requirements/req-val-1/executions",
        json={"artifact_id": "artifact-val", "test_case_ids": ["case-1"]},
    )

    assert response.status_code == 400
    assert "executable" in response.json()["detail"].lower()


def test_duplicate_request_while_running_rejected(client, monkeypatch):
    _seed(client)
    db = get_db()
    asyncio.run(db.executable_tests.insert_one(_executable_test_doc()))
    # A run already in progress for this requirement.
    asyncio.run(
        db.executions.insert_one(
            {
                "execution_id": "exec-running",
                "requirement_id": "req-val-1",
                "project_id": "project-val",
                "artifact": {
                    "artifact_id": "artifact-val",
                    "project_id": "project-val",
                    "requirement_id": "req-val-1",
                    "file_name": "LoginService.java",
                    "version": 1,
                    "source": "AI_GENERATED",
                },
                "status": "RUNNING",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )
    monkeypatch.setattr(
        runner,
        "check_availability",
        lambda: runner.Availability(
            available=True, reason="", runner_label="docker image=x"
        ),
    )

    response = client.post(
        "/requirements/req-val-1/executions",
        json={
            "artifact_id": "artifact-val",
            "test_case_ids": ["case-1"],
            "executable_test_id": "exec-test-1",
        },
    )

    assert response.status_code == 409


def test_invalid_request_creates_no_record(client):
    _seed(client)
    db = get_db()

    client.post(
        "/requirements/req-val-1/executions",
        json={"artifact_id": "artifact-val", "test_case_ids": []},
    )

    count = asyncio.run(db.executions.count_documents({}))
    assert count == 0


def test_reconcile_marks_interrupted_runs_as_error(client):
    db = get_db()
    for status in ("PENDING", "RUNNING", "PASSED"):
        asyncio.run(
            db.executions.insert_one(
                {
                    "execution_id": f"exec-{status}",
                    "requirement_id": "req-val-1",
                    "project_id": "project-val",
                    "artifact": {
                        "artifact_id": "a",
                        "project_id": "p",
                        "requirement_id": "r",
                        "file_name": "A.java",
                        "version": 1,
                        "source": "AI_GENERATED",
                    },
                    "status": status,
                    "created_at": "2024-01-01T00:00:00",
                    "updated_at": "2024-01-01T00:00:00",
                }
            )
        )

    from app.api.executions import reconcile_interrupted_executions

    modified = asyncio.run(reconcile_interrupted_executions())

    assert modified == 2
    pending = asyncio.run(db.executions.find_one({"execution_id": "exec-PENDING"}))
    running = asyncio.run(db.executions.find_one({"execution_id": "exec-RUNNING"}))
    passed = asyncio.run(db.executions.find_one({"execution_id": "exec-PASSED"}))
    assert pending["status"] == "ERROR"
    assert running["status"] == "ERROR"
    assert "interrupted" in pending["error_message"].lower()
    assert passed["status"] == "PASSED"  # terminal states untouched
