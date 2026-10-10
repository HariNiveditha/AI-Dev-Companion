import asyncio

import pytest
from fastapi.testclient import TestClient

from app.db.mongodb import get_db
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        db = get_db()
        asyncio.run(db.executions.delete_many({}))
        asyncio.run(db.code_artifacts.delete_many({}))
        asyncio.run(db.requirements.delete_many({}))
        yield test_client


def test_start_execution_disabled_by_default_returns_run_record(client):
    db = get_db()
    requirement_id = "req-exec-1"
    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": requirement_id,
                "projectId": "project-123",
                "title": "Account login",
                "description": "Users log in.",
                "status": "CONFIRMED",
                "analysis": {},
            }
        )
    )
    asyncio.run(
        db.code_artifacts.insert_one(
            {
                "artifact_id": "artifact-1",
                "project_id": "project-123",
                "requirement_id": requirement_id,
                "file_name": "LoginService.java",
                "language": "Java",
                "content": "class LoginService {}",
                "version": 1,
                "source": "AI_GENERATED",
                "status": "AI_GENERATED",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )

    response = client.post(
        f"/requirements/{requirement_id}/executions",
        json={"artifact_id": "artifact-1", "test_case_ids": ["case-1", "case-2"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["requirement_id"] == requirement_id
    assert payload["status"] == "DISABLED"
    assert payload["artifact"]["file_name"] == "LoginService.java"
    assert "secure sandbox" in payload["error_message"].lower()


def test_get_execution_results_returns_empty_list_for_created_run(client):
    db = get_db()
    requirement_id = "req-exec-2"
    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": requirement_id,
                "projectId": "project-123",
                "title": "Password reset",
                "description": "User can reset password.",
                "status": "CONFIRMED",
                "analysis": {},
            }
        )
    )
    asyncio.run(
        db.code_artifacts.insert_one(
            {
                "artifact_id": "artifact-2",
                "project_id": "project-123",
                "requirement_id": requirement_id,
                "file_name": "PasswordReset.java",
                "language": "Java",
                "content": "class PasswordReset {}",
                "version": 2,
                "source": "DEVELOPER_EDITED",
                "status": "EDITED",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )

    create_response = client.post(
        f"/requirements/{requirement_id}/executions",
        json={"artifact_id": "artifact-2", "test_case_ids": []},
    )
    execution_id = create_response.json()["execution_id"]

    result_response = client.get(f"/executions/{execution_id}/results")

    assert create_response.status_code == 200
    assert result_response.status_code == 200
    assert result_response.json() == []


def test_start_execution_returns_404_for_missing_requirement(client):
    response = client.post(
        "/requirements/missing-execution/executions",
        json={"artifact_id": "artifact-missing", "test_case_ids": []},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Requirement not found"


def test_start_execution_returns_404_for_missing_artifact(client):
    db = get_db()
    requirement_id = "req-exec-3"
    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": requirement_id,
                "projectId": "project-123",
                "title": "Order service",
                "description": "Orders can be created.",
                "status": "CONFIRMED",
                "analysis": {},
            }
        )
    )

    response = client.post(
        f"/requirements/{requirement_id}/executions",
        json={"artifact_id": "missing-artifact", "test_case_ids": []},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact not found"
