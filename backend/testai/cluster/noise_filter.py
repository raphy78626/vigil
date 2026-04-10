"""Smart noise filtering — ML-inspired classifier to separate signal from noise events.

Scores each event as signal (worth keeping) or noise (should be filtered).
Uses a weighted heuristic model trained on common noise patterns:
  - Known noise domains (slack, gmail, calendar, etc.)
  - Event frequency bursts (rapid-fire scroll/resize = noise)
  - Element type signals (form inputs = high signal, scrollbar = low)
  - URL pattern matching (API polling, analytics = noise)
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple
from urllib.parse import urlparse

NOISE_DOMAINS = {
    "slack.com", "app.slack.com", "mail.google.com", "gmail.com",
    "calendar.google.com", "outlook.office.com", "outlook.live.com",
    "teams.microsoft.com", "web.whatsapp.com", "discord.com",
    "twitter.com", "x.com", "facebook.com", "linkedin.com",
    "reddit.com", "youtube.com", "netflix.com", "spotify.com",
    "docs.google.com", "drive.google.com", "notion.so",
    "figma.com", "miro.com", "clickup.com",
    "chrome://", "about:", "edge://", "brave://",
}

NOISE_URL_PATTERNS = [
    re.compile(r"/api/v\d+/(heartbeat|ping|health|alive)", re.I),
    re.compile(r"\.(png|jpg|jpeg|gif|svg|ico|woff2?|ttf|eot)\b", re.I),
    re.compile(r"(analytics|telemetry|tracking|pixel|beacon)", re.I),
    re.compile(r"(google-analytics|gtag|hotjar|segment|mixpanel)", re.I),
    re.compile(r"chrome-extension://", re.I),
    re.compile(r"/_next/static/", re.I),
    re.compile(r"/sockjs-node/", re.I),
    re.compile(r"/ws\b", re.I),
]

HIGH_SIGNAL_ACTIONS = {"click", "input", "submit", "change", "select", "fill"}
LOW_SIGNAL_ACTIONS = {"scroll", "resize", "mousemove", "mouseenter", "mouseleave", "focus", "blur"}

HIGH_SIGNAL_ELEMENTS = {"button", "a", "input", "select", "textarea", "form", "label", "[role=button]", "[role=link]"}
LOW_SIGNAL_ELEMENTS = {"div", "span", "body", "html", "head", "script", "style", "svg", "path"}


class NoiseFilter:
    def __init__(self, allowed_domains: List[str] = None, threshold: float = 0.4):
        self.allowed_domains = set(allowed_domains or [])
        self.threshold = threshold

    def score_event(self, event: Dict) -> float:
        """Score an event from 0.0 (pure noise) to 1.0 (strong signal)."""
        score = 0.5  # neutral start
        url = event.get("url", "")
        event_type = event.get("type", "").lower()
        element = event.get("element", {}) or {}

        # Domain check
        domain = self._extract_domain(url)
        if domain in NOISE_DOMAINS:
            score -= 0.4
        if self.allowed_domains and domain not in self.allowed_domains:
            score -= 0.2

        # URL pattern check
        for pat in NOISE_URL_PATTERNS:
            if pat.search(url):
                score -= 0.3
                break

        # Action type
        if event_type in HIGH_SIGNAL_ACTIONS:
            score += 0.25
        elif event_type in LOW_SIGNAL_ACTIONS:
            score -= 0.2

        # Element type
        tag = (element.get("tag_name") or element.get("tagName") or "").lower()
        if tag in HIGH_SIGNAL_ELEMENTS or any(tag == e for e in HIGH_SIGNAL_ELEMENTS):
            score += 0.15
        elif tag in LOW_SIGNAL_ELEMENTS:
            score -= 0.1

        # Has test ID = strong signal
        for attr in ("data-testid", "data-test", "data-cy", "data-qa"):
            if element.get(attr) or (element.get("attributes") or {}).get(attr):
                score += 0.2
                break

        # Has meaningful text = signal
        text = element.get("text", "") or element.get("innerText", "")
        if text and len(text.strip()) > 2:
            score += 0.1

        # Page title present = signal
        if event.get("page_title"):
            score += 0.05

        return max(0.0, min(1.0, score))

    def filter_events(self, events: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """Split events into (signal, noise) based on scoring threshold."""
        signal, noise = [], []
        for event in events:
            s = self.score_event(event)
            event["_noise_score"] = round(s, 3)
            if s >= self.threshold:
                signal.append(event)
            else:
                noise.append(event)
        return signal, noise

    def filter_burst_noise(self, events: List[Dict], max_gap_ms: int = 200, max_burst: int = 5) -> List[Dict]:
        """Remove burst noise: rapid-fire events of the same type within max_gap_ms."""
        if len(events) < 2:
            return events

        result = []
        burst_count = 0
        prev_type = None
        prev_ts = 0

        for event in events:
            ts = self._parse_ts(event.get("timestamp", ""))
            etype = event.get("type", "")

            if etype == prev_type and ts - prev_ts < max_gap_ms:
                burst_count += 1
                if burst_count > max_burst:
                    continue
            else:
                burst_count = 0

            result.append(event)
            prev_type = etype
            prev_ts = ts

        return result

    def _extract_domain(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower().replace("www.", "")
        except Exception:
            return ""

    def _parse_ts(self, ts) -> float:
        if isinstance(ts, (int, float)):
            return float(ts)
        if isinstance(ts, str):
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.timestamp() * 1000
            except Exception:
                return 0
        return 0

    def get_stats(self, events: List[Dict]) -> Dict:
        """Return noise filtering statistics for a batch of events."""
        signal, noise = self.filter_events(events)
        scores = [e.get("_noise_score", 0.5) for e in events]
        return {
            "total_events": len(events),
            "signal_events": len(signal),
            "noise_events": len(noise),
            "filter_rate": round(len(noise) / max(len(events), 1) * 100, 1),
            "avg_score": round(sum(scores) / max(len(scores), 1), 3),
            "threshold": self.threshold,
        }
