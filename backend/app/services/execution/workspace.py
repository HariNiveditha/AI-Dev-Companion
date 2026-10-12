"""Build the isolated workspace for one test execution.

Layout created inside a temporary directory (host side):

    <tmp>/src/<package dirs>/<Source>.java   production sources (read-only in container)
    <tmp>/src/<package dirs>/<TestClass>.java executable JUnit test source
    <tmp>/out/classes/                        javac destination (writable in container)
    <tmp>/out/reports/                        JUnit XML reports (writable in container)
    <tmp>/out/sources.txt                     javac @argfile (container paths, app-written)

Only application-controlled paths and pre-validated file names ever reach the
command line; no user text is interpolated into a shell command (the container
is started with an argument array and no shell).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# Same safety pattern used by the compile/analyze routes: plain Java file names,
# no directories, no traversal.
JAVA_FILE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.java$")

PACKAGE_PATTERN = re.compile(
    r"^\s*package\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;", re.MULTILINE
)

# Container-side fixed mount points.
CONTAINER_WORKSPACE = "/workspace"
CONTAINER_OUT = "/out"
CONTAINER_JUNIT_JAR = "/opt/junit/junit.jar"


class WorkspaceError(Exception):
    """The execution workspace could not be built from the given inputs."""


@dataclass
class ExecutionWorkspace:
    root: Path
    src_dir: Path
    out_dir: Path
    sources_argfile: Path
    reports_dir: Path
    classes_dir: Path

    @property
    def container_sources_argfile(self) -> str:
        return f"{CONTAINER_OUT}/sources.txt"


def derive_class_name(content: str) -> Optional[str]:
    """Return the first top-level class/interface name declared in *content*."""
    match = re.search(
        r"\b(?:public\s+)?(?:final\s+|abstract\s+)*(?:class|interface|enum|record)\s+([A-Za-z_$][\w$]*)",
        content,
    )
    return match.group(1) if match else None


def _write_source(src_dir: Path, file_name: str, content: str) -> str:
    """Write one source into its package directory; return container path."""
    if not JAVA_FILE_NAME_PATTERN.fullmatch(file_name):
        raise WorkspaceError(f"unsafe Java file name: {file_name!r}")
    package_match = PACKAGE_PATTERN.search(content)
    package_dir = src_dir
    if package_match:
        package_dir = src_dir.joinpath(*package_match.group(1).split("."))
    package_dir.mkdir(parents=True, exist_ok=True)
    target = package_dir / file_name
    target.write_text(content, encoding="utf-8")
    return f"{CONTAINER_WORKSPACE}/{file_name}" if package_dir == src_dir else (
        f"{CONTAINER_WORKSPACE}/"
        + "/".join(package_match.group(1).split("."))
        + f"/{file_name}"
    )


def build_workspace(
    root: Path,
    production_sources: Iterable[dict],
    test_content: str,
    test_file_name: str,
) -> ExecutionWorkspace:
    """Materialize production + test sources and the javac argfile.

    ``production_sources`` are artifact documents (``file_name`` + ``content``);
    they must already be the chosen snapshot versions.
    """
    root = Path(root)
    src_dir = root / "src"
    out_dir = root / "out"
    classes_dir = out_dir / "classes"
    reports_dir = out_dir / "reports"
    for directory in (src_dir, classes_dir, reports_dir):
        directory.mkdir(parents=True, exist_ok=True)

    container_paths: list[str] = []
    for artifact in production_sources:
        file_name = artifact.get("file_name", "")
        content = artifact.get("content", "")
        if not content.strip():
            raise WorkspaceError(f"artifact {file_name!r} has empty content")
        container_paths.append(_write_source(src_dir, file_name, content))

    if not test_content.strip():
        raise WorkspaceError("executable test source is empty")
    container_paths.append(_write_source(src_dir, test_file_name, test_content))

    # javac @argfile: absolute container paths, one per line, app-written only.
    sources_argfile = out_dir / "sources.txt"
    sources_argfile.write_text(
        "\n".join(f'"{p}"' for p in container_paths) + "\n", encoding="utf-8"
    )

    return ExecutionWorkspace(
        root=root,
        src_dir=src_dir,
        out_dir=out_dir,
        sources_argfile=sources_argfile,
        reports_dir=reports_dir,
        classes_dir=classes_dir,
    )
