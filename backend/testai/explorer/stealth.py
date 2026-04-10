"""Stealth browser launcher — anti-detection and human-like behavior."""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)

_STEALTH_JS = """
() => {
    // Remove webdriver flag
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // Chrome runtime
    window.chrome = window.chrome || {};
    window.chrome.runtime = window.chrome.runtime || {};

    // Languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en']
    });

    // Plugins — simulate real Chrome
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5]
    });

    // Permissions API
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);

    // WebGL vendor
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter.call(this, parameter);
    };
}
"""

_OVERLAY_CSS = """
[class*="cookie"], [id*="cookie"], [id*="onetrust"], #onetrust-banner-sdk,
[class*="consent"], [class*="gdpr"], [class*="cc-banner"], .cc-window,
[class*="intercom"], #intercom-container, [class*="drift"],
[class*="popup"][class*="overlay"], [class*="modal-backdrop"],
[class*="notification-banner"], [class*="promo-banner"],
[class*="announcement"], [class*="snackbar"], [class*="toast"],
[class*="onboarding"], [class*="walkthrough"], [class*="tour"],
[role="dialog"][class*="overlay"], [role="alertdialog"],
[class*="chat-widget"], [class*="chatbot"], #hubspot-messages-iframe-container
{ display: none !important; visibility: hidden !important;
  opacity: 0 !important; pointer-events: none !important; }
"""

_OVERLAY_OBSERVER_JS = """
(function() {
    if (window.__testai_overlay_observer) return;
    const SELS = [
        '[class*="cookie"]', '[id*="cookie"]', '[class*="consent"]',
        '[class*="gdpr"]', '[class*="overlay"][class*="popup"]',
        '[class*="intercom"]', '[class*="drift"]', '[class*="modal-backdrop"]',
        '[class*="notification-banner"]', '[class*="chat-widget"]',
        '[role="dialog"]', '[role="alertdialog"]'
    ];
    function hide(el) {
        el.style.setProperty('display', 'none', 'important');
        el.style.setProperty('visibility', 'hidden', 'important');
    }
    const obs = new MutationObserver(muts => {
        for (const m of muts) {
            for (const n of m.addedNodes) {
                if (n.nodeType !== 1) continue;
                for (const s of SELS) {
                    if (n.matches && n.matches(s)) { hide(n); break; }
                    n.querySelectorAll && n.querySelectorAll(s).forEach(hide);
                }
            }
        }
    });
    obs.observe(document.body || document.documentElement,
                { childList: true, subtree: true });
    window.__testai_overlay_observer = obs;
})();
"""

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


async def launch_stealth_browser(
    pw: Playwright,
    auth_state: Optional[str] = None,
    headed: bool = True,
) -> BrowserContext:
    """Launch a stealth Chromium context that resists bot detection."""
    viewport_w = 1280 + random.randint(-20, 20)
    viewport_h = 800 + random.randint(-10, 10)
    ua = random.choice(USER_AGENTS)

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--disable-infobars",
        "--disable-background-timer-throttling",
        "--disable-popup-blocking",
    ]

    try:
        browser = await pw.chromium.launch(
            channel="chrome",
            headless=not headed,
            args=launch_args,
        )
    except Exception:
        browser = await pw.chromium.launch(
            headless=not headed,
            args=launch_args,
        )

    ctx_kwargs = {
        "viewport": {"width": viewport_w, "height": viewport_h},
        "user_agent": ua,
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "bypass_csp": True,
    }

    if auth_state and Path(auth_state).exists():
        ctx_kwargs["storage_state"] = auth_state

    context = await browser.new_context(**ctx_kwargs)
    return context


async def apply_stealth(page: Page) -> None:
    """Apply stealth patches and overlay immunity to a page."""
    try:
        await page.add_init_script(_STEALTH_JS)
    except Exception:
        pass

    try:
        await page.add_style_tag(content=_OVERLAY_CSS)
    except Exception:
        pass

    try:
        await page.evaluate(_OVERLAY_OBSERVER_JS)
    except Exception:
        pass


async def inject_overlay_shield(page: Page) -> None:
    """Re-inject overlay immunity after navigation."""
    try:
        await page.add_style_tag(content=_OVERLAY_CSS)
    except Exception:
        pass
    try:
        await page.evaluate(_OVERLAY_OBSERVER_JS)
    except Exception:
        pass


async def sweep_overlays(page: Page) -> None:
    """Proactively dismiss visible overlays by clicking dismiss buttons."""
    dismiss_js = """
    () => {
        const btns = document.querySelectorAll(
            'button, [role="button"], a'
        );
        const dismiss = ['accept', 'close', 'dismiss', 'got it', 'ok',
                         'i agree', 'no thanks', 'maybe later', 'skip',
                         'continue', 'allow', 'deny', 'reject'];
        for (const b of btns) {
            const txt = (b.textContent || '').trim().toLowerCase();
            if (dismiss.some(d => txt.includes(d)) && b.offsetParent) {
                try { b.click(); } catch(e) {}
            }
        }
    }
    """
    try:
        await page.evaluate(dismiss_js)
    except Exception:
        pass


async def human_delay(min_ms: int = 200, max_ms: int = 800) -> None:
    """Add a randomized human-like delay between actions."""
    delay = random.randint(min_ms, max_ms) / 1000.0
    await asyncio.sleep(delay)
