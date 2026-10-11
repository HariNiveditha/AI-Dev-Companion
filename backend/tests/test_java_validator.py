"""Regression tests for Java source-code validation.

Covers the specific failure modes observed with Gemini structured-JSON output:
  * single-line Java (collapsed newlines)
  * missing `import` keyword (bare package path)
  * unbalanced braces / incomplete source
  * multiple Java files in one response
  * Markdown-fenced responses
  * preservation of valid strings, comments, and text blocks
"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.mongodb import get_db
from app.main import app
from app.services.java_validator import validate_java_source


# ---------------------------------------------------------------------------
# Unit tests for validate_java_source
# ---------------------------------------------------------------------------

class TestValidateJavaSource:
    """Direct tests for the structural validator."""

    def test_valid_java_passes(self):
        source = (
            "package com.example;\n"
            "\n"
            "import java.util.List;\n"
            "import java.util.ArrayList;\n"
            "\n"
            "public class Foo {\n"
            "    public static void main(String[] args) {\n"
            "        List<String> items = new ArrayList<>();\n"
            "        items.add(\"hello\");\n"
            "    }\n"
            "}\n"
        )
        result = validate_java_source(source)
        assert result.ok
        assert result.errors == []

    def test_empty_source_fails(self):
        result = validate_java_source("")
        assert not result.ok
        assert "empty" in result.errors[0].lower()

    def test_single_line_source_fails(self):
        source = (
            "package com.example; import java.security.MessageDigest; "
            "public class PasswordUtil { "
            "public static String hash(String p) { return p; } }"
        )
        result = validate_java_source(source)
        assert not result.ok
        assert any("newline" in e.lower() for e in result.errors)

    def test_unbalanced_braces_fails(self):
        source = (
            "package com.example;\n"
            "\n"
            "public class Foo {\n"
            "    public void bar() {\n"
            "        System.out.println(\"hi\");\n"
            "    }\n"
            # missing final closing brace for class
        )
        result = validate_java_source(source)
        assert not result.ok
        assert any("brace" in e.lower() for e in result.errors)

    def test_extra_closing_brace_fails(self):
        source = (
            "public class Foo {\n"
            "}\n"
            "}\n"
        )
        result = validate_java_source(source)
        assert not result.ok
        assert any("closing brace" in e.lower() for e in result.errors)

    def test_missing_import_keyword_fails(self):
        source = (
            "package com.example;\n"
            "\n"
            "import java.security.MessageDigest;\n"
            "java.util.Base64;\n"
            "\n"
            "public class Foo {\n"
            "}\n"
        )
        result = validate_java_source(source)
        assert not result.ok
        assert any("import" in e.lower() for e in result.errors)

    def test_missing_class_declaration_fails(self):
        source = (
            "package com.example;\n"
            "\n"
            "import java.util.List;\n"
        )
        result = validate_java_source(source)
        assert not result.ok
        assert any("class" in e.lower() for e in result.errors)

    def test_markdown_fences_detected(self):
        source = (
            "```java\n"
            "public class Foo {\n"
            "}\n"
            "```"
        )
        result = validate_java_source(source)
        assert not result.ok
        assert any("fence" in e.lower() for e in result.errors)

    def test_braces_inside_string_literals_ignored(self):
        source = (
            'public class Foo {\n'
            '    String s = "{{{}}}";\n'
            '}\n'
        )
        result = validate_java_source(source)
        # The string contains balanced braces inside quotes, so
        # structural analysis should see balanced braces overall.
        assert not any("brace" in e.lower() for e in result.errors)

    def test_braces_inside_comments_ignored(self):
        source = (
            "public class Foo {\n"
            "    // This comment has { an unbalanced brace\n"
            "    /* and this one has } too */\n"
            "}\n"
        )
        result = validate_java_source(source)
        assert result.ok

    def test_text_block_preserved(self):
        source = (
            'public class Foo {\n'
            '    String xml = """\n'
            '        <root>\\n</root>\n'
            '    """;\n'
            '}\n'
        )
        result = validate_java_source(source)
        assert result.ok

    def test_unbalanced_parentheses_detected(self):
        source = (
            "public class Foo {\n"
            "    public void bar() {\n"
            "        System.out.println(\"hello\"\n"
            "    }\n"
            "}\n"
        )
        result = validate_java_source(source)
        assert not result.ok
        assert any("parenthes" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# Endpoint-level regression tests for malformed AI responses
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


def _create_confirmed_requirement(db, rid="req-val-1"):
    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": rid,
                "projectId": "proj-1",
                "title": "Password hashing",
                "description": "Hash passwords securely.",
                "status": "CONFIRMED",
                "analysis": {
                    "functional_requirements": ["Hash passwords"],
                    "non_functional_requirements": [],
                    "assumptions": [],
                    "ambiguities": [],
                    "edge_cases": [],
                    "acceptance_criteria": [],
                },
            }
        )
    )


def test_generate_code_rejects_single_line_output(client, monkeypatch):
    """Regression: Gemini returns entire Java file on one line."""
    _reset()
    db = get_db()
    _create_confirmed_requirement(db)

    single_line = (
        "package com.example; import java.security.MessageDigest; "
        "public class PasswordUtil { "
        "public static String hash(String p) { return p; } }"
    )
    fake = SimpleNamespace(
        files=[
            SimpleNamespace(
                file_name="PasswordUtil.java",
                language="Java",
                content=single_line,
            )
        ]
    )
    import app.api.requirements as req_routes
    monkeypatch.setattr(req_routes, "generate_java_code", lambda *a, **k: fake)

    resp = client.post("/requirements/req-val-1/generate-code")
    assert resp.status_code == 502
    assert "newline" in resp.json()["detail"].lower()

    # Verify nothing was persisted
    artifacts = asyncio.run(db.code_artifacts.find({}).to_list(10))
    assert len(artifacts) == 0


def test_generate_code_rejects_missing_import_keyword(client, monkeypatch):
    """Regression: `java.util.Base64;` without `import`."""
    _reset()
    db = get_db()
    _create_confirmed_requirement(db)

    malformed = (
        "package com.example;\n"
        "import java.security.MessageDigest;\n"
        "java.util.Base64;\n"
        "public class Foo {\n"
        "}\n"
    )
    fake = SimpleNamespace(
        files=[
            SimpleNamespace(
                file_name="Foo.java", language="Java", content=malformed
            )
        ]
    )
    import app.api.requirements as req_routes
    monkeypatch.setattr(req_routes, "generate_java_code", lambda *a, **k: fake)

    resp = client.post("/requirements/req-val-1/generate-code")
    assert resp.status_code == 502
    assert "import" in resp.json()["detail"].lower()


def test_generate_code_rejects_missing_closing_brace(client, monkeypatch):
    """Regression: class brace never closed."""
    _reset()
    db = get_db()
    _create_confirmed_requirement(db)

    incomplete = (
        "package com.example;\n"
        "public class Foo {\n"
        "    public void bar() {\n"
        "    }\n"
        # missing class closing brace
    )
    fake = SimpleNamespace(
        files=[
            SimpleNamespace(
                file_name="Foo.java", language="Java", content=incomplete
            )
        ]
    )
    import app.api.requirements as req_routes
    monkeypatch.setattr(req_routes, "generate_java_code", lambda *a, **k: fake)

    resp = client.post("/requirements/req-val-1/generate-code")
    assert resp.status_code == 502
    assert "brace" in resp.json()["detail"].lower()


def test_generate_code_accepts_multiple_valid_files(client, monkeypatch):
    """Multiple well-formed Java files should all be persisted."""
    _reset()
    db = get_db()
    _create_confirmed_requirement(db)

    file1 = (
        "package com.example;\n"
        "import java.util.Base64;\n"
        "public class PasswordHasher {\n"
        "    public String hash(String p) {\n"
        "        return Base64.getEncoder().encodeToString(p.getBytes());\n"
        "    }\n"
        "}\n"
    )
    file2 = (
        "package com.example;\n"
        "public class PasswordUtil {\n"
        "    public boolean verify(String a, String b) {\n"
        "        return a.equals(b);\n"
        "    }\n"
        "}\n"
    )
    fake = SimpleNamespace(
        files=[
            SimpleNamespace(file_name="PasswordHasher.java", language="Java", content=file1),
            SimpleNamespace(file_name="PasswordUtil.java", language="Java", content=file2),
        ]
    )
    import app.api.requirements as req_routes
    monkeypatch.setattr(req_routes, "generate_java_code", lambda *a, **k: fake)

    resp = client.post("/requirements/req-val-1/generate-code")
    assert resp.status_code == 200
    artifacts = resp.json()
    assert len(artifacts) == 2
    names = {a["file_name"] for a in artifacts}
    assert names == {"PasswordHasher.java", "PasswordUtil.java"}


def test_generate_code_rejects_mixed_valid_and_invalid(client, monkeypatch):
    """One valid file plus one single-line file → reject everything."""
    _reset()
    db = get_db()
    _create_confirmed_requirement(db)

    valid = (
        "package com.example;\n"
        "public class Good {\n"
        "}\n"
    )
    bad = "public class Bad { public void x() {} }"
    fake = SimpleNamespace(
        files=[
            SimpleNamespace(file_name="Good.java", language="Java", content=valid),
            SimpleNamespace(file_name="Bad.java", language="Java", content=bad),
        ]
    )
    import app.api.requirements as req_routes
    monkeypatch.setattr(req_routes, "generate_java_code", lambda *a, **k: fake)

    resp = client.post("/requirements/req-val-1/generate-code")
    assert resp.status_code == 502
    # Nothing persisted at all
    artifacts = asyncio.run(db.code_artifacts.find({}).to_list(10))
    assert len(artifacts) == 0


# ---------------------------------------------------------------------------
# Regression tests for Phase 10 improvement endpoint
# ---------------------------------------------------------------------------

def _create_artifact_with_analysis(db, aid="art-val-1", rid="req-val-2"):
    asyncio.run(
        db.requirements.insert_one(
            {
                "_id": rid,
                "projectId": "proj-1",
                "title": "Login",
                "description": "Login.",
                "status": "CONFIRMED",
                "analysis": {},
            }
        )
    )
    asyncio.run(
        db.code_artifacts.insert_one(
            {
                "artifact_id": aid,
                "project_id": "proj-1",
                "requirement_id": rid,
                "file_name": "Login.java",
                "language": "Java",
                "content": "package com.example;\npublic class Login {\n    public void go() {}\n}\n",
                "version": 1,
                "source": "AI_GENERATED",
                "status": "AI_GENERATED",
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        )
    )
    asyncio.run(
        db.static_analysis_results.insert_one(
            {
                "analysis_id": str(uuid4()),
                "artifact_id": aid,
                "status": "COMPLETED",
                "checkstyle": {
                    "status": "COMPLETED",
                    "findings": [
                        {
                            "tool": "Checkstyle",
                            "severity": "WARNING",
                            "file": "Login.java",
                            "line": 3,
                            "rule": "NeedBraces",
                            "message": "Missing braces",
                        }
                    ],
                },
                "spotbugs": {"status": "COMPLETED", "findings": []},
                "security": {"status": "COMPLETED", "findings": []},
                "created_at": "2024-01-01T00:00:00",
            }
        )
    )


def test_improve_rejects_single_line_output(client, monkeypatch):
    """Improvement proposal with single-line Java is rejected."""
    _reset()
    db = get_db()
    _create_artifact_with_analysis(db)

    fake = SimpleNamespace(
        improved_content="public class Login { public void go() { System.out.println(\"ok\"); } }",
        explanation="Improved.",
        findings_addressed=["Fixed braces"],
        non_actionable_findings=[],
    )
    import app.api.improvement as imp_routes
    monkeypatch.setattr(imp_routes, "generate_code_improvement", lambda *a, **k: fake)

    resp = client.post("/improvements/generate?artifact_id=art-val-1")
    assert resp.status_code == 502
    assert "newline" in resp.json()["detail"].lower()
    # No proposal persisted
    proposals = asyncio.run(db.improvement_proposals.find({}).to_list(10))
    assert len(proposals) == 0


def test_improve_rejects_missing_import(client, monkeypatch):
    """Improvement proposal with bare package path is rejected."""
    _reset()
    db = get_db()
    _create_artifact_with_analysis(db)

    fake = SimpleNamespace(
        improved_content=(
            "package com.example;\n"
            "java.util.Base64;\n"
            "public class Login {\n"
            "    public void go() {}\n"
            "}\n"
        ),
        explanation="Improved.",
        findings_addressed=[],
        non_actionable_findings=[],
    )
    import app.api.improvement as imp_routes
    monkeypatch.setattr(imp_routes, "generate_code_improvement", lambda *a, **k: fake)

    resp = client.post("/improvements/generate?artifact_id=art-val-1")
    assert resp.status_code == 502
    assert "import" in resp.json()["detail"].lower()


def test_improve_accepts_valid_output(client, monkeypatch):
    """Well-formed improvement proposal is accepted and persisted."""
    _reset()
    db = get_db()
    _create_artifact_with_analysis(db)

    fake = SimpleNamespace(
        improved_content=(
            "package com.example;\n"
            "public class Login {\n"
            "    public void go() {\n"
            "        System.out.println(\"ok\");\n"
            "    }\n"
            "}\n"
        ),
        explanation="Added braces.",
        findings_addressed=["Fixed braces"],
        non_actionable_findings=[],
    )
    import app.api.improvement as imp_routes
    monkeypatch.setattr(imp_routes, "generate_code_improvement", lambda *a, **k: fake)

    resp = client.post("/improvements/generate?artifact_id=art-val-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PENDING"
    # Original artifact untouched
    original = asyncio.run(db.code_artifacts.find_one({"artifact_id": "art-val-1"}))
    assert "public void go() {}" in original["content"]


# ---------------------------------------------------------------------------
# Tests for valid strings / comments / text blocks being preserved
# ---------------------------------------------------------------------------

def test_validate_strips_string_literals_correctly():
    """Braces inside strings must not affect brace counting."""
    source = (
        'public class A {\n'
        '    String a = "{{";\n'
        '    String b = "}}";\n'
        '}\n'
    )
    result = validate_java_source(source)
    assert result.ok


def test_validate_strips_comments_correctly():
    """Braces inside comments must not affect brace counting."""
    source = (
        "public class A {\n"
        "    /* { unbalanced */\n"
        "    // another { one\n"
        "}\n"
    )
    result = validate_java_source(source)
    assert result.ok


def test_validate_handles_escapes_in_strings():
    """Escaped quotes inside string literals are handled."""
    source = (
        'public class A {\n'
        '    String s = "she said \\"hello\\" and left {";\n'
        '}\n'
    )
    result = validate_java_source(source)
    assert result.ok
