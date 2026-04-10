"""Shadow DOM support — pierce shadow roots for Web Component-based apps.

Required for apps built with:
  - Salesforce Lightning (Lightning Web Components)
  - SAP UI5
  - Vaadin
  - Shoelace, Spectrum Web Components
  - Any custom Web Components with Shadow DOM

Generates selectors that pierce shadow boundaries:
  - Playwright: page.locator('my-component').locator('internal >> css=.button')
  - Selenium: execute_script to traverse shadowRoot
  - Cypress: cy.get('my-component').shadow().find('.button')
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional


KNOWN_SHADOW_HOSTS = {
    "lightning-", "lwc-", "force-", "ui-",
    "sl-", "sp-",
    "vaadin-",
    "ion-",
    "mwc-",
    "md-",
}


class ShadowDOMHandler:
    def is_shadow_host(self, tag_name: str) -> bool:
        tag = tag_name.lower()
        if "-" not in tag:
            return False
        return any(tag.startswith(prefix) for prefix in KNOWN_SHADOW_HOSTS) or "-" in tag

    def parse_shadow_path(self, event: Dict) -> List[Dict]:
        """Extract the shadow DOM path from a captured event.

        The extension sends composedPath() data, which includes
        shadow root boundaries.
        """
        path = event.get("composed_path") or event.get("shadow_path") or []
        if not path:
            return []

        shadow_segments = []
        current_segment = {"host": None, "elements": []}

        for node in path:
            if isinstance(node, str):
                node = {"tag": node}

            tag = node.get("tag", "").lower()
            is_shadow_root = node.get("is_shadow_root", False)

            if is_shadow_root:
                if current_segment["elements"]:
                    shadow_segments.append(current_segment)
                current_segment = {"host": tag, "elements": []}
            else:
                current_segment["elements"].append(node)

        if current_segment["elements"]:
            shadow_segments.append(current_segment)

        return shadow_segments

    def generate_playwright_selector(self, shadow_path: List[Dict]) -> str:
        """Generate a Playwright selector that pierces shadow DOM.

        Playwright supports CSS piercing via `>>` combinator.
        """
        if not shadow_path:
            return ""

        parts = []
        for segment in shadow_path:
            host = segment.get("host")
            elements = segment.get("elements", [])

            if host:
                parts.append(host)

            for el in elements:
                sel = self._best_selector(el)
                if sel:
                    parts.append(sel)
                    break

        return " >> ".join(parts) if parts else ""

    def generate_selenium_js(self, shadow_path: List[Dict]) -> str:
        """Generate JavaScript for Selenium to traverse shadow roots."""
        if not shadow_path:
            return ""

        lines = ["let el = document"]
        for i, segment in enumerate(shadow_path):
            host = segment.get("host")
            elements = segment.get("elements", [])

            if host:
                lines.append(f"el = el.querySelector('{host}')")
                lines.append("el = el.shadowRoot")

            for el in elements:
                sel = self._best_selector(el)
                if sel:
                    lines.append(f"el = el.querySelector('{sel}')")
                    break

        lines.append("return el")
        return "; ".join(lines)

    def generate_cypress_chain(self, shadow_path: List[Dict]) -> str:
        """Generate a Cypress .shadow() chain."""
        if not shadow_path:
            return ""

        parts = []
        for segment in shadow_path:
            host = segment.get("host")
            elements = segment.get("elements", [])

            if host:
                if parts:
                    parts.append(f".shadow().find('{host}')")
                else:
                    parts.append(f"cy.get('{host}')")

            for el in elements:
                sel = self._best_selector(el)
                if sel:
                    if not parts:
                        parts.append(f"cy.get('{sel}')")
                    else:
                        parts.append(f".shadow().find('{sel}')")
                    break

        return "".join(parts)

    def enrich_event(self, event: Dict) -> Dict:
        """Enrich a captured event with shadow DOM selector metadata."""
        shadow_path = self.parse_shadow_path(event)
        if not shadow_path:
            return event

        event["shadow_dom"] = {
            "pierced": True,
            "depth": len(shadow_path),
            "playwright_selector": self.generate_playwright_selector(shadow_path),
            "selenium_js": self.generate_selenium_js(shadow_path),
            "cypress_chain": self.generate_cypress_chain(shadow_path),
        }
        return event

    def _best_selector(self, el: Dict) -> str:
        if isinstance(el, str):
            return el
        attrs = el.get("attributes", {}) or {}
        for attr in ("data-testid", "data-test", "data-cy", "id"):
            val = attrs.get(attr) or el.get(attr)
            if val:
                if attr == "id":
                    return f"#{val}"
                return f"[{attr}=\"{val}\"]"
        tag = el.get("tag", "")
        cls = attrs.get("class", "") or el.get("class", "")
        if tag and cls:
            first_cls = cls.split()[0]
            return f"{tag}.{first_cls}"
        if tag:
            return tag
        return ""
