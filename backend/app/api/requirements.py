import re
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from app.db.mongodb import get_db
from app.models.code_artifact import CodeArtifact
from app.models.requirement import Requirement, RequirementAnalysis
from app.services.ai.service import analyze_requirement_text, generate_java_code

router = APIRouter()

JAVA_FILE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.java$")

@router.post("/{requirement_id}/analyze", response_model=Requirement)
async def analyze_requirement(requirement_id: str):
    db = get_db()
    req_data = await db.requirements.find_one({"_id": requirement_id})
    if not req_data:
        raise HTTPException(status_code=404, detail="Requirement not found")
    
    # Set status to analyzing
    await db.requirements.update_one({"_id": requirement_id}, {"$set": {"status": "ANALYZING"}})
    
    try:
        analysis_result = analyze_requirement_text(req_data["title"], req_data["description"])
        # Update requirement with analysis
        await db.requirements.update_one(
            {"_id": requirement_id}, 
            {"$set": {
                "status": "ANALYZED",
                "analysis": analysis_result.dict()
            }}
        )
    except ValueError as ve:
        # API Key missing or similar validation error
        await db.requirements.update_one({"_id": requirement_id}, {"$set": {"status": "ANALYSIS_FAILED"}})
        raise HTTPException(status_code=500, detail=str(ve))
    except Exception as e:
        await db.requirements.update_one({"_id": requirement_id}, {"$set": {"status": "ANALYSIS_FAILED"}})
        raise HTTPException(status_code=500, detail=f"AI Analysis Failed: {str(e)}")

    # Fetch updated
    updated_req = await db.requirements.find_one({"_id": requirement_id})
    return updated_req


@router.post("/{requirement_id}/confirm", response_model=Requirement)
async def confirm_requirement(requirement_id: str):
    db = get_db()
    req_data = await db.requirements.find_one({"_id": requirement_id})
    if not req_data:
        raise HTTPException(status_code=404, detail="Requirement not found")

    if req_data.get("status") != "ANALYZED":
        raise HTTPException(
            status_code=409,
            detail="Requirement must have a completed AI analysis before confirmation",
        )

    try:
        RequirementAnalysis.model_validate(req_data.get("analysis"))
    except (ValidationError, TypeError, ValueError):
        raise HTTPException(
            status_code=409,
            detail="Requirement must have a valid AI analysis before confirmation",
        )

    await db.requirements.update_one({"_id": requirement_id}, {"$set": {"status": "CONFIRMED"}})
    updated_req = await db.requirements.find_one({"_id": requirement_id})
    return updated_req


@router.post("/{requirement_id}/generate-code", response_model=list[CodeArtifact])
async def generate_code(requirement_id: str):
    db = get_db()
    req_data = await db.requirements.find_one({"_id": requirement_id})
    if not req_data:
        raise HTTPException(status_code=404, detail="Requirement not found")

    if req_data.get("status") != "CONFIRMED":
        raise HTTPException(
            status_code=409,
            detail="Requirement must be confirmed before code generation",
        )

    try:
        analysis = RequirementAnalysis.model_validate(req_data.get("analysis"))
    except (ValidationError, TypeError, ValueError):
        raise HTTPException(
            status_code=409,
            detail="Requirement must have a valid AI analysis before code generation",
        )

    try:
        generated = generate_java_code(
            req_data["title"], req_data["description"], analysis
        )
    except ValueError:
        raise HTTPException(
            status_code=503,
            detail="AI code generation is not configured",
        )
    except RuntimeError:
        raise HTTPException(status_code=502, detail="AI code generation failed")

    file_names = set()
    for generated_file in generated.files:
        if (
            not generated_file.file_name
            or not JAVA_FILE_NAME_PATTERN.fullmatch(generated_file.file_name)
            or generated_file.file_name in file_names
            or not generated_file.content.strip()
        ):
            raise HTTPException(
                status_code=502,
                detail="AI returned an invalid Java source file",
            )
        file_names.add(generated_file.file_name)

    now = datetime.utcnow()
    artifacts = []
    for generated_file in generated.files:
        previous_versions = await db.code_artifacts.find(
            {
                "project_id": req_data["projectId"],
                "requirement_id": requirement_id,
                "file_name": generated_file.file_name,
            }
        ).to_list(1000)
        next_version = max(
            (artifact.get("version", 0) for artifact in previous_versions),
            default=0,
        ) + 1
        artifacts.append(
            CodeArtifact(
                artifact_id=str(uuid4()),
                project_id=req_data["projectId"],
                requirement_id=requirement_id,
                file_name=generated_file.file_name,
                language="Java",
                content=generated_file.content,
                version=next_version,
                source="AI_GENERATED",
                status="AI_GENERATED",
                created_at=now,
                updated_at=now,
            ).model_dump()
        )

    await db.code_artifacts.insert_many(artifacts)
    return artifacts


@router.get("/{requirement_id}/artifacts", response_model=list[CodeArtifact])
async def get_requirement_artifacts(requirement_id: str):
    db = get_db()
    requirement = await db.requirements.find_one({"_id": requirement_id})
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return await db.code_artifacts.find(
        {"requirement_id": requirement_id}
    ).sort([("file_name", 1), ("version", 1)]).to_list(1000)
