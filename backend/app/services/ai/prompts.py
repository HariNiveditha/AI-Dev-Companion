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
- Use proper Java formatting with newlines between statements, imports, and class declarations.
- Each statement must be on its own line.
- Imports must be separated by newlines.
- Class and method declarations must be on separate lines.

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


def get_code_improvement_prompt(
    title: str,
    description: str,
    source_code: str,
    findings: list[dict],
) -> str:
    import json

    findings_json = json.dumps(findings, indent=2)

    return f"""You are an expert Java software engineer specializing in code quality and security.
You are given a Java source file, the software requirement it implements, and a list of static analysis findings from Checkstyle, SpotBugs, and Semgrep.

Your task is to propose targeted improvements to the source code that address the actionable findings while preserving the original intended behavior.

## Rules:
- Preserve the original package declaration, imports, class names, and public method signatures.
- Do not introduce unrelated refactoring or new features.
- Do not change the intended behavior of the code.
- If a finding is a false positive or does not require a code change, list it under non_actionable_findings with a brief explanation.
- Only make changes that are directly supported by the findings.
- The improved code must be complete and compilable.
- Do not add comments unless they clarify a non-obvious fix.
- Return only structured JSON matching this schema.

## Response Schema:
{{
    "improved_content": "complete improved Java source code",
    "explanation": "explanation of the changes made and why they address the findings",
    "findings_addressed": ["brief description of each finding that was addressed"],
    "non_actionable_findings": ["brief description of each finding that does not require a code change"]
}}

## Software Requirement:
Title: {title}
Description: {description}

## Original Java Source Code:
{source_code}

## Static Analysis Findings:
{findings_json}
"""
