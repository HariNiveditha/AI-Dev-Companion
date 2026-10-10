
from app.models.requirement import RequirementAnalysis
from app.models.code_artifact import GeneratedCodeResponse
from app.models.test_case import TestCaseGenerationResponse
from app.models.improvement import CodeImprovementResponse

from .provider import AIProvider
from .prompts import (
    get_requirement_analysis_prompt,
    get_code_generation_prompt,
    get_test_case_generation_prompt,
    get_code_improvement_prompt,
)


def analyze_requirement_text(
    title: str, description: str
) -> RequirementAnalysis:
    provider = AIProvider()
    prompt = get_requirement_analysis_prompt(title, description)
    return provider.analyze_requirement(prompt, RequirementAnalysis)


def generate_java_code(
    title: str,
    description: str,
    analysis: RequirementAnalysis,
) -> GeneratedCodeResponse:
    prompt = get_code_generation_prompt(
        title, description, analysis.model_dump()
    )
    provider = AIProvider()
    response = provider.generate_code(prompt, GeneratedCodeResponse)

    # Preserve the original AI-generated source.
    # Do not modify Java using regex-based formatting.
    return response


def generate_test_cases(
    title: str,
    description: str,
    analysis: RequirementAnalysis,
) -> TestCaseGenerationResponse:
    prompt = get_test_case_generation_prompt(
        title, description, analysis.model_dump()
    )
    provider = AIProvider()
    return provider.generate_test_cases(
        prompt, TestCaseGenerationResponse
    )


def generate_code_improvement(
    title: str,
    description: str,
    source_code: str,
    findings: list[dict],
) -> CodeImprovementResponse:
    prompt = get_code_improvement_prompt(
        title, description, source_code, findings
    )
    provider = AIProvider()
    response = provider.generate_code(prompt, CodeImprovementResponse)

    # Preserve the improved source exactly as returned by the AI.
    # Validate and compile it separately before accepting it.
    return response
