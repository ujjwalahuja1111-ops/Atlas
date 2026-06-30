"""Single Mongo client + db handle shared by all engines."""
from motor.motor_asyncio import AsyncIOMotorClient
from .settings import MONGO_URL, DB_NAME

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


async def ensure_indexes() -> None:
    await db.users.create_index("phone", unique=True)
    await db.projects.create_index("created_at")
    await db.sites.create_index([("project_id", 1), ("created_at", -1)])
    await db.events.create_index([("site_id", 1), ("server_created_at", -1)])
    await db.events.create_index("ai_status")
    await db.raw_assets.create_index("event_id")
    await db.ai_analyses.create_index("event_id", unique=True)
    await db.corrections.create_index([("original_event_id", 1), ("created_at", -1)])
    await db.prompt_versions.create_index([("name", 1), ("version", 1)], unique=True)
    # V3
    await db.operational_items.create_index([("site_id", 1), ("status", 1), ("priority", 1)])
    await db.operational_items.create_index("last_updated_at")
    await db.operational_items.create_index("assigned_to_user_id")
    await db.operational_events.create_index([("operational_item_id", 1), ("created_at", 1)])
    await db.ai_proposals.create_index([("event_id", 1), ("decision", 1)])
    await db.ai_proposals.create_index("site_id")


async def close_client() -> None:
    client.close()
