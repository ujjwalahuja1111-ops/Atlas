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


class SiteUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    image_url: Optional[str] = None


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


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, user: dict = Depends(get_current_user)):
    """Hard-delete only if the project has no dependent sites (archived or
    not). Returns 409 with the blocking counts otherwise; the UI should
    offer archive as the fallback path. Mirrors DELETE /sites/{id} exactly.
    """
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Supervisors cannot delete projects")
    existing = await memory_engine.get_project(project_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")
    refs = await memory_engine.project_reference_counts(project_id)
    if any(refs.values()):
        raise HTTPException(status_code=409, detail={
            "message": "Project has dependent sites — archive instead.",
            "refs": refs,
        })
    ok = await memory_engine.delete_project(project_id)
    return {"deleted": ok, "id": project_id}


@router.get("/sites")
async def list_sites(project_id: Optional[str] = None,
                     include_archived: bool = False,
                     user: dict = Depends(get_current_user)):
    return await memory_engine.list_sites(project_id, include_archived=include_archived)


@router.post("/sites")
async def create_site(req: SiteCreate, user: dict = Depends(get_current_user)):
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Supervisors cannot create sites")
    return await memory_engine.insert_site(
        project_id=req.project_id, name=req.name, location=req.location, image_url=req.image_url
    )


@router.patch("/sites/{site_id}")
async def update_site(site_id: str, req: SiteUpdate,
                      user: dict = Depends(get_current_user)):
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Supervisors cannot edit sites")
    existing = await memory_engine.get_site(site_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Site not found")
    return await memory_engine.update_site(
        site_id, name=req.name, location=req.location, image_url=req.image_url,
    )


@router.post("/sites/{site_id}/archive")
async def archive_site(site_id: str, user: dict = Depends(get_current_user)):
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Supervisors cannot archive sites")
    existing = await memory_engine.get_site(site_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Site not found")
    return await memory_engine.archive_site(site_id)


@router.post("/sites/{site_id}/unarchive")
async def unarchive_site(site_id: str, user: dict = Depends(get_current_user)):
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Supervisors cannot unarchive sites")
    existing = await memory_engine.get_site(site_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Site not found")
    return await memory_engine.unarchive_site(site_id)


@router.delete("/sites/{site_id}")
async def delete_site(site_id: str, user: dict = Depends(get_current_user)):
    """Hard-delete only if the site has no dependent records.

    Returns 409 with the blocking counts otherwise; the UI should offer
    archive as the fallback path.
    """
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Supervisors cannot delete sites")
    existing = await memory_engine.get_site(site_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Site not found")
    refs = await memory_engine.site_reference_counts(site_id)
    if any(refs.values()):
        raise HTTPException(status_code=409, detail={
            "message": "Site has dependent records — archive instead.",
            "refs": refs,
        })
    ok = await memory_engine.delete_site(site_id)
    return {"deleted": ok, "id": site_id}


@router.get("/projects/{project_id}/summary")
async def project_summary(project_id: str, user: dict = Depends(get_current_user)):
    """Sprint-2 dashboard tile for a single project.

    active_sites: sites not archived under this project.
    open_tasks:   operational items whose status is not in a terminal bucket.
    pending_material_requests / pending_labour_requests: category-scoped subsets.
    """
    from core.db import db

    project = await memory_engine.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    active_sites = await db.sites.count_documents({
        "project_id": project_id, "archived_at": None,
    })
    total_sites = await db.sites.count_documents({"project_id": project_id})

    open_statuses_exclude = ["closed", "verified", "archived", "cancelled", "duplicate"]
    base_q = {
        "project_id": project_id,
        "status": {"$nin": open_statuses_exclude},
    }
    open_tasks = await db.operational_items.count_documents(base_q)
    pending_material = await db.operational_items.count_documents({
        **base_q, "category": "material_requirement",
    })
    pending_labour = await db.operational_items.count_documents({
        **base_q, "category": "labour_requirement",
    })

    return {
        "project": {"id": project["id"], "name": project["name"],
                    "code": project.get("code"), "location": project.get("location")},
        "active_sites": active_sites,
        "total_sites": total_sites,
        "open_tasks": open_tasks,
        "pending_material_requests": pending_material,
        "pending_labour_requests": pending_labour,
    }


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
