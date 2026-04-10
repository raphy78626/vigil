"""DOM inspector: headless Playwright field introspection for autoresearch."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse, urlunparse

from testai.models.journey import Journey
from testai.exploration.mutations import Mutation

logger = logging.getLogger(__name__)

# JavaScript injected via page.evaluate() to extract input attributes
_JS_INSPECT = r"""
() => {
    const inputs = Array.from(document.querySelectorAll(
        'input:not([type="hidden"]), textarea, select'
    ));
    return inputs.map(el => ({
        type: el.type || el.tagName.toLowerCase(),
        name: el.name || '',
        id: el.id || '',
        required: el.required || false,
        minLength: (el.minLength !== undefined && el.minLength > 0) ? el.minLength : null,
        maxLength: (el.maxLength !== undefined && el.maxLength > 0 && el.maxLength < 524288)
                    ? el.maxLength : null,
        min: el.min || null,
        max: el.max || null,
        pattern: el.pattern || null,
        placeholder: el.placeholder || '',
        ariaLabel: el.getAttribute('aria-label') || '',
        labelText: (() => {
            if (el.id) {
                const lbl = document.querySelector('label[for="' + el.id + '"]');
                if (lbl) return lbl.textContent.trim().slice(0, 60);
            }
            const parent = el.closest('label');
            if (parent) return parent.textContent.trim().slice(0, 60);
            return '';
        })(),
    }));
}
"""


@dataclass
class FieldSchema:
    field_key: str
    html_type: str
    required: bool
    min_length: Optional[int]
    max_length: Optional[int]
    min_value: Optional[str]
    max_value: Optional[str]
    pattern: Optional[str]
    step_idx: int  # index of matching journey step, or -1


def _make_field_key(raw: dict) -> str:
    """Pick the most human-readable key for a field."""
    for k in ("labelText", "ariaLabel", "name", "placeholder", "id"):
        v = raw.get(k, "")
        if v:
            return str(v)[:40]
    return "field"


def _match_step(field_key: str, journey: Journey) -> int:
    """Find the first fill step whose selector text contains field_key."""
    fk = field_key.lower()
    for idx, step in enumerate(journey.steps):
        if step.action_type not in ("fill_form", "fill", "input", "type"):
            continue
        for sv in step.selectors.values():
            if sv and fk in sv.lower():
                return idx
        if step.description and fk in step.description.lower():
            return idx
    return -1


async def inspect_fields(base_url: str, journey: Journey) -> List[FieldSchema]:
    """Launch headless Chromium, navigate to the form URL, extract field constraints."""
    # Find the URL of the first fill step
    form_url = ""
    for step in journey.steps:
        if step.action_type in ("fill_form", "fill", "input", "type") and step.url:
            form_url = step.url
            break
    if not form_url and journey.steps:
        form_url = journey.steps[0].url
    if not form_url and base_url:
        form_url = base_url
    if not form_url:
        return []

    # Re-anchor the path to the supplied base_url (scheme + netloc override)
    if base_url and form_url:
        try:
            parsed_form = urlparse(form_url)
            parsed_base = urlparse(base_url)
            form_url = urlunparse(parsed_form._replace(
                scheme=parsed_base.scheme,
                netloc=parsed_base.netloc,
            ))
        except Exception:
            pass

    js_code = json.dumps(_JS_INSPECT)
    target_url = json.dumps(form_url)

    script = f"""import asyncio, json, sys
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto({target_url}, wait_until='domcontentloaded', timeout=15000)
            await page.wait_for_timeout(1500)
            result = await page.evaluate({js_code})
            print(json.dumps(result))
        except Exception as e:
            print("[]")
            sys.exit(0)
        finally:
            await browser.close()

asyncio.run(main())
"""

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "dom_inspect.py"
            script_path.write_text(script, encoding="utf-8")

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmpdir,
            )
            try:
                stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=25)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                logger.warning("dom_inspector: timeout inspecting %s", form_url)
                return []

        raw_text = stdout.decode("utf-8", errors="replace").strip()
        raw_list = json.loads(raw_text or "[]")
        if not isinstance(raw_list, list):
            return []

        schemas: List[FieldSchema] = []
        for raw in raw_list:
            if not isinstance(raw, dict):
                continue
            fk = _make_field_key(raw)
            html_type = (raw.get("type") or "text").lower()
            if html_type == "textarea":
                html_type = "text"

            max_len = raw.get("maxLength")
            max_len = int(max_len) if max_len is not None else None

            min_len = raw.get("minLength")
            min_len = int(min_len) if min_len is not None else None

            schemas.append(FieldSchema(
                field_key=fk,
                html_type=html_type,
                required=bool(raw.get("required", False)),
                min_length=min_len,
                max_length=max_len,
                min_value=raw.get("min") or None,
                max_value=raw.get("max") or None,
                pattern=raw.get("pattern") or None,
                step_idx=_match_step(fk, journey),
            ))
        return schemas

    except Exception as e:
        logger.warning("dom_inspector: error: %s", e)
        return []


def generate_constraint_mutations(
    field_schemas: List[FieldSchema],
    journey: Journey,
) -> List[Mutation]:
    """Generate boundary/format mutations derived from HTML field constraints."""
    mutations: List[Mutation] = []

    for schema in field_schemas:
        idx = schema.step_idx

        # maxlength boundary: N+1 chars
        if schema.max_length and schema.max_length > 0:
            mutations.append(Mutation(
                type="boundary",
                step_idx=idx,
                field_key=schema.field_key,
                mutated_value="A" * (schema.max_length + 1),
                description=f"Over maxlength ({schema.max_length}+1) in {schema.field_key}",
                expected_outcome="should_reject",
            ))

        # minlength boundary: N-1 chars
        if schema.min_length and schema.min_length > 0:
            val = "A" * max(schema.min_length - 1, 0)
            mutations.append(Mutation(
                type="boundary",
                step_idx=idx,
                field_key=schema.field_key,
                mutated_value=val,
                description=f"Under minlength ({schema.min_length}-1) in {schema.field_key}",
                expected_outcome="should_reject",
            ))

        # number min: below minimum
        if schema.min_value is not None and schema.html_type == "number":
            try:
                mutations.append(Mutation(
                    type="boundary",
                    step_idx=idx,
                    field_key=schema.field_key,
                    mutated_value=str(int(schema.min_value) - 1),
                    description=f"Below min ({schema.min_value}) in {schema.field_key}",
                    expected_outcome="should_reject",
                ))
            except (ValueError, TypeError):
                pass

        # number max: above maximum
        if schema.max_value is not None and schema.html_type == "number":
            try:
                mutations.append(Mutation(
                    type="boundary",
                    step_idx=idx,
                    field_key=schema.field_key,
                    mutated_value=str(int(schema.max_value) + 1),
                    description=f"Above max ({schema.max_value}) in {schema.field_key}",
                    expected_outcome="should_reject",
                ))
            except (ValueError, TypeError):
                pass

        # pattern violation
        if schema.pattern:
            mutations.append(Mutation(
                type="invalid_format",
                step_idx=idx,
                field_key=schema.field_key,
                mutated_value="INVALID_9!@#",
                description=f"Pattern-violating value in {schema.field_key}",
                expected_outcome="should_reject",
            ))

        # url type
        if schema.html_type == "url":
            for v in ("not-a-url", "ftp://"):
                mutations.append(Mutation(
                    type="invalid_format",
                    step_idx=idx,
                    field_key=schema.field_key,
                    mutated_value=v,
                    description=f"Invalid URL '{v}' in {schema.field_key}",
                    expected_outcome="should_reject",
                ))

        # date type
        if schema.html_type == "date":
            for v in ("2099-13-45", "not-a-date"):
                mutations.append(Mutation(
                    type="invalid_format",
                    step_idx=idx,
                    field_key=schema.field_key,
                    mutated_value=v,
                    description=f"Invalid date '{v}' in {schema.field_key}",
                    expected_outcome="should_reject",
                ))

        # required field confirmation (only when step is matched)
        if schema.required and idx >= 0:
            mutations.append(Mutation(
                type="empty_field",
                step_idx=idx,
                field_key=schema.field_key,
                mutated_value="",
                description=f"Empty required field (DOM confirmed): {schema.field_key}",
                expected_outcome="should_reject",
            ))

    return mutations
