from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class RequirementAnalysis(BaseModel):
    functional_requirements: List[str] = []
    non_functional_requirements: List[str] = []
    assumptions: List[str] = []
    ambiguities: List[str] = []
    edge_cases: List[str] = []
    acceptance_criteria: List[str] = []

class Requirement(BaseModel):
    id: str = Field(alias="_id", default=None)
    projectId: str
    title: str
    description: str
    status: str = "DRAFT" # DRAFT, ANALYZING, ANALYZED, ANALYSIS_FAILED, CONFIRMED
    analysis: Optional[RequirementAnalysis] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)

class RequirementCreate(BaseModel):
    title: str
    description: str
