"""Journey Labeler: uses LLM to name and categorize event flows."""

from __future__ import annotations

import json
import uuid
from typing import List

from litellm import completion

from testai.models.event import Event
from testai.models.journey import Journey
from testai.models.step import Step

LABELING_PROMPT = """You are a QA test analyst. Given a numbered sequence of web interactions captured from a QA tester's browser, analyze and label this functional journey.

## Captured Interactions

{event_summary}

## Instructions

Group the numbered events into logical steps. Each step may correspond to one or more consecutive events.

Respond with a JSON object (no markdown fences) matching this exact schema:

{{
  "name": "3-8 word journey name (e.g. 'Guest Checkout with Promo Code')",
  "domain": "Business domain (e.g. 'Payments', 'Authentication', 'User Management')",
  "feature": "Feature area (e.g. 'Checkout', 'Login', 'Profile Settings')",
  "steps": [
    {{
      "order": 1,
      "description": "Human-readable step description",
      "action_type": "navigate|click|fill_form|submit|verify",
      "element_hint": "What element was interacted with",
      "event_indices": [1, 2]
    }}
  ],
  "tags": ["tag1", "tag2"],
  "confidence": 0.85
}}

IMPORTANT: "event_indices" must list the 1-based event numbers from the captured interactions that belong to this step.
Every event number must appear in exactly one step. Do not skip any events.
Focus on the FUNCTIONAL INTENT, not the raw mechanics.

{vocabulary_hints}"""


class JourneyLabeler:
    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model

    def label(self, flow_events: List[Event], session_id: str = "", vocabulary_hints: str = "") -> Journey:
        event_summary = self._summarize_events(flow_events)
        hints_block = ""
        if vocabulary_hints:
            hints_block = (
                "\n## Learned Vocabulary (from human corrections)\n"
                + vocabulary_hints
                + "\nUse these as strong hints when assigning domain, feature, and name."
            )
        prompt = LABELING_PROMPT.format(
            event_summary=event_summary,
            vocabulary_hints=hints_block,
        )

        response = completion(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]

        data = json.loads(raw)

        steps = []
        for s in data.get("steps", []):
            indices = s.get("event_indices", [])
            mapped_ids = []
            for idx in indices:
                i = idx - 1  # 1-based to 0-based
                if 0 <= i < len(flow_events):
                    mapped_ids.append(flow_events[i].id)
            if not mapped_ids:
                mapped_ids = [flow_events[min(s["order"] - 1, len(flow_events) - 1)].id]
            steps.append(Step(
                id=str(uuid.uuid4()),
                order=s["order"],
                description=s["description"],
                action_type=s.get("action_type", ""),
                element_hint=s.get("element_hint"),
                event_ids=mapped_ids,
            ))

        return Journey(
            id=str(uuid.uuid4()),
            name=data["name"],
            domain=data.get("domain", ""),
            feature=data.get("feature", ""),
            steps=steps,
            confidence=data.get("confidence", 0.5),
            session_id=session_id,
            tags=data.get("tags", []),
        )

    def _summarize_events(self, events: List[Event]) -> str:
        lines = []
        for i, event in enumerate(events, 1):
            parts = ["{0}. [{1}] {2}".format(i, event.type.value, event.url)]
            if event.element:
                el = event.element
                parts.append("   Element: <{0}> {1}".format(
                    el.tag_name, el.selectors.text or el.selectors.css))
                if el.input_type:
                    parts.append("   Input type: {0}".format(el.input_type))
            if event.navigation:
                parts.append("   From: {0}".format(event.navigation.from_url))
                parts.append("   To: {0}".format(event.navigation.to_url))
            if event.page_title:
                parts.append("   Page: {0}".format(event.page_title))
            lines.append("\n".join(parts))
        return "\n\n".join(lines)
