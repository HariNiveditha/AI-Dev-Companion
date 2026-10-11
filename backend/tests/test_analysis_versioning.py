"""Regression tests for static-analysis version tracking.

Covers the defects where selecting an older artifact version and re-running
static analysis silently analyzed the newest code instead, and where analysis
results carried no record of which version (or which sibling files) were
actually analyzed:
  * snapshot pins the selected file to the chosen version
  * sibling files fall back to their latest version
  * ``StaticAnalysisResult`` records ``version`` + ``analyzed_files``
  * legacy analysis documents (no version fields) still validate
  * analyzing an older version does not clobber the newer version's findings
"""

import asyncio
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import artifacts as artifact_routes
from app.db.mongodb import get_db
from app.main import app
from app.models.code_artifact import (
    AnalysisToolResult,
    AnalyzedFile,
    StaticAnalysisResult,
)


# ---------------------------------------------------------------------------
# Pure-logic tests for the analysis snapshot builder
# ---------------------------------------------------------------------------

class TestBuildAnalysisSnapshot:
    def _art(self, file_name, version, artifact_id=None):
        return {
            "artifact_id": artifact_id or f"{file_name}-v{version}",
            "file_name": file_name,
            "version": version,
            "content": f"// {file_name} v{version}",
        }

    def test_selected_version_is_pinned(self):
        """Selecting an older version analyzes that version, not the newest."""
        v1 = self._art("User.java", 1)
        v2 = self._art("User.java", 2)
        snapshot = artifact_routes._build_analysis_snapshot([v1, v2], v1)
        assert len(snapshot) == 1
        assert snapshot[0]["artifact_id"] == v1["artifact_id"]
        assert snapshot[0]["version"] == 1

    def test_sibling_files_use_latest(self):
        """Other files still contribute their newest version to the snapshot."""
        user_v1 = self._art("User.java", 1)
        helper_v1 = self._art("Helper.java", 1)
        helper_v2 = self._art("Helper.java", 2)
        snapshot = artifact_routes._build_analysis_snapshot(
            [user_v1, helper_v1, helper_v2], user_v1
        )
        by_file = {item["file_name"]: item for item in snapshot}
        assert by_file["User.java"]["version"] == 1
        assert by_file["Helper.java"]["version"] == 2

    def test_selected_latest_version_still_analyzed(self):
        """Pin is a no-op when the selected artifact already is the latest."""
        v1 = self._art("User.java", 1)
        v2 = self._art("User.java", 2)
        snapshot = artifact_routes._build_analysis_snapshot([v1, v2], v2)
        assert snapshot[0]["artifact_id"] == v2["artifact_id"]


# ---------------------------------------------------------------------------
# Model backward compatibility
# ---------------------------------------------------------------------------

class TestStaticAnalysisResultModel:
    def test_records_version_and_analyzed_files(self):
        result = StaticAnalysisResult(
            analysis_id=str(uuid4()),
            artifact_id="art-1",
            version=2,
            analyzed_files=[
                AnalyzedFile(artifact_id="art-1", file_name="User.java", version=2),
                AnalyzedFile(artifact_id="art-9", file_name="Helper.java", version=1),
            ],
            status="COMPLETED",
            checkstyle=AnalysisToolResult(status="COMPLETED", findings=[]),
            spotbugs=AnalysisToolResult(status="COMPLETED", findings=[]),
            security=AnalysisToolResult(status="COMPLETED", findings=[]),
            created_at=datetime.utcnow(),
        )
        assert result.version == 2
        assert [f.version for f in result.analyzed_files] == [2, 1]

    def test_legacy_document_without_version_fields_validates(self):
        """Documents persisted before version tracking was added still load."""
        legacy = {
            "analysis_id": str(uuid4()),
            "artifact_id": "art-legacy",
            "status": "COMPLETED",
            "checkstyle": {"status": "COMPLETED", "findings": []},
            "spotbugs": {"status": "COMPLETED", "findings": []},
            "security": {"status": "COMPLETED", "findings": []},
            "created_at": "2024-01-01T00:00:00",
        }
        result = StaticAnalysisResult.model_validate(legacy)
        assert result.version is None
        assert result.analyzed_files == []


# ---------------------------------------------------------------------------
# Endpoint-level test: analyzing an older version does not clobber newer results
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _reset():
    db = get_db()
    asyncio.run(db.requirements.delete_many({}))
    asyncio.run(db.code_artifacts.delete_many({}))
    asyncio.run(db.static_analysis_results.delete_many({}))
    asyncio.run(db.improvement_proposals.delete_many({}))


def _seed_two_versions(db):
    """Create User.java v1 (original) and v2 (accepted improvement)."""
    base = {
        "project_id": "proj-1",
        "requirement_id": "req-ver-1",
        "file_name": "User.java",
        "language": "Java",
        "source": "AI_GENERATED",
        "status": "AI_GENERATED",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    }
    asyncio.run(
        db.code_artifacts.insert_one(
            {**base, "artifact_id": "user-v1", "version": 1, "content": "// v1 original"}
        )
    )
    asyncio.run(
        db.code_artifacts.insert_one(
            {**base, "artifact_id": "user-v2", "version": 2, "content": "// v2 improved"}
        )
    )


def test_analyzing_older_version_pins_content_and_preserves_newer_result(
    client, monkeypatch
):
    """Regression: analyzing v1 after v2 exists must analyze v1's content and
    must not overwrite v2's stored findings."""
    _reset()
    db = get_db()
    _seed_two_versions(db)

    # Record what content each analysis actually wrote to disk.
    written = []

    def fake_write_sources(temp_dir, artifacts):
        written.append(sorted((a["file_name"], a["version"]) for a in artifacts))
        return []

    empty = AnalysisToolResult(status="COMPLETED", findings=[])
    monkeypatch.setattr(artifact_routes, "_write_sources", fake_write_sources)
    monkeypatch.setattr(artifact_routes, "_run_checkstyle", lambda *a, **k: empty)
    monkeypatch.setattr(artifact_routes, "_run_semgrep", lambda *a, **k: empty)
    monkeypatch.setattr(artifact_routes, "_run_spotbugs", lambda *a, **k: empty)
    # Prevent invoking the real javac binary during the test.
    monkeypatch.setattr(artifact_routes.shutil, "which", lambda *_a, **_k: None)

    # First, analyze the NEWEST version (v2) and store a sentinel finding.
    asyncio.run(
        db.static_analysis_results.insert_one(
            StaticAnalysisResult(
                analysis_id=str(uuid4()),
                artifact_id="user-v2",
                version=2,
                analyzed_files=[AnalyzedFile(artifact_id="user-v2", file_name="User.java", version=2)],
                status="COMPLETED",
                checkstyle=AnalysisToolResult(
                    status="COMPLETED",
                    findings=[{
                        "tool": "Checkstyle",
                        "severity": "WARNING",
                        "file": "User.java",
                        "line": 3,
                        "rule": "NeedBraces",
                        "message": "v2 sentinel finding",
                    }],
                ),
                spotbugs=empty,
                security=empty,
                created_at=datetime.utcnow(),
            ).model_dump()
        )
    )

    # Now analyze the OLDER version (v1).
    response = client.post("/artifacts/user-v1/analyze")
    assert response.status_code == 200
    payload = response.json()

    # The analysis is scoped to the selected version.
    assert payload["artifact_id"] == "user-v1"
    assert payload["version"] == 1
    assert payload["analyzed_files"] == [
        {"artifact_id": "user-v1", "file_name": "User.java", "version": 1}
    ]

    # The snapshot written to disk used v1's content, not the latest.
    assert written == [[("User.java", 1)]]

    # v2's stored result is untouched (historical findings preserved).
    v2_result = asyncio.run(
        db.static_analysis_results.find_one(
            {"artifact_id": "user-v2"}, sort=[("created_at", -1)]
        )
    )
    assert v2_result is not None
    assert v2_result["checkstyle"]["findings"][0]["message"] == "v2 sentinel finding"
