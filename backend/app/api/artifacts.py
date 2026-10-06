from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.db.mongodb import get_db
from app.models.code_artifact import CodeArtifact, CodeArtifactEdit

router = APIRouter()


@router.put("/{artifact_id}", response_model=CodeArtifact)
async def edit_artifact(artifact_id: str, artifact_in: CodeArtifactEdit):
    db = get_db()
    current = await db.code_artifacts.find_one({"artifact_id": artifact_id})
    if not current:
        raise HTTPException(status_code=404, detail="Code artifact not found")

    previous_versions = await db.code_artifacts.find(
        {
            "project_id": current["project_id"],
            "requirement_id": current["requirement_id"],
            "file_name": current["file_name"],
        }
    ).to_list(1000)
    next_version = max(
        (artifact.get("version", 0) for artifact in previous_versions),
        default=0,
    ) + 1
    now = datetime.utcnow()
    edited = CodeArtifact(
        artifact_id=str(uuid4()),
        project_id=current["project_id"],
        requirement_id=current["requirement_id"],
        file_name=current["file_name"],
        language="Java",
        content=artifact_in.content,
        version=next_version,
        source="DEVELOPER_EDITED",
        status="EDITED",
        created_at=now,
        updated_at=now,
    ).model_dump()
    await db.code_artifacts.insert_one(edited)
    return edited