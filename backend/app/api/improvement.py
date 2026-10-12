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
    AnalyzedFile,
    CodeArtifact,
    CompileResult,
    StaticAnalysisResult,
)
from app.models.improvement import (
    CodeImprovementResponse,
    ImprovementComparison,
    ImprovementProposal,
    ReviewDecisionRequest,
)
from app.services.ai.service import generate_code_improvement
from app.services.improvement import (
    accept_proposal,
    compare_findings,
    create_proposal,
    generate_diff,
    get_comparison,
    get_proposal,
    list_proposals,
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

    # Collect findings from all tools, assigning each a stable ID so the AI's
    # response can be mapped back without guesswork.
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

    finding_ids: dict[str, AnalysisFinding] = {}
    findings_for_ai: list[dict] = []
    for index, f in enumerate(findings, start=1):
        finding_id = f"F{index}"
        finding_ids[finding_id] = f
        findings_for_ai.append(
            {
                "finding_id": finding_id,
                "tool": f.tool,
                "severity": f.severity,
                "file": f.file,
                "line": f.line,
                "column": f.column,
                "rule": f.rule,
                "message": f.message,
            }
        )

    # Build the full analyzed source context.  Findings routinely reference
    # files other than the selected artifact, so the AI must see every file in
    # the analysis snapshot or it cannot fix them.
    source_files = await _analyzed_source_files(analysis, artifact)
    # Map file_name -> artifact_id for every analyzed file, so a proposal can
    # target a file other than the one the user selected.
    artifact_id_by_file = await _analyzed_artifact_ids(analysis, artifact)

    # Call AI service
    try:
        ai_response = generate_code_improvement(
            title=requirement["title"],
            description=requirement["description"],
            source_files=source_files,
            findings=findings_for_ai,
            target_file=artifact["file_name"],
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI improvement failed: {str(e)}")

    # Resolve which file the AI actually improved.  It may differ from the
    # selected artifact when the actionable findings live in another file.
    target_name = (getattr(ai_response, "target_file", None) or "").strip()
    if not target_name or target_name not in source_files:
        target_name = artifact["file_name"]
    improved_artifact_id = artifact_id_by_file.get(target_name, artifact_id)
    original_target_content = source_files[target_name]

    # Validate AI response
    if not ai_response.improved_content.strip():
        raise HTTPException(
            status_code=502,
            detail="AI returned empty improved content",
        )

    if ai_response.improved_content.strip() == original_target_content.strip():
        # Valid review, no safe source change: a completed outcome, not an
        # error. Persist it as a terminal NO_CHANGE proposal so the per-finding
        # verdicts stay visible. Nothing is addressed (no code changed), every
        # finding stays on record, and no new artifact version is created.
        assessments = getattr(ai_response, "finding_assessments", None) or []
        explanation = (
            f"Review completed — no source change recommended for {target_name}. "
            + ai_response.explanation.strip()
        )
        try:
            no_change = await create_proposal(
                artifact_id=improved_artifact_id,
                improved_content=original_target_content,
                explanation=explanation,
                findings_addressed=[],
                non_actionable_findings=list(finding_ids.values()),
                finding_assessments=assessments,
                formatting_notes=[],
                status="NO_CHANGE",
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to persist proposal: {str(e)}")
        return no_change

    # Structural validation: reject malformed Java before persisting.
    from app.services.java_validator import validate_java_source

    validation = validate_java_source(ai_response.improved_content)
    if not validation.ok:
        detail = (
            f"AI returned structurally invalid Java source for {target_name}: "
            + "; ".join(validation.errors)
            + ". Please regenerate the improvement proposal."
        )
        raise HTTPException(status_code=502, detail=detail)

    # Regression guard: the AI regenerates the whole file and sometimes
    # re-indents lines no finding requires (observed: closing braces at 8
    # spaces instead of 4, producing new IndentationCheck violations).
    # Revert whitespace-only changes that no indentation finding justifies
    # so the proposal preserves already-correct code.
    from app.services.format_guard import (
        indentation_finding_lines,
        preserve_unrelated_formatting,
        restoration_notes,
    )

    justified = indentation_finding_lines(findings_for_ai, target_name)
    guarded_content, restorations = preserve_unrelated_formatting(
        original_target_content, ai_response.improved_content, justified
    )
    if guarded_content.strip() == original_target_content.strip():
        # The AI changed nothing except whitespace it was not asked to touch.
        raise HTTPException(
            status_code=502,
            detail=(
                f"AI returned only unjustified formatting changes for {target_name} "
                "and no code fix. Please regenerate the improvement proposal."
            ),
        )
    formatting_notes = restoration_notes(restorations)

    # Map the AI's verdicts back to real findings by ID.
    findings_addressed, non_actionable = _map_finding_verdicts(
        ai_response, finding_ids
    )

    # Create and persist proposal against the file that was actually improved.
    try:
        proposal = await create_proposal(
            artifact_id=improved_artifact_id,
            improved_content=guarded_content,
            explanation=ai_response.explanation,
            findings_addressed=findings_addressed,
            non_actionable_findings=non_actionable,
            finding_assessments=getattr(ai_response, "finding_assessments", None) or [],
            formatting_notes=formatting_notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to persist proposal: {str(e)}")

    return proposal


def _map_finding_verdicts(
    ai_response: "CodeImprovementResponse",
    finding_ids: dict[str, AnalysisFinding],
) -> tuple[list[AnalysisFinding], list[AnalysisFinding]]:
    """Split findings into addressed vs not, using explicit IDs and verdicts.

    An ID counts as addressed only if the AI listed it in addressed_finding_ids
    or assessed it ACTIONABLE.  Anything else is reported honestly as not fixed.
    """
    addressed: set[str] = set(getattr(ai_response, "addressed_finding_ids", None) or [])
    for assessment in getattr(ai_response, "finding_assessments", None) or []:
        if assessment.classification == "ACTIONABLE":
            addressed.add(assessment.finding_id)

    findings_addressed: list[AnalysisFinding] = []
    non_actionable: list[AnalysisFinding] = []
    for finding_id, finding in finding_ids.items():
        if finding_id in addressed:
            findings_addressed.append(finding)
        else:
            non_actionable.append(finding)
    return findings_addressed, non_actionable


async def _analyzed_source_files(
    analysis: dict, artifact: dict
) -> dict[str, str]:
    """Load the exact source of every file in the analysis snapshot.

    Falls back to the latest version of any file that is no longer resolvable,
    and always includes the selected artifact so it can be improved.
    """
    db = get_db()
    source_files: dict[str, str] = {artifact["file_name"]: artifact["content"]}

    for analyzed in analysis.get("analyzed_files", []) or []:
        file_name = analyzed.get("file_name")
        analyzed_artifact_id = analyzed.get("artifact_id")
        if not file_name or file_name in source_files:
            continue
        doc = None
        if analyzed_artifact_id:
            doc = await db.code_artifacts.find_one({"artifact_id": analyzed_artifact_id})
        if not doc:
            latest = await db.code_artifacts.find(
                {"project_id": artifact["project_id"], "requirement_id": artifact["requirement_id"], "file_name": file_name}
            ).sort("version", -1).to_list(1)
            doc = latest[0] if latest else None
        if doc and doc.get("content"):
            source_files[file_name] = doc["content"]

    return source_files


async def _analyzed_artifact_ids(analysis: dict, artifact: dict) -> dict[str, str]:
    """Map file_name -> artifact_id for every file in the analysis snapshot.

    Lets a proposal target a file other than the selected artifact when the
    actionable findings live elsewhere.
    """
    db = get_db()
    ids: dict[str, str] = {artifact["file_name"]: artifact["artifact_id"]}

    for analyzed in analysis.get("analyzed_files", []) or []:
        file_name = analyzed.get("file_name")
        analyzed_artifact_id = analyzed.get("artifact_id")
        if not file_name or file_name in ids:
            continue
        if analyzed_artifact_id and await db.code_artifacts.find_one({"artifact_id": analyzed_artifact_id}):
            ids[file_name] = analyzed_artifact_id
            continue
        latest = await db.code_artifacts.find(
            {"project_id": artifact["project_id"], "requirement_id": artifact["requirement_id"], "file_name": file_name}
        ).sort("version", -1).to_list(1)
        if latest:
            ids[file_name] = latest[0]["artifact_id"]

    return ids


@router.get("", response_model=list[ImprovementProposal])
async def list_improvement_proposals(
    artifact_id: Optional[str] = None,
    requirement_id: Optional[str] = None,
    project_id: Optional[str] = None,
):
    """Retrieve improvement proposals with optional filtering."""
    return await list_proposals(
        artifact_id=artifact_id,
        requirement_id=requirement_id,
        project_id=project_id,
    )


@router.get("/{proposal_id}", response_model=ImprovementProposal)
async def get_improvement_proposal(proposal_id: str):
    """Retrieve an improvement proposal by ID."""
    proposal = await get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@router.post("/{proposal_id}/accept", response_model=ImprovementProposal)
async def accept_improvement(
    proposal_id: str,
    review_req: Optional[ReviewDecisionRequest] = None,
):
    """
    Accept an improvement proposal and create a new artifact version.

    After acceptance:
    1. Validates proposal is pending and not terminal
    2. Validates target artifact exists and has not changed or evolved to a newer version
    3. Runs Java structural validation on the proposed content
    4. Creates a new artifact version with improved content
    5. Compiles the new version
    6. Runs static analysis on the new version
    7. Persists review metadata and returns the updated proposal with results
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

    # Check if a newer version of the target file was created after this proposal
    latest_docs = await db.code_artifacts.find(
        {
            "project_id": proposal.project_id,
            "requirement_id": proposal.requirement_id,
            "file_name": proposal.file_name,
        }
    ).sort("version", -1).to_list(1)
    latest_version = latest_docs[0]["version"] if latest_docs else 0
    if latest_version > original_artifact.get("version", 0):
        raise HTTPException(
            status_code=409,
            detail=f"Target artifact has evolved to version {latest_version} (proposal was based on version {original_artifact.get('version', 0)}). Please generate a new proposal.",
        )

    # Validate Java syntax/structure before accepting
    from app.services.java_validator import validate_java_source
    validation = validate_java_source(proposal.improved_content)
    if not validation.ok:
        raise HTTPException(
            status_code=422,
            detail=f"Proposed changes failed Java structural validation: {'; '.join(validation.errors)}",
        )

    comment = review_req.comment if review_req else None
    reviewer = review_req.reviewer if review_req else "local-developer"

    # Accept the proposal and create new artifact version
    try:
        accepted = await accept_proposal(
            proposal_id,
            comment=comment,
            reviewer=reviewer,
        )
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
async def reject_improvement(
    proposal_id: str,
    review_req: Optional[ReviewDecisionRequest] = None,
):
    """Reject an improvement proposal without modifying any artifacts."""
    proposal = await get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != "PENDING":
        raise HTTPException(
            status_code=409,
            detail=f"Proposal has already been {proposal.status.lower()}",
        )

    comment = review_req.comment if review_req else None
    reviewer = review_req.reviewer if review_req else "local-developer"

    try:
        rejected = await reject_proposal(
            proposal_id,
            comment=comment,
            reviewer=reviewer,
        )
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
    snapshot = _build_analysis_snapshot(related, artifact)
    if any(not JAVA_FILE_NAME_PATTERN.fullmatch(item["file_name"]) for item in snapshot):
        return None

    with tempfile.TemporaryDirectory(prefix="ai-se-analysis-") as temp_dir:
        source_paths = _write_sources(temp_dir, snapshot)
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
        version=artifact.get("version"),
        analyzed_files=_analyzed_files(snapshot),
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


def _build_analysis_snapshot(related: list[dict], selected: dict) -> list[dict]:
    """Pin the selected file to its chosen version; latest for every other file.

    Keeps the analyzed content scoped to the artifact the caller asked about
    instead of silently jumping to the newest code for that file.
    """
    snapshot_by_file: dict[str, dict] = {
        item["file_name"]: item for item in _latest_artifacts(related)
    }
    snapshot_by_file[selected["file_name"]] = selected
    return list(snapshot_by_file.values())


def _analyzed_files(snapshot: list[dict]) -> list[AnalyzedFile]:
    return [
        AnalyzedFile(
            artifact_id=item["artifact_id"],
            file_name=item["file_name"],
            version=item.get("version", 0),
        )
        for item in snapshot
    ]


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
