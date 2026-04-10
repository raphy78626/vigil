"""Multi-session journey merger — detect and merge duplicate journeys from different QA sessions.

When two QA engineers independently test the same flow (e.g., checkout), this module
detects the similarity and merges them into a single canonical journey, keeping
the best selectors and most comprehensive step sequence.
"""

from __future__ import annotations

import json
import uuid
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple


def _step_signature(step: Dict) -> str:
    """Normalize a step into a comparable signature."""
    action = (step.get("action_type") or "click").lower()
    desc = (step.get("description") or "").lower().strip()
    url_path = ""
    if step.get("url"):
        from urllib.parse import urlparse
        url_path = urlparse(step["url"]).path
    return f"{action}|{url_path}|{desc[:60]}"


def _journey_signature(steps: List[Dict]) -> List[str]:
    return [_step_signature(s) for s in steps]


class JourneyMerger:
    def __init__(self, similarity_threshold: float = 0.65):
        self.threshold = similarity_threshold

    def find_duplicates(self, journeys: List[Dict]) -> List[Tuple[Dict, Dict, float]]:
        """Find pairs of journeys that are likely duplicates."""
        pairs = []
        sigs = [(j, _journey_signature(j.get("steps", []))) for j in journeys]

        for i in range(len(sigs)):
            for k in range(i + 1, len(sigs)):
                j1, sig1 = sigs[i]
                j2, sig2 = sigs[k]

                if not sig1 or not sig2:
                    continue

                sim = self._similarity(sig1, sig2)
                if sim >= self.threshold:
                    pairs.append((j1, j2, round(sim, 3)))

        return sorted(pairs, key=lambda x: -x[2])

    def merge(self, journey_a: Dict, journey_b: Dict) -> Dict:
        """Merge two similar journeys into one canonical journey.

        Strategy: use the longer step sequence as the base, enrich with
        selectors from the other, and combine metadata.
        """
        steps_a = journey_a.get("steps", [])
        steps_b = journey_b.get("steps", [])

        if len(steps_b) > len(steps_a):
            base, supplement = journey_b, journey_a
            base_steps, supp_steps = steps_b, steps_a
        else:
            base, supplement = journey_a, journey_b
            base_steps, supp_steps = steps_a, steps_b

        merged_steps = []
        supp_sigs = {_step_signature(s): s for s in supp_steps}

        for step in base_steps:
            sig = _step_signature(step)
            merged = dict(step)

            if sig in supp_sigs:
                merged["selectors"] = self._merge_selectors(
                    self._parse_selectors(step.get("selectors")),
                    self._parse_selectors(supp_sigs[sig].get("selectors")),
                )

            merged_steps.append(merged)

        tags_a = set(self._parse_tags(journey_a.get("tags")))
        tags_b = set(self._parse_tags(journey_b.get("tags")))
        merged_tags = sorted(tags_a | tags_b | {"merged"})

        conf_a = journey_a.get("confidence", 0) or 0
        conf_b = journey_b.get("confidence", 0) or 0

        return {
            "id": str(uuid.uuid4())[:8],
            "name": base.get("name", "Merged Journey"),
            "domain": base.get("domain") or supplement.get("domain", ""),
            "feature": base.get("feature") or supplement.get("feature", ""),
            "confidence": round(max(conf_a, conf_b) * 1.05, 3),
            "tags": merged_tags,
            "steps": merged_steps,
            "merged_from": [journey_a.get("id", ""), journey_b.get("id", "")],
            "discovered_by": "merger",
        }

    def auto_merge(self, journeys: List[Dict]) -> Dict:
        """Find all duplicates and merge them. Returns merge report."""
        duplicates = self.find_duplicates(journeys)
        merged_ids = set()
        merge_results = []

        for j1, j2, sim in duplicates:
            id1 = j1.get("id", "")
            id2 = j2.get("id", "")
            if id1 in merged_ids or id2 in merged_ids:
                continue

            merged = self.merge(j1, j2)
            merge_results.append({
                "merged_journey": merged,
                "source_ids": [id1, id2],
                "similarity": sim,
            })
            merged_ids.add(id1)
            merged_ids.add(id2)

        return {
            "duplicates_found": len(duplicates),
            "merges_performed": len(merge_results),
            "results": merge_results,
        }

    def _similarity(self, sig_a: List[str], sig_b: List[str]) -> float:
        return SequenceMatcher(None, sig_a, sig_b).ratio()

    def _merge_selectors(self, sel_a: Dict, sel_b: Dict) -> str:
        merged = {}
        for key in ("test_id", "id", "name", "aria_label", "role", "label", "text", "css", "xpath"):
            val = sel_a.get(key) or sel_b.get(key)
            if val:
                merged[key] = val
        return json.dumps(merged)

    def _parse_selectors(self, sel) -> Dict:
        if isinstance(sel, dict):
            return sel
        if isinstance(sel, str):
            try:
                return json.loads(sel)
            except Exception:
                return {}
        return {}

    def _parse_tags(self, tags) -> List[str]:
        if isinstance(tags, list):
            return tags
        if isinstance(tags, str):
            try:
                return json.loads(tags)
            except Exception:
                return []
        return []
