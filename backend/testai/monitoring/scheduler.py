"""Monitor scheduler — periodic test execution with webhook alerts."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class MonitorScheduler:
    """Lightweight in-process scheduler for periodic test monitors.

    Uses a background thread that wakes every 60s to check which monitors
    are due based on their simplified interval (parsed from cron_expr).
    """

    def __init__(self, db=None):
        self._db = db
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

    def start(self, db) -> None:
        if self._running:
            return
        self._db = db
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="vigil-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def _loop(self) -> None:
        self._stop_event.wait(timeout=10)  # initial delay before first tick
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:
                logger.warning("Monitor scheduler tick error", exc_info=True)
            self._stop_event.wait(timeout=60)

    def _tick(self) -> None:
        if not self._db:
            return
        monitors = self._db.get_monitors(limit=200)
        now = datetime.now(timezone.utc)

        for mon in monitors:
            if not mon.get("enabled"):
                continue
            interval_seconds = self._parse_interval(mon.get("cron_expr", "0 */6 * * *"))
            last_run = mon.get("last_run_at")
            if last_run:
                try:
                    last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                    elapsed = (now - last_dt).total_seconds()
                    if elapsed < interval_seconds:
                        continue
                except Exception:
                    pass

            self._execute_monitor(mon)

    def _parse_interval(self, cron_expr: str) -> int:
        """Parse simplified cron to interval seconds. Supports common patterns."""
        parts = cron_expr.strip().split()
        if len(parts) >= 5:
            hour_part = parts[1]
            if hour_part.startswith("*/"):
                try:
                    return int(hour_part[2:]) * 3600
                except ValueError:
                    pass
            min_part = parts[0]
            if min_part.startswith("*/"):
                try:
                    return int(min_part[2:]) * 60
                except ValueError:
                    pass
        return 6 * 3600  # default: every 6 hours

    def _execute_monitor(self, mon: Dict) -> None:
        """Run the monitored test and handle results."""
        monitor_id = mon["id"]
        monitor_type = mon.get("monitor_type", "journey")
        target_id = mon["target_id"]
        base_url = mon.get("base_url", "")

        now_iso = datetime.now(timezone.utc).isoformat()
        passed = False
        error_msg = ""

        try:
            if monitor_type == "journey":
                passed, error_msg = self._run_journey_check(target_id, base_url, mon)
            elif monitor_type == "api":
                passed, error_msg = self._run_api_check(target_id)
            elif monitor_type == "url":
                passed, error_msg = self._run_url_check(target_id)
        except Exception as e:
            error_msg = str(e)[:500]

        status = "passed" if passed else "failed"
        self._db.update_monitor(monitor_id, {"last_run_at": now_iso, "last_status": status})

        if not passed:
            alert = {
                "id": str(uuid.uuid4()),
                "monitor_id": monitor_id,
                "alert_type": "failure",
                "message": f"Monitor '{mon.get('name', monitor_id)}' failed: {error_msg[:300]}",
            }
            self._db.insert_alert(alert)

            webhook = mon.get("webhook_url", "")
            if webhook:
                self._send_webhook(webhook, mon, status, error_msg)

    def _run_journey_check(self, journey_id: str, base_url: str, mon: Dict) -> tuple:
        """Quick health check — verify journey exists and URL is reachable."""
        journey = self._db.get_journey_with_steps(journey_id)
        if not journey:
            return False, f"Journey {journey_id} not found"
        if base_url:
            try:
                resp = httpx.get(base_url, timeout=15, follow_redirects=True)
                if resp.status_code >= 500:
                    return False, f"URL returned {resp.status_code}"
            except Exception as e:
                return False, f"URL unreachable: {e}"
        return True, ""

    def _run_api_check(self, test_id: str) -> tuple:
        """Execute an API test from the api_tests table."""
        test = self._db.get_api_test(test_id)
        if not test:
            return False, f"API test {test_id} not found"
        from testai.api_testing.runner import APITestRunner
        runner = APITestRunner(timeout=15)
        result = runner.run_test(test)
        if result["passed"]:
            return True, ""
        return False, result.get("error_message", f"Status {result.get('status_code', 0)}")

    def _run_url_check(self, url: str) -> tuple:
        """Simple uptime check — verify URL returns 2xx."""
        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            if 200 <= resp.status_code < 400:
                return True, ""
            return False, f"HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)[:300]

    def _send_webhook(self, url: str, mon: Dict, status: str, error: str) -> None:
        try:
            payload = {
                "monitor": mon.get("name", mon["id"]),
                "status": status,
                "error": error[:500],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": mon.get("monitor_type", "journey"),
            }
            httpx.post(url, json=payload, timeout=10)
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            logger.warning("Webhook delivery failed for %s: %s", url, e)
