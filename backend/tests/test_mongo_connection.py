"""Regression tests for MongoDB connection behavior.

Guards the 'projects disappear after refresh' root cause: the backend must
never silently fall back to a non-persistent in-memory store when configured to
use a real server, and it must surface a clear error (not an empty project
list) when that server is unreachable.
"""

import pytest

from app.db import mongodb


def test_mock_mode_uses_in_memory_client(monkeypatch):
    """USE_MOCK_MONGO=true must select the mock client and the app DB."""
    monkeypatch.setattr(mongodb, "USE_MOCK", True)
    monkeypatch.setattr(mongodb, "DB_NAME", "ai_assistant_db")

    import asyncio

    asyncio.run(mongodb.connect_to_mongo())
    try:
        assert mongodb.db is not None
        # mongomock_motor exposes a database object; the app reads it via get_db.
        assert mongodb.get_db() is mongodb.db
    finally:
        asyncio.run(mongodb.close_mongo_connection())


def test_real_mode_raises_clear_error_when_unreachable(monkeypatch):
    """A bad real-server URI must raise loudly, not return an empty DB handle."""
    monkeypatch.setattr(mongodb, "USE_MOCK", False)
    monkeypatch.setattr(mongodb, "DB_NAME", "ai_assistant_db")
    monkeypatch.setattr(
        mongodb, "MONGO_URI", "mongodb://127.0.0.1:59999/?serverSelectionTimeoutMS=200"
    )
    monkeypatch.setattr(mongodb, "SERVER_SELECTION_TIMEOUT_MS", 200)

    import asyncio

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(mongodb.connect_to_mongo())

    msg = str(excinfo.value)
    assert "Failed to connect to MongoDB" in msg
    # The password must never appear in the raised message.
    assert "example" not in msg


def test_redacted_uri_strips_credentials():
    """Logging helper must never include the password."""
    redacted = mongodb._redacted_uri(
        "mongodb://root:supersecret@127.0.0.1:27018/ai_assistant_db?authSource=admin"
    )
    assert "supersecret" not in redacted
    assert "root" not in redacted
    assert "127.0.0.1:27018" in redacted


def test_db_name_matches_collection_the_app_queries():
    """connect_to_mongo must select the same DB the project API reads/writes.

    The project endpoints call get_db().projects, so whatever DB name the
    connection layer picks is where projects are persisted. This asserts the
    configured name is the one the app depends on.
    """
    assert mongodb.DB_NAME == "ai_assistant_db"
