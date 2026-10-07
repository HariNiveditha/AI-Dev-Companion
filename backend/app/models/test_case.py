from datetime import datetime

from pydantic import BaseModel


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
