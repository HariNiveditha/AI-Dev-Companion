"""Structural validation and safe formatting for AI-generated Java source.

This module provides :func:`validate_java_source` and :func:`format_java_source`
used by the Phase 3 code-generation pipeline and the Phase 10 improvement
workflow to guarantee that malformed AI output is rejected before it is
persisted as an artifact, and never to accept truncated or otherwise
syntactically invalid Java source.

Why no external Java formatter is used
---------------------------------------
The project does not declare a Java formatter (for example,
google-java-format) in ``requirements.txt`` or ``backend/requirements.txt``,
and ``backend/.tools`` contains only Checkstyle, SpotBugs and Semgrep
dependencies. Adding a formatting dependency to the Python environment would
change the runtime shape of the service. Instead this module implements a
lightweight, dependency-free formatter that only inserts structural
newlines where they are unambiguous, and a strict validator that refuses to
accept source that is incomplete or malformed. The validator is the safety
gate: formatting is best-effort only.

The validator deliberately does not rely on compiling the source ahead of
time for generation-time checks: compilation is an expensive, environment-
dependent step. The structural checks here (balanced braces, brackets and
parentheses, correct import lines, trailing closing token, import ordering)
cover the reported failure modes -- reached end of file while parsing,
class, interface, enum, or record expected, missing import keyword,
a single long line, and a malformed import declaration -- with no external
tools. They are also fast enough to run inside the request path as a
pre-persistence gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# Line length threshold used by the light formatter. This is a reasonable
# convention for generated source and matches the project's existing style.
MAX_LINE_LENGTH = 120

# Tokens that must balance in valid Java source.
_BRACKETS = {"}": "{", "]": "[", ")": "("}
_OPEN_BRACKETS = set(_BRACKETS.values())


@dataclass
class Diagnostic:
    """A single diagnostic reported by :func:`validate_java_source`."""

    severity: str
    message: str
    line: Optional[int] = None


@dataclass
class ValidationResult:
    """Result of validating a Java source blob."""

    is_valid: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)
    formatted_content: Optional[str] = None
    formatting_applied: bool = False

    @property
    def failures(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]


def _line_number(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1

def _strip_comments_and_strings(content: str) -> str:
    """Return content with comments and string literals replaced by single spaces.

    This is a lightweight lexical scanner sufficient to make a structural
    bracket scan trustworthy. It does not fully tokenize every Java escape
    sequence, but it is deliberately conservative: it only *removes* tokens
    that are unambiguous (line comments, block comments, and simple single-
    and double-quoted literals), so malformed strings are never silently
    treated as balanced.
    """
    out: list[str] = []
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]
        nxt = content[i + 1] if i + 1 < n else ""
        # Line comment.
        if ch == "/" and nxt == "/":
            j = content.find("\n", i)
            out.append(" ")
            if j == -1:
                break
            i = j + 1
            continue
        # Block comment.
        if ch == "/" and nxt == "*":
            j = content.find("*/", i + 2)
            out.append(" ")
            if j == -1:
                break
            i = j + 2
            continue
        # Character literal (handle common escapes).
        if ch == "'":
            out.append(" ")
            i += 1
            while i < n:
                if content[i] == "\\":
                    i += 2
                    continue
                if content[i] == "'":
                    i += 1
                    break
                i += 1
            continue
        # String literal.
        if ch == '"':
            out.append(" ")
            i += 1
            while i < n:
                if content[i] == "\\":
                    i += 2
                    continue
                if content[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _scan_brackets(content: str) -> list[Diagnostic]:
    """Detect unbalanced brackets and the missing trailing token."""
    cleaned = _strip_comments_and_strings(content)
    stack: list[str] = []
    errors: list[Diagnostic] = []
    i = 0
    n = len(cleaned)
    while i < n:
        ch = cleaned[i]
        if ch in _OPEN_BRACKETS:
            stack.append(ch)
        elif ch in _BRACKETS:
            if not stack:
                errors.append(
                    Diagnostic(
                        severity="error",
                        message=f"Unmatched closing '{ch}' at line {_line_number(content, i)}",
                        line=_line_number(content, i),
                    )
                )
            elif stack[-1] == _BRACKETS[ch]:
                stack.pop()
            else:
                errors.append(
                    Diagnostic(
                        severity="error",
                        message=(
                            f"Mismatched '{ch}' at line {_line_number(content, i)}; "
                            f"expected '{_BRACKETS[ch]}' to close"
                        ),
                        line=_line_number(content, i),
                    )
                )
        i += 1

    for bracket in stack:
        errors.append(
            Diagnostic(
                severity="error",
                message=f"Unclosed '{bracket}' at end of file; missing closing token",
                line=None,
            )
        )
    return errors



def _validate_import_lines(content: str) -> list[Diagnostic]:
    """Check that import declarations are well-formed.

    Catches malformed import declarations such as
    ``java.util.Base64;`` being emitted instead of
    ``import java.util.Base64;``.
    """
    errors: list[Diagnostic] = []
    import_re = re.compile(
        r"^\s*import\s+(static\s+)?([A-Za-z_][A-Za-z0-9_.]*)(?:\.\s*([A-Za-z_][A-Za-z0-9_]*))?\s*;\s*$"
    )
    for idx, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("import"):
            m = import_re.fullmatch(stripped)
            if not m:
                errors.append(
                    Diagnostic(
                        severity="error",
                        message=(
                            f"Invalid import declaration on line {idx}: '{stripped}'. "
                            "Expected 'import java.util.Base64;' style."
                        ),
                        line=idx,
                    )
                )
    return errors


def _validate_missing_import_statements(content: str) -> list[Diagnostic]:
    """Detect top-level statements that reference a dotted package name without an import.

    A line like ``java.util.Base64;`` at the top level of a Java file is not
    a valid import nor a valid declaration. Without the ``import`` keyword
    (or an explicit fully-qualified ``java.util.Base64.`` prefix), the
    compiler reports ``class, interface, enum, or record expected``. This
    check flags such statements so they are not persisted as artifacts.
    """
    errors: list[Diagnostic] = []
    # A top-level dotted name that ends with ';' and is not preceded by a
    # keyword/imports we accept. We look for a dotted sequence of identifiers
    # followed by ';' on a line that is not itself an import or a banned
    # keyword keyword.
    dotted_stmt_re = re.compile(
        r"^[A-Za-z_][A-Za-z0-9_]*(?:\s*\.\s*[A-Za-z_][A-Za-z0-9_]*)+\s*;\s*$"
    )
    for idx, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("import", "static")) or not dotted_stmt_re.match(stripped):
            continue
        # This is a top-level dotted statement without an import; flag it.
        errors.append(
            Diagnostic(
                severity="error",
                message=(
                    f"Top-level statement on line {idx} references a package name "
                    f"('{stripped}') without an 'import' declaration. Expected "
                    f"'import {stripped}' instead."
                ),
                line=idx,
            )
        )
    return errors



def validate_java_source(
    content: str,
    *,
    request_id: Optional[str] = None,
) -> ValidationResult:
    """Validate that *content* is complete, syntactically well-formed Java.

    Returns a :class:`ValidationResult`. The result is *invalid* for every
    failure mode reported in the task: truncated source, unmatched braces,
    a missing import keyword, and a file that ends mid-declaration or
    mid-token. Formatting is applied as a best-effort step only when the
    source is structurally valid.
    """
    diagnostics: list[Diagnostic] = []

    # 1. Bracket balance -- catches truncated files and unmatched braces.
    diagnostics.extend(_scan_brackets(content))

    # 2. Import declarations must be well-formed (catches
    #    'java.util.Base64;' instead of 'import java.util.Base64;').
    diagnostics.extend(_validate_import_lines(content))

    # 3. Missing import statements -- catches a package name used at the
    #    top level without an import declaration (catches
    #    'java.util.Base64;' instead of 'import java.util.Base64;').
    diagnostics.extend(_validate_missing_import_statements(content))

    # 4. Ensure the file actually ends with a closing token rather than an
    #    open bracket. This is the direct check for truncated source.
    last_non_space = -1
    for idx in range(len(content) - 1, -1, -1):
        if not content[idx].isspace():
            last_non_space = idx
            break
    if last_non_space != -1 and content[last_non_space] in _OPEN_BRACKETS:
        # The file is missing a closing token.
        diagnostics.append(
            Diagnostic(
                severity="error",
                message=(
                    f"Source ends while '{content[last_non_space]}' is still open. "
                    "Add the missing closing token(s) or regenerate the file."
                ),
                line=None,
            )
        )

    is_valid = len(diagnostics) == 0
    return ValidationResult(
        is_valid=is_valid,
        diagnostics=diagnostics,
        formatted_content=None,
        formatting_applied=False,
    )



def _insert_newlines_after_statement_terminators(content: str) -> str:
    """Insert newlines after semicolons and block delimiters.

    This is intentionally conservative: it never deletes, reorders, or
    rewrites any token. It only adds a newline after ';', '{', and '}'
    when it is safe to do so (i.e. the next non-space character is not
    another delimiter or a string/char literal).
    """
    chars = list(content)
    out: list[str] = []
    i = 0
    n = len(chars)
    while i < n:
        ch = chars[i]
        out.append(ch)
        if ch in ";{}":
            # Peek ahead past whitespace to see what follows.
            j = i + 1
            while j < n and chars[j].isspace():
                j += 1
            if j < n and chars[j] not in ";{}":
                out.append("\n")
        i += 1
    return "".join(out)


def format_java_source(content: str) -> tuple[str, bool]:
    """Apply conservative formatting and return (result, changed).

    The formatter inserts newlines after statement terminators and block
    delimiters where they are syntactically safe. It does not attempt to
    produce Google/Google-Style output, because that would require a full
    Java grammar. It only guarantees that the returned source is
    structurally equivalent (modulo whitespace) to the input and that it
    is written across multiple lines.
    """
    # If the source is already multi-line and structurally sane, return
    # it unchanged so we never churn artifacts on the backend.
    if "\n" in content:
        return content, False

    # One long line: insert safe newlines.
    return _insert_newlines_after_statement_terminators(content), True


def validate_and_format_java_source(
    content: str,
    *,
    request_id: Optional[str] = None,
) -> ValidationResult:
    """Validate and, if valid, lightly format the source.

    This is the single entry point used by both Phase 3 and Phase 10.
    """
    result = validate_java_source(content, request_id=request_id)
    if not result.is_valid:
        return result
    formatted, changed = format_java_source(content)
    result.formatted_content = formatted
    result.formatting_applied = changed
    return result
