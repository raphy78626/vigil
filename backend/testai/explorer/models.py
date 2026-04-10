"""Data models for the AI Explorer agent."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ActionType(str, Enum):
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    NAVIGATE = "navigate"
    SCROLL = "scroll"
    BACK = "back"
    STOP = "stop"


class ExplorerStrategy(str, Enum):
    BFS = "bfs"
    DFS = "dfs"


class SessionStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class InteractiveElement:
    """A single actionable element on the page."""
    index: int
    tag: str
    role: str = ""
    text: str = ""
    href: str = ""
    placeholder: str = ""
    aria_label: str = ""
    input_type: str = ""
    name: str = ""
    css_selector: str = ""
    is_visible: bool = True
    bounding_box: Optional[Dict[str, float]] = None

    def summary(self) -> str:
        parts = [f"[{self.index}] <{self.tag}>"]
        if self.role:
            parts.append(f'role="{self.role}"')
        if self.text:
            parts.append(f'"{self.text[:60]}"')
        if self.href:
            parts.append(f'href="{self.href[:80]}"')
        if self.placeholder:
            parts.append(f'placeholder="{self.placeholder}"')
        if self.input_type:
            parts.append(f'type="{self.input_type}"')
        return " ".join(parts)


@dataclass
class PageSnapshot:
    """State of a page at a point in time."""
    url: str
    title: str
    elements: List[InteractiveElement] = field(default_factory=list)
    screenshot_b64: Optional[str] = None
    timestamp: str = ""

    def elements_summary(self, max_items: int = 40) -> str:
        lines = []
        for el in self.elements[:max_items]:
            lines.append(el.summary())
        if len(self.elements) > max_items:
            lines.append(f"... and {len(self.elements) - max_items} more elements")
        return "\n".join(lines)


@dataclass
class PlannedAction:
    """An action the LLM decided to take."""
    element_index: int
    action: ActionType
    fill_value: str = ""
    reason: str = ""


@dataclass
class InteractionRecord:
    """Record of a single interaction during exploration."""
    step_number: int
    url_before: str
    url_after: str
    action: ActionType
    element_summary: str = ""
    css_selector: str = ""
    text: str = ""
    fill_value: str = ""
    success: bool = True
    error: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DiscoveredJourney:
    """A user flow discovered during exploration."""
    name: str
    description: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    urls: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExplorerResult:
    """Final result of an exploration session."""
    session_id: str
    base_url: str
    strategy: str
    status: str = SessionStatus.COMPLETED.value
    pages_visited: int = 0
    unique_urls: List[str] = field(default_factory=list)
    interactions: List[InteractionRecord] = field(default_factory=list)
    journeys: List[DiscoveredJourney] = field(default_factory=list)
    flow_graph: Dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "base_url": self.base_url,
            "strategy": self.strategy,
            "status": self.status,
            "pages_visited": self.pages_visited,
            "unique_urls": self.unique_urls,
            "interactions": [i.to_dict() for i in self.interactions],
            "journeys": [j.to_dict() for j in self.journeys],
            "flow_graph": self.flow_graph,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }
