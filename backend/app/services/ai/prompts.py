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


def get_test_case_generation_prompt(title: str, description: str, analysis: dict) -> str:
    import json

    return f"""You are an expert QA engineer and software test designer.
Generate multiple high-quality software test cases for the confirmed requirement below.

Return only structured JSON in this exact shape:
{{
  "test_cases": [
    {{
      "title": "Test case title",
      "description": "What this test verifies",
      "input": "Example input or scenario",
      "expected_output": "Expected result",
      "priority": "HIGH",
      "type": "FUNCTIONAL"
    }}
  ]
}}

Rules:
- Generate 5 to 8 relevant test cases.
- Use realistic values for priority: HIGH, MEDIUM, or LOW.
- Use realistic values for type: FUNCTIONAL, NEGATIVE, EDGE_CASE, SECURITY, or VALIDATION.
- Include a mix of normal, boundary, validation, and failure scenarios when appropriate.
- Do not include markdown fences, explanations, or additional fields.
- Do not include comments.
- Ensure each test case is meaningful and aligned to the requirement.
- The JSON must be valid and parseable.

Confirmed Requirement Title: {title}
Confirmed Requirement Description: {description}
Requirement Analysis:
{json.dumps(analysis, indent=2)}
"""
