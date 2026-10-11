"""Java source-code structural validation for AI-generated output.

This module detects obviously malformed Java source before it is
persisted as an artifact.  It does NOT attempt to auto-fix code.

Detection targets:
  * Single-line output (Gemini structured-JSON newline collapse)
  * Unbalanced braces / parentheses
  * Missing ``import`` keyword before a package path
  * Missing ``class`` / ``interface`` / ``enum`` / ``record`` declaration
  * Markdown code fences left inside the content
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:  # allow ``if result:`` shorthand
        return self.ok


def _strip_java_comments(source: str) -> str:
    """Return *source* with line and block comments replaced by spaces.

    This keeps character offsets intact so brace counting stays accurate
    even when braces appear inside comments.
    """
    # Remove block comments /* ... */
    without_block = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group()), source, flags=re.DOTALL)

    # Remove line comments // ...
    without_line = re.sub(
        r"//[^\n]*",
        lambda m: " " * len(m.group()),
        without_block,
    )
    return without_line


def _strip_string_literals(source: str) -> str:
    """Replace the contents of string and character literals with spaces.

    This prevents braces, semicolons, etc. inside string literals from
    affecting structural validation.
    """
    result = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        # Character literal
        if ch == "'":
            result.append("'")
            i += 1
            while i < n and source[i] != "'":
                if source[i] == "\\":
                    result.append(source[i])
                    i += 1
                    if i < n:
                        result.append(source[i])
                        i += 1
                else:
                    i += 1
            if i < n:
                result.append("'")
                i += 1
        # String literal
        elif ch == '"':
            result.append('"')
            i += 1
            while i < n and source[i] != '"':
                if source[i] == "\\":
                    result.append(source[i])
                    i += 1
                    if i < n:
                        result.append(source[i])
                        i += 1
                else:
                    i += 1
            if i < n:
                result.append('"')
                i += 1
        else:
            result.append(ch)
            i += 1
    return "".join(result)


def validate_java_source(source: str) -> ValidationResult:
    """Validate that *source* looks like structurally complete Java.

    Returns a :class:`ValidationResult` whose ``errors`` list contains a
    human-readable description of every structural problem detected.
    """
    errors: List[str] = []

    if not source or not source.strip():
        return ValidationResult(ok=False, errors=["Source code is empty."])

    # --- markdown fences ---
    if source.strip().startswith("```") or "```" in source:
        errors.append("Source contains Markdown code fences.")

    # --- newlines ---
    if "\n" not in source:
        errors.append(
            "Source has no newline characters — the entire file appears on one line."
        )

    # --- structural analysis on comment/string-stripped copy ---
    structural = _strip_string_literals(_strip_java_comments(source))

    # --- balanced braces ---
    depth = 0
    for ch in structural:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    if depth > 0:
        errors.append(f"Unbalanced braces: {depth} closing brace(s) missing.")
    elif depth < 0:
        errors.append("Unbalanced braces: too many closing braces.")

    # --- balanced parentheses ---
    depth = 0
    for ch in structural:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
    if depth > 0:
        errors.append(f"Unbalanced parentheses: {depth} closing parenthesis missing.")
    elif depth < 0:
        errors.append("Unbalanced parentheses: too many closing parentheses.")

    # --- class/interface/enum/record declaration ---
    if not re.search(
        r"\b(class|interface|enum|record)\s+\w+", structural
    ):
        errors.append("No class, interface, enum, or record declaration found.")

    # --- missing `import` keyword before a package-style path ---
    # Looks for lines whose first token starts with a lowercase package
    # segment followed by a dot, but does NOT begin with a keyword like
    # `package`, `import`, `return`, `throw`, etc.
    keyword_prefix = re.compile(
        r"^\s*(package|import|public|private|protected|static|final|class|"
        r"interface|enum|record|return|throw|new|if|else|for|while|do|try|"
        r"catch|finally|switch|case|break|continue|extends|implements|"
        r"this|super|void|int|long|double|float|boolean|char|byte|short|"
        r"String|List|Map|Set|var|assert|synchronized|transient|volatile|"
        r"native|abstract|default|sealed|permits|non-sealed)",
    )
    for line in structural.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Check if the line looks like a bare package path (e.g. `java.util.Base64;`)
        if re.match(r"^[a-z][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+;?\s*$", stripped):
            if not keyword_prefix.match(stripped):
                errors.append(
                    f'Malformed import — found `{stripped.rstrip(";")};` '
                    f'without the `import` keyword.'
                )

    return ValidationResult(ok=len(errors) == 0, errors=errors)
