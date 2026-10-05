from app.models.requirement import RequirementAnalysis
from .provider import AIProvider
from .prompts import get_requirement_analysis_prompt

def analyze_requirement_text(title: str, description: str) -> RequirementAnalysis:
    provider = AIProvider()
    prompt = get_requirement_analysis_prompt(title, description)
    analysis_result = provider.analyze_requirement(prompt, RequirementAnalysis)
    return analysis_result
