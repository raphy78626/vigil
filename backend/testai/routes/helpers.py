"""Shared helpers for route handlers."""

from __future__ import annotations

import json

from testai.models.journey import Journey
from testai.models.step import Step


def build_journey(journey_id: str, journey_data: dict) -> Journey:
    steps = [
        Step(
            id=s["id"],
            journey_id=journey_id,
            order=s["step_order"],
            description=s["description"],
            url=s.get("url", ""),
            action_type=s.get("action_type", ""),
            element_hint=s.get("element_hint"),
            selectors=json.loads(s.get("selectors", "{}")),
            event_ids=json.loads(s.get("event_ids", "[]")),
        )
        for s in journey_data.get("steps", [])
    ]
    return Journey(
        id=journey_data["id"],
        name=journey_data["name"],
        domain=journey_data.get("domain", ""),
        feature=journey_data.get("feature", ""),
        steps=steps,
        confidence=journey_data.get("confidence", 0),
        tags=json.loads(journey_data.get("tags", "[]")),
    )
