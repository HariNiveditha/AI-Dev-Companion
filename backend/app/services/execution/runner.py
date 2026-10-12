"""Orchestration of one real test execution inside the safe container boundary.

Flow (all external work happens inside the container — never on the host):

1. re-verify runner availability (fail closed);
2. build the isolated workspace from the artifact snapshot + test source;
3. compile production + test sources (``javac -proc:none``) — a failure here
   means *no trustworthy results exist*, so the execution is ERROR, not FAILED;
4. run the JUnit console launcher;
5. parse and validate the structured XML report — counts come only from it;
6. classify: PASSED (all executed tests green, skips allowed), FAILED (at
   least one test failed or errored), or ERROR (infrastructure: missing or
   malformed report, timeout, launch failure, unexpected exception).
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.models.execution import ExecutionCompileResult, ExecutionCounts
from app.services.execution import container as container_runtime
from app.services.execution.junit_report import (
    ParsedTestCase,
    ReportMalformedError,
    ReportMissingError,
    parse_reports,
)
from app.services.execution.workspace import ExecutionWorkspace, WorkspaceError, build_workspace

APP_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_IMAGE = "eclipse-temurin:21-jdk"
DEFAULT_JUNIT_JAR = APP_ROOT / ".tools" / "junit-platform-console-standalone-1.10.2.jar"


class RunnerUnavailableError(Exception):
    """The safe runner cannot execute tests right now (fail closed)."""


@dataclass
class Availability:
    available: bool
    reason: str
    runner_label: str = ""


@dataclass
class RunnerOutcome:
    status: str  # PASSED | FAILED | ERROR
    counts: ExecutionCounts = field(default_factory=ExecutionCounts)
    raw_cases: list[ParsedTestCase] = field(default_factory=list)
    compile_result: Optional[ExecutionCompileResult] = None
    error_message: Optional[str] = None
    runner_exit_code: Optional[int] = None
    runner_label: str = ""


def execution_enabled() -> bool:
    return os.getenv("ENABLE_JAVA_EXECUTION", "false").lower() == "true"


def configured_image() -> str:
    return os.getenv("EXECUTION_IMAGE", DEFAULT_IMAGE)


def junit_jar_path() -> Path:
    return Path(os.getenv("JUNIT_CONSOLE_JAR", str(DEFAULT_JUNIT_JAR)))


def _compile_timeout() -> int:
    return max(10, int(os.getenv("EXECUTION_COMPILE_TIMEOUT_SECONDS", "90")))


def _run_timeout() -> int:
    return max(10, int(os.getenv("EXECUTION_TIMEOUT_SECONDS", "120")))


def check_availability() -> Availability:
    """Probe every dependency of the safe runner. Fail closed with a reason."""
    if not execution_enabled():
        return Availability(
            available=False,
            reason=(
                "Java/JUnit execution is disabled until a secure sandbox with "
                "Docker or Podman is configured. Set ENABLE_JAVA_EXECUTION=true "
                "and provide a container runtime, the runner image "
                f"({configured_image()}), and the JUnit console jar "
                "(see README, Phase 9)."
            ),
        )

    cli = container_runtime.find_runtime()
    if not cli:
        return Availability(
            available=False,
            reason=(
                "Execution is enabled but no container runtime (docker/podman) "
                "was found on PATH. Tests are never executed on the host. "
                "Install Docker or Podman, or disable execution."
            ),
        )

    ok, detail = container_runtime.probe_runtime(cli)
    if not ok:
        return Availability(available=False, reason=f"Execution is enabled but the container runtime is unavailable: {detail}")

    image = container_runtime.validate_image_ref(configured_image())
    ok, detail = container_runtime.probe_image(cli, image)
    if not ok:
        return Availability(available=False, reason=f"Execution is enabled but the runner cannot start: {detail}")

    jar = junit_jar_path()
    if not jar.exists():
        return Availability(
            available=False,
            reason=(
                "Execution is enabled but the JUnit console jar was not found at "
                f"{jar}. Download junit-platform-console-standalone-1.10.2.jar from "
                "Maven Central into backend/.tools/ (see README, Phase 9)."
            ),
        )

    return Availability(available=True, reason="", runner_label=container_runtime.runner_label(cli, image))


def _error_outcome(
    message: str,
    *,
    compile_result: Optional[ExecutionCompileResult] = None,
    runner_exit_code: Optional[int] = None,
    runner_label: str = "",
) -> RunnerOutcome:
    return RunnerOutcome(
        status="ERROR",
        counts=ExecutionCounts(),
        raw_cases=[],
        compile_result=compile_result,
        error_message=message,
        runner_exit_code=runner_exit_code,
        runner_label=runner_label,
    )


def execute(
    execution_id: str,
    production_sources: list[dict],
    test_content: str,
    test_file_name: str,
) -> RunnerOutcome:
    """Compile and run the executable test for one execution. Blocking call."""
    availability = check_availability()
    if not availability.available:
        raise RunnerUnavailableError(availability.reason)

    cli = container_runtime.find_runtime()
    image = container_runtime.validate_image_ref(configured_image())
    jar = junit_jar_path()
    label = availability.runner_label

    try:
        with tempfile.TemporaryDirectory(prefix="ai-se-exec-") as tmp:
            workspace: ExecutionWorkspace = build_workspace(
                Path(tmp), production_sources, test_content, test_file_name
            )

            compile_result = container_runtime.compile_tests(
                cli=cli,
                image=image,
                execution_id=execution_id,
                workspace=workspace,
                junit_jar=jar,
                timeout_seconds=_compile_timeout(),
            )
            if compile_result.status == "ERROR":
                return _error_outcome(
                    "Test compilation timed out inside the runner container; "
                    "no trustworthy results were collected.",
                    compile_result=compile_result,
                    runner_label=label,
                )
            if compile_result.status != "PASSED":
                return _error_outcome(
                    "Test compilation failed — no tests were executed and no "
                    "trustworthy results exist (see compile_result for compiler diagnostics).",
                    compile_result=compile_result,
                    runner_label=label,
                )

            run = container_runtime.run_junit(
                cli=cli,
                image=image,
                execution_id=execution_id,
                workspace=workspace,
                junit_jar=jar,
                timeout_seconds=_run_timeout(),
            )
            if run.timed_out:
                return _error_outcome(
                    f"Test execution exceeded the {_run_timeout()}-second timeout; "
                    "the runner container was terminated.",
                    compile_result=compile_result,
                    runner_label=label,
                )
            if run.exit_code is None:
                return _error_outcome(
                    f"Runner container failed to start: {run.stderr.strip() or 'no diagnostics'}",
                    compile_result=compile_result,
                    runner_label=label,
                )

            try:
                report = parse_reports(workspace.reports_dir)
            except (ReportMissingError, ReportMalformedError, WorkspaceError) as exc:
                return _error_outcome(
                    f"Runner report could not be trusted: {exc}",
                    compile_result=compile_result,
                    runner_exit_code=run.exit_code,
                    runner_label=label,
                )

            counts = ExecutionCounts(
                total=report.total,
                passed=report.count("PASSED"),
                failed=report.count("FAILED"),
                skipped=report.count("SKIPPED"),
                error=report.count("ERROR"),
            )
            status = "PASSED" if counts.failed == 0 and counts.error == 0 else "FAILED"
            return RunnerOutcome(
                status=status,
                counts=counts,
                raw_cases=report.testcases,
                compile_result=compile_result,
                error_message=None,
                runner_exit_code=run.exit_code,
                runner_label=label,
            )
    except (WorkspaceError, ValueError) as exc:
        return _error_outcome(f"Execution workspace could not be prepared: {exc}", runner_label=label)
