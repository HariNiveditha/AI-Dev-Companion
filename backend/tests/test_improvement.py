import asyncio
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import improvement as improvement_routes
from app.db.mongodb import get_db
from app.main import app
from app.models.code_artifact import (
    AnalysisFinding,
    AnalysisToolResult,
    CompileResult,
    StaticAnalysisResult,
)
from app.models.improvement import CodeImprovementResponse, ImprovementProposal


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _reset_collections():
    db = get_db()
    asyncio.run(db.improvement_proposals.delete_many({}))
    asyncio.run(db.code_artifacts.delete_many({}))
    asyncio.run(db.static_analysis_results.delete_many({}))
    asyncio.run(db.requirements.delete_many({}))


def _create_test_requirement(db, requirement_id="req-imp-1"):
    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": requirement_id,
                "projectId": "project-123",
                "title": "Login Service",
                "description": "Users should be able to log in securely.",
                "status": "CONFIRMED",
                "analysis": {},
            }
        )
    )


def _create_test_artifact(db, artifact_id="artifact-imp-1", requirement_id="req-imp-1"):
    asyncio.run(
        db.code_artifacts.insert_one(
            {
                "artifact_id": artifact_id,
                "project_id": "project-123",
                "requirement_id": requirement_id,
                "file_name": "LoginService.java",
                "language": "Java",
                "content": "package com.example;\n\npublic class LoginService {\n    public boolean login(String user, String pass) {\n        return true;\n    }\n}\n",
                "version": 1,
                "source": "AI_GENERATED",
                "status": "AI_GENERATED",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )


def _create_test_analysis(db, artifact_id="artifact-imp-1"):
    asyncio.run(
        db.static_analysis_results.insert_one(
            {
                "analysis_id": str(uuid4()),
                "artifact_id": artifact_id,
                "status": "COMPLETED",
                "checkstyle": {
                    "status": "COMPLETED",
                    "findings": [
                        {
                            "tool": "Checkstyle",
                            "severity": "WARNING",
                            "file": "LoginService.java",
                            "line": 4,
                            "column": 5,
                            "rule": "Indentation",
                            "message": "Incorrect indentation level",
                        }
                    ],
                },
                "spotbugs": {
                    "status": "COMPLETED",
                    "findings": [
                        {
                            "tool": "SpotBugs",
                            "severity": "HIGH",
                            "file": "LoginService.java",
                            "line": 5,
                            "rule": "DM_EXIT",
                            "message": "Method might exit while holding a lock",
                        }
                    ],
                },
                "security": {
                    "status": "COMPLETED",
                    "findings": [],
                },
                "created_at": "2024-01-01T00:00:00",
            }
        )
    )


def test_generate_improvement_creates_proposal(client, monkeypatch):
    _reset_collections()
    db = get_db()
    _create_test_requirement(db)
    _create_test_artifact(db)
    _create_test_analysis(db)

    fake_response = CodeImprovementResponse(
        improved_content="package com.example;\n\npublic class LoginService {\n    public boolean login(String user, String pass) {\n        // Fixed indentation\n        return user != null && pass != null;\n    }\n}\n",
        explanation="Fixed indentation and added null checks.",
        findings_addressed=["Indentation issue", "Potential null pointer"],
        non_actionable_findings=[],
    )
    monkeypatch.setattr(
        improvement_routes,
        "generate_code_improvement",
        lambda *args, **kwargs: fake_response,
    )

    response = client.post("/improvements/generate?artifact_id=artifact-imp-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "PENDING"
    assert payload["artifact_id"] == "artifact-imp-1"
    assert payload["file_name"] == "LoginService.java"
    assert len(payload["findings_addressed"]) >= 1
    assert payload["improved_content"] != payload["original_content"]


def test_generate_improvement_requires_analysis(client, monkeypatch):
    _reset_collections()
    db = get_db()
    _create_test_requirement(db)
    _create_test_artifact(db)
    # No analysis created

    response = client.post("/improvements/generate?artifact_id=artifact-imp-1")

    assert response.status_code == 400
    assert "analysis" in response.json()["detail"].lower()


def test_generate_improvement_requires_findings(client, monkeypatch):
    _reset_collections()
    db = get_db()
    _create_test_requirement(db)
    _create_test_artifact(db)

    # Create analysis with zero findings
    asyncio.run(
        db.static_analysis_results.insert_one(
            {
                "analysis_id": str(uuid4()),
                "artifact_id": "artifact-imp-1",
                "status": "COMPLETED",
                "checkstyle": {"status": "COMPLETED", "findings": []},
                "spotbugs": {"status": "COMPLETED", "findings": []},
                "security": {"status": "COMPLETED", "findings": []},
                "created_at": "2024-01-01T00:00:00",
            }
        )
    )

    response = client.post("/improvements/generate?artifact_id=artifact-imp-1")

    assert response.status_code == 400
    assert "zero findings" in response.json()["detail"].lower()


def test_generate_improvement_handles_ai_failure(client, monkeypatch):
    _reset_collections()
    db = get_db()
    _create_test_requirement(db)
    _create_test_artifact(db)
    _create_test_analysis(db)

    def raise_error(*args, **kwargs):
        raise RuntimeError("AI provider failed")

    monkeypatch.setattr(improvement_routes, "generate_code_improvement", raise_error)

    response = client.post("/improvements/generate?artifact_id=artifact-imp-1")

    assert response.status_code == 502
    assert "AI provider failed" in response.json()["detail"]


def test_generate_improvement_handles_missing_artifact(client):
    _reset_collections()

    response = client.post("/improvements/generate?artifact_id=nonexistent")

    assert response.status_code == 404


def test_accept_proposal_creates_new_version(client, monkeypatch):
    _reset_collections()
    db = get_db()
    _create_test_requirement(db)
    _create_test_artifact(db)
    _create_test_analysis(db)

    # Create a proposal directly
    proposal_id = str(uuid4())
    asyncio.run(
        db.improvement_proposals.insert_one(
            {
                "proposal_id": proposal_id,
                "artifact_id": "artifact-imp-1",
                "project_id": "project-123",
                "requirement_id": "req-imp-1",
                "file_name": "LoginService.java",
                "original_content": "package com.example;\n\npublic class LoginService {\n    public boolean login(String user, String pass) {\n        return true;\n    }\n}\n",
                "improved_content": "package com.example;\n\npublic class LoginService {\n    public boolean login(String user, String pass) {\n        return user != null;\n    }\n}\n",
                "explanation": "Fixed null check",
                "findings_addressed": [],
                "non_actionable_findings": [],
                "status": "PENDING",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )

    # Mock compile and analyze to avoid needing real tools
    async def mock_compile(artifact_id):
        return CompileResult(
            artifact_id=artifact_id,
            status="PASSED",
            exit_code=0,
            stdout="",
            stderr="",
            duration_ms=100,
            timestamp=datetime.utcnow(),
        )

    async def mock_analyze(artifact_id):
        return StaticAnalysisResult(
            analysis_id=str(uuid4()),
            artifact_id=artifact_id,
            status="COMPLETED",
            checkstyle=AnalysisToolResult(status="COMPLETED", findings=[]),
            spotbugs=AnalysisToolResult(status="COMPLETED", findings=[]),
            security=AnalysisToolResult(status="COMPLETED", findings=[]),
            created_at=datetime.utcnow(),
        )

    monkeypatch.setattr(improvement_routes, "_compile_artifact_internal", mock_compile)
    monkeypatch.setattr(improvement_routes, "_analyze_artifact_internal", mock_analyze)

    response = client.post(f"/improvements/{proposal_id}/accept")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ACCEPTED"
    assert payload["accepted_artifact_id"] is not None
    assert payload["accepted_version"] == 2
    assert payload["compile_result"]["status"] == "PASSED"

    # Verify original artifact is unchanged
    original = asyncio.run(
        db.code_artifacts.find_one({"artifact_id": "artifact-imp-1"})
    )
    assert original["content"] == "package com.example;\n\npublic class LoginService {\n    public boolean login(String user, String pass) {\n        return true;\n    }\n}\n"
    assert original["version"] == 1

    # Verify new version exists
    new_version = asyncio.run(
        db.code_artifacts.find_one({"artifact_id": payload["accepted_artifact_id"]})
    )
    assert new_version is not None
    assert new_version["version"] == 2


def test_accept_proposal_prevents_duplicate_acceptance(client, monkeypatch):
    _reset_collections()
    db = get_db()
    _create_test_requirement(db)
    _create_test_artifact(db)
    _create_test_analysis(db)

    proposal_id = str(uuid4())
    asyncio.run(
        db.improvement_proposals.insert_one(
            {
                "proposal_id": proposal_id,
                "artifact_id": "artifact-imp-1",
                "project_id": "project-123",
                "requirement_id": "req-imp-1",
                "file_name": "LoginService.java",
                "original_content": "original content",
                "improved_content": "improved content",
                "explanation": "Fix",
                "findings_addressed": [],
                "non_actionable_findings": [],
                "status": "ACCEPTED",
                "accepted_artifact_id": "new-artifact-id",
                "accepted_version": 2,
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
                "accepted_at": "2024-01-01T00:00:01",
            }
        )
    )

    response = client.post(f"/improvements/{proposal_id}/accept")

    assert response.status_code == 409
    assert "already been accepted" in response.json()["detail"]


def test_accept_proposal_prevents_stale_acceptance(client, monkeypatch):
    _reset_collections()
    db = get_db()
    _create_test_requirement(db)
    _create_test_artifact(db)
    _create_test_analysis(db)

    proposal_id = str(uuid4())
    asyncio.run(
        db.improvement_proposals.insert_one(
            {
                "proposal_id": proposal_id,
                "artifact_id": "artifact-imp-1",
                "project_id": "project-123",
                "requirement_id": "req-imp-1",
                "file_name": "LoginService.java",
                "original_content": "original content",
                "improved_content": "improved content",
                "explanation": "Fix",
                "findings_addressed": [],
                "non_actionable_findings": [],
                "status": "PENDING",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )

    # Modify the original artifact after proposal creation
    asyncio.run(
        db.code_artifacts.update_one(
            {"artifact_id": "artifact-imp-1"},
            {"$set": {"content": "modified content"}},
        )
    )

    response = client.post(f"/improvements/{proposal_id}/accept")

    assert response.status_code == 409
    assert "changed since the proposal was generated" in response.json()["detail"]


def test_reject_proposal_preserves_original(client):
    _reset_collections()
    db = get_db()
    _create_test_requirement(db)
    _create_test_artifact(db)
    _create_test_analysis(db)

    proposal_id = str(uuid4())
    asyncio.run(
        db.improvement_proposals.insert_one(
            {
                "proposal_id": proposal_id,
                "artifact_id": "artifact-imp-1",
                "project_id": "project-123",
                "requirement_id": "req-imp-1",
                "file_name": "LoginService.java",
                "original_content": "original content",
                "improved_content": "improved content",
                "explanation": "Fix",
                "findings_addressed": [],
                "non_actionable_findings": [],
                "status": "PENDING",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )

    response = client.post(f"/improvements/{proposal_id}/reject")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "REJECTED"
    assert payload["rejected_at"] is not None

    # Verify original artifact is unchanged
    original = asyncio.run(
        db.code_artifacts.find_one({"artifact_id": "artifact-imp-1"})
    )
    assert original["content"] == "package com.example;\n\npublic class LoginService {\n    public boolean login(String user, String pass) {\n        return true;\n    }\n}\n"

    # Verify no new artifact was created
    all_artifacts = asyncio.run(
        db.code_artifacts.find({"requirement_id": "req-imp-1"}).to_list(10)
    )
    assert len(all_artifacts) == 1


def test_reject_proposal_prevents_duplicate_rejection(client):
    _reset_collections()
    db = get_db()
    _create_test_requirement(db)
    _create_test_artifact(db)
    _create_test_analysis(db)

    proposal_id = str(uuid4())
    asyncio.run(
        db.improvement_proposals.insert_one(
            {
                "proposal_id": proposal_id,
                "artifact_id": "artifact-imp-1",
                "project_id": "project-123",
                "requirement_id": "req-imp-1",
                "file_name": "LoginService.java",
                "original_content": "original content",
                "improved_content": "improved content",
                "explanation": "Fix",
                "findings_addressed": [],
                "non_actionable_findings": [],
                "status": "REJECTED",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
                "rejected_at": "2024-01-01T00:00:01",
            }
        )
    )

    response = client.post(f"/improvements/{proposal_id}/reject")

    assert response.status_code == 409
    assert "already been rejected" in response.json()["detail"]


def test_get_proposal_returns_proposal(client):
    _reset_collections()
    db = get_db()
    _create_test_requirement(db)
    _create_test_artifact(db)
    _create_test_analysis(db)

    proposal_id = str(uuid4())
    asyncio.run(
        db.improvement_proposals.insert_one(
            {
                "proposal_id": proposal_id,
                "artifact_id": "artifact-imp-1",
                "project_id": "project-123",
                "requirement_id": "req-imp-1",
                "file_name": "LoginService.java",
                "original_content": "original content",
                "improved_content": "improved content",
                "explanation": "Fix",
                "findings_addressed": [],
                "non_actionable_findings": [],
                "status": "PENDING",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )

    response = client.get(f"/improvements/{proposal_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["proposal_id"] == proposal_id
    assert payload["status"] == "PENDING"


def test_get_proposal_returns_404_for_missing(client):
    _reset_collections()

    response = client.get("/improvements/nonexistent")

    assert response.status_code == 404


def test_get_diff_returns_unified_diff(client):
    _reset_collections()
    db = get_db()
    _create_test_requirement(db)
    _create_test_artifact(db)
    _create_test_analysis(db)

    proposal_id = str(uuid4())
    asyncio.run(
        db.improvement_proposals.insert_one(
            {
                "proposal_id": proposal_id,
                "artifact_id": "artifact-imp-1",
                "project_id": "project-123",
                "requirement_id": "req-imp-1",
                "file_name": "LoginService.java",
                "original_content": "line 1\nline 2\nline 3",
                "improved_content": "line 1\nline 2 modified\nline 3",
                "explanation": "Modified line 2",
                "findings_addressed": [],
                "non_actionable_findings": [],
                "status": "PENDING",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )

    response = client.get(f"/improvements/{proposal_id}/diff")

    assert response.status_code == 200
    payload = response.json()
    assert "diff" in payload
    assert "-line 2" in payload["diff"]
    assert "+line 2 modified" in payload["diff"]


def test_comparison_shows_resolved_findings(client):
    _reset_collections()
    db = get_db()
    _create_test_requirement(db)
    _create_test_artifact(db)
    _create_test_analysis(db)

    # Create a proposal
    proposal_id = str(uuid4())
    asyncio.run(
        db.improvement_proposals.insert_one(
            {
                "proposal_id": proposal_id,
                "artifact_id": "artifact-imp-1",
                "project_id": "project-123",
                "requirement_id": "req-imp-1",
                "file_name": "LoginService.java",
                "original_content": "original content",
                "improved_content": "improved content",
                "explanation": "Fix",
                "findings_addressed": [],
                "non_actionable_findings": [],
                "status": "ACCEPTED",
                "accepted_artifact_id": "artifact-imp-2",
                "accepted_version": 2,
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
                "accepted_at": "2024-01-01T00:00:01",
            }
        )
    )

    # Create improved artifact
    asyncio.run(
        db.code_artifacts.insert_one(
            {
                "artifact_id": "artifact-imp-2",
                "project_id": "project-123",
                "requirement_id": "req-imp-1",
                "file_name": "LoginService.java",
                "language": "Java",
                "content": "improved content",
                "version": 2,
                "source": "DEVELOPER_EDITED",
                "status": "EDITED",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )

    # Create improved analysis with fewer findings
    asyncio.run(
        db.static_analysis_results.insert_one(
            {
                "analysis_id": str(uuid4()),
                "artifact_id": "artifact-imp-2",
                "status": "COMPLETED",
                "checkstyle": {"status": "COMPLETED", "findings": []},
                "spotbugs": {"status": "COMPLETED", "findings": []},
                "security": {"status": "COMPLETED", "findings": []},
                "created_at": "2024-01-01T00:00:00",
            }
        )
    )

    response = client.get(f"/improvements/{proposal_id}/comparison")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_before"] == 2
    assert payload["total_after"] == 0
    assert len(payload["findings_resolved"]) == 2
    assert len(payload["findings_remaining"]) == 0
