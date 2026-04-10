"""Explore API: /api/journeys/{id}/explore — mutation-based QA variant runner."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from testai import state
from testai.exploration.mutations import (
    ExplorationVariant,
    classify_behavior,
    generate_variants,
    generate_variants_enhanced,
)
from testai.routes.helpers import build_journey
from testai.routes.replay import _stream_replay

router = APIRouter()


class ExploreRequest(BaseModel):
    base_url: str = ""
    env_vars: dict = {}
    headed: bool = False
    browser: str = "chromium"
    autoresearch: bool = True


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@router.get("/api/journeys/{journey_id}/explore/preview")
async def explore_preview(
    journey_id: str,
    autoresearch: bool = False,
    base_url: str = "",
):
    """Dry-run: return list of variants that would be tested."""
    journey_data = state.db.get_journey_with_steps(journey_id)
    if not journey_data:
        raise HTTPException(status_code=404, detail="Journey not found")
    journey = build_journey(journey_id, journey_data)

    research_info: dict = {}
    if autoresearch and base_url:
        variants, research_log = await generate_variants_enhanced(journey, base_url, state.llm)
        research_info = research_log
    else:
        variants = generate_variants(journey)

    return {
        "variants": [
            {
                "variant_id": v.variant_id,
                "description": v.mutation.description,
                "mutation_type": v.mutation.type,
                "expected_outcome": v.mutation.expected_outcome,
            }
            for v in variants
        ],
        **research_info,
    }


async def _stream_exploration(
    journey,
    base_url: str,
    headed: bool,
    env_vars: dict,
    browser: str,
    autoresearch: bool = True,
    llm=None,
) -> AsyncGenerator[str, None]:
    if autoresearch and base_url:
        yield _sse({"type": "research_start", "message": "Inspecting live form fields…"})
        variants, research_log = await generate_variants_enhanced(journey, base_url, llm)
        yield _sse({
            "type": "research_done",
            "dom_fields": research_log["dom_fields"],
            "constraint_mutations": research_log["constraint_mutations"],
            "llm_mutations": research_log["llm_mutations"],
            "total_variants": len(variants),
            "journey_name": journey.name,
        })
    else:
        variants = generate_variants(journey)
        yield _sse({"type": "start", "total_variants": len(variants), "journey_name": journey.name})

    total = len(variants)

    results = []

    for i, variant in enumerate(variants):
        yield _sse({
            "type": "variant_start",
            "variant_id": variant.variant_id,
            "description": variant.mutation.description,
            "mutation_type": variant.mutation.type,
            "index": i,
            "total": total,
        })

        t0 = time.monotonic()
        lines = []
        exit_code = -1

        # Happy-path (v0) uses auto_heal; mutations don't
        use_heal = variant.mutation.type == "none"

        async for raw in _stream_replay(
            variant.journey,
            base_url,
            headed=headed,
            env_vars=env_vars,
            auto_heal=use_heal,
            max_heal_attempts=1 if use_heal else 0,
            browser=browser,
        ):
            # raw is "data: {...}\n\n"
            data_line = raw[6:].strip()  # strip "data: "
            try:
                msg = json.loads(data_line)
            except Exception:
                continue

            if msg["type"] == "line":
                lines.append(msg.get("text", ""))
                yield raw  # forward to client
            elif msg["type"] == "done":
                exit_code = msg.get("exit_code", -1)
            elif msg["type"] == "screenshot":
                yield raw  # forward screenshots too

        behavior = classify_behavior(variant, exit_code, "\n".join(lines))
        duration_ms = int((time.monotonic() - t0) * 1000)
        passed = exit_code == 0

        result = {
            "variant_id": variant.variant_id,
            "description": variant.mutation.description,
            "mutation_type": variant.mutation.type,
            "exit_code": exit_code,
            "passed": passed,
            "app_behavior": behavior,
            "duration_ms": duration_ms,
        }
        results.append(result)

        yield _sse({
            "type": "variant_done",
            "variant_id": variant.variant_id,
            "passed": passed,
            "app_behavior": behavior,
            "duration_ms": duration_ms,
            "index": i,
            "total": total,
        })

    # Summarise
    bugs = sum(1 for r in results if r["app_behavior"] == "bug_accepted_invalid")
    correctly_rejected = sum(1 for r in results if r["app_behavior"] == "correctly_rejected")
    dep_confirmed = sum(1 for r in results if r["app_behavior"] == "dependency_confirmed")
    redundant = sum(1 for r in results if r["app_behavior"] == "step_redundant")

    exp_id = str(uuid.uuid4())[:8]
    finished_at = datetime.now(timezone.utc).isoformat()

    try:
        state.db.insert_exploration({
            "id": exp_id,
            "journey_id": journey.id,
            "base_url": base_url,
            "total_variants": total,
            "bugs_found": bugs,
            "results_json": json.dumps(results),
            "finished_at": finished_at,
        })
    except Exception as e:
        import sys
        print(f"[warn] failed to save exploration {exp_id}: {e}", file=sys.stderr)

    yield _sse({
        "type": "explore_done",
        "exploration_id": exp_id,
        "summary": {
            "total": total,
            "bugs_found": bugs,
            "correctly_rejected": correctly_rejected,
            "dependency_confirmed": dep_confirmed,
            "step_redundant": redundant,
        },
    })


@router.post("/api/journeys/{journey_id}/explore")
async def explore_journey(journey_id: str, req: ExploreRequest):
    """Run mutation-based QA exploration and stream results as SSE."""
    journey_data = state.db.get_journey_with_steps(journey_id)
    if not journey_data:
        raise HTTPException(status_code=404, detail="Journey not found")
    journey = build_journey(journey_id, journey_data)

    browser = req.browser if req.browser in state.SUPPORTED_BROWSERS else "chromium"

    return StreamingResponse(
        _stream_exploration(
            journey,
            req.base_url,
            req.headed,
            req.env_vars,
            browser,
            autoresearch=req.autoresearch,
            llm=state.llm,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
