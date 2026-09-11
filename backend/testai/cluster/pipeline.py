"""Full clustering pipeline: ingest JSON -> segment -> group -> label -> store."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from testai.models.event import Event, EventType, ElementContext, ElementSelectors, NavigationContext, KeyEventContext
from testai.cluster.segmenter import SessionSegmenter
from testai.cluster.grouper import FlowGrouper
# JourneyLabeler and HierarchyBuilder imported lazily inside run_pipeline()
# so parse_raw_event() is importable without litellm installed (used by the
# offline pipeline).
from testai.hitl.review import ReviewManager
from testai.hitl.learner import LabelLearner
from testai.storage.db import Database


def parse_raw_event(raw: Dict) -> Event:
    element = None
    if raw.get("element"):
        el = raw["element"]
        sels = el.get("selectors", {})
        element = ElementContext(
            tag_name=el.get("tagName", "unknown"),
            selectors=ElementSelectors(
                css=sels.get("css", ""),
                xpath=sels.get("xpath"),
                text=sels.get("text"),
                full_text=sels.get("fullText"),
                aria_label=sels.get("ariaLabel"),
                test_id=sels.get("testId"),
                test_id_attr=sels.get("testIdAttr"),
                role=sels.get("role"),
                label=sels.get("label"),
                name=sels.get("name"),
                placeholder=sels.get("placeholder"),
                title=sels.get("title"),
                href=sels.get("href"),
                class_name=sels.get("className"),
                data_attributes=sels.get("dataAttributes"),
            ),
            input_type=el.get("inputType"),
            value=el.get("value"),
            coordinates=el.get("coordinates"),
        )

    navigation = None
    if raw.get("navigation"):
        nav = raw["navigation"]
        navigation = NavigationContext(
            from_url=nav.get("fromUrl", ""),
            to_url=nav.get("toUrl", ""),
            trigger=nav.get("trigger", "unknown"),
        )

    key_event = None
    if raw.get("key") or raw.get("combo"):
        key_event = KeyEventContext(
            key=raw.get("key", ""),
            code=raw.get("code", ""),
            combo=raw.get("combo", ""),
            ctrl_key=raw.get("ctrlKey", False),
            meta_key=raw.get("metaKey", False),
            alt_key=raw.get("altKey", False),
            shift_key=raw.get("shiftKey", False),
        )

    event_type = raw.get("type", "click")
    try:
        etype = EventType(event_type)
    except ValueError:
        etype = EventType.CLICK

    ts = raw.get("timestamp", 0)
    if isinstance(ts, (int, float)) and ts > 1e12:
        ts = ts / 1000.0
    dt = datetime.fromtimestamp(ts) if ts else datetime.now()

    return Event(
        id=raw.get("id", ""),
        timestamp=dt,
        type=etype,
        url=raw.get("url", ""),
        page_title=raw.get("pageTitle", ""),
        element=element,
        navigation=navigation,
        key_event=key_event,
        tab_id=raw.get("tabId", 0),
        session_id=raw.get("sessionId", ""),
    )


def run_pipeline(
    events_path: str,
    model: str = "gpt-4o-mini",
    db_path: Optional[str] = None,
    verbose: bool = True,
):
    if verbose:
        print(f"\n{'='*60}")
        print("  Vigil — Semantic Clustering Pipeline")
        print(f"{'='*60}\n")

    # 1. Load events
    raw_events = json.loads(Path(events_path).read_text())
    if verbose:
        print(f"[1/6] Loaded {len(raw_events)} raw events from {events_path}")

    events = [parse_raw_event(e) for e in raw_events]
    events = [e for e in events if e.url and not e.url.startswith("chrome")]
    if verbose:
        print(f"       Parsed {len(events)} valid events")

    if not events:
        print("No valid events to process. Exiting.")
        return

    # 2. Segment into sessions
    segmenter = SessionSegmenter()
    sessions = segmenter.segment(events)
    if verbose:
        print(f"\n[2/6] Segmented into {len(sessions)} sessions")
        for i, s in enumerate(sessions):
            print(f"       Session {i+1}: {len(s)} events, {s[0].url[:60]}...")

    # 3. Group into flows
    grouper = FlowGrouper()
    all_flows = []
    for session in sessions:
        flows = grouper.group(session)
        all_flows.extend(flows)
    if verbose:
        print(f"\n[3/6] Grouped into {len(all_flows)} candidate flows")
        for i, f in enumerate(all_flows):
            types = [e.type.value for e in f]
            print(f"       Flow {i+1}: {len(f)} events — {', '.join(types[:5])}...")

    if not all_flows:
        print("No meaningful flows found. Try capturing more interactions.")
        return

    # 4. Label with LLM (with continuous learning hints)
    db = Database(Path(db_path)) if db_path else Database()
    db.connect()

    learner = LabelLearner(db)
    vocabulary_hints = learner.get_vocabulary_hints()
    if verbose:
        print(f"\n[4/6] Labeling flows with LLM ({model})...")
        if vocabulary_hints:
            print("       Using learned vocabulary hints from past corrections")
    from testai.cluster.labeler import JourneyLabeler  # lazy: needs litellm
    labeler = JourneyLabeler(model=model)
    journeys = []
    for i, flow in enumerate(all_flows):
        try:
            journey = labeler.label(flow, session_id=flow[0].session_id, vocabulary_hints=vocabulary_hints)
            journeys.append(journey)
            if verbose:
                print(f"       Journey {i+1}: \"{journey.name}\" "
                      f"({journey.domain} > {journey.feature}) "
                      f"[confidence: {journey.confidence:.0%}]")
        except Exception as e:
            if verbose:
                print(f"       Flow {i+1}: labeling failed — {e}")

    if not journeys:
        print("No journeys could be labeled. Check your LLM API key.")
        db.close()
        return

    # 5. Store
    for e in events:
        db.insert_event(e)
    for j in journeys:
        db.insert_journey(j)

    # 6. HITL triage: auto-approve or queue for review
    review_manager = ReviewManager(db)
    if verbose:
        print(f"\n[6/6] HITL triage (threshold: {review_manager.threshold:.0%})...")
    for j in journeys:
        status = review_manager.triage(j.id, j.confidence)
        if verbose:
            icon = "auto" if status == "auto_approved" else "queue"
            print(f"       [{icon}] \"{j.name}\" ({j.confidence:.0%}) → {status}")

    if verbose:
        print(f"\n[5/6] Stored {len(events)} events and {len(journeys)} journeys")
        print(f"       Database: {db.db_path}")

    db.close()

    # Summary
    if verbose:
        print(f"\n{'='*60}")
        print("  RESULTS")
        print(f"{'='*60}")
        print(f"  Events processed:  {len(events)}")
        print(f"  Sessions found:    {len(sessions)}")
        print(f"  Flows identified:  {len(all_flows)}")
        print(f"  Journeys labeled:  {len(journeys)}")
        print()
        for j in journeys:
            print(f"  [{j.confidence:.0%}] {j.name}")
            print(f"       Domain: {j.domain} | Feature: {j.feature}")
            print(f"       Steps: {len(j.steps)}")
            for s in j.steps:
                print(f"         {s.order}. {s.description}")
            print()

    return journeys


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m testai.cluster.pipeline <events.json> [--model gpt-4o-mini]")
        sys.exit(1)

    events_file = sys.argv[1]
    model_name = "gpt-4o-mini"
    for i, arg in enumerate(sys.argv):
        if arg == "--model" and i + 1 < len(sys.argv):
            model_name = sys.argv[i + 1]

    run_pipeline(events_file, model=model_name)
