"""Session Segmenter: splits a continuous event stream into discrete sessions."""

from __future__ import annotations

from typing import List, Optional, Set
from urllib.parse import urlparse

from testai.models.event import Event

DEFAULT_GAP_THRESHOLD_MS = 5 * 60 * 1000


class SessionSegmenter:
    def __init__(
        self,
        gap_threshold_ms: int = DEFAULT_GAP_THRESHOLD_MS,
        allowlisted_domains: Optional[List[str]] = None,
    ):
        self.gap_threshold_ms = gap_threshold_ms
        self.allowlisted_domains: Set[str] = set(allowlisted_domains or [])

    def segment(self, events: List[Event]) -> List[List[Event]]:
        if not events:
            return []

        sorted_events = sorted(events, key=lambda e: e.timestamp)
        sessions: List[List[Event]] = []
        current_session: List[Event] = [sorted_events[0]]

        for i in range(1, len(sorted_events)):
            prev = sorted_events[i - 1]
            curr = sorted_events[i]

            if self._is_session_boundary(prev, curr):
                if current_session:
                    sessions.append(current_session)
                current_session = [curr]
            else:
                current_session.append(curr)

        if current_session:
            sessions.append(current_session)

        if self.allowlisted_domains:
            sessions = [self._filter_allowlisted(s) for s in sessions]
            sessions = [s for s in sessions if s]

        return sessions

    def _is_session_boundary(self, prev: Event, curr: Event) -> bool:
        time_gap_ms = (curr.timestamp.timestamp() - prev.timestamp.timestamp()) * 1000
        if time_gap_ms > self.gap_threshold_ms:
            return True

        prev_domain = urlparse(prev.url).netloc
        curr_domain = urlparse(curr.url).netloc
        if prev_domain != curr_domain:
            return True

        return False

    def _filter_allowlisted(self, events: List[Event]) -> List[Event]:
        return [
            e for e in events
            if urlparse(e.url).netloc in self.allowlisted_domains
        ]
