"""Hierarchy Builder: organizes labeled journeys into a domain tree."""

from __future__ import annotations

import json
from typing import Dict, List

from litellm import completion

from testai.models.journey import Journey

HIERARCHY_PROMPT = """You are a QA architect. Given these discovered journeys, organize them into a coherent hierarchy.

## Discovered Journeys

{journey_list}

## Instructions

Respond with a JSON object (no markdown fences):

{{
  "domains": [
    {{
      "name": "Domain Name",
      "features": [
        {{
          "name": "Feature Name",
          "journeys": [
            {{
              "id": "journey-id",
              "is_variant_of": null,
              "is_duplicate_of": null
            }}
          ]
        }}
      ]
    }}
  ]
}}"""


class HierarchyBuilder:
    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model

    def organize(self, journeys: List[Journey]) -> Dict:
        if not journeys:
            return {"domains": []}

        if len(journeys) == 1:
            j = journeys[0]
            return {
                "domains": [{
                    "name": j.domain or "Uncategorized",
                    "features": [{
                        "name": j.feature or "General",
                        "journeys": [{"id": j.id, "is_variant_of": None, "is_duplicate_of": None}],
                    }],
                }]
            }

        journey_list = self._format_journeys(journeys)
        prompt = HIERARCHY_PROMPT.format(journey_list=journey_list)

        response = completion(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)

    def _format_journeys(self, journeys: List[Journey]) -> str:
        lines = []
        for j in journeys:
            steps_desc = "; ".join(s.description for s in j.steps[:5])
            lines.append(
                "- ID: {id}\n  Name: {name}\n  Domain: {domain}\n  Feature: {feature}\n  Steps: {steps}\n  Tags: {tags}".format(
                    id=j.id, name=j.name, domain=j.domain, feature=j.feature,
                    steps=steps_desc, tags=", ".join(j.tags)))
        return "\n\n".join(lines)
