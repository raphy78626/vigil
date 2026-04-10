"""Site Quality Auditor — AI-powered webapp assessment.

Launches a headless browser, analyzes DOM structure, tech stack,
performance metrics, and uses LLM (optionally with vision) to produce
a structured site report card with letter grades.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Known framework signatures in the DOM or scripts
_FRAMEWORK_SIGNATURES = {
    "__NEXT_DATA__": "Next.js",
    "__NUXT__": "Nuxt.js",
    "ng-version": "Angular",
    "data-reactroot": "React",
    "data-react-helmet": "React",
    "__vue__": "Vue.js",
    "data-svelte": "Svelte",
    "ember-view": "Ember.js",
    "_gatsby": "Gatsby",
}

_CSS_LIB_PATTERNS = {
    "tailwind": "Tailwind CSS",
    "bootstrap": "Bootstrap",
    "material": "Material UI",
    "chakra": "Chakra UI",
    "ant-": "Ant Design",
    "bulma": "Bulma",
    "foundation": "Foundation",
}

_AUDIT_SYSTEM_PROMPT = """\
You are a senior web consultant performing a structured site quality audit.
You will receive DOM statistics, tech stack detection results, performance
metrics, and optionally a screenshot of the page.

Return ONLY valid JSON with this exact structure:
{
  "usability": {"score": 0-100, "grade": "A-F", "issues": ["..."], "strengths": ["..."]},
  "appearance": {"score": 0-100, "grade": "A-F", "feedback": ["..."]},
  "accessibility": {"score": 0-100, "grade": "A-F", "issues": ["..."]},
  "performance": {"score": 0-100, "grade": "A-F", "metrics": {...}},
  "tech_stack": {"framework": "...", "css_lib": "...", "analytics": [...], "cdn": "...", "is_modern": true/false, "details": "..."},
  "recommendations": ["top 5 actionable improvements"],
  "overall_grade": "A-F",
  "overall_score": 0-100,
  "summary": "2-3 sentence executive summary"
}

Scoring guide:
- A (90-100): Excellent, industry best practice
- B (75-89): Good, minor improvements possible
- C (60-74): Average, noticeable gaps
- D (40-59): Below average, significant issues
- F (0-39): Poor, critical problems
"""


@dataclass
class DOMStats:
    total_elements: int = 0
    headings: Dict[str, int] = field(default_factory=dict)
    images_total: int = 0
    images_with_alt: int = 0
    forms: int = 0
    inputs_with_label: int = 0
    inputs_total: int = 0
    links_total: int = 0
    links_with_text: int = 0
    aria_attributes: int = 0
    has_viewport_meta: bool = False
    has_lang_attr: bool = False
    has_skip_link: bool = False
    has_main_landmark: bool = False
    color_contrast_issues: int = 0


@dataclass
class TechStack:
    framework: str = "Unknown"
    css_library: str = "Unknown"
    analytics: List[str] = field(default_factory=list)
    cdn: str = ""
    server: str = ""
    http_headers: Dict[str, str] = field(default_factory=dict)
    scripts: List[str] = field(default_factory=list)
    is_spa: bool = False
    is_pwa: bool = False


@dataclass
class PerfMetrics:
    ttfb_ms: float = 0
    lcp_ms: float = 0
    cls: float = 0
    dom_content_loaded_ms: float = 0
    load_time_ms: float = 0
    total_resources: int = 0
    total_transfer_kb: float = 0
    slowest_resources: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class AuditResult:
    url: str = ""
    dom_stats: DOMStats = field(default_factory=DOMStats)
    tech_stack: TechStack = field(default_factory=TechStack)
    perf_metrics: PerfMetrics = field(default_factory=PerfMetrics)
    screenshot_b64: str = ""
    llm_review: Dict[str, Any] = field(default_factory=dict)
    raw_scores: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SiteAuditor:
    """Performs comprehensive site quality audits using Playwright + LLM."""

    def __init__(self, llm_provider=None):
        self.llm = llm_provider

    async def audit(self, url: str, depth: int = 1) -> AuditResult:
        """Run a full site audit on the given URL."""
        from playwright.async_api import async_playwright

        result = AuditResult(url=url)

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                )
                page = await context.new_page()

                response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

                if response:
                    for header in ["server", "x-powered-by", "x-frame-options",
                                   "content-security-policy", "strict-transport-security"]:
                        val = response.headers.get(header)
                        if val:
                            result.tech_stack.http_headers[header] = val
                    result.tech_stack.server = response.headers.get("server", "")

                result.dom_stats = await self._analyze_dom(page)
                result.tech_stack = await self._detect_tech(page, result.tech_stack)
                result.perf_metrics = await self._collect_perf(page)

                try:
                    screenshot_bytes = await page.screenshot(full_page=True, type="png")
                    result.screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
                except Exception as e:
                    logger.warning("Screenshot failed: %s", e)

                await browser.close()

        except Exception as e:
            result.error = str(e)[:500]
            logger.error("Audit failed for %s: %s", url, e, exc_info=True)
            return result

        if self.llm:
            result.llm_review = await self._llm_review(result)
            result.raw_scores = result.llm_review

        return result

    async def _analyze_dom(self, page) -> DOMStats:
        """Extract DOM structure statistics."""
        stats = DOMStats()
        try:
            stats_raw = await page.evaluate("""() => {
                const stats = {
                    total_elements: document.querySelectorAll('*').length,
                    headings: {},
                    images_total: document.querySelectorAll('img').length,
                    images_with_alt: document.querySelectorAll('img[alt]:not([alt=""])').length,
                    forms: document.querySelectorAll('form').length,
                    inputs_total: document.querySelectorAll('input, textarea, select').length,
                    inputs_with_label: 0,
                    links_total: document.querySelectorAll('a').length,
                    links_with_text: 0,
                    aria_attributes: document.querySelectorAll('[aria-label], [aria-describedby], [role]').length,
                    has_viewport_meta: !!document.querySelector('meta[name="viewport"]'),
                    has_lang_attr: !!document.documentElement.lang,
                    has_skip_link: !!document.querySelector('a[href="#main"], a[href="#content"], .skip-link, .skip-nav'),
                    has_main_landmark: !!document.querySelector('main, [role="main"]'),
                };
                for (let i = 1; i <= 6; i++) {
                    const count = document.querySelectorAll('h' + i).length;
                    if (count > 0) stats.headings['h' + i] = count;
                }
                document.querySelectorAll('input, textarea, select').forEach(el => {
                    if (el.id && document.querySelector('label[for="' + el.id + '"]')) {
                        stats.inputs_with_label++;
                    } else if (el.closest('label')) {
                        stats.inputs_with_label++;
                    } else if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) {
                        stats.inputs_with_label++;
                    }
                });
                document.querySelectorAll('a').forEach(a => {
                    const text = (a.textContent || '').trim();
                    if (text.length > 0 || a.getAttribute('aria-label')) {
                        stats.links_with_text++;
                    }
                });
                return stats;
            }""")
            stats = DOMStats(**stats_raw)
        except Exception as e:
            logger.warning("DOM analysis failed: %s", e)
        return stats

    async def _detect_tech(self, page, existing: TechStack) -> TechStack:
        """Detect frameworks, CSS libraries, analytics from DOM and scripts."""
        tech = existing
        try:
            detection = await page.evaluate("""() => {
                const result = {
                    scripts: [],
                    framework_hints: [],
                    is_spa: false,
                    is_pwa: false,
                };

                document.querySelectorAll('script[src]').forEach(s => {
                    result.scripts.push(s.src);
                });

                // Framework detection
                if (document.querySelector('[data-reactroot], [data-react-helmet], #__next')) {
                    result.framework_hints.push('React');
                }
                if (window.__NEXT_DATA__) result.framework_hints.push('Next.js');
                if (window.__NUXT__) result.framework_hints.push('Nuxt.js');
                if (document.querySelector('[ng-version], [_nghost]')) result.framework_hints.push('Angular');
                if (document.querySelector('[data-v-]') || window.__vue__) result.framework_hints.push('Vue.js');
                if (document.querySelector('[data-svelte]')) result.framework_hints.push('Svelte');

                // SPA detection
                if (document.querySelector('[id="root"], [id="app"], [id="__next"], [id="__nuxt"]')) {
                    result.is_spa = true;
                }

                // PWA detection
                if (document.querySelector('link[rel="manifest"]')) {
                    result.is_pwa = true;
                }

                return result;
            }""")

            tech.scripts = detection.get("scripts", [])[:10]
            tech.is_spa = detection.get("is_spa", False)
            tech.is_pwa = detection.get("is_pwa", False)

            hints = detection.get("framework_hints", [])
            if hints:
                tech.framework = hints[0]

            # Detect CSS library from stylesheets and classes
            page_html = await page.content()
            page_lower = page_html.lower()
            for pattern, lib_name in _CSS_LIB_PATTERNS.items():
                if pattern in page_lower:
                    tech.css_library = lib_name
                    break

            # Analytics detection from script sources
            analytics_patterns = {
                "google-analytics": "Google Analytics",
                "googletagmanager": "Google Tag Manager",
                "segment.com": "Segment",
                "mixpanel": "Mixpanel",
                "amplitude": "Amplitude",
                "hotjar": "Hotjar",
                "fullstory": "FullStory",
                "sentry": "Sentry",
                "datadog": "Datadog",
            }
            for src in tech.scripts:
                src_lower = src.lower()
                for pattern, name in analytics_patterns.items():
                    if pattern in src_lower and name not in tech.analytics:
                        tech.analytics.append(name)

            # CDN detection
            cdn_patterns = {
                "cloudflare": "Cloudflare",
                "fastly": "Fastly",
                "akamai": "Akamai",
                "cloudfront": "CloudFront",
                "vercel": "Vercel",
                "netlify": "Netlify",
            }
            server = (tech.server or "").lower()
            for pattern, name in cdn_patterns.items():
                if pattern in server:
                    tech.cdn = name
                    break

        except Exception as e:
            logger.warning("Tech detection failed: %s", e)
        return tech

    async def _collect_perf(self, page) -> PerfMetrics:
        """Collect performance metrics from the page."""
        metrics = PerfMetrics()
        try:
            perf_data = await page.evaluate("""() => {
                const nav = performance.getEntriesByType('navigation')[0] || {};
                const resources = performance.getEntriesByType('resource') || [];

                let lcp = 0;
                let cls = 0;
                try {
                    const lcpEntries = performance.getEntriesByType('largest-contentful-paint');
                    if (lcpEntries.length) lcp = lcpEntries[lcpEntries.length - 1].startTime;
                } catch(e) {}

                try {
                    const clsEntries = performance.getEntriesByType('layout-shift');
                    clsEntries.forEach(e => { if (!e.hadRecentInput) cls += e.value; });
                } catch(e) {}

                const totalBytes = resources.reduce((sum, r) => sum + (r.transferSize || 0), 0);
                const slowest = [...resources]
                    .sort((a, b) => b.duration - a.duration)
                    .slice(0, 5)
                    .map(r => ({name: r.name.slice(-80), duration_ms: Math.round(r.duration), size_kb: Math.round((r.transferSize || 0) / 1024)}));

                return {
                    ttfb_ms: Math.round(nav.responseStart - nav.requestStart || 0),
                    lcp_ms: Math.round(lcp),
                    cls: Math.round(cls * 1000) / 1000,
                    dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd - nav.startTime || 0),
                    load_time_ms: Math.round(nav.loadEventEnd - nav.startTime || 0),
                    total_resources: resources.length,
                    total_transfer_kb: Math.round(totalBytes / 1024),
                    slowest_resources: slowest,
                };
            }""")
            metrics = PerfMetrics(**perf_data)
        except Exception as e:
            logger.warning("Perf collection failed: %s", e)
        return metrics

    async def _llm_review(self, result: AuditResult) -> Dict[str, Any]:
        """Send collected data to LLM for structured quality assessment."""
        if not self.llm:
            return {}

        prompt = f"""Analyze this website and provide a quality audit:

URL: {result.url}

DOM STATISTICS:
- Total elements: {result.dom_stats.total_elements}
- Headings: {json.dumps(result.dom_stats.headings)}
- Images: {result.dom_stats.images_total} total, {result.dom_stats.images_with_alt} with alt text
- Forms: {result.dom_stats.forms}, Inputs: {result.dom_stats.inputs_total} ({result.dom_stats.inputs_with_label} with labels)
- Links: {result.dom_stats.links_total} total, {result.dom_stats.links_with_text} with text
- ARIA attributes: {result.dom_stats.aria_attributes}
- Viewport meta: {result.dom_stats.has_viewport_meta}, Lang attr: {result.dom_stats.has_lang_attr}
- Skip link: {result.dom_stats.has_skip_link}, Main landmark: {result.dom_stats.has_main_landmark}

TECH STACK:
- Framework: {result.tech_stack.framework}
- CSS: {result.tech_stack.css_library}
- Analytics: {', '.join(result.tech_stack.analytics) or 'None detected'}
- CDN: {result.tech_stack.cdn or 'Unknown'}
- Server: {result.tech_stack.server or 'Unknown'}
- SPA: {result.tech_stack.is_spa}, PWA: {result.tech_stack.is_pwa}

PERFORMANCE:
- TTFB: {result.perf_metrics.ttfb_ms}ms
- LCP: {result.perf_metrics.lcp_ms}ms
- CLS: {result.perf_metrics.cls}
- DOM Content Loaded: {result.perf_metrics.dom_content_loaded_ms}ms
- Full Load: {result.perf_metrics.load_time_ms}ms
- Resources: {result.perf_metrics.total_resources} ({result.perf_metrics.total_transfer_kb}KB)
- Slowest: {json.dumps(result.perf_metrics.slowest_resources[:3])}

Provide your structured quality assessment as JSON."""

        try:
            images = []
            if self.llm.has_vision and result.screenshot_b64:
                images = [result.screenshot_b64[:500000]]

            response = self.llm.ask(
                prompt,
                system=_AUDIT_SYSTEM_PROMPT,
                max_tokens=2048,
                images=images or None,
            )

            if not response:
                return {}

            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            return json.loads(text)

        except json.JSONDecodeError:
            logger.warning("LLM audit response was not valid JSON")
            return {"error": "Invalid JSON response from LLM"}
        except Exception as e:
            logger.error("LLM review failed: %s", e, exc_info=True)
            return {"error": str(e)[:200]}
