"""TestAI-Pro API Server: AI-powered QA automation platform."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from testai import state
from testai.routes import (
    ingest, journeys, replay, runs, reviews, ai,
    auth_routes, settings, misc, export, explorer,
    explore_mutations, audit, helpers,
)

app = FastAPI(
    title="TestAI-Pro",
    version="1.0.0",
    description="AI-powered QA Automation Platform — observe, learn, and replay user journeys with self-healing test generation.",
    docs_url="/docs",
    redoc_url="/redoc",
)

_CORS_ORIGINS = [o.strip() for o in os.environ.get("VIGIL_CORS_ORIGINS", "").split(",") if o.strip()]
if not _CORS_ORIGINS:
    _CORS_ORIGINS = ["http://localhost:8000", "http://127.0.0.1:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

DASHBOARD_DIR = Path(__file__).parent.parent.parent / "dashboard"


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    index_path = DASHBOARD_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text()
    return "<h1>TestAI-Pro</h1><p>Dashboard not found.</p>"


if (DASHBOARD_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=DASHBOARD_DIR / "static"), name="static")

app.include_router(ingest.router)
app.include_router(journeys.router)
app.include_router(replay.router)
app.include_router(runs.router)
app.include_router(reviews.router)
app.include_router(ai.router)
app.include_router(auth_routes.router)
app.include_router(settings.router)
app.include_router(misc.router)
app.include_router(export.router)
app.include_router(explorer.router)
app.include_router(explore_mutations.router)
app.include_router(audit.router)


def main():
    import uvicorn

    port = 8000
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        port = int(sys.argv[idx + 1])

    print(f"\n  TestAI-Pro v1.0.0")
    print(f"  http://localhost:{port}")
    print(f"  API Docs: http://localhost:{port}/docs")
    print(f"  Database: {state.db.db_path}\n")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
