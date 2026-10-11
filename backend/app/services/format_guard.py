"""Whitespace-preservation guard for AI-improved Java source.

The AI regenerates the complete source of the file it improves.  While doing
so it occasionally re-indents or otherwise reformats lines that no finding
requires (observed in production: closing braces returned at 8-space
indentation instead of the original 4, producing new Checkstyle
IndentationCheck violations on the accepted version).

This module compares the AI output against the original source and reverts
any *whitespace-only* change to an existing line that is not justified by a
static-analysis finding for that line.  It is deliberately conservative:

  * Only ``replace`` blocks of equal length are inspected, so legitimate
    insertions (e.g. the blank lines an EmptyLineSeparatorCheck fix
    requires) pass through untouched.
  * A line is only reverted when its stripped content is identical to the
    original - real code changes are never touched.
  * A change is kept when an indentation-related finding was reported for
    that line (or the line directly after it), so genuine indentation fixes
    are not blocked.

This is line-level restoration of the developer's original bytes, not
regex-based reformatting of AI code.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class FormattingRestoration:
    """A whitespace-only AI change that was reverted to the original line."""

    line: int  # 1-based line number in the improved content
    original_line: str  # the developer's original text (restored)
    reverted_line: str  # the AI's unjustified whitespace variant


def indentation_finding_lines(
    findings: Sequence[dict], target_file: str
) -> set[int]:
    """Collect 1-based line numbers of indentation findings in *target_file*.

    A whitespace-only change on those lines is part of a legitimate fix and
    must not be reverted.
    """
    justified: set[int] = set()
    for f in findings:
        if f.get("file") != target_file:
            continue
        blob = f"{f.get('rule') or ''} {f.get('message') or ''}".lower()
        if "indentation" in blob and f.get("line"):
            try:
                justified.add(int(f["line"]))
            except (TypeError, ValueError):
                continue
    return justified


def preserve_unrelated_formatting(
    original: str,
    improved: str,
    justified_lines: Iterable[int] = (),
) -> Tuple[str, List[FormattingRestoration]]:
    """Revert unjustified whitespace-only changes in *improved*.

    Returns the cleaned content plus the list of restorations performed.
    When nothing needs restoring, the improved text is returned unchanged.
    """
    justified = set(justified_lines)
    original_lines = original.split("\n")
    improved_lines = improved.split("\n")

    cleaned = list(improved_lines)
    restorations: List[FormattingRestoration] = []

    matcher = difflib.SequenceMatcher(
        a=original_lines, b=improved_lines, autojunk=False
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        # Only equal-length replacements can be whitespace-only line swaps.
        if tag != "replace" or (i2 - i1) != (j2 - j1):
            continue
        for offset in range(i2 - i1):
            old = original_lines[i1 + offset]
            new = improved_lines[j1 + offset]
            if old == new or old.strip() != new.strip():
                # Identical, or a genuine code change - leave it alone.
                continue
            original_line_no = i1 + offset + 1
            # An indentation finding on this line or the next justifies the
            # change (closing braces are sometimes reported one line off
            # after blank-line insertions).
            if any((original_line_no + slack) in justified for slack in (0, 1)):
                continue
            cleaned[j1 + offset] = old
            restorations.append(
                FormattingRestoration(
                    line=j1 + offset + 1,
                    original_line=old,
                    reverted_line=new,
                )
            )

    if not restorations:
        return improved, []
    return "\n".join(cleaned), restorations


def restoration_notes(restorations: Sequence[FormattingRestoration]) -> List[str]:
    """Human-readable notes for restorations, shown on the proposal."""
    notes = []
    for r in restorations:
        old_label = r.original_line.strip() or "<blank>"
        new_label = r.reverted_line.strip() or "<blank>"
        notes.append(
            f"Line {r.line}: reverted unjustified whitespace change "
            f"({new_label!r} -> restored original {old_label!r})."
        )
    return notes
