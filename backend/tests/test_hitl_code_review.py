import asyncio
from datetime import datetime
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
from app.models.improvement import FindingAssessment, ImprovementProposal


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


def _setup_project_data(db):
    req_id = "req-hitl-1"
    art_id = "art-hitl-1"
    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": req_id,
                "projectId": "proj-hitl-1",
                "title": "Auth Manager",
                "description": "Authenticate users securely.",
                "status": "CONFIRMED",
            }
        )
    )
    asyncio.run(
        db.code_artifacts.insert_one(
            {
                "artifact_id": art_id,
                "project_id": "proj-hitl-1",
                "requirement_id": req_id,
                "file_name": "AuthManager.java",
                "language": "Java",
                "content": "package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return true;\n    }\n}\n",
                "version": 1,
                "source": "AI_GENERATED",
                "status": "AI_GENERATED",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )
    )
    return req_id, art_id


def test_retrieve_pending_proposal_with_finding_assessments(client):
    """1. Retrieving a pending proposal with its finding assessments."""
    _reset_collections()
    db = get_db()
    req_id, art_id = _setup_project_data(db)

    proposal_id = str(uuid4())
    assessments = [
        FindingAssessment(finding_id="F1", classification="ACTIONABLE", reasoning="Null check needed"),
        FindingAssessment(finding_id="F2", classification="NON_ACTIONABLE", reasoning="False positive"),
        FindingAssessment(finding_id="F3", classification="NEEDS_CONTEXT", reasoning="Requires auth config context"),
    ]
    finding1 = AnalysisFinding(tool="Checkstyle", severity="INFO", file="AuthManager.java", line=4, message="Check null")
    finding2 = AnalysisFinding(tool="SpotBugs", severity="LOW", file="AuthManager.java", line=4, message="Unused param")
    finding3 = AnalysisFinding(tool="Semgrep", severity="MEDIUM", file="AuthManager.java", line=4, message="Hardcoded check")

    proposal = ImprovementProposal(
        proposal_id=proposal_id,
        artifact_id=art_id,
        project_id="proj-hitl-1",
        requirement_id=req_id,
        file_name="AuthManager.java",
        original_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return true;\n    }\n}\n",
        improved_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return u != null && p != null;\n    }\n}\n",
        explanation="Added null checks",
        findings_addressed=[finding1],
        non_actionable_findings=[finding2, finding3],
        finding_assessments=assessments,
        status="PENDING",
        source_version=1,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    asyncio.run(db.improvement_proposals.insert_one(proposal.model_dump()))

    response = client.get(f"/improvements/{proposal_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["proposal_id"] == proposal_id
    assert data["status"] == "PENDING"
    assert data["source_version"] == 1
    assert len(data["finding_assessments"]) == 3
    classifications = {a["classification"] for a in data["finding_assessments"]}
    assert classifications == {"ACTIONABLE", "NON_ACTIONABLE", "NEEDS_CONTEXT"}


def test_accept_valid_proposal_with_comment_and_reviewer(client, monkeypatch):
    """2. Accepting a valid source-changing proposal with reviewer metadata."""
    _reset_collections()
    db = get_db()
    req_id, art_id = _setup_project_data(db)

    proposal_id = str(uuid4())
    proposal = ImprovementProposal(
        proposal_id=proposal_id,
        artifact_id=art_id,
        project_id="proj-hitl-1",
        requirement_id=req_id,
        file_name="AuthManager.java",
        original_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return true;\n    }\n}\n",
        improved_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return u != null && p != null;\n    }\n}\n",
        explanation="Added null checks",
        status="PENDING",
        source_version=1,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    asyncio.run(db.improvement_proposals.insert_one(proposal.model_dump()))

    async def mock_compile(aid):
        return CompileResult(
            artifact_id=aid,
            status="PASSED",
            exit_code=0,
            stdout="",
            stderr="",
            duration_ms=50,
            timestamp=datetime.utcnow(),
        )

    async def mock_analyze(aid):
        return StaticAnalysisResult(
            analysis_id=str(uuid4()),
            artifact_id=aid,
            status="COMPLETED",
            checkstyle=AnalysisToolResult(status="COMPLETED", findings=[]),
            spotbugs=AnalysisToolResult(status="COMPLETED", findings=[]),
            security=AnalysisToolResult(status="COMPLETED", findings=[]),
            created_at=datetime.utcnow(),
        )

    monkeypatch.setattr(improvement_routes, "_compile_artifact_internal", mock_compile)
    monkeypatch.setattr(improvement_routes, "_analyze_artifact_internal", mock_analyze)

    payload = {"comment": "Approved following review of null checks.", "reviewer": "developer-alice"}
    response = client.post(f"/improvements/{proposal_id}/accept", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "ACCEPTED"
    assert res["review_action"] == "APPROVE"
    assert res["review_comment"] == "Approved following review of null checks."
    assert res["reviewer"] == "developer-alice"
    assert res["decision_timestamp"] is not None
    assert res["accepted_version"] == 2
    assert res["accepted_artifact_id"] is not None

    # Verify database has exactly version 1 and version 2
    artifacts = asyncio.run(db.code_artifacts.find({"file_name": "AuthManager.java"}).sort("version", 1).to_list(10))
    assert len(artifacts) == 2
    assert artifacts[0]["version"] == 1
    assert artifacts[1]["version"] == 2
    assert artifacts[1]["artifact_id"] == res["accepted_artifact_id"]


def test_reject_pending_proposal_with_comment(client):
    """3. Rejecting a pending proposal with a comment."""
    _reset_collections()
    db = get_db()
    req_id, art_id = _setup_project_data(db)

    proposal_id = str(uuid4())
    proposal = ImprovementProposal(
        proposal_id=proposal_id,
        artifact_id=art_id,
        project_id="proj-hitl-1",
        requirement_id=req_id,
        file_name="AuthManager.java",
        original_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return true;\n    }\n}\n",
        improved_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return false;\n    }\n}\n",
        explanation="Rejectable change",
        status="PENDING",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    asyncio.run(db.improvement_proposals.insert_one(proposal.model_dump()))

    payload = {"comment": "Rejection: Always returning false breaks functionality.", "reviewer": "reviewer-bob"}
    response = client.post(f"/improvements/{proposal_id}/reject", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "REJECTED"
    assert data["review_action"] == "REJECT"
    assert data["review_comment"] == "Rejection: Always returning false breaks functionality."
    assert data["reviewer"] == "reviewer-bob"
    assert data["rejected_at"] is not None
    assert data["decision_timestamp"] is not None

    # Verify no new artifact was created
    artifacts = asyncio.run(db.code_artifacts.find({"file_name": "AuthManager.java"}).to_list(10))
    assert len(artifacts) == 1
    assert artifacts[0]["version"] == 1


def test_repeated_acceptance_prevents_duplicate_versions(client, monkeypatch):
    """4. Repeated acceptance without duplicate artifact versions."""
    _reset_collections()
    db = get_db()
    req_id, art_id = _setup_project_data(db)

    proposal_id = str(uuid4())
    proposal = ImprovementProposal(
        proposal_id=proposal_id,
        artifact_id=art_id,
        project_id="proj-hitl-1",
        requirement_id=req_id,
        file_name="AuthManager.java",
        original_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return true;\n    }\n}\n",
        improved_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return u != null;\n    }\n}\n",
        explanation="Fix",
        status="PENDING",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    asyncio.run(db.improvement_proposals.insert_one(proposal.model_dump()))

    async def mock_compile(aid):
        return CompileResult(artifact_id=aid, status="PASSED", exit_code=0, stdout="", stderr="", duration_ms=10, timestamp=datetime.utcnow())

    async def mock_analyze(aid):
        return StaticAnalysisResult(
            analysis_id=str(uuid4()), artifact_id=aid, status="COMPLETED",
            checkstyle=AnalysisToolResult(status="COMPLETED", findings=[]),
            spotbugs=AnalysisToolResult(status="COMPLETED", findings=[]),
            security=AnalysisToolResult(status="COMPLETED", findings=[]),
            created_at=datetime.utcnow(),
        )

    monkeypatch.setattr(improvement_routes, "_compile_artifact_internal", mock_compile)
    monkeypatch.setattr(improvement_routes, "_analyze_artifact_internal", mock_analyze)

    # First accept: 200
    res1 = client.post(f"/improvements/{proposal_id}/accept")
    assert res1.status_code == 200

    # Second accept: 409 Conflict
    res2 = client.post(f"/improvements/{proposal_id}/accept")
    assert res2.status_code == 409
    assert "already been accepted" in res2.json()["detail"].lower()

    # Verify exactly 2 artifact versions exist (v1 and v2), no duplicate v3
    artifacts = asyncio.run(db.code_artifacts.find({"file_name": "AuthManager.java"}).to_list(10))
    assert len(artifacts) == 2


def test_terminal_proposals_cannot_be_modified(client):
    """5. Rejecting or accepting an already-terminal proposal."""
    _reset_collections()
    db = get_db()
    req_id, art_id = _setup_project_data(db)

    # Create an ACCEPTED proposal
    accepted_id = str(uuid4())
    p_accepted = ImprovementProposal(
        proposal_id=accepted_id, artifact_id=art_id, project_id="proj-hitl-1", requirement_id=req_id,
        file_name="AuthManager.java", original_content="x", improved_content="y", explanation="z",
        status="ACCEPTED", created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    # Create a REJECTED proposal
    rejected_id = str(uuid4())
    p_rejected = ImprovementProposal(
        proposal_id=rejected_id, artifact_id=art_id, project_id="proj-hitl-1", requirement_id=req_id,
        file_name="AuthManager.java", original_content="x", improved_content="y", explanation="z",
        status="REJECTED", created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    asyncio.run(db.improvement_proposals.insert_many([p_accepted.model_dump(), p_rejected.model_dump()]))

    # Rejecting an ACCEPTED proposal -> 409
    res_reject_accepted = client.post(f"/improvements/{accepted_id}/reject")
    assert res_reject_accepted.status_code == 409

    # Accepting a REJECTED proposal -> 409
    res_accept_rejected = client.post(f"/improvements/{rejected_id}/accept")
    assert res_accept_rejected.status_code == 409

    # Rejecting an already REJECTED proposal -> 409
    res_reject_rejected = client.post(f"/improvements/{rejected_id}/reject")
    assert res_reject_rejected.status_code == 409


def test_no_change_proposal_is_read_only_terminal(client):
    """6. Attempting to accept or reject a NO_CHANGE proposal."""
    _reset_collections()
    db = get_db()
    req_id, art_id = _setup_project_data(db)

    no_change_id = str(uuid4())
    p_no_change = ImprovementProposal(
        proposal_id=no_change_id, artifact_id=art_id, project_id="proj-hitl-1", requirement_id=req_id,
        file_name="AuthManager.java",
        original_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return true;\n    }\n}\n",
        improved_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return true;\n    }\n}\n",
        explanation="Review completed — no source change recommended.",
        status="NO_CHANGE",
        review_action="NO_CHANGE",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    asyncio.run(db.improvement_proposals.insert_one(p_no_change.model_dump()))

    # Accepting NO_CHANGE -> 409 Conflict
    res_accept = client.post(f"/improvements/{no_change_id}/accept")
    assert res_accept.status_code == 409
    assert "no_change" in res_accept.json()["detail"].lower()

    # Rejecting NO_CHANGE -> 409 Conflict
    res_reject = client.post(f"/improvements/{no_change_id}/reject")
    assert res_reject.status_code == 409
    assert "no_change" in res_reject.json()["detail"].lower()

    # Verify no new artifact versions created
    artifacts = asyncio.run(db.code_artifacts.find({"file_name": "AuthManager.java"}).to_list(10))
    assert len(artifacts) == 1


def test_stale_source_artifact_version_conflict(client):
    """7. Stale source/artifact version conflicts prevent silent overwrite."""
    _reset_collections()
    db = get_db()
    req_id, art_id = _setup_project_data(db)

    proposal_id = str(uuid4())
    proposal = ImprovementProposal(
        proposal_id=proposal_id,
        artifact_id=art_id,
        project_id="proj-hitl-1",
        requirement_id=req_id,
        file_name="AuthManager.java",
        original_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return true;\n    }\n}\n",
        improved_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return u != null;\n    }\n}\n",
        explanation="Fix",
        status="PENDING",
        source_version=1,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    asyncio.run(db.improvement_proposals.insert_one(proposal.model_dump()))

    # Simulate another edit creating version 2 of AuthManager.java
    asyncio.run(
        db.code_artifacts.insert_one(
            {
                "artifact_id": "art-hitl-2",
                "project_id": "proj-hitl-1",
                "requirement_id": req_id,
                "file_name": "AuthManager.java",
                "language": "Java",
                "content": "package com.example;\n\npublic class AuthManager {\n    // Newer version\n}\n",
                "version": 2,
                "source": "DEVELOPER_EDITED",
                "status": "EDITED",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )
    )

    # Attempting to accept proposal that was based on version 1 should fail with 409
    res = client.post(f"/improvements/{proposal_id}/accept")
    assert res.status_code == 409
    assert "evolved to version 2" in res.json()["detail"] or "changed" in res.json()["detail"].lower()


def test_validation_failure_prevents_persistence(client):
    """8. Validation failure without partial persistence."""
    _reset_collections()
    db = get_db()
    req_id, art_id = _setup_project_data(db)

    proposal_id = str(uuid4())
    # Proposed content is invalid Java (unclosed braces, syntax error)
    invalid_content = "package com.example;\npublic class AuthManager { unclosed syntax error {{{ "
    proposal = ImprovementProposal(
        proposal_id=proposal_id,
        artifact_id=art_id,
        project_id="proj-hitl-1",
        requirement_id=req_id,
        file_name="AuthManager.java",
        original_content="package com.example;\n\npublic class AuthManager {\n    public boolean auth(String u, String p) {\n        return true;\n    }\n}\n",
        improved_content=invalid_content,
        explanation="Attempted invalid syntax fix",
        status="PENDING",
        source_version=1,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    asyncio.run(db.improvement_proposals.insert_one(proposal.model_dump()))

    # Accept should fail with 422 Unprocessable Entity
    res = client.post(f"/improvements/{proposal_id}/accept")
    assert res.status_code == 422
    assert "validation" in res.json()["detail"].lower()

    # Proposal remains PENDING in database
    p_doc = asyncio.run(db.improvement_proposals.find_one({"proposal_id": proposal_id}))
    assert p_doc["status"] == "PENDING"

    # No new artifact created
    artifacts = asyncio.run(db.code_artifacts.find({"file_name": "AuthManager.java"}).to_list(10))
    assert len(artifacts) == 1
    assert artifacts[0]["version"] == 1


def test_list_proposals_history(client):
    """12. Retrieving proposal history by artifact and requirement."""
    _reset_collections()
    db = get_db()
    req_id, art_id = _setup_project_data(db)

    p1_id = str(uuid4())
    p2_id = str(uuid4())
    asyncio.run(
        db.improvement_proposals.insert_many(
            [
                {
                    "proposal_id": p1_id,
                    "artifact_id": art_id,
                    "project_id": "proj-hitl-1",
                    "requirement_id": req_id,
                    "file_name": "AuthManager.java",
                    "original_content": "v1",
                    "improved_content": "v2",
                    "explanation": "Proposal 1",
                    "status": "ACCEPTED",
                    "created_at": datetime(2026, 1, 1, 10, 0, 0),
                    "updated_at": datetime(2026, 1, 1, 10, 5, 0),
                },
                {
                    "proposal_id": p2_id,
                    "artifact_id": art_id,
                    "project_id": "proj-hitl-1",
                    "requirement_id": req_id,
                    "file_name": "AuthManager.java",
                    "original_content": "v2",
                    "improved_content": "v3",
                    "explanation": "Proposal 2",
                    "status": "PENDING",
                    "created_at": datetime(2026, 1, 2, 10, 0, 0),
                    "updated_at": datetime(2026, 1, 2, 10, 0, 0),
                },
            ]
        )
    )

    res = client.get(f"/improvements?artifact_id={art_id}")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 2
    # Newest first
    assert items[0]["proposal_id"] == p2_id
    assert items[1]["proposal_id"] == p1_id
