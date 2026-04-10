"""Runs API: /api/runs, /api/runs/stats, /api/runs/{id}/diagnostics."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from testai import state

router = APIRouter()


@router.get("/api/runs")
async def list_test_runs(journey_id: str = "", limit: int = 50):
    """List test run history, optionally filtered by journey."""
    runs = state.db.get_test_runs(journey_id or None, limit)
    return runs


@router.get("/api/runs/stats")
async def run_stats():
    """Aggregate pass/fail stats across all runs."""
    return state.db.get_run_stats()


@router.get("/api/runs/{run_id}/diagnostics")
async def get_run_diagnostics(run_id: str):
    """Return captured console errors, network failures, and API calls for a test run."""
    data = state.db.get_run_diagnostics(run_id)
    if not data:
        raise HTTPException(status_code=404, detail="Run not found")
    return data
