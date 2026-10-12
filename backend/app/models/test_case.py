from datetime import datetime
from typing import List, Literal

from pydantic import BaseModel, Field


class TestCase(BaseModel):
    test_case_id: str
    requirement_id: str
    title: str
    description: str
    input: str
    expected_output: str
    priority: str
    type: str
    created_at: datetime


class TestCaseCreate(BaseModel):
    requirement_id: str
    title: str
    description: str
    input: str
    expected_output: str
    priority: str
    type: str


class TestCaseDraft(BaseModel):
    title: str
    description: str
    input: str
    expected_output: str
    priority: str
    type: str


class TestCaseGenerationResponse(BaseModel):
    test_cases: List[TestCaseDraft]


# ---------------------------------------------------------------------------
# Phase 9: executable test sources
# ---------------------------------------------------------------------------

class ExecutableTest(BaseModel):
    """A stored, compilable JUnit 5 test source for one requirement.

    Descriptive ``TestCase`` records (Phase 6) are never executed directly.
    They are *implemented by* an executable test source: ``method_map`` links
    each descriptive test-case id to the JUnit ``@Test`` method that verifies
    it. Only the executable source is compiled and run.
    """

    executable_test_id: str
    project_id: str
    requirement_id: str
    class_name: str
    file_name: str
    content: str
    version: int = Field(default=1, ge=1)
    # test_case_id -> JUnit method name implementing that case.
    method_map: dict = Field(default_factory=dict)
    source: Literal["AI_GENERATED", "DEVELOPER_EDITED"]
    created_at: datetime
    updated_at: datetime


class ExecutableTestCreate(BaseModel):
    content: str = Field(min_length=1)
    method_map: dict = Field(default_factory=dict)


class ExecutableTestGenerateRequest(BaseModel):
    test_case_ids: List[str]


class MethodLink(BaseModel):
    """One descriptive test case implemented by one JUnit method.

    A list of links is used instead of a ``dict`` because the Gemini
    Developer API rejects ``additionalProperties`` in structured-output
    schemas, which every map shape produces. The endpoint converts these
    links into the stored ``method_map`` after validation.
    """

    test_case_id: str
    method: str


class ExecutableTestDraft(BaseModel):
    """Structured response the AI must return for executable-test generation."""

    content: str
    method_links: List[MethodLink] = Field(default_factory=list)


class ExecutableTestGenerationResponse(BaseModel):
    test_class: ExecutableTestDraft
