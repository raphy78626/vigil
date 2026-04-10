"""
Generate QA events for TWO completely different web apps to prove
Vigil is fully app-agnostic.

App 1: The Internet Herokuapp — login/logout flow (no data-testid, uses #id selectors)
App 2: TodoMVC (Playwright demo) — add/toggle/filter todos (no data-testid, uses class selectors)
"""

import json
import uuid
import time

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


def pageload(url, title, sid, t):
    return _event("pageload", url, title, sid, t,
                  navigation={"fromUrl": "", "toUrl": url, "trigger": "pageload"})


def nav(from_url, to_url, title, sid, t):
    return _event("navigation", to_url, title, sid, t,
                  navigation={"fromUrl": from_url, "toUrl": to_url, "trigger": "click"})


def click(url, title, text, tag, sid, t, css=None, test_id=None):
    return _event("click", url, title, sid, t, element={
        "tagName": tag,
        "selectors": {
            "css": css or tag,
            "text": text,
            "ariaLabel": None,
            "testId": test_id,
            "testIdAttr": None,
        },
        "inputType": None,
        "value": None,
    })


def inp(url, title, css, value, input_type, sid, t, name=None, placeholder=None):
    is_pw = input_type == "password"
    return _event("input", url, title, sid, t, element={
        "tagName": "input",
        "selectors": {
            "css": css,
            "text": None,
            "ariaLabel": None,
            "testId": None,
            "testIdAttr": None,
            "name": name,
            "placeholder": placeholder,
        },
        "inputType": input_type,
        "value": "[REDACTED]" if is_pw else value,
    })


def submit(url, title, css, sid, t):
    return _event("submit", url, title, sid, t, element={
        "tagName": "form",
        "selectors": {"css": css, "text": None, "ariaLabel": None, "testId": None},
        "inputType": None,
        "value": None,
    })


def build_events():
    events = []

    # ─────────────────────────────────────────────
    # APP 1: The Internet Herokuapp — Login/Logout
    # Uses: #id selectors, no data-testid
    # ─────────────────────────────────────────────
    BASE1 = "https://the-internet.herokuapp.com"
    s1 = str(uuid.uuid4())
    t = 0

    events += [
        pageload(f"{BASE1}/login", "The Internet", s1, t),

        inp(f"{BASE1}/login", "The Internet",
            "#username", "tomsmith", "text", s1, t + 3, name="username"),

        inp(f"{BASE1}/login", "The Internet",
            "#password", "", "password", s1, t + 6, name="password"),

        click(f"{BASE1}/login", "The Internet",
              "Login", "button", s1, t + 8,
              css="button.radius[type='submit']"),

        nav(f"{BASE1}/login", f"{BASE1}/secure", "The Internet", s1, t + 9),

        pageload(f"{BASE1}/secure", "The Internet", s1, t + 10),

        click(f"{BASE1}/secure", "The Internet",
              "Logout", "a", s1, t + 16,
              css="a[href='/logout']"),

        nav(f"{BASE1}/secure", f"{BASE1}/login", "The Internet", s1, t + 17),
    ]

    # ─────────────────────────────────────────────
    # APP 2: TodoMVC — Add, toggle, filter todos
    # Uses: class selectors, placeholder, no IDs
    # ─────────────────────────────────────────────
    BASE2 = "https://demo.playwright.dev/todomvc"
    s2 = str(uuid.uuid4())
    t = 100

    events += [
        pageload(f"{BASE2}/#/", "React • TodoMVC", s2, t),

        inp(f"{BASE2}/#/", "React • TodoMVC",
            "input.new-todo", "Buy groceries", "text", s2, t + 3,
            placeholder="What needs to be done?"),

        submit(f"{BASE2}/#/", "React • TodoMVC", "input.new-todo", s2, t + 5),

        inp(f"{BASE2}/#/", "React • TodoMVC",
            "input.new-todo", "Walk the dog", "text", s2, t + 8,
            placeholder="What needs to be done?"),

        submit(f"{BASE2}/#/", "React • TodoMVC", "input.new-todo", s2, t + 10),

        inp(f"{BASE2}/#/", "React • TodoMVC",
            "input.new-todo", "Read a book", "text", s2, t + 13,
            placeholder="What needs to be done?"),

        submit(f"{BASE2}/#/", "React • TodoMVC", "input.new-todo", s2, t + 15),

        click(f"{BASE2}/#/", "React • TodoMVC",
              "Buy groceries", "label", s2, t + 20,
              css="ul.todo-list li:first-child label"),

        click(f"{BASE2}/#/", "React • TodoMVC",
              "Active", "a", s2, t + 25,
              css="a[href='#/active']"),

        click(f"{BASE2}/#/", "React • TodoMVC",
              "Completed", "a", s2, t + 30,
              css="a[href='#/completed']"),

        click(f"{BASE2}/#/", "React • TodoMVC",
              "All", "a", s2, t + 35,
              css="a[href='#/']"),
    ]

    return events


if __name__ == "__main__":
    events = build_events()
    out_path = "/Users/rahil78626/Projects/TestAiPro/TestAI-Pro/backend/multiapp-events.json"
    with open(out_path, "w") as f:
        json.dump(events, f, indent=2)
    print(f"Generated {len(events)} events across 2 different apps → multiapp-events.json")
    print(f"  App 1: The Internet Herokuapp (login/logout) — {sum(1 for e in events if 'herokuapp' in e['url'])} events")
    print(f"  App 2: TodoMVC (add/toggle/filter) — {sum(1 for e in events if 'playwright' in e['url'])} events")
