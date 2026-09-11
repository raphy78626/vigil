"""Ingest API: /api/ingest, /api/ingest/file, /ws/events."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from collections import defaultdict
from pathlib import Path
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect, Header, Request
from pydantic import BaseModel

from testai import state
from testai.team.auth import require_auth

router = APIRouter()

_rate_buckets: dict = defaultdict(lambda: {"count": 0, "window_start": 0.0})
_RATE_LIMIT_INGEST = int(os.environ.get("VIGIL_INGEST_RATE_LIMIT", "60"))
_INGEST_TOKEN = os.environ.get("VIGIL_INGEST_TOKEN", "")
_ws_event_buffers: dict[str, list] = {}


def _check_rate_limit(client_ip: str, limit: int = _RATE_LIMIT_INGEST) -> None:
    now = time.time()
    bucket = _rate_buckets[client_ip]
    if now - bucket["window_start"] >= 60:
        bucket["count"] = 0
        bucket["window_start"] = now
    bucket["count"] += 1
    if bucket["count"] > limit:
        raise HTTPException(status_code=429, detail="Too many requests. Slow down.")


def _verify_ingest_token(authorization: Optional[str] = None) -> None:
    if not _INGEST_TOKEN:
        return
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token != _INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing ingest token.")


def _auto_version_journeys(journeys):
    if not journeys:
        return
    for j in journeys:
        jid = j.id if hasattr(j, "id") else j.get("id", "")
        if jid:
            try:
                state.db.record_journey_version(jid)
            except Exception as _e:
                print(f"[warn] version snapshot for {jid}: {_e}", file=sys.stderr)


async def _cluster_events_async(events: list) -> int:
    loop = asyncio.get_event_loop()

    def _do_cluster():
        import tempfile as _tf

        tmp = Path(_tf.mktemp(suffix=".json"))
        tmp.write_text(json.dumps(events))
        try:
            from testai.cluster.pipeline_local import run_pipeline_local

            journeys = run_pipeline_local(str(tmp), db_path=str(state.db.db_path), verbose=False)
            _auto_version_journeys(journeys)
            return len(journeys) if journeys else 0
        finally:
            tmp.unlink(missing_ok=True)

    return await loop.run_in_executor(None, _do_cluster)


class IngestRequest(BaseModel):
    events: List[dict]
    use_llm: bool = False
    model: str = "gpt-4o-mini"


@router.post("/api/ingest")
async def ingest_events(req: IngestRequest, request: Request, authorization: Optional[str] = Header(default=None)):
    """Receive events from the extension and run clustering."""
    _verify_ingest_token(authorization)
    _check_rate_limit(request.client.host if request.client else "unknown")
    import tempfile

    tmp = Path(tempfile.mktemp(suffix=".json"))
    tmp.write_text(json.dumps(req.events))

    try:
        if req.use_llm:
            from testai.cluster.pipeline import run_pipeline

            journeys = run_pipeline(str(tmp), model=req.model, db_path=str(state.db.db_path), verbose=False)
        else:
            from testai.cluster.pipeline_local import run_pipeline_local

            journeys = run_pipeline_local(str(tmp), db_path=str(state.db.db_path), verbose=False)

        _auto_version_journeys(journeys)
        return {
            "status": "ok",
            "journeys_created": len(journeys) if journeys else 0,
        }
    except Exception:
        raise
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/api/ingest/file")
async def ingest_file(file: UploadFile = File(...), use_llm: bool = False, _payload: dict = Depends(require_auth)):
    """Upload an exported JSON file from the extension."""
    content = await file.read()
    events = json.loads(content)

    import tempfile

    tmp = Path(tempfile.mktemp(suffix=".json"))
    tmp.write_text(json.dumps(events))

    try:
        if use_llm:
            from testai.cluster.pipeline import run_pipeline

            journeys = run_pipeline(str(tmp), db_path=str(state.db.db_path), verbose=False)
        else:
            from testai.cluster.pipeline_local import run_pipeline_local

            journeys = run_pipeline_local(str(tmp), db_path=str(state.db.db_path), verbose=False)

        _auto_version_journeys(journeys)
        return {
            "status": "ok",
            "events_received": len(events),
            "journeys_created": len(journeys) if journeys else 0,
        }
    finally:
        tmp.unlink(missing_ok=True)


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket, token: Optional[str] = None):
    """Real-time event streaming from the extension.

    Auth: pass token as a query-string parameter (?token=<bearer_token>)
    or send an {"action": "auth", "token": "<bearer_token>"} message first.
    """
    await websocket.accept()

    # Prefer query-param auth; fall back to first-message auth
    payload = None
    if token:
        payload = state.team_auth.validate_token(token)
    if not payload:
        # Also accept the ingest token for backward compatibility
        if _INGEST_TOKEN and token == _INGEST_TOKEN:
            payload = {"role": "member"}  # treat as authenticated member
        else:
            # Wait for an auth message before allowing events
            try:
                auth_msg = await websocket.receive_json()
                if auth_msg.get("action") == "auth":
                    t = auth_msg.get("token", "")
                    payload = state.team_auth.validate_token(t)
                    if not payload and _INGEST_TOKEN and t == _INGEST_TOKEN:
                        payload = {"role": "member"}
            except Exception:
                pass

    if not payload:
        await websocket.send_json({"type": "error", "detail": "Authentication required."})
        await websocket.close(code=4001)
        return

    session_id = str(uuid.uuid4())
    _ws_event_buffers[session_id] = []

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action", "event")

            if action == "event":
                _ws_event_buffers[session_id].append(data.get("event", data))
                await websocket.send_json({
                    "type": "ack",
                    "count": len(_ws_event_buffers[session_id]),
                })

            elif action == "flush":
                events = _ws_event_buffers.get(session_id, [])
                if events:
                    result = await _cluster_events_async(events)
                    await websocket.send_json({
                        "type": "clustered",
                        "journeys_created": result,
                        "events_processed": len(events),
                    })
                    _ws_event_buffers[session_id] = []
                else:
                    await websocket.send_json({"type": "clustered", "journeys_created": 0, "events_processed": 0})

    except WebSocketDisconnect:
        events = _ws_event_buffers.pop(session_id, [])
        if events:
            await _cluster_events_async(events)
