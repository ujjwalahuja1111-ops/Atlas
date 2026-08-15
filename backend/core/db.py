"""Single Mongo client + db handle shared by all engines.

Connection pool settings (DEV-02): a long-running process — most
visibly bootstrap.py's own multi-stage pipeline, which can hold this
client open across thousands of sequential operations — risks a
pooled connection sitting idle long enough for a network intermediary
(a corporate firewall, NAT, or MongoDB Atlas's own cloud
infrastructure) to close it before the client's next use of it. When
that happens, PyMongo/Motor's own retry machinery is what determines
whether the caller sees a transparent retry on a fresh connection or a
raw ConnectionResetError — so both settings below are set explicitly,
not left to library defaults that may vary by driver version or be
silently disabled by a connection string that doesn't request them.
See scripts/DEV02_ROOT_CAUSE.md for the full investigation this is
addressing.
"""
from motor.motor_asyncio import AsyncIOMotorClient
from .settings import MONGO_URL, DB_NAME

client = AsyncIOMotorClient(
    MONGO_URL,
    # Proactively recycle a pooled connection after 45s idle - safely
    # under common cloud/firewall idle-kill windows (MongoDB Atlas's
    # own load balancer, and most corporate NAT/firewall idle timeouts,
    # commonly sit at 60s or higher) so the client discards a
    # connection on its own schedule rather than discovering it was
    # already killed by something else on the next attempted use.
    maxIdleTimeMS=45000,
    # Explicit, not assumed from the driver's own default (which does
    # already default to True in modern PyMongo, but a connection
    # string or deployment topology can silently disable it - stated
    # here so it's never an accident whether a stale connection gets
    # transparently retried on a fresh one or surfaces as an error).
    retryReads=True,
    retryWrites=True,
)
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
    # V4 — Knowledge Engine (Sprint 4)
    await db.knowledge_items.create_index([("type", 1), ("archived_at", 1)])
    await db.knowledge_items.create_index("category_id")
    await db.knowledge_items.create_index("phase_id")
    await db.knowledge_items.create_index("tags")
    await db.knowledge_items.create_index("status")
    await db.knowledge_items.create_index("relationships.target_id")
    await db.knowledge_versions.create_index([("item_id", 1), ("version", -1)])
    # Sprint 4.1 — User Management foundation
    await db.users.create_index("approval_status")
    # Sprint 5 — Construction Workflow Engine
    await db.workflow_activities.create_index([("project_id", 1), ("order", 1)])
    await db.workflow_activities.create_index("knowledge_activity_id")
    # PX-03 Phase 4 Section 2 — payment idempotency, backing the
    # application-level check in record_payment() with a database-
    # level guarantee. Partial: only applies when idempotency_key is
    # actually set, so payments without one (every pre-existing
    # caller) are entirely unaffected.
    await db.payments.create_index(
        [("payment_request_id", 1), ("idempotency_key", 1)], unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
    )


async def close_client() -> None:
    client.close()
