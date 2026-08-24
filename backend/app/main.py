import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.scheduler.scheduler import reaper_loop
from app.api import projects, jobs, workers, attempts, webhooks, websocket

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

_reaper_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _reaper_task
    init_db()
    _reaper_task = asyncio.create_task(reaper_loop())
    yield
    if _reaper_task:
        _reaper_task.cancel()


app = FastAPI(
    title="Fault-Tolerant CI System",
    description="A CI platform with independent workers, Docker-isolated "
                 "job execution, at-least-once fault-tolerant scheduling, "
                 "and an integrated AI failure analyzer.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(jobs.router)
app.include_router(workers.router)
app.include_router(attempts.router)
app.include_router(webhooks.router)
app.include_router(websocket.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
