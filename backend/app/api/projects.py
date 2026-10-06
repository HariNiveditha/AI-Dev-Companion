from fastapi import APIRouter, HTTPException, Depends
from typing import List
from uuid import uuid4
from ..models.project import Project, ProjectCreate
from ..models.requirement import Requirement, RequirementCreate
from ..db.mongodb import get_db

router = APIRouter()

@router.post("/", response_model=Project)
async def create_project(project_in: ProjectCreate):
    db = get_db()
    new_project = project_in.dict()
    new_project["_id"] = str(uuid4())
    new_project["status"] = "REQUIREMENT_PENDING"
    await db.projects.insert_one(new_project)
    return new_project

@router.get("/", response_model=List[Project])
async def get_projects():
    db = get_db()
    projects = await db.projects.find().to_list(1000)
    return projects

@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str):
    db = get_db()
    project = await db.projects.find_one({"_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@router.post("/{project_id}/requirements", response_model=Requirement)
async def add_requirement(project_id: str, req_in: RequirementCreate):
    db = get_db()
    project = await db.projects.find_one({"_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    new_req = req_in.dict()
    new_req["_id"] = str(uuid4())
    new_req["projectId"] = project_id
    new_req["status"] = "DRAFT"
    await db.requirements.insert_one(new_req)
    return new_req

@router.get("/{project_id}/requirements", response_model=List[Requirement])
async def get_requirements(project_id: str):
    db = get_db()
    reqs = await db.requirements.find({"projectId": project_id}).to_list(1000)
    return reqs
