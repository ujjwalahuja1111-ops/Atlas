"""Project Atlas — FastAPI wiring.

Engines and routes live in their own modules. This file only:
  • boots the app + middleware
  • wires routers
  • starts/stops the async Intelligence worker on lifespan
  • ensures Mongo indexes
"""
from contextlib import asynccontextmanager
import logging
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware

from core.db import ensure_indexes, close_client
from core.settings import PROJECT_NAME, APP_VERSION
from engines import intelligence_engine
from routes import auth as auth_routes
from routes import projects as projects_routes
from routes import events as events_routes
from routes import timeline as timeline_routes
from routes import raw_assets as raw_assets_routes
from routes import operational_items as operational_items_routes
from routes import ai_proposals as ai_proposals_routes
from routes import operational_center as operational_center_routes


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("atlas")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_indexes()
    await intelligence_engine.start_worker()
    logger.info(f"{PROJECT_NAME} {APP_VERSION} ready")
    yield
    await intelligence_engine.stop_worker()
    await close_client()


app = FastAPI(title=PROJECT_NAME, version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(projects_routes.router)
app.include_router(events_routes.router)
app.include_router(timeline_routes.router)
app.include_router(raw_assets_routes.router)
app.include_router(operational_items_routes.router)
app.include_router(ai_proposals_routes.router)
app.include_router(operational_center_routes.router)


@app.get("/api/")
async def root():
    return {"platform": PROJECT_NAME, "version": APP_VERSION, "status": "ok"}


# --- review artifact download (temporary; remove after handoff) ---
@app.get("/api/download/atlas_review.zip")
async def download_atlas_review():
    path = "/app/atlas_review.zip"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="archive not found")
    return FileResponse(
        path,
        media_type="application/zip",
        filename="atlas_review.zip",
    )
