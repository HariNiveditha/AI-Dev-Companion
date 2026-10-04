import os
from motor.motor_asyncio import AsyncIOMotorClient

# Fallback to mongomock_motor if real mongo is not running
from mongomock_motor import AsyncMongoMockClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
USE_MOCK = os.getenv("USE_MOCK_MONGO", "true").lower() == "true"

client = None
db = None

async def connect_to_mongo():
    global client, db
    if USE_MOCK:
        client = AsyncMongoMockClient()
        print("Using Mock MongoDB")
    else:
        client = AsyncIOMotorClient(MONGO_URI)
        print("Using Real MongoDB")
    db = client.ai_assistant_db

async def close_mongo_connection():
    global client
    if client and not USE_MOCK:
        client.close()

def get_db():
    return db
