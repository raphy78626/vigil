"""
Showcase demo generator for client presentations.

Generates rich, multi-app demo data with:
  - 3 different web apps (SauceDemo, Herokuapp, TodoMVC)
  - 12+ realistic journeys with high-confidence labels
  - Pre-populated test run history (mixed pass/fail/healed)
  - Explorer session results
  - Review queue items

Usage:
    python -m testai demo-showcase         # Full showcase data
    python -m testai demo-showcase --clean  # Wipe DB first, then populate
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

from testai.storage.db import Database


def _id():
    return str(uuid.uuid4())


def _ts(base: datetime, offset_min: float = 0, offset_sec: float = 0):
    return (base + timedelta(minutes=offset_min, seconds=offset_sec)).isoformat()


# ─────────────────────────────────────────────
# Journey definitions — 3 apps, 12 journeys
# ─────────────────────────────────────────────
def _build_journeys(now: datetime):
    journeys = []

    # ═══════════════════════════════════════════
    # APP 1: SauceDemo — E-Commerce (6 journeys)
    # ═══════════════════════════════════════════
    base = "https://www.saucedemo.com"

    # J1: Login with valid credentials
    j1_id = _id()
    journeys.append({
        "journey": {
            "id": j1_id, "name": "Login with Valid Credentials",
            "domain": "Authentication", "feature": "Login",
            "confidence": 0.95, "discovered_by": "chrome-extension",
            "session_id": _id(), "tags": ["authentication", "login", "smoke"],
            "discovered_at": _ts(now, -120),
            "review_status": "approved",
        },
        "steps": [
            {"id": _id(), "order": 1, "description": "Navigate to login page", "url": f"{base}/", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 2, "description": "Type 'standard_user' into username", "url": f"{base}/", "action_type": "fill_form", "selectors": {"test_id": "username", "css": "[data-test='username']", "input_type": "text", "value": "standard_user", "placeholder": "Username"}},
            {"id": _id(), "order": 3, "description": "Type password", "url": f"{base}/", "action_type": "fill_form", "selectors": {"test_id": "password", "css": "[data-test='password']", "input_type": "password", "value": "secret_sauce", "placeholder": "Password"}},
            {"id": _id(), "order": 4, "description": "Click 'Login' button", "url": f"{base}/", "action_type": "click", "selectors": {"test_id": "login-button", "css": "[data-test='login-button']", "text": "Login", "role": "button"}},
            {"id": _id(), "order": 5, "description": "Navigate to /inventory.html", "url": f"{base}/inventory.html", "action_type": "navigate", "selectors": {}},
        ],
    })

    # ── Reusable login steps for SauceDemo (auth-gated pages) ──
    def _sauce_login_steps(base_url):
        return [
            {"id": _id(), "order": 1, "description": "Navigate to login page", "url": f"{base_url}/", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 2, "description": "Type 'standard_user' into username", "url": f"{base_url}/", "action_type": "fill_form", "selectors": {"test_id": "username", "css": "[data-test='username']", "input_type": "text", "value": "standard_user", "placeholder": "Username"}},
            {"id": _id(), "order": 3, "description": "Type password", "url": f"{base_url}/", "action_type": "fill_form", "selectors": {"test_id": "password", "css": "[data-test='password']", "input_type": "password", "value": "secret_sauce", "placeholder": "Password"}},
            {"id": _id(), "order": 4, "description": "Click 'Login' button", "url": f"{base_url}/", "action_type": "click", "selectors": {"test_id": "login-button", "css": "[data-test='login-button']", "text": "Login", "role": "button"}},
            {"id": _id(), "order": 5, "description": "Navigate to /inventory.html", "url": f"{base_url}/inventory.html", "action_type": "navigate", "selectors": {}},
        ]

    # J2: Browse products and view details
    j2_id = _id()
    j2_login = _sauce_login_steps(base)
    journeys.append({
        "journey": {
            "id": j2_id, "name": "Browse Products & View Details",
            "domain": "Commerce", "feature": "Product Catalog",
            "confidence": 0.88, "discovered_by": "chrome-extension",
            "session_id": _id(), "tags": ["commerce", "catalog", "browse"],
            "discovered_at": _ts(now, -115),
            "review_status": "approved",
        },
        "steps": j2_login + [
            {"id": _id(), "order": 6, "description": "Click 'Sauce Labs Backpack' product", "url": f"{base}/inventory.html", "action_type": "click", "selectors": {"test_id": "item-4-title-link", "css": "#item_4_title_link > div", "text": "Sauce Labs Backpack"}},
            {"id": _id(), "order": 7, "description": "Navigate to product detail page", "url": f"{base}/inventory-item.html?id=4", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 8, "description": "Click 'Add to cart' button", "url": f"{base}/inventory-item.html?id=4", "action_type": "click", "selectors": {"test_id": "add-to-cart-sauce-labs-backpack", "css": "#add-to-cart-sauce-labs-backpack", "text": "Add to cart"}},
            {"id": _id(), "order": 9, "description": "Click 'Back to products'", "url": f"{base}/inventory-item.html?id=4", "action_type": "click", "selectors": {"test_id": "back-to-products", "css": "#back-to-products", "text": "Back to products"}},
            {"id": _id(), "order": 10, "description": "Navigate back to inventory", "url": f"{base}/inventory.html", "action_type": "navigate", "selectors": {}},
        ],
    })

    # J3: Full checkout flow (happy path) — includes login + add item first
    j3_id = _id()
    j3_login = _sauce_login_steps(base)
    journeys.append({
        "journey": {
            "id": j3_id, "name": "Complete Checkout — Happy Path",
            "domain": "Commerce", "feature": "Checkout",
            "confidence": 0.92, "discovered_by": "chrome-extension",
            "session_id": _id(), "tags": ["commerce", "checkout", "regression", "critical"],
            "discovered_at": _ts(now, -110),
            "review_status": "approved",
        },
        "steps": j3_login + [
            {"id": _id(), "order": 6, "description": "Click 'Add to cart' on Sauce Labs Backpack", "url": f"{base}/inventory.html", "action_type": "click", "selectors": {"test_id": "add-to-cart-sauce-labs-backpack", "css": "#add-to-cart-sauce-labs-backpack", "text": "Add to cart"}},
            {"id": _id(), "order": 7, "description": "Click shopping cart icon", "url": f"{base}/inventory.html", "action_type": "click", "selectors": {"css": ".shopping_cart_link", "test_id": "shopping-cart-link"}},
            {"id": _id(), "order": 8, "description": "Navigate to cart", "url": f"{base}/cart.html", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 9, "description": "Click 'Checkout' button", "url": f"{base}/cart.html", "action_type": "click", "selectors": {"test_id": "checkout", "css": "#checkout", "text": "Checkout"}},
            {"id": _id(), "order": 10, "description": "Navigate to checkout info", "url": f"{base}/checkout-step-one.html", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 11, "description": "Type 'Test' into firstName", "url": f"{base}/checkout-step-one.html", "action_type": "fill_form", "selectors": {"test_id": "firstName", "css": "#first-name", "value": "Test"}},
            {"id": _id(), "order": 12, "description": "Type 'User' into lastName", "url": f"{base}/checkout-step-one.html", "action_type": "fill_form", "selectors": {"test_id": "lastName", "css": "#last-name", "value": "User"}},
            {"id": _id(), "order": 13, "description": "Type '10001' into postalCode", "url": f"{base}/checkout-step-one.html", "action_type": "fill_form", "selectors": {"test_id": "postalCode", "css": "#postal-code", "value": "10001"}},
            {"id": _id(), "order": 14, "description": "Click 'Continue'", "url": f"{base}/checkout-step-one.html", "action_type": "click", "selectors": {"test_id": "continue", "css": "#continue", "text": "Continue"}},
            {"id": _id(), "order": 15, "description": "Navigate to checkout overview", "url": f"{base}/checkout-step-two.html", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 16, "description": "Click 'Finish' to complete order", "url": f"{base}/checkout-step-two.html", "action_type": "click", "selectors": {"test_id": "finish", "css": "#finish", "text": "Finish"}},
            {"id": _id(), "order": 17, "description": "Navigate to order confirmation", "url": f"{base}/checkout-complete.html", "action_type": "navigate", "selectors": {}},
        ],
    })

    # J4: Sort products by price — includes login
    j4_id = _id()
    j4_login = _sauce_login_steps(base)
    journeys.append({
        "journey": {
            "id": j4_id, "name": "Sort Products by Price",
            "domain": "Commerce", "feature": "Product Sorting",
            "confidence": 0.82, "discovered_by": "chrome-extension",
            "session_id": _id(), "tags": ["commerce", "sort", "ux"],
            "discovered_at": _ts(now, -100),
            "review_status": "auto_approved",
        },
        "steps": j4_login + [
            {"id": _id(), "order": 6, "description": "Select 'Price (low to high)' from sort dropdown", "url": f"{base}/inventory.html", "action_type": "select", "selectors": {"test_id": "product-sort-container", "css": "[data-test='product-sort-container']", "value": "Price (low to high)"}},
            {"id": _id(), "order": 7, "description": "Select 'Price (high to low)' from sort dropdown", "url": f"{base}/inventory.html", "action_type": "select", "selectors": {"test_id": "product-sort-container", "css": "[data-test='product-sort-container']", "value": "Price (high to low)"}},
        ],
    })

    # J5: Remove item from cart — includes login + add item first
    j5_id = _id()
    j5_login = _sauce_login_steps(base)
    journeys.append({
        "journey": {
            "id": j5_id, "name": "Remove Item from Cart",
            "domain": "Commerce", "feature": "Cart",
            "confidence": 0.87, "discovered_by": "chrome-extension",
            "session_id": _id(), "tags": ["commerce", "cart", "remove"],
            "discovered_at": _ts(now, -95),
            "review_status": "approved",
        },
        "steps": j5_login + [
            {"id": _id(), "order": 6, "description": "Click 'Add to cart' on Sauce Labs Backpack", "url": f"{base}/inventory.html", "action_type": "click", "selectors": {"test_id": "add-to-cart-sauce-labs-backpack", "css": "#add-to-cart-sauce-labs-backpack", "text": "Add to cart"}},
            {"id": _id(), "order": 7, "description": "Click shopping cart icon", "url": f"{base}/inventory.html", "action_type": "click", "selectors": {"css": ".shopping_cart_link", "test_id": "shopping-cart-link"}},
            {"id": _id(), "order": 8, "description": "Navigate to cart page", "url": f"{base}/cart.html", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 9, "description": "Click 'Remove' on Backpack", "url": f"{base}/cart.html", "action_type": "click", "selectors": {"test_id": "remove-sauce-labs-backpack", "css": "#remove-sauce-labs-backpack", "text": "Remove"}},
            {"id": _id(), "order": 10, "description": "Click 'Continue Shopping'", "url": f"{base}/cart.html", "action_type": "click", "selectors": {"test_id": "continue-shopping", "css": "#continue-shopping", "text": "Continue Shopping"}},
            {"id": _id(), "order": 11, "description": "Navigate back to inventory", "url": f"{base}/inventory.html", "action_type": "navigate", "selectors": {}},
        ],
    })

    # J6: Failed login attempt
    j6_id = _id()
    journeys.append({
        "journey": {
            "id": j6_id, "name": "Failed Login — Locked Out User",
            "domain": "Authentication", "feature": "Login Error",
            "confidence": 0.90, "discovered_by": "chrome-extension",
            "session_id": _id(), "tags": ["authentication", "negative", "error-handling"],
            "discovered_at": _ts(now, -90),
            "review_status": "approved",
        },
        "steps": [
            {"id": _id(), "order": 1, "description": "Navigate to login page", "url": f"{base}/", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 2, "description": "Type 'locked_out_user' into username", "url": f"{base}/", "action_type": "fill_form", "selectors": {"test_id": "username", "css": "#user-name", "value": "locked_out_user"}},
            {"id": _id(), "order": 3, "description": "Enter password", "url": f"{base}/", "action_type": "fill_form", "selectors": {"test_id": "password", "css": "#password", "input_type": "password"}},
            {"id": _id(), "order": 4, "description": "Click 'Login' button", "url": f"{base}/", "action_type": "click", "selectors": {"test_id": "login-button", "text": "Login"}},
            {"id": _id(), "order": 5, "description": "Verify error message displayed", "url": f"{base}/", "action_type": "assert", "selectors": {"css": ".error-message-container", "text": "locked out"}},
        ],
    })

    # ═══════════════════════════════════════════
    # APP 2: Herokuapp — Classic Test App (3 journeys)
    # ═══════════════════════════════════════════
    base2 = "https://the-internet.herokuapp.com"

    # J7: Login / Logout flow
    j7_id = _id()
    journeys.append({
        "journey": {
            "id": j7_id, "name": "Login and Logout Flow",
            "domain": "Authentication", "feature": "Login",
            "confidence": 0.91, "discovered_by": "chrome-extension",
            "session_id": _id(), "tags": ["authentication", "login", "logout", "smoke"],
            "discovered_at": _ts(now, -80),
            "review_status": "approved",
        },
        "steps": [
            {"id": _id(), "order": 1, "description": "Navigate to login page", "url": f"{base2}/login", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 2, "description": "Type 'tomsmith' into username", "url": f"{base2}/login", "action_type": "fill_form", "selectors": {"css": "#username", "name": "username", "value": "tomsmith"}},
            {"id": _id(), "order": 3, "description": "Enter password", "url": f"{base2}/login", "action_type": "fill_form", "selectors": {"css": "#password", "name": "password", "input_type": "password"}},
            {"id": _id(), "order": 4, "description": "Click 'Login' button", "url": f"{base2}/login", "action_type": "click", "selectors": {"css": "button.radius[type='submit']", "text": "Login"}},
            {"id": _id(), "order": 5, "description": "Navigate to secure area", "url": f"{base2}/secure", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 6, "description": "Click 'Logout'", "url": f"{base2}/secure", "action_type": "click", "selectors": {"css": "a[href='/logout']", "text": "Logout"}},
        ],
    })

    # J8: Drag and drop
    j8_id = _id()
    journeys.append({
        "journey": {
            "id": j8_id, "name": "Drag and Drop Interaction",
            "domain": "UI Components", "feature": "Drag & Drop",
            "confidence": 0.78, "discovered_by": "ai-explorer",
            "session_id": _id(), "tags": ["ui", "drag-drop", "interaction"],
            "discovered_at": _ts(now, -70),
            "review_status": "pending_review",
        },
        "steps": [
            {"id": _id(), "order": 1, "description": "Navigate to drag-and-drop page", "url": f"{base2}/drag_and_drop", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 2, "description": "Drag column A to column B position", "url": f"{base2}/drag_and_drop", "action_type": "drag", "selectors": {"css": "#column-a", "text": "A"}},
            {"id": _id(), "order": 3, "description": "Verify columns swapped", "url": f"{base2}/drag_and_drop", "action_type": "assert", "selectors": {"css": "#column-a", "text": "B"}},
        ],
    })

    # J9: File upload
    j9_id = _id()
    journeys.append({
        "journey": {
            "id": j9_id, "name": "File Upload Test",
            "domain": "UI Components", "feature": "File Upload",
            "confidence": 0.85, "discovered_by": "ai-explorer",
            "session_id": _id(), "tags": ["ui", "upload", "file"],
            "discovered_at": _ts(now, -65),
            "review_status": "auto_approved",
        },
        "steps": [
            {"id": _id(), "order": 1, "description": "Navigate to file upload page", "url": f"{base2}/upload", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 2, "description": "Choose file to upload", "url": f"{base2}/upload", "action_type": "fill_form", "selectors": {"css": "#file-upload", "input_type": "file"}},
            {"id": _id(), "order": 3, "description": "Click 'Upload' button", "url": f"{base2}/upload", "action_type": "click", "selectors": {"css": "#file-submit", "text": "Upload"}},
            {"id": _id(), "order": 4, "description": "Verify upload success message", "url": f"{base2}/upload", "action_type": "assert", "selectors": {"css": "#uploaded-files", "text": "test-file.txt"}},
        ],
    })

    # ═══════════════════════════════════════════
    # APP 3: TodoMVC — SPA Framework (3 journeys)
    # ═══════════════════════════════════════════
    base3 = "https://demo.playwright.dev/todomvc"

    # J10: Add multiple todos
    j10_id = _id()
    journeys.append({
        "journey": {
            "id": j10_id, "name": "Add Multiple Todo Items",
            "domain": "Task Management", "feature": "Create Todo",
            "confidence": 0.93, "discovered_by": "chrome-extension",
            "session_id": _id(), "tags": ["todo", "create", "spa"],
            "discovered_at": _ts(now, -55),
            "review_status": "approved",
        },
        "steps": [
            {"id": _id(), "order": 1, "description": "Navigate to TodoMVC app", "url": f"{base3}/#/", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 2, "description": "Type 'Buy groceries' into todo input", "url": f"{base3}/#/", "action_type": "fill_form", "selectors": {"css": "input.new-todo", "placeholder": "What needs to be done?", "value": "Buy groceries"}},
            {"id": _id(), "order": 3, "description": "Press Enter to add todo", "url": f"{base3}/#/", "action_type": "submit", "selectors": {"css": "input.new-todo"}},
            {"id": _id(), "order": 4, "description": "Type 'Walk the dog' into todo input", "url": f"{base3}/#/", "action_type": "fill_form", "selectors": {"css": "input.new-todo", "value": "Walk the dog"}},
            {"id": _id(), "order": 5, "description": "Press Enter to add todo", "url": f"{base3}/#/", "action_type": "submit", "selectors": {"css": "input.new-todo"}},
            {"id": _id(), "order": 6, "description": "Type 'Read a book' into todo input", "url": f"{base3}/#/", "action_type": "fill_form", "selectors": {"css": "input.new-todo", "value": "Read a book"}},
            {"id": _id(), "order": 7, "description": "Press Enter to add todo", "url": f"{base3}/#/", "action_type": "submit", "selectors": {"css": "input.new-todo"}},
        ],
    })

    # J11: Complete and filter todos
    j11_id = _id()
    journeys.append({
        "journey": {
            "id": j11_id, "name": "Complete & Filter Todo Items",
            "domain": "Task Management", "feature": "Filter Todos",
            "confidence": 0.86, "discovered_by": "chrome-extension",
            "session_id": _id(), "tags": ["todo", "filter", "complete"],
            "discovered_at": _ts(now, -50),
            "review_status": "approved",
        },
        "steps": [
            {"id": _id(), "order": 1, "description": "Navigate to TodoMVC app", "url": f"{base3}/#/", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 2, "description": "Toggle 'Buy groceries' as completed", "url": f"{base3}/#/", "action_type": "click", "selectors": {"css": "ul.todo-list li:first-child .toggle"}},
            {"id": _id(), "order": 3, "description": "Click 'Active' filter", "url": f"{base3}/#/active", "action_type": "click", "selectors": {"css": "a[href='#/active']", "text": "Active"}},
            {"id": _id(), "order": 4, "description": "Click 'Completed' filter", "url": f"{base3}/#/completed", "action_type": "click", "selectors": {"css": "a[href='#/completed']", "text": "Completed"}},
            {"id": _id(), "order": 5, "description": "Click 'All' filter", "url": f"{base3}/#/", "action_type": "click", "selectors": {"css": "a[href='#/']", "text": "All"}},
        ],
    })

    # J12: Delete a todo
    j12_id = _id()
    journeys.append({
        "journey": {
            "id": j12_id, "name": "Delete a Todo Item",
            "domain": "Task Management", "feature": "Delete Todo",
            "confidence": 0.80, "discovered_by": "ai-explorer",
            "session_id": _id(), "tags": ["todo", "delete", "destructive"],
            "discovered_at": _ts(now, -45),
            "review_status": "pending_review",
        },
        "steps": [
            {"id": _id(), "order": 1, "description": "Navigate to TodoMVC app", "url": f"{base3}/#/", "action_type": "navigate", "selectors": {}},
            {"id": _id(), "order": 2, "description": "Hover over 'Walk the dog' todo item", "url": f"{base3}/#/", "action_type": "hover", "selectors": {"css": "ul.todo-list li:nth-child(2)"}},
            {"id": _id(), "order": 3, "description": "Click destroy button on 'Walk the dog'", "url": f"{base3}/#/", "action_type": "click", "selectors": {"css": "ul.todo-list li:nth-child(2) .destroy"}},
        ],
    })

    # Return journey IDs mapped for test run generation
    journey_ids = {
        "login_sauce": j1_id, "browse_products": j2_id, "checkout": j3_id,
        "sort_products": j4_id, "remove_cart": j5_id, "failed_login": j6_id,
        "login_herokuapp": j7_id, "drag_drop": j8_id, "file_upload": j9_id,
        "add_todos": j10_id, "filter_todos": j11_id, "delete_todo": j12_id,
    }
    return journeys, journey_ids


# ─────────────────────────────────────────────
# Test Run History — realistic pass/fail mix
# ─────────────────────────────────────────────
def _build_test_runs(journey_ids: Dict[str, str], now: datetime):
    runs = []

    # Each entry: (key, base_url, passed, steps_total, steps_passed, duration_ms, error, healed, offset_hours)
    run_defs = [
        # Recent successful runs (step counts match updated journeys with login)
        ("login_sauce", "https://www.saucedemo.com", True, 5, 5, 3200, "", False, -2),
        ("browse_products", "https://www.saucedemo.com", True, 10, 10, 6100, "", False, -2),
        ("checkout", "https://www.saucedemo.com", True, 17, 17, 12700, "", False, -1.5),
        ("add_todos", "https://demo.playwright.dev/todomvc", True, 7, 7, 2800, "", False, -1.5),
        ("filter_todos", "https://demo.playwright.dev/todomvc", True, 5, 5, 2100, "", False, -1),
        ("login_herokuapp", "https://the-internet.herokuapp.com", True, 6, 6, 5400, "", False, -1),

        # Healed runs (auto-healed by AI)
        ("sort_products", "https://www.saucedemo.com", True, 7, 7, 5800, "", True, -3),
        ("remove_cart", "https://www.saucedemo.com", True, 11, 11, 6900, "", True, -4),

        # Failed runs
        ("failed_login", "https://www.saucedemo.com", True, 5, 5, 2100, "", False, -0.5),
        ("drag_drop", "https://the-internet.herokuapp.com", False, 3, 1, 6200, "TimeoutError: locator.drag_to timed out after 15000ms", False, -5),
        ("file_upload", "https://the-internet.herokuapp.com", False, 4, 2, 4500, "FileChooser dialog not triggered — headless mode limitation", False, -6),
        ("delete_todo", "https://demo.playwright.dev/todomvc", False, 3, 2, 3100, "Element .destroy not visible — hover state required", False, -4),

        # Older runs for history depth
        ("login_sauce", "https://www.saucedemo.com", True, 5, 5, 3400, "", False, -24),
        ("checkout", "https://www.saucedemo.com", False, 17, 12, 15000, "Timeout waiting for /checkout-complete.html — network slow", False, -24),
        ("checkout", "https://www.saucedemo.com", True, 17, 17, 13200, "", True, -12),
        ("login_herokuapp", "https://the-internet.herokuapp.com", True, 6, 6, 5100, "", False, -48),
        ("add_todos", "https://demo.playwright.dev/todomvc", True, 7, 7, 2600, "", False, -36),
    ]

    for key, base_url, passed, total, passed_steps, dur, err, healed, offset_h in run_defs:
        started = now + timedelta(hours=offset_h)
        finished = started + timedelta(milliseconds=dur)
        runs.append({
            "id": _id(),
            "journey_id": journey_ids[key],
            "base_url": base_url,
            "passed": passed,
            "total_steps": total,
            "passed_steps": passed_steps,
            "duration_ms": dur,
            "exit_code": 0 if passed else 1,
            "headed": True,
            "error_message": err,
            "healed": healed,
            "heal_attempts": 2 if healed else (1 if not passed else 0),
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "console_errors": [],
            "network_failures": [],
            "api_calls": [],
        })

    return runs


# ─────────────────────────────────────────────
# Explorer session — looks like a completed run
# ─────────────────────────────────────────────
def _build_explorer_session(now: datetime):
    return {
        "id": _id(),
        "base_url": "https://www.saucedemo.com",
        "strategy": "bfs",
        "status": "completed",
        "pages_visited": 8,
        "flows_discovered": 6,
        "config_json": json.dumps({
            "max_pages": 30, "max_time_minutes": 10,
            "headed": True, "skills": ["curious_explorer", "form_specialist"],
        }),
        "results_json": json.dumps({
            "pages": ["/", "/inventory.html", "/inventory-item.html?id=4",
                      "/cart.html", "/checkout-step-one.html",
                      "/checkout-step-two.html", "/checkout-complete.html"],
            "duration_seconds": 142,
        }),
        "started_at": _ts(now, -180),
        "finished_at": _ts(now, -177, 38),
    }


# ─────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────
def run_showcase(clean: bool = False, db_path: str | None = None):
    """Generate and insert all showcase demo data."""
    print(f"\n{'='*60}")
    print("  Vigil — Showcase Demo Generator")
    print(f"{'='*60}\n")

    db = Database(Path(db_path)) if db_path else Database()
    db.connect()

    if clean:
        print("[0/5] Cleaning existing data...")
        for table in ["test_runs", "steps", "journeys", "events",
                      "explorer_sessions", "review_actions", "label_corrections",
                      "journey_versions", "flaky_tests"]:
            try:
                db.conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass
        db.conn.commit()
        print("       Done — fresh start.\n")

    now = datetime.now()

    # 1. Build journeys
    print("[1/5] Generating 12 journeys across 3 apps...")
    journey_defs, journey_ids = _build_journeys(now)

    for jdef in journey_defs:
        j = jdef["journey"]
        db.conn.execute(
            """INSERT OR REPLACE INTO journeys
            (id, name, domain, feature, confidence, discovered_at,
             discovered_by, session_id, tags, review_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (j["id"], j["name"], j["domain"], j["feature"],
             j["confidence"], j["discovered_at"], j["discovered_by"],
             j["session_id"], json.dumps(j["tags"]), j.get("review_status", "pending_review")),
        )
        for s in jdef["steps"]:
            db.conn.execute(
                """INSERT OR REPLACE INTO steps
                (id, journey_id, step_order, description, url,
                 action_type, element_hint, selectors, event_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (s["id"], j["id"], s["order"], s["description"],
                 s["url"], s["action_type"], s["description"],
                 json.dumps(s["selectors"]), json.dumps([])),
            )
    db.conn.commit()

    apps = set()
    for jdef in journey_defs:
        for s in jdef["steps"]:
            from urllib.parse import urlparse
            host = urlparse(s["url"]).netloc
            if host:
                apps.add(host)
    print(f"       Apps: {', '.join(sorted(apps))}")
    print(f"       Domains: {', '.join(sorted(set(j['journey']['domain'] for j in journey_defs)))}")

    # 2. Build test runs
    print("\n[2/5] Generating 17 test run history entries...")
    test_runs = _build_test_runs(journey_ids, now)
    for run in test_runs:
        db.insert_test_run(run)
    passed = sum(1 for r in test_runs if r["passed"])
    healed = sum(1 for r in test_runs if r["healed"])
    print(f"       {passed} passed, {len(test_runs) - passed} failed, {healed} auto-healed")

    # 3. Build explorer session
    print("\n[3/5] Generating AI Explorer session...")
    explorer = _build_explorer_session(now)
    db.conn.execute(
        """INSERT OR REPLACE INTO explorer_sessions
        (id, base_url, strategy, status, pages_visited, flows_discovered,
         config_json, results_json, started_at, finished_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (explorer["id"], explorer["base_url"], explorer["strategy"],
         explorer["status"], explorer["pages_visited"], explorer["flows_discovered"],
         explorer["config_json"], explorer["results_json"],
         explorer["started_at"], explorer["finished_at"]),
    )
    db.conn.commit()
    print(f"       Explored {explorer['pages_visited']} pages, found {explorer['flows_discovered']} flows")

    # 4. Build review queue actions
    print("\n[4/5] Populating review queue...")
    approved_count = 0
    pending_count = 0
    for jdef in journey_defs:
        j = jdef["journey"]
        if j.get("review_status") == "approved":
            approved_count += 1
            db.conn.execute(
                """INSERT OR REPLACE INTO review_actions
                (id, journey_id, action, reviewer, note)
                VALUES (?, ?, 'approve', 'demo-reviewer', 'Verified during QA session')""",
                (_id(), j["id"]),
            )
        elif j.get("review_status") == "pending_review":
            pending_count += 1
    db.conn.commit()
    print(f"       {approved_count} approved, {pending_count} pending review")

    # 5. Summary
    print(f"\n[5/5] Database: {db.db_path}")

    db.close()

    print(f"\n{'='*60}")
    print("  SHOWCASE READY!")
    print(f"{'='*60}")
    print(f"""
  3 web apps:
    - SauceDemo (e-commerce)       6 journeys
    - Herokuapp (classic tests)    3 journeys
    - TodoMVC (SPA framework)      3 journeys

  17 test runs  |  {passed} passed  |  {healed} auto-healed
  1 AI Explorer session (8 pages crawled)
  {approved_count} review-approved  |  {pending_count} pending human review

  Start the server:
    python -m testai server

  Then open: http://localhost:8000
""")
    print(f"{'='*60}\n")
