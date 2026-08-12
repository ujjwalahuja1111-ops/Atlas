"""Notification Inbox Foundation (PX-01A P2-09).

A genuinely new, small collection — explicitly permitted by this
task's own "new collections unless absolutely required for
notifications" carve-out, since nothing existing tracks "does this
user know about this yet." In-app only: no push, email, WhatsApp, or
background jobs, matching this task's own explicit scope.

Design discipline matching every other Atlas engine: this file only
creates and reads notification records. It does not duplicate any
business logic from the engines that trigger it — each trigger call
site passes in data (title, body, category, links) that engine already
computed for its own purpose (an assignment, a status change, a
payment event); this engine's only job is turning that into a durable,
per-user, markable-as-read record.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from core.db import db

NOTIFICATION_CATEGORIES = ("assignment", "approval", "clarification", "status_change", "commercial")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return f"ntf_{uuid.uuid4()}"


async def create_notification(*, user_id: str, category: str, title: str, body: str,
                              project_id: Optional[str] = None, entity_type: Optional[str] = None,
                              entity_id: Optional[str] = None) -> dict:
    """The one write path every trigger site calls. Never raises on a
    bad category — falls back to storing it as-is rather than blocking
    the real action (an assignment, a status change) that triggered
    it; a malformed notification is a much smaller problem than a
    failed assignment."""
    doc = {
        "id": _new_id(), "user_id": user_id, "category": category,
        "title": title, "body": body, "project_id": project_id,
        "entity_type": entity_type, "entity_id": entity_id,
        "read": False, "created_at": _now(),
    }
    await db.notifications.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def list_notifications(user_id: str, *, category: Optional[str] = None,
                             unread_only: bool = False, limit: int = 100) -> list[dict]:
    q: dict = {"user_id": user_id}
    if category and category != "all":
        q["category"] = category
    if unread_only:
        q["read"] = False
    return await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)


async def unread_count(user_id: str) -> int:
    return await db.notifications.count_documents({"user_id": user_id, "read": False})


async def mark_read(notification_id: str, *, user_id: str) -> Optional[dict]:
    """Scoped to the calling user — a notification belongs to exactly
    one inbox; marking someone else's notification read is a no-op,
    not an error, matching the low-stakes nature of this action."""
    await db.notifications.update_one(
        {"id": notification_id, "user_id": user_id}, {"$set": {"read": True, "read_at": _now()}})
    return await db.notifications.find_one({"id": notification_id, "user_id": user_id}, {"_id": 0})


async def mark_all_read(user_id: str, *, category: Optional[str] = None) -> int:
    q: dict = {"user_id": user_id, "read": False}
    if category and category != "all":
        q["category"] = category
    result = await db.notifications.update_many(q, {"$set": {"read": True, "read_at": _now()}})
    return result.modified_count if hasattr(result, "modified_count") else 0


async def notify_assignment(*, assignee_user_id: str, actor_name: str, item_title: str,
                            project_id: str, entity_type: str, entity_id: str,
                            is_reassignment: bool = False) -> None:
    verb = "reassigned" if is_reassignment else "assigned"
    await create_notification(
        user_id=assignee_user_id, category="assignment",
        title=f"You were {verb}: {item_title}",
        body=f"{actor_name} {verb} you to this.",
        project_id=project_id, entity_type=entity_type, entity_id=entity_id,
    )


async def notify_status_change(*, user_id: str, item_title: str, to_status: str,
                               project_id: str, entity_type: str, entity_id: str) -> None:
    await create_notification(
        user_id=user_id, category="status_change",
        title=f"{item_title} moved to {to_status.replace('_', ' ')}",
        body=f"Status changed to {to_status.replace('_', ' ')}.",
        project_id=project_id, entity_type=entity_type, entity_id=entity_id,
    )


async def notify_clarification_requested(*, user_id: str, item_title: str, note: str,
                                         project_id: str, entity_type: str, entity_id: str) -> None:
    await create_notification(
        user_id=user_id, category="clarification",
        title=f"Clarification needed: {item_title}",
        body=note[:200], project_id=project_id, entity_type=entity_type, entity_id=entity_id,
    )


async def notify_clarification_answered(*, user_id: str, item_title: str,
                                        project_id: str, entity_type: str, entity_id: str) -> None:
    await create_notification(
        user_id=user_id, category="clarification",
        title=f"Clarification answered: {item_title}",
        body="A response is now available.",
        project_id=project_id, entity_type=entity_type, entity_id=entity_id,
    )


async def notify_commercial(*, user_id: str, title: str, body: str,
                            project_id: str, entity_type: str, entity_id: str) -> None:
    await create_notification(
        user_id=user_id, category="commercial", title=title, body=body,
        project_id=project_id, entity_type=entity_type, entity_id=entity_id,
    )
