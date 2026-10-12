"""Regression tests for AI executable-test generation.

Root cause covered here: the response schema sent to the Gemini Developer
API must not contain ``additionalProperties`` (every map shape produces it
and the API rejects the whole request). The contract test pins the schema
shape; the endpoint tests pin success and every failure path with mocked
AI calls (mocked results are never presented as live verification).
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

import app.api.executions as executions_module
from app.db.mongodb import get_db
from app.main import app
from app.models.test_case import (
    ExecutableTestGenerationResponse,
    MethodLink,
)


VALID_JUNIT = (
    "import org.junit.jupiter.api.Test;\n"
    "\n"
    "public class LoginServiceTest {\n"
    "    @Test\n"
    "    void acceptsValidLogin() {}\n"
    "    @Test\n"
    "    void rejectsInvalidLogin() {}\n"
    "}\n"
)


def _find_additional_properties(schema):
    """Collect JSON-schema paths using additionalProperties (recursive)."""
    found = []

    def walk(node, path):
        if isinstance(node, dict):
            if "additionalProperties" in node:
                found.append(path)
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(schema, "$")
    return found


def test_generation_response_schema_has_no_additional_properties():
    """The Developer API rejects additionalProperties; the schema must not need it."""
    schema = ExecutableTestGenerationResponse.model_json_schema()

    assert _find_additional_properties(schema) == []


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


def _seed(client):
    db = get_db()
    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": "req-gen-1",
                "projectId": "project-gen",
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
                "artifact_id": "artifact-gen",
                "project_id": "project-gen",
                "requirement_id": "req-gen-1",
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
    for case_id in ("case-1", "case-2"):
        asyncio.run(
            db.test_cases.insert_one(
                {
                    "test_case_id": case_id,
                    "requirement_id": "req-gen-1",
                    "project_id": "project-gen",
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


def _ai_response(content=VALID_JUNIT, links=None):
    if links is None:
        links = [
            MethodLink(test_case_id="case-1", method="acceptsValidLogin"),
            MethodLink(test_case_id="case-2", method="rejectsInvalidLogin"),
        ]
    return ExecutableTestGenerationResponse(
        test_class={"content": content, "method_links": links}
    )


def _generate(client):
    return client.post(
        "/requirements/req-gen-1/executable-tests/generate",
        json={"test_case_ids": ["case-1", "case-2"]},
    )


def test_generate_success_persists_version(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(
        executions_module,
        "generate_executable_test_source",
        lambda *args, **kwargs: _ai_response(),
    )

    response = _generate(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_name"] == "LoginServiceTest.java"
    assert payload["version"] == 1
    assert payload["source"] == "AI_GENERATED"
    assert payload["method_map"] == {
        "case-1": "acceptsValidLogin",
        "case-2": "rejectsInvalidLogin",
    }

    stored = client.get("/requirements/req-gen-1/executable-tests").json()
    assert len(stored) == 1
    assert stored[0]["executable_test_id"] == payload["executable_test_id"]


def test_generate_provider_failure_returns_actionable_502(client, monkeypatch):
    _seed(client)

    def failing(*args, **kwargs):
        raise RuntimeError("AI Provider failed: 429 quota exhausted")

    monkeypatch.setattr(
        executions_module, "generate_executable_test_source", failing
    )

    response = _generate(client)

    assert response.status_code == 502
    assert "quota" in response.json()["detail"]


def test_generate_not_configured_returns_503(client, monkeypatch):
    _seed(client)

    def missing_key(*args, **kwargs):
        raise ValueError("AI_API_KEY is missing. Please configure it in .env")

    monkeypatch.setattr(
        executions_module, "generate_executable_test_source", missing_key
    )

    response = _generate(client)

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_generate_invalid_java_rejected(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(
        executions_module,
        "generate_executable_test_source",
        lambda *args, **kwargs: _ai_response(content="public class Broken { oops"),
    )

    response = _generate(client)

    assert response.status_code == 502
    assert "invalid JUnit" in response.json()["detail"]

    db = get_db()
    count = asyncio.run(db.executable_tests.count_documents({}))
    assert count == 0  # invalid output is never persisted


def test_generate_missing_case_link_rejected(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(
        executions_module,
        "generate_executable_test_source",
        lambda *args, **kwargs: _ai_response(
            links=[MethodLink(test_case_id="case-1", method="acceptsValidLogin")]
        ),
    )

    response = _generate(client)

    assert response.status_code == 502
    assert "case-2" in response.json()["detail"]


def test_generate_unexpected_case_link_rejected(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(
        executions_module,
        "generate_executable_test_source",
        lambda *args, **kwargs: _ai_response(
            links=[
                MethodLink(test_case_id="case-1", method="acceptsValidLogin"),
                MethodLink(test_case_id="case-2", method="rejectsInvalidLogin"),
                MethodLink(test_case_id="case-9", method="extraMethod"),
            ]
        ),
    )

    response = _generate(client)

    assert response.status_code == 502
    assert "case-9" in response.json()["detail"]


def test_generate_duplicate_case_link_rejected(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(
        executions_module,
        "generate_executable_test_source",
        lambda *args, **kwargs: _ai_response(
            links=[
                MethodLink(test_case_id="case-1", method="acceptsValidLogin"),
                MethodLink(test_case_id="case-1", method="rejectsInvalidLogin"),
                MethodLink(test_case_id="case-2", method="rejectsInvalidLogin"),
            ]
        ),
    )

    response = _generate(client)

    assert response.status_code == 502
    assert "duplicate" in response.json()["detail"].lower()


def test_generate_undeclared_method_rejected(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(
        executions_module,
        "generate_executable_test_source",
        lambda *args, **kwargs: _ai_response(
            links=[
                MethodLink(test_case_id="case-1", method="doesNotExist"),
                MethodLink(test_case_id="case-2", method="rejectsInvalidLogin"),
            ]
        ),
    )

    response = _generate(client)

    assert response.status_code == 502
    assert "doesNotExist" in response.json()["detail"]


def test_generate_persistence_failure_returns_500(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(
        executions_module,
        "generate_executable_test_source",
        lambda *args, **kwargs: _ai_response(),
    )

    async def failing_insert(document):
        raise RuntimeError("disk unavailable")

    class _FailingCollection:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        async def insert_one(self, document):
            return await failing_insert(document)

    class _FailingDB:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            if name == "executable_tests":
                return _FailingCollection(self._real.executable_tests)
            return getattr(self._real, name)

    db = get_db()
    monkeypatch.setattr(executions_module, "get_db", lambda: _FailingDB(db))

    response = _generate(client)

    assert response.status_code == 500
    assert "could not be saved" in response.json()["detail"]
