"""Audit API: /api/audit — AI-powered site quality assessment."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from testai import state

router = APIRouter()


class AuditRequest(BaseModel):
    url: str
    depth: int = 1


class AuditStatusResponse(BaseModel):
    status: str
    url: str
    result: Optional[dict] = None
    error: Optional[str] = None


@router.post("/api/audit")
async def run_audit(req: AuditRequest):
    """Run an AI-powered site quality audit on the given URL."""
    if not req.url or not req.url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    from testai.audit.site_audit import SiteAuditor

    auditor = SiteAuditor(llm_provider=state.llm)

    try:
        result = await auditor.audit(req.url, depth=req.depth)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audit failed: {str(e)[:300]}")

    if result.error and not result.llm_review:
        return {
            "status": "error",
            "url": req.url,
            "error": result.error,
        }

    return {
        "status": "ok",
        "url": req.url,
        "result": result.to_dict(),
    }


@router.get("/api/runs/{run_id}/performance")
async def get_run_performance(run_id: str):
    """Get performance telemetry (step timings + web vitals) for a test run."""
    row = state.db.conn.execute(
        "SELECT step_timings, web_vitals, duration_ms, total_steps FROM test_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")

    row = dict(row)
    step_timings = json.loads(row.get("step_timings") or "{}")
    web_vitals = json.loads(row.get("web_vitals") or "{}")

    return {
        "run_id": run_id,
        "duration_ms": row.get("duration_ms", 0),
        "total_steps": row.get("total_steps", 0),
        "step_timings": step_timings,
        "web_vitals": web_vitals,
    }


@router.get("/api/journeys/{journey_id}/performance")
async def get_journey_performance(journey_id: str, limit: int = 10):
    """Get performance telemetry across recent runs for a journey."""
    rows = state.db.conn.execute(
        """SELECT id, passed, duration_ms, total_steps, step_timings, web_vitals, started_at
           FROM test_runs WHERE journey_id = ? ORDER BY started_at DESC LIMIT ?""",
        (journey_id, limit),
    ).fetchall()

    runs = []
    for r in rows:
        r = dict(r)
        runs.append({
            "run_id": r["id"],
            "passed": bool(r["passed"]),
            "duration_ms": r["duration_ms"],
            "total_steps": r["total_steps"],
            "step_timings": json.loads(r.get("step_timings") or "{}"),
            "web_vitals": json.loads(r.get("web_vitals") or "{}"),
            "started_at": r["started_at"],
        })

    return {"journey_id": journey_id, "runs": runs}
