"""LabelLearner: continuous learning from human corrections."""

from __future__ import annotations

from typing import Dict, List

from testai.storage.db import Database


class LabelLearner:
    """Builds vocabulary hints from past corrections to improve future LLM labeling."""

    def __init__(self, db: Database):
        self.db = db

    def get_vocabulary_hints(self) -> str:
        """Return a prompt fragment with learned vocabulary for the LLM labeler."""
        vocab = self.db.get_domain_vocabulary()
        patterns = self.db.get_correction_patterns(limit=20)

        parts = []

        domains = vocab.get("domains", [])
        if domains:
            parts.append(f"Known domains: {', '.join(domains)}")

        features = vocab.get("features", [])
        if features:
            parts.append(f"Known features: {', '.join(features)}")

        if patterns:
            corrections = []
            for p in patterns[:10]:
                if p["field"] in ("domain", "feature", "name") and p["count"] >= 2:
                    corrections.append(
                        f"When AI assigned {p['field']}='{p['old_value']}', "
                        f"humans corrected it to '{p['new_value']}' ({p['count']}x)"
                    )
            if corrections:
                parts.append("Common corrections:\n" + "\n".join(corrections))

        if not parts:
            return ""

        return "\n".join(parts)

    def get_correction_analytics(self) -> Dict:
        """Return analytics about labeling accuracy and correction trends."""
        patterns = self.db.get_correction_patterns(limit=50)
        stats = self.db.get_review_stats()
        trend = self.db.get_accuracy_trend(days=30)

        field_counts: Dict[str, int] = {}
        for p in patterns:
            field_counts[p["field"]] = field_counts.get(p["field"], 0) + p["count"]

        return {
            "most_corrected_fields": sorted(
                field_counts.items(), key=lambda x: x[1], reverse=True
            ),
            "top_patterns": patterns[:10],
            "review_stats": stats,
            "daily_trend": trend,
        }
