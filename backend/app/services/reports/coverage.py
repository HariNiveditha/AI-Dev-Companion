from typing import Any
def build_coverage_report(
    requirements: list[dict[str, Any]],
    test_cases: list[dict[str, Any]],
    execution_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a test-case coverage summary from existing project records."""

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

    return {
        "total_requirements": total_requirements,
        "covered_requirements": len(covered),
        "uncovered_requirements": sorted(requirement_ids - covered),
        "requirement_coverage_percentage": coverage_percentage,
        "total_test_cases": len(test_cases),
        "total_execution_runs": len(execution_runs),
        "execution_status": "available" if execution_runs else "no_runs",
        "note": (
            "This report measures requirement-to-test-case coverage, "
            "not Java source-code coverage."
        ),
    }