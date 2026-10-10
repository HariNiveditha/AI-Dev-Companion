import difflib
from datetime import datetime
from typing import Optional
from uuid import uuid4

from app.db.mongodb import get_db
from app.models.code_artifact import (
    AnalysisFinding,
    CodeArtifact,
    CompileResult,
    StaticAnalysisResult,
)
from app.models.improvement import (
    CodeImprovementResponse,
    FindingComparison,
    ImprovementComparison,
    ImprovementProposal,
)


def generate_diff(original: str, improved: str, file_name: str = "file.java") -> str:
    """Generate a unified diff between original and improved source code."""
    original_lines = original.splitlines(keepends=True)
    improved_lines = improved.splitlines(keepends=True)

    diff = difflib.unified_diff(
        original_lines,
        improved_lines,
        fromfile=f"a/{file_name}",
        tofile=f"b/{file_name}",
        lineterm="",
    )
    return "".join(diff)


def _finding_key(finding: AnalysisFinding) -> tuple:
    """Create a stable key for matching findings across analyses."""
    return (
        finding.tool,
        finding.rule or "",
        finding.file,
        finding.message.strip().lower(),
    )


def compare_findings(
    before: list[AnalysisFinding],
    after: list[AnalysisFinding],
) -> tuple[list[AnalysisFinding], list[AnalysisFinding], list[AnalysisFinding], list[AnalysisFinding]]:
    """
    Compare findings before and after improvement.

    Returns: (resolved, remaining, new, unmatched)
    """
    before_keys = {_finding_key(f): f for f in before}
    after_keys = {_finding_key(f): f for f in after}

    resolved = []
    remaining = []
    new_findings = []
    unmatched = []

    # Check before findings
    for key, finding in before_keys.items():
        if key in after_keys:
            remaining.append(finding)
        else:
            resolved.append(finding)

    # Check after findings
    for key, finding in after_keys.items():
        if key not in before_keys:
            new_findings.append(finding)

    return resolved, remaining, new_findings, unmatched


async def create_proposal(
    artifact_id: str,
    improved_content: str,
    explanation: str,
    findings_addressed: list[AnalysisFinding],
    non_actionable_findings: list[AnalysisFinding],
) -> ImprovementProposal:
    """Create and persist an improvement proposal."""
    db = get_db()
    artifact = await db.code_artifacts.find_one({"artifact_id": artifact_id})
    if not artifact:
        raise ValueError("Artifact not found")

    now = datetime.utcnow()
    proposal = ImprovementProposal(
        proposal_id=str(uuid4()),
        artifact_id=artifact_id,
        project_id=artifact["project_id"],
        requirement_id=artifact["requirement_id"],
        file_name=artifact["file_name"],
        original_content=artifact["content"],
        improved_content=improved_content,
        explanation=explanation,
        findings_addressed=findings_addressed,
        non_actionable_findings=non_actionable_findings,
        status="PENDING",
        created_at=now,
        updated_at=now,
    )

    await db.improvement_proposals.insert_one(proposal.model_dump())
    return proposal


async def get_proposal(proposal_id: str) -> Optional[ImprovementProposal]:
    """Retrieve an improvement proposal by ID."""
    db = get_db()
    data = await db.improvement_proposals.find_one({"proposal_id": proposal_id})
    if not data:
        return None
    return ImprovementProposal.model_validate(data)


async def accept_proposal(
    proposal_id: str,
    compile_result: Optional[CompileResult] = None,
    after_analysis: Optional[StaticAnalysisResult] = None,
) -> ImprovementProposal:
    """
    Accept an improvement proposal and create a new artifact version.

    This function:
    1. Verifies the proposal is in PENDING status
    2. Creates a new artifact version with the improved content
    3. Marks the proposal as ACCEPTED
    4. Stores compilation and analysis results
    """
    db = get_db()
    proposal_data = await db.improvement_proposals.find_one({"proposal_id": proposal_id})
    if not proposal_data:
        raise ValueError("Proposal not found")

    proposal = ImprovementProposal.model_validate(proposal_data)
    if proposal.status != "PENDING":
        raise ValueError(f"Cannot accept proposal with status {proposal.status}")

    # Verify the original artifact still exists
    original_artifact = await db.code_artifacts.find_one(
        {"artifact_id": proposal.artifact_id}
    )
    if not original_artifact:
        raise ValueError("Original artifact no longer exists")

    # Create new artifact version
    now = datetime.utcnow()
    related_artifacts = await db.code_artifacts.find(
        {
            "project_id": proposal.project_id,
            "requirement_id": proposal.requirement_id,
            "file_name": proposal.file_name,
        }
    ).to_list(1000)
    next_version = max(
        (a.get("version", 0) for a in related_artifacts),
        default=0,
    ) + 1

    new_artifact = CodeArtifact(
        artifact_id=str(uuid4()),
        project_id=proposal.project_id,
        requirement_id=proposal.requirement_id,
        file_name=proposal.file_name,
        language="Java",
        content=proposal.improved_content,
        version=next_version,
        source="DEVELOPER_EDITED",
        status="EDITED",
        created_at=now,
        updated_at=now,
    )

    await db.code_artifacts.insert_one(new_artifact.model_dump())

    # Update proposal
    await db.improvement_proposals.update_one(
        {"proposal_id": proposal_id},
        {
            "$set": {
                "status": "ACCEPTED",
                "accepted_artifact_id": new_artifact.artifact_id,
                "accepted_version": next_version,
                "compile_result": compile_result.model_dump() if compile_result else None,
                "after_analysis": after_analysis.model_dump() if after_analysis else None,
                "accepted_at": now,
                "updated_at": now,
            }
        },
    )

    # Return updated proposal
    updated = await db.improvement_proposals.find_one({"proposal_id": proposal_id})
    return ImprovementProposal.model_validate(updated)


async def reject_proposal(proposal_id: str) -> ImprovementProposal:
    """Reject an improvement proposal without modifying any artifacts."""
    db = get_db()
    proposal_data = await db.improvement_proposals.find_one({"proposal_id": proposal_id})
    if not proposal_data:
        raise ValueError("Proposal not found")

    proposal = ImprovementProposal.model_validate(proposal_data)
    if proposal.status != "PENDING":
        raise ValueError(f"Cannot reject proposal with status {proposal.status}")

    now = datetime.utcnow()
    await db.improvement_proposals.update_one(
        {"proposal_id": proposal_id},
        {
            "$set": {
                "status": "REJECTED",
                "rejected_at": now,
                "updated_at": now,
            }
        },
    )

    updated = await db.improvement_proposals.find_one({"proposal_id": proposal_id})
    return ImprovementProposal.model_validate(updated)


async def get_comparison(proposal_id: str) -> Optional[ImprovementComparison]:
    """Get before-and-after comparison for an accepted proposal."""
    db = get_db()
    proposal_data = await db.improvement_proposals.find_one({"proposal_id": proposal_id})
    if not proposal_data:
        return None

    proposal = ImprovementProposal.model_validate(proposal_data)

    # Get original analysis
    original_analysis = None
    if proposal.artifact_id:
        original_analysis = await db.static_analysis_results.find_one(
            {"artifact_id": proposal.artifact_id},
            sort=[("created_at", -1)],
        )

    # Get improved analysis
    improved_analysis = None
    if proposal.accepted_artifact_id:
        improved_analysis = await db.static_analysis_results.find_one(
            {"artifact_id": proposal.accepted_artifact_id},
            sort=[("created_at", -1)],
        )

    # Get original compile result
    original_compile = None
    if proposal.artifact_id:
        # Compile results are stored on the artifact or in a separate collection
        # For now, we'll check if there's a compile result stored
        pass

    # Compare findings
    before_findings: list[AnalysisFinding] = []
    after_findings: list[AnalysisFinding] = []

    if original_analysis:
        for tool_result in [
            original_analysis.get("checkstyle", {}),
            original_analysis.get("spotbugs", {}),
            original_analysis.get("security", {}),
        ]:
            if isinstance(tool_result, dict):
                for f in tool_result.get("findings", []):
                    before_findings.append(AnalysisFinding.model_validate(f))

    if improved_analysis:
        for tool_result in [
            improved_analysis.get("checkstyle", {}),
            improved_analysis.get("spotbugs", {}),
            improved_analysis.get("security", {}),
        ]:
            if isinstance(tool_result, dict):
                for f in tool_result.get("findings", []):
                    after_findings.append(AnalysisFinding.model_validate(f))

    resolved, remaining, new_findings, unmatched = compare_findings(
        before_findings, after_findings
    )

    # Get original artifact version
    original_artifact = await db.code_artifacts.find_one(
        {"artifact_id": proposal.artifact_id}
    )
    original_version = original_artifact.get("version", 0) if original_artifact else 0

    return ImprovementComparison(
        proposal_id=proposal_id,
        original_artifact_id=proposal.artifact_id,
        original_version=original_version,
        improved_artifact_id=proposal.accepted_artifact_id,
        improved_version=proposal.accepted_version,
        original_analysis=StaticAnalysisResult.model_validate(original_analysis) if original_analysis else None,
        improved_analysis=StaticAnalysisResult.model_validate(improved_analysis) if improved_analysis else None,
        original_compile_status=proposal.compile_result.status if proposal.compile_result else None,
        improved_compile_status=proposal.compile_result.status if proposal.compile_result else None,
        findings_resolved=resolved,
        findings_remaining=remaining,
        findings_new=new_findings,
        findings_unmatched=unmatched,
        total_before=len(before_findings),
        total_after=len(after_findings),
        created_at=datetime.utcnow(),
    )
