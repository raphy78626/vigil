"""
Generate QA events for testing Vigil's OWN dashboard.
The ultimate dog-fooding: Vigil tests itself.

Flow captured:
  Session 1: Search + Browse journeys
    - Open dashboard
    - Type "checkout" in chat → Ask
    - Click a journey card
    - View steps → close modal
    - Change domain filter

  Session 2: Search + Export
    - Open dashboard
    - Type "login" in chat → Ask
    - Click a journey card
    - Click "Export Test" button
    - Close modal
"""

import json
import uuid
import time

BASE_URL = "http://localhost:8000"
NOW = time.time() * 1000


def ts(offset_seconds=0):
    return int(NOW + offset_seconds * 1000)


def _event(etype, url, title, session_id, t, **extra):
    e = {
        "type": etype,
        "url": url,
        "pageTitle": title,
        "id": str(uuid.uuid4()),
        "timestamp": ts(t),
        "sessionId": session_id,
        "tabId": 1,
    }
    e.update(extra)
    return e


def pageload(path, sid, t):
    url = BASE_URL + path
    return _event("pageload", url, "Vigil — Journey Dashboard", sid, t,
                  navigation={"fromUrl": "", "toUrl": url, "trigger": "pageload"})


def click(path, text, tag, sid, t, css=None):
    return _event("click", BASE_URL + path, "Vigil — Journey Dashboard", sid, t,
                  element={
                      "tagName": tag,
                      "selectors": {
                          "css": css or tag,
                          "text": text,
                          "ariaLabel": None,
                          "testId": None,
                          "testIdAttr": None,
                      },
                      "inputType": None,
                      "value": None,
                  })


def inp(path, css, value, input_type, sid, t, placeholder=None):
    return _event("input", BASE_URL + path, "Vigil — Journey Dashboard", sid, t,
                  element={
                      "tagName": "input",
                      "selectors": {
                          "css": css,
                          "text": None,
                          "ariaLabel": None,
                          "testId": None,
                          "testIdAttr": None,
                          "name": None,
                          "placeholder": placeholder,
                      },
                      "inputType": input_type,
                      "value": value,
                  })


def submit(path, css, sid, t):
    return _event("submit", BASE_URL + path, "Vigil — Journey Dashboard", sid, t,
                  element={
                      "tagName": "form",
                      "selectors": {"css": css, "text": None, "ariaLabel": None, "testId": None},
                      "inputType": None,
                      "value": None,
                  })


def build_events():
    events = []

    # ─────────────────────────────────────────────
    # SESSION 1: Search "checkout" + browse journey
    # ─────────────────────────────────────────────
    s1 = str(uuid.uuid4())
    t = 0

    events += [
        pageload("/", s1, t),

        # Type "checkout" in chat
        inp("/", "#chat-input", "checkout", "text", s1, t + 3,
            placeholder="Search journeys..."),
        # Click Ask button
        click("/", "Ask", "button", s1, t + 5,
              css="#chat-form button[type='submit']"),
        submit("/", "#chat-form", s1, t + 5),

        # Click first journey card
        click("/", "Add To Cart on Checkout", "div", s1, t + 10,
              css=".journey-card"),

        # Close modal
        click("/", "×", "button", s1, t + 16,
              css=".modal-close"),

        # Change domain filter
        click("/", "Authentication", "option", s1, t + 20,
              css="#domain-filter option"),
    ]

    # ─────────────────────────────────────────────
    # SESSION 2: Search "login" + export test
    # ─────────────────────────────────────────────
    s2 = str(uuid.uuid4())
    t = 100

    events += [
        pageload("/", s2, t),

        # Type "login" in chat
        inp("/", "#chat-input", "login", "text", s2, t + 4,
            placeholder="Search journeys..."),
        # Click Ask
        click("/", "Ask", "button", s2, t + 6,
              css="#chat-form button[type='submit']"),
        submit("/", "#chat-form", s2, t + 6),

        # Click journey card
        click("/", "Add To Cart on Login", "div", s2, t + 12,
              css=".journey-card"),

        # Click Export Test
        click("/", "↓ Export Test", "button", s2, t + 18,
              css=".export-btn"),

        # Close modal
        click("/", "×", "button", s2, t + 22,
              css=".modal-close"),
    ]

    return events


if __name__ == "__main__":
    events = build_events()
    out_path = "/Users/rahil78626/Projects/TestAiPro/Vigil/backend/self-test-events.json"
    with open(out_path, "w") as f:
        json.dump(events, f, indent=2)
    print(f"Generated {len(events)} events across 2 sessions → self-test-events.json")
    print(f"  Session 1: Search 'checkout' + browse journey ({sum(1 for e in events if e['sessionId'] == events[0]['sessionId'])} events)")
    print(f"  Session 2: Search 'login' + export test ({sum(1 for e in events if e['sessionId'] != events[0]['sessionId'])} events)")
