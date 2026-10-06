def get_requirement_analysis_prompt(title: str, description: str) -> str:
    return f"""You are an expert Software Architect and Business Analyst.
You are analyzing a software requirement to extract structured information.

DO NOT generate source code.
You must identify:
- functional requirements (what the system should do)
- non-functional requirements (performance, security, usability, etc.)
- assumptions (things not explicitly stated but necessary)
- ambiguities (unclear points that need clarification)
- edge cases (unusual or extreme situations)
- acceptance criteria (measurable conditions for success)

Do not invent requirements that are not reasonably supported.
If something is unclear, place it under ambiguities or assumptions.

Requirement Title: {title}
Requirement Description: {description}
"""


def get_code_generation_prompt(
        title: str, description: str, analysis: dict
) -> str:
        import json

        return f"""You are an expert Java software engineer.
Generate Java source code for the confirmed software requirement below.

Use the confirmed requirement as the primary source of truth and the AI
requirement analysis as supporting context. Generate only functionality
supported by the requirement. Do not invent unrelated functionality.

Return only structured JSON matching this schema:
{{
    "files": [
        {{
            "file_name": "Example.java",
            "language": "Java",
            "content": "complete Java source code"
        }}
    ]
}}

Rules:
- Generate Java source code only.
- Do not generate tests, documentation, CI/CD configuration, or build files.
- Do not claim that the code has been compiled or tested.
- Return one or more complete Java source files.
- Every file_name must be a simple Java filename ending in .java, with no path.

Confirmed Requirement Title: {title}
Confirmed Requirement Description: {description}
Confirmed Requirement Analysis:
{json.dumps(analysis, indent=2)}
"""
