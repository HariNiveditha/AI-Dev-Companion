"""Git/Repository integration API routes.

Provides endpoints for:
- Repository initialization and connection
- Repository status
- Changed-file listing and diffs
- Stage/unstage operations
- Commit creation
- Commit history and commit details
"""

from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

from app.services.git import (
    init_repo,
    connect_repo,
    get_repo_status,
    get_diff,
    stage_files,
    unstage_files,
    create_commit,
    get_commit_history,
    get_commit_details,
)
from app.db.mongodb import get_db


router = APIRouter(prefix="/git", tags=["Git"])


class ConnectRepoRequest(BaseModel):
    workspace_path: str = ""


class DiffRequest(BaseModel):
    source: Optional[str] = "HEAD"
    target: Optional[str] = None
    staging: bool = False


class StageFilesRequest(BaseModel):
    file_paths: Optional[List[str]] = None


class CommitRequest(BaseModel):
    message: Optional[str] = None
    file_paths: Optional[List[str]] = None


async def _get_project_id(project_id: str) -> str:
    """Validate that the project exists and return its ID."""
    db = get_db()
    project = await db.projects.find_one({"_id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project_id


@router.post("/init/{project_id}")
async def api_init_repo(project_id: str):
    """Initialize a new Git repository for the project workspace.

    The repo is initialized at the project's authorized workspace directory.
    If a repo already exists, this is reported safely without error.
    """
    project_id = await _get_project_id(project_id)
    result = await init_repo(project_id)
    return result


@router.post("/connect/{project_id}")
async def api_connect_repo(
    project_id: str,
    payload: Optional[ConnectRepoRequest] = Body(None),
    workspace_path: Optional[str] = Query(None),
):
    """Connect to an existing local Git repository."""
    project_id = await _get_project_id(project_id)
    path = (payload.workspace_path if payload and payload.workspace_path else workspace_path) or ""
    result = await connect_repo(project_id, path)
    return result


@router.get("/status/{project_id}")
async def api_repo_status(project_id: str):
    """Get the current Git repository status.

    Includes: current branch, clean/dirty state, modified/added/deleted/untracked files,
    staged/unstaged diffs, and latest commit information.
    """
    project_id = await _get_project_id(project_id)
    status = await get_repo_status(project_id)
    return status


@router.post("/diff/{project_id}")
async def api_get_diff(
    project_id: str,
    payload: Optional[DiffRequest] = Body(None),
    source: Optional[str] = Query(None),
    target: Optional[str] = Query(None),
    staging: Optional[bool] = Query(None),
):
    """Get a diff for the repository."""
    project_id = await _get_project_id(project_id)
    src = (payload.source if payload and payload.source else source) or "HEAD"
    tgt = payload.target if (payload and payload.target is not None) else target
    stg = payload.staging if (payload and payload.staging is not None) else (staging if staging is not None else False)
    diff = await get_diff(project_id, source=src, target=tgt, staging=stg)
    return diff


@router.post("/stage/{project_id}")
async def api_stage_files(
    project_id: str,
    payload: Optional[Union[StageFilesRequest, List[str]]] = Body(None),
):
    """Stage the specified files for commit."""
    project_id = await _get_project_id(project_id)
    if isinstance(payload, list):
        paths = payload
    elif payload and isinstance(payload, StageFilesRequest) and payload.file_paths is not None:
        paths = payload.file_paths
    else:
        paths = []
    staged = await stage_files(project_id, paths)
    return staged


@router.post("/unstage/{project_id}")
async def api_unstage_files(
    project_id: str,
    payload: Optional[Union[StageFilesRequest, List[str]]] = Body(None),
):
    """Unstage the specified files."""
    project_id = await _get_project_id(project_id)
    if isinstance(payload, list):
        paths = payload
    elif payload and isinstance(payload, StageFilesRequest) and payload.file_paths is not None:
        paths = payload.file_paths
    else:
        paths = []
    unstaged = await unstage_files(project_id, paths)
    return unstaged


@router.post("/commit/{project_id}")
async def api_create_commit(
    project_id: str,
    payload: Optional[CommitRequest] = Body(None),
    message: Optional[str] = Query(None),
):
    """Create a commit with the given message."""
    project_id = await _get_project_id(project_id)
    msg = (payload.message if payload and payload.message else message) or ""
    fps = payload.file_paths if payload else None
    committed = await create_commit(project_id, msg, fps)
    return committed


@router.get("/history/{project_id}")
async def api_commit_history(project_id: str, max_count: int = 20):
    """Get the recent commit history.

    Returns commits with hash, author, date, and message.
    """
    project_id = await _get_project_id(project_id)
    history = await get_commit_history(project_id, max_count=max_count)
    return history


@router.get("/commit/{project_id}/{commit_hash}")
async def api_commit_details(
    project_id: str,
    commit_hash: str,
):
    """Get details of a specific commit, including changed files and diff."""
    project_id = await _get_project_id(project_id)
    details = await get_commit_details(project_id, commit_hash)
    return details