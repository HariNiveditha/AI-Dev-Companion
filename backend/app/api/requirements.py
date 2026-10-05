from fastapi import APIRouter, HTTPException
from app.db.mongodb import get_db
from app.models.requirement import Requirement, RequirementAnalysis
from app.services.ai.service import analyze_requirement_text

router = APIRouter()

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
        
    await db.requirements.update_one({"_id": requirement_id}, {"$set": {"status": "CONFIRMED"}})
    updated_req = await db.requirements.find_one({"_id": requirement_id})
    return updated_req
