"""Journeys API: CRUD, versions, label, merge, duplicate, suites."""

from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from testai import state

router = APIRouter()


class LabelUpdateRequest(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    feature: Optional[str] = None
    tags: Optional[List[str]] = None


class MergeRequest(BaseModel):
    journey_id_a: str
    journey_id_b: str


@router.get("/api/journeys")
async def list_journeys(domain: Optional[str] = None, feature: Optional[str] = None, limit: int = 50):
    return state.db.get_journeys(domain=domain, feature=feature, limit=limit)


@router.get("/api/journeys/{journey_id}")
async def get_journey(journey_id: str):
    journey = state.db.get_journey_with_steps(journey_id)
    if not journey:
        raise HTTPException(status_code=404, detail="Journey not found")
    return journey


@router.get("/api/journeys/{journey_id}/versions")
async def journey_versions(journey_id: str):
    versions = state.db.get_journey_versions(journey_id)
    for v in versions:
        if v.get("diff_json"):
            v["diff"] = json.loads(v["diff_json"])
        else:
            v["diff"] = None
        v.pop("steps_json", None)
        v.pop("diff_json", None)
    return versions


@router.post("/api/journeys/{journey_id}/version")
async def snapshot_journey_version(journey_id: str):
    result = state.db.record_journey_version(journey_id)
    if result is None:
        return {"message": "No changes detected since last version"}
    return {"message": f"Version {result['version']} recorded", "diff": result.get("diff")}


@router.patch("/api/journeys/{journey_id}/label")
async def update_journey_label(journey_id: str, req: LabelUpdateRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    result = state.db.update_journey_label(journey_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="Journey not found")
    return {"ok": True, "journey": result}


@router.post("/api/journeys/find-duplicates")
async def find_duplicates(threshold: float = 0.65):
    """Find duplicate journey pairs across all recorded journeys."""
    journeys_raw = state.db.get_journeys(limit=1000)
    journeys = []
    for j in journeys_raw:
        full = state.db.get_journey_with_steps(j["id"])
        if full:
            journeys.append(full)
    pairs = state.journey_merger.find_duplicates(journeys)
    return {
        "duplicates": [
            {
                "journey_a": p[0]["name"],
                "journey_b": p[1]["name"],
                "id_a": p[0]["id"],
                "id_b": p[1]["id"],
                "similarity": p[2],
            }
            for p in pairs
        ],
    }


@router.post("/api/journeys/merge")
async def merge_journeys(req: MergeRequest):
    """Merge two similar journeys into one canonical journey."""
    j1 = state.db.get_journey_with_steps(req.journey_id_a)
    j2 = state.db.get_journey_with_steps(req.journey_id_b)
    if not j1 or not j2:
        raise HTTPException(status_code=404, detail="One or both journeys not found")
    merged = state.journey_merger.merge(j1, j2)
    return {"ok": True, "merged_journey": merged}


@router.post("/api/journeys/auto-merge")
async def auto_merge():
    """Automatically find and merge all duplicate journeys."""
    journeys_raw = state.db.get_journeys(limit=1000)
    journeys = []
    for j in journeys_raw:
        full = state.db.get_journey_with_steps(j["id"])
        if full:
            journeys.append(full)
    report = state.journey_merger.auto_merge(journeys)
    return report


@router.get("/api/suites/generate")
async def generate_suites():
    """Auto-generate test suites from recorded journeys."""
    journeys_raw = state.db.get_journeys(limit=1000)
    journeys = []
    for j in journeys_raw:
        journeys.append(j)
    suites = state.suite_generator.generate(journeys)
    return {"suites": suites, "total_suites": len(suites)}


@router.get("/api/suites/coverage-gaps")
async def coverage_gaps():
    """Identify feature areas with no test coverage."""
    journeys_raw = state.db.get_journeys(limit=1000)
    gaps = state.suite_generator.suggest_missing(journeys_raw)
    return {"gaps": gaps, "total_gaps": len(gaps)}
