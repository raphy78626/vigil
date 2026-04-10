"""Natural Language Query Engine: translates user questions into journey lookups."""

from __future__ import annotations

import json
from typing import Dict, List

from litellm import completion

from testai.storage.db import Database

QUERY_PROMPT = """You are a QA assistant. Translate the user's question into a structured query.

Domains available: {domains}
User question: "{question}"

Respond with JSON (no markdown):
{{
  "intent": "list_journeys|search|coverage_summary",
  "filters": {{
    "domain": null,
    "feature": null,
    "search_text": null
  }}
}}"""


class QueryEngine:
    def __init__(self, db: Database, model: str = "gpt-4o-mini"):
        self.db = db
        self.model = model

    def ask(self, question: str) -> str:
        domains = self.db.get_all_domains()
        prompt = QUERY_PROMPT.format(
            domains=", ".join(domains) if domains else "none yet",
            question=question,
        )

        response = completion(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]

        parsed = json.loads(raw)
        results = self._execute_query(parsed)
        return self._format_response(question, results)

    def _execute_query(self, parsed: Dict) -> List[Dict]:
        filters = parsed.get("filters", {})
        if filters.get("search_text"):
            return self.db.search_journeys(filters["search_text"])
        return self.db.get_journeys(
            domain=filters.get("domain"),
            feature=filters.get("feature"),
        )

    def _format_response(self, question: str, data: List[Dict]) -> str:
        if not data:
            return "No journeys found matching your query."
        lines = ["Found {0} journey(s):".format(len(data))]
        for r in data[:10]:
            lines.append("- {0} ({1} > {2}) [confidence: {3:.0%}]".format(
                r["name"], r.get("domain", "?"), r.get("feature", "?"), r.get("confidence", 0)))
        return "\n".join(lines)
