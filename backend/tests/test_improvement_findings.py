"""Regression tests for the static-analysis -> AI improvement pipeline.

Guards the root cause where findings were sent to the AI without the source of
the files they reference, so the AI could not fix them and the endpoint wrongly
claimed "all findings may be non-actionable".
"""

import asyncio
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import improvement as improvement_routes
from app.db.mongodb import get_db
from app.main import app
from app.models.code_artifact import (
    AnalysisToolResult,
    CompileResult,
    StaticAnalysisResult,
)
from app.models.improvement import CodeImprovementResponse, FindingAssessment
from app.services.ai import prompts as prompts_module


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _reset():
    db = get_db()
    for col in ["improvement_proposals", "code_artifacts", "static_analysis_results", "requirements"]:
        asyncio.run(getattr(db, col).delete_many({}))


def _requirement(db):
    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": "req-r1",
                "projectId": "proj-r1",
                "title": "Food Ordering System",
                "description": "Users register, log in, and order food.",
                "status": "CONFIRMED",
                "analysis": {},
            }
        )
    )


USER_SRC = (
    "package com.auth.model;\n\npublic class User {\n"
    "    private String username;\n    private String email;\n\n    public String getUsername() {\n        return username;\n    }\n}\n"
)
PASS_SRC = (
    "package com.auth.util;\n\nimport java.security.MessageDigest;\n\npublic class PasswordUtil {\n"
    "    public static String hashPassword(String password) {\n"
    "        try {\n            return MessageDigest.getInstance(\"SHA-256\").toString();\n"
    "        } catch (Exception e) {\n            throw new RuntimeException(\"boom\", e);\n        }\n    }\n}\n"
)
AUTH_SRC = (
    "package com.auth.service;\n\nimport com.auth.model.User;\nimport com.auth.util.PasswordUtil;\n\npublic class AuthService {\n"
    "    public boolean register(String email, String password) {\n"
    "        String hash = PasswordUtil.hashPassword(password);\n        return hash != null;\n    }\n}\n"
)


def _three_artifacts(db):
    """AuthService selected; findings live in User.java + PasswordUtil.java."""
    ids = {}
    for name, src in [("User.java", USER_SRC), ("PasswordUtil.java", PASS_SRC), ("AuthService.java", AUTH_SRC)]:
        aid = str(uuid4())
        ids[name] = aid
        asyncio.run(
            db.code_artifacts.insert_one(
                {
                    "artifact_id": aid,
                    "project_id": "proj-r1",
                    "requirement_id": "req-r1",
                    "file_name": name,
                    "language": "Java",
                    "content": src,
                    "version": 1,
                    "source": "AI_GENERATED",
                    "status": "AI_GENERATED",
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
            )
        )
    return ids


def _cross_file_analysis(db, artifact_id, ids):
    """Real-shaped findings: Checkstyle in User.java, SpotBugs in PasswordUtil.java."""
    asyncio.run(
        db.static_analysis_results.insert_one(
            {
                "analysis_id": str(uuid4()),
                "artifact_id": artifact_id,
                "version": 1,
                "analyzed_files": [
                    {"artifact_id": ids[n], "file_name": n, "version": 1}
                    for n in ["User.java", "PasswordUtil.java", "AuthService.java"]
                ],
                "status": "COMPLETED",
                "checkstyle": {
                    "status": "COMPLETED",
                    "findings": [
                        {
                            "tool": "Checkstyle",
                            "severity": "ERROR",
                            "file": "User.java",
                            "line": 4,
                            "column": 5,
                            "rule": "com.puppycrawl.tools.checkstyle.checks.whitespace.EmptyLineSeparatorCheck",
                            "message": "'VARIABLE_DEF' should be separated from previous line.",
                        }
                    ],
                },
                "spotbugs": {
                    "status": "COMPLETED",
                    "findings": [
                        {
                            "tool": "SpotBugs",
                            "severity": "LOW",
                            "file": "PasswordUtil.java",
                            "line": 6,
                            "column": None,
                            "rule": "THROWS_METHOD_THROWS_RUNTIMEEXCEPTION",
                            "message": "THROWS_METHOD_THROWS_RUNTIMEEXCEPTION",
                        }
                    ],
                },
                "security": {"status": "COMPLETED", "findings": []},
                "created_at": "2026-01-01T00:00:00",
            }
        )
    )


def _capture(monkeypatch, response):
    """Capture the prompt + source_files handed to the AI and return the response."""
    captured = {}

    def fake_generate(title, description, source_files, findings, target_file):
        captured["source_files"] = source_files
        captured["findings"] = findings
        captured["target_file"] = target_file
        captured["prompt"] = prompts_module.get_code_improvement_prompt(
            title, description, source_files, findings, target_file
        )
        return response

    monkeypatch.setattr(improvement_routes, "generate_code_improvement", fake_generate)
    return captured


# --- Part 1/2: findings + their files must reach the AI ---

def test_findings_and_their_file_sources_reach_the_ai(client, monkeypatch):
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["AuthService.java"], ids)

    # Genuinely different from AUTH_SRC so the no-change guard is not tripped.
    improved_auth = AUTH_SRC.replace(
        "public class AuthService {\n    public boolean register",
        "public class AuthService {\n\n    public boolean register",
    )
    response = CodeImprovementResponse(
        improved_content=improved_auth,
        explanation="User.java needs a blank line; SpotBugs rule is out of scope for this file.",
        findings_addressed=[],
        non_actionable_findings=["SpotBugs runtime-exception is deliberate"],
        addressed_finding_ids=[],
        finding_assessments=[
            FindingAssessment(finding_id="F1", classification="NEEDS_CONTEXT", reasoning="Finding is in User.java, not the selected file."),
            FindingAssessment(finding_id="F2", classification="NON_ACTIONABLE", reasoning="Throwing RuntimeException is intentional."),
        ],
    )
    captured = _capture(monkeypatch, response)

    resp = client.post(f"/improvements/generate?artifact_id={ids['AuthService.java']}")
    assert resp.status_code == 200

    # The selected file is marked as the one to improve.
    assert captured["target_file"] == "AuthService.java"
    # Every file the findings reference is included, with its exact source.
    assert captured["source_files"]["User.java"] == USER_SRC
    assert captured["source_files"]["PasswordUtil.java"] == PASS_SRC
    assert captured["source_files"]["AuthService.java"] == AUTH_SRC

    # Findings carry stable IDs plus file/line/rule/message/severity.
    rules = {f["rule"] for f in captured["findings"]}
    assert any("EmptyLineSeparatorCheck" in r for r in rules)
    assert "THROWS_METHOD_THROWS_RUNTIMEEXCEPTION" in rules
    for f in captured["findings"]:
        assert f["finding_id"].startswith("F")
        assert f["file"] and f["severity"] and f["message"]

    # The rendered prompt embeds the actual sources and finding metadata.
    prompt = captured["prompt"]
    assert "private String username;" in prompt
    assert "throw new RuntimeException" in prompt
    assert "EmptyLineSeparatorCheck" in prompt
    # The selected file is marked, but the model is told it may target the
    # file where a finding actually lives rather than the selected file.
    assert "currently selected by the user" in prompt
    assert "target_file" in prompt


def test_actionable_finding_produces_proposal_and_maps_by_id(client, monkeypatch):
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["User.java"], ids)

    # AI fixes User.java by inserting the required blank line.
    improved_user = USER_SRC.replace(
        "public class User {\n    private String username;",
        "public class User {\n\n    private String username;",
    )
    response = CodeImprovementResponse(
        improved_content=improved_user,
        explanation="Inserted a blank line before the field (F1) per EmptyLineSeparatorCheck.",
        findings_addressed=["Blank line before VARIABLE_DEF in User.java"],
        non_actionable_findings=["SpotBugs rule targets another file"],
        addressed_finding_ids=["F1"],
        finding_assessments=[
            FindingAssessment(finding_id="F1", classification="ACTIONABLE", reasoning="Blank line inserted."),
            FindingAssessment(finding_id="F2", classification="NEEDS_CONTEXT", reasoning="PasswordUtil.java not selected."),
        ],
    )
    _capture(monkeypatch, response)

    resp = client.post(f"/improvements/generate?artifact_id={ids['User.java']}")
    assert resp.status_code == 200
    payload = resp.json()

    # Concrete proposal, addressed finding tied to the Checkstyle rule.
    assert payload["improved_content"] == improved_user
    assert payload["improved_content"] != payload["original_content"]
    assert len(payload["findings_addressed"]) == 1
    assert "EmptyLineSeparatorCheck" in payload["findings_addressed"][0]["rule"]
    # The SpotBugs finding is preserved honestly, not dropped.
    assert len(payload["non_actionable_findings"]) == 1
    assert payload["non_actionable_findings"][0]["rule"] == "THROWS_METHOD_THROWS_RUNTIMEEXCEPTION"


# --- Part 3: no-change vs malformed vs failed must be distinct ---

def test_valid_no_change_response_returns_no_change_proposal(client, monkeypatch):
    """A valid review with no safe change is a 200 NO_CHANGE proposal, not an error."""
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["User.java"], ids)

    # Valid response, but identical source and an explicit per-finding verdict.
    response = CodeImprovementResponse(
        improved_content=USER_SRC,
        explanation="Could not safely change.",
        findings_addressed=[],
        non_actionable_findings=[],
        addressed_finding_ids=[],
        finding_assessments=[
            FindingAssessment(finding_id="F1", classification="NEEDS_CONTEXT", reasoning="Need project style config."),
            FindingAssessment(finding_id="F2", classification="NON_ACTIONABLE", reasoning="Intentional throw."),
        ],
    )
    _capture(monkeypatch, response)

    resp = client.post(f"/improvements/generate?artifact_id={ids['User.java']}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "NO_CHANGE"
    assert payload["improved_content"] == payload["original_content"]
    # The AI's own verdicts stay visible on the persisted record.
    verdicts = {a["finding_id"]: a for a in payload["finding_assessments"]}
    assert verdicts["F1"]["classification"] == "NEEDS_CONTEXT"
    assert verdicts["F2"]["classification"] == "NON_ACTIONABLE"
    assert "Intentional throw." in verdicts["F2"]["reasoning"]
    # Nothing was addressed (no code changed); every finding stays on record.
    assert payload["findings_addressed"] == []
    assert len(payload["non_actionable_findings"]) == 2
    # No new artifact version was created.
    versions = asyncio.run(
        db.code_artifacts.find({"file_name": "User.java"}).to_list(10)
    )
    assert len(versions) == 1
    # The analyzer findings themselves are untouched.
    analysis = asyncio.run(
        db.static_analysis_results.find_one({"artifact_id": ids["User.java"]})
    )
    total = sum(
        len((analysis.get(tool) or {}).get("findings", []))
        for tool in ("checkstyle", "spotbugs", "security")
    )
    assert total == 2


def test_malformed_ai_response_is_not_treated_as_non_actionable(client, monkeypatch):
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["User.java"], ids)

    def broken(*args, **kwargs):
        raise RuntimeError("AI Provider failed: unparseable output")

    monkeypatch.setattr(improvement_routes, "generate_code_improvement", broken)

    resp = client.post(f"/improvements/generate?artifact_id={ids['User.java']}")
    assert resp.status_code == 502
    assert "unparseable" in resp.json()["detail"]
    assert asyncio.run(db.improvement_proposals.find({}).to_list(10)) == []


def test_malformed_java_is_rejected_without_persisting_proposal(client, monkeypatch):
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["User.java"], ids)

    # Unbalanced braces: structural validation must reject it.
    bad_java = "package com.auth.model;\n\npublic class User {\n    private String username;\n"
    response = CodeImprovementResponse(
        improved_content=bad_java,
        explanation="Trimmed the file.",
        findings_addressed=[],
        non_actionable_findings=[],
        addressed_finding_ids=["F1"],
        finding_assessments=[FindingAssessment(finding_id="F1", classification="ACTIONABLE", reasoning="x")],
    )
    _capture(monkeypatch, response)

    resp = client.post(f"/improvements/generate?artifact_id={ids['User.java']}")
    assert resp.status_code == 502
    assert "invalid Java" in resp.json()["detail"]
    assert asyncio.run(db.improvement_proposals.find({}).to_list(10)) == []


def test_unknown_finding_ids_do_not_mark_findings_addressed(client, monkeypatch):
    """IDs the backend never issued must not silently resolve findings."""
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["User.java"], ids)

    improved_user = USER_SRC + "\n// comment\n"
    response = CodeImprovementResponse(
        improved_content=improved_user,
        explanation="Made a change.",
        findings_addressed=["something"],
        non_actionable_findings=[],
        addressed_finding_ids=["F99"],  # not a real ID
        finding_assessments=[
            FindingAssessment(finding_id="F99", classification="ACTIONABLE", reasoning="phantom"),
        ],
    )
    _capture(monkeypatch, response)

    resp = client.post(f"/improvements/generate?artifact_id={ids['User.java']}")
    assert resp.status_code == 200
    payload = resp.json()
    # Real findings F1/F2 were never addressed.
    assert payload["findings_addressed"] == []
    assert len(payload["non_actionable_findings"]) == 2


# --- Cross-file targeting: the proposal follows the findings, not the selection ---

def _user_fix_response(**overrides):
    improved_user = USER_SRC.replace(
        "public class User {\n    private String username;",
        "public class User {\n\n    private String username;",
    )
    kwargs = dict(
        improved_content=improved_user,
        explanation="Fixed EmptyLineSeparatorCheck in User.java (F1) by inserting the required blank line.",
        findings_addressed=["Blank line before VARIABLE_DEF in User.java"],
        non_actionable_findings=["SpotBugs THROWS_METHOD_THROWS_RUNTIMEEXCEPTION is deliberate"],
        addressed_finding_ids=["F1"],
        target_file="User.java",
        finding_assessments=[
            FindingAssessment(finding_id="F1", classification="ACTIONABLE", reasoning="Blank line inserted."),
            FindingAssessment(finding_id="F2", classification="NON_ACTIONABLE", reasoning="Intentional throw."),
        ],
    )
    kwargs.update(overrides)
    return CodeImprovementResponse(**kwargs), improved_user


def test_fix_for_findings_file_creates_proposal_when_other_file_selected(client, monkeypatch):
    """AuthService.java selected; the fix is in User.java -> proposal targets User.java."""
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["AuthService.java"], ids)

    response, improved_user = _user_fix_response()
    _capture(monkeypatch, response)

    resp = client.post(f"/improvements/generate?artifact_id={ids['AuthService.java']}")
    assert resp.status_code == 200
    payload = resp.json()

    # The proposal is bound to the file that was actually fixed.
    assert payload["file_name"] == "User.java"
    assert payload["artifact_id"] == ids["User.java"]
    assert payload["original_content"] == USER_SRC
    assert payload["improved_content"] == improved_user
    # The Checkstyle finding was addressed and the SpotBugs finding preserved.
    assert len(payload["findings_addressed"]) == 1
    assert "EmptyLineSeparatorCheck" in payload["findings_addressed"][0]["rule"]
    assert payload["non_actionable_findings"][0]["rule"] == "THROWS_METHOD_THROWS_RUNTIMEEXCEPTION"

    # The selected AuthService.java was not modified (still v1, original source).
    auth = asyncio.run(db.code_artifacts.find_one({"artifact_id": ids["AuthService.java"]}))
    assert auth["content"] == AUTH_SRC
    assert auth["version"] == 1
    # The original User.java was not modified either; only a proposal exists.
    user = asyncio.run(db.code_artifacts.find_one({"artifact_id": ids["User.java"]}))
    assert user["content"] == USER_SRC
    assert user["version"] == 1


def test_unknown_target_file_falls_back_to_selected_artifact(client, monkeypatch):
    """A target_file outside the analysis snapshot must not hijack the proposal."""
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["AuthService.java"], ids)

    improved_auth = AUTH_SRC.replace(
        "public class AuthService {\n    public boolean register",
        "public class AuthService {\n\n    public boolean register",
    )
    response = CodeImprovementResponse(
        improved_content=improved_auth,
        explanation="Touched the selected file.",
        findings_addressed=[],
        non_actionable_findings=[],
        addressed_finding_ids=[],
        target_file="NotAnalyzed.java",
        finding_assessments=[
            FindingAssessment(finding_id="F1", classification="NEEDS_CONTEXT", reasoning="x"),
            FindingAssessment(finding_id="F2", classification="NON_ACTIONABLE", reasoning="y"),
        ],
    )
    _capture(monkeypatch, response)

    resp = client.post(f"/improvements/generate?artifact_id={ids['AuthService.java']}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["file_name"] == "AuthService.java"
    assert payload["artifact_id"] == ids["AuthService.java"]


def test_no_change_guard_compares_against_target_file_not_selection(client, monkeypatch):
    """An unchanged response for the AI's target file returns NO_CHANGE for that file."""
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["AuthService.java"], ids)

    # AI targets User.java but returns it byte-identical: a real no-op.
    response, _ = _user_fix_response(improved_content=USER_SRC)
    _capture(monkeypatch, response)

    resp = client.post(f"/improvements/generate?artifact_id={ids['AuthService.java']}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "NO_CHANGE"
    assert payload["file_name"] == "User.java"
    assert payload["artifact_id"] == ids["User.java"]
    # The AI's own verdicts travel on the record, not in an error message.
    assert any(
        a["classification"] == "ACTIONABLE" for a in payload["finding_assessments"]
    )
    # ...but nothing counts as addressed: no code changed, so nothing was fixed,
    # even though the AI labeled F1 ACTIONABLE.
    assert payload["findings_addressed"] == []
    assert len(payload["non_actionable_findings"]) == 2
    # No new version of either file was created.
    assert asyncio.run(db.code_artifacts.count_documents({})) == 3


def test_accept_cross_file_proposal_versions_target_file_and_keeps_history(client, monkeypatch):
    """Accept creates User.java v2, leaves AuthService.java alone, keeps v1 + old analysis."""
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["AuthService.java"], ids)

    response, improved_user = _user_fix_response()
    _capture(monkeypatch, response)

    resp = client.post(f"/improvements/generate?artifact_id={ids['AuthService.java']}")
    assert resp.status_code == 200
    proposal_id = resp.json()["proposal_id"]

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
        result = StaticAnalysisResult(
            analysis_id=str(uuid4()),
            artifact_id=artifact_id,
            status="COMPLETED",
            checkstyle=AnalysisToolResult(status="COMPLETED", findings=[]),
            spotbugs=AnalysisToolResult(status="COMPLETED", findings=[]),
            security=AnalysisToolResult(status="COMPLETED", findings=[]),
            created_at=datetime.utcnow(),
        )
        # Mirror the real helper: the re-analysis is persisted as a NEW
        # document, leaving the historical snapshot untouched.
        await db.static_analysis_results.insert_one(result.model_dump())
        return result

    monkeypatch.setattr(improvement_routes, "_compile_artifact_internal", mock_compile)
    monkeypatch.setattr(improvement_routes, "_analyze_artifact_internal", mock_analyze)

    accept = client.post(f"/improvements/{proposal_id}/accept")
    assert accept.status_code == 200
    payload = accept.json()
    assert payload["status"] == "ACCEPTED"
    assert payload["accepted_version"] == 2

    # New version is of User.java, with the fixed content.
    new_version = asyncio.run(
        db.code_artifacts.find_one({"artifact_id": payload["accepted_artifact_id"]})
    )
    assert new_version["file_name"] == "User.java"
    assert new_version["version"] == 2
    assert new_version["content"] == improved_user

    # Originals are untouched: User.java v1 preserved, AuthService.java still v1-only.
    user_v1 = asyncio.run(db.code_artifacts.find_one({"artifact_id": ids["User.java"]}))
    assert user_v1["content"] == USER_SRC
    assert user_v1["version"] == 1
    auth_versions = asyncio.run(
        db.code_artifacts.find({"file_name": "AuthService.java"}).to_list(10)
    )
    assert [a["version"] for a in auth_versions] == [1]

    # Historical analysis preserved: the original snapshot still exists alongside
    # the re-analysis attached to the accepted version.
    analyses = asyncio.run(db.static_analysis_results.find({}).to_list(20))
    original_ids = {a["analysis_id"] for a in analyses}
    assert len(analyses) == 2
    assert payload["after_analysis"] is not None
    assert payload["after_analysis"]["analysis_id"] in original_ids


# --- Format guard: fixing a finding must not smuggle in re-indentation ---

def _indentation_analysis(db, artifact_id, ids, lines):
    """v2-style analysis: EmptyLineSeparator fixed, IndentationCheck present."""
    asyncio.run(
        db.static_analysis_results.insert_one(
            {
                "analysis_id": str(uuid4()),
                "artifact_id": artifact_id,
                "version": 1,
                "analyzed_files": [
                    {"artifact_id": ids[n], "file_name": n, "version": 1}
                    for n in ["User.java", "PasswordUtil.java", "AuthService.java"]
                ],
                "status": "COMPLETED",
                "checkstyle": {
                    "status": "COMPLETED",
                    "findings": [
                        {
                            "tool": "Checkstyle",
                            "severity": "ERROR",
                            "file": "User.java",
                            "line": line,
                            "column": 9,
                            "rule": "com.puppycrawl.tools.checkstyle.checks.indentation.IndentationCheck",
                            "message": "'method def rcurly' has incorrect indentation level 8, expected level should be 4.",
                        }
                        for line in lines
                    ],
                },
                "spotbugs": {"status": "COMPLETED", "findings": []},
                "security": {"status": "COMPLETED", "findings": []},
                "created_at": "2026-01-01T00:00:00",
            }
        )
    )


# The exact production incident: AI inserted the required blank line but
# returned getUsername()/getEmail() closing braces at 8-space indentation.
REGRESSION_ORIGINAL = USER_SRC
REGRESSION_SMUGGLED = USER_SRC.replace(
    "public class User {\n    private String username;",
    "public class User {\n\n    private String username;",
).replace(
    "        return username;\n    }",
    "        return username;\n        }",
).replace(
    "        return email;\n    }",
    "        return email;\n        }",
)


def test_fix_does_not_smuggle_in_reindentation(client, monkeypatch):
    """Regression test for the User.java v2 incident: a Checkstyle fix must
    not introduce incorrect indentation, and the fix itself must survive."""
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["AuthService.java"], ids)

    response = CodeImprovementResponse(
        improved_content=REGRESSION_SMUGGLED,
        explanation="Inserted the required blank line (F1).",
        findings_addressed=["Blank line before VARIABLE_DEF"],
        non_actionable_findings=[],
        addressed_finding_ids=["F1"],
        target_file="User.java",
        finding_assessments=[
            FindingAssessment(finding_id="F1", classification="ACTIONABLE", reasoning="Blank line inserted."),
            FindingAssessment(finding_id="F2", classification="NON_ACTIONABLE", reasoning="Intentional throw."),
        ],
    )
    _capture(monkeypatch, response)

    resp = client.post(f"/improvements/generate?artifact_id={ids['AuthService.java']}")
    assert resp.status_code == 200
    payload = resp.json()

    # The re-indentation regression is reverted: the closing brace keeps its
    # original 4-space indentation.
    improved = payload["improved_content"]
    assert "        return username;\n    }\n" in improved
    assert "        }\n" not in improved
    # The legitimate fix (blank line separating the VARIABLE_DEF) is NOT regressed.
    assert "public class User {\n\n    private String username;" in improved
    # The reversion is surfaced honestly, never silent.
    assert len(payload["formatting_notes"]) == 1
    assert "Line " in payload["formatting_notes"][0]


def test_whitespace_change_at_indentation_finding_line_is_kept(client, monkeypatch):
    """When IndentationCheck findings cover the lines, correcting the
    indentation IS the fix and must not be reverted."""
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    # The original already has the bad braces (v2 state); findings name them.
    bad_original = REGRESSION_SMUGGLED
    asyncio.run(
        db.code_artifacts.update_one(
            {"artifact_id": ids["User.java"]},
            {"$set": {"content": bad_original}},
        )
    )
    # In bad_original the over-indented closing brace is at line 10.
    _indentation_analysis(db, ids["User.java"], ids, lines=[10])

    fixed = bad_original.replace("        }\n", "    }\n")
    response = CodeImprovementResponse(
        improved_content=fixed,
        explanation="Corrected closing-brace indentation (F1).",
        findings_addressed=["Indentation fixed"],
        non_actionable_findings=[],
        addressed_finding_ids=["F1"],
        target_file="User.java",
        finding_assessments=[
            FindingAssessment(finding_id="F1", classification="ACTIONABLE", reasoning="Indentation corrected."),
        ],
    )
    _capture(monkeypatch, response)

    resp = client.post(f"/improvements/generate?artifact_id={ids['User.java']}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["improved_content"] == fixed
    assert payload["formatting_notes"] == []


def test_only_whitespace_changes_is_rejected_not_persisted(client, monkeypatch):
    """An AI response with no real fix (only re-indentation) must not
    become a proposal."""
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["User.java"], ids)

    only_whitespace = USER_SRC.replace("    private String username;", "        private String username;")
    response = CodeImprovementResponse(
        improved_content=only_whitespace,
        explanation="Reformatted.",
        findings_addressed=[],
        non_actionable_findings=[],
        addressed_finding_ids=[],
        target_file="User.java",
        finding_assessments=[
            FindingAssessment(finding_id="F1", classification="ACTIONABLE", reasoning="x"),
            FindingAssessment(finding_id="F2", classification="NON_ACTIONABLE", reasoning="y"),
        ],
    )
    _capture(monkeypatch, response)

    resp = client.post(f"/improvements/generate?artifact_id={ids['User.java']}")
    assert resp.status_code == 502
    assert "formatting changes" in resp.json()["detail"]
    assert asyncio.run(db.improvement_proposals.find({}).to_list(10)) == []


# --- Part 4: NO_CHANGE proposals are terminal records, never new versions ---

def _no_change_proposal_id(client, monkeypatch, db, ids):
    """Generate a NO_CHANGE proposal via mocked AI; return its proposal_id."""
    response = CodeImprovementResponse(
        improved_content=USER_SRC,
        explanation="Could not safely change.",
        findings_addressed=[],
        non_actionable_findings=[],
        addressed_finding_ids=[],
        finding_assessments=[
            FindingAssessment(finding_id="F1", classification="NON_ACTIONABLE", reasoning="Style only."),
            FindingAssessment(finding_id="F2", classification="NON_ACTIONABLE", reasoning="Intentional throw."),
        ],
    )
    _capture(monkeypatch, response)
    resp = client.post(f"/improvements/generate?artifact_id={ids['User.java']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "NO_CHANGE"
    return resp.json()["proposal_id"]


def test_no_change_proposal_cannot_be_accepted(client, monkeypatch):
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["User.java"], ids)

    proposal_id = _no_change_proposal_id(client, monkeypatch, db, ids)

    resp = client.post(f"/improvements/{proposal_id}/accept")
    assert resp.status_code == 409
    assert "no_change" in resp.json()["detail"].lower()

    # No new artifact version was created and the record is untouched.
    assert asyncio.run(db.code_artifacts.count_documents({})) == 3
    stored = asyncio.run(
        db.improvement_proposals.find_one({"proposal_id": proposal_id})
    )
    assert stored["status"] == "NO_CHANGE"
    assert stored["accepted_artifact_id"] is None


def test_no_change_proposal_cannot_be_rejected(client, monkeypatch):
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["User.java"], ids)

    proposal_id = _no_change_proposal_id(client, monkeypatch, db, ids)

    resp = client.post(f"/improvements/{proposal_id}/reject")
    assert resp.status_code == 409

    stored = asyncio.run(
        db.improvement_proposals.find_one({"proposal_id": proposal_id})
    )
    assert stored["status"] == "NO_CHANGE"


def test_no_change_proposal_is_retrievable_with_verdicts(client, monkeypatch):
    _reset()
    db = get_db()
    _requirement(db)
    ids = _three_artifacts(db)
    _cross_file_analysis(db, ids["User.java"], ids)

    proposal_id = _no_change_proposal_id(client, monkeypatch, db, ids)

    resp = client.get(f"/improvements/{proposal_id}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "NO_CHANGE"
    # NON_ACTIONABLE findings remain visible on the record.
    assert len(payload["non_actionable_findings"]) == 2
    assert len(payload["finding_assessments"]) == 2
