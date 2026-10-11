"""Unit tests for the whitespace-preservation format guard.

Production incident being guarded: the AI fixed two EmptyLineSeparatorCheck
findings in User.java but returned the closing braces of getUsername() and
getEmail() at 8-space indentation instead of the original 4.  The proposal
was accepted, and Checkstyle then reported two new IndentationCheck
violations on the new version.  The guard must revert whitespace-only
changes that no indentation finding justifies, while never touching blank
line insertions or genuine fixes.
"""

from app.services.format_guard import (
    indentation_finding_lines,
    preserve_unrelated_formatting,
    restoration_notes,
)

V1 = (
    "package com.auth.model;\n"
    "\n"
    "public class User {\n"
    "    private String username;\n"
    "    private String email;\n"
    "\n"
    "    public String getUsername() {\n"
    "        return username;\n"
    "    }\n"
    "\n"
    "    public String getEmail() {\n"
    "        return email;\n"
    "    }\n"
    "}\n"
)

# Exactly what the model returned for the accepted proposal: correct blank
# line inserted, but getUsername/getEmail closing braces re-indented to 8.
BAD_FIX = (
    "package com.auth.model;\n"
    "\n"
    "public class User {\n"
    "    private String username;\n"
    "\n"
    "    private String email;\n"
    "\n"
    "    public String getUsername() {\n"
    "        return username;\n"
    "        }\n"
    "\n"
    "    public String getEmail() {\n"
    "        return email;\n"
    "        }\n"
    "}\n"
)

EMPTY_LINE_FINDINGS = [
    {
        "finding_id": "F1",
        "tool": "Checkstyle",
        "severity": "ERROR",
        "file": "User.java",
        "line": 5,
        "column": 5,
        "rule": "com.puppycrawl.tools.checkstyle.checks.whitespace.EmptyLineSeparatorCheck",
        "message": "'VARIABLE_DEF' should be separated from previous line.",
    }
]

INDENTATION_FINDINGS = [
    {
        "finding_id": "F1",
        "tool": "Checkstyle",
        "severity": "ERROR",
        "file": "User.java",
        "line": 10,
        "column": 9,
        "rule": "com.puppycrawl.tools.checkstyle.checks.indentation.IndentationCheck",
        "message": "'method def rcurly' has incorrect indentation level 8, expected level should be 4.",
    },
    {
        "finding_id": "F2",
        "tool": "Checkstyle",
        "severity": "ERROR",
        "file": "User.java",
        "line": 14,
        "column": 9,
        "rule": "com.puppycrawl.tools.checkstyle.checks.indentation.IndentationCheck",
        "message": "'method def rcurly' has incorrect indentation level 8, expected level should be 4.",
    },
]


def test_reindent_regression_is_reverted_and_fix_preserved():
    """The production regression: re-indented braces are restored, the
    blank-line fix that addressed the findings is kept."""
    cleaned, restorations = preserve_unrelated_formatting(V1, BAD_FIX)

    # The unjustified 8-space braces are back to the original 4 spaces.
    assert "        return username;\n    }\n" in cleaned
    assert "        return email;\n    }\n" in cleaned
    assert "        }\n" not in cleaned
    # The legitimate blank-line insertions survive.
    assert "    private String username;\n\n    private String email;\n" in cleaned
    # Two restorations, one per over-indented brace (lines 10 and 14 of
    # the improved content).
    assert len(restorations) == 2
    assert [r.line for r in restorations] == [10, 14]
    notes = restoration_notes(restorations)
    assert len(notes) == 2
    assert "Line 10" in notes[0] and "Line 14" in notes[1]


def test_indentation_finding_justifies_whitespace_change():
    """When an IndentationCheck finding covers the line, the whitespace
    change is the fix itself and must NOT be reverted."""
    # v2-style source with the bad braces is the ORIGINAL here; the AI
    # corrects them to 4 spaces.  That correction is a whitespace-only
    # change justified by the findings.
    improved = BAD_FIX.replace("        }\n", "    }\n")
    justified = indentation_finding_lines(INDENTATION_FINDINGS, "User.java")
    assert justified == {10, 14}

    cleaned, restorations = preserve_unrelated_formatting(BAD_FIX, improved, justified)
    assert cleaned == improved
    assert restorations == []


def test_indentation_findings_only_justify_their_own_file():
    findings = [dict(INDENTATION_FINDINGS[0], file="Other.java")]
    assert indentation_finding_lines(findings, "User.java") == set()


def test_genuine_code_changes_are_never_touched():
    """Non-whitespace changes pass through even on unjustified lines."""
    changed = V1.replace("return username;", "return username.trim();")
    cleaned, restorations = preserve_unrelated_formatting(V1, changed)
    assert cleaned == changed
    assert restorations == []


def test_insertions_and_deletions_pass_through():
    """Blank-line insertion (the legitimate fix) is not a whitespace-only
    replacement, so it is never inspected."""
    cleaned, restorations = preserve_unrelated_formatting(V1, BAD_FIX, justified_lines={10, 14})
    # With both braces justified, everything the AI did is kept.
    assert cleaned == BAD_FIX
    assert restorations == []


def test_identical_content_returns_unchanged():
    cleaned, restorations = preserve_unrelated_formatting(V1, V1)
    assert cleaned == V1
    assert restorations == []
