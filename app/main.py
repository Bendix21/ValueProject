import asyncio
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_jobs import router as jobs_router
from app.config import get_settings
from app.db import jobs_repo
from app.db.checkpointer import get_checkpointer
from app.graph.build import build_graph
from app.observability import init_tracing

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_tracing(settings.lmnr_project_api_key)
    await jobs_repo.setup(settings.db_url)
    app.state.running_tasks = {}
    async with get_checkpointer(settings) as checkpointer:
        app.state.graph = build_graph(checkpointer)
        app.state.settings = settings
        yield


app = FastAPI(title="QA Swarm Autonomous", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in get_settings().cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(jobs_router)

if os.path.isdir(get_settings().screenshot_root):
    app.mount(
        "/screenshots", StaticFiles(directory=get_settings().screenshot_root), name="screenshots"
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
