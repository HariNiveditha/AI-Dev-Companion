"""Tests for the Phase 9 report: honest linkage/result metrics."""

from app.services.reports.coverage import build_coverage_report


def test_report_measures_linkage_and_results():
    requirements = [{"_id": "req-1"}, {"_id": "req-2"}]
    test_cases = [{"requirement_id": "req-1"}]
    execution_runs = [
        {
            "execution_id": "run-1",
            "status": "PASSED",
            "test_results": [
                {"status": "PASSED"},
                {"status": "PASSED"},
                {"status": "FAILED"},
                {"status": "SKIPPED"},
            ],
        },
        {
            "execution_id": "run-2",
            "status": "ERROR",
            "test_results": [{"status": "ERROR"}],
        },
        {"execution_id": "run-3", "status": "DISABLED"},
    ]

    report = build_coverage_report(requirements, test_cases, execution_runs)

    # Linkage (not source coverage).
    assert report["total_requirements"] == 2
    assert report["covered_requirements"] == 1
    assert report["requirement_coverage_percentage"] == 50.0

    # Real per-test outcomes.
    assert report["test_result_summary"]["total"] == 5
    assert report["test_result_summary"]["passed"] == 2
    assert report["test_result_summary"]["failed"] == 1
    assert report["test_result_summary"]["skipped"] == 1
    assert report["test_result_summary"]["error"] == 1
    assert report["test_result_summary"]["executions_with_results"] == 2

    # Source-code coverage is explicitly not measured.
    assert report["code_coverage"]["status"] == "NOT_MEASURED"
    assert report["code_coverage"]["percentage"] is None

    assert report["metrics"]["code_coverage"]


def test_report_with_no_runs():
    report = build_coverage_report([{"_id": "req-1"}], [], [])

    assert report["test_result_summary"]["total"] == 0
    assert report["test_result_summary"]["executions_with_results"] == 0
    assert report["execution_status"] == "no_runs"
    assert report["code_coverage"]["status"] == "NOT_MEASURED"
