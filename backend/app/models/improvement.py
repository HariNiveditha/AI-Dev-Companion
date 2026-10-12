from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.code_artifact import AnalysisFinding, CompileResult, StaticAnalysisResult


class FindingAssessment(BaseModel):
    """The AI's per-finding evaluation.

    Every finding sent to the model must be accounted for exactly once so the
    backend can report honestly instead of guessing from free text.
    """

    finding_id: str
    classification: Literal["ACTIONABLE", "NON_ACTIONABLE", "NEEDS_CONTEXT"]
    reasoning: str = ""


class CodeImprovementResponse(BaseModel):
    """Structured response from the AI for a code improvement proposal."""

    improved_content: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    # The file improved_content belongs to.  Findings often live in a different
    # file than the one the user selected, so the model picks the file it
    # actually fixed.  Defaults to the selected artifact when omitted.
    target_file: Optional[str] = None
    findings_addressed: List[str] = Field(default_factory=list)
    non_actionable_findings: List[str] = Field(default_factory=list)
    # Explicit finding IDs (e.g. "F1") tied to the changes in improved_content.
    addressed_finding_ids: List[str] = Field(default_factory=list)
    # One assessment per finding the model was given, keyed by finding_id.
    finding_assessments: List[FindingAssessment] = Field(default_factory=list)


class ImprovementProposal(BaseModel):
    """A persisted AI-generated code improvement proposal."""

    proposal_id: str
    artifact_id: str
    project_id: str
    requirement_id: str
    file_name: str
    original_content: str
    improved_content: str
    explanation: str
    findings_addressed: List[AnalysisFinding] = Field(default_factory=list)
    non_actionable_findings: List[AnalysisFinding] = Field(default_factory=list)
    # Per-finding classification returned by the AI, keyed by finding_id.
    finding_assessments: List[FindingAssessment] = Field(default_factory=list)
    # Whitespace-only AI changes that the format guard reverted because no
    # finding justified them (surfaced so the reversion is never silent).
    formatting_notes: List[str] = Field(default_factory=list)
    status: Literal["PENDING", "ACCEPTED", "REJECTED", "NO_CHANGE"] = "PENDING"
    compile_result: Optional[CompileResult] = None
    after_analysis: Optional[StaticAnalysisResult] = None
    accepted_artifact_id: Optional[str] = None
    accepted_version: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    accepted_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None


class FindingComparison(BaseModel):
    """Comparison of a single finding before and after improvement."""

    finding: AnalysisFinding
    status: Literal["RESOLVED", "REMAINING", "NEW"]
    matched: bool = True


class ImprovementComparison(BaseModel):
    """Before-and-after comparison of static analysis findings."""

    proposal_id: str
    original_artifact_id: str
    original_version: int
    improved_artifact_id: Optional[str] = None
    improved_version: Optional[int] = None
    original_analysis: Optional[StaticAnalysisResult] = None
    improved_analysis: Optional[StaticAnalysisResult] = None
    original_compile_status: Optional[str] = None
    improved_compile_status: Optional[str] = None
    findings_resolved: List[AnalysisFinding] = Field(default_factory=list)
    findings_remaining: List[AnalysisFinding] = Field(default_factory=list)
    findings_new: List[AnalysisFinding] = Field(default_factory=list)
    findings_unmatched: List[AnalysisFinding] = Field(default_factory=list)
    total_before: int = 0
    total_after: int = 0
    created_at: datetime
