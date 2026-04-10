"""API test runner — execute REST API tests with assertion validation."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx


class APITestRunner:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def run_test(self, test: Dict) -> Dict:
        """Execute a single API test and validate assertions."""
        start = time.monotonic()
        try:
            response = self._make_request(test)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            body_text = response.text
            try:
                body_json = response.json()
            except Exception:
                body_json = None

            assertion_results = self._check_assertions(
                test.get("assertions", []), response, body_json, body_text
            )
            all_passed = all(a["passed"] for a in assertion_results) if assertion_results else True

            return {
                "id": str(uuid.uuid4()),
                "test_id": test["id"],
                "passed": all_passed and 200 <= response.status_code < 400,
                "status_code": response.status_code,
                "response_time_ms": elapsed_ms,
                "response_body": body_text[:10000],
                "assertion_results": assertion_results,
                "error_message": "",
            }
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {
                "id": str(uuid.uuid4()),
                "test_id": test["id"],
                "passed": False,
                "status_code": 0,
                "response_time_ms": elapsed_ms,
                "response_body": "",
                "assertion_results": [],
                "error_message": str(e)[:500],
            }

    def _make_request(self, test: Dict) -> httpx.Response:
        method = test.get("method", "GET").upper()
        url = test["url"]
        headers = test.get("headers", {})
        body = test.get("body", "")

        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            kwargs: Dict[str, Any] = {"headers": headers}
            if method in ("POST", "PUT", "PATCH") and body:
                if isinstance(body, (dict, list)):
                    kwargs["json"] = body
                else:
                    kwargs["content"] = str(body)
                    if "content-type" not in {k.lower() for k in headers}:
                        kwargs["headers"]["Content-Type"] = "application/json"

            return client.request(method, url, **kwargs)

    def _check_assertions(
        self, assertions: List[Dict], response: httpx.Response,
        body_json: Any, body_text: str
    ) -> List[Dict]:
        results = []
        for a in assertions:
            atype = a.get("type", "status_code")
            expected = a.get("expected")
            path = a.get("path", "")

            try:
                if atype == "status_code":
                    actual = response.status_code
                    passed = actual == int(expected)
                elif atype == "body_contains":
                    actual = body_text
                    passed = str(expected) in body_text
                elif atype == "json_path":
                    actual = self._resolve_json_path(body_json, path)
                    passed = str(actual) == str(expected)
                elif atype == "header":
                    actual = response.headers.get(path, "")
                    passed = str(expected) in str(actual)
                elif atype == "response_time_lt":
                    actual = response.elapsed.total_seconds() * 1000
                    passed = actual < float(expected)
                elif atype == "regex":
                    actual = body_text
                    passed = bool(re.search(str(expected), body_text))
                else:
                    actual = None
                    passed = False

                results.append({
                    "type": atype,
                    "expected": str(expected),
                    "actual": str(actual)[:500] if actual is not None else "",
                    "passed": passed,
                    "path": path,
                })
            except Exception as e:
                results.append({
                    "type": atype,
                    "expected": str(expected),
                    "actual": f"Error: {e}",
                    "passed": False,
                    "path": path,
                })

        return results

    def _resolve_json_path(self, obj: Any, path: str) -> Any:
        """Simple dot-notation JSON path resolver: 'data.items[0].name'"""
        if obj is None:
            return None
        parts = re.split(r'\.|\[|\]', path)
        current = obj
        for part in parts:
            if not part:
                continue
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current

    def run_batch(self, tests: List[Dict]) -> List[Dict]:
        """Run multiple API tests sequentially."""
        return [self.run_test(t) for t in tests]
