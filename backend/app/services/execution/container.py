"""Containerized execution of compiled JUnit tests (the safe boundary).

Generated/user-provided Java is *never* executed on the host.  Production and
test sources are compiled and executed inside a fixed, application-controlled
container image with:

* ``--network=none``            no network access for the test process
* ``--read-only`` + tmpfs /tmp  read-only root filesystem, small writable /tmp
* ``--user 65534:65534``        non-root user
* ``--cap-drop=ALL`` + ``no-new-privileges``
* ``--memory`` / ``--cpus`` / ``--pids-limit`` resource + process caps
* ``--init``                    proper PID 1 signal handling / zombie reaping
* bind mounts limited to: the workspace (read-only), the output dir (writable),
  and the JUnit console jar (read-only)

The container is started with an *argument array* — no shell — and every path
reaching the command line is application-generated or validated against a
strict Java-file-name pattern.  Timeouts force-kill and remove the container.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.models.execution import ExecutionCompileResult
from app.services.execution.workspace import CONTAINER_JUNIT_JAR, ExecutionWorkspace

# Docker image reference: lowercase repo/path with optional tag/digest.
_IMAGE_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:/@-]*$")

# Diagnostics kept in Mongo stay small but informative.
_LOG_LIMIT = 4000


def _truncate(text: Optional[str]) -> str:
    if not text:
        return ""
    if len(text) <= _LOG_LIMIT:
        return text
    return text[:_LOG_LIMIT] + f"\n... [truncated {len(text) - _LOG_LIMIT} characters]"


def find_runtime() -> Optional[str]:
    return shutil.which("docker") or shutil.which("podman")


def validate_image_ref(image: str) -> str:
    if not _IMAGE_REF_PATTERN.fullmatch(image):
        raise ValueError(f"unsafe container image reference: {image!r}")
    return image


def probe_runtime(cli: str, timeout: int = 15) -> tuple[bool, str]:
    """Verify the CLI exists *and* its daemon/machine is reachable."""
    try:
        completed = subprocess.run(
            [cli, "version"], capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return False, f"{cli} version timed out after {timeout}s (daemon not responding)"
    except OSError as exc:
        return False, f"failed to launch {cli}: {exc}"
    if completed.returncode != 0:
        detail = _truncate(completed.stderr or completed.stdout).strip()
        return False, f"{cli} daemon not reachable (exit {completed.returncode}): {detail}"
    return True, ""


def probe_image(cli: str, image: str, timeout: int = 20) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [cli, "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"{cli} image inspect timed out after {timeout}s"
    except OSError as exc:
        return False, f"failed to launch {cli}: {exc}"
    if completed.returncode != 0:
        return False, (
            f"runner image '{image}' is not present locally — "
            f"pull it once with: {cli} pull {image}"
        )
    return True, ""


def runner_label(cli: str, image: str) -> str:
    # stem.lower() keeps the label stable across platforms
    # (Windows reports "docker.EXE", POSIX "docker").
    return f"{Path(cli).stem.lower()} image={image}"


def _base_flags(name: str) -> list[str]:
    return [
        "run",
        "--rm",
        "--name", name,
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=128",
        "--memory=512m",
        "--memory-swap=512m",
        "--cpus=1.0",
        "--user", "65534:65534",
        "--init",
        "--tmpfs", "/tmp:rw,size=64m",
    ]


def _mount_flags(workspace: ExecutionWorkspace, junit_jar: Path) -> list[str]:
    return [
        "-v", f"{workspace.src_dir}:/workspace:ro",
        "-v", f"{workspace.out_dir}:/out:rw",
        "-v", f"{junit_jar}:{CONTAINER_JUNIT_JAR}:ro",
        "-w", "/workspace",
    ]


def _container_name(execution_id: str, step: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "", execution_id)[:32]
    return f"ai-se-exec-{safe_id}-{step}"


def force_remove_container(cli: str, name: str, timeout: int = 15) -> None:
    """Best-effort kill+remove used after timeouts so containers never linger."""
    try:
        subprocess.run(
            [cli, "rm", "-f", name],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


@dataclass
class ContainerRun:
    """Outcome of one container invocation (compile or test run)."""

    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


def _run_container(
    cli: str,
    image: str,
    name: str,
    command: list[str],
    workspace: ExecutionWorkspace,
    junit_jar: Path,
    timeout_seconds: int,
) -> ContainerRun:
    cmd = [
        cli,
        *_base_flags(name),
        *_mount_flags(workspace, junit_jar),
        validate_image_ref(image),
        *command,
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_seconds, check=False
        )
        return ContainerRun(
            exit_code=completed.returncode,
            stdout=_truncate(completed.stdout),
            stderr=_truncate(completed.stderr),
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
    except subprocess.TimeoutExpired as exc:
        force_remove_container(cli, name)
        return ContainerRun(
            exit_code=None,
            stdout=_truncate((exc.stdout or b"").decode("utf-8", "replace")
                             if isinstance(exc.stdout, bytes) else exc.stdout),
            stderr=_truncate((exc.stderr or b"").decode("utf-8", "replace")
                             if isinstance(exc.stderr, bytes) else exc.stderr),
            duration_ms=round((time.perf_counter() - started) * 1000),
            timed_out=True,
        )
    except OSError as exc:
        return ContainerRun(
            exit_code=None,
            stdout="",
            stderr=_truncate(f"failed to launch container runtime: {exc}"),
            duration_ms=round((time.perf_counter() - started) * 1000),
        )


def compile_tests(
    cli: str,
    image: str,
    execution_id: str,
    workspace: ExecutionWorkspace,
    junit_jar: Path,
    timeout_seconds: int,
) -> ExecutionCompileResult:
    """Compile production + test sources inside the container (``javac -proc:none``)."""
    name = _container_name(execution_id, "compile")
    run = _run_container(
        cli=cli,
        image=image,
        name=name,
        command=[
            "javac",
            "-proc:none",
            "-encoding", "UTF-8",
            # Test sources import org.junit.jupiter.*: the JUnit console
            # jar (mounted read-only) provides the API at compile time.
            "-cp", CONTAINER_JUNIT_JAR,
            "-d", "/out/classes",
            f"@{workspace.container_sources_argfile}",
        ],
        workspace=workspace,
        junit_jar=junit_jar,
        timeout_seconds=timeout_seconds,
    )
    if run.timed_out:
        status = "ERROR"
    elif run.exit_code == 0:
        status = "PASSED"
    else:
        status = "FAILED"
    return ExecutionCompileResult(
        status=status,
        exit_code=run.exit_code,
        stdout=run.stdout,
        stderr=run.stderr,
        duration_ms=run.duration_ms,
    )


def run_junit(
    cli: str,
    image: str,
    execution_id: str,
    workspace: ExecutionWorkspace,
    junit_jar: Path,
    timeout_seconds: int,
) -> ContainerRun:
    """Execute the JUnit console launcher inside the container."""
    name = _container_name(execution_id, "test")
    return _run_container(
        cli=cli,
        image=image,
        name=name,
        command=[
            "java",
            "-jar", CONTAINER_JUNIT_JAR,
            "execute",
            f"--class-path=/out/classes",
            f"--scan-class-path=/out/classes",
            f"--reports-dir=/out/reports",
            "--details=none",
            "--disable-ansi-colors",
        ],
        workspace=workspace,
        junit_jar=junit_jar,
        timeout_seconds=timeout_seconds,
    )
