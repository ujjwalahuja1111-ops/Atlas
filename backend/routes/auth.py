"""Auth routes."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Literal
from core.auth import create_token, get_current_user
from engines import memory_engine

router = APIRouter(prefix="/api", tags=["auth"])

Role = Literal["supervisor", "coordinator", "management"]


class LoginRequest(BaseModel):
    phone: str
    name: str
    role: Role = "supervisor"


@router.post("/auth/login")
async def login(req: LoginRequest):
    phone = req.phone.strip()
    if len(phone) < 6:
        raise HTTPException(status_code=400, detail="Invalid phone")
    user = await memory_engine.upsert_user(phone=phone, name=req.name.strip() or "Site User", role=req.role)
    return {"token": create_token(user["id"]), "user": user}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user
