"""AI API: /api/ai/*, /api/query."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from testai import state

router = APIRouter()


class QueryRequest(BaseModel):
    question: str


class AssertionRequest(BaseModel):
    journey_id: str
    context: str = ""


class NLTestRequest(BaseModel):
    description: str
    base_url: str = ""
    domain: str = ""


def _llm_query(question: str) -> Optional[str]:
    """Use the configured LLM to understand and answer the query."""
    domains = state.db.get_all_domains()
    all_journeys = state.db.get_journeys(limit=100)

    if not all_journeys:
        return None

    journey_index = "\n".join(
        f"- {j['name']} (domain={j.get('domain','?')}, feature={j.get('feature','?')}, "
        f"confidence={j.get('confidence',0):.0%}, steps={j.get('step_count', '?')})"
        for j in all_journeys
    )

    prompt = f"""You are a QA assistant for a test automation platform called Vigil.
The user is asking about their discovered test journeys.

Available domains: {', '.join(domains) if domains else 'none'}

Journey index:
{journey_index}

User question: "{question}"

Answer the question concisely using the journey data above. Use markdown formatting.
If the user is searching for specific journeys, list them with bullets.
If they ask about coverage, summarize which domains/features are covered.
If you can't answer from the data, say so honestly."""

    resp = state.llm.ask(prompt, max_tokens=512)
    return resp if resp else None


@router.post("/api/query")
async def query(req: QueryRequest):
    """AI-powered natural language query with keyword fallback."""
    q = req.question.strip()

    if state.llm.model:
        try:
            loop = asyncio.get_event_loop()
            answer = await loop.run_in_executor(None, _llm_query, q)
            if answer:
                return {"answer": answer, "ai": True}
        except Exception as _e:
            print(f"[warn] LLM query failed, falling back to keyword search: {_e}", file=sys.stderr)

    q_lower = q.lower()
    results = state.db.search_journeys(q_lower, limit=20)

    if not results:
        for word in sorted(q_lower.split(), key=len, reverse=True):
            if len(word) > 3:
                results = state.db.search_journeys(word, limit=20)
                if results:
                    break

    if not results:
        results = state.db.get_journeys(limit=10)

    if not results:
        return {"answer": "No journeys discovered yet. Run the demo or capture some events first!", "ai": False}

    lines = [f"Found {len(results)} journey(s):\n"]
    for r in results:
        lines.append(
            f"- **{r['name']}** ({r.get('domain', '?')} > {r.get('feature', '?')}) "
            f"[confidence: {r.get('confidence', 0):.0%}]"
        )
    return {"answer": "\n".join(lines), "ai": False}


@router.post("/api/ai/assertions")
async def generate_assertions(req: AssertionRequest):
    """Generate expect() assertions for a journey using the configured LLM."""
    journey_data = state.db.get_journey_with_steps(req.journey_id)
    if not journey_data:
        raise HTTPException(status_code=404, detail="Journey not found")

    steps = journey_data.get("steps", [])
    step_desc = "\n".join(
        f"  {i+1}. [{s.get('action_type','?')}] {s.get('description','')} on {s.get('url','')}"
        for i, s in enumerate(steps)
    )

    prompt = f"""Generate Playwright Python assertions (expect() calls) for this test journey.

Journey: {journey_data['name']}
Steps:
{step_desc}

{f'Additional context: {req.context}' if req.context else ''}

Return a JSON array of assertion objects:
[{{"after_step": 3, "code": "expect(page.locator(...)).to_be_visible()", "description": "Verify X is shown"}}]

Rules:
- Use playwright.sync_api expect() syntax
- Each assertion should verify a meaningful outcome (not just click happened)
- Focus on: page titles, visible elements, URL changes, text content
- Return ONLY valid JSON, no markdown"""

    result = state.llm.ask(prompt, temperature=0.2, max_tokens=2048)
    if not result:
        raise HTTPException(status_code=503, detail="LLM not available — configure a provider in Settings")

    try:
        if result.startswith("```"):
            result = result.split("\n", 1)[1].rsplit("```", 1)[0]
        assertions = json.loads(result)
    except json.JSONDecodeError:
        assertions = [{"after_step": 0, "code": result, "description": "Raw suggestion"}]

    return {"assertions": assertions, "model": state.llm.model}


@router.post("/api/ai/generate-test")
async def generate_test_from_nl(req: NLTestRequest):
    """Generate a Playwright test from a natural language description."""
    prompt = f"""Generate a complete Playwright Python test from this description.

Test description: {req.description}
Base URL: {req.base_url or 'use base_url parameter'}
Domain: {req.domain or 'web app'}

Requirements:
- pytest-playwright format: def test_xxx(page: Page, base_url: str):
- Use robust locators: get_by_role, get_by_text, get_by_label, data-testid
- Add page.wait_for_load_state("networkidle") after navigation
- Add expect() assertions to verify outcomes
- Use os.environ.get() for any credentials
- Include these imports: import os, re, pytest, from playwright.sync_api import Page, expect

Return ONLY the complete Python test file. No markdown fences."""

    result = state.llm.ask(prompt, temperature=0.2, max_tokens=4096)
    if not result:
        raise HTTPException(status_code=503, detail="LLM not available — configure a provider in Settings")

    if result.startswith("```"):
        result = result.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    return {"test_code": result, "model": state.llm.model}


@router.get("/api/ai/rca")
async def root_cause_analysis(journey_id: str = "", limit: int = 20):
    """Analyze recent failures for patterns and root causes."""
    runs = state.db.get_test_runs(journey_id or None, limit)
    failures = [r for r in runs if not r.get("passed")]

    if not failures:
        return {"analysis": "No failures found in recent runs.", "patterns": []}

    fail_summary = "\n".join(
        f"- Run {i+1}: {r.get('journey_name','')} on {r.get('base_url','')} — "
        f"failed at step {r.get('passed_steps',0)}/{r.get('total_steps',0)}, "
        f"error: {r.get('error_message','')[:200]}, "
        f"healed: {bool(r.get('healed'))}, duration: {r.get('duration_ms',0)}ms"
        for i, r in enumerate(failures[:15])
    )

    prompt = f"""Analyze these Playwright test failures and identify patterns.

Recent failures ({len(failures)} total):
{fail_summary}

Provide a JSON response:
{{
  "summary": "1-2 sentence overview",
  "patterns": [{{"pattern": "description", "frequency": "X of Y", "severity": "high|medium|low", "fix": "suggested fix"}}],
  "flaky_tests": ["journey names that fail intermittently"],
  "recommendations": ["actionable items"]
}}

Return ONLY valid JSON."""

    result = state.llm.ask(prompt, temperature=0.1, max_tokens=2048)
    if not result:
        basic = {
            "summary": f"{len(failures)} failures in recent {len(runs)} runs.",
            "patterns": [],
            "flaky_tests": [],
            "recommendations": ["Configure an LLM provider in Settings for AI-powered analysis."],
        }
        return {"analysis": basic, "model": "none"}

    try:
        if result.startswith("```"):
            result = result.split("\n", 1)[1].rsplit("```", 1)[0]
        analysis = json.loads(result)
    except json.JSONDecodeError:
        analysis = {"summary": result[:500], "patterns": [], "flaky_tests": [], "recommendations": []}

    return {"analysis": analysis, "model": state.llm.model}
