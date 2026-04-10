"""QA Skills — persona-driven exploration strategies for the AI Explorer.

Each skill gives the LLM a specific QA mindset: what to look for,
what to try, and what curiosity heuristics to follow.  Skills are
composable — the explorer can use several at once to produce a rich
system prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class QASkill:
    id: str
    name: str
    icon: str
    description: str
    system_directive: str
    curiosity_rules: List[str]
    fill_overrides: Dict[str, str] = field(default_factory=dict)
    priority_elements: List[str] = field(default_factory=list)
    avoid_elements: List[str] = field(default_factory=list)


SKILL_REGISTRY: Dict[str, QASkill] = {}


def _register(skill: QASkill) -> QASkill:
    SKILL_REGISTRY[skill.id] = skill
    return skill


# ── Core exploration skills ───────────────────────────────────────

CURIOUS_EXPLORER = _register(QASkill(
    id="curious_explorer",
    name="Curious Explorer",
    icon="🔍",
    description="Deep curiosity — clicks everything, opens every dropdown, expands every accordion. Maximises page and feature coverage.",
    system_directive=(
        "You are an insatiably curious QA engineer. Your instinct is to "
        "poke every interactive element you haven't tried yet. You open "
        "dropdowns, expand accordions, toggle switches, open modals, hover "
        "menus, and scroll to the bottom of every page looking for hidden "
        "content. If a page has tabs, you click every tab. If there's a "
        "'show more' link, you click it. Nothing escapes your attention."
    ),
    curiosity_rules=[
        "Click every tab, accordion, and expandable section you find",
        "Open every dropdown and menu item, even if they look decorative",
        "Scroll to the bottom of the page to discover lazy-loaded content",
        "Hover over elements that might reveal tooltips or sub-menus",
        "If you see a 'Show more', 'Load more', or '...' — click it",
        "Prefer unexplored areas of the page over already-seen ones",
        "Try toggling every switch and checkbox to observe state changes",
    ],
    priority_elements=["details", "summary", "accordion", "tab", "dropdown", "modal", "toggle"],
))

EDGE_CASE_HUNTER = _register(QASkill(
    id="edge_case_hunter",
    name="Edge Case Hunter",
    icon="🎯",
    description="Deliberately tries boundary values, empty inputs, special characters, and unusual sequences to find bugs.",
    system_directive=(
        "You are a meticulous QA engineer who specialises in edge cases and "
        "boundary testing. When you see a form, you don't just fill it with "
        "happy-path data — you try empty submissions, max-length strings, "
        "special characters, negative numbers, and boundary values. You test "
        "what happens when you submit a form twice quickly, use the back button "
        "after a submission, or navigate away mid-flow. Your goal is to break "
        "things gracefully."
    ),
    curiosity_rules=[
        "Try submitting forms with empty required fields to check validation",
        "Enter very long strings (200+ chars) to test overflow handling",
        "Use special characters: <script>alert(1)</script>, ' OR 1=1 --, null",
        "Enter negative numbers, zero, and very large numbers in numeric fields",
        "Try email fields with invalid formats: 'notanemail', '@missing', 'a@b'",
        "Submit the same form multiple times rapidly",
        "Navigate back after a successful submission to check re-submit behaviour",
        "Try pasting content instead of typing where possible",
    ],
    fill_overrides={
        "email": "not-an-email",
        "number": "-1",
        "password": "",
        "text": "<script>alert('xss')</script>",
        "tel": "abc",
        "url": "not-a-url",
        "search": "' OR 1=1 --",
    },
))

FORM_SPECIALIST = _register(QASkill(
    id="form_specialist",
    name="Form Specialist",
    icon="📋",
    description="Deep expertise in form testing — fills every field, tests validation, tries all input combinations.",
    system_directive=(
        "You are a QA engineer who specialises in form testing. You methodically "
        "fill every field in a form before submitting. You test required field "
        "validation by clearing fields. You try different combinations of form "
        "inputs. You check that error messages appear when expected and disappear "
        "when corrected. After a successful submission you check for confirmation "
        "messages and verify the data was accepted."
    ),
    curiosity_rules=[
        "Always fill ALL fields in a form before clicking submit",
        "After submitting, check for success/error messages on the page",
        "Try clearing a required field and submitting to test validation",
        "Check that inline validation appears as you type",
        "Test both valid and invalid data in the same form",
        "Look for hidden form fields or conditionally-visible sections",
        "After a successful submission, go back and check if the form was reset",
        "Test auto-complete and suggested values in input fields",
    ],
    priority_elements=["input", "textarea", "select", "form", "button[type=submit]"],
))

NAVIGATION_MAPPER = _register(QASkill(
    id="navigation_mapper",
    name="Navigation Mapper",
    icon="🗺️",
    description="Systematic page-by-page exploration — builds a complete sitemap by following every link and menu item.",
    system_directive=(
        "You are a QA engineer whose mission is to visit every reachable page "
        "in the application. You systematically click through navigation menus, "
        "breadcrumbs, sidebar links, footer links, and any in-page links. You "
        "explore every route and sub-route. You check that the back button works "
        "correctly. You look for orphan pages that aren't linked from the main nav."
    ),
    curiosity_rules=[
        "Prioritise navigation links, sidebar items, and menu entries",
        "Visit every link in the header and footer navigation",
        "Follow breadcrumbs to verify the navigation hierarchy",
        "Click logo or home links to verify they navigate correctly",
        "Check that the browser back button works after each navigation",
        "Look for pagination and visit multiple pages of results",
        "Explore sub-menus and nested navigation structures",
        "Check for 404 pages by noting any broken links",
    ],
    priority_elements=["nav a", "header a", "footer a", "sidebar a", "breadcrumb a"],
    avoid_elements=["input", "textarea"],
))

ACCESSIBILITY_AUDITOR = _register(QASkill(
    id="accessibility_auditor",
    name="Accessibility Auditor",
    icon="♿",
    description="Tests keyboard navigation, screen reader compatibility, focus management, and ARIA attribute correctness.",
    system_directive=(
        "You are an accessibility-focused QA engineer. You test that every "
        "interactive element can be reached via keyboard Tab navigation. You "
        "check that ARIA labels are present and meaningful. You verify focus "
        "management in modals and dialogs. You test that colour contrast is "
        "sufficient and that images have alt text. You check that form fields "
        "have associated labels."
    ),
    curiosity_rules=[
        "Check that buttons and links have descriptive text or ARIA labels",
        "Verify that modals trap focus and return it when closed",
        "Look for images without alt text",
        "Test that form fields have <label> elements or aria-label",
        "Check that error messages are associated with their fields via aria-describedby",
        "Verify that interactive elements have visible focus indicators",
        "Test that skip-to-content links exist on content-heavy pages",
        "Check heading hierarchy (h1, h2, h3) for logical structure",
    ],
    priority_elements=["[role]", "[aria-label]", "[aria-describedby]", "img", "label"],
))

ERROR_RECOVERY_TESTER = _register(QASkill(
    id="error_recovery",
    name="Error Recovery Tester",
    icon="🔄",
    description="Deliberately causes errors and tests how the app recovers — offline states, timeouts, interrupted flows.",
    system_directive=(
        "You are a QA engineer who tests error handling and recovery paths. "
        "You submit invalid data to trigger error states. You interrupt multi-step "
        "flows mid-way. You try accessing pages that require authentication without "
        "logging in. You test what happens after a failed action — can the user "
        "retry? Is there a helpful error message? Does the app recover gracefully?"
    ),
    curiosity_rules=[
        "Submit forms with intentionally invalid data to trigger error states",
        "Interrupt a multi-step wizard mid-flow by navigating away",
        "After an error, try correcting the input and resubmitting",
        "Check that error messages are clear and actionable",
        "Test the 'cancel' or 'close' button on every dialog and modal",
        "Try accessing a protected page directly via URL",
        "After a failure, verify the app returns to a usable state",
        "Test retry logic — submit a failing action multiple times",
    ],
))

SECURITY_PROBER = _register(QASkill(
    id="security_prober",
    name="Security Prober",
    icon="🔒",
    description="Basic security testing — checks for XSS vectors, open redirects, exposed sensitive data, and IDOR patterns.",
    system_directive=(
        "You are a security-minded QA engineer performing basic security checks. "
        "You look for reflected user input (potential XSS). You check for exposed "
        "tokens or sensitive data in URLs. You test for open redirects. You verify "
        "that authentication is enforced on protected pages. You look for IDOR "
        "patterns by modifying URL IDs. You do NOT perform destructive attacks."
    ),
    curiosity_rules=[
        "Enter <script>alert(1)</script> in text fields to test for XSS reflection",
        "Check URL parameters for sensitive data (tokens, emails, passwords)",
        "Test for open redirects by modifying redirect URLs if visible",
        "Check if incrementing IDs in URLs exposes other users' data",
        "Verify that logout actually invalidates the session",
        "Look for hidden form fields that contain sensitive information",
        "Check that password fields mask input and don't autocomplete",
        "Verify HTTPS is used for all sensitive operations",
    ],
    fill_overrides={
        "text": "<img src=x onerror=alert(1)>",
        "search": "' OR '1'='1",
        "url": "javascript:alert(1)",
    },
))

MOBILE_RESPONSIVE_TESTER = _register(QASkill(
    id="mobile_responsive",
    name="Mobile & Responsive",
    icon="📱",
    description="Tests responsive behaviour — checks that layouts adapt, touch targets are adequate, and nothing overflows.",
    system_directive=(
        "You are a QA engineer testing responsive behaviour. You look for "
        "elements that overflow their containers, text that gets cut off, "
        "buttons that are too small to tap, and navigation that doesn't adapt "
        "to narrow viewports. You check that hamburger menus work, that modals "
        "are scrollable, and that forms are usable on small screens."
    ),
    curiosity_rules=[
        "Look for horizontal scrollbars which indicate overflow issues",
        "Check that navigation collapses into a hamburger menu on small screens",
        "Verify touch targets are at least 44x44px for mobile usability",
        "Check that text doesn't overflow or get clipped in containers",
        "Test that modals and dialogs are scrollable if they exceed viewport height",
        "Verify images and media scale down appropriately",
        "Check that forms are usable with a single column layout",
        "Test that hover-dependent features have touch alternatives",
    ],
))

WORKFLOW_COMPLETIONIST = _register(QASkill(
    id="workflow_completionist",
    name="Workflow Completionist",
    icon="✅",
    description="Finishes every multi-step flow from start to end — never abandons a checkout, signup, or wizard mid-way.",
    system_directive=(
        "You are a QA engineer who never abandons a flow mid-way. If you start "
        "a checkout process, you complete it. If you begin filling a multi-step "
        "form, you go through every step. If there's a wizard, you finish all "
        "pages. You verify the end state — the confirmation screen, the success "
        "message, the dashboard update. You treat incomplete flows as a failure "
        "to explore."
    ),
    curiosity_rules=[
        "Once you start a multi-step process, complete EVERY step",
        "Don't navigate away from a form until you've submitted it",
        "After a successful flow, verify the confirmation page or message",
        "Check that completed actions are reflected elsewhere (e.g. cart count updates)",
        "Return to the starting point after completing a flow to ensure consistency",
        "Test the complete happy path before trying variations",
        "If a flow branches (e.g. guest vs. registered checkout), explore both paths",
        "Document the expected end state for each completed flow",
    ],
))

PERFORMANCE_OBSERVER = _register(QASkill(
    id="performance_observer",
    name="Performance Observer",
    icon="⚡",
    description="Notes slow page loads, unresponsive interactions, and jank — flags performance issues alongside functional ones.",
    system_directive=(
        "You are a QA engineer with a keen eye for performance. You notice when "
        "pages take too long to load, when clicks have delayed responses, when "
        "scrolling stutters, and when images load slowly. You test pages with lots "
        "of content to stress lazy loading. You check that loading spinners appear "
        "for async operations. You note any freezes or unresponsive moments."
    ),
    curiosity_rules=[
        "Note any page that takes more than 3 seconds to become interactive",
        "Check that loading indicators appear for asynchronous operations",
        "Scroll through long lists to test virtual/lazy loading performance",
        "Click actions rapidly to check for debouncing and rate limiting",
        "Test pages with lots of images to verify lazy loading",
        "Check that animations are smooth and don't cause jank",
        "Verify that search/filter results appear within a reasonable time",
        "Test the app with multiple tabs open to check resource consumption",
    ],
))

DATA_INTEGRITY_CHECKER = _register(QASkill(
    id="data_integrity",
    name="Data Integrity Checker",
    icon="🔢",
    description="Verifies that data entered matches data displayed — checks CRUD operations round-trip correctly.",
    system_directive=(
        "You are a QA engineer focused on data integrity. When you create an "
        "item, you verify it appears in listings. When you edit data, you confirm "
        "the changes persist. When you delete, you verify removal. You check that "
        "sorting and filtering produce correct results. You compare data between "
        "different views of the same information."
    ),
    curiosity_rules=[
        "After creating an item, navigate to the list view and verify it appears",
        "After editing, reload the page and confirm changes persisted",
        "Check that sort order is correct (alphabetical, date, numeric)",
        "Filter results and verify only matching items are shown",
        "Test pagination — verify total counts match visible items",
        "Compare the same data shown in different views (list vs. detail vs. dashboard)",
        "Create items with special characters and verify they display correctly",
        "Test search functionality with exact, partial, and no-result queries",
    ],
))

FLOW_EXPANDER = _register(QASkill(
    id="flow_expander",
    name="Flow Expander",
    icon="🌿",
    description="Given a known user flow, discovers related flows — alternative paths, edge cases, error states, and sibling features on the same pages.",
    system_directive=(
        "You are a QA engineer who has ALREADY SEEN a specific user flow on this app. "
        "Your mission is to discover RELATED flows that the original user did NOT try. "
        "Focus on: alternative paths from the same pages, opposite actions (delete vs create, "
        "cancel vs confirm), edge cases (empty input, boundary values), error recovery paths, "
        "sibling navigation items the user skipped, and variations of the same workflow "
        "(different options, different data). Stay on pages the seed flow touched or their "
        "immediate neighbors — do NOT wander to unrelated parts of the app."
    ),
    curiosity_rules=[
        "If the seed flow created something, try deleting or editing it",
        "If the seed flow filled a form, try submitting it empty or with invalid data",
        "If the seed flow clicked one menu item, try every OTHER menu item on that page",
        "If the seed flow selected one option, try every other option in the same dropdown",
        "If the seed flow completed a multi-step process, try cancelling at each step",
        "Look for undo/revert actions related to what the seed flow did",
        "Try the same flow but with different input data",
        "Check what happens if you go back/refresh mid-flow",
    ],
    priority_elements=["button", "a", "select", "input", "[role=menuitem]", "[role=tab]"],
))


# ── Preset bundles ────────────────────────────────────────────────

SKILL_BUNDLES: Dict[str, List[str]] = {
    "quick_scan": [
        "curious_explorer",
        "navigation_mapper",
    ],
    "deep_qa": [
        "curious_explorer",
        "edge_case_hunter",
        "form_specialist",
        "workflow_completionist",
    ],
    "security_focused": [
        "security_prober",
        "edge_case_hunter",
        "error_recovery",
    ],
    "accessibility_audit": [
        "accessibility_auditor",
        "navigation_mapper",
        "mobile_responsive",
    ],
    "full_regression": [
        "curious_explorer",
        "edge_case_hunter",
        "form_specialist",
        "navigation_mapper",
        "workflow_completionist",
        "error_recovery",
        "data_integrity",
    ],
    "seed_expansion": [
        "flow_expander",
        "edge_case_hunter",
        "workflow_completionist",
    ],
}


# ── Prompt builder ────────────────────────────────────────────────

def build_skill_prompt(skill_ids: List[str]) -> str:
    """Compose a unified system prompt from one or more QA skills.

    Returns a combined system directive with all curiosity rules
    merged and de-duplicated.
    """
    skills = [SKILL_REGISTRY[sid] for sid in skill_ids if sid in SKILL_REGISTRY]
    if not skills:
        return ""

    parts: List[str] = []
    parts.append("You are an expert QA engineer with the following specialities:\n")

    for sk in skills:
        parts.append(f"**{sk.name}** — {sk.system_directive}\n")

    all_rules: List[str] = []
    seen: set = set()
    for sk in skills:
        for rule in sk.curiosity_rules:
            key = rule.lower().strip()
            if key not in seen:
                seen.add(key)
                all_rules.append(rule)

    if all_rules:
        parts.append("\nQA Curiosity Rules (follow ALL of these):")
        for i, rule in enumerate(all_rules, 1):
            parts.append(f"  {i}. {rule}")

    parts.append("\nIMPORTANT: Return ONLY valid JSON. No markdown, no explanation.")
    return "\n".join(parts)


def get_fill_overrides(skill_ids: List[str]) -> Dict[str, str]:
    """Merge fill_overrides from all active skills.

    Later skills override earlier ones if they share a key.
    """
    merged: Dict[str, str] = {}
    for sid in skill_ids:
        sk = SKILL_REGISTRY.get(sid)
        if sk and sk.fill_overrides:
            merged.update(sk.fill_overrides)
    return merged


def get_priority_elements(skill_ids: List[str]) -> List[str]:
    """Merge priority_elements from all active skills, de-duplicated."""
    seen: set = set()
    result: List[str] = []
    for sid in skill_ids:
        sk = SKILL_REGISTRY.get(sid)
        if sk:
            for el in sk.priority_elements:
                if el not in seen:
                    seen.add(el)
                    result.append(el)
    return result


def list_skills() -> List[dict]:
    """Return all registered skills for the dashboard UI."""
    return [
        {
            "id": sk.id,
            "name": sk.name,
            "icon": sk.icon,
            "description": sk.description,
            "curiosity_rules": sk.curiosity_rules,
        }
        for sk in SKILL_REGISTRY.values()
    ]


def list_bundles() -> Dict[str, List[str]]:
    """Return all preset bundles."""
    return SKILL_BUNDLES
