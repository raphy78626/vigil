"""Selenium + Pytest Test Generator — third framework export for maximum market coverage.

Generated tests use:
  - pytest + selenium (webdriver)
  - Multi-strategy locator fallback (By.CSS_SELECTOR, By.XPATH, By.ID, By.NAME)
  - WebDriverWait for dynamic elements
  - Screenshots on failure
  - Configurable base URL via env var
"""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urlparse

from testai.models.journey import Journey
from testai.models.step import Step

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_NUMERIC_ID_RE = re.compile(r"/\d{4,}/")


def _safe(text: str) -> str:
    return text.replace('"', '\\"').replace("\n", " ").strip()


def _first_url(journey: Journey) -> str:
    for step in journey.steps:
        if step.url:
            parsed = urlparse(step.url)
            return f"{parsed.scheme}://{parsed.netloc}"
    return "http://localhost"


class SeleniumExporter:
    def export(self, journey: Journey) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", journey.name.lower()).strip("_")[:40]
        origin = _first_url(journey)
        steps = journey.steps
        total = len(steps)

        lines = [
            '"""Auto-generated Selenium test by Vigil."""',
            "",
            "import os",
            "import time",
            "import pytest",
            "from selenium import webdriver",
            "from selenium.webdriver.common.by import By",
            "from selenium.webdriver.common.keys import Keys",
            "from selenium.webdriver.common.action_chains import ActionChains",
            "from selenium.webdriver.support.ui import WebDriverWait",
            "from selenium.webdriver.support import expected_conditions as EC",
            "from selenium.common.exceptions import TimeoutException, NoSuchElementException",
            "",
            "",
            f'BASE_URL = os.environ.get("BASE_URL", "{origin}")',
            "TIMEOUT = int(os.environ.get(\"TESTAI_TIMEOUT\", \"15\"))",
            "",
            "",
            "@pytest.fixture",
            "def driver():",
            '    """Set up Chrome WebDriver with standard options."""',
            "    options = webdriver.ChromeOptions()",
            '    if os.environ.get("HEADLESS", "true").lower() == "true":',
            '        options.add_argument("--headless=new")',
            '    options.add_argument("--no-sandbox")',
            '    options.add_argument("--disable-dev-shm-usage")',
            '    options.add_argument("--window-size=1280,800")',
            "    d = webdriver.Chrome(options=options)",
            "    d.implicitly_wait(TIMEOUT)",
            "    yield d",
            "    d.quit()",
            "",
            "",
            "def _find(driver, selectors, description):",
            '    """Try multiple locator strategies until one works."""',
            "    strategies = []",
            "    if selectors.get('test_id'):",
            "        strategies.append((By.CSS_SELECTOR, f'[data-testid=\"{selectors[\"test_id\"]}\"]'))",
            "    if selectors.get('id'):",
            "        strategies.append((By.ID, selectors['id']))",
            "    if selectors.get('name'):",
            "        strategies.append((By.NAME, selectors['name']))",
            "    if selectors.get('aria_label'):",
            "        strategies.append((By.CSS_SELECTOR, f'[aria-label=\"{selectors[\"aria_label\"]}\"]'))",
            "    if selectors.get('css'):",
            "        strategies.append((By.CSS_SELECTOR, selectors['css']))",
            "    if selectors.get('text'):",
            "        strategies.append((By.XPATH, f'//*[contains(text(), \"{selectors[\"text\"]}\")]'))",
            "    if not strategies:",
            "        strategies.append((By.XPATH, f'//*[contains(text(), \"{description[:50]}\")]'))",
            "",
            "    for by, val in strategies:",
            "        try:",
            "            el = WebDriverWait(driver, TIMEOUT).until(",
            "                EC.element_to_be_clickable((by, val))",
            "            )",
            "            return el",
            "        except (TimeoutException, NoSuchElementException):",
            "            continue",
            '    raise Exception(f"Element not found: {description}")',
            "",
            "",
            f"def test_{slug}(driver):",
            f'    """Vigil journey: {_safe(journey.name)} — All {total} steps."""',
        ]

        for i, step in enumerate(steps):
            n = i + 1
            lines.append(f"    # Step {n}/{total} — {_safe(step.description)}")
            lines.append(f'    print(f"  ▸ Step {n}/{total} — {_safe(step.description)}")')

            action = (step.action_type or "click").lower()
            sel_dict = self._build_sel_dict(step)

            if action in ("navigate", "pageload", "navigation") or (step.url and i == 0):
                path = urlparse(step.url or "").path or "/"
                lines.append(f'    driver.get(BASE_URL + "{path}")')
                lines.append("    WebDriverWait(driver, TIMEOUT).until(")
                lines.append("        lambda d: d.execute_script('return document.readyState') == 'complete'")
                lines.append("    )")
            elif action in ("click", "submit"):
                lines.append(f"    el = _find(driver, {sel_dict}, \"{_safe(step.description)}\")")
                lines.append("    el.click()")
            elif action in ("input", "fill", "change"):
                val = self._guess_value(step)
                lines.append(f"    el = _find(driver, {sel_dict}, \"{_safe(step.description)}\")")
                lines.append("    el.clear()")
                lines.append(f'    el.send_keys("{_safe(val)}")')
            elif action == "select":
                lines.append(f"    el = _find(driver, {sel_dict}, \"{_safe(step.description)}\")")
                lines.append("    from selenium.webdriver.support.ui import Select")
                lines.append("    Select(el).select_by_visible_text(el.find_elements(By.TAG_NAME, 'option')[1].text)")
            elif action == "scroll":
                lines.append(f"    el = _find(driver, {sel_dict}, \"{_safe(step.description)}\")")
                lines.append("    driver.execute_script('arguments[0].scrollIntoView({block:\"center\"});', el)")
            elif action == "hover":
                lines.append(f"    el = _find(driver, {sel_dict}, \"{_safe(step.description)}\")")
                lines.append("    ActionChains(driver).move_to_element(el).perform()")
            else:
                lines.append(f"    el = _find(driver, {sel_dict}, \"{_safe(step.description)}\")")
                lines.append("    el.click()")

            lines.append(f'    _shot(driver, {n})')
            lines.append("")

        lines.append('    print("  ✓ All steps passed")')
        lines.append("")
        lines.append("")
        lines.append("def _shot(driver, n):")
        lines.append('    d = os.environ.get("SCREENSHOT_DIR", "")')
        lines.append("    if d:")
        lines.append("        import pathlib")
        lines.append("        pathlib.Path(d).mkdir(parents=True, exist_ok=True)")
        lines.append("        path = f\"{d}/step_{n:02d}.png\"")
        lines.append("        driver.save_screenshot(path)")
        lines.append("        print(f\"__SCREENSHOT__:step_{n:02d}.png\")")
        lines.append("")

        return "\n".join(lines)

    def _build_sel_dict(self, step: Step) -> str:
        sel = step.selectors or {}
        d = {}
        for key in ("test_id", "id", "name", "aria_label", "css", "text", "role", "label"):
            if sel.get(key):
                d[key] = sel[key]
        if not d and step.element_hint:
            d["text"] = step.element_hint[:60]
        if not d and step.description:
            d["text"] = step.description[:60]
        return repr(d)

    def _guess_value(self, step: Step) -> str:
        desc = (step.description or "").lower()
        sel = step.selectors or {}
        input_type = sel.get("input_type", "text")
        if "password" in desc or input_type == "password":
            return 'os.environ.get("TEST_PASSWORD", "TestPass123!")'
        if "email" in desc or input_type == "email":
            return "test@example.com"
        if "phone" in desc or input_type == "tel":
            return "555-0100"
        if "zip" in desc or "postal" in desc:
            return "10001"
        return "Test Value"

    def export_requirements(self) -> str:
        return "selenium>=4.15.0\npytest>=7.0\nwebdriver-manager>=4.0\n"
