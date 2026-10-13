import asyncio
import os
import shutil
import stat
import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.db.mongodb import get_db
from app.main import app
from app.services.git import APP_ROOT


def safe_rmtree(path: Path):
    if not path.exists():
        return
    def onerror(func, p, _):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    shutil.rmtree(path, onerror=onerror)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def test_project():
    project_id = f"test-git-{uuid.uuid4().hex[:8]}"
    workspace_dir = APP_ROOT / "projects" / project_id
    safe_rmtree(workspace_dir)

    db = get_db()
    asyncio.run(
        db.projects.update_one(
            {"_id": project_id},
            {
                "$set": {
                    "_id": project_id,
                    "name": "Git Test Project",
                    "description": "Project for git testing",
                    "language": "Java",
                    "status": "REQUIREMENT_PENDING",
                }
            },
            upsert=True,
        )
    )

    yield project_id

    # Cleanup
    safe_rmtree(workspace_dir)
    asyncio.run(db.projects.delete_one({"_id": project_id}))


def test_git_status_uninitialized(client, test_project):
    """Status on a non-initialized repo returns is_repo: False and does not crawl to parent."""
    resp = client.get(f"/git/status/{test_project}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_repo"] is False
    assert data["latest_commit"] is None


def test_git_init_success(client, test_project):
    """Init creates a real .git directory inside the project workspace."""
    resp = client.post(f"/git/init/{test_project}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["initialized"] is True
    assert data["already_existing"] is False

    git_dir = APP_ROOT / "projects" / test_project / ".git"
    assert git_dir.exists()
    assert git_dir.is_dir()

    # Second call detects already existing repo safely
    resp_again = client.post(f"/git/init/{test_project}")
    assert resp_again.status_code == 200
    data_again = resp_again.json()
    assert data_again["initialized"] is True
    assert data_again["already_existing"] is True


def test_git_status_after_init(client, test_project):
    """Status after init shows is_repo: True, clean working tree, and no commits."""
    client.post(f"/git/init/{test_project}")
    resp = client.get(f"/git/status/{test_project}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_repo"] is True
    assert data["is_clean"] is True
    assert data["latest_commit"] is None


def test_git_stage_unstage_commit_diff_flow(client, test_project):
    """Full lifecycle: create file, stage, diff, unstage, stage, commit, history."""
    init_res = client.post(f"/git/init/{test_project}")
    assert init_res.status_code == 200
    workspace_dir = APP_ROOT / "projects" / test_project

    # Create file
    test_file = workspace_dir / "Calculator.java"
    test_file.write_text("public class Calculator { public int add(int a, int b) { return a + b; } }\n")

    # Status shows untracked file
    resp_status = client.get(f"/git/status/{test_project}")
    assert resp_status.status_code == 200
    assert "Calculator.java" in resp_status.json()["untracked_files"]
    assert resp_status.json()["is_clean"] is False

    # Stage the file
    resp_stage = client.post(
        f"/git/stage/{test_project}",
        json={"file_paths": ["Calculator.java"]},
    )
    assert resp_stage.status_code == 200
    assert resp_stage.json()["staged"] is True

    # Diff with staging=True shows added file
    resp_diff = client.post(
        f"/git/diff/{test_project}",
        json={"staging": True},
    )
    assert resp_diff.status_code == 200
    assert "Calculator" in resp_diff.json()["diff"]

    # Unstage the file
    resp_unstage = client.post(
        f"/git/unstage/{test_project}",
        json={"file_paths": ["Calculator.java"]},
    )
    assert resp_unstage.status_code == 200
    assert resp_unstage.json()["unstaged"] is True

    # Stage all (empty list)
    resp_stage_all = client.post(
        f"/git/stage/{test_project}",
        json={"file_paths": []},
    )
    assert resp_stage_all.status_code == 200

    # Commit with message
    resp_commit = client.post(
        f"/git/commit/{test_project}",
        json={"message": "feat: add calculator service"},
    )
    assert resp_commit.status_code == 200
    commit_data = resp_commit.json()
    assert commit_data["committed"] is True
    commit_hash = commit_data["commit_hash"]
    assert len(commit_hash) >= 7

    # Status after commit is clean
    resp_clean = client.get(f"/git/status/{test_project}")
    assert resp_clean.status_code == 200
    status_data = resp_clean.json()
    assert status_data["is_clean"] is True
    assert status_data["latest_commit"]["message"] == "feat: add calculator service"
    assert status_data["latest_commit"]["hash"] == commit_hash

    # Commit history contains the commit
    resp_history = client.get(f"/git/history/{test_project}")
    assert resp_history.status_code == 200
    history = resp_history.json()
    assert history["total_shown"] == 1
    assert history["commits"][0]["hash"] == commit_hash
    assert history["commits"][0]["message"] == "feat: add calculator service"

    # Commit details contains diff
    resp_details = client.get(f"/git/commit/{test_project}/{commit_hash}")
    assert resp_details.status_code == 200
    details = resp_details.json()
    assert details["commit_hash"] == commit_hash
    assert "Calculator.java" in details["changed_files"]


def test_path_traversal_is_blocked(client, test_project):
    """Path traversal attempts are rejected with 400 Bad Request."""
    client.post(f"/git/init/{test_project}")

    resp = client.post(
        f"/git/stage/{test_project}",
        json={"file_paths": ["../../etc/passwd"]},
    )
    assert resp.status_code == 400
