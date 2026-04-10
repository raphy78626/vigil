"""
Demo script: generates realistic captured events simulating a QA session
on saucedemo.com, then runs the full pipeline.

Usage:
    python -m testai.demo                    # Uses rule-based labeler (no API key needed)
    python -m testai.demo --use-llm          # Uses real LLM for labeling (needs API key)
"""

import json
import uuid
import sys
from datetime import datetime, timedelta
from pathlib import Path


def generate_saucedemo_events():
    """Simulate a QA tester exploring saucedemo.com for ~10 minutes."""
    base_time = datetime.now() - timedelta(hours=1)
    session_id = str(uuid.uuid4())
    events = []

    def ts(minutes, seconds=0):
        return int((base_time + timedelta(minutes=minutes, seconds=seconds)).timestamp() * 1000)

    def evt(t, etype, url, element=None, navigation=None, title=""):
        return {
            "id": str(uuid.uuid4()),
            "timestamp": t,
            "isoTime": datetime.fromtimestamp(t / 1000).isoformat(),
            "type": etype,
            "url": url,
            "pageTitle": title,
            "tabId": 1,
            "sessionId": session_id,
            "element": element,
            "navigation": navigation,
        }

    # --- Journey 1: Login Flow ---
    events.append(evt(ts(0), "pageload", "https://www.saucedemo.com/",
                       navigation={"fromUrl": "", "toUrl": "https://www.saucedemo.com/", "trigger": "pageload"},
                       title="Swag Labs"))
    events.append(evt(ts(0, 5), "click", "https://www.saucedemo.com/",
                       element={"tagName": "input", "selectors": {"css": "#user-name", "text": None, "testId": "username", "id": "user-name", "name": "user-name", "placeholder": "Username", "ariaLabel": None, "className": "input_error form_input"}, "inputType": "text", "value": None},
                       title="Swag Labs"))
    events.append(evt(ts(0, 10), "input", "https://www.saucedemo.com/",
                       element={"tagName": "input", "selectors": {"css": "#user-name", "text": None, "testId": "username", "id": "user-name", "name": "user-name", "placeholder": "Username", "ariaLabel": None, "className": "input_error form_input"}, "inputType": "text", "value": "standard_user"},
                       title="Swag Labs"))
    events.append(evt(ts(0, 15), "click", "https://www.saucedemo.com/",
                       element={"tagName": "input", "selectors": {"css": "#password", "text": None, "testId": "password", "id": "password", "name": "password", "placeholder": "Password", "ariaLabel": None, "className": "input_error form_input"}, "inputType": "password", "value": None},
                       title="Swag Labs"))
    events.append(evt(ts(0, 18), "input", "https://www.saucedemo.com/",
                       element={"tagName": "input", "selectors": {"css": "#password", "text": None, "testId": "password", "id": "password", "name": "password", "placeholder": "Password", "ariaLabel": None, "className": "input_error form_input"}, "inputType": "password", "value": "[REDACTED]"},
                       title="Swag Labs"))
    events.append(evt(ts(0, 22), "click", "https://www.saucedemo.com/",
                       element={"tagName": "input", "selectors": {"css": "#login-button", "text": "Login", "testId": "login-button", "id": "login-button", "name": "login-button", "placeholder": None, "ariaLabel": None, "className": "submit-button btn_action"}, "inputType": "submit", "value": "Login"},
                       title="Swag Labs"))
    events.append(evt(ts(0, 25), "navigation", "https://www.saucedemo.com/inventory.html",
                       navigation={"fromUrl": "https://www.saucedemo.com/", "toUrl": "https://www.saucedemo.com/inventory.html", "trigger": "spa"},
                       title="Swag Labs"))
    events.append(evt(ts(0, 26), "pageload", "https://www.saucedemo.com/inventory.html",
                       navigation={"fromUrl": "https://www.saucedemo.com/", "toUrl": "https://www.saucedemo.com/inventory.html", "trigger": "pageload"},
                       title="Swag Labs"))

    # --- Journey 2: Browse Products + Add to Cart ---
    events.append(evt(ts(1, 0), "click", "https://www.saucedemo.com/inventory.html",
                       element={"tagName": "div", "selectors": {"css": ".inventory_item:nth-child(1) .inventory_item_name", "text": "Sauce Labs Backpack", "testId": "inventory-item-name", "id": None, "name": None, "placeholder": None, "ariaLabel": None, "className": "inventory_item_name"}, "inputType": None, "value": None},
                       title="Swag Labs"))
    events.append(evt(ts(1, 3), "pageload", "https://www.saucedemo.com/inventory-item.html?id=4",
                       navigation={"fromUrl": "https://www.saucedemo.com/inventory.html", "toUrl": "https://www.saucedemo.com/inventory-item.html?id=4", "trigger": "pageload"},
                       title="Swag Labs"))
    events.append(evt(ts(1, 10), "click", "https://www.saucedemo.com/inventory-item.html?id=4",
                       element={"tagName": "button", "selectors": {"css": "#add-to-cart", "text": "Add to cart", "testId": "add-to-cart", "id": "add-to-cart", "name": None, "placeholder": None, "ariaLabel": None, "className": "btn btn_primary btn_small btn_inventory"}, "inputType": None, "value": None},
                       title="Swag Labs"))
    events.append(evt(ts(1, 15), "click", "https://www.saucedemo.com/inventory-item.html?id=4",
                       element={"tagName": "button", "selectors": {"css": "#back-to-products", "text": "Back to products", "testId": "back-to-products", "id": "back-to-products", "name": None, "placeholder": None, "ariaLabel": None, "className": "inventory_details_back_button"}, "inputType": None, "value": None},
                       title="Swag Labs"))
    events.append(evt(ts(1, 17), "navigation", "https://www.saucedemo.com/inventory.html",
                       navigation={"fromUrl": "https://www.saucedemo.com/inventory-item.html?id=4", "toUrl": "https://www.saucedemo.com/inventory.html", "trigger": "spa"},
                       title="Swag Labs"))
    events.append(evt(ts(1, 30), "click", "https://www.saucedemo.com/inventory.html",
                       element={"tagName": "button", "selectors": {"css": "#add-to-cart-sauce-labs-bike-light", "text": "Add to cart", "testId": "add-to-cart-sauce-labs-bike-light", "id": "add-to-cart-sauce-labs-bike-light", "name": None, "placeholder": None, "ariaLabel": None, "className": "btn btn_primary btn_small btn_inventory"}, "inputType": None, "value": None},
                       title="Swag Labs"))

    # --- Journey 3: Checkout Flow ---
    events.append(evt(ts(2, 0), "click", "https://www.saucedemo.com/inventory.html",
                       element={"tagName": "a", "selectors": {"css": ".shopping_cart_link", "text": "2", "testId": "shopping-cart-link", "id": None, "name": None, "placeholder": None, "ariaLabel": None, "className": "shopping_cart_link"}, "inputType": None, "value": None},
                       title="Swag Labs"))
    events.append(evt(ts(2, 2), "pageload", "https://www.saucedemo.com/cart.html",
                       navigation={"fromUrl": "https://www.saucedemo.com/inventory.html", "toUrl": "https://www.saucedemo.com/cart.html", "trigger": "pageload"},
                       title="Swag Labs"))
    events.append(evt(ts(2, 10), "click", "https://www.saucedemo.com/cart.html",
                       element={"tagName": "button", "selectors": {"css": "#checkout", "text": "Checkout", "testId": "checkout", "id": "checkout", "name": None, "placeholder": None, "ariaLabel": None, "className": "submit-button btn_action"}, "inputType": None, "value": None},
                       title="Swag Labs"))
    events.append(evt(ts(2, 12), "pageload", "https://www.saucedemo.com/checkout-step-one.html",
                       navigation={"fromUrl": "https://www.saucedemo.com/cart.html", "toUrl": "https://www.saucedemo.com/checkout-step-one.html", "trigger": "pageload"},
                       title="Swag Labs"))
    events.append(evt(ts(2, 18), "input", "https://www.saucedemo.com/checkout-step-one.html",
                       element={"tagName": "input", "selectors": {"css": "#first-name", "text": None, "testId": "firstName", "id": "first-name", "name": None, "placeholder": "First Name", "ariaLabel": None, "className": "input_error form_input"}, "inputType": "text", "value": "Test"},
                       title="Swag Labs"))
    events.append(evt(ts(2, 22), "input", "https://www.saucedemo.com/checkout-step-one.html",
                       element={"tagName": "input", "selectors": {"css": "#last-name", "text": None, "testId": "lastName", "id": "last-name", "name": None, "placeholder": "Last Name", "ariaLabel": None, "className": "input_error form_input"}, "inputType": "text", "value": "User"},
                       title="Swag Labs"))
    events.append(evt(ts(2, 26), "input", "https://www.saucedemo.com/checkout-step-one.html",
                       element={"tagName": "input", "selectors": {"css": "#postal-code", "text": None, "testId": "postalCode", "id": "postal-code", "name": None, "placeholder": "Zip/Postal Code", "ariaLabel": None, "className": "input_error form_input"}, "inputType": "text", "value": "12345"},
                       title="Swag Labs"))
    events.append(evt(ts(2, 30), "click", "https://www.saucedemo.com/checkout-step-one.html",
                       element={"tagName": "input", "selectors": {"css": "#continue", "text": "Continue", "testId": "continue", "id": "continue", "name": None, "placeholder": None, "ariaLabel": None, "className": "submit-button btn_action"}, "inputType": "submit", "value": "Continue"},
                       title="Swag Labs"))
    events.append(evt(ts(2, 32), "pageload", "https://www.saucedemo.com/checkout-step-two.html",
                       navigation={"fromUrl": "https://www.saucedemo.com/checkout-step-one.html", "toUrl": "https://www.saucedemo.com/checkout-step-two.html", "trigger": "pageload"},
                       title="Swag Labs"))
    events.append(evt(ts(2, 40), "click", "https://www.saucedemo.com/checkout-step-two.html",
                       element={"tagName": "button", "selectors": {"css": "#finish", "text": "Finish", "testId": "finish", "id": "finish", "name": None, "placeholder": None, "ariaLabel": None, "className": "submit-button btn_action"}, "inputType": None, "value": None},
                       title="Swag Labs"))
    events.append(evt(ts(2, 42), "pageload", "https://www.saucedemo.com/checkout-complete.html",
                       navigation={"fromUrl": "https://www.saucedemo.com/checkout-step-two.html", "toUrl": "https://www.saucedemo.com/checkout-complete.html", "trigger": "pageload"},
                       title="Swag Labs"))

    return events


def generate_demo_file(output_path: str = "demo-events.json"):
    events = generate_saucedemo_events()
    Path(output_path).write_text(json.dumps(events, indent=2))
    print(f"Generated {len(events)} demo events → {output_path}")
    return output_path


if __name__ == "__main__":
    use_llm = "--use-llm" in sys.argv

    demo_file = Path(__file__).parent.parent.parent / "demo-events.json"
    generate_demo_file(str(demo_file))

    if use_llm:
        from testai.cluster.pipeline import run_pipeline
        print("\nRunning pipeline with LLM labeling...\n")
        run_pipeline(str(demo_file))
    else:
        from testai.cluster.pipeline_local import run_pipeline_local
        print("\nRunning pipeline with rule-based labeling (no API key needed)...\n")
        run_pipeline_local(str(demo_file))
