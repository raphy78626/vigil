"""AI Explorer agent — autonomous app discovery using LLM-driven navigation."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Set
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PwTimeout

from testai.explorer.analyzer import take_snapshot, extract_elements
from testai.explorer.graph import FlowGraph, normalize_url
from testai.explorer.models import (
    ActionType,
    DiscoveredJourney,
    ExplorerResult,
    ExplorerStrategy,
    InteractionRecord,
    PageSnapshot,
    PlannedAction,
    SessionStatus,
)
from testai.explorer.skills import (
    build_skill_prompt,
    get_fill_overrides,
    get_priority_elements,
    SKILL_REGISTRY,
)
from testai.explorer.stealth import (
    apply_stealth,
    human_delay,
    inject_overlay_shield,
    launch_stealth_browser,
    sweep_overlays,
)
from testai.llm import get_provider

logger = logging.getLogger(__name__)


@dataclass
class ExplorerConfig:
    base_url: str
    strategy: str = ExplorerStrategy.BFS.value
    max_pages: int = 30
    max_time_minutes: int = 10
    auth_domain: Optional[str] = None
    headed: bool = True
    include_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=lambda: ["curious_explorer"])


_DEFAULT_PLANNER_SYSTEM = """You are a QA engineer autonomously exploring a web application.
Your goal: discover ALL user-facing features, pages, and flows for maximum test coverage.

Strategy:
- Prioritize navigation links, menu items, and buttons that lead to NEW pages
- Fill forms with realistic test data (names, emails, etc.) to discover form flows
- Avoid logout/delete/destructive actions
- Avoid external links (different domain)
- Avoid elements you've already interacted with if they lead to known pages
- Prefer unexplored areas of the app

IMPORTANT: Return ONLY valid JSON. No markdown, no explanation."""

_PLANNER_PROMPT = """Current page: {url}
Title: {title}
Pages visited so far: {visited_count}
Visited URLs: {visited_urls}

Interactive elements on this page:
{elements}

Which element should I interact with next?
Return JSON:
{{
  "element_index": <int>,
  "action": "click" | "fill" | "select" | "back" | "stop",
  "fill_value": "<value if action is fill, otherwise empty>",
  "reason": "<brief reason for this choice>"
}}

Rules:
- "element_index" must match one of the [index] numbers above
- Use "fill" for input/textarea elements, with realistic test data
- Use "back" if all elements on this page have been explored or lead to visited pages
- Use "stop" if you believe full coverage has been achieved
- Prefer links/buttons leading to NEW unexplored pages"""

_JOURNEY_SYNTHESIS_SYSTEM = """You are a QA engineer analyzing an exploration log.
Group the interactions into distinct user journeys (logical user flows).
Each journey should represent a meaningful user task or workflow."""

_JOURNEY_SYNTHESIS_PROMPT = """The explorer visited these pages:
{page_list}

And performed these interactions:
{interaction_log}

Group these into distinct user journeys.
Return JSON array:
[
  {{
    "name": "Journey name",
    "description": "What this journey tests",
    "step_indices": [0, 1, 2, ...]
  }}
]

Rules:
- Each step_index refers to the interaction number (0-based)
- A step can only belong to one journey
- Name journeys descriptively (e.g. "Login Flow", "Product Search", "Settings Navigation")
- Group related sequential actions together
- Return ONLY valid JSON"""


class ExplorerAgent:
    """LLM-driven autonomous web app explorer."""

    def __init__(self, config: ExplorerConfig):
        self.config = config
        self.session_id = str(uuid.uuid4())
        self.llm = get_provider()
        self._base_domain = urlparse(config.base_url).netloc
        self.graph = FlowGraph(self._base_domain)
        self.interactions: List[InteractionRecord] = []
        self._stop_requested = False
        self._step_counter = 0

        self._bfs_queue: deque = deque()
        self._explored_elements: Dict[str, Set[int]] = {}

        valid_skills = [s for s in config.skills if s in SKILL_REGISTRY]
        self._active_skills = valid_skills or ["curious_explorer"]
        skill_prompt = build_skill_prompt(self._active_skills)
        self._system_prompt = skill_prompt if skill_prompt else _DEFAULT_PLANNER_SYSTEM
        self._fill_overrides = get_fill_overrides(self._active_skills)
        self._priority_elements = get_priority_elements(self._active_skills)

    def request_stop(self) -> None:
        self._stop_requested = True

    async def run(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Main exploration loop. Yields SSE-style event dicts."""
        logging.getLogger("LiteLLM").setLevel(logging.ERROR)
        logging.getLogger("litellm").setLevel(logging.ERROR)
        logging.getLogger("httpx").setLevel(logging.WARNING)

        started = datetime.now(timezone.utc)
        deadline = started.timestamp() + (self.config.max_time_minutes * 60)

        yield self._event("start", {
            "session_id": self.session_id,
            "base_url": self.config.base_url,
            "strategy": self.config.strategy,
            "max_pages": self.config.max_pages,
            "max_time_minutes": self.config.max_time_minutes,
            "skills": self._active_skills,
        })

        async with async_playwright() as pw:
            auth_state = None
            if self.config.auth_domain:
                from testai.auth import get_auth_for_url
                auth_state = get_auth_for_url(self.config.base_url)

            context = await launch_stealth_browser(
                pw,
                auth_state=auth_state,
                headed=self.config.headed,
            )

            page = await context.new_page()
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)

            try:
                yield self._event("status", {"message": "Navigating to start page..."})
                await page.goto(
                    self.config.base_url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except PwTimeout:
                    pass

                await inject_overlay_shield(page)
                await sweep_overlays(page)
                await human_delay(500, 1000)

                consecutive_fails = 0

                while not self._should_stop(deadline):
                    snapshot = await take_snapshot(page, with_screenshot=self.llm.has_vision)

                    self.graph.visit_page(
                        snapshot.url,
                        title=snapshot.title,
                        element_count=len(snapshot.elements),
                        has_forms=any(
                            e.tag in ("input", "textarea", "select")
                            for e in snapshot.elements
                        ),
                    )

                    yield self._event("page", {
                        "url": snapshot.url,
                        "title": snapshot.title,
                        "elements": len(snapshot.elements),
                        "pages_visited": self.graph.page_count,
                        "step": self._step_counter,
                        "screenshot": snapshot.screenshot_b64[:200] + "..."
                            if snapshot.screenshot_b64 else None,
                    })

                    current_domain = urlparse(snapshot.url).netloc if snapshot.url else ""
                    off_domain = current_domain and current_domain != self._base_domain

                    if not snapshot.elements or snapshot.url in ("about:blank", "") or off_domain:
                        reason = "off-domain" if off_domain else "empty page"
                        yield self._event("status", {"message": f"Detected {reason}, returning to base..."})
                        try:
                            await page.goto(self.config.base_url,
                                            wait_until="domcontentloaded", timeout=15000)
                            await inject_overlay_shield(page)
                        except Exception:
                            logger.debug("Failed to navigate back to base URL", exc_info=True)
                        await human_delay(300, 600)
                        consecutive_fails += 1
                        if consecutive_fails >= 5:
                            yield self._event("status", {"message": "Too many failures, stopping exploration"})
                            break
                        continue

                    action = await self._plan_action(snapshot)

                    if action.action == ActionType.STOP:
                        yield self._event("status", {"message": "Explorer decided coverage is sufficient"})
                        break

                    if action.action == ActionType.BACK:
                        yield self._event("action", {
                            "type": "back",
                            "reason": action.reason,
                        })
                        try:
                            await page.go_back(timeout=10000)
                            await page.wait_for_load_state("domcontentloaded", timeout=8000)
                            await inject_overlay_shield(page)
                            await human_delay()
                        except Exception:
                            await page.goto(self.config.base_url,
                                            wait_until="domcontentloaded", timeout=15000)
                            await inject_overlay_shield(page)
                        continue

                    record = await self._execute_action(page, snapshot, action)
                    self.interactions.append(record)
                    self._step_counter += 1

                    if record.success:
                        consecutive_fails = 0
                        if record.url_before != record.url_after:
                            self.graph.add_transition(
                                record.url_before,
                                record.url_after,
                                action=record.action.value if isinstance(record.action, ActionType) else record.action,
                                element_text=record.text,
                            )
                    else:
                        consecutive_fails += 1
                        if consecutive_fails >= 3:
                            yield self._event("status", {"message": "Too many consecutive failures, navigating back..."})
                            try:
                                await page.go_back(timeout=10000)
                                await inject_overlay_shield(page)
                            except Exception:
                                await page.goto(self.config.base_url,
                                                wait_until="domcontentloaded", timeout=15000)
                                await inject_overlay_shield(page)
                            consecutive_fails = 0

                    yield self._event("interaction", {
                        "step": self._step_counter,
                        "action": record.action.value if isinstance(record.action, ActionType) else record.action,
                        "element": record.element_summary[:80],
                        "url_before": record.url_before,
                        "url_after": record.url_after,
                        "success": record.success,
                        "error": record.error[:100] if record.error else "",
                        "pages_visited": self.graph.page_count,
                    })

                    await human_delay(300, 700)

            except Exception as e:
                logger.exception("Explorer crashed")
                yield self._event("error", {"message": str(e)[:300]})
            finally:
                try:
                    await context.close()
                except Exception:
                    logger.debug("Failed to close browser context", exc_info=True)

        finished = datetime.now(timezone.utc)

        yield self._event("status", {"message": "Synthesizing journeys..."})
        journeys = await self._synthesize_journeys()

        result = ExplorerResult(
            session_id=self.session_id,
            base_url=self.config.base_url,
            strategy=self.config.strategy,
            status=SessionStatus.STOPPED.value if self._stop_requested else SessionStatus.COMPLETED.value,
            pages_visited=self.graph.page_count,
            unique_urls=self.graph.unique_urls,
            interactions=self.interactions,
            journeys=journeys,
            flow_graph=self.graph.to_dict(),
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
        )

        yield self._event("done", result.to_dict())

    # ------------------------------------------------------------------
    # Action planning
    # ------------------------------------------------------------------

    async def _plan_action(self, snapshot: PageSnapshot) -> PlannedAction:
        """Ask the LLM which element to interact with next."""
        page_key = normalize_url(snapshot.url)
        if page_key not in self._explored_elements:
            self._explored_elements[page_key] = set()

        explored = self._explored_elements.get(page_key, set())
        elements_text = snapshot.elements_summary(max_items=40)
        visited_urls = "\n".join(f"  - {u}" for u in self.graph.unique_urls[:20])

        explored_note = ""
        if explored:
            explored_note = f"\nAlready interacted with element indices: {sorted(explored)}. Do NOT pick these again.\n"

        prompt = _PLANNER_PROMPT.format(
            url=snapshot.url,
            title=snapshot.title,
            visited_count=self.graph.page_count,
            visited_urls=visited_urls,
            elements=elements_text,
        ) + explored_note

        images = [snapshot.screenshot_b64] if snapshot.screenshot_b64 and self.llm.has_vision else None

        try:
            response = self.llm.ask(
                prompt,
                system=self._system_prompt,
                temperature=0.3,
                max_tokens=512,
                images=images,
            )
        except Exception as e:
            logger.warning("LLM planning failed: %s", e)
            return self._fallback_action(snapshot)

        if not response:
            return self._fallback_action(snapshot)

        return self._parse_action(response, snapshot)

    def _parse_action(self, response: str, snapshot: PageSnapshot) -> PlannedAction:
        """Parse the LLM response into a PlannedAction."""
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{[^}]+\}', text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return self._fallback_action(snapshot)
            else:
                return self._fallback_action(snapshot)

        action_str = data.get("action", "click").lower()
        try:
            action = ActionType(action_str)
        except ValueError:
            action = ActionType.CLICK

        element_index = data.get("element_index")
        try:
            element_index = int(element_index)
        except (TypeError, ValueError):
            element_index = 0
        if element_index < 0 or element_index >= len(snapshot.elements):
            element_index = 0

        page_key = normalize_url(snapshot.url)
        explored = self._explored_elements.get(page_key, set())
        if element_index in explored and action not in (ActionType.BACK, ActionType.STOP):
            return self._fallback_action(snapshot)

        return PlannedAction(
            element_index=element_index,
            action=action,
            fill_value=data.get("fill_value", ""),
            reason=data.get("reason", ""),
        )

    def _fallback_action(self, snapshot: PageSnapshot) -> PlannedAction:
        """Deterministic fallback when LLM is unavailable or fails to parse.

        Priority order (influenced by active QA skills):
          0. Skill-priority elements (tabs, accordions, forms, etc.)
          1. Links to unvisited pages
          2. Buttons
          3. Form inputs
        Falls back to BACK if everything has been explored.
        """
        page_key = normalize_url(snapshot.url)
        explored = self._explored_elements.get(page_key, set())
        unexplored = [el for el in snapshot.elements if el.index not in explored]

        # Pass 0: skill-priority elements (e.g. accordions, tabs, form fields)
        if self._priority_elements:
            for el in unexplored:
                el_tags = f"{el.tag} {el.role or ''} {el.css_selector or ''}".lower()
                if any(prio.lower() in el_tags for prio in self._priority_elements):
                    action = ActionType.CLICK
                    fill_val = ""
                    if el.tag in ("input", "textarea"):
                        action = ActionType.FILL
                        fill_val = self._smart_fill(el)
                    return PlannedAction(
                        element_index=el.index,
                        action=action,
                        fill_value=fill_val,
                        reason=f"skill-priority: {el.tag}",
                    )

        # Pass 1: links to unvisited pages
        for el in unexplored:
            if el.tag == "a" and el.href:
                href_parsed = urlparse(el.href)
                if href_parsed.netloc and href_parsed.netloc != self._base_domain:
                    continue
                norm = normalize_url(el.href) if el.href.startswith("http") else ""
                if norm and self.graph.visit_count(el.href) >= 2:
                    continue
                return PlannedAction(
                    element_index=el.index,
                    action=ActionType.CLICK,
                    reason="fallback: unvisited link",
                )

        # Pass 2: form inputs (fill before clicking submit)
        for el in unexplored:
            if el.tag in ("input", "textarea") and el.input_type not in ("hidden", "submit", "button"):
                value = self._smart_fill(el)
                return PlannedAction(
                    element_index=el.index,
                    action=ActionType.FILL,
                    fill_value=value,
                    reason="fallback: form field",
                )

        # Pass 3: buttons and submit inputs
        for el in unexplored:
            if el.tag == "button" or el.role == "button" or el.input_type in ("submit", "button"):
                return PlannedAction(
                    element_index=el.index,
                    action=ActionType.CLICK,
                    reason="fallback: unexplored button",
                )

        # Pass 4: any remaining clickable element
        for el in unexplored:
            if el.tag in ("a", "summary", "details") or el.role in ("tab", "menuitem"):
                return PlannedAction(
                    element_index=el.index,
                    action=ActionType.CLICK,
                    reason="fallback: remaining interactive element",
                )

        return PlannedAction(
            element_index=0,
            action=ActionType.BACK,
            reason="fallback: all elements explored on this page",
        )

    # ------------------------------------------------------------------
    # Action execution
    # ------------------------------------------------------------------

    async def _execute_action(
        self, page: Page, snapshot: PageSnapshot, action: PlannedAction
    ) -> InteractionRecord:
        """Execute a planned action on the page and record the result."""
        url_before = page.url
        element = snapshot.elements[action.element_index] if action.element_index < len(snapshot.elements) else None

        page_key = normalize_url(url_before)
        if page_key not in self._explored_elements:
            self._explored_elements[page_key] = set()
        self._explored_elements[page_key].add(action.element_index)

        record = InteractionRecord(
            step_number=self._step_counter,
            url_before=url_before,
            url_after=url_before,
            action=action.action,
            element_summary=element.summary() if element else "",
            css_selector=element.css_selector if element else "",
            text=element.text if element else "",
            fill_value=action.fill_value,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if not element:
            record.success = False
            record.error = "No element found for index"
            return record

        try:
            await sweep_overlays(page)

            if action.action == ActionType.CLICK:
                await self._do_click(page, element)
            elif action.action == ActionType.FILL:
                await self._do_fill(page, element, action.fill_value)
            elif action.action == ActionType.SELECT:
                await self._do_select(page, element, action.fill_value)

            await human_delay(500, 1500)

            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except PwTimeout:
                pass

            await inject_overlay_shield(page)
            record.url_after = page.url
            record.success = True

            # Fix 1: click that didn't navigate — mark element explored so it's skipped next round
            if (action.action == ActionType.CLICK
                    and record.url_before == record.url_after):
                _pk = normalize_url(record.url_before)
                if _pk not in self._explored_elements:
                    self._explored_elements[_pk] = set()
                self._explored_elements[_pk].add(action.element_index)

            # Fix 2: fill that didn't navigate — press Enter for SPA inputs (TodoMVC, search bars, etc.)
            if (action.action == ActionType.FILL
                    and record.url_before == record.url_after
                    and element):
                try:
                    await page.locator(element.css_selector).first.press("Enter", timeout=3000)
                    await human_delay(300, 600)
                    record.url_after = page.url
                except Exception:
                    pass

        except PwTimeout as e:
            record.success = False
            record.error = f"Timeout: {str(e)[:150]}"
        except Exception as e:
            record.success = False
            record.error = str(e)[:200]

        return record

    async def _do_click(self, page: Page, element) -> None:
        """Click an element using multiple strategies."""
        sel = element.css_selector

        strategies = []
        if element.role == "link" and element.text:
            strategies.append(("role_link", f'page.get_by_role("link", name="{element.text[:60]}")'))
        if element.text and len(element.text) <= 60:
            strategies.append(("text", f'page.get_by_text("{element.text[:60]}")'))
        if sel:
            strategies.append(("css", sel))

        last_err = None
        for name, locator_expr in strategies:
            try:
                if name == "css":
                    locator = page.locator(locator_expr).first
                elif name == "role_link":
                    locator = page.get_by_role("link", name=element.text[:60]).first
                elif name == "text":
                    locator = page.get_by_text(element.text[:60], exact=False).first
                else:
                    continue

                await locator.scroll_into_view_if_needed(timeout=3000)
                await locator.click(timeout=8000)
                return
            except Exception as e:
                last_err = e
                continue

        if element.bounding_box:
            try:
                x = element.bounding_box["x"] + element.bounding_box["width"] / 2
                y = element.bounding_box["y"] + element.bounding_box["height"] / 2
                await page.mouse.click(x, y)
                return
            except Exception as e:
                last_err = e

        if last_err:
            raise last_err

    async def _do_fill(self, page: Page, element, value: str) -> None:
        """Fill a form field."""
        sel = element.css_selector

        strategies = []
        if element.placeholder:
            strategies.append(("placeholder", element.placeholder))
        if element.aria_label:
            strategies.append(("label", element.aria_label))
        if sel:
            strategies.append(("css", sel))

        for name, loc_val in strategies:
            try:
                if name == "placeholder":
                    locator = page.get_by_placeholder(loc_val).first
                elif name == "label":
                    locator = page.get_by_label(loc_val).first
                else:
                    locator = page.locator(loc_val).first

                await locator.click(timeout=3000)
                await locator.fill(value, timeout=5000)
                return
            except Exception:
                continue

        raise Exception(f"Could not fill element: {element.summary()}")

    async def _do_select(self, page: Page, element, value: str) -> None:
        """Select an option in a dropdown."""
        try:
            locator = page.locator(element.css_selector).first
            await locator.select_option(value=value, timeout=5000)
        except Exception:
            try:
                locator = page.locator(element.css_selector).first
                await locator.select_option(label=value, timeout=5000)
            except Exception:
                raise Exception(f"Could not select option in: {element.summary()}")

    # ------------------------------------------------------------------
    # Journey synthesis
    # ------------------------------------------------------------------

    async def _synthesize_journeys(self) -> List[DiscoveredJourney]:
        """Use LLM to group interactions into meaningful journeys, with fallback."""
        local_journeys = self.graph.extract_journeys(self.interactions)

        if not self.interactions:
            return local_journeys

        if not self.llm.get_status().get("has_key", False) and self.llm.config.provider != "ollama":
            return local_journeys

        page_list = "\n".join(
            f"  - {url} (visited {node.visit_count}x, {node.element_count} elements)"
            for url, node in list(self.graph.nodes.items())[:30]
        )

        interaction_log = "\n".join(
            f"  [{i}] {rec.action.value if isinstance(rec.action, ActionType) else rec.action}: "
            f"{rec.element_summary[:60]} "
            f"({rec.url_before[:50]} -> {rec.url_after[:50]})"
            for i, rec in enumerate(self.interactions[:50])
        )

        prompt = _JOURNEY_SYNTHESIS_PROMPT.format(
            page_list=page_list,
            interaction_log=interaction_log,
        )

        try:
            response = self.llm.ask(
                prompt,
                system=_JOURNEY_SYNTHESIS_SYSTEM,
                temperature=0.2,
                max_tokens=2048,
            )
        except Exception:
            logger.warning("LLM journey synthesis failed, falling back to local journeys", exc_info=True)
            return local_journeys

        if not response:
            return local_journeys

        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        try:
            journey_defs = json.loads(text)
        except json.JSONDecodeError:
            return local_journeys

        if not isinstance(journey_defs, list):
            return local_journeys

        journeys = []
        for jdef in journey_defs:
            indices = jdef.get("step_indices", [])
            steps = []
            urls = []
            for idx in indices:
                if 0 <= idx < len(self.interactions):
                    rec = self.interactions[idx]
                    urls.append(rec.url_after or rec.url_before)
                    steps.append({
                        "order": len(steps) + 1,
                        "description": f"{rec.action.value if isinstance(rec.action, ActionType) else rec.action}: {rec.element_summary[:60]}",
                        "url": rec.url_after or rec.url_before,
                        "action_type": rec.action.value if isinstance(rec.action, ActionType) else rec.action,
                        "element_hint": rec.css_selector,
                        "selectors": {"css": rec.css_selector, "text": rec.text},
                    })

            if steps:
                journeys.append(DiscoveredJourney(
                    name=jdef.get("name", f"Journey {len(journeys)+1}"),
                    description=jdef.get("description", ""),
                    steps=steps,
                    urls=list(set(urls)),
                ))

        return journeys if journeys else local_journeys

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _smart_fill(self, element) -> str:
        """Generate fill value respecting active skill overrides."""
        input_type = (element.input_type or "text").lower()
        if self._fill_overrides and input_type in self._fill_overrides:
            return self._fill_overrides[input_type]
        return _generate_fill_value(element)

    def _should_stop(self, deadline: float) -> bool:
        if self._stop_requested:
            return True
        if time.time() >= deadline:
            return True
        if self.graph.page_count >= self.config.max_pages:
            return True
        return False

    def _event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"type": event_type, **data}


async def expand_from_journey(journey_data: dict, config_overrides: dict | None = None) -> AsyncGenerator[Dict[str, Any], None]:
    """Seed-based journey expansion: given a known journey, discover related flows.

    Analyzes the seed journey's URLs, element patterns, and feature keywords,
    then launches the AI Explorer with context injection so the LLM focuses on
    related flows — alternative paths, edge cases, error states, sibling features.
    """
    steps = journey_data.get("steps", [])
    if not steps:
        yield {"type": "error", "message": "Seed journey has no steps"}
        return

    seed_urls: list[str] = []
    seed_actions: list[str] = []
    seed_elements: list[str] = []
    for s in steps:
        url = s.get("url", "")
        if url and url not in seed_urls:
            seed_urls.append(url)
        desc = s.get("description", "")
        if desc:
            seed_actions.append(desc)
        hint = s.get("element_hint") or ""
        if hint:
            seed_elements.append(hint[:80])

    base_url = seed_urls[0] if seed_urls else journey_data.get("domain", "http://localhost")
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"

    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    seed_summary = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(seed_actions[:20]))
    seed_url_list = "\n".join(f"  - {u}" for u in seed_urls[:10])

    seed_context = (
        f"SEED JOURNEY: \"{journey_data.get('name', 'Unknown')}\"\n"
        f"The user already captured this flow:\n{seed_summary}\n\n"
        f"Pages visited:\n{seed_url_list}\n\n"
        "YOUR MISSION: Discover RELATED flows that the original user did NOT try.\n"
        "Focus on:\n"
        "  - Alternative paths from the SAME pages (different buttons, menus, options)\n"
        "  - Opposite actions (delete vs create, cancel vs confirm, reject vs approve)\n"
        "  - Edge cases (empty input, boundary values, special characters)\n"
        "  - Error recovery paths (what happens if something fails mid-flow?)\n"
        "  - Sibling navigation items the user skipped\n"
        "  - Variations of the same workflow with different data\n"
        "Stay on pages the seed flow touched or their immediate neighbors."
    )

    overrides = config_overrides or {}
    config = ExplorerConfig(
        base_url=origin,
        strategy=overrides.get("strategy", "bfs"),
        max_pages=overrides.get("max_pages", 20),
        max_time_minutes=overrides.get("max_time_minutes", 8),
        auth_domain=parsed.netloc,
        headed=overrides.get("headed", True),
        skills=overrides.get("skills", ["flow_expander", "edge_case_hunter", "workflow_completionist"]),
    )

    agent = ExplorerAgent(config)

    agent._system_prompt = (
        build_skill_prompt(agent._active_skills)
        + "\n\n--- SEED CONTEXT ---\n"
        + seed_context
    )

    yield {"type": "expansion_start", "session_id": agent.session_id, "seed_journey": journey_data.get("name", ""), "base_url": origin}

    async for event in agent.run():
        yield event


def _generate_fill_value(element) -> str:
    """Generate realistic test data based on input type and context."""
    input_type = (element.input_type or "").lower()
    name = (element.name or "").lower()
    placeholder = (element.placeholder or "").lower()
    label = (element.aria_label or "").lower()

    context = f"{name} {placeholder} {label}"

    if input_type == "email" or "email" in context:
        return "testuser@example.com"
    if input_type == "password" or "password" in context:
        return "TestPass123!"
    if input_type == "tel" or "phone" in context:
        return "5551234567"
    if input_type == "number" or "amount" in context or "quantity" in context:
        return "42"
    if input_type == "url" or "url" in context or "website" in context:
        return "https://example.com"
    if "name" in context and "last" in context:
        return "TestUser"
    if "name" in context and "first" in context:
        return "Test"
    if "name" in context:
        return "Test User"
    if "search" in context or "query" in context:
        return "test search"
    if "city" in context:
        return "New York"
    if "zip" in context or "postal" in context:
        return "10001"
    if "address" in context:
        return "123 Test Street"
    if "company" in context or "organization" in context:
        return "TestCorp"
    if "title" in context:
        return "Test Title"
    if "description" in context or "message" in context or "comment" in context:
        return "This is an automated test entry"
    if input_type == "date":
        return "2025-01-15"

    return "test input"
