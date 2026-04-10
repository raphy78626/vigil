"""Tests for session segmentation logic."""

from datetime import datetime, timedelta

from testai.cluster.segmenter import SessionSegmenter
from testai.models.event import Event, EventType


def _make_event(
    minutes_offset: int = 0,
    url: str = "https://app.example.com/products",
    event_type: EventType = EventType.CLICK,
) -> Event:
    return Event(
        id=f"evt-{minutes_offset}",
        timestamp=datetime(2026, 2, 21, 10, 0) + timedelta(minutes=minutes_offset),
        type=event_type,
        url=url,
        page_title="Test Page",
        session_id="session-1",
    )


def test_single_session_no_gaps():
    events = [_make_event(i) for i in range(5)]
    segmenter = SessionSegmenter()
    sessions = segmenter.segment(events)
    assert len(sessions) == 1
    assert len(sessions[0]) == 5


def test_splits_on_time_gap():
    events = [
        _make_event(0),
        _make_event(1),
        _make_event(2),
        _make_event(10),  # 10 min gap > 5 min threshold
        _make_event(11),
    ]
    segmenter = SessionSegmenter()
    sessions = segmenter.segment(events)
    assert len(sessions) == 2
    assert len(sessions[0]) == 3
    assert len(sessions[1]) == 2


def test_splits_on_domain_change():
    events = [
        _make_event(0, url="https://app.example.com/page1"),
        _make_event(1, url="https://app.example.com/page2"),
        _make_event(2, url="https://mail.google.com/inbox"),
        _make_event(3, url="https://mail.google.com/compose"),
    ]
    segmenter = SessionSegmenter()
    sessions = segmenter.segment(events)
    assert len(sessions) == 2


def test_empty_events():
    segmenter = SessionSegmenter()
    assert segmenter.segment([]) == []


def test_allowlist_filtering():
    events = [
        _make_event(0, url="https://app.example.com/page1"),
        _make_event(1, url="https://slack.com/messages"),
        _make_event(2, url="https://app.example.com/page2"),
    ]
    segmenter = SessionSegmenter(allowlisted_domains=["app.example.com"])
    sessions = segmenter.segment(events)
    total_events = sum(len(s) for s in sessions)
    assert total_events == 2
