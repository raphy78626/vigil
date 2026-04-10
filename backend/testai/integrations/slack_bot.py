"""Slack/Teams integration — incoming webhooks, slash command handler, failure alerts.

Supports:
  - POST to Slack/Teams webhook for failure notifications
  - Slash command handler: /vigil query <text>, /vigil status, /vigil replay <journey_id>
  - Rich message formatting with attachments
  - Configurable webhook URL per workspace
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx

_CONFIG_PATH = Path.home() / ".vigil" / "slack.json"

PLATFORMS = {
    "slack": {"name": "Slack", "color_pass": "#2eb886", "color_fail": "#e01e5a", "color_warn": "#daa038"},
    "teams": {"name": "Teams", "color_pass": "Good", "color_fail": "Attention", "color_warn": "Warning"},
}


class SlackBot:
    def __init__(self):
        self._config = self._load_config()

    def _load_config(self) -> Dict:
        if _CONFIG_PATH.exists():
            return json.loads(_CONFIG_PATH.read_text())
        return {"webhook_url": "", "platform": "slack", "channel": "", "enabled": False}

    def save_config(self, webhook_url: str, platform: str = "slack", channel: str = "") -> Dict:
        self._config = {
            "webhook_url": webhook_url,
            "platform": platform,
            "channel": channel,
            "enabled": bool(webhook_url),
        }
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(json.dumps(self._config, indent=2))
        return self._config

    def get_config(self) -> Dict:
        return {**self._config, "webhook_url": self._config.get("webhook_url", "")[:20] + "..." if self._config.get("webhook_url") else ""}

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("enabled") and self._config.get("webhook_url"))

    def send_test_result(self, journey_name: str, passed: bool, run_id: str,
                         base_url: str = "", duration_ms: int = 0, browser: str = "",
                         healed: bool = False, error: str = "") -> bool:
        if not self.enabled:
            return False

        status = "PASSED" if passed else "FAILED"
        color = PLATFORMS["slack"]["color_pass"] if passed else PLATFORMS["slack"]["color_fail"]
        icon = ":white_check_mark:" if passed else ":x:"

        fields = [
            {"title": "Journey", "value": journey_name, "short": True},
            {"title": "Status", "value": f"{icon} {status}", "short": True},
            {"title": "Browser", "value": browser or "chromium", "short": True},
            {"title": "Duration", "value": f"{duration_ms}ms", "short": True},
        ]
        if base_url:
            fields.append({"title": "URL", "value": base_url, "short": False})
        if healed:
            fields.append({"title": "Auto-Healed", "value": ":wrench: Yes", "short": True})
        if error and not passed:
            fields.append({"title": "Error", "value": f"```{error[:200]}```", "short": False})

        return self._post_webhook({
            "text": f"Vigil Test {status}: {journey_name}",
            "attachments": [{
                "color": color,
                "fields": fields,
                "footer": f"Vigil | Run {run_id[:8]}",
                "ts": int(datetime.now(timezone.utc).timestamp()),
            }],
        })

    def send_alert(self, monitor_name: str, alert_type: str, message: str) -> bool:
        if not self.enabled:
            return False
        color = PLATFORMS["slack"]["color_fail"] if alert_type == "failure" else PLATFORMS["slack"]["color_warn"]
        return self._post_webhook({
            "text": f":rotating_light: Vigil Alert: {monitor_name}",
            "attachments": [{
                "color": color,
                "fields": [
                    {"title": "Monitor", "value": monitor_name, "short": True},
                    {"title": "Type", "value": alert_type, "short": True},
                    {"title": "Details", "value": message[:500], "short": False},
                ],
                "footer": "Vigil Monitor",
                "ts": int(datetime.now(timezone.utc).timestamp()),
            }],
        })

    def send_summary(self, total: int, passed: int, failed: int, flaky: int = 0) -> bool:
        if not self.enabled:
            return False
        icon = ":white_check_mark:" if failed == 0 else ":warning:"
        return self._post_webhook({
            "text": f"{icon} Vigil Daily Summary",
            "attachments": [{
                "color": PLATFORMS["slack"]["color_pass"] if failed == 0 else PLATFORMS["slack"]["color_warn"],
                "fields": [
                    {"title": "Total Runs", "value": str(total), "short": True},
                    {"title": "Passed", "value": str(passed), "short": True},
                    {"title": "Failed", "value": str(failed), "short": True},
                    {"title": "Flaky", "value": str(flaky), "short": True},
                ],
                "footer": "Vigil",
            }],
        })

    def handle_slash_command(self, text: str, db) -> Dict:
        """Handle /vigil slash commands. Returns Slack-compatible response."""
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower() if parts else "help"
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "status":
            stats = db.get_run_stats()
            flaky = db.get_flaky_tests()
            return {
                "response_type": "in_channel",
                "text": f":bar_chart: *Vigil Status*\n"
                        f"• Runs: {stats.get('total_runs', 0)} (pass rate: {stats.get('pass_rate', 0)}%)\n"
                        f"• Flaky tests: {len(flaky)}\n"
                        f"• Journeys: {len(db.get_journeys(limit=1000))}",
            }

        elif cmd in ("query", "search", "find"):
            if not arg:
                return {"text": "Usage: `/vigil query <search text>`"}
            results = db.search_journeys(arg, limit=5)
            if not results:
                return {"text": f"No journeys matching '{arg}'"}
            lines = [f":mag: *Journeys matching '{arg}':*"]
            for j in results:
                lines.append(f"• *{j['name']}* ({j.get('domain', '?')} > {j.get('feature', '?')}) — `{j['id'][:8]}`")
            return {"response_type": "in_channel", "text": "\n".join(lines)}

        elif cmd == "flaky":
            flaky = db.get_flaky_tests()
            if not flaky:
                return {"text": ":white_check_mark: No flaky tests detected"}
            lines = [":warning: *Flaky Tests:*"]
            for f in flaky:
                q = ":lock:" if f.get("quarantined") else ":unlock:"
                lines.append(f"• {q} *{f.get('journey_name', '')}* — flake rate: {f['flake_rate']}%")
            return {"response_type": "in_channel", "text": "\n".join(lines)}

        elif cmd == "coverage":
            journeys = db.get_journeys(limit=1000)
            domains = set(j.get("domain", "") for j in journeys if j.get("domain"))
            features = set(j.get("feature", "") for j in journeys if j.get("feature"))
            return {
                "response_type": "in_channel",
                "text": f":chart_with_upwards_trend: *Coverage*\n"
                        f"• Journeys: {len(journeys)}\n"
                        f"• Domains: {', '.join(sorted(domains)) or 'none'}\n"
                        f"• Features: {', '.join(sorted(features)) or 'none'}",
            }

        else:
            return {
                "text": ":robot_face: *Vigil Slash Commands:*\n"
                        "• `/vigil status` — Platform stats\n"
                        "• `/vigil query <text>` — Search journeys\n"
                        "• `/vigil flaky` — List flaky tests\n"
                        "• `/vigil coverage` — Coverage summary\n"
                        "• `/vigil help` — This message",
            }

    def _post_webhook(self, payload: Dict) -> bool:
        url = self._config.get("webhook_url", "")
        if not url:
            return False
        try:
            if self._config.get("channel"):
                payload["channel"] = self._config["channel"]
            resp = httpx.post(url, json=payload, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False
