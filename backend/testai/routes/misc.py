"""Misc API: coverage, domains, visual, flaky, noise, capture, credentials, monitors, api-tests, team, integrations, platform, browsers."""

from __future__ import annotations

import asyncio
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from testai import state
from testai.cluster.noise_filter import NoiseFilter

router = APIRouter()


# --- Coverage API ---

@router.get("/api/coverage")
async def coverage_summary():
    return state.coverage_analyzer.get_summary()


@router.get("/api/coverage/domains")
async def domain_coverage():
    return state.coverage_analyzer.get_domain_coverage()


@router.get("/api/coverage/features")
async def feature_coverage(domain: Optional[str] = None):
    return state.coverage_analyzer.get_feature_coverage(domain=domain)


@router.get("/api/domains")
async def list_domains():
    return state.db.get_all_domains()


# --- Cross-Browser & Mobile ---

@router.get("/api/browsers")
async def list_browsers():
    """List supported browsers and mobile device profiles."""
    return {
        "browsers": state.SUPPORTED_BROWSERS,
        "devices": {k: {**v, "id": k} for k, v in state.DEVICE_PROFILES.items()},
    }


# --- Visual Regression ---

@router.get("/api/visual/baselines/{journey_id}")
async def get_baselines(journey_id: str):
    """List visual baselines for a journey."""
    baselines = state.db.get_visual_baselines(journey_id)
    return [
        {"step_order": b["step_order"], "width": b["width"], "height": b["height"], "updated_at": b["updated_at"]}
        for b in baselines
    ]


@router.post("/api/visual/baselines/{journey_id}/reset")
async def reset_baselines(journey_id: str):
    """Delete all baselines for a journey so the next run creates new ones."""
    state.db.conn.execute("DELETE FROM visual_baselines WHERE journey_id = ?", (journey_id,))
    state.db.conn.commit()
    return {"ok": True, "journey_id": journey_id}


@router.get("/api/visual/diffs/{run_id}")
async def get_visual_diffs(run_id: str):
    """Get visual regression diffs for a specific run."""
    diffs = state.db.get_visual_diffs(run_id)
    return diffs


# --- Flaky Test Management ---

@router.get("/api/flaky")
async def get_flaky_tests():
    """List all detected flaky tests with their flake rates."""
    return state.db.get_flaky_tests()


@router.post("/api/flaky/analyze")
async def analyze_flaky():
    """Re-analyze all test runs to detect flaky tests."""
    results = state.db.analyze_flaky_tests()
    return {"analyzed": len(results), "flaky": [r for r in results if r.get("is_flaky")]}


@router.post("/api/flaky/{journey_id}/quarantine")
async def quarantine_flaky(journey_id: str, quarantine: bool = True):
    """Quarantine or unquarantine a flaky test."""
    state.db.quarantine_test(journey_id, quarantine)
    return {"ok": True, "journey_id": journey_id, "quarantined": quarantine}


@router.get("/api/flaky/{journey_id}/history")
async def flaky_history(journey_id: str, limit: int = 30):
    """Get pass/fail trend for a specific journey."""
    runs = state.db.get_run_history_for_journey(journey_id, limit)
    return {
        "journey_id": journey_id,
        "runs": runs,
        "total": len(runs),
        "pass_rate": round(sum(1 for r in runs if r["passed"]) / max(len(runs), 1) * 100, 1),
    }


# --- API Testing ---

class APITestCreateRequest(BaseModel):
    name: str
    method: str = "GET"
    url: str
    description: str = ""
    headers: dict = {}
    body: str | dict = ""
    assertions: List[dict] = []
    tags: List[str] = []


@router.post("/api/api-tests")
async def create_api_test(req: APITestCreateRequest):
    """Create a new API test case."""
    test = {
        "id": str(uuid.uuid4())[:8],
        "name": req.name,
        "description": req.description,
        "method": req.method.upper(),
        "url": req.url,
        "headers": req.headers,
        "body": req.body,
        "assertions": req.assertions,
        "tags": req.tags,
    }
    state.db.insert_api_test(test)
    return {"ok": True, "test": test}


@router.get("/api/api-tests")
async def list_api_tests(limit: int = 50):
    """List all API test cases."""
    return state.db.get_api_tests(limit)


@router.get("/api/api-tests/{test_id}")
async def get_api_test(test_id: str):
    """Get a specific API test case."""
    test = state.db.get_api_test(test_id)
    if not test:
        raise HTTPException(status_code=404, detail="API test not found")
    return test


@router.post("/api/api-tests/{test_id}/run")
async def run_api_test(test_id: str):
    """Execute an API test and record results."""
    test = state.db.get_api_test(test_id)
    if not test:
        raise HTTPException(status_code=404, detail="API test not found")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, state.api_test_runner.run_test, test)
    state.db.insert_api_test_run(result)
    return result


@router.post("/api/api-tests/run-batch")
async def run_api_test_batch():
    """Execute all API tests."""
    tests = state.db.get_api_tests(limit=200)
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, state.api_test_runner.run_batch, tests)
    for r in results:
        state.db.insert_api_test_run(r)
    passed = sum(1 for r in results if r["passed"])
    return {"total": len(results), "passed": passed, "failed": len(results) - passed, "results": results}


@router.get("/api/api-tests/{test_id}/runs")
async def list_api_test_runs(test_id: str, limit: int = 20):
    """Get run history for an API test."""
    return state.db.get_api_test_runs(test_id, limit)


@router.delete("/api/api-tests/{test_id}")
async def delete_api_test(test_id: str):
    """Delete an API test case."""
    if state.db.delete_api_test(test_id):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="API test not found")


# --- Monitoring / Scheduled Runs ---

class MonitorCreateRequest(BaseModel):
    name: str
    monitor_type: str = "journey"
    target_id: str
    base_url: str = ""
    cron_expr: str = "0 */6 * * *"
    browser: str = "chromium"
    webhook_url: str = ""


class MonitorUpdateRequest(BaseModel):
    name: Optional[str] = None
    cron_expr: Optional[str] = None
    browser: Optional[str] = None
    enabled: Optional[bool] = None
    webhook_url: Optional[str] = None
    base_url: Optional[str] = None


@router.post("/api/monitors")
async def create_monitor(req: MonitorCreateRequest):
    """Create a scheduled monitor for a journey, API test, or URL."""
    mon = {
        "id": str(uuid.uuid4())[:8],
        "name": req.name,
        "monitor_type": req.monitor_type,
        "target_id": req.target_id,
        "base_url": req.base_url,
        "cron_expr": req.cron_expr,
        "browser": req.browser,
        "webhook_url": req.webhook_url,
    }
    state.db.insert_monitor(mon)
    return {"ok": True, "monitor": mon}


@router.get("/api/monitors")
async def list_monitors(limit: int = 50):
    """List all scheduled monitors."""
    return state.db.get_monitors(limit)


@router.get("/api/monitors/alerts")
async def list_alerts(limit: int = 50):
    """List recent monitor alerts."""
    return state.db.get_alerts(limit)


@router.get("/api/monitors/status")
async def monitor_scheduler_status():
    """Check if the monitor scheduler is running."""
    return {"running": state.monitor_scheduler.is_running}


@router.post("/api/monitors/alerts/{alert_id}/ack")
async def acknowledge_alert(alert_id: str):
    """Acknowledge a monitor alert."""
    state.db.acknowledge_alert(alert_id)
    return {"ok": True}


@router.get("/api/monitors/{monitor_id}")
async def get_monitor(monitor_id: str):
    """Get a specific monitor."""
    mon = state.db.get_monitor(monitor_id)
    if not mon:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return mon


@router.patch("/api/monitors/{monitor_id}")
async def update_monitor(monitor_id: str, req: MonitorUpdateRequest):
    """Update a monitor's configuration."""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if "enabled" in updates:
        updates["enabled"] = 1 if updates["enabled"] else 0
    state.db.update_monitor(monitor_id, updates)
    return {"ok": True}


@router.delete("/api/monitors/{monitor_id}")
async def delete_monitor(monitor_id: str):
    """Delete a scheduled monitor."""
    if state.db.delete_monitor(monitor_id):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Monitor not found")


# --- Team / Auth ---

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str = ""
    role: str = "member"


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/api/team/register")
async def register_user(req: RegisterRequest):
    """Register a new team member."""
    try:
        user = state.team_auth.create_user(req.username, req.password, req.email, req.role)
        return {"ok": True, "user": user}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/team/login")
async def login_user(req: LoginRequest):
    """Authenticate and receive a JWT token."""
    result = state.team_auth.login(req.username, req.password)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return result


@router.get("/api/team/me")
async def get_current_user(authorization: str = Header(default="")):
    """Get the current authenticated user from their JWT token."""
    token = authorization.replace("Bearer ", "") if authorization else ""
    if not token:
        return {"authenticated": False}
    payload = state.team_auth.validate_token(token)
    if not payload:
        return {"authenticated": False}
    user = state.db.get_user(payload["sub"])
    if not user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "email": user.get("email", ""),
        },
    }


@router.get("/api/team/users")
async def list_users():
    """List all team members (admin-only in production)."""
    return state.db.get_users()


# --- Slack/Teams Integration ---

class SlackConfigRequest(BaseModel):
    webhook_url: str
    platform: str = "slack"
    channel: str = ""


class SlashCommandRequest(BaseModel):
    text: str = ""
    command: str = "/vigil"


@router.get("/api/integrations/slack/config")
async def get_slack_config():
    """Get the current Slack/Teams integration config."""
    return state.slack_bot.get_config()


@router.post("/api/integrations/slack/config")
async def save_slack_config(req: SlackConfigRequest):
    """Save Slack/Teams webhook configuration."""
    config = state.slack_bot.save_config(req.webhook_url, req.platform, req.channel)
    return {"ok": True, "config": config}


@router.post("/api/integrations/slack/test")
async def test_slack_webhook():
    """Send a test message to the configured Slack/Teams webhook."""
    ok = state.slack_bot.send_summary(total=5, passed=4, failed=1, flaky=1)
    return {"ok": ok, "message": "Test message sent" if ok else "Failed — check webhook URL"}


@router.post("/api/integrations/slack/slash")
async def handle_slash_command(req: SlashCommandRequest):
    """Handle /vigil slash commands from Slack."""
    return state.slack_bot.handle_slash_command(req.text, state.db)


# --- Noise Filtering ---

class NoiseFilterRequest(BaseModel):
    events: List[dict]
    allowed_domains: List[str] = []
    threshold: float = 0.4


@router.post("/api/noise/filter")
async def filter_noise(req: NoiseFilterRequest):
    """Filter noise from a batch of captured events."""
    nf = NoiseFilter(allowed_domains=req.allowed_domains, threshold=req.threshold)
    signal, noise = nf.filter_events(req.events)
    signal = nf.filter_burst_noise(signal)
    stats = nf.get_stats(req.events)
    return {"signal": signal, "noise": noise, "stats": stats}


@router.post("/api/noise/score")
async def score_event(event: dict):
    """Score a single event for noise probability."""
    score = state.noise_filter.score_event(event)
    return {"score": round(score, 3), "is_signal": score >= 0.4, "threshold": 0.4}


# --- Credential Manager ---

class CredentialRequest(BaseModel):
    domain: str
    username: str
    password: str
    role: str = "standard"
    label: str = ""


class LoginDetectRequest(BaseModel):
    url: str
    page_html: str = ""


@router.post("/api/credentials")
async def save_credential(req: CredentialRequest):
    """Store a credential for a domain."""
    result = state.credential_manager.save_credential(
        req.domain, req.username, req.password, req.role, req.label
    )
    return {"ok": True, "credential": result}


@router.get("/api/credentials")
async def list_credential_domains():
    """List all domains with stored credentials."""
    return state.credential_manager.list_domains()


@router.get("/api/credentials/{domain}")
async def get_domain_credentials(domain: str, role: str = None):
    """Get credentials for a domain (passwords are masked)."""
    return state.credential_manager.get_credentials(domain, role)


@router.delete("/api/credentials/{domain}/{username}")
async def delete_credential(domain: str, username: str):
    """Remove a stored credential."""
    ok = state.credential_manager.delete_credential(domain, username)
    if not ok:
        raise HTTPException(status_code=404, detail="Credential not found")
    return {"ok": True}


@router.post("/api/credentials/detect-login")
async def detect_login_page(req: LoginDetectRequest):
    """Detect whether a URL is a login page."""
    return state.credential_manager.detect_login_page(req.url, req.page_html)


# --- Rich Event Processing (Scroll/Hover/Drag) ---

@router.post("/api/capture/process-events")
async def process_rich_events(events: List[dict]):
    """Process raw extension events into enriched events with replay strategies."""
    processed = state.rich_event_processor.process(events)
    return {"events": processed, "total": len(processed)}


@router.get("/api/capture/supported-events")
async def supported_events():
    """List all supported rich event types."""
    return state.rich_event_processor.get_supported_events()


# --- Shadow DOM ---

@router.post("/api/capture/shadow-dom/enrich")
async def enrich_shadow_event(event: dict):
    """Enrich a captured event with Shadow DOM selector metadata."""
    enriched = state.shadow_dom_handler.enrich_event(event)
    return enriched


class ShadowSelectorRequest(BaseModel):
    shadow_path: List[dict]


@router.post("/api/capture/shadow-dom/selectors")
async def generate_shadow_selectors(req: ShadowSelectorRequest):
    """Generate framework-specific selectors for a Shadow DOM path."""
    return {
        "playwright": state.shadow_dom_handler.generate_playwright_selector(req.shadow_path),
        "selenium_js": state.shadow_dom_handler.generate_selenium_js(req.shadow_path),
        "cypress": state.shadow_dom_handler.generate_cypress_chain(req.shadow_path),
    }


# --- Platform Info ---

@router.get("/api/platform/info")
async def platform_info():
    """Return platform capabilities and status."""
    return {
        "version": "0.3.0",
        "features": {
            "visual_regression": True,
            "cross_browser": state.SUPPORTED_BROWSERS,
            "mobile_devices": list(state.DEVICE_PROFILES.keys()),
            "parallel_execution": True,
            "api_testing": True,
            "monitoring": state.monitor_scheduler.is_running,
            "team_auth": True,
            "flaky_management": True,
            "ci_cd_generation": ["playwright", "cypress"],
            "supported_llms": 6,
            "qa_skills": 11,
            "slack_teams_bot": state.slack_bot.enabled,
            "export_frameworks": ["playwright", "cypress", "selenium"],
            "noise_filtering": True,
            "journey_merging": True,
            "test_suite_generation": True,
            "credential_manager": True,
            "rich_events": list(state.rich_event_processor.get_supported_events().keys()),
            "shadow_dom": True,
        },
        "stats": {
            **state.db.get_run_stats(),
            "api_tests": len(state.db.get_api_tests(limit=1000)),
            "monitors": len(state.db.get_monitors(limit=1000)),
            "users": len(state.db.get_users()),
            "credential_domains": len(state.credential_manager.list_domains()),
        },
    }
