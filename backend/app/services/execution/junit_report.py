"""Parsing and validation of the JUnit XML reports produced by the runner.

The structured XML report — never console text — is the single source of truth
for pass/fail/skip/error counts.  The parser validates the report before any
count is accepted:

* every report file must be well-formed XML with a ``<testsuite>`` root (or a
  ``<testsuites>`` wrapper containing suites);
* every ``<testcase>`` must carry a ``name``;
* if a suite declares ``tests=``/``failures=``/``errors=``/``skipped=``
  attributes, they must agree with the elements actually present.

Anything else raises :class:`ReportMissingError` / :class:`ReportMalformedError`
and the execution is recorded as ERROR rather than guessed at.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional


class ReportMissingError(Exception):
    """The runner produced no XML report at all."""


class ReportMalformedError(Exception):
    """The runner produced a report that failed structural validation."""


RawStatus = Literal["PASSED", "FAILED", "ERROR", "SKIPPED"]


@dataclass
class ParsedTestCase:
    """One ``<testcase>`` element from the report."""

    name: str
    classname: str
    status: RawStatus
    duration_ms: Optional[int] = None
    message: Optional[str] = None
    stacktrace: Optional[str] = None


@dataclass
class ParsedReport:
    testcases: list[ParsedTestCase] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.testcases)

    def count(self, status: RawStatus) -> int:
        return sum(1 for case in self.testcases if case.status == status)


def _parse_duration_ms(time_attr: Optional[str]) -> Optional[int]:
    if time_attr is None:
        return None
    try:
        return max(0, round(float(time_attr) * 1000))
    except ValueError:
        return None


def normalize_method_name(raw_name: str) -> str:
    """Strip JUnit's method-signature suffix for method_map matching.

    The console launcher reports ``name=\"acceptsValidLogin()\"`` (and
    ``name=\"cases(int)[1]\"`` for parameterized invocations) while
    ``method_map`` stores bare declared method names.  Only the part
    before the first ``(`` is used for matching; the raw name is kept
    verbatim on the parsed record.
    """
    base = raw_name.split("(", 1)[0].strip()
    return base or raw_name


def _classify(testcase: ET.Element) -> tuple[RawStatus, Optional[str], Optional[str]]:
    """Derive status from child elements: failure > error > skipped > passed."""
    failure = testcase.find("failure")
    if failure is not None:
        return "FAILED", failure.attrib.get("message"), (failure.text or "") or None
    error = testcase.find("error")
    if error is not None:
        return "ERROR", error.attrib.get("message"), (error.text or "") or None
    skipped = testcase.find("skipped")
    if skipped is not None:
        return "SKIPPED", skipped.attrib.get("message"), None
    return "PASSED", None, None


def _parse_suite(suite: ET.Element, parsed: ParsedReport, source: str) -> None:
    cases = suite.findall("testcase")
    if len(cases) == 0 and suite.tag == "testsuite" and not list(suite):
        # A genuinely empty suite file is tolerated only if attributes agree.
        pass

    # Validate declared counters against the elements actually present.
    derived: dict[str, int] = {"failures": 0, "errors": 0, "skipped": 0}
    for case in cases:
        status, _, _ = _classify(case)
        if status == "FAILED":
            derived["failures"] += 1
        elif status == "ERROR":
            derived["errors"] += 1
        elif status == "SKIPPED":
            derived["skipped"] += 1

    if "tests" in suite.attrib:
        try:
            declared = int(suite.attrib["tests"])
        except ValueError:
            raise ReportMalformedError(
                f"{source}: tests attribute is not an integer: {suite.attrib['tests']!r}"
            )
        if declared != len(cases):
            raise ReportMalformedError(
                f"{source}: suite declares tests={declared} but contains "
                f"{len(cases)} <testcase> elements"
            )
    for attr in ("failures", "errors", "skipped"):
        if attr in suite.attrib:
            try:
                declared = int(suite.attrib[attr])
            except ValueError:
                raise ReportMalformedError(
                    f"{source}: {attr} attribute is not an integer: {suite.attrib[attr]!r}"
                )
            if declared != derived[attr]:
                raise ReportMalformedError(
                    f"{source}: suite declares {attr}={declared} but contains "
                    f"{derived[attr]} matching <testcase> elements"
                )

    for case in cases:
        name = case.attrib.get("name")
        if not name:
            raise ReportMalformedError(f"{source}: a <testcase> has no name attribute")
        status, message, stacktrace = _classify(case)
        parsed.testcases.append(
            ParsedTestCase(
                name=name,
                classname=case.attrib.get("classname", ""),
                status=status,
                duration_ms=_parse_duration_ms(case.attrib.get("time")),
                message=message,
                stacktrace=stacktrace,
            )
        )


def parse_report_file(path: Path, parsed: ParsedReport) -> None:
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise ReportMalformedError(f"{path.name}: not well-formed XML ({exc})") from exc
    root = tree.getroot()

    if root.tag == "testsuites":
        suites = root.findall("testsuite")
        if not suites:
            raise ReportMalformedError(f"{path.name}: <testsuites> contains no <testsuite>")
    elif root.tag == "testsuite":
        suites = [root]
    else:
        raise ReportMalformedError(
            f"{path.name}: unexpected root element <{root.tag}> (expected testsuite/testsuites)"
        )

    for suite in suites:
        _parse_suite(suite, parsed, path.name)


def parse_reports(reports_dir: Path) -> ParsedReport:
    """Parse every ``*.xml`` report in *reports_dir* and validate it.

    Raises :class:`ReportMissingError` when no report file exists and
    :class:`ReportMalformedError` when a report fails validation.
    """
    reports_dir = Path(reports_dir)
    files = sorted(reports_dir.glob("*.xml")) if reports_dir.exists() else []
    if not files:
        raise ReportMissingError(
            f"runner produced no XML report in {reports_dir.name}/ "
            "(no tests discovered, or the runner failed before reporting)"
        )

    parsed = ParsedReport(files=[f.name for f in files])
    for path in files:
        parse_report_file(path, parsed)

    if not parsed.testcases:
        raise ReportMissingError(
            "runner report exists but contains no <testcase> entries "
            f"(files: {', '.join(parsed.files)})"
        )
    return parsed
