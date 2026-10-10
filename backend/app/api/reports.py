
from fastapi import APIRouter, HTTPException, Query

from app.db.mongodb import get_db
from app.services.reports.coverage import build_coverage_report

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/coverage")
async def get_coverage_report(
    project_id: str | None = Query(default=None),
):
    db = get_db()

    requirements_query = {}
    if project_id:
        requirements_query["projectId"] = project_id

    requirements = await db.requirements.find(
        requirements_query
    ).to_list(10000)

    requirement_ids = [
        str(item["_id"])
        for item in requirements
        if item.get("_id") is not None
    ]

    if requirement_ids:
        test_cases = await db.test_cases.find(
            {"requirement_id": {"$in": requirement_ids}}
        ).to_list(10000)

        execution_runs = await db.executions.find(
            {"requirement_id": {"$in": requirement_ids}}
        ).to_list(10000)
    else:
        test_cases = []
        execution_runs = []

    report = build_coverage_report(
        requirements,
        test_cases,
        execution_runs,
    )

    status_counts = {}
    for run in execution_runs:
        status = str(run.get("status", "UNKNOWN")).upper()
        status_counts[status] = status_counts.get(status, 0) + 1

    report["execution_status_counts"] = status_counts
    report["project_id"] = project_id

    return report
