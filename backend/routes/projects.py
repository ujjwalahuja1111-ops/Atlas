"""Projects and sites routes. Preserves the Project → Site hierarchy."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.auth import get_current_user
from engines import memory_engine

router = APIRouter(prefix="/api", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    code: str = ""
    location: str = ""
    image_url: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    location: Optional[str] = None
    image_url: Optional[str] = None


class SiteCreate(BaseModel):
    project_id: str
    name: str
    location: str = ""
    image_url: str = ""


@router.get("/projects")
async def list_projects(include_archived: bool = False,
                        user: dict = Depends(get_current_user)):
    return await memory_engine.list_projects(include_archived=include_archived)


@router.post("/projects")
async def create_project(req: ProjectCreate, user: dict = Depends(get_current_user)):
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Supervisors cannot create projects")
    return await memory_engine.insert_project(
        name=req.name, code=req.code, location=req.location, image_url=req.image_url
    )


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, req: ProjectUpdate,
                         user: dict = Depends(get_current_user)):
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Supervisors cannot edit projects")
    existing = await memory_engine.get_project(project_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")
    return await memory_engine.update_project(
        project_id,
        name=req.name, code=req.code,
        location=req.location, image_url=req.image_url,
    )


@router.post("/projects/{project_id}/archive")
async def archive_project(project_id: str, user: dict = Depends(get_current_user)):
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Supervisors cannot archive projects")
    existing = await memory_engine.get_project(project_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")
    return await memory_engine.archive_project(project_id)


@router.post("/projects/{project_id}/unarchive")
async def unarchive_project(project_id: str, user: dict = Depends(get_current_user)):
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Supervisors cannot unarchive projects")
    existing = await memory_engine.get_project(project_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")
    return await memory_engine.unarchive_project(project_id)


@router.get("/sites")
async def list_sites(project_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    return await memory_engine.list_sites(project_id)


@router.post("/sites")
async def create_site(req: SiteCreate, user: dict = Depends(get_current_user)):
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Supervisors cannot create sites")
    return await memory_engine.insert_site(
        project_id=req.project_id, name=req.name, location=req.location, image_url=req.image_url
    )


@router.post("/projects/seed")
async def seed_demo(user: dict = Depends(get_current_user)):
    """Seed one demo project + 3 sites under it. Idempotent."""
    existing_projects = await memory_engine.list_projects()
    if existing_projects:
        existing_sites = await memory_engine.list_sites()
        return {"seeded": False, "projects": len(existing_projects), "sites": len(existing_sites)}

    project = await memory_engine.insert_project(
        name="Atlas Pilot Construction",
        code="ATL-01",
        location="NCR, India",
        image_url="https://images.pexels.com/photos/17770160/pexels-photo-17770160.jpeg",
    )
    demos = [
        ("Tower A — Sector 62", "Noida, UP",
         "https://images.pexels.com/photos/13758319/pexels-photo-13758319.jpeg"),
        ("Metro Line Extension", "Gurgaon, HR",
         "https://images.pexels.com/photos/6082416/pexels-photo-6082416.jpeg"),
        ("Residency Block C", "Faridabad, HR",
         "https://images.pexels.com/photos/17770160/pexels-photo-17770160.jpeg"),
    ]
    for name, loc, img in demos:
        await memory_engine.insert_site(project_id=project["id"], name=name, location=loc, image_url=img)
    return {"seeded": True, "project_id": project["id"], "sites": len(demos)}
