
from app.services.reports.coverage import build_coverage_report


def test_empty_coverage_report():
    report = build_coverage_report([], [], [])

    assert report["total_requirements"] == 0
    assert report["covered_requirements"] == 0
    assert report["uncovered_requirements"] == []
    assert report["requirement_coverage_percentage"] == 0
    assert report["total_test_cases"] == 0
    assert report["total_execution_runs"] == 0


def test_coverage_with_covered_and_uncovered_requirements():
    requirements = [
        {"_id": "req-1"},
        {"_id": "req-2"},
        {"_id": "req-3"},
    ]
    test_cases = [
        {"requirement_id": "req-1"},
        {"requirement_id": "req-1"},
        {"requirement_id": "req-3"},
    ]
    execution_runs = [
        {"execution_id": "run-1", "status": "PENDING"},
        {"execution_id": "run-2", "status": "DISABLED"},
    ]

    report = build_coverage_report(
        requirements,
        test_cases,
        execution_runs,
    )

    assert report["total_requirements"] == 3
    assert report["covered_requirements"] == 2
    assert report["uncovered_requirements"] == ["req-2"]
    assert report["requirement_coverage_percentage"] == 66.67
    assert report["total_test_cases"] == 3
    assert report["total_execution_runs"] == 2
