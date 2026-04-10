"""Tests for the local (rule-based) clustering pipeline and exporter."""

import json
import time
import uuid
from pathlib import Path

import pytest

from testai.cluster.pipeline_local import run_pipeline_local, describe_step
from testai.models.event import Event, EventType, ElementContext, ElementSelectors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event_dict(
    etype: str = "click",
    url: str = "https://app.example.com/",
    session_id: str | None = None,
    selectors: dict | None = None,
    value: str = "",
    key: str = "",
    combo: str = "",
    tag: str = "button",
) -> dict:
    ts = time.time() * 1000
    return {
        "id": str(uuid.uuid4()),
        "type": etype,
        "url": url,
        "pageTitle": "Test Page",
        "timestamp": ts,
        "sessionId": session_id or str(uuid.uuid4()),
        "isTopFrame": True,
        "element": {
            "tagName": tag,
            "selectors": selectors or {"css": "button.submit", "ariaLabel": "Submit", "text": "Submit"},
            "value": value,
        },
        "key": key,
        "code": key,
        "combo": combo,
    }


def _run_pipeline_with_events(events: list, tmp_path: Path) -> list:
    f = tmp_path / "events.json"
    f.write_text(json.dumps(events))
    return run_pipeline_local(str(f), db_path=str(tmp_path / "test.db"), verbose=False) or []


# ---------------------------------------------------------------------------
# Pipeline tests
# ---------------------------------------------------------------------------

class TestPipelineLocal:
    def test_basic_click_creates_journey(self, tmp_path):
        sess = str(uuid.uuid4())
        events = [
            _make_event_dict("pageload", session_id=sess),
            _make_event_dict("click", session_id=sess),
        ]
        journeys = _run_pipeline_with_events(events, tmp_path)
        assert len(journeys) >= 1

    def test_input_event_creates_fill_step(self, tmp_path):
        sess = str(uuid.uuid4())
        events = [
            _make_event_dict("pageload", session_id=sess),
            _make_event_dict(
                "input",
                session_id=sess,
                tag="input",
                selectors={"css": "input#email", "placeholder": "Email", "ariaLabel": "Email"},
                value="user@example.com",
            ),
        ]
        journeys = _run_pipeline_with_events(events, tmp_path)
        assert len(journeys) >= 1
        steps = journeys[0].steps
        fill_steps = [s for s in steps if s.action_type == "fill_form"]
        assert len(fill_steps) >= 1
        assert "user@example.com" in fill_steps[0].description

    def test_noise_events_are_skipped(self, tmp_path):
        sess = str(uuid.uuid4())
        events = [
            _make_event_dict("pageload", session_id=sess),
            _make_event_dict("scroll", session_id=sess),
            _make_event_dict("focus", session_id=sess),
            _make_event_dict("copy", session_id=sess),
            _make_event_dict("hover", session_id=sess),
            _make_event_dict("click", session_id=sess),  # only meaningful one
        ]
        journeys = _run_pipeline_with_events(events, tmp_path)
        assert len(journeys) >= 1
        action_types = [s.action_type for s in journeys[0].steps]
        assert "scroll" not in action_types
        assert "focus" not in action_types

    def test_video_player_noise_filtered(self, tmp_path):
        sess = str(uuid.uuid4())
        events = [
            _make_event_dict("pageload", session_id=sess, url="https://www.youtube.com/watch?v=abc"),
            _make_event_dict("click", session_id=sess,
                             selectors={"css": "[aria-label='Seek slider']", "ariaLabel": "Seek slider", "role": "slider"}),
            _make_event_dict("click", session_id=sess,
                             selectors={"css": "#skip-button", "text": "Skip", "role": "button"}),
            _make_event_dict("click", session_id=sess,
                             selectors={"css": "input#search", "ariaLabel": "Search", "placeholder": "Search"}),
        ]
        journeys = _run_pipeline_with_events(events, tmp_path)
        assert len(journeys) >= 1
        descs = [s.description for s in journeys[0].steps]
        assert not any("Seek slider" in d for d in descs), "Seek slider should be filtered"
        assert not any("Skip" == d.strip() for d in descs), "Skip ad should be filtered"

    def test_keypress_enter_creates_step(self, tmp_path):
        sess = str(uuid.uuid4())
        events = [
            _make_event_dict("pageload", session_id=sess),
            _make_event_dict("keypress", session_id=sess, key="Enter", combo="Enter"),
        ]
        journeys = _run_pipeline_with_events(events, tmp_path)
        assert len(journeys) >= 1
        steps = journeys[0].steps
        key_steps = [s for s in steps if s.action_type == "keypress"]
        assert len(key_steps) >= 1
        assert "Enter" in key_steps[0].description

    def test_empty_events_returns_none(self, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text("[]")
        result = run_pipeline_local(str(f), db_path=str(tmp_path / "test.db"), verbose=False)
        assert not result

    def test_chrome_extension_events_filtered(self, tmp_path):
        sess = str(uuid.uuid4())
        events = [
            _make_event_dict("click", url="chrome-extension://abc/popup.html", session_id=sess),
            _make_event_dict("click", url="https://app.example.com/", session_id=sess),
        ]
        journeys = _run_pipeline_with_events(events, tmp_path)
        for j in journeys:
            for s in j.steps:
                assert "chrome-extension" not in (s.url or "")


# ---------------------------------------------------------------------------
# describe_step tests
# ---------------------------------------------------------------------------

class TestDescribeStep:
    def _click_event(self, css="button.submit", text="Submit", aria="Submit"):
        return Event(
            id="e1", timestamp=__import__("datetime").datetime.now(),
            type=EventType.CLICK, url="https://app.example.com/",
            element=ElementContext(
                tag_name="button",
                selectors=ElementSelectors(css=css, text=text, aria_label=aria),
            )
        )

    def test_click_returns_click_step(self):
        step = describe_step(self._click_event(), order=1)
        assert step is not None
        assert step.action_type == "click"

    def test_scroll_returns_none(self):
        e = Event(id="e2", timestamp=__import__("datetime").datetime.now(),
                  type=EventType.SCROLL, url="https://x.com/")
        assert describe_step(e, order=1) is None

    def test_hover_returns_none(self):
        e = Event(id="e3", timestamp=__import__("datetime").datetime.now(),
                  type=EventType.HOVER, url="https://x.com/")
        assert describe_step(e, order=1) is None

    def test_video_player_noise_filtered(self):
        e = Event(
            id="e4", timestamp=__import__("datetime").datetime.now(),
            type=EventType.CLICK, url="https://youtube.com/watch?v=x",
            element=ElementContext(
                tag_name="div",
                selectors=ElementSelectors(css="[aria-label='Seek slider']", aria_label="Seek slider"),
            )
        )
        assert describe_step(e, order=1) is None
