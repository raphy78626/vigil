"""Export API: /api/journeys/{id}/export/*, /api/export/selenium/*, /api/export/ci."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from testai import state
from testai.export.ci import generate_github_actions
from testai.routes.helpers import build_journey

router = APIRouter()


class CIWorkflowRequest(BaseModel):
    framework: str = "playwright"
    base_url: str = "https://your-app.example.com"
    cron: str = ""
    has_auth: bool = False
    browsers: List[str] = ["chromium"]
    parallel_shards: int = 1
    retries: int = 2
    visual_regression: bool = False
    slack_webhook: bool = False


@router.get("/api/journeys/{journey_id}/export/playwright", response_class=PlainTextResponse)
async def export_playwright(journey_id: str):
    journey_data = state.db.get_journey_with_steps(journey_id)
    if not journey_data:
        raise HTTPException(status_code=404, detail="Journey not found")
    journey = build_journey(journey_id, journey_data)
    return state.playwright_exporter.export(journey)


@router.get("/api/journeys/{journey_id}/export/conftest", response_class=PlainTextResponse)
async def export_conftest(journey_id: str):
    journey_data = state.db.get_journey_with_steps(journey_id)
    if not journey_data:
        raise HTTPException(status_code=404, detail="Journey not found")
    journey = build_journey(journey_id, journey_data)
    return state.playwright_exporter.export_conftest(journey)


@router.get("/api/journeys/{journey_id}/export/cypress", response_class=PlainTextResponse)
async def export_cypress(journey_id: str):
    journey_data = state.db.get_journey_with_steps(journey_id)
    if not journey_data:
        raise HTTPException(status_code=404, detail="Journey not found")
    journey = build_journey(journey_id, journey_data)
    return state.cypress_exporter.export(journey)


@router.post("/api/export/ci", response_class=PlainTextResponse)
async def export_ci_workflow(req: CIWorkflowRequest):
    """Generate GitHub Actions workflow with cross-browser matrix, retries, and parallel sharding."""
    fw = "cypress" if req.framework.lower() == "cypress" else "playwright"
    return generate_github_actions(
        framework=fw,
        base_url=req.base_url,
        cron=req.cron,
        has_auth=req.has_auth,
        browsers=req.browsers,
        parallel_shards=req.parallel_shards,
        retries=req.retries,
        visual_regression=req.visual_regression,
        slack_webhook=req.slack_webhook,
    )


@router.get("/api/export/selenium/{journey_id}")
async def export_selenium(journey_id: str):
    """Export a journey as a Pytest + Selenium test."""
    journey_data = state.db.get_journey_with_steps(journey_id)
    if not journey_data:
        raise HTTPException(status_code=404, detail="Journey not found")
    journey = build_journey(journey_id, journey_data)
    code = state.selenium_exporter.export(journey)
    return PlainTextResponse(code, media_type="text/plain")


@router.get("/api/export/selenium/{journey_id}/requirements")
async def export_selenium_requirements(journey_id: str):
    """Get the pip requirements for the Selenium test."""
    return PlainTextResponse(state.selenium_exporter.export_requirements(), media_type="text/plain")
