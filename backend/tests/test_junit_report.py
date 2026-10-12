"""Tests for the JUnit XML report parser (Phase 9).

The parser is the only source of pass/fail/skip/error counts, so its
validation behavior is tested directly: well-formed reports are
parsed, and malformed or missing reports raise instead of producing
guessed-at numbers.
"""

from pathlib import Path

import pytest

from app.services.execution.junit_report import (
    ReportMalformedError,
    ReportMissingError,
    normalize_method_name,
    parse_reports,
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    target = reports / name
    target.write_text(content, encoding="utf-8")
    return reports


VALID_SUITE = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="UserServiceTest" tests="3" failures="1" errors="0" skipped="1" time="0.42">
  <testcase name="acceptsValidLogin" classname="UserServiceTest" time="0.01"/>
  <testcase name="rejectsWrongPassword" classname="UserServiceTest" time="0.02">
    <failure message="expected [false]" type="AssertionFailedError">java.lang.AssertionError: expected [false]</failure>
  </testcase>
  <testcase name="skippedCase" classname="UserServiceTest" time="0">
    <skipped message="not implemented yet"/>
  </testcase>
</testsuite>
"""


def test_normalize_method_name_strips_signature_suffix():
    # The real JUnit console launcher reports "name='foo()'".
    assert normalize_method_name("acceptsValidLogin()") == "acceptsValidLogin"
    assert normalize_method_name("cases(int)[1]") == "cases"
    assert normalize_method_name("plainName") == "plainName"


def test_parse_report_keeps_raw_name_verbatim(tmp_path):
    reports = _write(tmp_path, "TEST-junit-jupiter.xml", VALID_SUITE)

    report = parse_reports(reports)

    assert report.total == 3
    assert report.count("PASSED") == 1
    assert report.count("FAILED") == 1
    assert report.count("SKIPPED") == 1
    assert report.count("ERROR") == 0

    failed = next(case for case in report.testcases if case.status == "FAILED")
    assert failed.name == "rejectsWrongPassword"
    assert failed.message == "expected [false]"
    assert "AssertionError" in (failed.stacktrace or "")
    assert failed.duration_ms == 20


def test_parse_testsuites_wrapper(tmp_path):
    content = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="A" tests="1" failures="0" errors="0" skipped="0" time="0.01">
    <testcase name="one" classname="A" time="0.01"/>
  </testsuite>
  <testsuite name="B" tests="1" failures="0" errors="0" skipped="0" time="0.01">
    <testcase name="two" classname="B" time="0.01"/>
  </testsuite>
</testsuites>
"""
    reports = _write(tmp_path, "TEST-combined.xml", content)
    report = parse_reports(reports)

    assert report.total == 2
    assert report.count("PASSED") == 2


def test_missing_report_raises(tmp_path):
    (tmp_path / "reports").mkdir()

    with pytest.raises(ReportMissingError):
        parse_reports(tmp_path / "reports")


def test_nonexistent_directory_raises(tmp_path):
    with pytest.raises(ReportMissingError):
        parse_reports(tmp_path / "does-not-exist")


def test_malformed_xml_raises(tmp_path):
    reports = _write(tmp_path, "TEST-broken.xml", "<testsuite><testcase>")

    with pytest.raises(ReportMalformedError):
        parse_reports(reports)


def test_wrong_root_element_raises(tmp_path):
    content = """<?xml version="1.0"?>
<results>
  <case name="x"/>
</results>
"""
    reports = _write(tmp_path, "TEST-wrong.xml", content)

    with pytest.raises(ReportMalformedError):
        parse_reports(reports)


def test_counter_mismatch_raises(tmp_path):
    content = """<?xml version="1.0"?>
<testsuite name="M" tests="2" failures="0" errors="0" skipped="0" time="0.01">
  <testcase name="onlyOne" classname="M" time="0.01"/>
</testsuite>
"""
    reports = _write(tmp_path, "TEST-mismatch.xml", content)

    with pytest.raises(ReportMalformedError):
        parse_reports(reports)


def test_case_without_name_raises(tmp_path):
    content = """<?xml version="1.0"?>
<testsuite name="N" tests="1" failures="0" errors="0" skipped="0" time="0.01">
  <testcase classname="N" time="0.01"/>
</testsuite>
"""
    reports = _write(tmp_path, "TEST-noname.xml", content)

    with pytest.raises(ReportMalformedError):
        parse_reports(reports)


def test_report_without_testcases_raises(tmp_path):
    content = """<?xml version="1.0"?>
<testsuite name="E" tests="0" failures="0" errors="0" skipped="0" time="0"/>
"""
    reports = _write(tmp_path, "TEST-empty.xml", content)

    with pytest.raises(ReportMissingError):
        parse_reports(reports)
