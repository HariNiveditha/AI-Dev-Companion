import os
from urllib.parse import urlparse

from motor.motor_asyncio import AsyncIOMotorClient

# Fallback to mongomock_motor if real mongo is not running
from mongomock_motor import AsyncMongoMockClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
USE_MOCK = os.getenv("USE_MOCK_MONGO", "true").lower() == "true"
DB_NAME = os.getenv("MONGO_DB_NAME", "ai_assistant_db")
# Fail fast (instead of hanging) when the real server is unreachable/misconfigured.
SERVER_SELECTION_TIMEOUT_MS = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000"))

client = None
db = None


def _redacted_uri(uri: str) -> str:
    """Return the URI with any password stripped, safe to log."""
    try:
        parsed = urlparse(uri)
        host = parsed.hostname or "?"
        port = parsed.port or 27017
        return f"{parsed.scheme}://{host}:{port}/{DB_NAME}"
    except Exception:
        return "mongodb://<unparseable-uri>"


async def connect_to_mongo():
    """Connect to MongoDB, verifying the real server before serving traffic.

    When USE_MOCK_MONGO is false we ping the server during startup so a wrong
    port/credentials fails loudly here, instead of the API silently returning
    empty project lists later.
    """
    global client, db
    if USE_MOCK:
        client = AsyncMongoMockClient()
        print("⚠️  Using in-memory Mock MongoDB (USE_MOCK_MONGO=true) — data is NOT persisted.")
    else:
        client = AsyncIOMotorClient(
            MONGO_URI,
            serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
        )
        try:
            await client.admin.command("ping")
        except Exception as exc:
            raise RuntimeError(
                "Failed to connect to MongoDB at "
                f"{_redacted_uri(MONGO_URI)}. "
                "Check that the server is running, the host/port are correct, "
                "and credentials/authSource match. "
                f"Original error: {type(exc).__name__}"
            ) from exc
        print(f"Using Real MongoDB at {_redacted_uri(MONGO_URI)}")
    db = client[DB_NAME]


async def close_mongo_connection():
    global client
    if client and not USE_MOCK:
        client.close()


def get_db():
    return db
