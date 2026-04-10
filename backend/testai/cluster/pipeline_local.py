"""
Local pipeline: uses rule-based heuristics instead of LLM for labeling.
No API key needed. Good for demos, testing, and offline use.

Labeling is derived dynamically from real URLs, page titles, and captured
actions — no hardcoded app-specific keywords.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from testai.models.event import Event, EventType
from testai.models.journey import Journey
from testai.models.step import Step
from testai.cluster.segmenter import SessionSegmenter
from testai.cluster.grouper import FlowGrouper
from testai.storage.db import Database


# Universal semantic overrides — intentionally minimal.
# These apply to any webapp and carry clear meaning regardless of app context.
_SEMANTIC = {
    "login":    ("Authentication", "Login"),
    "signin":   ("Authentication", "Login"),
    "logout":   ("Authentication", "Logout"),
    "register": ("Authentication", "Registration"),
    "signup":   ("Authentication", "Registration"),
    "auth":     ("Authentication", "Authentication"),
    "password": ("Authentication", "Password"),
    "forgot":   ("Authentication", "Password Reset"),
    "reset":    ("Authentication", "Password Reset"),
    "checkout": ("Commerce", "Checkout"),
    "payment":  ("Commerce", "Payment"),
    "billing":  ("Commerce", "Billing"),
    "cart":     ("Commerce", "Cart"),
    "basket":   ("Commerce", "Cart"),
    "order":    ("Commerce", "Orders"),
}

# Path segments that carry no semantic meaning and should be ignored.
_NOISE = {
    "", "index", "home", "app", "www", "static", "assets",
    "api", "v1", "v2", "v3", "en", "us", "gb",
    "step", "page", "view", "detail", "details",
}


_VOWELS = frozenset("aeiou")

def _is_random_slug(s: str) -> bool:
    """Return True if the segment looks like a random/generated slug.

    Criteria:
      - 8+ chars with no vowels (machine-generated token like "zcvbnmqw")
      - 20+ chars with no spaces (already split on separators, so this is a
        single very long token — probably a hash, encoded ID, or JS build hash)
    """
    if len(s) >= 20:
        return True
    if len(s) >= 8 and not any(c in _VOWELS for c in s):
        return True
    return False


def _path_segments(url: str) -> List[str]:
    """Extract clean, meaningful segments from a URL path."""
    path = urlparse(url).path.lower()
    # Strip file extensions (.html, .php, .aspx, .jsp, etc.)
    path = re.sub(r"\.[a-z]{2,5}$", "", path)
    # Split on / - _ and filter noise / numeric IDs / UUIDs / random slugs
    raw = re.split(r"[/_\-]", path)
    return [
        s for s in raw
        if s
        and s not in _NOISE
        and not re.fullmatch(r"[0-9a-f\-]{8,}", s)  # hex IDs / UUIDs
        and not s.isdigit()
        and not _is_random_slug(s)
    ]


def _label_from_title(title: str) -> str:
    """Extract the most specific part of a page title."""
    if not title:
        return ""
    # Strip brand suffix after separators like " | ", " - ", " — "
    for sep in (" | ", " - ", " — ", " :: ", " > ", " / "):
        if sep in title:
            title = title.split(sep)[0]
    return title.strip()


def _to_label(segment: str) -> str:
    """Convert a URL segment or token to a display label."""
    return segment.replace("-", " ").replace("_", " ").title()


def infer_domain_and_feature(
    urls: List[str],
    page_titles: List[str],
    element_texts: List[str],
) -> Tuple[str, str]:
    """
    Infer domain and feature purely from captured data.

    Priority:
      1. Universal semantic overrides (auth / commerce patterns)
      2. URL path segments — most frequent first segment = domain,
         most specific (deepest) segment = feature
      3. Page title text
      4. Element button/link text
    """
    all_segments: List[str] = []
    for url in urls:
        all_segments.extend(_path_segments(url))

    combined_text = " ".join(all_segments + page_titles + element_texts).lower()

    # 1. Semantic override — check combined text for universal patterns
    for keyword, (dom, feat) in _SEMANTIC.items():
        if re.search(r"\b" + keyword + r"\b", combined_text):
            return dom, feat

    # 2. URL-driven — weighted frequency
    seg_counter: Counter = Counter()
    depth_counter: Counter = Counter()
    for url in urls:
        segs = _path_segments(url)
        if not segs:
            continue
        seg_counter[segs[0]] += 2          # First segment → likely the domain area
        for depth, s in enumerate(segs):
            depth_counter[s] += depth + 1  # Deeper = more specific = better feature

    if seg_counter:
        domain_seg = seg_counter.most_common(1)[0][0]
        # Feature = deepest / most specific segment that is not the domain segment
        feature_candidates = [
            (s, w) for s, w in depth_counter.most_common()
            if s != domain_seg
        ]
        feature_seg = feature_candidates[0][0] if feature_candidates else domain_seg
        return _to_label(domain_seg), _to_label(feature_seg)

    # 3. Page title fallback
    for title in page_titles:
        label = _label_from_title(title)
        if label:
            return label, label

    # 4. Domain name fallback — use hostname if all path segments were noise
    for url in urls:
        hostname = urlparse(url).hostname or ""
        if hostname:
            # Strip www. prefix and TLD — keep the brand name
            parts = hostname.split(".")
            if parts[0] == "www" and len(parts) > 1:
                parts = parts[1:]
            brand = parts[0].title() if parts else ""
            if brand:
                return brand, "General"

    return "General", "General"


def generate_journey_name(domain: str, feature: str, events: List[Event]) -> str:
    """
    Derive a human-readable journey name from actual captured actions,
    not from a fixed lookup table.
    """
    action_counts = Counter(e.type.value for e in events)
    has_input    = action_counts.get("input", 0) > 0
    has_submit   = action_counts.get("submit", 0) > 0
    has_nav      = action_counts.get("navigation", 0) > 1   # more than one nav = multi-page
    n_clicks     = action_counts.get("click", 0)

    # Collect meaningful button/link texts the user actually clicked
    click_texts = [
        e.element.selectors.text.strip()
        for e in events
        if e.type == EventType.CLICK
        and e.element
        and e.element.selectors.text
        and len(e.element.selectors.text.strip()) <= 40
    ]

    # If a key action label is visible, incorporate it into the name
    key_actions = ["add to cart", "checkout", "submit", "confirm", "finish",
                   "place order", "buy now", "sign in", "log in", "register",
                   "save", "delete", "remove", "upload", "download", "search"]
    for action in key_actions:
        for ct in click_texts:
            if action in ct.lower():
                return f"{_to_label(action)} on {feature}"

    # Pattern-based naming from action mix
    if has_input and has_submit and has_nav:
        return f"Fill & Submit {feature}"
    if has_input and has_nav:
        return f"Enter Data in {feature}"
    if has_input:
        return f"Fill {feature} Form"
    if has_submit:
        return f"Submit {feature}"
    if n_clicks >= 3 and has_nav:
        return f"Navigate {domain}"
    if has_nav:
        return f"Browse {feature}"
        return f"Explore {feature}"


_SKIP_EVENT_TYPES = {
    EventType.SCROLL, EventType.FOCUS, EventType.COPY,
    EventType.CONTEXTMENU, EventType.DRAG, EventType.HOVER,
}

_NOISE_CSS_PATTERNS = (
    'ytp-', 'seek-slider', 'volume', 'skip-button', 'skip-ad',
    'ad-skip', 'mute-button', 'play-button', 'fullscreen-button',
    'subtitles-button', 'settings-button', 'miniplayer-button',
    'autoplay-button', 'theater-button', 'progress-bar',
    'logo-icon', 'logo-container',
)

_NOISE_ARIA_PATTERNS = (
    'seek slider', 'volume', 'mute', 'play ', 'pause',
    'full screen', 'fullscreen', 'mini player', 'miniplayer',
    'settings', 'subtitles', 'closed captions', 'autoplay',
    'theater mode', 'next video',
)

def _is_noise_click(event: Event) -> bool:
    """Detect clicks on video player controls and other UI noise."""
    if not event.element:
        return False
    s = event.element.selectors
    css_lower = (s.css or "").lower()
    aria_lower = (s.aria_label or "").lower()
    text_lower = (s.text or "").lower()

    if any(p in css_lower for p in _NOISE_CSS_PATTERNS):
        return True
    if any(p in aria_lower for p in _NOISE_ARIA_PATTERNS):
        return True
    if text_lower in ("skip", "skip ad", "skip ads"):
        return True
    return False


def describe_step(event: Event, order: int) -> Step | None:
    """Convert an Event into a Step. Returns None for noise events that should be skipped."""
    if event.type in _SKIP_EVENT_TYPES:
        return None
    if event.type == EventType.CLICK and _is_noise_click(event):
        return None

    desc = ""
    action_type = "click"

    if event.type == EventType.PAGELOAD:
        path = urlparse(event.url).path or "/"
        desc = f"Navigate to {path}"
        action_type = "navigate"
    elif event.type == EventType.NAVIGATION:
        to_url = event.navigation.to_url if event.navigation else event.url
        path = urlparse(to_url).path or "/"
        desc = f"Navigate to {path}"
        action_type = "navigate"
    elif event.type == EventType.CLICK and event.element:
        el = event.element
        text = el.selectors.text or ""
        tag = el.tag_name
        if text:
            desc = f"Click '{text[:50]}' {tag}"
        elif el.selectors.aria_label:
            desc = f"Click [{el.selectors.aria_label[:50]}]"
        elif el.selectors.test_id:
            desc = f"Click [{el.selectors.test_id}]"
        elif el.selectors.role:
            desc = f"Click {el.selectors.role} {tag}"
        else:
            desc = f"Click {el.selectors.css or tag}"
        action_type = "click"
    elif event.type == EventType.DBLCLICK and event.element:
        el = event.element
        text = el.selectors.text or ""
        desc = f"Double-click '{text[:50]}'" if text else f"Double-click {el.tag_name}"
        action_type = "dblclick"
    elif event.type == EventType.INPUT and event.element:
        el = event.element
        field_name = (el.selectors.label or el.selectors.placeholder
                      or el.selectors.aria_label or el.selectors.name
                      or el.selectors.test_id or el.selectors.css or "field")
        if el.input_type == "password":
            desc = f"Enter password in {field_name}"
        else:
            val = el.value or "text"
            desc = f"Type '{val[:30]}' into {field_name}"
        action_type = "fill_form"
    elif event.type == EventType.CHANGE and event.element:
        el = event.element
        field_name = (el.selectors.label or el.selectors.aria_label
                      or el.selectors.name or el.selectors.css or "field")
        val = el.value or ""
        desc = f"Select '{val[:30]}' in {field_name}"
        action_type = "select"
    elif event.type == EventType.KEYPRESS and event.key_event:
        key = event.key_event.key
        if key == "Enter":
            desc = "Press Enter"
            action_type = "keypress"
        elif key == "Escape":
            desc = "Press Escape"
            action_type = "keypress"
        elif key == "Tab":
            desc = "Press Tab"
            action_type = "keypress"
        else:
            desc = f"Press {key}"
            action_type = "keypress"
    elif event.type == EventType.KEYCOMBO and event.key_event:
        desc = f"Press {event.key_event.combo}"
        action_type = "keycombo"
    elif event.type == EventType.PASTE and event.element:
        desc = "Paste into field"
        action_type = "paste"
    elif event.type == EventType.SUBMIT:
        desc = "Submit form"
        action_type = "submit"
    else:
        desc = f"{event.type.value} on {urlparse(event.url).path}"

    selectors = {}
    if event.element:
        s = event.element.selectors
        if s.test_id:
            selectors["test_id"] = s.test_id
            selectors["test_id_attr"] = s.test_id_attr or "data-testid"
        if s.css:
            selectors["css"] = s.css
        if s.text:
            selectors["text"] = s.text
        if s.full_text:
            selectors["fullText"] = s.full_text
        if s.aria_label:
            selectors["ariaLabel"] = s.aria_label
        if s.role:
            selectors["role"] = s.role
        if s.label:
            selectors["label"] = s.label
        if s.name:
            selectors["name"] = s.name
        if s.placeholder:
            selectors["placeholder"] = s.placeholder
        if s.title:
            selectors["title"] = s.title
        if s.href:
            selectors["href"] = s.href
        if event.element.value:
            selectors["value"] = event.element.value
        if event.element.input_type:
            selectors["input_type"] = event.element.input_type

    if event.key_event:
        selectors["key"] = event.key_event.key
        selectors["combo"] = event.key_event.combo

    step = Step(
        id=str(uuid.uuid4()),
        order=order,
        description=desc,
        event_ids=[event.id],
        url=event.url,
        action_type=action_type,
        element_hint=desc,
        selectors=selectors,
    )
    return step


def _compute_confidence(steps: List[Step]) -> float:
    """Compute journey confidence based on selector quality of its steps.

    Higher-quality selectors (test_id, aria_label) → higher confidence.
    Text-only or CSS-only selectors are more brittle → lower confidence.
    """
    if not steps:
        return 0.50
    scores = []
    for step in steps:
        if step.action_type == "navigate":
            scores.append(0.90)
            continue
        s = step.selectors
        if s.get("test_id"):
            scores.append(0.90)
        elif s.get("label") or s.get("role"):
            scores.append(0.82)
        elif s.get("ariaLabel"):
            scores.append(0.80)
        elif s.get("css"):
            scores.append(0.65)
        elif s.get("text"):
            scores.append(0.50)
        else:
            scores.append(0.40)
    return round(sum(scores) / len(scores), 2)


def label_flow_locally(flow_events: List[Event]) -> Journey:
    urls = [e.url for e in flow_events]

    page_titles = [
        e.page_title for e in flow_events if e.page_title
    ]
    element_texts = [
        e.element.selectors.text
        for e in flow_events
        if e.element and e.element.selectors.text
    ]

    domain, feature = infer_domain_and_feature(urls, page_titles, element_texts)
    name = generate_journey_name(domain, feature, flow_events)

    steps = []
    step_order = 0
    for event in flow_events:
        step = describe_step(event, step_order + 1)
        if step is not None:
            step_order += 1
            step.order = step_order
            steps.append(step)

    tags = list(set([
        domain.lower().replace(" ", "-"),
        feature.lower().replace(" ", "-"),
    ]))

    return Journey(
        id=str(uuid.uuid4()),
        name=name,
        domain=domain,
        feature=feature,
        steps=steps,
        confidence=_compute_confidence(steps),
        discovered_at=flow_events[0].timestamp if flow_events else datetime.now(),
        discovered_by="demo-qa",
        session_id=flow_events[0].session_id if flow_events else "",
        tags=tags,
    )


def run_pipeline_local(
    events_path: str,
    db_path: Optional[str] = None,
    verbose: bool = True,
):
    from testai.cluster.pipeline import parse_raw_event

    if verbose:
        print(f"\n{'='*60}")
        print("  Vigil — Local Clustering Pipeline (No LLM)")
        print(f"{'='*60}\n")

    raw_events = json.loads(Path(events_path).read_text())
    if verbose:
        print(f"[1/5] Loaded {len(raw_events)} raw events from {events_path}")

    events = []
    for _re in raw_events:
        try:
            events.append(parse_raw_event(_re))
        except Exception:
            raise
    events = [e for e in events if e.url and not e.url.startswith("chrome")]
    if verbose:
        print(f"       Parsed {len(events)} valid events")

    if not events:
        print("No valid events. Exiting.")
        return

    segmenter = SessionSegmenter()
    sessions = segmenter.segment(events)
    if verbose:
        print(f"\n[2/5] Segmented into {len(sessions)} sessions")

    grouper = FlowGrouper()
    all_flows = []
    for session in sessions:
        flows = grouper.group(session)
        all_flows.extend(flows)
    if verbose:
        print(f"\n[3/5] Grouped into {len(all_flows)} candidate flows")

    if not all_flows:
        if verbose:
            print("No flows found. Treating entire sessions as flows...")
        all_flows = sessions

    if verbose:
        print(f"\n[4/5] Labeling flows with rule-based heuristics...")
    journeys = []
    for i, flow in enumerate(all_flows):
        journey = label_flow_locally(flow)
        journeys.append(journey)
        if verbose:
            print(f"       Journey {i+1}: \"{journey.name}\" "
                  f"({journey.domain} > {journey.feature}) "
                  f"[confidence: {journey.confidence:.0%}]")

    db = Database(Path(db_path)) if db_path else Database()
    db.connect()
    for e in events:
        db.insert_event(e)
    for j in journeys:
        db.insert_journey(j)
    if verbose:
        print(f"\n[5/5] Stored {len(events)} events and {len(journeys)} journeys")
        print(f"       Database: {db.db_path}")
    db.close()

    if verbose:
        print(f"\n{'='*60}")
        print("  DISCOVERED JOURNEYS")
        print(f"{'='*60}")
        for j in journeys:
            print(f"\n  [{j.confidence:.0%}] {j.name}")
            print(f"       Domain: {j.domain} | Feature: {j.feature}")
            print(f"       Tags: {', '.join(j.tags)}")
            print(f"       Steps ({len(j.steps)}):")
            for s in j.steps:
                print(f"         {s.order}. {s.description}")

        print(f"\n{'='*60}")
        print(f"  Dashboard: python -m testai.server")
        print(f"  Then open: http://localhost:8000")
        print(f"{'='*60}\n")

    return journeys
