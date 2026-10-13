import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from fastapi import HTTPException

from app.db.mongodb import get_db
from app.models.code_artifact import CodeArtifact

APP_ROOT = Path(__file__).resolve().parents[2]


def shutil_which(cmd: str) -> Optional[str]:
    """Simple shutil.which wrapper."""
    return shutil.which(cmd)


def _ensure_git_available() -> None:
    """Verify git is available; raise HTTPException if not."""
    if shutil_which("git") is None:
        raise HTTPException(status_code=503, detail="Git is not installed on this system.")


async def _sync_artifacts_to_workspace(project_id: str) -> None:
    """Synchronize generated Java artifacts into the project workspace.

    Materializes the latest version of each Java source file from the
    code_artifacts MongoDB collection into the project's workspace directory
    so that Git operations can track them. Silently skips if the database
    is not available.
    """
    db = get_db()
    if db is None:
        return

    workspace_root = APP_ROOT / "projects" / project_id
    workspace_root.mkdir(parents=True, exist_ok=True)

    # Use the async MongoDB driver's find/to_list properly
    try:
        artifacts = await db.code_artifacts.find({"project_id": project_id}).sort(
            "version", -1
        ).to_list(None)
    except Exception:
        # Fallback: if the database operation fails, skip sync gracefully
        return

    written_files: set[str] = set()

    for artifact in artifacts:
        file_name = artifact.get("file_name", "")
        if not file_name or not file_name.endswith(".java"):
            continue

        if file_name in written_files:
            continue
        written_files.add(file_name)

        file_path = workspace_root / file_name
        file_path.parent.mkdir(parents=True, exist_ok=True)

        content = artifact.get("content", "")
        if content.strip():
            file_path.write_text(content, encoding="utf-8")


def _resolve_workspace_path(project_id: str, path: Union[str, Path] = "") -> Path:
    """Resolve and validate that a path is within the project's authorized workspace.

    Each project is expected to have its workspace under APP_ROOT / projects / {project_id}.
    Path traversal outside this boundary raises an error.
    """
    workspace_root = (APP_ROOT / "projects" / project_id).resolve()
    p = str(path).strip() if path is not None else ""
    if not p or p == ".":
        return workspace_root

    path_obj = Path(p)
    if path_obj.is_absolute():
        resolved = path_obj.resolve()
    else:
        resolved = (workspace_root / path_obj).resolve()

    if not str(resolved).startswith(str(workspace_root) + os.sep) and resolved != workspace_root:
        raise HTTPException(
            status_code=400,
            detail=f"Path '{path}' resolves outside the authorized workspace for project {project_id}.",
        )

    return resolved


def _run_git(
    project_id: str,
    *args: str,
    cwd: Optional[str] = None,
    timeout_seconds: int = 30,
) -> subprocess.CompletedProcess:
    """Run a git command safely with argument arrays (no shell=True).

    The working directory is always constrained to the project workspace.
    """
    _ensure_git_available()

    if cwd is not None:
        resolved_cwd = _resolve_workspace_path(project_id, cwd)
    else:
        resolved_cwd = (APP_ROOT / "projects" / project_id).resolve()

    # Flatten and normalize arguments, avoiding accidental leading 'git' duplicates
    cleaned_args: List[str] = []
    for a in args:
        if a == "git" and not cleaned_args:
            continue
        cleaned_args.append(str(a))

    cmd = ["git", *cleaned_args]

    env = os.environ.copy()
    # Stop Git from ascending above APP_ROOT into the host application repository
    env["GIT_CEILING_DIRECTORIES"] = str(APP_ROOT)
    # Ensure standard author/committer configs so commits succeed everywhere
    if not env.get("GIT_AUTHOR_NAME"):
        env["GIT_AUTHOR_NAME"] = "AI SE Assistant"
    if not env.get("GIT_AUTHOR_EMAIL"):
        env["GIT_AUTHOR_EMAIL"] = "assistant@local"
    if not env.get("GIT_COMMITTER_NAME"):
        env["GIT_COMMITTER_NAME"] = "AI SE Assistant"
    if not env.get("GIT_COMMITTER_EMAIL"):
        env["GIT_COMMITTER_EMAIL"] = "assistant@local"

    try:
        return subprocess.run(
            cmd,
            cwd=str(resolved_cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail=f"Git command timed out after {timeout_seconds} seconds.",
        )


def _is_git_repo(project_id: str, path: Union[str, Path] = "") -> bool:
    """Check if the given path is a Git repository within the project workspace."""
    try:
        cwd = _resolve_workspace_path(project_id, path or ".")
        if not cwd.exists():
            return False
        # Direct check for .git directory or gitdir file
        if (cwd / ".git").exists():
            return True

        result = _run_git(project_id, "rev-parse", "--show-toplevel", cwd=str(cwd), timeout_seconds=10)
        if result.returncode != 0:
            return False

        top_level = Path(result.stdout.strip()).resolve()
        workspace_root = (APP_ROOT / "projects" / project_id).resolve()
        return top_level == workspace_root or str(top_level).startswith(str(workspace_root) + os.sep)
    except HTTPException:
        raise
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API functions (async)
# ---------------------------------------------------------------------------


async def init_repo(project_id: str, workspace_path: str = "") -> Dict[str, Any]:
    """Initialize a new Git repository in the project workspace.

    The repo is initialized at the project's authorized workspace directory.
    If a repo already exists, this is reported safely without error.

    Synchronizes MongoDB artifacts to the workspace before initialization.
    """
    await _sync_artifacts_to_workspace(project_id)

    target = _resolve_workspace_path(project_id, workspace_path or ".")
    target.mkdir(parents=True, exist_ok=True)

    if _is_git_repo(project_id, workspace_path or "."):
        return {
            "initialized": True,
            "already_existing": True,
            "path": str(target),
            "message": "Repository already exists at workspace path.",
        }

    result = _run_git(project_id, "init", cwd=str(target))
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Git init failed: {result.stderr.strip() or result.stdout.strip()}",
        )

    return {
        "initialized": True,
        "already_existing": False,
        "path": str(target),
        "message": "Repository initialized successfully.",
    }


async def connect_repo(project_id: str, workspace_path: str = "") -> Dict[str, Any]:
    """Connect to an existing local Git repository at the given workspace path."""
    await _sync_artifacts_to_workspace(project_id)

    target = _resolve_workspace_path(project_id, workspace_path or ".")

    if not _is_git_repo(project_id, workspace_path or "."):
        raise HTTPException(
            status_code=400,
            detail=f"No Git repository found at '{workspace_path}'. Initialize one first or verify the path.",
        )

    return {
        "connected": True,
        "path": str(target),
        "existing_repository": True,
    }


async def get_repo_status(project_id: str, workspace_path: str = "") -> Dict[str, Any]:
    """Get the current Git repository status.

    Includes: current branch, clean/dirty state, modified/added/deleted/untracked files,
    staged/unstaged diffs, and latest commit information.

    Synchronizes MongoDB artifacts to the workspace before status check.
    """
    await _sync_artifacts_to_workspace(project_id)

    base = _resolve_workspace_path(project_id, workspace_path or ".")

    if not _is_git_repo(project_id, workspace_path or "."):
        return {
            "error": "No Git repository found at the specified path.",
            "is_repo": False,
            "branch": None,
            "is_clean": True,
            "modified_files": [],
            "added_files": [],
            "deleted_files": [],
            "untracked_files": [],
            "staged_diff": "",
            "unstaged_diff": "",
            "staged_diff_stat": "",
            "latest_commit": None,
            "has_upstream": False,
            "branch_detail": None,
        }

    branch_result = _run_git(project_id, "branch", "--show-current", cwd=str(base))
    branch = branch_result.stdout.strip()
    if not branch:
        sym_result = _run_git(project_id, "symbolic-ref", "--short", "HEAD", cwd=str(base))
        branch = sym_result.stdout.strip() or "main"

    full_status_result = _run_git(project_id, "status", "--porcelain", cwd=str(base))

    modified = []
    added = []
    deleted = []
    untracked = []

    for line in full_status_result.stdout.splitlines():
        if not line.strip() or len(line) < 3:
            continue
        stage_chars = line[:2]
        filename = line[3:].strip()
        if stage_chars[0] == '?':
            untracked.append(filename)
        elif stage_chars[0] == 'M':
            modified.append(filename)
        elif stage_chars[0] == 'A':
            added.append(filename)
        elif stage_chars[0] == 'D':
            deleted.append(filename)
        elif stage_chars == 'AA':
            added.append(filename)
        elif stage_chars[0] == ' ' and stage_chars[1] == 'D':
            deleted.append(filename)
        elif stage_chars[0] == ' ' and stage_chars[1] == 'M':
            modified.append(filename)
        elif stage_chars[0] == 'R':
            modified.append(filename)
        elif stage_chars[0] == 'C':
            modified.append(filename)

    diff_result_staged = _run_git(project_id, "diff", "--cached", cwd=str(base))
    diff_result_unstaged = _run_git(project_id, "diff", cwd=str(base))

    branch_ahead_behind_result = _run_git(
        project_id, "log", "--oneline", "@{u}...HEAD", cwd=str(base), timeout_seconds=10
    )
    has_upstream = branch_ahead_behind_result.returncode == 0
    ahead = 0
    behind = 0
    if has_upstream:
        ahead_result = _run_git(project_id, "rev-list", "--count", "HEAD..@{u}", cwd=str(base), timeout_seconds=10)
        behind_result = _run_git(project_id, "rev-list", "--count", "@{u}..HEAD", cwd=str(base), timeout_seconds=10)
        if ahead_result.returncode == 0:
            ahead = int(ahead_result.stdout.strip() or "0")
        if behind_result.returncode == 0:
            behind = int(behind_result.stdout.strip() or "0")

    is_clean = (
        not modified
        and not added
        and not deleted
        and not untracked
        and not (diff_result_staged.stdout or "").strip()
    )

    diff_summary_result = _run_git(project_id, "diff", "--stat", "--cached", cwd=str(base))

    commit_info = None
    latest_result = _run_git(project_id, "log", "--oneline", "-1", cwd=str(base))
    if latest_result.returncode == 0 and latest_result.stdout.strip():
        commit_line = latest_result.stdout.strip()
        match = re.match(r"^([0-9a-f]{7,})\s+(.*)", commit_line)
        if match:
            commit_hash = match.group(1)
            message = match.group(2)
            commit_show = _run_git(project_id, "show", "--format=%an <%ae>", "--no-patch", "-s", cwd=str(base))
            author = commit_show.stdout.strip() if commit_show.returncode == 0 else ""
            commit_show_date = _run_git(project_id, "show", "--format=%ai", "--no-patch", "-s", cwd=str(base))
            date = commit_show_date.stdout.strip() if commit_show_date.returncode == 0 else ""
            commit_info = {
                "hash": commit_hash,
                "message": message,
                "author": author,
                "date": date,
            }

    return {
        "is_repo": True,
        "branch": branch,
        "is_clean": is_clean,
        "modified_files": modified,
        "added_files": added,
        "deleted_files": deleted,
        "untracked_files": untracked,
        "staged_diff": diff_result_staged.stdout.strip(),
        "unstaged_diff": diff_result_unstaged.stdout.strip() if diff_result_unstaged.stdout else "",
        "staged_diff_stat": diff_summary_result.stdout.strip(),
        "latest_commit": commit_info,
        "has_upstream": has_upstream,
        "branch_detail": {
            "name": branch,
            "ahead": ahead,
            "behind": behind,
        },
    }


async def get_diff(
    project_id: str,
    source: Optional[str] = "HEAD",
    target: Optional[str] = None,
    staging: bool = False,
) -> Dict[str, Any]:
    """Get diff between commits, index, or working tree."""
    _ensure_git_available()
    workspace_root = (APP_ROOT / "projects" / project_id).resolve()

    if not _is_git_repo(project_id, "."):
        return {"diff": "", "stat": ""}

    if staging:
        cmd = ["diff", "--cached"]
    else:
        cmd = ["diff"]

    if target:
        cmd.extend([source, target])
    elif source and source != "HEAD":
        cmd.extend([source])

    result = _run_git(project_id, *cmd, cwd=str(workspace_root))
    return {
        "diff": result.stdout.strip() if result.returncode == 0 else "",
        "stat": result.stderr.strip() if result.stderr else "",
    }


async def stage_files(project_id: str, file_paths: Optional[List[str]] = None) -> Dict[str, Any]:
    """Stage specified files or all files if list is empty."""
    await _sync_artifacts_to_workspace(project_id)
    workspace_root = (APP_ROOT / "projects" / project_id).resolve()

    if not _is_git_repo(project_id, "."):
        raise HTTPException(status_code=400, detail="Repository not initialized.")

    if not file_paths:
        result = _run_git(project_id, "add", "-A", cwd=str(workspace_root))
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Git add failed: {result.stderr.strip() or result.stdout.strip()}",
            )
        return {
            "staged": True,
            "files": ["."],
            "message": "All files staged successfully.",
        }

    rel_paths: List[str] = []
    for fp in file_paths:
        resolved = _resolve_workspace_path(project_id, fp)
        rel = Path(resolved).relative_to(workspace_root)
        rel_paths.append(str(rel))

    result = _run_git(project_id, "add", *rel_paths, cwd=str(workspace_root))
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Git add failed: {result.stderr.strip() or result.stdout.strip()}",
        )

    return {
        "staged": True,
        "files": file_paths,
        "message": "Files staged successfully.",
    }


async def unstage_files(project_id: str, file_paths: Optional[List[str]] = None) -> Dict[str, Any]:
    """Unstage specified files or all files if list is empty."""
    await _sync_artifacts_to_workspace(project_id)
    workspace_root = (APP_ROOT / "projects" / project_id).resolve()

    if not _is_git_repo(project_id, "."):
        raise HTTPException(status_code=400, detail="Repository not initialized.")

    head_check = _run_git(project_id, "rev-parse", "--verify", "HEAD", cwd=str(workspace_root))
    has_head = head_check.returncode == 0

    if not file_paths:
        if has_head:
            result = _run_git(project_id, "reset", "HEAD", cwd=str(workspace_root))
        else:
            result = _run_git(project_id, "rm", "--cached", "-r", ".", cwd=str(workspace_root))

        return {
            "unstaged": True,
            "files": ["."],
            "message": "All files unstaged successfully.",
        }

    rel_paths: List[str] = []
    for fp in file_paths:
        resolved = _resolve_workspace_path(project_id, fp)
        rel = Path(resolved).relative_to(workspace_root)
        rel_paths.append(str(rel))

    if has_head:
        result = _run_git(project_id, "reset", "HEAD", "--", *rel_paths, cwd=str(workspace_root))
    else:
        result = _run_git(project_id, "rm", "--cached", "--", *rel_paths, cwd=str(workspace_root))

    return {
        "unstaged": True,
        "files": file_paths,
        "message": "Files unstaged successfully.",
    }


async def create_commit(
    project_id: str,
    message: str,
    file_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a commit with the given message.

    If file_paths are specified, only those files are included in the commit.
    If no files are specified, all staged changes are committed.

    Synchronizes MongoDB artifacts to the workspace before committing.
    """
    await _sync_artifacts_to_workspace(project_id)

    if not message or not message.strip():
        raise HTTPException(status_code=400, detail="Commit message is required.")

    if not _is_git_repo(project_id, "."):
        raise HTTPException(status_code=400, detail="Repository not initialized.")

    workspace_root = (APP_ROOT / "projects" / project_id).resolve()

    if file_paths:
        await stage_files(project_id, file_paths)

    result = _run_git(project_id, "commit", "-m", message.strip(), cwd=str(workspace_root))
    if result.returncode != 0:
        combined = f"{result.stderr.strip()} {result.stdout.strip()}".lower()
        if "nothing to commit" in combined or "no changes added to commit" in combined:
            raise HTTPException(
                status_code=400,
                detail="No changes to commit. Stage files first or provide modifications.",
            )
        raise HTTPException(
            status_code=500,
            detail=f"Git commit failed: {result.stderr.strip() or result.stdout.strip()}",
        )

    commit_info_result = _run_git(project_id, "log", "--oneline", "-1", cwd=str(workspace_root))
    commit_hash = commit_info_result.stdout.strip().split()[0] if commit_info_result.returncode == 0 else "unknown"

    return {
        "committed": True,
        "commit_hash": commit_hash,
        "message": message.strip(),
    }


async def get_commit_history(
    project_id: str,
    max_count: int = 20,
) -> Dict[str, Any]:
    """Get the recent commit history.

    Returns a list of commits with hash, author, date, and message.

    Synchronizes MongoDB artifacts to the workspace before fetching history.
    """
    await _sync_artifacts_to_workspace(project_id)
    workspace_root = (APP_ROOT / "projects" / project_id).resolve()

    if not _is_git_repo(project_id, "."):
        return {"commits": [], "total_shown": 0}

    result = _run_git(
        project_id, "log", f"-{max_count}", "--oneline", cwd=str(workspace_root)
    )
    if result.returncode != 0:
        return {"commits": [], "total_shown": 0}

    commits = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        match = re.match(r"^([0-9a-f]{7,12})\s+(.*)", line)
        if match:
            commit_hash = match.group(1)
            msg = match.group(2)
            author_result = _run_git(
                project_id, "show", "--format=%an <%ae>", "--no-patch", "-s", f"{commit_hash}^!",
                cwd=str(workspace_root),
            )
            date_result = _run_git(
                project_id, "show", "--format=%ai", "--no-patch", "-s", f"{commit_hash}^!",
                cwd=str(workspace_root),
            )

            author = author_result.stdout.strip() if author_result.returncode == 0 else "unknown"
            date = date_result.stdout.strip() if date_result.returncode == 0 else "unknown"

            commits.append({
                "hash": commit_hash,
                "message": msg,
                "author": author,
                "date": date,
            })

    return {
        "commits": commits,
        "total_shown": len(commits),
    }


async def get_commit_details(
    project_id: str,
    commit_hash: str,
) -> Dict[str, Any]:
    """Get details of a specific commit, including changed files and diff."""
    _ensure_git_available()
    workspace_root = (APP_ROOT / "projects" / project_id).resolve()

    verify = _run_git(
        project_id, "rev-parse", "--verify", commit_hash,
        cwd=str(workspace_root),
        timeout_seconds=10,
    )
    if verify.returncode != 0:
        raise HTTPException(
            status_code=404,
            detail=f"Commit '{commit_hash}' not found in this repository.",
        )

    diff_result = _run_git(
        project_id, "show", "--format=", "--stat", commit_hash,
        cwd=str(workspace_root),
    )

    changed_files_result = _run_git(
        project_id, "show", "--format=", "--name-only", commit_hash,
        cwd=str(workspace_root),
    )

    full_diff_result = _run_git(
        project_id, "show", commit_hash,
        cwd=str(workspace_root),
    )

    return {
        "commit_hash": commit_hash,
        "stat": diff_result.stdout.strip() if diff_result.returncode == 0 else "",
        "changed_files": [
            f for f in changed_files_result.stdout.strip().splitlines() if f.strip()
        ]
        if changed_files_result.returncode == 0
        else [],
        "diff": full_diff_result.stdout.strip() if full_diff_result.returncode == 0 else "",
    }