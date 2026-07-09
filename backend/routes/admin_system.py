"""Admin System Information (Sprint 4.2).

One read-only, admin-only endpoint giving an Administrator everything they'd
otherwise need Git Bash / curl / MongoDB / DevTools for: what build is
running, whether the backend and database are actually reachable, and
top-line counts. Deliberately a new, narrowly-scoped file rather than
folding this into routes/admin_users.py — system diagnostics and user
administration are different concerns that happen to share the same
admin-only gate, not the same feature.

Mirrors the `_require_admin` pattern already established in
routes/knowledge.py and routes/admin_users.py rather than inventing a new
one. Read-only: this file never writes to any collection.
"""
import os
import subprocess
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user
from core.settings import APP_VERSION, PROJECT_NAME, ROOT_DIR
from core.db import db

router = APIRouter(prefix="/api/admin", tags=["admin-system"])

# Recorded once at process import (effectively server boot time) — the
# closest honest proxy for "build date" available without a dedicated CI
# step that stamps a real build timestamp into the deployed image. If the
# deploy pipeline sets a BUILD_DATE env var, that's preferred and used
# instead (see system_info() below).
_STARTED_AT = datetime.now(timezone.utc).isoformat()


def _require_admin(user: dict) -> None:
    if user["role"] != "management":
        raise HTTPException(status_code=403, detail="System Information is admin-only")


def _detect_git_commit() -> str:
    """Best-effort short commit hash. Computed once at import time (not
    per-request) since it never changes for the life of a running process.
    Falls back to a GIT_COMMIT env var (for deploy pipelines that don't
    ship a .git directory into the built image), then to "unknown" — never
    raises, since this must never break the endpoint it backs.
    """
    try:
        repo_root = ROOT_DIR.parent  # backend/ -> repo root, where .git lives
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2, cwd=str(repo_root),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return os.environ.get("GIT_COMMIT", "unknown")


_GIT_COMMIT = _detect_git_commit()


@router.get("/system-info")
async def system_info(user: dict = Depends(get_current_user)):
    _require_admin(user)

    try:
        await db.command("ping")
        database_status = "connected"
    except Exception as e:
        database_status = f"error: {e}"

    total_users = await db.users.count_documents({})
    total_projects = await db.projects.count_documents({})
    total_sites = await db.sites.count_documents({})
    pending_approvals = await db.users.count_documents({"approval_status": "pending"})

    started = datetime.fromisoformat(_STARTED_AT)
    uptime_seconds = int((datetime.now(timezone.utc) - started).total_seconds())

    return {
        "project_name": PROJECT_NAME,
        "version": APP_VERSION,
        "git_commit": _GIT_COMMIT,
        "build_date": os.environ.get("BUILD_DATE", _STARTED_AT),
        "server_started_at": _STARTED_AT,
        "uptime_seconds": uptime_seconds,
        "backend_status": "healthy",
        "database_status": database_status,
        "total_users": total_users,
        "total_projects": total_projects,
        "total_sites": total_sites,
        "pending_approvals": pending_approvals,
    }
