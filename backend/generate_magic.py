"""
Generate a rich, realistic multi-session QA dataset for Vigil demo.
Simulates a real QA engineer doing exploratory testing on an e-commerce app.
"""

import json
import uuid
import time
from datetime import datetime, timedelta

BASE_URL = "https://www.saucedemo.com"
NOW = time.time() * 1000  # ms

def ts(offset_seconds=0):
    return int(NOW + offset_seconds * 1000)

def nav(from_path, to_path, session_id, t, trigger="click"):
    return {
        "type": "navigation",
        "url": BASE_URL + to_path,
        "pageTitle": path_title(to_path),
        "navigation": {"fromUrl": BASE_URL + from_path, "toUrl": BASE_URL + to_path, "trigger": trigger},
        "id": str(uuid.uuid4()),
        "timestamp": ts(t),
        "sessionId": session_id,
        "tabId": 1,
    }

def pageload(path, session_id, t):
    return {
        "type": "pageload",
        "url": BASE_URL + path,
        "pageTitle": path_title(path),
        "navigation": {"fromUrl": "", "toUrl": BASE_URL + path, "trigger": "pageload"},
        "id": str(uuid.uuid4()),
        "timestamp": ts(t),
        "sessionId": session_id,
        "tabId": 1,
    }

def click(path, text, tag, test_id, session_id, t, css=None):
    return {
        "type": "click",
        "url": BASE_URL + path,
        "pageTitle": path_title(path),
        "element": {
            "tagName": tag,
            "selectors": {
                "css": css or (f"[data-test='{test_id}']" if test_id else tag),
                "text": text,
                "ariaLabel": None,
                "testId": test_id,
                "testIdAttr": "data-test" if test_id else None,
            },
            "inputType": None,
            "value": None,
        },
        "id": str(uuid.uuid4()),
        "timestamp": ts(t),
        "sessionId": session_id,
        "tabId": 1,
    }

def inp(path, field_name, value, input_type, session_id, t):
    # saucedemo.com uses data-test="fieldName" attributes
    is_pw = input_type == "password"
    return {
        "type": "input",
        "url": BASE_URL + path,
        "pageTitle": path_title(path),
        "element": {
            "tagName": "input",
            "selectors": {
                "css": f"[data-test='{field_name}']",
                "text": None,
                "ariaLabel": None,
                "testId": field_name,
                "testIdAttr": "data-test",
                "name": field_name,
                "placeholder": field_name.capitalize(),
            },
            "inputType": input_type,
            "value": "[REDACTED]" if is_pw else value,
        },
        "id": str(uuid.uuid4()),
        "timestamp": ts(t),
        "sessionId": session_id,
        "tabId": 1,
    }

def submit(path, session_id, t):
    return {
        "type": "submit",
        "url": BASE_URL + path,
        "pageTitle": path_title(path),
        "element": {"tagName": "form", "selectors": {"css": "form", "text": None, "ariaLabel": None, "testId": None}},
        "id": str(uuid.uuid4()),
        "timestamp": ts(t),
        "sessionId": session_id,
        "tabId": 1,
    }

def path_title(path):
    titles = {
        "/": "Swag Labs",
        "/inventory.html": "Swag Labs — Products",
        "/inventory-item.html": "Swag Labs — Product Detail",
        "/cart.html": "Swag Labs — Cart",
        "/checkout-step-one.html": "Swag Labs — Checkout: Info",
        "/checkout-step-two.html": "Swag Labs — Checkout: Overview",
        "/checkout-complete.html": "Swag Labs — Order Complete",
        "/login": "Swag Labs — Login",
    }
    return titles.get(path, "Swag Labs")


def build_events():
    events = []

    # ─────────────────────────────────────────────
    # SESSION 1: Happy path — full purchase flow
    # ─────────────────────────────────────────────
    s1 = str(uuid.uuid4())
    t = 0
    events += [
        pageload("/", s1, t),
        inp("/", "username", "standard_user", "text", s1, t+2),
        inp("/", "password", "", "password", s1, t+4),
        click("/", "Login", "input", "login-button", s1, t+6),
        nav("/", "/inventory.html", s1, t+7),

        pageload("/inventory.html", s1, t+8),
        click("/inventory.html", "Sauce Labs Backpack", "div", "inventory-item-name", s1, t+12),
        nav("/inventory.html", "/inventory-item.html", s1, t+13),

        pageload("/inventory-item.html", s1, t+14),
        click("/inventory-item.html", "Add to cart", "button", "add-to-cart", s1, t+18),
        click("/inventory-item.html", "Back to products", "button", "back-to-products", s1, t+22),
        nav("/inventory-item.html", "/inventory.html", s1, t+23),

        pageload("/inventory.html", s1, t+24),
        click("/inventory.html", "Sauce Labs Bike Light", "div", "inventory-item-name", s1, t+28),
        nav("/inventory.html", "/inventory-item.html", s1, t+29),

        pageload("/inventory-item.html", s1, t+30),
        click("/inventory-item.html", "Add to cart", "button", "add-to-cart", s1, t+34),
        click("/inventory-item.html", "Back to products", "button", "back-to-products", s1, t+38),
        nav("/inventory-item.html", "/inventory.html", s1, t+39),

        pageload("/inventory.html", s1, t+40),
        click("/inventory.html", "2", "a", "shopping-cart-link", s1, t+44),
        nav("/inventory.html", "/cart.html", s1, t+45),

        pageload("/cart.html", s1, t+46),
        click("/cart.html", "Checkout", "button", "checkout", s1, t+52),
        nav("/cart.html", "/checkout-step-one.html", s1, t+53),

        pageload("/checkout-step-one.html", s1, t+54),
        inp("/checkout-step-one.html", "firstName", "Test", "text", s1, t+58),
        inp("/checkout-step-one.html", "lastName", "User", "text", s1, t+61),
        inp("/checkout-step-one.html", "postalCode", "10001", "text", s1, t+64),
        submit("/checkout-step-one.html", s1, t+65),
        click("/checkout-step-one.html", "Continue", "input", "continue", s1, t+66),
        nav("/checkout-step-one.html", "/checkout-step-two.html", s1, t+67),

        pageload("/checkout-step-two.html", s1, t+68),
        click("/checkout-step-two.html", "Finish", "button", "finish", s1, t+76),
        nav("/checkout-step-two.html", "/checkout-complete.html", s1, t+77),

        pageload("/checkout-complete.html", s1, t+78),
        click("/checkout-complete.html", "Back Home", "button", "back-to-products", s1, t+84),
        nav("/checkout-complete.html", "/inventory.html", s1, t+85),
    ]

    # ─────────────────────────────────────────────
    # SESSION 2: Sort + filter exploration
    # ─────────────────────────────────────────────
    s2 = str(uuid.uuid4())
    t = 200
    events += [
        pageload("/", s2, t),
        inp("/", "username", "standard_user", "text", s2, t+2),
        inp("/", "password", "", "password", s2, t+4),
        click("/", "Login", "input", "login-button", s2, t+5),
        nav("/", "/inventory.html", s2, t+6),

        pageload("/inventory.html", s2, t+7),
        click("/inventory.html", "Name (A to Z)", "option", "active-option", s2, t+14),
        click("/inventory.html", "Name (Z to A)", "option", "za", s2, t+20),
        click("/inventory.html", "Price (low to high)", "option", "lohi", s2, t+28),
        click("/inventory.html", "Price (high to low)", "option", "hilo", s2, t+36),

        click("/inventory.html", "Sauce Labs Fleece Jacket", "div", "inventory-item-name", s2, t+42),
        nav("/inventory.html", "/inventory-item.html", s2, t+43),

        pageload("/inventory-item.html", s2, t+44),
        click("/inventory-item.html", "Add to cart", "button", "add-to-cart", s2, t+50),
        click("/inventory-item.html", "Back to products", "button", "back-to-products", s2, t+54),
        nav("/inventory-item.html", "/inventory.html", s2, t+55),

        pageload("/inventory.html", s2, t+56),
        click("/inventory.html", "1", "a", "shopping-cart-link", s2, t+62),
        nav("/inventory.html", "/cart.html", s2, t+63),

        pageload("/cart.html", s2, t+64),
        click("/cart.html", "Remove", "button", "remove", s2, t+70),
        click("/cart.html", "Continue Shopping", "button", "continue-shopping", s2, t+76),
        nav("/cart.html", "/inventory.html", s2, t+77),
    ]

    # ─────────────────────────────────────────────
    # SESSION 3: Failed login → recovery → checkout
    # ─────────────────────────────────────────────
    s3 = str(uuid.uuid4())
    t = 400
    events += [
        pageload("/", s3, t),
        inp("/", "username", "locked_out_user", "text", s3, t+3),
        inp("/", "password", "", "password", s3, t+5),
        click("/", "Login", "input", "login-button", s3, t+6),

        inp("/", "username", "standard_user", "text", s3, t+16),
        inp("/", "password", "", "password", s3, t+18),
        click("/", "Login", "input", "login-button", s3, t+20),
        nav("/", "/inventory.html", s3, t+21),

        pageload("/inventory.html", s3, t+22),
        click("/inventory.html", "Sauce Labs Onesie", "div", "inventory-item-name", s3, t+28),
        nav("/inventory.html", "/inventory-item.html", s3, t+29),

        pageload("/inventory-item.html", s3, t+30),
        click("/inventory-item.html", "Add to cart", "button", "add-to-cart", s3, t+36),
        click("/inventory-item.html", "1", "a", "shopping-cart-link", s3, t+40),
        nav("/inventory-item.html", "/cart.html", s3, t+41),

        pageload("/cart.html", s3, t+42),
        click("/cart.html", "Checkout", "button", "checkout", s3, t+48),
        nav("/cart.html", "/checkout-step-one.html", s3, t+49),

        pageload("/checkout-step-one.html", s3, t+50),
        inp("/checkout-step-one.html", "firstName", "Jane", "text", s3, t+54),
        inp("/checkout-step-one.html", "lastName", "Doe", "text", s3, t+57),
        inp("/checkout-step-one.html", "postalCode", "SW1A", "text", s3, t+60),
        click("/checkout-step-one.html", "Continue", "input", "continue", s3, t+62),
        nav("/checkout-step-one.html", "/checkout-step-two.html", s3, t+63),

        pageload("/checkout-step-two.html", s3, t+64),
        click("/checkout-step-two.html", "Finish", "button", "finish", s3, t+72),
        nav("/checkout-step-two.html", "/checkout-complete.html", s3, t+73),

        pageload("/checkout-complete.html", s3, t+74),
    ]

    # ─────────────────────────────────────────────
    # SESSION 4: Quick add-multiple & bulk checkout
    # ─────────────────────────────────────────────
    s4 = str(uuid.uuid4())
    t = 600
    events += [
        pageload("/", s4, t),
        inp("/", "username", "standard_user", "text", s4, t+2),
        inp("/", "password", "", "password", s4, t+4),
        click("/", "Login", "input", "login-button", s4, t+5),
        nav("/", "/inventory.html", s4, t+6),

        pageload("/inventory.html", s4, t+7),
        click("/inventory.html", "Add to cart", "button", "add-to-cart-sauce-labs-backpack", s4, t+10),
        click("/inventory.html", "Add to cart", "button", "add-to-cart-sauce-labs-bike-light", s4, t+13),
        click("/inventory.html", "Add to cart", "button", "add-to-cart-sauce-labs-bolt-t-shirt", s4, t+16),
        click("/inventory.html", "Add to cart", "button", "add-to-cart-sauce-labs-fleece-jacket", s4, t+19),
        click("/inventory.html", "4", "a", "shopping-cart-link", s4, t+22),
        nav("/inventory.html", "/cart.html", s4, t+23),

        pageload("/cart.html", s4, t+24),
        click("/cart.html", "Checkout", "button", "checkout", s4, t+30),
        nav("/cart.html", "/checkout-step-one.html", s4, t+31),

        pageload("/checkout-step-one.html", s4, t+32),
        inp("/checkout-step-one.html", "firstName", "Bulk", "text", s4, t+36),
        inp("/checkout-step-one.html", "lastName", "Buyer", "text", s4, t+39),
        inp("/checkout-step-one.html", "postalCode", "94103", "text", s4, t+42),
        click("/checkout-step-one.html", "Continue", "input", "continue", s4, t+44),
        nav("/checkout-step-one.html", "/checkout-step-two.html", s4, t+45),

        pageload("/checkout-step-two.html", s4, t+46),
        click("/checkout-step-two.html", "Finish", "button", "finish", s4, t+54),
        nav("/checkout-step-two.html", "/checkout-complete.html", s4, t+55),
        pageload("/checkout-complete.html", s4, t+56),
    ]

    return events


if __name__ == "__main__":
    events = build_events()
    out_path = "/Users/rahil78626/Projects/TestAiPro/TestAI-Pro/backend/magic-events.json"
    with open(out_path, "w") as f:
        json.dump(events, f, indent=2)
    print(f"Generated {len(events)} events across 4 QA sessions → magic-events.json")
