"""Flow Grouper: clusters events within a session into coherent action flows."""

from __future__ import annotations

from typing import List
from urllib.parse import urlparse

from testai.models.event import Event, EventType


class FlowGrouper:
    def __init__(self, path_depth: int = 2):
        self.path_depth = path_depth

    def group(self, session_events: List[Event]) -> List[List[Event]]:
        if not session_events:
            return []

        flows: List[List[Event]] = []
        current_flow: List[Event] = [session_events[0]]

        for i in range(1, len(session_events)):
            prev = session_events[i - 1]
            curr = session_events[i]

            if self._is_flow_boundary(prev, curr):
                if current_flow:
                    flows.append(current_flow)
                current_flow = [curr]
            else:
                current_flow.append(curr)

        if current_flow:
            flows.append(current_flow)

        return [f for f in flows if len(f) >= 2]

    def _is_flow_boundary(self, prev: Event, curr: Event) -> bool:
        prev_prefix = self._path_prefix(prev.url)
        curr_prefix = self._path_prefix(curr.url)

        if prev_prefix != curr_prefix and curr.type == EventType.PAGELOAD:
            return True

        if (
            prev.type == EventType.NAVIGATION
            and curr.type == EventType.PAGELOAD
            and prev_prefix != curr_prefix
        ):
            return True

        return False

    def _path_prefix(self, url: str) -> str:
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        return "/".join(parts[: self.path_depth])
