"""Explorer API: /api/explorer/*."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from testai import state
from testai.auth import _domain_from_url
from testai.models.journey import Journey
from testai.models.step import Step

router = APIRouter()

_active_explorers: dict = {}


class ExplorerStartRequest(BaseModel):
    base_url: str
    strategy: str = "bfs"
    max_pages: int = 30
    max_time_minutes: int = 10
    headed: bool = True
    include_patterns: List[str] = []
    exclude_patterns: List[str] = []
    skills: List[str] = ["curious_explorer"]


class SaveJourneysRequest(BaseModel):
    journey_indices: List[int] = []


@router.post("/api/explorer/start")
async def start_explorer(req: ExplorerStartRequest):
    """Start an AI Explorer session. Returns SSE stream of progress events."""
    from testai.explorer.agent import ExplorerAgent, ExplorerConfig

    config = ExplorerConfig(
        base_url=req.base_url,
        strategy=req.strategy,
        max_pages=req.max_pages,
        max_time_minutes=req.max_time_minutes,
        auth_domain=_domain_from_url(req.base_url),
        headed=req.headed,
        include_patterns=req.include_patterns,
        exclude_patterns=req.exclude_patterns,
        skills=req.skills,
    )
    agent = ExplorerAgent(config)
    _active_explorers[agent.session_id] = agent

    session_data = {
        "id": agent.session_id,
        "base_url": req.base_url,
        "strategy": req.strategy,
        "status": "running",
        "pages_visited": 0,
        "flows_discovered": 0,
        "config_json": json.dumps({
            "max_pages": req.max_pages,
            "max_time_minutes": req.max_time_minutes,
            "headed": req.headed,
        }),
        "results_json": "{}",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    try:
        state.db.insert_explorer_session(session_data)
    except Exception as _e:
        import sys
        print(f"[warn] failed to persist explorer session: {_e}", file=sys.stderr)

    async def _stream():
        last_result = None
        try:
            async for event in agent.run():
                event_type = event.get("type", "unknown")
                yield f"data: {json.dumps(event)}\n\n"

                if event_type == "done":
                    last_result = event
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)[:300]})}\n\n"
        finally:
            _active_explorers.pop(agent.session_id, None)
            try:
                updates = {"status": "completed", "finished_at": datetime.now(timezone.utc).isoformat()}
                if last_result:
                    updates["pages_visited"] = last_result.get("pages_visited", 0)
                    updates["flows_discovered"] = len(last_result.get("journeys", []))
                    updates["results_json"] = json.dumps(last_result)
                state.db.update_explorer_session(agent.session_id, updates)
            except Exception as _e:
                import sys
                print(f"[warn] failed to update explorer session: {_e}", file=sys.stderr)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/explorer/stop/{session_id}")
async def stop_explorer(session_id: str):
    """Stop a running exploration session."""
    agent = _active_explorers.get(session_id)
    if not agent:
        raise HTTPException(status_code=404, detail="No active session with that ID")
    agent.request_stop()
    return {"ok": True, "session_id": session_id}


@router.get("/api/explorer/sessions")
async def list_explorer_sessions(limit: int = 20):
    """List past exploration sessions."""
    return state.db.get_explorer_sessions(limit)


@router.get("/api/explorer/results/{session_id}")
async def get_explorer_results(session_id: str):
    """Get results from a completed exploration session."""
    session = state.db.get_explorer_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    results = json.loads(session.get("results_json", "{}"))
    return {
        "session": {k: v for k, v in session.items() if k != "results_json"},
        "results": results,
    }


@router.post("/api/explorer/results/{session_id}/save")
async def save_explorer_journeys(session_id: str, req: SaveJourneysRequest):
    """Save discovered journeys from an exploration session to the main DB."""
    session = state.db.get_explorer_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    results = json.loads(session.get("results_json", "{}"))
    journeys_data = results.get("journeys", [])

    if not journeys_data:
        raise HTTPException(status_code=400, detail="No journeys found in session results")

    indices = req.journey_indices if req.journey_indices else list(range(len(journeys_data)))
    saved = []

    for idx in indices:
        if idx < 0 or idx >= len(journeys_data):
            continue
        jdata = journeys_data[idx]

        journey_id = str(uuid.uuid4())[:8]
        domain = _domain_from_url(session["base_url"])

        steps = []
        for i, s in enumerate(jdata.get("steps", [])):
            step_id = f"{journey_id}_s{i}"
            steps.append(
                Step(
                    id=step_id,
                    journey_id=journey_id,
                    order=i + 1,
                    description=s.get("description", ""),
                    url=s.get("url", ""),
                    action_type=s.get("action_type", "click"),
                    element_hint=s.get("element_hint"),
                    selectors=s.get("selectors", {}),
                )
            )

        journey = Journey(
            id=journey_id,
            name=jdata.get("name", f"Explorer Journey {idx+1}"),
            domain=domain,
            feature="explorer",
            steps=steps,
            confidence=0.7,
            discovered_by="ai-explorer",
            tags=["explorer", "auto-discovered"],
        )
        state.db.insert_journey(journey)
        saved.append({"id": journey_id, "name": journey.name, "steps": len(steps)})

    return {"ok": True, "saved": saved, "count": len(saved)}


class ExpandRequest(BaseModel):
    max_pages: int = 20
    max_time_minutes: int = 8
    headed: bool = True
    skills: List[str] = ["flow_expander", "edge_case_hunter", "workflow_completionist"]


@router.post("/api/journeys/{journey_id}/expand")
async def expand_journey(journey_id: str, req: ExpandRequest):
    """Seed-based journey expansion: discover related flows from a known journey."""
    from testai.explorer.agent import expand_from_journey

    journey_data = state.db.get_journey_with_steps(journey_id)
    if not journey_data:
        raise HTTPException(status_code=404, detail="Journey not found")

    config_overrides = {
        "max_pages": req.max_pages,
        "max_time_minutes": req.max_time_minutes,
        "headed": req.headed,
        "skills": req.skills,
    }

    async def _stream():
        last_result = None
        try:
            async for event in expand_from_journey(journey_data, config_overrides):
                event_type = event.get("type", "unknown")
                yield f"data: {json.dumps(event)}\n\n"
                if event_type == "done":
                    last_result = event
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)[:300]})}\n\n"
        finally:
            if last_result:
                try:
                    session_data = {
                        "id": last_result.get("session_id", str(uuid.uuid4())),
                        "base_url": journey_data.get("domain", ""),
                        "strategy": "seed_expansion",
                        "status": "completed",
                        "pages_visited": last_result.get("pages_visited", 0),
                        "flows_discovered": len(last_result.get("journeys", [])),
                        "config_json": json.dumps({"seed_journey_id": journey_id}),
                        "results_json": json.dumps(last_result),
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    }
                    state.db.insert_explorer_session(session_data)
                except Exception:
                    pass

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/explorer/skills")
async def get_explorer_skills():
    """List all available QA skills for the explorer."""
    from testai.explorer.skills import list_skills, list_bundles

    return {"skills": list_skills(), "bundles": list_bundles()}
