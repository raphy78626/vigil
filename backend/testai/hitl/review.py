"""ReviewManager: smart escalation and review workflow for journey labels."""

from __future__ import annotations

from typing import Dict, List, Optional

from testai.storage.db import Database


class ReviewManager:
    """Routes journeys to auto-approve or human review based on confidence."""

    def __init__(self, db: Database):
        self.db = db
        self._threshold: Optional[float] = None

    @property
    def threshold(self) -> float:
        if self._threshold is None:
            config = self.db.get_hitl_config()
            self._threshold = float(config.get("auto_approve_threshold", "0.85"))
        return self._threshold

    def reload_threshold(self) -> float:
        self._threshold = None
        return self.threshold

    def triage(self, journey_id: str, confidence: float) -> str:
        """Called after labeling. Auto-approves high-confidence, queues the rest."""
        if confidence >= self.threshold:
            self.db.set_review_status(journey_id, "auto_approved", "system")
            self.db.log_review_action(
                journey_id, "auto_approve", "system",
                f"Confidence {confidence:.0%} >= threshold {self.threshold:.0%}",
            )
            return "auto_approved"
        else:
            self.db.set_review_status(journey_id, "pending_review", "system")
            self.db.log_review_action(
                journey_id, "pending_review", "system",
                f"Confidence {confidence:.0%} < threshold {self.threshold:.0%}",
            )
            return "pending_review"

    def approve(self, journey_id: str, reviewer: str = "", note: str = "") -> bool:
        ok = self.db.set_review_status(journey_id, "approved", reviewer, note)
        if ok:
            self.db.log_review_action(journey_id, "approve", reviewer, note)
        return ok

    def reject(self, journey_id: str, reviewer: str = "", note: str = "") -> bool:
        ok = self.db.set_review_status(journey_id, "rejected", reviewer, note)
        if ok:
            self.db.log_review_action(journey_id, "reject", reviewer, note)
        return ok

    def correct_and_approve(
        self, journey_id: str, corrections: Dict, reviewer: str = "", note: str = ""
    ) -> Optional[Dict]:
        """Apply label corrections then approve."""
        result = self.db.update_journey_label(journey_id, corrections)
        if result is None:
            return None
        self.db.set_review_status(journey_id, "approved", reviewer, note)
        self.db.log_review_action(
            journey_id, "correct", reviewer, note, changes=corrections,
        )
        return result

    def batch_approve(self, journey_ids: List[str], reviewer: str = "") -> int:
        return self.db.batch_update_review_status(journey_ids, "approved", reviewer)
