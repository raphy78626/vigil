"""Playwright Test Generator — clean, auto-healing, webapp-agnostic.

Architecture:
  - conftest.py  — all shared helpers (_heal, _shot, overlay machinery, fixtures)
  - test_*.py    — thin test file: imports, one test function, step-by-step actions

Generated tests are ~60-100 lines regardless of journey length.
All heavy machinery (400+ lines) lives in conftest.py — written once, shared by all tests.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse
from typing import List, Optional

from testai.models.journey import Journey
from testai.models.step import Step


# ---------------------------------------------------------------------------
# Constants & patterns
# ---------------------------------------------------------------------------

_REACT_ID_RE = re.compile(r"^#?:[a-z0-9]+:$")
_REACT_ID_IN_SELECTOR = re.compile(r"#?:[a-z0-9]+:")
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_TOTAL_PH = "__TOTAL_STEPS__"


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _relative_path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return path


def _base_origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""


def _glob_path(path: str) -> str:
    """Replace UUIDs with globs and strip query params for flexible URL matching."""
    result = _UUID_RE.sub("*", path)
    if "?" in result:
        result = result.split("?")[0]
    return result


# ---------------------------------------------------------------------------
# Selector helpers
# ---------------------------------------------------------------------------

def _is_react_id(css: str) -> bool:
    return bool(_REACT_ID_RE.match(css.strip()))


_TRANSIENT_CSS_PATTERNS = (
    'inline-preview-player', 'video-stream', 'html5-main-video',
    'ytp-popup', 'ytp-tooltip', 'preview-overlay', 'hover-overlay',
)

_VALID_CSS_PSEUDOS = frozenset([
    'hover', 'focus', 'active', 'visited', 'link', 'checked', 'disabled',
    'enabled', 'first-child', 'last-child', 'first-of-type', 'last-of-type',
    'only-child', 'only-of-type', 'root', 'empty', 'target', 'not', 'is',
    'has', 'where', 'any', 'nth-child', 'nth-of-type', 'nth-last-child',
    'nth-last-of-type', 'focus-within', 'focus-visible', 'placeholder-shown',
    'read-only', 'read-write', 'required', 'optional', 'valid', 'invalid',
    'in-range', 'out-of-range', 'lang', 'dir', 'global', 'local',
])

_ID_COLON_SUFFIX_RE = re.compile(r'^#([\w-]+)(?::([\w-]+))+$')


def _fix_colon_id(css: str) -> str:
    """Convert #id:suffix to [id="id:suffix"] when the suffix is not a CSS pseudo-class."""
    m = _ID_COLON_SUFFIX_RE.match(css)
    if not m:
        return css
    raw_id = css[1:]
    parts = raw_id.split(':')
    suffixes = parts[1:]
    if all(s in _VALID_CSS_PSEUDOS for s in suffixes):
        return css
    return f'[id="{raw_id}"]'


_HASH_CLASS_RE = re.compile(r'\.[a-z][A-Za-z0-9_-]{4,7}(?![A-Za-z0-9_-])')


def _looks_like_hash_class(cls: str) -> bool:
    """Detect CSS-in-JS hashed class names (styled-components, emotion, CSS modules).

    Pattern: starts with lowercase, 5-8 chars (allowing hyphens), has at least
    one uppercase letter. Examples: .jfOktf, .ljUXWM, .cRqA-DA
    """
    name = cls.lstrip('.')
    if not (5 <= len(name) <= 8):
        return False
    if not name[0].islower():
        return False
    return any(c.isupper() for c in name)


def _strip_hash_classes(css: str) -> str:
    """Remove CSS-in-JS hashed class names, keeping tag names and structure."""
    result = _HASH_CLASS_RE.sub(
        lambda m: '' if _looks_like_hash_class(m.group(0)) else m.group(0),
        css,
    )
    return result.strip()


def _sanitize_css(css: str, has_alt: bool = False) -> str:
    if not css:
        return css
    if _is_react_id(css):
        return ""
    if _REACT_ID_IN_SELECTOR.search(css):
        return ""
    css = _fix_colon_id(css)
    css = _strip_hash_classes(css)
    if not css:
        return ""
    css_lower = css.lower()
    if any(p in css_lower for p in _TRANSIENT_CSS_PATTERNS):
        return ""
    if css_lower.strip().endswith('> video') or css_lower.strip() == 'video':
        return ""

    parts = css.split(" > ")
    svg_tags = {"svg", "path", "rect", "circle", "line", "polyline",
                "polygon", "ellipse", "g", "use"}
    while parts and any(parts[-1].strip().startswith(t) for t in svg_tags):
        parts.pop()
    if not parts:
        return css

    # Remove empty parts left by hash class stripping
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return ""

    clean = " > ".join(parts)
    nth_count = clean.count("nth-child")
    if nth_count > 5 and len(clean) > 120:
        for i, p in enumerate(parts):
            if p.strip().startswith("#") or p.strip().startswith("[data-"):
                clean = " > ".join(parts[i:])
                break
    return clean


def _field_key(step: Step) -> str:
    return step.selectors.get("test_id") or step.selectors.get("css", "")


# ---------------------------------------------------------------------------
# Auto-healing locator chain  — 6 strategies only
# ---------------------------------------------------------------------------

_UNIQUE_INPUT_TYPES = frozenset({"email", "search", "tel", "url", "date", "time", "number", "color", "range"})


# Tags that are too common to use as bare CSS selectors
_BARE_TAG_RE = re.compile(
    r'^(a|button|div|span|li|ul|ol|p|h[1-6]|section|article|nav|main|header|'
    r'footer|aside|form|table|tr|td|th|img|input|select|textarea|label)$'
)


def _is_generic_css(css: str) -> bool:
    """Return True if the CSS selector is too generic to reliably identify an element.

    Bare tags ('a', 'button'), bare tags with only nth-child positioning,
    or single-class selectors that resolve to just a tag are all dangerous.
    """
    if not css:
        return False
    stripped = css.strip()
    # Bare tag name
    if _BARE_TAG_RE.match(stripped):
        return True
    parts = stripped.split(' > ')
    last = parts[-1].strip() if parts else ''
    tag_part = last.split(':')[0].split('.')[0].split('[')[0].strip()
    # Tag with only nth-child positioning (e.g., "div > a:nth-child(2)")
    if _BARE_TAG_RE.match(tag_part) and ':nth-child' in last and len(parts) <= 2:
        return True
    # All-bare-tag chains like "li > a", "div > span" after hash class stripping
    if len(parts) >= 2:
        all_bare = all(
            _BARE_TAG_RE.match(p.strip().split(':')[0].split('.')[0].split('#')[0].split('[')[0].strip())
            for p in parts
        )
        has_no_qualifiers = not any(
            '.' in p or '#' in p or '[' in p for p in parts
        )
        if all_bare and has_no_qualifiers:
            return True
    return False


def _locator_chain(step: Step) -> List[str]:
    """Return an ordered list of Playwright locator expressions for a step.

    11 strategies, in priority order:
      1. test_id      (data-testid / data-cy / data-qa)
      2. role + name  (get_by_role with text or aria-label)
      3. label        (get_by_label — best for form inputs)
      4. aria_label   (locator by attribute)
      5. name attr    (stable for all HTML forms)
      6. placeholder  (stable for inputs — moved up)
      7. href         (links only)
      8. css          (stable, sanitized CSS selector)
      9. text         (visible text fallback)
      10. title       (fallback for icon buttons)
      11. input_type  (only unique types: email, search, etc.)
    """
    s = step.selectors
    test_id = s.get("test_id")
    test_id_attr = s.get("test_id_attr") or "data-testid"
    text = (s.get("text") or "").strip()
    placeholder = (s.get("placeholder") or "").strip()
    role = (s.get("role") or "").strip()
    label = (s.get("label") or "").strip()
    aria_label = (s.get("ariaLabel") or "").strip()
    name_attr = (s.get("name") or "").strip()
    href = (s.get("href") or "").strip()
    title = (s.get("title") or "").strip()
    input_type = (s.get("input_type") or "").strip().lower()
    tag_name = (s.get("tagName") or s.get("tag") or "").strip().lower()
    has_alt = bool(test_id or text or placeholder or role or label or aria_label)
    css = _sanitize_css(s.get("css", ""), has_alt=has_alt)

    attr = test_id_attr
    clean_id = (test_id or "").replace('"', '\\"')
    clean_tx = text.replace('"', '\\"') if text else ""

    chain: List[str] = []

    # 1. test_id
    if test_id:
        chain.append(f'page.locator("[{attr}=\\"{clean_id}\\"]")')

    # 2. role + name
    if role and (text or aria_label):
        name = (text if text else aria_label)[:80]
        safe_role = role.replace('"', '\\"')
        safe_name = name.replace('"', '\\"')
        chain.append(f'page.get_by_role("{safe_role}", name="{safe_name}")')

    # 3. label (best for form inputs)
    if label and len(label) <= 80:
        safe_label = label.replace('"', '\\"')
        chain.append(f'page.get_by_label("{safe_label}")')

    # 4. aria_label
    if aria_label and len(aria_label) <= 80:
        safe_aria = aria_label.replace('"', '\\"')
        chain.append(f'page.locator("[aria-label=\\"{safe_aria}\\"]")')

    # 5. name attribute (stable for all HTML forms)
    if name_attr and len(name_attr) <= 80:
        safe_name_attr = name_attr.replace('"', '\\"')
        chain.append(f'page.locator("[name=\\"{safe_name_attr}\\"]")')

    # 6. placeholder (moved up — stable for inputs)
    if placeholder:
        safe_ph = placeholder.replace('"', '\\"')
        chain.append(f'page.get_by_placeholder("{safe_ph}").first')

    # 7. href (links only — high priority when it's a real path)
    if href and len(href) <= 200:
        safe_href = href.replace('"', '\\"')
        chain.append(f'page.locator("a[href=\\"{safe_href}\\"]")')

    # 8. css (skip dangerously generic selectors)
    if css and not _is_generic_css(css):
        safe_css = css.replace('"', '\\"')
        chain.append(f'page.locator("{safe_css}").first')

    # 9. text
    if text and len(text) <= 80:
        chain.append(f'page.get_by_text("{clean_tx}", exact=True).first')

    # 10. title (fallback for icon buttons)
    if title and len(title) <= 80:
        safe_title = title.replace('"', '\\"')
        chain.append(f'page.locator("[title=\\"{safe_title}\\"]")')

    # 11. input_type (only for unique/unambiguous types)
    if input_type in _UNIQUE_INPUT_TYPES:
        chain.append(f'page.locator("input[type=\\"{input_type}\\"]")')

    # 12. href-scoped text match (for links with both href and visible text)
    #     This disambiguates generic links by combining two signals
    if href and text and tag_name == "a" and len(href) <= 200 and len(text) <= 80:
        safe_href = href.replace('"', '\\"')
        chain.append(
            f'page.locator("a[href=\\"{safe_href}\\"]").filter(has_text="{clean_tx}").first'
        )

    # 13. visibleText fallback (captures descendant text unlike getDirectText)
    visible_text = (s.get("visibleText") or "").strip()
    if visible_text and visible_text != text and len(visible_text) <= 80:
        safe_vt = visible_text.replace('"', '\\"')
        chain.append(f'page.get_by_text("{safe_vt}", exact=True).first')

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: List[str] = []
    for loc in chain:
        if loc not in seen:
            seen.add(loc)
            unique.append(loc)

    # Fallback when nothing resolved
    if not unique:
        if text and len(text) <= 80:
            unique.append(f'page.get_by_text("{clean_tx}", exact=True).first')
        elif aria_label and len(aria_label) <= 80:
            safe_aria = aria_label.replace('"', '\\"')
            unique.append(f'page.locator("[aria-label=\\"{safe_aria}\\"]").first')
        elif step.action_type == "fill_form":
            unique.append('page.get_by_role("textbox").first')
        elif css:
            raw_css = s.get("css", "").replace('"', '\\"')
            unique.append(f'page.locator("{raw_css}").first')
        else:
            unique.append('page.locator("body").first')

    return unique


def _primary_locator(step: Step) -> str:
    chain = _locator_chain(step)
    return chain[0] if chain else 'page.locator("SELECTOR_NEEDED")'


_CREDENTIAL_FIELDS = {"password", "email", "username", "user", "login",
                       "phone", "token", "secret", "key", "code", "otp"}


def _is_credential_field(step: Step) -> bool:
    """Detect if a fill_form step targets a credential field."""
    s = step.selectors
    if s.get("input_type") == "password":
        return True
    name = (s.get("name") or s.get("label") or s.get("placeholder") or "").lower()
    return any(kw in name for kw in _CREDENTIAL_FIELDS)


def _fill_value(step: Step) -> str:
    s = step.selectors
    val = s.get("value") or ""
    raw_key = (s.get("test_id") or s.get("name") or s.get("label")
               or s.get("placeholder") or "")
    if not raw_key or _is_react_id(raw_key):
        raw_key = s.get("css", "field")
    field_key = re.sub(r"[^a-z0-9]", "_", raw_key)
    env_key = re.sub(r"[^A-Z0-9]", "_", field_key.upper()).strip("_")
    is_redacted = val in ("[REDACTED]", "")
    if is_redacted:
        return f'os.environ.get("{env_key}", "")'
    safe_val = val.replace('"', '\\"')
    # Auto-parameterize non-credential values with a unique suffix per run
    if not _is_credential_field(step) and val and val not in ("[REDACTED]", ""):
        return f'os.environ.get("{env_key}", "{safe_val}") + "_" + _RUN_ID'
    return f'os.environ.get("{env_key}", "{safe_val}")'


# ---------------------------------------------------------------------------
# Step deduplication
# ---------------------------------------------------------------------------

def _clean_segment(seg: List[Step]) -> List[Step]:
    if not seg:
        return seg
    first_attempt_fills: set[int] = set()
    for j, step in enumerate(seg):
        if step.action_type != "fill_form":
            continue
        key = _field_key(step)
        for k in range(j + 1, len(seg)):
            if seg[k].action_type == "fill_form" and _field_key(seg[k]) == key:
                if not any(seg[m].action_type == "submit" for m in range(j + 1, k)):
                    first_attempt_fills.add(j)
                break
    fields_seen_before: set[str] = set()
    failed_clicks: set[int] = set()
    for j, step in enumerate(seg):
        if step.action_type == "fill_form":
            fields_seen_before.add(_field_key(step))
        elif step.action_type == "click":
            retry_after = any(
                _field_key(seg[k]) in fields_seen_before
                for k in range(j + 1, len(seg))
                if seg[k].action_type == "fill_form"
            )
            if retry_after:
                failed_clicks.add(j)
    return [
        step for j, step in enumerate(seg)
        if j not in first_attempt_fills and j not in failed_clicks
    ]


def _dedup_progressive_fills(steps: List[Step]) -> List[Step]:
    if not steps:
        return steps
    result: List[Step] = []
    i = 0
    while i < len(steps):
        step = steps[i]
        if step.action_type == "fill_form":
            key = _field_key(step)
            last = step
            j = i + 1
            # Only collapse consecutive fills with NO intervening navigate/submit
            while (j < len(steps)
                   and steps[j].action_type == "fill_form"
                   and _field_key(steps[j]) == key
                   and not any(steps[k].action_type in ("navigate", "submit")
                               for k in range(i, j))):
                last = steps[j]
                j += 1
            result.append(last)
            i = j
        else:
            result.append(step)
            i += 1
    return result


def _dedup_consecutive_clicks(steps: List[Step]) -> List[Step]:
    """Collapse runs of identical clicks on the same element into a single click."""
    if not steps:
        return steps
    result: List[Step] = []
    i = 0
    while i < len(steps):
        step = steps[i]
        if step.action_type in ("click", "dblclick"):
            key = _field_key(step)
            last_idx = i
            j = i + 1
            while j < len(steps) and steps[j].action_type in ("click", "dblclick") and _field_key(steps[j]) == key:
                last_idx = j
                j += 1
            result.append(steps[last_idx])
            i = j
        else:
            result.append(step)
            i += 1
    return result


def _dedup_prefill_keypresses(steps: List[Step]) -> List[Step]:
    """Remove Backspace/Delete keypresses immediately before a fill (fill() clears anyway)."""
    if not steps:
        return steps
    _CLEAR_KEYS = frozenset(["Backspace", "Delete", ""])
    result: List[Step] = []
    i = 0
    while i < len(steps):
        step = steps[i]
        if step.action_type == "keypress":
            key = step.selectors.get("key", "")
            if key in _CLEAR_KEYS:
                j = i + 1
                while j < len(steps) and steps[j].action_type == "keypress":
                    j += 1
                if j < len(steps) and steps[j].action_type == "fill_form":
                    i = j
                    continue
        result.append(step)
        i += 1
    return result


_NOISE_CSS_PARTS = (
    'ytp-', 'seek-slider', 'skip-button', 'skip-ad', 'ad-skip',
    'mute-button', 'play-button', 'fullscreen-button', 'progress-bar',
    'logo-icon', 'logo-container', 'volume-',
)
_NOISE_ARIA_PARTS = (
    'seek slider', 'volume', 'mute', 'full screen', 'fullscreen',
    'mini player', 'miniplayer', 'subtitles',
    'closed captions', 'autoplay', 'theater mode', 'next video',
)
_NOISE_TEXT_EXACT = frozenset(('skip', 'skip ad', 'skip ads'))


def _filter_noise_steps(steps: List[Step]) -> List[Step]:
    """Remove video player controls, ad overlays, checkbox artifacts, and UI chrome."""
    result: List[Step] = []
    for step in steps:
        # Checkbox artifacts: Select 'true'/'false' and Type 'on'/'off' on React IDs
        # These are browser side-effects of clicking a checkbox label, not real actions.
        if step.action_type in ("select", "fill_form"):
            css = step.selectors.get("css") or ""
            val = (step.selectors.get("value") or "").lower()
            if _REACT_ID_IN_SELECTOR.search(css) and val in ("true", "false", "on", "off"):
                continue

        if step.action_type not in ("click", "dblclick"):
            result.append(step)
            continue
        css = (step.selectors.get("css") or "").lower()
        aria = (step.selectors.get("ariaLabel") or step.description or "").lower()
        txt = (step.selectors.get("text") or "").lower().strip()
        if any(p in css for p in _NOISE_CSS_PARTS):
            continue
        if any(p in aria for p in _NOISE_ARIA_PARTS):
            continue
        if txt in _NOISE_TEXT_EXACT:
            continue
        # SVG-only icon clicks with no identifying text/aria — usually UI chrome
        if not txt and not step.selectors.get("ariaLabel") and not step.selectors.get("text"):
            raw_css = (step.selectors.get("css") or "")
            sanitized = _sanitize_css(raw_css, has_alt=False)
            if not sanitized or _is_generic_css(sanitized):
                tag = (step.selectors.get("tagName") or "").lower()
                if tag in ("svg", "path", "circle") or raw_css.rstrip().endswith("svg"):
                    continue
        result.append(step)
    return result


def _dedup_steps(steps: List[Step]) -> List[Step]:
    steps = _filter_noise_steps(steps)
    steps = _dedup_progressive_fills(steps)
    steps = _dedup_consecutive_clicks(steps)
    steps = _dedup_prefill_keypresses(steps)

    nav_clean: List[Step] = []
    seen_nav: set[str] = set()
    for step in steps:
        if step.action_type == "navigate":
            key = _relative_path(step.url)
            if key in seen_nav:
                continue
            seen_nav.add(key)
        else:
            seen_nav.clear()
        nav_clean.append(step)

    segments: List[List[Step]] = []
    nav_steps: List[Step] = []
    current: List[Step] = []
    for step in nav_clean:
        if step.action_type == "navigate":
            segments.append(current)
            nav_steps.append(step)
            current = []
        else:
            current.append(step)
    segments.append(current)

    result: List[Step] = []
    for i, seg in enumerate(segments):
        result.extend(_clean_segment(seg))
        if i < len(nav_steps):
            result.append(nav_steps[i])
    return result


def _fn_name(journey_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", journey_name.lower()).strip("_")
    return f"test_{slug}"


def _chain_code(step: Step, indent: str = "        ") -> str:
    """Return Python list literal of locator expressions for a step."""
    chain = _locator_chain(step)
    if len(chain) == 1:
        return f"[{chain[0]}]"
    items = [f"\n{indent}{loc}," for loc in chain]
    return "[" + "".join(items) + f"\n{indent[:-4]}]"


# ---------------------------------------------------------------------------
# Conftest builder — all shared helpers live in conftest.py, NOT in test files
# ---------------------------------------------------------------------------

# These selectors are embedded verbatim into the generated conftest.py
_CONFTEST_OVERLAY_SELECTORS = [
    '[class*="cookie"]', '[id*="onetrust"]', '#onetrust-banner-sdk',
    '[class*="consent"]', '[class*="gdpr"]', '.cc-window',
    '[class*="intercom"]', '#intercom-container',
    '[class*="drift"]', '[class*="crisp"]',
    '[class*="notification-banner"]', '[class*="announcement"]',
    '[class*="snackbar"]', '[class*="whats-new"]',
    'tp-yt-paper-dialog', 'ytd-consent-bump-v2-lightbox', 'ytd-popup-container',
]


def _build_conftest(default_origin: str) -> str:
    """Return the full text of a generated conftest.py file."""
    sels_repr = repr(_CONFTEST_OVERLAY_SELECTORS)
    lines = [
        '"""',
        'conftest.py — generated by Vigil.',
        'Contains all shared helpers. Imported by every test in this directory.',
        '',
        'Env vars:',
        '  BASE_URL       — override base URL',
        '  STORAGE_STATE  — path to auth.json (pre-authenticated session)',
        '  TESTAI_TIMEOUT — element wait timeout ms (default 15000)',
        '  SCREENSHOT_DIR — screenshot output dir (default "screenshots")',
        '"""',
        'import os',
        'import pathlib',
        '',
        'import pytest',
        'from playwright.sync_api import TimeoutError as PwTimeout',
        '',
        '# ---------------------------------------------------------------------------',
        '# Shared constants',
        '# ---------------------------------------------------------------------------',
        '',
        '_TIMEOUT = int(os.environ.get("TESTAI_TIMEOUT", "15000"))',
        '_SHOTS = pathlib.Path(os.environ.get("SCREENSHOT_DIR", "screenshots"))',
        '_SHOTS.mkdir(exist_ok=True)',
        '',
        '',
        'def _shot(page, n, suffix=""):',
        '    name = f"step_{n:02d}{suffix}.png"',
        '    page.screenshot(path=str(_SHOTS / name))',
        '    print(f"__SCREENSHOT__:{name}", flush=True)',
        '',
        '',
        'def _do(loc, action, timeout):',
        '    if action == "click":',
        '        loc.click(timeout=timeout)',
        '    elif action == "visible":',
        '        loc.wait_for(state="visible", timeout=timeout)',
        '    elif action.startswith("fill:"):',
        '        loc.fill(action[5:], timeout=timeout)',
        '    elif action == "enter":',
        '        loc.press("Enter")',
        '',
        '',
        '# ---------------------------------------------------------------------------',
        '# Overlay suppression',
        '# ---------------------------------------------------------------------------',
        '',
        '_OVERLAY_CSS = """',
        '[class*="cookie"], [id*="cookie"], [id*="onetrust"], #onetrust-banner-sdk,',
        '[class*="consent"], [class*="gdpr"], [class*="cc-banner"], .cc-window,',
        '[class*="intercom"], #intercom-container, [class*="drift"], #drift-widget,',
        '[class*="crisp"], [class*="zendesk"], [class*="hubspot"],',
        '[class*="notification-banner"], [class*="announcement"],',
        '[class*="CookieConsent"], [class*="snackbar"], [class*="Snackbar"],',
        '[class*="whats-new"], [class*="product-update"], [class*="onboarding"],',
        '[class*="walkthrough"], [class*="tour"], [class*="promo-bar"],',
        'tp-yt-paper-dialog, ytd-consent-bump-v2-lightbox,',
        'ytd-popup-container, [id*="consent"] {',
        '    display: none !important;',
        '    visibility: hidden !important;',
        '    pointer-events: none !important;',
        '}',
        '"""',
        '',
        f'_OVERLAY_SELECTORS = {sels_repr}',
        '',
        '',
        'def _inject_overlay_shield(page):',
        '    """Inject CSS kill-sheet and MutationObserver to auto-hide overlays."""',
        '    try:',
        '        page.add_style_tag(content=_OVERLAY_CSS)',
        '    except Exception:',
        '        pass',
        '    try:',
        '        sels_json = repr(_OVERLAY_SELECTORS).replace("\'", \'"\')',
        '        js = (',
        '            "(function() {"',
        '            "if (window.__vigil_observer) return;"',
        '            f"var sels = {sels_json};"',
        '            "function sweep() {"',
        '            "sels.forEach(function(s) {"',
        '            "document.querySelectorAll(s).forEach(function(el) {"',
        '            "if (el.offsetHeight > 0) { el.style.display=\'none\'; el.style.pointerEvents=\'none\'; }"',
        '            "});});}}"',
        '            "sweep();"',
        '            "var obs = new MutationObserver(sweep);"',
        '            "obs.observe(document.body, {childList: true, subtree: true});"',
        '            "window.__vigil_observer = obs;"',
        '            "})();"',
        '        )',
        '        page.evaluate(js)',
        '    except Exception:',
        '        pass',
        '',
        '',
        'def _smart_overlay_sweep(page):',
        '    """Detect and dismiss any overlay by visual/behavioral characteristics.',
        '',
        '    Strategy: find fixed/sticky/absolute elements covering >5% of viewport,',
        '    try to dismiss via buttons, close icons, or aria-label, then force-hide',
        '    anything that remains.',
        '    """',
        '    try:',
        '        dismissed = page.evaluate("""() => {',
        '            const vw = window.innerWidth, vh = window.innerHeight;',
        '            const coverThreshold = 0.05;',
        '            const dismissed = [];',
        '            const dismissWords = [\'accept\',\'ok\',\'got it\',\'dismiss\',\'close\',',
        '                \'agree\',\'allow\',\'i understand\',\'continue\',\'no thanks\',',
        '                \'not now\',\'maybe later\',\'skip\',\'deny\',\'reject\',',
        '                \'x\',\'\\u2715\',\'\\xd7\',\'\\u2716\'];',
        '            for (const el of document.querySelectorAll(\'*\')) {',
        '                const style = window.getComputedStyle(el);',
        '                if (![\'fixed\',\'sticky\',\'absolute\'].includes(style.position)) continue;',
        '                const zi = parseFloat(style.zIndex || \'0\');',
        '                if (zi < 10 && style.position !== \'fixed\') continue;',
        '                const r = el.getBoundingClientRect();',
        '                if (r.width < 1 || r.height < 1) continue;',
        '                const coverage = (r.width * r.height) / (vw * vh);',
        '                if (coverage < coverThreshold) continue;',
        '                if (style.display === \'none\' || style.visibility === \'hidden\') continue;',
        '                if (parseFloat(style.opacity) === 0) continue;',
        '                let clicked = false;',
        '                // Try close buttons by aria-label first (most reliable)',
        '                for (const btn of el.querySelectorAll(\'[aria-label*="close" i],[aria-label*="dismiss" i]\')) {',
        '                    try { btn.click(); clicked = true; break; } catch(_) {}',
        '                }',
        '                if (!clicked) {',
        '                    const btns = el.querySelectorAll(\'button,[role="button"],a,[class*="close"],[class*="dismiss"]\');',
        '                    for (const btn of btns) {',
        '                        const t = (btn.textContent || \'\').trim().toLowerCase();',
        '                        if (dismissWords.includes(t) || btn.className.match(/close|dismiss/i)) {',
        '                            try { btn.click(); clicked = true; break; } catch(_) {}',
        '                        }',
        '                    }',
        '                }',
        '                // If no dismiss button found, force-hide the overlay',
        '                if (!clicked && coverage > 0.3) {',
        '                    el.style.display = \'none\';',
        '                    el.style.pointerEvents = \'none\';',
        '                }',
        '                if (clicked) dismissed.push(el.tagName + \'.\' + (el.className||\'\').slice(0,30));',
        '            }',
        '            return dismissed;',
        '        }""")',
        '        if dismissed:',
        '            page.wait_for_timeout(300)',
        '    except Exception:',
        '        pass',
        '',
        '',
        'def _sweep_overlays(page):',
        '    """Dismiss any visible overlay before a step."""',
        '    _smart_overlay_sweep(page)',
        '    for sel in _OVERLAY_SELECTORS:',
        '        try:',
        '            els = page.locator(sel)',
        '            if els.count() == 0:',
        '                continue',
        '            for i in range(min(els.count(), 2)):',
        '                el = els.nth(i)',
        '                if not el.is_visible():',
        '                    continue',
        '                for btn_text in ["Accept", "Got it", "Dismiss", "Close", "OK", "I agree"]:',
        '                    try:',
        '                        btn = el.get_by_text(btn_text, exact=False).first',
        '                        if btn.is_visible():',
        '                            btn.click(force=True, timeout=1000)',
        '                            page.wait_for_timeout(300)',
        '                            break',
        '                    except Exception:',
        '                        continue',
        '                try:',
        '                    if el.is_visible():',
        '                        el.evaluate("el => { el.style.display=\'none\'; el.style.pointerEvents=\'none\'; }")',
        '                except Exception:',
        '                    pass',
        '        except Exception:',
        '            continue',
        '',
        '',
        'def _dismiss_overlay(page):',
        '    """Reactive overlay dismissal: smart sweep + known selectors + escape + body-click."""',
        '    _smart_overlay_sweep(page)',
        '    _sweep_overlays(page)',
        '    for strategy in ["Escape", "click_body"]:',
        '        try:',
        '            if strategy == "Escape":',
        '                page.keyboard.press("Escape")',
        '                page.wait_for_timeout(400)',
        '            elif strategy == "click_body":',
        '                page.locator("body").click(position={"x": 1, "y": 1}, force=True)',
        '                page.wait_for_timeout(400)',
        '        except Exception:',
        '            pass',
        '',
        '',
        '# ---------------------------------------------------------------------------',
        '# Auto-healing locator engine',
        '# ---------------------------------------------------------------------------',
        '',
        'def _heal(page, locators, action, timeout=_TIMEOUT, _auth_ok=False,',
        '          _expected_text="", _expected_href="", _desc=""):',
        '    """Try each locator until one works.',
        '',
        '    Phases:',
        '      0. Quick retry with overlay sweep.',
        '      1. Try each locator with a short per-locator timeout.',
        '      2. fill: wait for inputs to appear, then retry.',
        '      3. click + overlay: dismiss overlays, retry, JS click with validation.',
        '      4. click stall: wait for page to settle.',
        '      5. Vision coordinate heal: screenshot -> vision LLM -> click at (x,y).',
        '    """',
        '    last_err = None',
        '    _pre_url = page.url  # snapshot URL for post-action verification',
        '',
        '    _AUTH_PATHS = [',
        '        "/login", "/signin", "/sign-in", "/sign_in",',
        '        "/auth", "/authenticate", "/authentication",',
        '        "/accounts", "/sso", "/saml", "/portal",',
        '        "/session/new", "/users/sign_in", "/wp-login.php",',
        '        "/oauth", "/authorize", "/connect/authorize",',
        '        "/adfs", "/cas/login", "/openid",',
        '    ]',
        '    # Detect unexpected auth redirects (skip when test is intentionally logging in)',
        '    if not _auth_ok:',
        '        current_url = page.url',
        '        _on_login = any(p in current_url.lower() for p in _AUTH_PATHS)',
        '        if not _on_login:',
        '            try:',
        '                _title = page.evaluate("() => document.title.toLowerCase()")',
        '                _on_login = any(w in _title for w in [',
        '                    "log in", "sign in", "login", "signin",',
        '                    "authentication", "authorize", "single sign",',
        '                    "identity", "credentials",',
        '                ])',
        '            except Exception:',
        '                pass',
        '        if not _on_login:',
        '            try:',
        '                _on_login = page.locator("input[type=\'password\']:visible").count() > 0',
        '            except Exception:',
        '                pass',
        '        if not _on_login:',
        '            try:',
        '                # OAuth/SAML redirect detection: common IdP domains',
        '                _idp_domains = ["accounts.google.com", "login.microsoftonline.com",',
        '                    "auth0.com", "okta.com", "onelogin.com", "ping",',
        '                    "cognito", "keycloak", "auth.", "sso."]',
        '                _on_login = any(d in current_url.lower() for d in _idp_domains)',
        '            except Exception:',
        '                pass',
        '        if _on_login:',
        '            import os as _os',
        '            _ss = _os.environ.get("STORAGE_STATE", "")',
        '            _hint = ""',
        '            if _ss:',
        '                _hint = f" (STORAGE_STATE={_ss} was set but may be expired)"',
        '            else:',
        '                _hint = "\\n\\nTo fix: run save_auth.py first, then:\\n  STORAGE_STATE=auth.json pytest ..."',
        '            raise Exception(',
        '                f"Auth required \\u2014 login page detected at: {current_url}{_hint}"',
        '            )',
        '',
        '    # Phase 0: quick retry (handles transient loading/animation without LLM)',
        '    for _attempt in range(2):',
        '        for loc in locators:',
        '            try:',
        '                _do(loc, action, min(timeout, 3000))',
        '                return loc',
        '            except Exception:',
        '                pass',
        '        page.wait_for_timeout(800)',
        '        _smart_overlay_sweep(page)',
        '        _sweep_overlays(page)',
        '',
        '    for i, loc in enumerate(locators):',
        '        try:',
        '            short = min(timeout, 5000) if i < len(locators) - 1 else timeout',
        '            _do(loc, action, short)',
        '            if i > 0:',
        '                print(f"    [healed] locator #{i + 1} worked", flush=True)',
        '            return loc',
        '        except Exception as e:',
        '            last_err = e',
        '',
        '    err_text = str(last_err)',
        '',
        '    if action.startswith("fill:"):',
        '        val = action[5:]',
        '        try:',
        '            focused = page.locator(":focus")',
        '            tag = focused.evaluate("el => el.tagName").lower()',
        '            if tag in ("input", "textarea"):',
        '                focused.fill(val, timeout=5000)',
        '                print("    [healed] filled focused element", flush=True)',
        '                return focused',
        '        except Exception:',
        '            pass',
        '        print("    [heal] waiting for input to render...", flush=True)',
        '        try:',
        '            page.locator("input[type=\'text\']:visible, input:not([type]):visible, textarea:visible").first.wait_for(state="visible", timeout=8000)',
        '        except Exception:',
        '            pass',
        '        for loc in locators:',
        '            try:',
        '                loc.fill(val, timeout=3000)',
        '                print("    [healed] input appeared after wait", flush=True)',
        '                return loc',
        '            except Exception:',
        '                pass',
        '',
        '    # ---- JS click validation helper ----',
        '    def _validate_js_click(loc, expected_text, expected_href):',
        '        """Validate a locator targets the right element before JS-clicking.',
        '',
        '        Returns True if click was executed, False if element didn\'t match.',
        '        """',
        '        try:',
        '            info = loc.evaluate("""el => ({',
        '                text: (el.innerText || \'\').trim().slice(0, 200),',
        '                href: el.getAttribute(\'href\') || \'\',',
        '                tag: el.tagName.toLowerCase(),',
        '            })""")',
        '            el_text = info.get("text", "")',
        '            el_href = info.get("href", "")',
        '            # If we have expected text/href, validate before clicking',
        '            if expected_text and expected_text.lower() not in el_text.lower():',
        '                print(f"    [heal] JS click skipped — text mismatch: expected \\"{expected_text}\\" but got \\"{el_text[:60]}\\"", flush=True)',
        '                return False',
        '            if expected_href and expected_href not in el_href:',
        '                print(f"    [heal] JS click skipped — href mismatch: expected \\"{expected_href}\\" but got \\"{el_href[:60]}\\"", flush=True)',
        '                return False',
        '            loc.evaluate("el => el.click()")',
        '            page.wait_for_timeout(1000)',
        '            return True',
        '        except Exception:',
        '            return False',
        '',
        '    # ---- Post-click verification ----',
        '    def _verify_click(pre_url):',
        '        """Check that a click caused an observable change.',
        '',
        '        Returns True if something changed (URL, new elements, etc).',
        '        Returns False only if we can confidently say click hit wrong target.',
        '        """',
        '        try:',
        '            post_url = page.url',
        '            if post_url != pre_url:',
        '                return True  # URL changed — click did something',
        '            return True  # Same URL is fine — many clicks don\'t navigate',
        '        except Exception:',
        '            return True  # Can\'t verify — assume OK',
        '',
        '    if action == "click" and "intercepts pointer events" in err_text:',
        '        print("    [heal] overlay blocking — dismissing...", flush=True)',
        '        _dismiss_overlay(page)',
        '        for loc in locators[:2]:',
        '            try:',
        '                _do(loc, action, 5000)',
        '                print("    [healed] overlay dismissed", flush=True)',
        '                return loc',
        '            except Exception as e:',
        '                last_err = e',
        '        # Validated JS click — check text/href before force-clicking',
        '        for loc in locators:',
        '            if _validate_js_click(loc, _expected_text, _expected_href):',
        '                print("    [healed] validated JS click bypassed overlay", flush=True)',
        '                return loc',
        '        # Last resort: blind JS click on first locator (logged as risky)',
        '        try:',
        '            locators[0].evaluate("el => el.click()")',
        '            page.wait_for_timeout(1000)',
        '            print("    [healed] JS click (unvalidated) bypassed overlay", flush=True)',
        '            return locators[0]',
        '        except Exception as e:',
        '            last_err = e',
        '',
        '    if action == "click":',
        '        print("    [heal] waiting for page to settle...", flush=True)',
        '        page.wait_for_timeout(3000)',
        '        _sweep_overlays(page)',
        '        for loc in locators:',
        '            try:',
        '                loc.click(timeout=5000)',
        '                print("    [healed] element appeared after wait", flush=True)',
        '                return loc',
        '            except Exception as e:',
        '                last_err = e',
        '',
        '    # Phase 4b: element exists but not visible — scroll into view, wait, force-click',
        '    if "not visible" in err_text or "element is not visible" in err_text.lower():',
        '        print("    [heal] element found but not visible — waiting for render...", flush=True)',
        '        # First try: wait up to 15s for it to become visible naturally',
        '        for loc in locators:',
        '            try:',
        '                loc.wait_for(state="visible", timeout=15000)',
        '                loc.click(timeout=5000)',
        '                print("    [healed] element became visible after wait", flush=True)',
        '                return loc',
        '            except Exception:',
        '                pass',
        '        # Second try: scroll into view then click',
        '        print("    [heal] scrolling element into view...", flush=True)',
        '        for loc in locators:',
        '            try:',
        '                loc.scroll_into_view_if_needed(timeout=5000)',
        '                page.wait_for_timeout(1000)',
        '                loc.click(timeout=5000)',
        '                print("    [healed] clicked after scroll-into-view", flush=True)',
        '                return loc',
        '            except Exception:',
        '                pass',
        '        # Third try: force-click (skips Playwright actionability checks)',
        '        print("    [heal] trying force click...", flush=True)',
        '        for loc in locators:',
        '            try:',
        '                loc.click(force=True, timeout=5000)',
        '                page.wait_for_timeout(1000)',
        '                print("    [healed] force-clicked hidden element", flush=True)',
        '                return loc',
        '            except Exception:',
        '                pass',
        '        # Fourth try: scrollIntoView + coordinate click via page.mouse',
        '        # React Flow / canvas components need real pointer events at real coordinates',
        '        for loc in locators:',
        '            try:',
        '                loc.evaluate("el => el.scrollIntoView({block: \'center\'})")',
        '                page.wait_for_timeout(1000)',
        '                box = loc.bounding_box(timeout=5000)',
        '                if box and box["width"] > 0 and box["height"] > 0:',
        '                    cx = box["x"] + box["width"] / 2',
        '                    cy = box["y"] + box["height"] / 2',
        '                    page.mouse.click(cx, cy)',
        '                    page.wait_for_timeout(1500)',
        '                    print(f"    [healed] coordinate click at ({cx:.0f}, {cy:.0f}) on hidden element", flush=True)',
        '                    return loc',
        '            except Exception:',
        '                pass',
        '        # Fifth try: dispatch full pointer event sequence (pointerdown + pointerup + click)',
        '        for loc in locators:',
        '            try:',
        '                loc.evaluate("""el => {',
        '                    el.scrollIntoView({block: \'center\'});',
        '                    const rect = el.getBoundingClientRect();',
        '                    const cx = rect.left + rect.width / 2;',
        '                    const cy = rect.top + rect.height / 2;',
        '                    for (const evtType of [\'pointerdown\', \'mousedown\', \'pointerup\', \'mouseup\', \'click\']) {',
        '                        el.dispatchEvent(new PointerEvent(evtType, {',
        '                            bubbles: true, cancelable: true, composed: true,',
        '                            clientX: cx, clientY: cy, pointerId: 1,',
        '                            pointerType: \'mouse\', button: 0, buttons: 1,',
        '                        }));',
        '                    }',
        '                }""")',
        '                page.wait_for_timeout(2000)',
        '                print("    [healed] dispatched pointer events on hidden element", flush=True)',
        '                return loc',
        '            except Exception as e:',
        '                last_err = e',
        '',
        '    # Phase 5: Vision coordinate heal (screenshot -> LLM -> click at x,y)',
        '    _vision_desc = _desc or _expected_text or action',
        '    if _vision_desc:',
        '        try:',
        '            import requests as _req, json as _json, base64 as _b64, os as _os',
        '            _api = _os.environ.get("VIGIL_API", "http://localhost:8000")',
        '            _ss_bytes = page.screenshot(type="png")',
        '            _ss_b64 = _b64.b64encode(_ss_bytes).decode()',
        '            _vp = page.viewport_size or {"width": 1280, "height": 720}',
        '            _resp = _req.post(f"{_api}/api/heal/vision", json={',
        '                "screenshot_b64": _ss_b64,',
        '                "description": _vision_desc,',
        '                "action_type": action.split(":")[0],',
        '                "viewport": _vp,',
        '            }, timeout=30)',
        '            if _resp.ok:',
        '                _coord = _resp.json()',
        '                if _coord.get("x") and _coord.get("y") and _coord.get("confidence", 0) > 0.3:',
        '                    if action.startswith("fill:"):',
        '                        page.mouse.click(_coord["x"], _coord["y"])',
        '                        page.wait_for_timeout(300)',
        '                        page.keyboard.type(action[5:])',
        '                        print(f"    [healed] vision fill at ({_coord[\'x\']}, {_coord[\'y\']}) "',
        '                              f"conf={_coord[\'confidence\']:.0%}", flush=True)',
        '                        return locators[0]',
        '                    else:',
        '                        page.mouse.click(_coord["x"], _coord["y"])',
        '                        print(f"    [healed] vision click at ({_coord[\'x\']}, {_coord[\'y\']}) "',
        '                              f"conf={_coord[\'confidence\']:.0%}", flush=True)',
        '                        return locators[0]',
        '        except Exception:',
        '            pass',
        '',
        '    try:',
        '        print(f"    [heal]   current URL: {page.url}", flush=True)',
        '        print(f"    [heal]   page title : {page.evaluate(\'() => document.title\')}", flush=True)',
        '        _vis = page.locator("input:visible, textarea:visible")',
        '        _vc = _vis.count()',
        '        if _vc:',
        '            _dd = []',
        '            for _ii in range(min(_vc, 5)):',
        '                _inp = _vis.nth(_ii)',
        '                _tt = _inp.get_attribute("type") or "text"',
        '                _nn = _inp.get_attribute("name") or _inp.get_attribute("placeholder") or ""',
        '                _dd.append(f"{_tt}({_nn})")',
        '            print(f"    [heal]   visible inputs: {\', \'.join(_dd)}", flush=True)',
        '    except Exception:',
        '        pass',
        '',
        '    raise last_err',
        '',
        '',
        '# ---------------------------------------------------------------------------',
        '# Pytest fixtures',
        '# ---------------------------------------------------------------------------',
        '',
        '@pytest.fixture(scope="session")',
        'def base_url(request):',
        '    # --base-url CLI flag takes priority; $BASE_URL env is the fallback.',
        f'    cli = request.config.getoption("--base-url", default=None)',
        f'    return cli or os.environ.get("BASE_URL", "{default_origin}")',
        '',
        '',
        '@pytest.fixture(scope="session")',
        'def browser_context_args(browser_context_args):',
        '    storage = os.environ.get("STORAGE_STATE", "")',
        '    if storage and os.path.exists(storage):',
        '        return {**browser_context_args, "storage_state": storage}',
        '    return browser_context_args',
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Test file renderer  — thin, clean, ~60-100 lines
# ---------------------------------------------------------------------------

def _render(journey: Journey) -> str:
    steps = _dedup_steps(journey.steps)
    fn = _fn_name(journey.name)
    conf = f"{journey.confidence * 100:.0f}%"
    tags = ", ".join(journey.tags) if journey.tags else "—"
    ts = journey.discovered_at.strftime("%Y-%m-%d %H:%M") if journey.discovered_at else "unknown"

    all_env_vars: List[tuple] = []
    for step in steps:
        if step.action_type == "fill_form":
            s = step.selectors
            val = s.get("value") or ""
            raw_key = (s.get("test_id") or s.get("name") or s.get("label")
                       or s.get("placeholder") or "")
            if not raw_key or _is_react_id(raw_key):
                raw_key = s.get("css", "field")
            field_key = re.sub(r"[^a-z0-9]", "_", raw_key)
            env_key = re.sub(r"[^A-Z0-9]", "_", field_key.upper()).strip("_")
            is_secret = s.get("input_type") == "password" or val in ("[REDACTED]", "")
            all_env_vars.append((env_key, val if not is_secret else "", is_secret))

    lines = [
        '"""',
        "Auto-generated by Vigil.",
        f"Journey  : {journey.name}",
        f"Domain   : {journey.domain} > {journey.feature}",
        f"Captured : {ts}",
        f"Confidence: {conf}  |  Tags: {tags}",
        "",
        "Run:",
        "  pytest test_this_file.py --base-url https://staging.example.com",
        "  STORAGE_STATE=auth.json pytest test_this_file.py  # with authentication",
    ]
    if all_env_vars:
        lines.append("")
        lines.append("Env vars:")
        seen: set = set()
        for env_key, default, is_secret in all_env_vars:
            if env_key in seen:
                continue
            seen.add(env_key)
            if is_secret:
                lines.append(f"  export {env_key}=<secret>")
            else:
                lines.append(f"  export {env_key}={default!r}")
    lines += ['"""', ""]

    lines += [
        "import os",
        "import time",
        "import json",
        "import pytest",
        "from playwright.sync_api import Page, TimeoutError as PwTimeout",
        "from conftest import (",
        "    _TIMEOUT, _SHOTS, _shot, _heal,",
        "    _inject_overlay_shield, _sweep_overlays,",
        ")",
        "",
        "# Unique suffix for this test run (avoids conflicts with prior runs)",
        "import hashlib as _hl",
        "_RUN_ID = _hl.md5(str(time.time()).encode()).hexdigest()[:6]",
        "",
        "",
        f"def {fn}(page: Page, base_url: str):",
        f'    """Replay: {journey.name}"""',
        "",
        "    _console_log: list = []",
        "    _network_log: list = []",
        "    _step_timings: dict = {}",
        "    _t0 = time.time()",
        "    _skipped: list = []",
        "    _failed: list = []",
        "    _skip_until_nav = False",
        "",
        "    def _on_console(msg):",
        "        _console_log.append(f'[{msg.type}] {msg.text}')",
        "        if msg.type == 'error':",
        "            print(f'    __CONSOLE_ERROR__:{msg.text[:200]}', flush=True)",
        "",
        "    def _on_request_failed(request):",
        "        text = f'{request.method} {request.url} -> {request.failure}'",
        "        _network_log.append(text)",
        "        print(f'    __NET_FAIL__:{text[:200]}', flush=True)",
        "",
        "    page.on('console', _on_console)",
        "    page.on('requestfailed', _on_request_failed)",
        "",
    ]

    # Initial navigation if first step is not navigate
    if steps and steps[0].action_type != "navigate":
        first_url = steps[0].url if steps[0].url else ""
        if first_url:
            init_path = _relative_path(first_url)
            safe_init = init_path.replace('"', '\\"')
            lines += [
                "    # ── Initial page load ──",
                f'    page.goto(base_url + "{safe_init}")',
                '    page.wait_for_load_state("domcontentloaded", timeout=_TIMEOUT)',
                "    try:",
                '        page.wait_for_load_state("networkidle", timeout=5000)',
                "    except PwTimeout:",
                "        pass  # SPA apps may never reach networkidle",
                "    _inject_overlay_shield(page)",
                "    page.wait_for_timeout(1500)",
                "",
            ]

    # Detect login flow: steps that fill password fields are part of auth
    _login_step_indices: set[int] = set()
    for i, s in enumerate(steps):
        if s.action_type == "fill_form" and s.selectors.get("input_type") == "password":
            # Mark a window of steps around the password fill as auth steps
            for j in range(max(0, i - 3), min(len(steps), i + 3)):
                _login_step_indices.add(j)

    step_num = 0
    last_path: Optional[str] = None
    prev_triggers_nav = False

    for idx, step in enumerate(steps):
        desc = step.description.replace('"', '\\"')

        next_nav_path: Optional[str] = None
        if idx + 1 < len(steps) and steps[idx + 1].action_type == "navigate":
            next_nav_path = _relative_path(steps[idx + 1].url)

        # Skip redundant click before fill on same React-ID element
        if (step.action_type == "click"
                and idx + 1 < len(steps)
                and steps[idx + 1].action_type == "fill_form"
                and _field_key(step) == _field_key(steps[idx + 1])
                and _is_react_id(step.selectors.get("css", ""))):
            continue

        if step.action_type == "navigate":
            path = _relative_path(step.url)
            safe_path = path.replace('"', '\\"')
            gp = _glob_path(safe_path)
            if path != last_path:
                step_num += 1
                n = step_num
                lines.append("")
                lines.append("    _skip_until_nav = False")
                if prev_triggers_nav:
                    lines.append(f'    print("  \\u25b8 Step {n}/{_TOTAL_PH} \\u2014 Wait for {gp}", flush=True)')
                    glob_url = f"**{gp}**".replace("***", "**")
                    lines.append("    try:")
                    lines.append(f'        page.wait_for_url("{glob_url}", timeout=_TIMEOUT)')
                    lines.append("    except PwTimeout:")
                    lines.append("        pass  # navigation may have already completed")
                else:
                    lines.append(f'    print("  \\u25b8 Step {n}/{_TOTAL_PH} \\u2014 {desc}", flush=True)')
                    lines.append(f'    page.goto(base_url + "{path}")')
                lines.append('    page.wait_for_load_state("domcontentloaded", timeout=_TIMEOUT)')
                lines.append("    try:")
                lines.append('        page.wait_for_load_state("networkidle", timeout=5000)')
                lines.append("    except PwTimeout:")
                lines.append("        pass  # SPA apps may never reach networkidle")
                lines.append("    _inject_overlay_shield(page)")
                lines.append(f"    _shot(page, {n})")
                last_path = path
            prev_triggers_nav = False

        elif step.action_type == "click":
            raw_css = step.selectors.get("css", "")
            text = (step.selectors.get("text") or "").strip()
            test_id = step.selectors.get("test_id")
            aria_label = (step.selectors.get("ariaLabel") or "").strip()

            has_any_selector = bool(raw_css or text or test_id or aria_label
                                    or step.selectors.get("placeholder")
                                    or step.selectors.get("role")
                                    or step.selectors.get("label"))

            if not has_any_selector and step.url:
                path = _relative_path(step.url)
                safe_path = path.replace('"', '\\"')
                if path != last_path:
                    step_num += 1
                    n = step_num
                    lines.append("")
                    lines.append(f'    print("  \\u25b8 Step {n}/{_TOTAL_PH} \\u2014 Navigate to {path}", flush=True)')
                    lines.append(f'    page.goto(base_url + "{safe_path}")')
                    lines.append('    page.wait_for_load_state("domcontentloaded", timeout=_TIMEOUT)')
                    lines.append("    try:")
                    lines.append('        page.wait_for_load_state("networkidle", timeout=5000)')
                    lines.append("    except PwTimeout:")
                    lines.append("        pass  # SPA apps may never reach networkidle")
                    lines.append("    _inject_overlay_shield(page)")
                    lines.append(f"    _shot(page, {n})")
                    last_path = path
                prev_triggers_nav = False
                continue

            step_num += 1
            n = step_num
            lines.append("")
            lines.append(f'    print("  \\u25b8 Step {n}/{_TOTAL_PH} \\u2014 {desc}", flush=True)')
            lines.append("    if _skip_until_nav:")
            lines.append(f'        print("    [skip] step skipped — prior step failed to produce expected UI state", flush=True)')
            lines.append(f"        _skipped.append({n})")
            lines.append("    else:")
            lines.append("      try:")
            lines.append("        _sweep_overlays(page)")

            # Dropdown/menu timing: if this step targets a menu item,
            # wait for it to render after the previous trigger click
            tag = step.selectors.get("tagName", "").lower()
            role = (step.selectors.get("role") or "").lower()
            if tag in ("li", "menuitem") or role in ("menuitem", "option"):
                chain_for_wait = _locator_chain(step)
                if chain_for_wait:
                    lines.append(f"        {chain_for_wait[0]}.wait_for(state='visible', timeout=5000)")

            if " option" in raw_css and text:
                parent = raw_css.split(" option")[0].strip().replace('"', '\\"')
                safe_text = text.replace('"', '\\"')
                lines.append(f'        page.locator("{parent}").select_option(label="{safe_text}")')
            else:
                chain = _locator_chain(step)
                if next_nav_path and not test_id and len(chain) == 1:
                    safe_np = next_nav_path.replace('"', '\\"')
                    lines.append("        try:")
                    lines.append(f"            {chain[0]}.click(timeout=5000)")
                    lines.append("        except PwTimeout:")
                    lines.append(f'            page.goto(base_url + "{safe_np}")')
                else:
                    auth_kw = ", _auth_ok=True" if idx in _login_step_indices else ""
                    _etx = (text or "").replace('"', '\\"')[:80]
                    _ehr = (step.selectors.get("href") or "").replace('"', '\\"')[:200]
                    _expect_kw = ""
                    if _etx:
                        _expect_kw += f', _expected_text="{_etx}"'
                    if _ehr:
                        _expect_kw += f', _expected_href="{_ehr}"'
                    _desc_kw = f', _desc="{desc}"'
                    lines.append(f"        _heal(page, {_chain_code(step)}, 'click'{auth_kw}{_expect_kw}{_desc_kw})")

            lines.append(f"        _shot(page, {n})")
            lines.append("      except Exception as _step_err:")
            lines.append(f'        print(f"    [SOFT FAIL] Step {n} failed: {{_step_err}}", flush=True)')
            lines.append(f"        _failed.append({n})")
            lines.append(f"        _shot(page, {n})")
            lines.append("        _skip_until_nav = True")
            prev_triggers_nav = True
            last_path = None

        elif step.action_type == "fill_form":
            step_num += 1
            n = step_num
            lines.append("")
            lines.append(f'    print("  \\u25b8 Step {n}/{_TOTAL_PH} \\u2014 {desc}", flush=True)')
            lines.append("    if _skip_until_nav:")
            lines.append(f'        print("    [skip] step skipped — prior step failed to produce expected UI state", flush=True)')
            lines.append(f"        _skipped.append({n})")
            lines.append("    else:")
            lines.append("      try:")
            if prev_triggers_nav:
                lines.append("        page.wait_for_timeout(1000)")
            chain = _locator_chain(step)
            fv = _fill_value(step)
            auth_kw = ", _auth_ok=True" if idx in _login_step_indices else ""
            _desc_kw = f', _desc="{desc}"'
            lines.append(f"        _heal(page, {_chain_code(step)}, 'fill:' + {fv}{auth_kw}{_desc_kw})")
            lines.append(f"        _shot(page, {n})")
            lines.append("      except Exception as _step_err:")
            lines.append(f'        print(f"    [SOFT FAIL] Step {n} failed: {{_step_err}}", flush=True)')
            lines.append(f"        _failed.append({n})")
            lines.append(f"        _shot(page, {n})")
            lines.append("        _skip_until_nav = True")
            prev_triggers_nav = False

        elif step.action_type == "submit":
            step_num += 1
            n = step_num
            lines.append("")
            lines.append(f'    print("  \\u25b8 Step {n}/{_TOTAL_PH} \\u2014 {desc}", flush=True)')
            lines.append("    if _skip_until_nav:")
            lines.append(f'        print("    [skip] step skipped", flush=True)')
            lines.append(f"        _skipped.append({n})")
            lines.append("    else:")
            lines.append("      try:")
            chain = _locator_chain(step)
            if len(chain) == 1:
                lines.append(f"        {chain[0]}.press('Enter')")
            else:
                _desc_kw = f', _desc="{desc}"'
                lines.append(f"        _heal(page, {_chain_code(step)}, 'enter'{_desc_kw})")
            lines.append(f"        _shot(page, {n})")
            lines.append("      except Exception as _step_err:")
            lines.append(f'        print(f"    [SOFT FAIL] Step {n} failed: {{_step_err}}", flush=True)')
            lines.append(f"        _failed.append({n})")
            lines.append("        _skip_until_nav = True")
            prev_triggers_nav = True

        elif step.action_type == "keypress":
            key = step.selectors.get("key", "Enter")
            step_num += 1
            n = step_num
            lines.append("")
            lines.append(f'    print("  \\u25b8 Step {n}/{_TOTAL_PH} \\u2014 {desc}", flush=True)')
            lines.append("    if not _skip_until_nav:")
            safe_key = key.replace('"', '\\"')
            lines.append(f'        page.keyboard.press("{safe_key}")')
            if key == "Enter":
                lines.append("        try:")
                lines.append('            page.wait_for_load_state("networkidle", timeout=8000)')
                lines.append("        except PwTimeout:")
                lines.append('            page.wait_for_load_state("domcontentloaded", timeout=_TIMEOUT)')
            lines.append(f"        _shot(page, {n})")
            lines.append("    else:")
            lines.append(f'        print("    [skip] step skipped", flush=True)')
            lines.append(f"        _skipped.append({n})")
            prev_triggers_nav = (key == "Enter")

        elif step.action_type == "keycombo":
            combo = step.selectors.get("combo", "")
            step_num += 1
            n = step_num
            lines.append("")
            lines.append(f'    print("  \\u25b8 Step {n}/{_TOTAL_PH} \\u2014 {desc}", flush=True)')
            lines.append("    if not _skip_until_nav:")
            pw_combo = combo.replace("Cmd", "Meta")
            safe_combo = pw_combo.replace('"', '\\"')
            lines.append(f'        page.keyboard.press("{safe_combo}")')
            lines.append(f"        _shot(page, {n})")
            lines.append("    else:")
            lines.append(f'        print("    [skip] step skipped", flush=True)')
            lines.append(f"        _skipped.append({n})")
            prev_triggers_nav = False

        elif step.action_type == "select":
            step_num += 1
            n = step_num
            lines.append("")
            lines.append(f'    print("  \\u25b8 Step {n}/{_TOTAL_PH} \\u2014 {desc}", flush=True)')
            lines.append("    if _skip_until_nav:")
            lines.append(f'        print("    [skip] step skipped", flush=True)')
            lines.append(f"        _skipped.append({n})")
            lines.append("    else:")
            lines.append("      try:")
            val = step.selectors.get("value", "")
            safe_val = val.replace('"', '\\"')
            chain = _locator_chain(step)
            if len(chain) > 1:
                lines.append("        _select_done = False")
                for loc in chain:
                    lines.append("        if not _select_done:")
                    lines.append("            try:")
                    lines.append(f'                {loc}.select_option(label="{safe_val}", timeout=5000)')
                    lines.append("                _select_done = True")
                    lines.append("            except Exception:")
                    lines.append("                pass")
            else:
                lines.append(f'        {chain[0]}.select_option(label="{safe_val}")')
            lines.append(f"        _shot(page, {n})")
            lines.append("      except Exception as _step_err:")
            lines.append(f'        print(f"    [SOFT FAIL] Step {n} failed: {{_step_err}}", flush=True)')
            lines.append(f"        _failed.append({n})")
            lines.append("        _skip_until_nav = True")
            prev_triggers_nav = False

        elif step.action_type == "dblclick":
            step_num += 1
            n = step_num
            lines.append("")
            lines.append(f'    print("  \\u25b8 Step {n}/{_TOTAL_PH} \\u2014 {desc}", flush=True)')
            lines.append("    if _skip_until_nav:")
            lines.append(f'        print("    [skip] step skipped", flush=True)')
            lines.append(f"        _skipped.append({n})")
            lines.append("    else:")
            lines.append("      try:")
            lines.append("        _sweep_overlays(page)")
            chain = _locator_chain(step)
            if len(chain) == 1:
                lines.append(f"        {chain[0]}.dblclick(timeout=_TIMEOUT)")
            else:
                lines.append(f"        {_primary_locator(step)}.dblclick(timeout=_TIMEOUT)")
            lines.append(f"        _shot(page, {n})")
            lines.append("      except Exception as _step_err:")
            lines.append(f'        print(f"    [SOFT FAIL] Step {n} failed: {{_step_err}}", flush=True)')
            lines.append(f"        _failed.append({n})")
            lines.append("        _skip_until_nav = True")
            prev_triggers_nav = False

        elif step.action_type == "verify":
            step_num += 1
            n = step_num
            lines.append("")
            lines.append(f'    print("  \\u25b8 Step {n}/{_TOTAL_PH} \\u2014 {desc}", flush=True)')
            lines.append("    if not _skip_until_nav:")
            lines.append(f"        {_primary_locator(step)}.wait_for(state='visible', timeout=_TIMEOUT)")
            lines.append(f"        _shot(page, {n})")
            lines.append("    else:")
            lines.append(f'        print("    [skip] step skipped", flush=True)')
            lines.append(f"        _skipped.append({n})")
            prev_triggers_nav = False

    lines.append("")
    lines.append(f'    _total = {_TOTAL_PH}')
    lines.append(f'    _passed = _total - len(_failed) - len(_skipped)')
    lines.append(f'    print(f"\\n  Result: {{_passed}}/{_TOTAL_PH} passed, {{len(_failed)}} failed, {{len(_skipped)}} skipped", flush=True)')
    lines.append('    if _failed:')
    lines.append('        print(f"  Failed steps: {_failed}", flush=True)')
    lines.append('    if _skipped:')
    lines.append('        print(f"  Skipped steps: {_skipped}", flush=True)')
    lines.append('    print(f"__SOFT_RESULTS__:passed={_passed},failed={len(_failed)},skipped={len(_skipped)}", flush=True)')
    lines.append('    # Hard-fail when majority of steps failed — soft-fail must not mask a broken run.')
    lines.append('    _actionable = _total - len(_skipped)')
    lines.append('    if _actionable > 0 and len(_failed) / _actionable > 0.5:')
    lines.append('        pytest.fail(f"Journey failed: {len(_failed)}/{_actionable} actionable steps failed — {_failed}")')
    lines.append("")
    lines.append("    # Emit step timings for replay route to parse")
    lines.append("    for _sn, _ms in _step_timings.items():")
    lines.append('        print(f"__STEP_TIMING__:{_sn}:{_ms}", flush=True)')
    lines.append("")
    lines.append("    # Collect Web Vitals via CDP")
    lines.append("    try:")
    lines.append('        _wv = page.evaluate("""() => {')
    lines.append("            const nav = performance.getEntriesByType('navigation')[0] || {};")
    lines.append("            let lcp = 0, cls = 0;")
    lines.append("            try { const e = performance.getEntriesByType('largest-contentful-paint'); if (e.length) lcp = e[e.length-1].startTime; } catch(x) {}")
    lines.append("            try { performance.getEntriesByType('layout-shift').forEach(e => { if (!e.hadRecentInput) cls += e.value; }); } catch(x) {}")
    lines.append("            return {")
    lines.append("                lcp_ms: Math.round(lcp),")
    lines.append("                cls: Math.round(cls * 1000) / 1000,")
    lines.append("                ttfb_ms: Math.round((nav.responseStart || 0) - (nav.requestStart || 0)),")
    lines.append("                dom_content_loaded_ms: Math.round((nav.domContentLoadedEventEnd || 0) - (nav.startTime || 0)),")
    lines.append("                load_time_ms: Math.round((nav.loadEventEnd || 0) - (nav.startTime || 0)),")
    lines.append("            };")
    lines.append('        }""")')
    lines.append('        print(f"__WEB_VITALS__:{json.dumps(_wv)}", flush=True)')
    lines.append("    except Exception:")
    lines.append("        pass")
    lines.append("")
    lines.append("    if _console_log:")
    lines.append('        print(f"\\n  Console log ({len(_console_log)} entries):", flush=True)')
    lines.append("        for entry in _console_log[-20:]:")
    lines.append('            print(f"    {entry[:150]}", flush=True)')
    lines.append("    if _network_log:")
    lines.append('        print(f"\\n  Network failures ({len(_network_log)}):", flush=True)')
    lines.append("        for entry in _network_log:")
    lines.append('            print(f"    {entry[:200]}", flush=True)')
    lines.append("")

    # Post-process: inject step-level timing around actions
    import re as _re
    processed = []
    _step_print_re = _re.compile(r'^(    print\("  \\u25b8 Step \d+/)')
    _shot_re = _re.compile(r'^    _shot\(page, (\d+)\)')
    for line in lines:
        if _step_print_re.match(line):
            processed.append(line)
            processed.append("    _t0 = time.time()")
        elif _shot_re.match(line):
            m = _shot_re.match(line)
            sn = m.group(1)
            processed.append(f"    _step_timings[{sn}] = int((time.time() - _t0) * 1000)")
            processed.append(line)
        else:
            processed.append(line)

    code = "\n".join(processed)
    return code.replace(_TOTAL_PH, str(step_num))


def _render_conftest(journey: Journey) -> str:
    origin = ""
    for step in journey.steps:
        if step.url:
            origin = _base_origin(step.url)
            if origin:
                break
    return _build_conftest(origin or "http://localhost")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class PlaywrightExporter:
    def export(self, journey: Journey) -> str:
        return _render(journey)

    def export_conftest(self, journey: Journey) -> str:
        return _render_conftest(journey)

    def export_to_file(self, journey: Journey, output_path: str) -> str:
        content = self.export(journey)
        with open(output_path, "w") as f:
            f.write(content)
        return output_path
