"""Daily Site Report routes (PX-02 Phase 3). Deliberately thin — all
business logic lives in services/daily_site_report_service.py.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from core.auth import get_current_user
from services import daily_site_report_service as svc

router = APIRouter(prefix="/api", tags=["daily-report"])


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@router.get("/projects/{project_id}/daily-report/today")
async def get_todays_report(project_id: str, client_safe: bool = False,
                            user: dict = Depends(get_current_user)):
    report = await svc.generate_daily_report(project_id, _today(), user=user)
    return svc.to_client_safe(report) if client_safe else report


@router.get("/projects/{project_id}/daily-report")
async def get_report_for_date(project_id: str, date: str = Query(...), client_safe: bool = False,
                              user: dict = Depends(get_current_user)):
    try:
        datetime.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be an ISO date, e.g. 2026-08-14")
    report = await svc.generate_daily_report(project_id, date, user=user)
    return svc.to_client_safe(report) if client_safe else report


@router.get("/projects/{project_id}/daily-report/export")
async def export_report(project_id: str, date: str = Query(...), format: str = "md",
                        client_safe: bool = False, user: dict = Depends(get_current_user)):
    if format != "md":
        raise HTTPException(status_code=400, detail="Only format=md is currently supported.")
    try:
        datetime.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be an ISO date, e.g. 2026-08-14")
    report = await svc.generate_daily_report(project_id, date, user=user)
    if client_safe:
        report = svc.to_client_safe(report)
    markdown = svc.render_markdown(report)
    return PlainTextResponse(content=markdown, media_type="text/markdown")
