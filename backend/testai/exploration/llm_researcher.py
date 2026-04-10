"""LLM-powered mutation researcher for the autoresearch phase."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, List

from testai.models.journey import Journey
from testai.exploration.mutations import Mutation

if TYPE_CHECKING:
    from testai.llm.provider import LLMProvider
    from testai.exploration.dom_inspector import FieldSchema

logger = logging.getLogger(__name__)

_RESEARCH_SYSTEM = (
    "You are a senior QA security engineer. Given a web form journey, suggest mutation "
    "test cases that would reveal missing validation. Focus on: domain-specific invalid "
    "values, business logic edge cases, security inputs, cross-field dependencies. "
    "Reply ONLY with a valid JSON array — no prose, no markdown."
)

_ALLOWED_OUTCOMES = {"should_reject", "may_accept"}
_ALLOWED_TYPES = {"boundary", "invalid_format", "empty_field"}


def _build_research_prompt(
    journey: Journey,
    field_schemas,
    existing_mutations: List[Mutation],
) -> str:
    lines = [f"Journey: {journey.name}", ""]
    lines.append("Steps:")
    for step in journey.steps:
        lines.append(
            f"  - [{step.action_type}] {step.description} (url: {step.url})"
        )
    lines.append("")

    if field_schemas:
        lines.append("Form fields discovered via DOM:")
        for fs in field_schemas:
            attrs = [f"type={fs.html_type}", f"required={fs.required}"]
            if fs.min_length:
                attrs.append(f"minlength={fs.min_length}")
            if fs.max_length:
                attrs.append(f"maxlength={fs.max_length}")
            if fs.pattern:
                attrs.append(f"pattern={fs.pattern}")
            lines.append(f"  - {fs.field_key}: {', '.join(attrs)}")
        lines.append("")

    if existing_mutations:
        lines.append("Already-planned mutations (do NOT repeat):")
        for m in existing_mutations[:20]:
            lines.append(f"  - {m.description} → '{m.mutated_value}'")
        lines.append("")

    lines.append(
        "Return up to 8 NEW mutation test cases as a JSON array. Each item must have:\n"
        '  {"description": "...", "field_key": "...", "mutated_value": "...",\n'
        '   "expected_outcome": "should_reject|may_accept",\n'
        '   "mutation_type": "boundary|invalid_format|empty_field"}\n'
        "\nFocus on domain-specific cases the static rules would miss."
    )
    return "\n".join(lines)


def _match_step_idx(field_key: str, journey: Journey) -> int:
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


def research_mutations(
    journey: Journey,
    field_schemas,
    llm,
) -> List[Mutation]:
    """Call LLM to brainstorm context-specific mutations. Returns [] on any failure."""
    if llm is None:
        return []

    try:
        status = llm.get_status()
        if not (status.get("has_key") or status.get("provider") == "ollama"):
            return []
    except Exception:
        return []

    # Collect existing static mutations to avoid duplication in the prompt
    existing_muts: List[Mutation] = []
    try:
        from testai.exploration.mutations import generate_variants
        existing_muts = [
            v.mutation for v in generate_variants(journey)
            if v.mutation.type != "none"
        ]
    except Exception:
        pass

    prompt = _build_research_prompt(journey, field_schemas, existing_muts)

    try:
        response = llm.ask(prompt, system=_RESEARCH_SYSTEM, temperature=0.3, max_tokens=1024)
        if not response:
            return []
    except Exception as e:
        logger.warning("llm_researcher: LLM call failed: %s", e)
        return []

    # Strip markdown fences if present
    text = response.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Extract the JSON array
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        logger.warning("llm_researcher: no JSON array in LLM response")
        return []

    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.warning("llm_researcher: JSON parse failed: %s", e)
        return []

    mutations: List[Mutation] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not all(k in item for k in ("description", "field_key", "mutated_value", "expected_outcome")):
            continue
        if item["expected_outcome"] not in _ALLOWED_OUTCOMES:
            continue
        if not isinstance(item["mutated_value"], str):
            continue

        mtype = item.get("mutation_type", "invalid_format")
        if mtype not in _ALLOWED_TYPES:
            mtype = "invalid_format"

        step_idx = _match_step_idx(str(item["field_key"]), journey)
        mutations.append(Mutation(
            type=mtype,
            step_idx=step_idx,
            field_key=str(item["field_key"])[:40],
            mutated_value=str(item["mutated_value"]),
            description=str(item["description"])[:100],
            expected_outcome=item["expected_outcome"],
        ))

    return mutations[:8]
