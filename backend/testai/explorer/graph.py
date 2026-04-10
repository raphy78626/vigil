"""Flow graph — tracks exploration state, detects cycles, extracts journeys."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from testai.explorer.models import (
    DiscoveredJourney,
    InteractionRecord,
    ActionType,
)

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_NUMERIC_SEGMENT_RE = re.compile(r"/\d{4,}/")


def normalize_url(url: str) -> str:
    """Normalize a URL to a canonical pattern for comparison.

    Replaces UUIDs and long numeric segments with placeholders, strips
    query params and fragments so that the same logical page produces
    the same key regardless of dynamic content.
    """
    parsed = urlparse(url)
    path = parsed.path or "/"
    path = _UUID_RE.sub("{id}", path)
    path = _NUMERIC_SEGMENT_RE.sub("/{num}/", path)
    return f"{parsed.scheme}://{parsed.netloc}{path}"


class FlowNode:
    """A unique page (by normalized URL) in the flow graph."""

    __slots__ = ("url_pattern", "title", "visit_count", "first_seen",
                 "element_count", "has_forms")

    def __init__(self, url_pattern: str, title: str = ""):
        self.url_pattern = url_pattern
        self.title = title
        self.visit_count = 0
        self.first_seen = datetime.now(timezone.utc).isoformat()
        self.element_count = 0
        self.has_forms = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url_pattern": self.url_pattern,
            "title": self.title,
            "visit_count": self.visit_count,
            "first_seen": self.first_seen,
            "element_count": self.element_count,
            "has_forms": self.has_forms,
        }


class FlowEdge:
    """A transition between two pages."""

    __slots__ = ("from_url", "to_url", "action", "element_text", "count")

    def __init__(self, from_url: str, to_url: str,
                 action: str = "", element_text: str = ""):
        self.from_url = from_url
        self.to_url = to_url
        self.action = action
        self.element_text = element_text
        self.count = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from": self.from_url,
            "to": self.to_url,
            "action": self.action,
            "element_text": self.element_text,
            "count": self.count,
        }


class FlowGraph:
    """Tracks the exploration graph and provides journey extraction."""

    def __init__(self, base_domain: str = ""):
        self.base_domain = base_domain
        self.nodes: Dict[str, FlowNode] = {}
        self.edges: List[FlowEdge] = []
        self._adjacency: Dict[str, List[int]] = defaultdict(list)
        self._visited_states: Set[str] = set()

    def visit_page(self, url: str, title: str = "",
                   element_count: int = 0, has_forms: bool = False) -> str:
        """Record a page visit. Returns the normalized URL pattern."""
        pattern = normalize_url(url)
        if pattern not in self.nodes:
            self.nodes[pattern] = FlowNode(pattern, title)
        node = self.nodes[pattern]
        node.visit_count += 1
        if title and not node.title:
            node.title = title
        node.element_count = max(node.element_count, element_count)
        node.has_forms = node.has_forms or has_forms
        return pattern

    def add_transition(self, from_url: str, to_url: str,
                       action: str = "", element_text: str = "") -> None:
        """Record a page-to-page transition."""
        from_pattern = normalize_url(from_url)
        to_pattern = normalize_url(to_url)

        for idx in self._adjacency[from_pattern]:
            edge = self.edges[idx]
            if edge.to_url == to_pattern and edge.action == action:
                edge.count += 1
                return

        edge = FlowEdge(from_pattern, to_pattern, action, element_text)
        idx = len(self.edges)
        self.edges.append(edge)
        self._adjacency[from_pattern].append(idx)

    def is_visited(self, url: str) -> bool:
        """Check if a normalized URL pattern has been visited."""
        return normalize_url(url) in self.nodes

    def visit_count(self, url: str) -> int:
        pattern = normalize_url(url)
        node = self.nodes.get(pattern)
        return node.visit_count if node else 0

    def mark_state(self, state_key: str) -> bool:
        """Mark a page state as seen. Returns True if it was new."""
        if state_key in self._visited_states:
            return False
        self._visited_states.add(state_key)
        return True

    @property
    def page_count(self) -> int:
        return len(self.nodes)

    @property
    def unique_urls(self) -> List[str]:
        return list(self.nodes.keys())

    def coverage_stats(self) -> Dict[str, Any]:
        form_pages = sum(1 for n in self.nodes.values() if n.has_forms)
        return {
            "pages_discovered": len(self.nodes),
            "transitions": len(self.edges),
            "pages_with_forms": form_pages,
            "total_visits": sum(n.visit_count for n in self.nodes.values()),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "stats": self.coverage_stats(),
        }

    # ------------------------------------------------------------------
    # Journey extraction
    # ------------------------------------------------------------------

    def extract_journeys(
        self, interactions: List[InteractionRecord]
    ) -> List[DiscoveredJourney]:
        """Split the interaction log into distinct journeys.

        A new journey starts when the user navigates to a significantly
        different part of the app (different path prefix) or returns to
        a previously visited page after exploring elsewhere.
        """
        if not interactions:
            return []

        journeys: List[DiscoveredJourney] = []
        current_steps: List[Dict[str, Any]] = []
        current_urls: List[str] = []
        current_prefix = ""

        def _flush(reason: str = ""):
            nonlocal current_steps, current_urls, current_prefix
            if len(current_steps) < 2:
                current_steps = []
                current_urls = []
                return

            name = _journey_name(current_urls, current_steps)
            journeys.append(DiscoveredJourney(
                name=name,
                description=f"Auto-discovered: {len(current_steps)} steps across {len(set(current_urls))} pages",
                steps=list(current_steps),
                urls=list(set(current_urls)),
            ))
            current_steps = []
            current_urls = []

        for rec in interactions:
            url = rec.url_after or rec.url_before
            prefix = _url_prefix(url)

            is_different_area = (
                current_prefix
                and prefix != current_prefix
                and not prefix.startswith(current_prefix)
                and not current_prefix.startswith(prefix)
            )

            if is_different_area and len(current_steps) >= 2:
                _flush("area change")

            current_prefix = prefix
            current_urls.append(url)
            current_steps.append({
                "order": len(current_steps) + 1,
                "description": _step_description(rec),
                "url": url,
                "action_type": rec.action.value if isinstance(rec.action, ActionType) else rec.action,
                "element_hint": rec.css_selector,
                "selectors": {"css": rec.css_selector, "text": rec.text},
            })

            if len(current_steps) >= 15:
                _flush("max steps")

        _flush("end")
        return journeys


def _url_prefix(url: str) -> str:
    """Extract the first meaningful path segment."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if parts:
        return "/" + parts[0]
    return "/"


def _journey_name(urls: List[str], steps: List[Dict]) -> str:
    """Generate a descriptive journey name from urls and steps."""
    if not urls:
        return "Unknown Flow"

    parsed = urlparse(urls[0])
    domain = parsed.netloc

    path_parts = set()
    for u in urls:
        parts = [p for p in urlparse(u).path.split("/") if p and len(p) < 30]
        path_parts.update(parts[:2])

    action_types = [s.get("action_type", "") for s in steps]
    has_form = "fill" in action_types
    has_navigation = sum(1 for a in action_types if a == "click") >= 3

    if has_form:
        prefix = "Form Flow"
    elif has_navigation:
        prefix = "Navigation Flow"
    else:
        prefix = "Explore Flow"

    path_hint = " > ".join(sorted(path_parts)[:3]) if path_parts else "home"
    return f"{prefix}: {path_hint}"


def _step_description(rec: InteractionRecord) -> str:
    """Generate a human-readable step description."""
    action = rec.action.value if isinstance(rec.action, ActionType) else rec.action

    if action == "click":
        target = rec.text[:50] if rec.text else rec.css_selector[:50]
        return f"Click '{target}'"
    elif action == "fill":
        target = rec.text[:30] if rec.text else rec.css_selector[:30]
        return f"Type into {target}"
    elif action == "select":
        return f"Select option in {rec.css_selector[:40]}"
    elif action == "navigate":
        return f"Navigate to {rec.url_after}"
    elif action == "back":
        return "Go back"
    else:
        return f"{action} on {rec.element_summary[:40]}"
