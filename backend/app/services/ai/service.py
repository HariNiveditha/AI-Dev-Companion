from app.models.requirement import RequirementAnalysis
from .provider import AIProvider
from .prompts import get_requirement_analysis_prompt
from app.models.code_artifact import GeneratedCodeResponse
from .prompts import get_code_generation_prompt

def analyze_requirement_text(title: str, description: str) -> RequirementAnalysis:
    provider = AIProvider()
    prompt = get_requirement_analysis_prompt(title, description)
    analysis_result = provider.analyze_requirement(prompt, RequirementAnalysis)
    return analysis_result

def generate_java_code(
    title: str, description: str, analysis: RequirementAnalysis
) -> GeneratedCodeResponse:
    prompt = get_code_generation_prompt(title, description, analysis.model_dump())
    provider = AIProvider()
    return provider.generate_code(prompt, GeneratedCodeResponse)
