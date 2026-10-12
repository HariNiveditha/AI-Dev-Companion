"""Tests for the containerized runner (Phase 9).

Availability is probed (fail closed) and the execution itself is
orchestrated with the container calls mocked out — these tests
verify state transitions, error classification, and that no
execution is ever left PENDING.  They do not prove the real
container runner works; the real-runner checks are separate.
"""

from pathlib import Path

import pytest

from app.models.execution import ExecutionCompileResult
from app.services.execution import container as container_runtime
from app.services.execution import runner
from app.services.execution.container import ContainerRun
from app.services.execution.junit_report import ReportMissingError
from app.services.execution.runner import (
    Availability,
    RunnerUnavailableError,
    check_availability,
    execute,
)
from app.services.execution.workspace import (
    build_workspace,
    derive_class_name,
)

VALID_TEST_SOURCE = """import org.junit.jupiter.api.Test;

public class SampleTest {
    @Test
    void passes() {
    }
}
"""

PRODUCTION_SOURCE = "public class Sample {}"


def _availability(available: bool = True, reason: str = "") -> Availability:
    return Availability(
        available=available,
        reason=reason,
        runner_label="docker image=eclipse-temurin:21-jdk",
    )


# ---------------------------------------------------------------------------
# Availability (fail closed)
# ---------------------------------------------------------------------------

def test_availability_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_JAVA_EXECUTION", raising=False)

    result = check_availability()

    assert result.available is False
    assert "secure sandbox" in result.reason.lower()


def test_availability_requires_container_runtime(monkeypatch):
    monkeypatch.setenv("ENABLE_JAVA_EXECUTION", "true")
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: None)

    result = check_availability()

    assert result.available is False
    assert "container runtime" in result.reason.lower()


def test_availability_requires_reachable_daemon(monkeypatch):
    monkeypatch.setenv("ENABLE_JAVA_EXECUTION", "true")
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: "/usr/bin/docker")
    monkeypatch.setattr(
        container_runtime,
        "probe_runtime",
        lambda cli, timeout=15: (False, "daemon not responding"),
    )

    result = check_availability()

    assert result.available is False
    assert "daemon not responding" in result.reason


def test_availability_requires_runner_image(monkeypatch):
    monkeypatch.setenv("ENABLE_JAVA_EXECUTION", "true")
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: "/usr/bin/docker")
    monkeypatch.setattr(
        container_runtime, "probe_runtime", lambda cli, timeout=15: (True, "")
    )
    monkeypatch.setattr(
        container_runtime,
        "probe_image",
        lambda cli, image, timeout=20: (False, "image 'x' is not present locally"),
    )

    result = check_availability()

    assert result.available is False
    assert "not present locally" in result.reason


def test_availability_requires_junit_jar(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_JAVA_EXECUTION", "true")
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: "/usr/bin/docker")
    monkeypatch.setattr(
        container_runtime, "probe_runtime", lambda cli, timeout=15: (True, "")
    )
    monkeypatch.setattr(
        container_runtime, "probe_image", lambda cli, image, timeout=20: (True, "")
    )
    monkeypatch.setattr(
        runner, "junit_jar_path", lambda: tmp_path / "missing-junit.jar"
    )

    result = check_availability()

    assert result.available is False
    assert "JUnit console jar" in result.reason


def test_availability_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_JAVA_EXECUTION", "true")
    jar = tmp_path / "junit-platform-console-standalone-1.10.2.jar"
    jar.write_bytes(b"jar")
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: "/usr/bin/docker")
    monkeypatch.setattr(
        container_runtime, "probe_runtime", lambda cli, timeout=15: (True, "")
    )
    monkeypatch.setattr(
        container_runtime, "probe_image", lambda cli, image, timeout=20: (True, "")
    )
    monkeypatch.setattr(runner, "junit_jar_path", lambda: jar)

    result = check_availability()

    assert result.available is True
    assert result.runner_label == "docker image=eclipse-temurin:21-jdk"


# ---------------------------------------------------------------------------
# Execution orchestration (container calls mocked)
# ---------------------------------------------------------------------------

def _mock_compile_ok(cli, image, execution_id, workspace, junit_jar, timeout_seconds):
    return ExecutionCompileResult(
        status="PASSED", exit_code=0, stdout="", stderr="", duration_ms=10
    )


def _write_report(workspace, xml: str) -> None:
    (workspace.reports_dir / "TEST-junit-jupiter.xml").write_text(
        xml, encoding="utf-8"
    )


PASSING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="SampleTest" tests="2" failures="0" errors="0" skipped="1" time="0.05">
  <testcase name="passes" classname="SampleTest" time="0.01"/>
  <testcase name="skipped" classname="SampleTest" time="0"><skipped/></testcase>
</testsuite>
"""

FAILING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="SampleTest" tests="2" failures="1" errors="0" skipped="0" time="0.05">
  <testcase name="passes" classname="SampleTest" time="0.01"/>
  <testcase name="fails" classname="SampleTest" time="0.02">
    <failure message="expected true" type="AssertionFailedError">stack</failure>
  </testcase>
</testsuite>
"""


def test_execute_passed_when_all_tests_green(monkeypatch):
    monkeypatch.setattr(runner, "check_availability", lambda: _availability())
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: "/usr/bin/docker")
    monkeypatch.setattr(container_runtime, "compile_tests", _mock_compile_ok)

    def mock_run(cli, image, execution_id, workspace, junit_jar, timeout_seconds):
        _write_report(workspace, PASSING_XML)
        return ContainerRun(
            exit_code=0, stdout="", stderr="", duration_ms=50
        )

    monkeypatch.setattr(container_runtime, "run_junit", mock_run)

    with runner.tempfile.TemporaryDirectory() as tmp:
        outcome = execute(
            "exec-1",
            [{"file_name": "Sample.java", "content": PRODUCTION_SOURCE}],
            VALID_TEST_SOURCE,
            "SampleTest.java",
        )

    assert outcome.status == "PASSED"
    assert outcome.counts.total == 2
    assert outcome.counts.passed == 1
    assert outcome.counts.skipped == 1
    assert outcome.counts.failed == 0
    assert outcome.error_message is None
    assert outcome.runner_exit_code == 0


def test_execute_failed_when_test_fails(monkeypatch):
    monkeypatch.setattr(runner, "check_availability", lambda: _availability())
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: "/usr/bin/docker")
    monkeypatch.setattr(container_runtime, "compile_tests", _mock_compile_ok)

    def mock_run(cli, image, execution_id, workspace, junit_jar, timeout_seconds):
        _write_report(workspace, FAILING_XML)
        return ContainerRun(exit_code=1, stdout="", stderr="", duration_ms=50)

    monkeypatch.setattr(container_runtime, "run_junit", mock_run)

    outcome = execute(
        "exec-2",
        [{"file_name": "Sample.java", "content": PRODUCTION_SOURCE}],
        VALID_TEST_SOURCE,
        "SampleTest.java",
    )

    assert outcome.status == "FAILED"
    assert outcome.counts.failed == 1
    failed = next(case for case in outcome.raw_cases if case.status == "FAILED")
    assert failed.message == "expected true"


def test_execute_error_when_compilation_fails(monkeypatch):
    monkeypatch.setattr(runner, "check_availability", lambda: _availability())
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: "/usr/bin/docker")

    def mock_compile(cli, image, execution_id, workspace, junit_jar, timeout_seconds):
        return ExecutionCompileResult(
            status="FAILED",
            exit_code=1,
            stdout="",
            stderr="SampleTest.java:3: error: cannot find symbol",
            duration_ms=10,
        )

    monkeypatch.setattr(container_runtime, "compile_tests", mock_compile)

    outcome = execute(
        "exec-3",
        [{"file_name": "Sample.java", "content": PRODUCTION_SOURCE}],
        VALID_TEST_SOURCE,
        "SampleTest.java",
    )

    assert outcome.status == "ERROR"
    assert outcome.counts.total == 0
    assert "compilation failed" in outcome.error_message.lower()
    assert outcome.compile_result.status == "FAILED"
    assert "cannot find symbol" in outcome.compile_result.stderr


def test_execute_error_on_test_timeout(monkeypatch):
    monkeypatch.setattr(runner, "check_availability", lambda: _availability())
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: "/usr/bin/docker")
    monkeypatch.setattr(container_runtime, "compile_tests", _mock_compile_ok)

    def mock_run(cli, image, execution_id, workspace, junit_jar, timeout_seconds):
        return ContainerRun(
            exit_code=None, stdout="", stderr="", duration_ms=timeout_seconds * 1000,
            timed_out=True,
        )

    monkeypatch.setattr(container_runtime, "run_junit", mock_run)

    outcome = execute(
        "exec-4",
        [{"file_name": "Sample.java", "content": PRODUCTION_SOURCE}],
        VALID_TEST_SOURCE,
        "SampleTest.java",
    )

    assert outcome.status == "ERROR"
    assert "timeout" in outcome.error_message.lower()


def test_execute_error_when_report_missing(monkeypatch):
    monkeypatch.setattr(runner, "check_availability", lambda: _availability())
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: "/usr/bin/docker")
    monkeypatch.setattr(container_runtime, "compile_tests", _mock_compile_ok)

    def mock_run(cli, image, execution_id, workspace, junit_jar, timeout_seconds):
        # Runner exits 0 but writes no report at all.
        return ContainerRun(exit_code=0, stdout="", stderr="", duration_ms=50)

    monkeypatch.setattr(container_runtime, "run_junit", mock_run)

    outcome = execute(
        "exec-5",
        [{"file_name": "Sample.java", "content": PRODUCTION_SOURCE}],
        VALID_TEST_SOURCE,
        "SampleTest.java",
    )

    assert outcome.status == "ERROR"
    assert "could not be trusted" in outcome.error_message


def test_execute_error_when_runner_cannot_start(monkeypatch):
    monkeypatch.setattr(runner, "check_availability", lambda: _availability())
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: "/usr/bin/docker")
    monkeypatch.setattr(container_runtime, "compile_tests", _mock_compile_ok)

    def mock_run(cli, image, execution_id, workspace, junit_jar, timeout_seconds):
        return ContainerRun(
            exit_code=None,
            stdout="",
            stderr="docker: Error response from daemon: OCI runtime error",
            duration_ms=5,
        )

    monkeypatch.setattr(container_runtime, "run_junit", mock_run)

    outcome = execute(
        "exec-6",
        [{"file_name": "Sample.java", "content": PRODUCTION_SOURCE}],
        VALID_TEST_SOURCE,
        "SampleTest.java",
    )

    assert outcome.status == "ERROR"
    assert "failed to start" in outcome.error_message.lower()


def test_execute_raises_when_unavailable(monkeypatch):
    monkeypatch.setattr(
        runner, "check_availability", lambda: _availability(available=False, reason="off")
    )

    with pytest.raises(RunnerUnavailableError):
        execute("exec-7", [], VALID_TEST_SOURCE, "SampleTest.java")


def test_execute_returns_terminal_status_only(monkeypatch):
    """Every code path must produce PASSED, FAILED, or ERROR — never PENDING."""
    monkeypatch.setattr(runner, "check_availability", lambda: _availability())
    monkeypatch.setattr(container_runtime, "find_runtime", lambda: "/usr/bin/docker")
    monkeypatch.setattr(container_runtime, "compile_tests", _mock_compile_ok)

    outcomes = []

    def mock_run(cli, image, execution_id, workspace, junit_jar, timeout_seconds):
        _write_report(workspace, PASSING_XML)
        return ContainerRun(exit_code=0, stdout="", stderr="", duration_ms=50)

    monkeypatch.setattr(container_runtime, "run_junit", mock_run)
    outcomes.append(
        execute("exec-8", [{"file_name": "S.java", "content": PRODUCTION_SOURCE}],
                VALID_TEST_SOURCE, "SampleTest.java").status
    )

    def mock_run_fail(cli, image, execution_id, workspace, junit_jar, timeout_seconds):
        _write_report(workspace, FAILING_XML)
        return ContainerRun(exit_code=1, stdout="", stderr="", duration_ms=50)

    monkeypatch.setattr(container_runtime, "run_junit", mock_run_fail)
    outcomes.append(
        execute("exec-9", [{"file_name": "S.java", "content": PRODUCTION_SOURCE}],
                VALID_TEST_SOURCE, "SampleTest.java").status
    )

    assert set(outcomes) <= {"PASSED", "FAILED", "ERROR"}


# ---------------------------------------------------------------------------
# Workspace construction
# ---------------------------------------------------------------------------

def test_workspace_writes_package_aware_sources(tmp_path):
    production = [
        {
            "file_name": "UserService.java",
            "content": "package com.example.app;\n\npublic class UserService {}",
        }
    ]
    test_source = (
        "package com.example.app;\n\nimport org.junit.jupiter.api.Test;\n\n"
        "public class UserServiceTest {\n    @Test\n    void passes() {}\n}\n"
    )

    workspace = build_workspace(
        tmp_path, production, test_source, "UserServiceTest.java"
    )

    assert (tmp_path / "src" / "com" / "example" / "app" / "UserService.java").exists()
    assert (tmp_path / "src" / "com" / "example" / "app" / "UserServiceTest.java").exists()
    argfile = (tmp_path / "out" / "sources.txt").read_text(encoding="utf-8")
    assert "/workspace/com/example/app/UserService.java" in argfile
    assert "/workspace/com/example/app/UserServiceTest.java" in argfile


def test_workspace_rejects_unsafe_file_name(tmp_path):
    with pytest.raises(Exception):
        build_workspace(
            tmp_path,
            [{"file_name": "../evil.java", "content": "public class X {}"}],
            VALID_TEST_SOURCE,
            "SampleTest.java",
        )


def test_derive_class_name():
    assert derive_class_name("public class UserServiceTest {") == "UserServiceTest"
    assert derive_class_name("class Helper {}") == "Helper"
    assert derive_class_name("no declaration here") is None
