"""Phase 9 reporting.

The report is deliberately honest about what each metric measures:

* **Requirement coverage** — share of requirements that have at least
  one linked descriptive test case.  This is *linkage*, NOT coverage
  of Java source code.
* **Test result summary** — pass/fail/skip/error counts aggregated
  from the persisted per-test results of every recorded execution run.
* **Execution status counts** — number of execution records per
  lifecycle status (DISABLED, ERROR, PASSED, FAILED, ...).
* **Code coverage** — NOT measured.  The runner does not integrate a
  coverage instrument (e.g. JaCoCo), so no source-coverage percentage
  is reported.  It is never guessed or fabricated.
"""

from typing import Any


_TERMINAL_STATUSES = {"PASSED", "FAILED", "ERROR", "DISABLED"}


def build_coverage_report(
    requirements: list[dict[str, Any]],
    test_cases: list[dict[str, Any]],
    execution_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a test-inventory, linkage, and execution-result summary."""

    requirement_ids = {
        str(item.get("_id", item.get("id")))
        for item in requirements
        if item.get("_id", item.get("id")) is not None
    }

    covered_requirement_ids = {
        str(item.get("requirement_id"))
        for item in test_cases
        if item.get("requirement_id") is not None
    }

    covered = requirement_ids & covered_requirement_ids
    total_requirements = len(requirement_ids)

    coverage_percentage = (
        round(len(covered) / total_requirements * 100, 2)
        if total_requirements
        else 0.0
    )

    # Aggregate per-test outcomes across every recorded execution run.
    result_totals = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 0}
    runs_with_results = 0
    for run in execution_runs:
        results = run.get("test_results") or []
        if results:
            runs_with_results += 1
        for result in results:
            status = str(result.get("status", "")).upper()
            result_totals["total"] += 1
            if status in ("PASSED", "FAILED", "SKIPPED", "ERROR"):
                result_totals[status.lower()] += 1

    return {
        "total_requirements": total_requirements,
        "covered_requirements": len(covered),
        "uncovered_requirements": sorted(requirement_ids - covered),
        "requirement_coverage_percentage": coverage_percentage,
        "total_test_cases": len(test_cases),
        "total_execution_runs": len(execution_runs),
        "execution_status": "available" if execution_runs else "no_runs",
        # New in Phase 9: what was actually executed and how it went.
        "test_result_summary": {
            **result_totals,
            "executions_with_results": runs_with_results,
            "scope": (
                "Aggregated from persisted per-test results of every "
                "recorded execution run."
            ),
        },
        "code_coverage": {
            "status": "NOT_MEASURED",
            "percentage": None,
            "reason": (
                "Java source-code coverage is not measured: the execution "
                "runner does not integrate a coverage instrument such as "
                "JaCoCo. Requirement-to-test-case linkage above is not "
                "source-code coverage."
            ),
        },
        "metrics": {
            "requirement_coverage_percentage": (
                "Share of requirements with at least one linked descriptive "
                "test case (linkage only; not source-code coverage)."
            ),
            "test_result_summary": (
                "Per-test pass/fail/skip/error counts from validated JUnit "
                "XML reports, aggregated across all recorded runs."
            ),
            "execution_status_counts": (
                "Number of execution records per lifecycle status."
            ),
            "code_coverage": (
                "Java source-code coverage: not measured (no JaCoCo integration)."
            ),
        },
        "note": (
            "Requirement coverage counts requirements that have at least one "
            "linked test case. It is not Java source-code coverage, and code "
            "coverage is not measured by this project."
        ),
    }
