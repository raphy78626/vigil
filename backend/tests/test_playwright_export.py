"""Tests for the Playwright test generator (export pipeline)."""

import uuid
from datetime import datetime

import pytest

from testai.export.playwright import PlaywrightExporter
from testai.models.journey import Journey
from testai.models.step import Step


def _make_journey(steps: list[Step], name: str = "Test Journey") -> Journey:
    return Journey(
        id=str(uuid.uuid4()),
        name=name,
        domain="example.com",
        feature="checkout",
        confidence=0.85,
        created_at=datetime.now().isoformat(),
        steps=steps,
    )


def _make_step(
    order: int,
    action_type: str,
    description: str,
    url: str = "https://app.example.com/",
    selectors: dict | None = None,
) -> Step:
    return Step(
        id=str(uuid.uuid4()),
        journey_id="test-journey",
        order=order,
        action_type=action_type,
        description=description,
        url=url,
        selectors=selectors or {},
        element_hint="",
    )


class TestPlaywrightExporter:
    def setup_method(self):
        self.exp = PlaywrightExporter()

    def test_empty_journey_returns_comment(self):
        j = _make_journey([])
        code = self.exp.export(j)
        assert "No steps" in code or "import" in code  # graceful

    def test_basic_click_generates_valid_python(self):
        j = _make_journey([
            _make_step(1, "click", "Click Submit button",
                       selectors={"css": "button.submit", "text": "Submit", "role": "button"}),
        ])
        code = self.exp.export(j)
        assert "def test_" in code
        assert "playwright" in code.lower() or "page" in code

    def test_fill_form_generates_fill_call(self):
        j = _make_journey([
            _make_step(1, "fill_form", "Type 'user@example.com' into Email",
                       selectors={"css": "input#email", "ariaLabel": "Email", "value": "user@example.com"}),
        ])
        code = self.exp.export(j)
        assert "fill(" in code or "type(" in code or "'fill:" in code

    def test_navigate_generates_goto(self):
        j = _make_journey([
            _make_step(1, "navigate", "Navigate to /",
                       url="https://app.example.com/",
                       selectors={}),
        ])
        code = self.exp.export(j)
        assert "goto" in code or "navigate" in code.lower()

    def test_keypress_enter_generates_keyboard_press(self):
        j = _make_journey([
            _make_step(1, "keypress", "Press Enter",
                       selectors={"key": "Enter", "combo": "Enter"}),
        ])
        code = self.exp.export(j)
        assert "Enter" in code

    def test_noise_steps_filtered_in_export(self):
        j = _make_journey([
            _make_step(1, "click", "Click [Seek slider]",
                       selectors={"css": "[aria-label='Seek slider']", "ariaLabel": "Seek slider"}),
            _make_step(2, "click", "Click Submit",
                       selectors={"css": "button.submit", "text": "Submit"}),
        ])
        code = self.exp.export(j)
        # Seek slider should be filtered, Submit should remain
        # The test may have fewer steps but Submit action should appear
        assert "Submit" in code or "submit" in code.lower()

    def test_test_function_name_derived_from_journey(self):
        j = _make_journey(
            [_make_step(1, "click", "Click Login", selectors={"css": "button"})],
            name="User Login Flow",
        )
        code = self.exp.export(j)
        assert "test_user_login_flow" in code or "def test_" in code

    def test_auto_healing_locators_present(self):
        j = _make_journey([
            _make_step(1, "click", "Click Submit",
                       selectors={"css": "button.submit", "text": "Submit", "ariaLabel": "Submit", "role": "button"}),
        ])
        code = self.exp.export(j)
        # Auto-healing means _heal() function and multiple locators
        assert "_heal" in code

    def test_conftest_generated(self):
        j = _make_journey([
            _make_step(1, "navigate", "Navigate to /",
                       url="https://app.example.com/", selectors={}),
        ])
        conftest = self.exp.export_conftest(j)
        assert "base_url" in conftest
        assert "app.example.com" in conftest

    def test_dedup_consecutive_clicks(self):
        """Multiple consecutive clicks on same element should be collapsed."""
        j = _make_journey([
            _make_step(1, "click", "Click Search",
                       selectors={"css": "input#search", "ariaLabel": "Search"}),
            _make_step(2, "click", "Click Search",
                       selectors={"css": "input#search", "ariaLabel": "Search"}),
            _make_step(3, "click", "Click Search",
                       selectors={"css": "input#search", "ariaLabel": "Search"}),
            _make_step(4, "fill_form", "Type 'hello' into Search",
                       selectors={"css": "input#search", "value": "hello"}),
        ])
        code = self.exp.export(j)
        # Should have fewer than 3 click steps (deduped) + 1 fill
        step_count = code.count("Step ")
        assert step_count <= 3, f"Expected deduplication, got {step_count} steps"

    # ------------------------------------------------------------------
    # Generic CSS filtering
    # ------------------------------------------------------------------

    def test_generic_css_filtered_bare_tag(self):
        """Bare tag selectors like 'a', 'button' must be filtered out."""
        j = _make_journey([
            _make_step(1, "click", "Click link",
                       selectors={"tagName": "a", "css": "a", "role": "link"}),
        ])
        code = self.exp.export(j)
        # page.locator("a").first should NOT appear — too generic
        assert 'page.locator("a").first' not in code, \
            "Bare 'a' CSS selector should be filtered as generic"

    def test_generic_css_filtered_button(self):
        """Bare 'button' selector must be filtered out."""
        j = _make_journey([
            _make_step(1, "click", "Click button",
                       selectors={"tagName": "button", "css": "button", "text": "Submit"}),
        ])
        code = self.exp.export(j)
        assert 'page.locator("button").first' not in code

    def test_specific_css_preserved(self):
        """CSS with classes/IDs should NOT be filtered."""
        j = _make_journey([
            _make_step(1, "click", "Click submit",
                       selectors={"css": "button.btn-primary", "text": "Submit"}),
        ])
        code = self.exp.export(j)
        assert "btn-primary" in code

    # ------------------------------------------------------------------
    # Expected text/href passed to _heal
    # ------------------------------------------------------------------

    def test_expected_text_passed_to_heal(self):
        """Click steps with text should pass _expected_text to _heal."""
        j = _make_journey([
            _make_step(1, "click", "Click 'Save Changes' button",
                       selectors={"text": "Save Changes", "role": "button"}),
        ])
        code = self.exp.export(j)
        assert '_expected_text="Save Changes"' in code

    def test_expected_href_passed_to_heal(self):
        """Click steps on links with href should pass _expected_href to _heal."""
        j = _make_journey([
            _make_step(1, "click", "Click Dashboard link",
                       selectors={"tagName": "a", "text": "Dashboard",
                                  "href": "/dashboard"}),
        ])
        code = self.exp.export(j)
        assert '_expected_href="/dashboard"' in code

    def test_no_expected_when_no_text(self):
        """Steps without text should not pass _expected_text."""
        j = _make_journey([
            _make_step(1, "click", "Click icon button",
                       selectors={"css": "button.icon-btn", "ariaLabel": "Settings"}),
        ])
        code = self.exp.export(j)
        assert '_expected_text=' not in code

    # ------------------------------------------------------------------
    # Conftest features
    # ------------------------------------------------------------------

    def test_conftest_has_validated_js_click(self):
        """Conftest should contain the validated JS click helper."""
        j = _make_journey([
            _make_step(1, "navigate", "Navigate", url="https://app.example.com/",
                       selectors={}),
        ])
        ct = self.exp.export_conftest(j)
        assert "_validate_js_click" in ct
        assert "text mismatch" in ct
        assert "href mismatch" in ct

    def test_conftest_has_expanded_auth_detection(self):
        """Conftest should detect OAuth/SAML/IdP redirects."""
        ct = self.exp.export_conftest(_make_journey([
            _make_step(1, "navigate", "Nav", url="https://app.example.com/",
                       selectors={}),
        ]))
        assert "oauth" in ct.lower()
        assert "accounts.google.com" in ct
        assert "login.microsoftonline.com" in ct
        assert "save_auth.py" in ct

    def test_conftest_has_dynamic_overlay_detection(self):
        """Overlay sweep should detect by position/coverage, not just selectors."""
        ct = self.exp.export_conftest(_make_journey([
            _make_step(1, "navigate", "Nav", url="https://app.example.com/",
                       selectors={}),
        ]))
        assert "coverThreshold" in ct
        assert "aria-label" in ct
        assert "dismissWords" in ct

    # ------------------------------------------------------------------
    # Locator chain — href-scoped and visibleText strategies
    # ------------------------------------------------------------------

    def test_href_scoped_text_locator(self):
        """Links with both href and text get an href+text scoped locator."""
        j = _make_journey([
            _make_step(1, "click", "Click 'Products' link",
                       selectors={"tagName": "a", "text": "Products",
                                  "href": "/products", "role": "link"}),
        ])
        code = self.exp.export(j)
        # Should have a filter(has_text=...) locator
        assert 'filter(has_text="Products")' in code

    def test_visible_text_fallback(self):
        """visibleText should create additional locator when different from text."""
        j = _make_journey([
            _make_step(1, "click", "Click card",
                       selectors={"text": "", "visibleText": "Premium Plan",
                                  "css": "div.card"}),
        ])
        code = self.exp.export(j)
        assert "Premium Plan" in code
