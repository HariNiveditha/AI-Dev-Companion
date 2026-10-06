import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.db.mongodb import get_db
from app.models.code_artifact import (
    AnalysisFinding,
    AnalysisToolResult,
    CodeArtifact,
    CodeArtifactEdit,
    CompileResult,
    StaticAnalysisResult,
)

router = APIRouter()
JAVA_FILE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.java$")
COMPILE_TIMEOUT_SECONDS = 15
ANALYSIS_TIMEOUT_SECONDS = 30
APP_ROOT = Path(__file__).resolve().parents[2]


@router.put("/{artifact_id}", response_model=CodeArtifact)
async def edit_artifact(artifact_id: str, artifact_in: CodeArtifactEdit):
    db = get_db()
    current = await db.code_artifacts.find_one({"artifact_id": artifact_id})
    if not current:
        raise HTTPException(status_code=404, detail="Code artifact not found")

    previous_versions = await db.code_artifacts.find(
        {
            "project_id": current["project_id"],
            "requirement_id": current["requirement_id"],
            "file_name": current["file_name"],
        }
    ).to_list(1000)
    next_version = max(
        (artifact.get("version", 0) for artifact in previous_versions),
        default=0,
    ) + 1
    now = datetime.utcnow()
    edited = CodeArtifact(
        artifact_id=str(uuid4()),
        project_id=current["project_id"],
        requirement_id=current["requirement_id"],
        file_name=current["file_name"],
        language="Java",
        content=artifact_in.content,
        version=next_version,
        source="DEVELOPER_EDITED",
        status="EDITED",
        created_at=now,
        updated_at=now,
    ).model_dump()
    await db.code_artifacts.insert_one(edited)
    return edited


@router.post("/{artifact_id}/compile", response_model=CompileResult)
async def compile_artifact(artifact_id: str):
    db = get_db()
    artifact = await db.code_artifacts.find_one({"artifact_id": artifact_id})
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if artifact.get("language") != "Java":
        raise HTTPException(status_code=400, detail="Only Java artifacts can be compiled")
    if not artifact.get("content", "").strip():
        raise HTTPException(status_code=400, detail="Artifact has no Java source code")

    javac_path = shutil.which("javac")
    if not javac_path:
        result = CompileResult(
            artifact_id=artifact_id,
            status="TOOL_ERROR",
            stderr="javac was not found. Install a JDK or configure a Java compiler.",
            duration_ms=0,
            timestamp=datetime.utcnow(),
        )
        return JSONResponse(status_code=503, content=result.model_dump(mode="json"))

    related_artifacts = await db.code_artifacts.find(
        {
            "project_id": artifact["project_id"],
            "requirement_id": artifact["requirement_id"],
            "language": "Java",
        }
    ).to_list(1000)
    latest_by_file: dict[str, dict] = {}
    for related in related_artifacts:
        current = latest_by_file.get(related["file_name"])
        if not current or related.get("version", 0) > current.get("version", 0):
            latest_by_file[related["file_name"]] = related

    if any(not JAVA_FILE_NAME_PATTERN.fullmatch(file_name) for file_name in latest_by_file):
        raise HTTPException(status_code=400, detail="Artifact contains an unsafe Java filename")

    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="ai-se-compile-") as temp_dir:
            source_paths = []
            for file_name, source_artifact in latest_by_file.items():
                package_match = re.search(
                    r"^\s*package\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;",
                    source_artifact["content"],
                    re.MULTILINE,
                )
                package_dir = Path(temp_dir)
                if package_match:
                    package_dir = package_dir.joinpath(*package_match.group(1).split("."))
                package_dir.mkdir(parents=True, exist_ok=True)
                final_path = package_dir / file_name
                with final_path.open("w", encoding="utf-8", newline="") as source_file:
                    source_file.write(source_artifact["content"])
                source_paths.append(str(final_path))
            completed = subprocess.run(
                [javac_path, "-encoding", "UTF-8", *source_paths],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=COMPILE_TIMEOUT_SECONDS,
                check=False,
            )
        status = "PASSED" if completed.returncode == 0 else "FAILED"
        return CompileResult(
            artifact_id=artifact_id,
            status=status,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=round((time.perf_counter() - started) * 1000),
            timestamp=datetime.utcnow(),
        )
    except subprocess.TimeoutExpired as exc:
        return CompileResult(
            artifact_id=artifact_id,
            status="TOOL_ERROR",
            stderr=f"Java compilation exceeded the {COMPILE_TIMEOUT_SECONDS}-second timeout.",
            stdout=exc.stdout or "",
            duration_ms=round((time.perf_counter() - started) * 1000),
            timestamp=datetime.utcnow(),
        )


def _latest_artifacts(artifacts: list[dict]) -> list[dict]:
    latest_by_file: dict[str, dict] = {}
    for artifact in artifacts:
        current = latest_by_file.get(artifact["file_name"])
        if not current or artifact.get("version", 0) > current.get("version", 0):
            latest_by_file[artifact["file_name"]] = artifact
    return list(latest_by_file.values())


def _write_sources(temp_dir: str, artifacts: list[dict]) -> list[str]:
    source_paths = []
    for source_artifact in artifacts:
        file_name = source_artifact["file_name"]
        package_match = re.search(
            r"^\s*package\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;",
            source_artifact["content"],
            re.MULTILINE,
        )
        package_dir = Path(temp_dir)
        if package_match:
            package_dir = package_dir.joinpath(*package_match.group(1).split("."))
        package_dir.mkdir(parents=True, exist_ok=True)
        final_path = package_dir / file_name
        final_path.write_text(source_artifact["content"], encoding="utf-8")
        source_paths.append(str(final_path))
    return source_paths


def _finding_from_checkstyle(error: ET.Element, file_name: str) -> AnalysisFinding:
    return AnalysisFinding(
        tool="Checkstyle",
        severity=error.attrib.get("severity", "warning").upper(),
        file=Path(file_name).name,
        line=int(error.attrib["line"]) if error.attrib.get("line") else None,
        column=int(error.attrib["column"]) if error.attrib.get("column") else None,
        rule=error.attrib.get("source"),
        message=error.attrib.get("message", "Checkstyle violation"),
    )


def _run_checkstyle(source_paths: list[str], temp_dir: str) -> AnalysisToolResult:
    java_path = shutil.which("java")
    checkstyle_jar = Path(
        os.getenv("CHECKSTYLE_JAR", str(APP_ROOT / ".tools" / "checkstyle-14.3.0-all.jar"))
    )
    config_path = Path(os.getenv("CHECKSTYLE_CONFIG", str(APP_ROOT / "checkstyle.xml")))
    if not java_path or not checkstyle_jar.exists() or not config_path.exists():
        return AnalysisToolResult(status="UNAVAILABLE")
    try:
        completed = subprocess.run(
            [java_path, "-jar", str(checkstyle_jar), "-c", str(config_path), "-f", "xml", *source_paths],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=ANALYSIS_TIMEOUT_SECONDS,
            check=False,
        )
        root = ET.fromstring(completed.stdout)
        findings = []
        for file_element in root.findall(".//file"):
            for error in file_element.findall("error"):
                findings.append(_finding_from_checkstyle(error, file_element.attrib.get("name", "unknown")))
        return AnalysisToolResult(status="COMPLETED", findings=findings)
    except (ET.ParseError, OSError, subprocess.TimeoutExpired):
        return AnalysisToolResult(status="FAILED")


def _run_spotbugs(source_dir: str, classes_dir: str) -> AnalysisToolResult:
    spotbugs = os.getenv("SPOTBUGS_COMMAND")
    if not spotbugs:
        default = APP_ROOT / ".tools" / "spotbugs-4.10.4" / "bin" / "spotbugs.bat"
        spotbugs = str(default) if default.exists() else shutil.which("spotbugs")
    if not spotbugs:
        return AnalysisToolResult(status="UNAVAILABLE")
    output_path = Path(source_dir) / "spotbugs.xml"
    try:
        completed = subprocess.run(
            [spotbugs, "-textui", "-xml:withMessages", "-output", str(output_path), "-effort:max", "-low", classes_dir],
            cwd=source_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=ANALYSIS_TIMEOUT_SECONDS,
            check=False,
        )
        if not output_path.exists():
            return AnalysisToolResult(status="FAILED")
        root = ET.parse(output_path).getroot()
        findings = []
        priority_names = {"1": "HIGH", "2": "MEDIUM", "3": "LOW"}
        for bug in root.findall(".//BugInstance"):
            source_line = bug.find(".//SourceLine")
            findings.append(
                AnalysisFinding(
                    tool="SpotBugs",
                    severity=priority_names.get(bug.attrib.get("priority", "3"), "LOW"),
                    file=(source_line.attrib.get("sourcefile", "unknown") if source_line is not None else "unknown"),
                    line=(int(source_line.attrib["start"]) if source_line is not None and source_line.attrib.get("start") else None),
                    rule=bug.attrib.get("type"),
                    message=bug.attrib.get("shortDescription", bug.attrib.get("type", "SpotBugs finding")),
                )
            )
        return AnalysisToolResult(status="COMPLETED", findings=findings)
    except (ET.ParseError, OSError, subprocess.TimeoutExpired):
        return AnalysisToolResult(status="FAILED")


def _find_semgrep() -> Optional[str]:
    candidates = [
        shutil.which("pysemgrep"),
        shutil.which("semgrep"),
        str(Path(sys.executable).parent / "Scripts" / "pysemgrep.exe"),
        str(Path(sys.executable).parent / "Scripts" / "semgrep.exe"),
        str(Path.home() / "AppData" / "Roaming" / "Python" / "Python313" / "Scripts" / "pysemgrep.exe"),
        str(Path.home() / "AppData" / "Roaming" / "Python" / "Python313" / "Scripts" / "semgrep.exe"),
    ]
    return next((candidate for candidate in candidates if candidate and Path(candidate).exists()), None)


def _run_semgrep(source_dir: str, source_paths: list[str]) -> AnalysisToolResult:
    semgrep = _find_semgrep()
    rules_path = APP_ROOT / "semgrep-rules.yml"
    if not semgrep or not rules_path.exists():
        return AnalysisToolResult(status="UNAVAILABLE")
    try:
        completed = subprocess.run(
            [semgrep, "--config", str(rules_path), "--json", "--no-git-ignore", *source_paths],
            cwd=source_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=ANALYSIS_TIMEOUT_SECONDS,
            check=False,
        )
        payload = json.loads(completed.stdout or "{}")
        findings = []
        for result in payload.get("results", []):
            start = result.get("start", {})
            extra = result.get("extra", {})
            findings.append(
                AnalysisFinding(
                    tool="Semgrep",
                    severity=extra.get("severity", "WARNING").upper(),
                    file=Path(result.get("path", "unknown")).name,
                    line=start.get("line"),
                    column=start.get("col"),
                    rule=result.get("check_id"),
                    message=extra.get("message", "Semgrep finding"),
                )
            )
        return AnalysisToolResult(status="COMPLETED", findings=findings)
    except (json.JSONDecodeError, OSError, subprocess.TimeoutExpired):
        return AnalysisToolResult(status="FAILED")


@router.post("/{artifact_id}/analyze", response_model=StaticAnalysisResult)
async def analyze_artifact(artifact_id: str):
    db = get_db()
    artifact = await db.code_artifacts.find_one({"artifact_id": artifact_id})
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if artifact.get("language") != "Java":
        raise HTTPException(status_code=400, detail="Only Java artifacts can be analyzed")
    if not artifact.get("content", "").strip():
        raise HTTPException(status_code=400, detail="Artifact has no Java source code")

    related = await db.code_artifacts.find(
        {"project_id": artifact["project_id"], "requirement_id": artifact["requirement_id"], "language": "Java"}
    ).to_list(1000)
    latest = _latest_artifacts(related)
    if any(not JAVA_FILE_NAME_PATTERN.fullmatch(item["file_name"]) for item in latest):
        raise HTTPException(status_code=400, detail="Artifact contains an unsafe Java filename")

    with tempfile.TemporaryDirectory(prefix="ai-se-analysis-") as temp_dir:
        source_paths = _write_sources(temp_dir, latest)
        checkstyle = _run_checkstyle(source_paths, temp_dir)
        security = _run_semgrep(temp_dir, source_paths)
        javac_path = shutil.which("javac")
        classes_dir = Path(temp_dir) / "classes"
        classes_dir.mkdir()
        spotbugs = AnalysisToolResult(status="NOT_RUN")
        if javac_path:
            compile_result = subprocess.run(
                [javac_path, "-encoding", "UTF-8", "-d", str(classes_dir), *source_paths],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=COMPILE_TIMEOUT_SECONDS,
                check=False,
            )
            if compile_result.returncode == 0:
                spotbugs = _run_spotbugs(temp_dir, str(classes_dir))

    statuses = {checkstyle.status, spotbugs.status, security.status}
    result_status = "COMPLETED" if statuses == {"COMPLETED"} else "PARTIAL"
    result = StaticAnalysisResult(
        analysis_id=str(uuid4()),
        artifact_id=artifact_id,
        status=result_status,
        checkstyle=checkstyle,
        spotbugs=spotbugs,
        security=security,
        created_at=datetime.utcnow(),
    )
    await db.static_analysis_results.insert_one(result.model_dump())
    return result


@router.get("/{artifact_id}/analysis", response_model=Optional[StaticAnalysisResult])
async def get_latest_analysis(artifact_id: str):
    db = get_db()
    artifact = await db.code_artifacts.find_one({"artifact_id": artifact_id})
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return await db.static_analysis_results.find_one(
        {"artifact_id": artifact_id}, sort=[("created_at", -1)]
    )