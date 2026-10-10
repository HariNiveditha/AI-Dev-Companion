import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import requirements as requirement_routes
from app.db.mongodb import get_db
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _reset_collections():
    db = get_db()
    asyncio.run(db.test_cases.delete_many({}))
    asyncio.run(db.requirements.delete_many({}))


def test_get_requirement_test_cases_returns_cases_for_existing_requirement(client):
    _reset_collections()
    db = get_db()
    requirement_id = "req-123"

    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": requirement_id,
                "projectId": "project-123",
                "title": "Login flow",
                "description": "Users should be able to log in.",
                "status": "CONFIRMED",
                "analysis": {},
            }
        )
    )
    asyncio.run(
        db.test_cases.insert_many(
            [
                {
                    "test_case_id": "case-1",
                    "requirement_id": requirement_id,
                    "title": "Valid login",
                    "description": "User can sign in with valid credentials.",
                    "input": "email=user@example.com; password=Secret123",
                    "expected_output": "User is logged in",
                    "priority": "HIGH",
                    "type": "FUNCTIONAL",
                    "created_at": "2024-01-01T00:00:00",
                },
                {
                    "test_case_id": "case-2",
                    "requirement_id": requirement_id,
                    "title": "Invalid password",
                    "description": "User cannot log in with wrong password.",
                    "input": "email=user@example.com; password=WrongPass",
                    "expected_output": "Login rejected",
                    "priority": "MEDIUM",
                    "type": "NEGATIVE",
                    "created_at": "2024-01-01T00:01:00",
                },
            ]
        )
    )

    response = client.get(f"/requirements/{requirement_id}/test-cases")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert {item["title"] for item in payload} == {"Valid login", "Invalid password"}


def test_get_requirement_test_cases_returns_empty_list_for_requirement_without_cases(client):
    _reset_collections()
    db = get_db()
    requirement_id = "req-empty"

    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": requirement_id,
                "projectId": "project-123",
                "title": "Profile update",
                "description": "Users should update their profile.",
                "status": "CONFIRMED",
                "analysis": {},
            }
        )
    )

    response = client.get(f"/requirements/{requirement_id}/test-cases")

    assert response.status_code == 200
    assert response.json() == []


def test_get_requirement_test_cases_returns_404_for_unknown_requirement(client):
    _reset_collections()

    response = client.get("/requirements/requirements-do-not-exist/test-cases")

    assert response.status_code == 404
    assert response.json()["detail"] == "Requirement not found"


def test_generate_requirement_test_cases_persists_generated_cases(client, monkeypatch):
    _reset_collections()
    db = get_db()
    requirement_id = "req-generate"

    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": requirement_id,
                "projectId": "project-123",
                "title": "Password reset",
                "description": "Users should be able to reset their password.",
                "status": "CONFIRMED",
                "analysis": {
                    "functional_requirements": ["User can reset password"],
                    "non_functional_requirements": ["Secure operations"],
                    "assumptions": [],
                    "ambiguities": [],
                    "edge_cases": [],
                    "acceptance_criteria": ["Reset flow works"],
                },
            }
        )
    )

    fake_generated = SimpleNamespace(
        test_cases=[
            SimpleNamespace(
                title="Reset request",
                description="User submits reset request with valid email.",
                input="email=user@example.com",
                expected_output="Reset email is sent",
                priority="HIGH",
                type="FUNCTIONAL",
            ),
            SimpleNamespace(
                title="Invalid email",
                description="User submits invalid email.",
                input="email=bad-email",
                expected_output="Reset request rejected",
                priority="LOW",
                type="VALIDATION",
            ),
        ]
    )
    monkeypatch.setattr(requirement_routes, "generate_test_cases", lambda *args, **kwargs: fake_generated)

    response = client.post(f"/requirements/{requirement_id}/generate-test-cases")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert {item["title"] for item in payload} == {"Reset request", "Invalid email"}

    saved_cases = asyncio.run(db.test_cases.find({"requirement_id": requirement_id}).to_list(10))
    assert len(saved_cases) == 2
    assert {item["title"] for item in saved_cases} == {"Reset request", "Invalid email"}
