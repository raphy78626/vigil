"""Auth state management — generate and store auth.json per domain.

Usage:
    python -m testai auth https://any-app.example.com

Opens a browser → you log in → close the browser → auth saved.
That's it. No buttons, no inspector, no fuss.

Storage: ~/.vigil/auth/<domain>.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

AUTH_DIR = Path.home() / ".vigil" / "auth"


def _domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or parsed.path.split("/")[0]


def _auth_path(domain: str) -> Path:
    safe = domain.replace(":", "_").replace("/", "_")
    return AUTH_DIR / f"{safe}.json"


def list_saved() -> list[dict]:
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for f in sorted(AUTH_DIR.glob("*.json")):
        domain = f.stem.replace("_", ":")
        results.append({
            "domain": domain,
            "path": str(f),
            "size_bytes": f.stat().st_size,
        })
    return results


def get_auth_for_url(url: str) -> str | None:
    domain = _domain_from_url(url)
    p = _auth_path(domain)
    return str(p) if p.exists() else None


def save_auth_data(domain: str, data: dict | list | str) -> str:
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    p = _auth_path(domain)
    if isinstance(data, str):
        p.write_text(data)
    else:
        p.write_text(json.dumps(data, indent=2))
    return str(p)


def generate_auth_interactive(url: str) -> str:
    """Open a browser for manual login. Close browser when done = auth saved.

    Uses the system-installed Chrome (not Playwright's bundled Chromium) with a
    persistent profile so Google/OAuth providers don't block sign-in as
    "insecure browser".
    """
    from playwright.sync_api import sync_playwright

    domain = _domain_from_url(url)
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _auth_path(domain)

    user_data_dir = AUTH_DIR / "_browser_profile"
    user_data_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  Vigil — Auth Generator")
    print(f"  ─────────────────────────────")
    print(f"  App:    {url}")
    print(f"  Domain: {domain}\n")
    print(f"  1. Log in to your account in the browser")
    print(f"  2. When you're fully logged in, just CLOSE the browser")
    print(f"  3. Auth will be saved automatically\n")

    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                str(user_data_dir),
                headless=False,
                channel="chrome",
                viewport={"width": 1280, "height": 800},
                args=[
                    "--disable-blink-features=AutomationControlled",
                ],
                ignore_default_args=["--enable-automation"],
            )
        except Exception:
            context = p.chromium.launch_persistent_context(
                str(user_data_dir),
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=[
                    "--disable-blink-features=AutomationControlled",
                ],
                ignore_default_args=["--enable-automation"],
            )

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url)

        try:
            page.wait_for_event("close", timeout=300_000)
        except Exception:
            pass

        context.storage_state(path=str(out_path))

        try:
            context.close()
        except Exception:
            pass

    size = out_path.stat().st_size if out_path.exists() else 0
    print(f"\n  Auth saved! ({size} bytes)")
    print(f"  File: {out_path}")
    print(f"\n  Now replay with auth:")
    print(f"    The dashboard will auto-detect it — just enter the base URL and hit Run.\n")
    return str(out_path)


def main():
    if len(sys.argv) < 2:
        print("\n  Vigil — Auth State Manager\n")
        print("  Generate auth for any app:")
        print("    python -m testai auth https://app.example.com\n")
        print("  Saved auth states:")
        saved = list_saved()
        for a in saved:
            print(f"    {a['domain']:40s}  {a['path']}")
        if not saved:
            print("    (none)")
        print()
        return

    url = sys.argv[1]
    if not url.startswith("http"):
        url = f"https://{url}"
    generate_auth_interactive(url)


if __name__ == "__main__":
    main()
