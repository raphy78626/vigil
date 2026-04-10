"""Page analyzer — extract interactive elements and capture screenshots."""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING, List, Optional

from testai.explorer.models import InteractiveElement, PageSnapshot

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

_EXTRACT_ELEMENTS_JS = """
() => {
    const results = [];
    const seen = new Set();

    const interactiveTags = new Set([
        'a', 'button', 'input', 'select', 'textarea', 'details', 'summary'
    ]);
    const interactiveRoles = new Set([
        'button', 'link', 'tab', 'menuitem', 'option', 'checkbox',
        'radio', 'switch', 'textbox', 'combobox', 'searchbox',
        'slider', 'spinbutton', 'listbox', 'menu', 'menubar',
        'navigation', 'tablist'
    ]);

    function isVisible(el) {
        if (!el.offsetParent && el.tagName !== 'BODY' && el.tagName !== 'HTML')
            return false;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        const s = getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0')
            return false;
        return true;
    }

    function getCssSelector(el) {
        if (el.id) return '#' + CSS.escape(el.id);
        if (el.dataset.testid) return `[data-testid="${el.dataset.testid}"]`;
        if (el.dataset.test) return `[data-test="${el.dataset.test}"]`;

        let path = el.tagName.toLowerCase();
        if (el.className && typeof el.className === 'string') {
            const cls = el.className.trim().split(/\\s+/).slice(0, 2).map(c => '.' + CSS.escape(c)).join('');
            if (cls) path += cls;
        }
        return path;
    }

    function getText(el) {
        const direct = el.textContent || '';
        return direct.trim().substring(0, 100);
    }

    const allElements = document.querySelectorAll(
        'a, button, input, select, textarea, [role], [onclick], [tabindex], ' +
        'details > summary, [data-testid], [data-test], [data-cy]'
    );

    let idx = 0;
    for (const el of allElements) {
        if (!isVisible(el)) continue;

        const tag = el.tagName.toLowerCase();
        const role = el.getAttribute('role') || '';
        const href = el.getAttribute('href') || '';
        const ariaLabel = el.getAttribute('aria-label') || '';

        // Skip non-interactive elements without interactive roles
        const isInteractive = interactiveTags.has(tag) ||
            interactiveRoles.has(role) ||
            el.hasAttribute('onclick') ||
            el.hasAttribute('tabindex') ||
            el.hasAttribute('data-testid');

        if (!isInteractive) continue;

        // Skip tiny or offscreen elements
        const rect = el.getBoundingClientRect();
        if (rect.width < 5 || rect.height < 5) continue;
        if (rect.top > window.innerHeight + 200) continue;

        // Skip anchors to same page or javascript:void
        if (tag === 'a' && (href === '#' || href === 'javascript:void(0)'))
            continue;

        const key = tag + '|' + (el.id || '') + '|' + getText(el).substring(0, 40) + '|' + href;
        if (seen.has(key)) continue;
        seen.add(key);

        results.push({
            index: idx++,
            tag: tag,
            role: role || (tag === 'a' ? 'link' : tag === 'button' ? 'button' : ''),
            text: getText(el),
            href: href,
            placeholder: el.getAttribute('placeholder') || '',
            aria_label: ariaLabel,
            input_type: el.getAttribute('type') || '',
            name: el.getAttribute('name') || '',
            css_selector: getCssSelector(el),
            bounding_box: {
                x: rect.x, y: rect.y,
                width: rect.width, height: rect.height
            }
        });

        if (idx >= 80) break;
    }
    return results;
}
"""


async def extract_elements(page: Page) -> List[InteractiveElement]:
    """Extract all interactive elements from the current page."""
    try:
        raw = await page.evaluate(_EXTRACT_ELEMENTS_JS)
    except Exception as e:
        logger.warning("Element extraction failed: %s", e)
        return []

    elements = []
    for item in raw:
        elements.append(InteractiveElement(
            index=item["index"],
            tag=item["tag"],
            role=item.get("role", ""),
            text=item.get("text", ""),
            href=item.get("href", ""),
            placeholder=item.get("placeholder", ""),
            aria_label=item.get("aria_label", ""),
            input_type=item.get("input_type", ""),
            name=item.get("name", ""),
            css_selector=item.get("css_selector", ""),
            bounding_box=item.get("bounding_box"),
        ))
    return elements


async def capture_screenshot(page: Page) -> Optional[str]:
    """Capture a screenshot and return base64-encoded PNG."""
    try:
        raw = await page.screenshot(type="png", full_page=False, timeout=10000)
        return base64.b64encode(raw).decode()
    except Exception as e:
        logger.warning("Screenshot capture failed: %s", e)
        return None


async def take_snapshot(page: Page, with_screenshot: bool = True) -> PageSnapshot:
    """Capture a full page snapshot: URL, title, elements, and optional screenshot."""
    url = page.url
    try:
        title = await page.title()
    except Exception:
        title = ""

    elements = await extract_elements(page)
    screenshot = await capture_screenshot(page) if with_screenshot else None

    from datetime import datetime, timezone
    return PageSnapshot(
        url=url,
        title=title,
        elements=elements,
        screenshot_b64=screenshot,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
