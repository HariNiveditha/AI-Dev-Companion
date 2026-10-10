import os
import re
import shutil
import subprocess
import tempfile
import time
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
    CompileResult,
    StaticAnalysisResult,
)
from app.models.improvement import (
    CodeImprovementResponse,
    ImprovementComparison,
    ImprovementProposal,
)
from app.services.ai.service import generate_code_improvement
from app.services.improvement import (
    accept_proposal,
    compare_findings,
    create_proposal,
    generate_diff,
    get_comparison,
    get_proposal,
    reject_proposal,
)

router = APIRouter(prefix="/improvements", tags=["Improvements"])

JAVA_FILE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.java$")
COMPILE_TIMEOUT_SECONDS = 15
ANALYSIS_TIMEOUT_SECONDS = 30
APP_ROOT = Path(__file__).resolve().parents[2]


@router.post("/generate", response_model=ImprovementProposal)
async def generate_improvement(artifact_id: str):
    """
    Generate an AI-powered code improvement proposal based on static analysis findings.

    This endpoint:
    1. Retrieves the artifact and its latest analysis
    2. Sends source code + findings + requirements to Gemini
    3. Validates the AI response
    4. Persists an improvement proposal
    5. Returns the proposal with diff
    """
    db = get_db()

    # Get the artifact
    artifact = await db.code_artifacts.find_one({"artifact_id": artifact_id})
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.get("language") != "Java":
        raise HTTPException(status_code=400, detail="Only Java artifacts can be improved")

    if not artifact.get("content", "").strip():
        raise HTTPException(status_code=400, detail="Artifact has no Java source code")

    # Get the requirement
    requirement = await db.requirements.find_one(
        {"_id": artifact["requirement_id"]}
    )
    if not requirement:
        raise HTTPException(status_code=404, detail="Associated requirement not found")

    # Get the latest analysis
    analysis = await db.static_analysis_results.find_one(
        {"artifact_id": artifact_id},
        sort=[("created_at", -1)],
    )

    if not analysis:
        raise HTTPException(
            status_code=400,
            detail="Static analysis has not been run for this artifact. Run analysis first.",
        )

    # Collect findings from all tools
    findings: list[AnalysisFinding] = []
    for tool_key in ["checkstyle", "spotbugs", "security"]:
        tool_result = analysis.get(tool_key, {})
        if isinstance(tool_result, dict):
            for f in tool_result.get("findings", []):
                findings.append(AnalysisFinding.model_validate(f))

    if not findings:
        raise HTTPException(
            status_code=400,
            detail="No static analysis findings to improve. Analysis completed with zero findings.",
        )

    # Prepare findings for AI
    findings_for_ai = [
        {
            "tool": f.tool,
            "severity": f.severity,
            "file": f.file,
            "line": f.line,
            "column": f.column,
            "rule": f.rule,
            "message": f.message,
        }
        for f in findings
    ]

    # Call AI service
    try:
        ai_response = generate_code_improvement(
            title=requirement["title"],
            description=requirement["description"],
            source_code=artifact["content"],
            findings=findings_for_ai,
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI improvement failed: {str(e)}")

    # Validate AI response
    if not ai_response.improved_content.strip():
        raise HTTPException(
            status_code=502,
            detail="AI returned empty improved content",
        )

    if ai_response.improved_content.strip() == artifact["content"].strip():
        raise HTTPException(
            status_code=400,
            detail="AI did not propose any changes. All findings may be non-actionable.",
        )

    # Determine which findings were addressed
    findings_addressed = []
    non_actionable = []

    # Simple heuristic: if the AI mentioned a finding rule or message, consider it addressed
    explanation_lower = ai_response.explanation.lower()
    for finding in findings:
        finding_text = f"{finding.rule or ''} {finding.message}".lower()
        # Check if the finding is mentioned in the explanation or findings_addressed
        addressed = False
        for addr_desc in ai_response.findings_addressed:
            if finding.rule and finding.rule.lower() in addr_desc.lower():
                addressed = True
                break
            if finding.message.lower() in addr_desc.lower():
                addressed = True
                break

        if addressed:
            findings_addressed.append(finding)
        else:
            non_actionable.append(finding)

    # Create and persist proposal
    try:
        proposal = await create_proposal(
            artifact_id=artifact_id,
            improved_content=ai_response.improved_content,
            explanation=ai_response.explanation,
            findings_addressed=findings_addressed,
            non_actionable_findings=non_actionable,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to persist proposal: {str(e)}")

    return proposal


@router.get("/{proposal_id}", response_model=ImprovementProposal)
async def get_improvement_proposal(proposal_id: str):
    """Retrieve an improvement proposal by ID."""
    proposal = await get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@router.post("/{proposal_id}/accept", response_model=ImprovementProposal)
async def accept_improvement(proposal_id: str):
    """
    Accept an improvement proposal and create a new artifact version.

    After acceptance:
    1. Creates a new artifact version with improved content
    2. Compiles the new version
    3. Runs static analysis on the new version
    4. Returns the updated proposal with results
    """
    db = get_db()

    # Get the proposal
    proposal = await get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != "PENDING":
        raise HTTPException(
            status_code=409,
            detail=f"Proposal has already been {proposal.status.lower()}",
        )

    # Verify the original artifact still exists and hasn't changed
    original_artifact = await db.code_artifacts.find_one(
        {"artifact_id": proposal.artifact_id}
    )
    if not original_artifact:
        raise HTTPException(
            status_code=410,
            detail="Original artifact no longer exists",
        )

    if original_artifact["content"] != proposal.original_content:
        raise HTTPException(
            status_code=409,
            detail="Original artifact has changed since the proposal was generated. Please generate a new proposal.",
        )

    # Accept the proposal and create new artifact version
    try:
        accepted = await accept_proposal(proposal_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Now compile and analyze the new version
    new_artifact_id = accepted.accepted_artifact_id

    # Compile the new version
    compile_result = await _compile_artifact_internal(new_artifact_id)

    # Run static analysis on the new version
    after_analysis = await _analyze_artifact_internal(new_artifact_id)

    # Update proposal with results
    await db.improvement_proposals.update_one(
        {"proposal_id": proposal_id},
        {
            "$set": {
                "compile_result": compile_result.model_dump() if compile_result else None,
                "after_analysis": after_analysis.model_dump() if after_analysis else None,
            }
        },
    )

    # Return updated proposal
    updated = await get_proposal(proposal_id)
    return updated


@router.post("/{proposal_id}/reject", response_model=ImprovementProposal)
async def reject_improvement(proposal_id: str):
    """Reject an improvement proposal without modifying any artifacts."""
    proposal = await get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != "PENDING":
        raise HTTPException(
            status_code=409,
            detail=f"Proposal has already been {proposal.status.lower()}",
        )

    try:
        rejected = await reject_proposal(proposal_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return rejected


@router.get("/{proposal_id}/comparison", response_model=ImprovementComparison)
async def get_improvement_comparison(proposal_id: str):
    """Get before-and-after comparison for an accepted proposal."""
    comparison = await get_comparison(proposal_id)
    if not comparison:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return comparison


@router.get("/{proposal_id}/diff")
async def get_improvement_diff(proposal_id: str):
    """Get the unified diff for an improvement proposal."""
    proposal = await get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    diff = generate_diff(
        proposal.original_content,
        proposal.improved_content,
        proposal.file_name,
    )
    return {"diff": diff}


# Internal helper functions for compile and analyze
# These reuse the logic from artifacts.py but work with artifact IDs directly

async def _compile_artifact_internal(artifact_id: str) -> Optional[CompileResult]:
    """Compile an artifact and return the result."""
    db = get_db()
    artifact = await db.code_artifacts.find_one({"artifact_id": artifact_id})
    if not artifact:
        return None

    javac_path = shutil.which("javac")
    if not javac_path:
        return CompileResult(
            artifact_id=artifact_id,
            status="TOOL_ERROR",
            stderr="javac was not found. Install a JDK or configure a Java compiler.",
            duration_ms=0,
            timestamp=datetime.utcnow(),
        )

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
        return CompileResult(
            artifact_id=artifact_id,
            status="TOOL_ERROR",
            stderr="Artifact contains an unsafe Java filename",
            duration_ms=0,
            timestamp=datetime.utcnow(),
        )

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


async def _analyze_artifact_internal(artifact_id: str) -> Optional[StaticAnalysisResult]:
    """Run static analysis on an artifact and return the result."""
    db = get_db()
    artifact = await db.code_artifacts.find_one({"artifact_id": artifact_id})
    if not artifact:
        return None

    related = await db.code_artifacts.find(
        {"project_id": artifact["project_id"], "requirement_id": artifact["requirement_id"], "language": "Java"}
    ).to_list(1000)
    latest = _latest_artifacts(related)
    if any(not JAVA_FILE_NAME_PATTERN.fullmatch(item["file_name"]) for item in latest):
        return None

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
    import sys
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
        import json
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
