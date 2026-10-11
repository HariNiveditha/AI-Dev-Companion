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

CRITICAL FORMATTING REQUIREMENTS — violating any of these will produce invalid output:
- Every file's content MUST contain real newline characters (\\n in JSON) between statements, imports, and declarations. Do NOT return the entire file on a single line.
- Every import statement must include the literal word "import", e.g. "import java.util.Base64;" — never just "java.util.Base64;".
- Every opening brace must have a matching closing brace. The file must end with all braces closed.
- Every file must contain a class, interface, enum, or record declaration.
- Do not leave Markdown code fences (```) inside the content string.

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
    source_files: dict[str, str],
    findings: list[dict],
    target_file: str,
) -> str:
    import json

    findings_json = json.dumps(findings, indent=2)

    # Render every analyzed file so the model can see the exact code each
    # finding refers to.  Findings routinely land in files other than the one
    # the user selected, so the model must be able to fix the file where the
    # finding actually lives.
    rendered_files = []
    for file_name, content in source_files.items():
        marker = "  <<< currently selected by the user" if file_name == target_file else ""
        rendered_files.append(
            f"### File: {file_name}{marker}\n```java\n{content}\n```"
        )
    files_block = "\n\n".join(rendered_files)

    return f"""You are an expert Java software engineer specializing in code quality and security.
You are given the Java source files of a small project, the software requirement they implement, and a list of static analysis findings from Checkstyle, SpotBugs, and Semgrep.

## Your task
1. Evaluate EVERY finding listed in "Static Analysis Findings" individually, against the exact source shown above.
2. Classify each finding as exactly one of:
   - ACTIONABLE: a concrete, safe code change in the file the finding names can resolve it.
   - NON_ACTIONABLE: a false positive, or the finding is correct but needs no code change.
   - NEEDS_CONTEXT: you cannot decide safely from the source provided.
3. For each ACTIONABLE finding, apply the smallest fix in the file the finding names, and record its finding_id in addressed_finding_ids.
4. Choose target_file to be the single file where you made the most substantive fix (the file that contained the actionable findings). Write that file's COMPLETE improved source in improved_content. Do not modify any other file.
5. Report findings you did not fix honestly under non_actionable_findings with a reason. Do NOT claim a finding is fixed unless your change actually resolves it.

IMPORTANT: A finding may name a DIFFERENT file than the user's selected file. You must still fix it, in the file the finding names, and set target_file to that file. Do not modify a file merely because it is selected if its violations are elsewhere.

## Rules
- Preserve the original package declaration, imports, class names, and public method signatures of the file you improve.
- Preserve the exact indentation and whitespace of every line you do not need to change. Do NOT re-indent, re-align, or reformat any line as a side effect of your fix - closing braces must keep their original indentation. Unrelated whitespace changes will be rejected.
- Do not introduce unrelated refactoring or new features.
- Do not change the intended behavior of the code.
- Do not suppress warnings, delete findings, or weaken checks.
- Only make changes directly supported by a finding.
- Every finding_id you were given MUST appear exactly once in finding_assessments.
- The improved code must be complete and compilable.

## Special guidance
- A Checkstyle "should be separated from previous line" (EmptyLineSeparatorCheck) finding is an actionable formatting fix: insert the required blank line at the named file/line. Insert blank lines only - do not touch any other line.
- A Checkstyle IndentationCheck finding IS a whitespace fix: change only the indentation of the exact offending line(s) to the expected level reported by the finding, and change nothing else in the file.
- A SpotBugs THROWS_METHOD_THROWS_RUNTIMEEXCEPTION finding is usually NON_ACTIONABLE or NEEDS_CONTEXT: rethrowing as RuntimeException is often deliberate. Only change it if doing so cannot break callers or alter behavior; otherwise explain why you left it.

## CRITICAL FORMATTING REQUIREMENTS — violating any of these produces invalid output
- improved_content MUST contain real newline characters (\\n in JSON) between statements, imports, and declarations. Do NOT return the file on a single line.
- Every import statement must include the literal word "import", e.g. "import java.util.Base64;".
- Every opening brace must have a matching closing brace. The file must end with all braces closed.
- Do not leave Markdown code fences (```) inside improved_content.

## Response Schema:
{{
    "improved_content": "complete improved source of the file named in target_file",
    "target_file": "the exact file_name you improved, e.g. \\"User.java\\"",
    "explanation": "what changed and which finding_ids each change addresses",
    "findings_addressed": ["short human-readable description of each addressed finding"],
    "addressed_finding_ids": ["F1", "F3"],
    "finding_assessments": [
        {{"finding_id": "F1", "classification": "ACTIONABLE", "reasoning": "why"}},
        {{"finding_id": "F2", "classification": "NEEDS_CONTEXT", "reasoning": "why"}}
    ],
    "non_actionable_findings": ["short description + reason for each finding not fixed"]
}}

## Software Requirement:
Title: {title}
Description: {description}

## User's selected file (informational only): {target_file}

## Project Source Files:
{files_block}

## Static Analysis Findings:
{findings_json}
"""
