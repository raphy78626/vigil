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
from testai.team.auth import require_auth

app = FastAPI(
    title="TestAI-Pro",
    version="1.0.0",
    description="AI-powered QA Automation Platform — observe, learn, and replay user journeys with self-healing test generation.",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.on_event("startup")
async def _startup() -> None:
    """Create the first admin account on first run (deferred from import time)."""
    try:
        generated_password = state.team_auth.ensure_admin_exists()
        if generated_password:
            print(
                f"\n  ⚠️  First run: admin account created.\n"
                f"  Username: admin\n"
                f"  Password: {generated_password}\n"
                f"  (saved to ~/.vigil/admin.passwd — change it after first login)\n"
            )
    except Exception as _e:
        import sys
        print(f"[warn] team auth startup: {_e}", file=sys.stderr)

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

from fastapi import Depends

_auth_dep = [Depends(require_auth)]

# Public routes — no auth required (login, register)
app.include_router(misc.public_router)

# All other routers require a valid Bearer token
app.include_router(misc.router, dependencies=_auth_dep)
app.include_router(ingest.router, dependencies=_auth_dep)
app.include_router(journeys.router, dependencies=_auth_dep)
app.include_router(replay.router, dependencies=_auth_dep)
app.include_router(runs.router, dependencies=_auth_dep)
app.include_router(reviews.router, dependencies=_auth_dep)
app.include_router(ai.router, dependencies=_auth_dep)
app.include_router(auth_routes.router, dependencies=_auth_dep)
app.include_router(settings.router, dependencies=_auth_dep)
app.include_router(export.router, dependencies=_auth_dep)
app.include_router(explorer.router, dependencies=_auth_dep)
app.include_router(explore_mutations.router, dependencies=_auth_dep)
app.include_router(audit.router, dependencies=_auth_dep)


def main():
    import uvicorn

    port = 8000
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        port = int(sys.argv[idx + 1])

    host = os.environ.get("VIGIL_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "::1", "localhost"):
        print(f"\n  ⚠️  VIGIL_HOST={host} — API is reachable on the network. Ensure auth is enabled.")

    print(f"\n  TestAI-Pro v1.0.0")
    print(f"  http://{host}:{port}")
    print(f"  API Docs: http://{host}:{port}/docs")
    print(f"  Database: {state.db.db_path}\n")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
