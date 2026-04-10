"""Generate mutated variants of a happy-path journey for QA exploration."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import List

from testai.models.journey import Journey

MAX_VARIANTS = 40


@dataclass
class Mutation:
    type: str            # "empty_field" | "invalid_format" | "boundary" | "skip_step"
    step_idx: int        # index in journey.steps
    field_key: str       # human label (e.g. "email", "step_3_click")
    mutated_value: str   # the new value (or "" for skip)
    description: str     # "Empty email field"
    expected_outcome: str  # "should_reject" | "may_accept" | "unknown"


@dataclass
class ExplorationVariant:
    variant_id: str
    journey: Journey     # deep-copy with one mutation applied
    mutation: Mutation


def _detect_field_type(step) -> str:
    """Detect the semantic type of a form field from its selectors."""
    sels = step.selectors
    candidates = [
        sels.get("input_type", ""),
        sels.get("name", ""),
        sels.get("label", ""),
        sels.get("placeholder", ""),
        sels.get("aria_label", ""),
        step.description or "",
    ]
    text = " ".join(c for c in candidates if c).lower()

    if "email" in text:
        return "email"
    if "password" in text or "passwd" in text:
        return "password"
    if "phone" in text or "tel" in text or sels.get("input_type") in ("tel", "phone"):
        return "phone"
    if "number" in text or sels.get("input_type") == "number":
        return "number"
    return "text"


def _field_mutations(field_type: str, field_key: str, step_idx: int) -> List[Mutation]:
    """Return a list of mutations appropriate for the detected field type."""
    mutations: List[Mutation] = []

    if field_type == "email":
        mutations = [
            Mutation("empty_field", step_idx, field_key, "", f"Empty {field_key} field", "should_reject"),
            Mutation("invalid_format", step_idx, field_key, "notanemail", f"Invalid email (no @)", "should_reject"),
            Mutation("invalid_format", step_idx, field_key, "test@", f"Malformed email (test@)", "should_reject"),
        ]
    elif field_type == "password":
        mutations = [
            Mutation("empty_field", step_idx, field_key, "", f"Empty {field_key} field", "should_reject"),
            Mutation("boundary", step_idx, field_key, "a", f"Too-short {field_key} (1 char)", "should_reject"),
            Mutation("boundary", step_idx, field_key, "' OR '1'='1", f"SQL injection in {field_key}", "should_reject"),
        ]
    elif field_type == "phone":
        mutations = [
            Mutation("empty_field", step_idx, field_key, "", f"Empty {field_key} field", "should_reject"),
            Mutation("invalid_format", step_idx, field_key, "not-a-phone", f"Non-numeric {field_key}", "should_reject"),
        ]
    elif field_type == "number":
        mutations = [
            Mutation("empty_field", step_idx, field_key, "", f"Empty {field_key} field", "should_reject"),
            Mutation("invalid_format", step_idx, field_key, "abc", f"Text in numeric {field_key}", "should_reject"),
            Mutation("boundary", step_idx, field_key, "-1", f"Negative value in {field_key}", "should_reject"),
        ]
    else:  # generic text
        mutations = [
            Mutation("empty_field", step_idx, field_key, "", f"Empty {field_key} field", "should_reject"),
            Mutation("boundary", step_idx, field_key, "A" * 256, f"Overflow {field_key} (256 chars)", "may_accept"),
            Mutation("boundary", step_idx, field_key, "<script>alert(1)</script>", f"XSS probe in {field_key}", "should_reject"),
            Mutation("boundary", step_idx, field_key, "测试🎉", f"Unicode/emoji in {field_key}", "may_accept"),
        ]

    return mutations


def _field_key(step) -> str:
    """Human-readable key for the field being filled."""
    sels = step.selectors
    for key in ("label", "aria_label", "name", "placeholder"):
        val = sels.get(key, "")
        if val:
            return val[:40]
    return step.description[:40] if step.description else f"step_{step.order}"


def _apply_mutation(journey: Journey, mutation: Mutation) -> Journey:
    """Return a deep-copy of journey with the mutation applied."""
    j = journey.model_copy(deep=True)
    j.id = str(uuid.uuid4())[:8]
    j.variant_of = journey.id

    if mutation.type == "skip_step":
        j.steps = [s for i, s in enumerate(j.steps) if i != mutation.step_idx]
        for idx, s in enumerate(j.steps):
            s.order = idx + 1
    elif mutation.type == "combo_empty":
        # Clear all fill-form step values at once
        for step in j.steps:
            if step.action_type in ("fill_form", "fill", "input", "type"):
                step.selectors = {**step.selectors, "value": ""}
    elif mutation.step_idx == -1:
        # Unmatched field — cannot apply, return unmodified copy
        pass
    else:
        # Standard fill_form mutation — set value in selectors
        step = j.steps[mutation.step_idx]
        step.selectors = {**step.selectors, "value": mutation.mutated_value}

    return j


def generate_variants(journey: Journey) -> List[ExplorationVariant]:
    """Generate mutation variants from a happy-path journey."""
    variants: List[ExplorationVariant] = []

    # Variant 0: original happy path (no mutation, but wrap in ExplorationVariant)
    no_op = Mutation("none", -1, "happy_path", "", "Original happy path", "unknown")
    original_copy = journey.model_copy(deep=True)
    variants.append(ExplorationVariant(
        variant_id="v0",
        journey=original_copy,
        mutation=no_op,
    ))

    vid = 1

    # Fill-form mutations
    for idx, step in enumerate(journey.steps):
        if step.action_type not in ("fill_form", "fill", "input", "type"):
            continue
        if vid >= MAX_VARIANTS:
            break

        field_type = _detect_field_type(step)
        fkey = _field_key(step)
        for mut in _field_mutations(field_type, fkey, idx):
            if vid >= MAX_VARIANTS:
                break
            mutated_journey = _apply_mutation(journey, mut)
            variants.append(ExplorationVariant(
                variant_id=f"v{vid}",
                journey=mutated_journey,
                mutation=mut,
            ))
            vid += 1

    # Skip-step mutations for click steps
    for idx, step in enumerate(journey.steps):
        if step.action_type not in ("click", "button", "link"):
            continue
        if vid >= MAX_VARIANTS:
            break

        mut = Mutation(
            "skip_step", idx,
            f"step_{step.order}_click",
            "",
            f"Skip step {step.order}: {step.description[:50]}",
            "unknown",
        )
        mutated_journey = _apply_mutation(journey, mut)
        variants.append(ExplorationVariant(
            variant_id=f"v{vid}",
            journey=mutated_journey,
            mutation=mut,
        ))
        vid += 1

    return variants[:MAX_VARIANTS]


def classify_behavior(variant: ExplorationVariant, exit_code: int, full_output: str) -> str:
    """Classify the app's behavior given a mutation variant and test result."""
    mtype = variant.mutation.type

    if mtype == "none":
        return "passed" if exit_code == 0 else "failed"

    if mtype == "skip_step":
        return "dependency_confirmed" if exit_code != 0 else "step_redundant"

    # empty_field / invalid_format / boundary / combo_empty
    if exit_code != 0:
        return "correctly_rejected"
    return "bug_accepted_invalid"


def generate_combinatorial_mutations(journey: Journey) -> List[Mutation]:
    """Generate cross-field combination mutations (all-empty, email+no-password)."""
    fill_steps = [
        (idx, step) for idx, step in enumerate(journey.steps)
        if step.action_type in ("fill_form", "fill", "input", "type")
    ]
    if not fill_steps:
        return []

    mutations: List[Mutation] = []

    # All required fields empty simultaneously
    mutations.append(Mutation(
        type="combo_empty",
        step_idx=-1,
        field_key="all_required_fields",
        mutated_value="__ALL_EMPTY__",
        description="All required fields empty",
        expected_outcome="should_reject",
    ))

    # Cross-field: valid email + empty password
    if len(fill_steps) >= 2:
        email_idx = -1
        password_idx = -1
        for idx, step in fill_steps:
            text = " ".join([
                step.selectors.get("input_type", ""),
                step.selectors.get("name", ""),
                step.selectors.get("label", ""),
                step.selectors.get("placeholder", ""),
                step.description or "",
            ]).lower()
            if "email" in text and email_idx == -1:
                email_idx = idx
            elif ("password" in text or "passwd" in text) and password_idx == -1:
                password_idx = idx

        if email_idx >= 0 and password_idx >= 0:
            mutations.append(Mutation(
                type="empty_field",
                step_idx=password_idx,
                field_key="password",
                mutated_value="",
                description="Valid email + empty password (cross-field)",
                expected_outcome="should_reject",
            ))

    return mutations[:3]


async def generate_variants_enhanced(
    journey: Journey,
    base_url: str,
    llm=None,
) -> tuple:
    """Enhanced variant generation with DOM inspection + LLM research.

    Returns (variants, research_log) where research_log is a dict with counts.
    Autoresearch is purely additive — static variants are always present.
    """
    import asyncio as _asyncio

    # 1. Static base variants (always present)
    base = generate_variants(journey)

    # 2. DOM research
    field_schemas = []
    if base_url:
        try:
            from testai.exploration.dom_inspector import (
                inspect_fields,
                generate_constraint_mutations,
            )
            field_schemas = await inspect_fields(base_url, journey)
            constraint_muts = generate_constraint_mutations(field_schemas, journey)
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "generate_variants_enhanced: DOM inspect failed: %s", e
            )
            constraint_muts = []
    else:
        constraint_muts = []

    # 3. LLM research (blocking call, run in executor to avoid blocking event loop)
    llm_muts = []
    if llm:
        try:
            from testai.exploration.llm_researcher import research_mutations
            loop = _asyncio.get_event_loop()
            llm_muts = await loop.run_in_executor(
                None, research_mutations, journey, field_schemas, llm
            )
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "generate_variants_enhanced: LLM research failed: %s", e
            )

    # 4. Combinatorial mutations
    combo_muts = generate_combinatorial_mutations(journey)

    # 5. Merge, deduplicate by (step_idx, mutated_value), cap at MAX_VARIANTS
    seen: set = set()
    for v in base:
        seen.add((v.mutation.step_idx, v.mutation.mutated_value))

    vid = len(base)
    for mut in (constraint_muts + llm_muts + combo_muts):
        if vid >= MAX_VARIANTS:
            break
        key = (mut.step_idx, mut.mutated_value)
        if key in seen:
            continue
        seen.add(key)
        mutated_journey = _apply_mutation(journey, mut)
        base.append(ExplorationVariant(
            variant_id=f"v{vid}",
            journey=mutated_journey,
            mutation=mut,
        ))
        vid += 1

    research_log = {
        "dom_fields": len(field_schemas),
        "constraint_mutations": len(constraint_muts),
        "llm_mutations": len(llm_muts),
    }
    return base[:MAX_VARIANTS], research_log
