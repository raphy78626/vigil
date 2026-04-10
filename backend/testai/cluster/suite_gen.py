"""Test suite auto-generation — group related journeys into logical suites.

Groups journeys by domain + feature into named test suites:
  - "Auth Suite" for login/register/password-reset journeys
  - "Cart Suite" for add-to-cart, checkout, payment journeys
  - Smart fallback: URL-path prefix clustering when feature labels are sparse
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Optional
from urllib.parse import urlparse

FEATURE_KEYWORDS = {
    "auth": ["login", "sign in", "signin", "register", "signup", "sign up", "password", "forgot", "reset password", "sso", "oauth", "logout"],
    "cart": ["cart", "add to cart", "basket", "checkout", "payment", "order", "purchase", "buy"],
    "search": ["search", "filter", "sort", "query", "browse", "find"],
    "profile": ["profile", "settings", "preferences", "account", "my account", "dashboard"],
    "navigation": ["menu", "navbar", "header", "footer", "breadcrumb", "sidebar", "home"],
    "forms": ["form", "submit", "contact", "feedback", "survey", "apply"],
    "content": ["article", "blog", "post", "page", "product", "detail", "view"],
    "admin": ["admin", "manage", "config", "setup", "users"],
    "onboarding": ["onboard", "welcome", "tutorial", "walkthrough", "getting started"],
    "messaging": ["chat", "message", "inbox", "notification", "alert"],
}


class SuiteGenerator:
    def generate(self, journeys: List[Dict]) -> List[Dict]:
        """Generate test suites from a list of journeys."""
        suites = defaultdict(list)

        for j in journeys:
            suite_name = self._classify(j)
            suites[suite_name].append(j)

        result = []
        for name, members in sorted(suites.items()):
            domains = set(m.get("domain", "") for m in members if m.get("domain"))
            result.append({
                "name": name,
                "journey_count": len(members),
                "journeys": [{"id": m.get("id", ""), "name": m.get("name", "")} for m in members],
                "domains": sorted(domains),
                "estimated_duration_s": sum(len(m.get("steps", [])) * 2 for m in members),
            })

        return result

    def _classify(self, journey: Dict) -> str:
        feature = (journey.get("feature") or "").lower()
        name = (journey.get("name") or "").lower()
        domain = (journey.get("domain") or "").lower()
        first_url = ""
        steps = journey.get("steps", [])
        if steps:
            first_url = (steps[0].get("url") or "") if isinstance(steps[0], dict) else ""

        text = f"{feature} {name} {first_url}"

        for suite_key, keywords in FEATURE_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                label = suite_key.replace("_", " ").title()
                if domain:
                    return f"{domain.split('.')[0].title()} — {label} Suite"
                return f"{label} Suite"

        if domain:
            return f"{domain.split('.')[0].title()} — General Suite"

        if first_url:
            path_prefix = self._path_prefix(first_url)
            if path_prefix:
                return f"Suite: {path_prefix}"

        return "Uncategorized Suite"

    def _path_prefix(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            parts = [p for p in parsed.path.split("/") if p]
            if parts:
                return parts[0].replace("-", " ").replace("_", " ").title()
        except Exception:
            pass
        return ""

    def suggest_missing(self, journeys: List[Dict]) -> List[Dict]:
        """Suggest coverage gaps — features with no journeys."""
        covered = set()
        for j in journeys:
            text = f"{j.get('feature', '')} {j.get('name', '')}".lower()
            for suite_key, keywords in FEATURE_KEYWORDS.items():
                if any(kw in text for kw in keywords):
                    covered.add(suite_key)

        gaps = []
        for suite_key in FEATURE_KEYWORDS:
            if suite_key not in covered:
                gaps.append({
                    "feature": suite_key,
                    "suite_name": f"{suite_key.replace('_', ' ').title()} Suite",
                    "suggestion": f"No journeys cover {suite_key} flows — consider recording test sessions for: {', '.join(FEATURE_KEYWORDS[suite_key][:3])}",
                })

        return gaps
