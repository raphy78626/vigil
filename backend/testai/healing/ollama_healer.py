"""Ollama-powered auto-healing for failing Playwright tests.

Flow:
  1. Test fails → parse error output to find failing step + error type
  2. Send failing code + error + context to local Ollama model
  3. Receive patched code for the failing step
  4. Splice patch into the test file
  5. Re-run

Requires: Ollama running locally (http://localhost:11434)
Model preference: qwen2.5-coder:7b (fast, good at code)
"""

from __future__ import annotations

import ast
import json
import re
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"
PREFERRED_MODELS = ["qwen2.5-coder:7b", "qwen2.5:7b", "qwen2.5-coder:1.5b"]


@dataclass
class FailureContext:
    step_number: int
    total_steps: int
    error_message: str
    error_type: str          # "overlay", "timeout", "not_found", "auth_redirect", "wrong_element", "other"
    failing_code_line: str
    full_test_code: str
    test_file_path: str
    current_url: str = ""
    page_title: str = ""
    visible_inputs: str = ""
    console_errors: str = ""


@dataclass
class HealResult:
    success: bool
    patched_code: str
    explanation: str
    model_used: str
    attempts: int


def _check_ollama() -> Optional[str]:
    """Check Ollama is running and find the best available model."""
    try:
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if resp.status_code != 200:
            return None
        models = [m["name"] for m in resp.json().get("models", [])]
        for pref in PREFERRED_MODELS:
            for m in models:
                if m.startswith(pref.split(":")[0]) and (
                    ":" not in pref or pref in m
                ):
                    return m
        return models[0] if models else None
    except (httpx.HTTPError, httpx.TimeoutException, ConnectionError):
        return None


def _classify_error(error_text: str) -> str:
    if "Auth required" in error_text and "login form detected" in error_text:
        return "auth_redirect"
    if "intercepts pointer events" in error_text:
        return "overlay"
    low = error_text.lower()
    if "cannot be filled" in low or "input of type" in low:
        return "wrong_element"
    _AUTH_PATHS = [
        "/login", "/signin", "/sign-in", "/sign_in",
        "/auth", "/authenticate", "/authentication",
        "/accounts", "/sso", "/saml", "/portal",
        "/session/new", "/users/sign_in", "/wp-login.php",
        "401", "403",
    ]
    if "timeout" in low and "waiting for locator" in low:
        if any(p in low for p in _AUTH_PATHS):
            return "auth_redirect"
    if "password(" in low and "visible inputs:" in low:
        return "auth_redirect"
    if "Timeout" in error_text and "waiting for locator" in error_text:
        return "not_found"
    if "Timeout" in error_text:
        return "timeout"
    if "strict mode violation" in error_text:
        return "ambiguous_selector"
    return "other"


def _parse_failure(test_output: str, test_code: str) -> Optional[FailureContext]:
    """Extract structured failure info from pytest output."""
    # Find the LAST step (the one that failed)
    step_matches = list(re.finditer(
        r"Step\s+(\d+)/(\d+)",
        test_output,
    ))
    step_num = int(step_matches[-1].group(1)) if step_matches else 0
    total = int(step_matches[-1].group(2)) if step_matches else 0

    error_lines = []
    capture = False
    for line in test_output.splitlines():
        if "FAILED" in line or "Error" in line:
            capture = True
        if capture:
            error_lines.append(line)
        if len(error_lines) > 30:
            break

    error_text = "\n".join(error_lines) if error_lines else test_output[-2000:]
    error_type = _classify_error(error_text)

    failing_line = ""
    line_match = re.search(r"test_replay\.py:(\d+):", test_output)
    if line_match:
        lineno = int(line_match.group(1))
        code_lines = test_code.splitlines()
        start = max(0, lineno - 5)
        end = min(len(code_lines), lineno + 5)
        failing_line = "\n".join(code_lines[start:end])

    # Extract page context from heal output
    current_url = ""
    page_title = ""
    visible_inputs = ""
    console_errors = ""
    for line in test_output.splitlines():
        if "[heal]   current URL:" in line:
            current_url = line.split("current URL:", 1)[-1].strip()
        elif "[heal]   page title :" in line:
            page_title = line.split("page title :", 1)[-1].strip()
        elif "[heal]   visible inputs:" in line:
            visible_inputs = line.split("visible inputs:", 1)[-1].strip()
        elif "__CONSOLE_ERROR__:" in line:
            console_errors += line.split("__CONSOLE_ERROR__:", 1)[-1].strip() + "; "

    # Infer auth redirect from error + URL context
    if error_type == "wrong_element" and not current_url:
        if "login-button" in error_text or "type=\"submit\"" in error_text:
            error_type = "auth_redirect"

    return FailureContext(
        step_number=step_num,
        total_steps=total,
        error_message=error_text[:2000],
        error_type=error_type,
        failing_code_line=failing_line,
        full_test_code=test_code,
        test_file_path="test_replay.py",
        current_url=current_url,
        page_title=page_title,
        visible_inputs=visible_inputs,
        console_errors=console_errors,
    )


_SYSTEM_PROMPT = """\
You are a Playwright test auto-healer. A test step has failed and you must fix it.

CRITICAL RULES:
1. This is a pytest-playwright test. The `page` object is a FIXTURE parameter — do NOT use sync_playwright(), do NOT create browser/context/page yourself.
2. The test function signature MUST be: def test_XXX(page: Page, base_url: str):
3. Return ONLY the fixed Python function starting with "def test_" — no markdown fences, no explanation.
4. Keep ALL existing helpers (_heal, _shot, _do, _dismiss_overlay, _TIMEOUT, _SHOTS) unchanged.
5. Keep ALL existing imports unchanged. Do NOT add new imports. Available: os, re, pathlib, pytest, playwright.sync_api (Page, expect, TimeoutError as PwTimeout).
6. Keep the step numbering and print statements intact.

CONTEXT AWARENESS (MOST IMPORTANT):
- ALWAYS check CURRENT URL and PAGE TITLE in the error context. If the page is on a LOGIN page but the test expects a CHECKOUT/DASHBOARD page, the test MUST first authenticate (login) before proceeding. Add login steps!
- If error is "Input of type submit cannot be filled" — the selector is resolving to a SUBMIT BUTTON instead of a text input. The real issue is usually that the page hasn't loaded the expected form (likely an auth redirect). Add a login flow BEFORE the form fill.
- For saucedemo.com: login requires filling [data-test="username"] with "standard_user", [data-test="password"] with "secret_sauce", then clicking [data-test="login-button"], then navigating to the target page.

COMMON FIXES:
- Auth redirect (on login page instead of target) → add login steps before navigating to the target page
- "Input of type submit cannot be filled" → you're on the WRONG PAGE; the selector found a submit button because the expected form doesn't exist here. Fix the navigation/auth flow.
- React ID like [id=':r2k:'] not found → replace with page.get_by_role("textbox").last or page.locator("input[type='text']:visible").last
- Overlay blocking click → add page.wait_for_timeout(2000) then locator.click(force=True)
- Element not found → try text-based: page.get_by_text("..."), or role-based: page.get_by_role("button", name="...")
- After a click that opens a form/modal, add page.wait_for_timeout(2000) before the next fill step
- strict mode violation → add .first to the locator
- NEVER use "input:visible" to fill — use "input[type='text']:visible" to exclude submit/button/hidden inputs
"""


def _build_prompt(ctx: FailureContext) -> str:
    # Only send the 20-line window around the failure, not the entire test
    code_lines = ctx.full_test_code.splitlines()

    fn_start = 0
    for i, line in enumerate(code_lines):
        if line.startswith("def test_"):
            fn_start = i
            break

    # Find the failing line number from error
    fail_lineno = 0
    lineno_match = re.search(r"test_replay\.py:(\d+):", ctx.error_message)
    if lineno_match:
        fail_lineno = int(lineno_match.group(1))

    # Pass the entire test function
    test_function_code = "\n".join(code_lines[fn_start:])

    # Build page context section if available
    page_context = ""
    if ctx.current_url or ctx.page_title or ctx.visible_inputs:
        page_context = f"""
PAGE CONTEXT AT TIME OF FAILURE:
  Current URL:    {ctx.current_url or 'unknown'}
  Page Title:     {ctx.page_title or 'unknown'}
  Visible Inputs: {ctx.visible_inputs[:500] if ctx.visible_inputs else 'none detected'}
"""
        if ctx.current_url and any(p in ctx.current_url.lower() for p in ['/login', '/signin', '/sign-in', '/auth', 'accounts.google.com']):
            if 'checkout' not in ctx.current_url.lower():
                page_context += """
  *** CRITICAL: The browser is on a LOGIN page, NOT the target page! ***
  *** The test MUST authenticate first before navigating to the target. ***
"""
    if ctx.console_errors:
        page_context += f"\n  JS Console Errors: {ctx.console_errors[:300]}\n"

    # Build error-specific fix instructions
    fix_instructions = {
        "wrong_element": '- The selector resolved to a SUBMIT BUTTON (type="submit") instead of a text input.\n- This usually means the page is WRONG (e.g., login page instead of checkout).\n- FIX: Add login/authentication steps BEFORE navigating to the target page.\n- For saucedemo.com: fill username "standard_user", password "secret_sauce", click login, THEN navigate.',
        "auth_redirect": "- The browser was REDIRECTED to a login page.\n- FIX: Add authentication steps at the start of the test.\n- For saucedemo.com: navigate to /, fill username/password, click login, then goto target page.",
        "overlay": "- An overlay/popup is blocking the click.\n- FIX: add page.wait_for_timeout(2000) then locator.click(force=True)",
        "not_found": "- Element not found within timeout.\n- FIX: try page.get_by_text('...', exact=True).first.click() or check page URL",
        "timeout": "- General timeout.\n- FIX: increase wait time, or check if page loaded correctly (might need auth)",
        "ambiguous_selector": "- Multiple elements match the selector.\n- FIX: add .first or .nth(0) to narrow down",
    }
    fix_text = fix_instructions.get(ctx.error_type, "- Inspect the error and fix the failing line")

    return f"""A Playwright test step failed. You must fix the code.

RULES:
- This is pytest-playwright. `page` is a fixture. NEVER use sync_playwright/browser/context.
- Function signature: def test_XXX(page: Page, base_url: str):
- Helpers available: _heal(page, locators, action), _shot(page, n), _dismiss_overlay(page), _do(loc, action, timeout)
- Available imports: os, re, pathlib, pytest, Page, expect, PwTimeout
- NEVER use "input:visible" without type filter — use "input[type='text']:visible" to avoid selecting submit buttons
{page_context}
ERROR TYPE: {ctx.error_type}

ERROR:
{ctx.error_message[:800]}

FULL TEST FUNCTION:
```python
{test_function_code}
```

FIX INSTRUCTIONS for "{ctx.error_type}":
{fix_text}

Return the ENTIRE `def test_...` function with your fix applied. Do NOT truncate the function. Do NOT add any explanation. Start your response with `def test_`."""


class OllamaHealer:
    def __init__(self, base_url: str = OLLAMA_URL):
        self.base_url = base_url
        self.model = None

    def available(self) -> bool:
        self.model = _check_ollama()
        return self.model is not None

    def heal(self, test_output: str, test_code: str) -> Optional[HealResult]:
        if not self.model and not self.available():
            logger.warning("Ollama not available — skipping auto-heal")
            return HealResult(False, "", "Ollama not running", "", 0)

        ctx = _parse_failure(test_output, test_code)
        if not ctx:
            return HealResult(False, "", "Could not parse test failure", self.model or "", 0)

        prompt = _build_prompt(ctx)
        logger.info(
            "Sending heal request to Ollama (%s) for step %d error=%s",
            self.model, ctx.step_number, ctx.error_type,
        )

        try:
            resp = httpx.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "system": _SYSTEM_PROMPT,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 2048},
                },
                timeout=240,
            )
            if resp.status_code != 200:
                msg = f"Ollama returned HTTP {resp.status_code}"
                logger.error("%s: %s", msg, resp.text[:500])
                return HealResult(False, "", msg, self.model, 1)

            raw = resp.json().get("response", "")
            logger.info("Ollama response length: %d chars", len(raw))

            patched = _extract_code(raw, test_code)
            if not patched:
                return HealResult(
                    success=False,
                    patched_code="",
                    explanation="Could not extract valid code from Ollama response",
                    model_used=self.model,
                    attempts=1,
                )

            return HealResult(
                success=True,
                patched_code=patched,
                explanation=f"Auto-healed step {ctx.step_number} ({ctx.error_type})",
                model_used=self.model,
                attempts=1,
            )

        except httpx.TimeoutException:
            return HealResult(False, "", "Ollama request timed out (180s)", self.model, 1)
        except Exception as e:
            logger.error("Ollama heal error: %s", e, exc_info=True)
            return HealResult(False, "", f"Error: {e}", self.model or "", 1)


_FORBIDDEN_PATTERNS = [
    "sync_playwright",
    "browser = ",
    "browser.new_context",
    "browser.new_page",
    "context = ",
    "context.new_page",
    "p.chromium.launch",
    "p.firefox.launch",
    "p.webkit.launch",
    "async def test_",
    "import playwright",
]


def _extract_code(raw_response: str, original_code: str) -> Optional[str]:
    """Extract valid Python from Ollama's response, validate, and merge."""
    code = raw_response.strip()
    
    # Try to extract from markdown code blocks first
    code_blocks = re.findall(r"```(?:python)?\n(.*?)```", code, re.DOTALL)
    if code_blocks:
        # Use the largest code block
        code = max(code_blocks, key=len).strip()
    else:
        # Fallback if no markdown blocks
        if code.startswith("```"):
            code = re.sub(r"^```\w*\n?", "", code)
            code = re.sub(r"\n?```.*$", "", code, flags=re.DOTALL)
            code = code.strip()

    if not code:
        return None

    # Strip forbidden patterns
    for pat in _FORBIDDEN_PATTERNS:
        if pat in code:
            code = "\n".join(
                line for line in code.splitlines()
                if pat not in line
            )

    # Case 1: Ollama returned a full function — merge with preamble
    if "def test_" in code:
        if "def test_" in code and "(page" not in code:
            code = re.sub(
                r"def (test_\w+)\(\):",
                r"def \1(page: Page, base_url: str):",
                code,
            )

        original_lines = original_code.splitlines()
        test_fn_start = None
        for i, line in enumerate(original_lines):
            if line.startswith("def test_"):
                test_fn_start = i
                break

        if test_fn_start is None:
            return None

        preamble = "\n".join(original_lines[:test_fn_start])
        new_fn_start = code.find("def test_")
        if new_fn_start > 0:
            code = code[new_fn_start:]

        result = preamble + "\n" + code + "\n"
        return _validate_syntax(result)

    # Case 2: Ollama returned a snippet — splice into original at the failure point
    original_lines = original_code.splitlines()

    snippet_lines = [l.strip() for l in code.splitlines() if l.strip()]
    if not snippet_lines:
        return None

    for sl in snippet_lines:
        if "Step" in sl and "print" in sl:
            for i, ol in enumerate(original_lines):
                if sl in ol or (sl[:40] in ol and len(sl) > 20):
                    end_i = min(i + len(snippet_lines) + 5, len(original_lines))
                    patched = original_lines[:i] + code.splitlines() + original_lines[end_i:]
                    result = "\n".join(patched) + "\n"
                    return _validate_syntax(result)

    return None


def _validate_syntax(code: str) -> Optional[str]:
    """Validate that the patched code is syntactically valid Python.
    Returns the code if valid, None if it has syntax errors."""
    try:
        ast.parse(code)
        return code
    except SyntaxError as e:
        logger.warning("Auto-heal produced invalid Python (line %s): %s", e.lineno, e.msg)
        return None
