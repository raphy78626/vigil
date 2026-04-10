"""Validate Playwright test export + replay across all captured journeys.

Exports each journey, runs it with pytest, and records pass/fail + timing.
Produces a markdown summary table.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

API = "http://localhost:8000"
VENV_PYTHON = str(Path(__file__).resolve().parent / "venv" / "bin" / "python")
TIMEOUT_PER_TEST = 120  # seconds


def get_journeys():
    resp = httpx.get(f"{API}/api/journeys", timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_journey_detail(jid: str):
    resp = httpx.get(f"{API}/api/journeys/{jid}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def export_playwright(jid: str) -> str:
    resp = httpx.get(f"{API}/api/journeys/{jid}/export/playwright", timeout=30)
    resp.raise_for_status()
    return resp.text


def get_base_url(journey: dict) -> str:
    steps = journey.get("steps", [])
    for s in steps:
        url = s.get("url", "")
        if url:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def run_test(test_code: str, base_url: str) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test_replay.py")
        with open(test_file, "w") as f:
            f.write(test_code)

        cmd = [
            VENV_PYTHON, "-m", "pytest", test_file,
            "-v", "-s", "--tb=short", "--no-header",
            f"--base-url={base_url}",
        ]

        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=TIMEOUT_PER_TEST, cwd=tmpdir,
            )
            elapsed = time.time() - start
            passed = result.returncode == 0
            output = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            passed = False
            output = f"TIMEOUT after {TIMEOUT_PER_TEST}s"

        # Extract step progress
        last_step = "0/0"
        for line in output.splitlines():
            if "Step " in line and "/" in line:
                import re
                m = re.search(r"Step\s+(\d+/\d+)", line)
                if m:
                    last_step = m.group(1)

        # Extract error type
        error_summary = ""
        if not passed:
            for line in output.splitlines():
                if "TimeoutError" in line or "Error:" in line:
                    error_summary = line.strip()[:120]
                    break

        return {
            "passed": passed,
            "elapsed": round(elapsed, 1),
            "last_step": last_step,
            "error": error_summary,
            "output": output[-2000:],
        }


def main():
    print("=" * 70)
    print("  Vigil Replay Validation — Real App Pass Rates")
    print("=" * 70)

    journeys = get_journeys()
    results = []

    for j in journeys:
        jid = j["id"]
        name = j["name"]
        detail = get_journey_detail(jid)
        steps = detail.get("steps", [])
        step_count = len(steps)
        base_url = get_base_url(detail)
        domain = urlparse(base_url).netloc if base_url else "unknown"

        if step_count == 0 or not base_url:
            print(f"\n  SKIP {name} — no steps or no URL")
            results.append({
                "name": name, "domain": domain, "steps": step_count,
                "passed": False, "elapsed": 0, "last_step": "0/0",
                "error": "No steps", "skipped": True,
            })
            continue

        print(f"\n  Testing: {name} ({domain}, {step_count} steps)")

        try:
            test_code = export_playwright(jid)
        except Exception as e:
            print(f"    EXPORT FAILED: {e}")
            results.append({
                "name": name, "domain": domain, "steps": step_count,
                "passed": False, "elapsed": 0, "last_step": "0/0",
                "error": f"Export failed: {e}", "skipped": False,
            })
            continue

        # Check if exported code compiles
        try:
            compile(test_code, "<test>", "exec")
        except SyntaxError as e:
            print(f"    SYNTAX ERROR in export: {e}")
            results.append({
                "name": name, "domain": domain, "steps": step_count,
                "passed": False, "elapsed": 0, "last_step": "0/0",
                "error": f"SyntaxError: {e}", "skipped": False,
            })
            continue

        r = run_test(test_code, base_url)
        status = "PASS" if r["passed"] else "FAIL"
        print(f"    {status} — {r['last_step']} in {r['elapsed']}s")
        if r["error"]:
            print(f"    Error: {r['error'][:100]}")

        results.append({
            "name": name, "domain": domain, "steps": step_count,
            "skipped": False, **r,
        })

    # Summary
    print("\n" + "=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)

    total = len([r for r in results if not r.get("skipped")])
    passed = len([r for r in results if r["passed"]])
    failed = total - passed
    skipped = len([r for r in results if r.get("skipped")])

    print(f"\n  Total: {total}  Passed: {passed}  Failed: {failed}  Skipped: {skipped}")
    if total > 0:
        print(f"  Pass rate: {passed/total*100:.0f}%")

    # Markdown table
    print("\n### Per-Journey Results\n")
    print("| Journey | Domain | Steps | Result | Progress | Time | Error |")
    print("|---------|--------|------:|--------|----------|-----:|-------|")
    for r in results:
        if r.get("skipped"):
            continue
        status = "Pass" if r["passed"] else "**FAIL**"
        err = r.get("error", "")[:60]
        print(f"| {r['name']} | {r['domain']} | {r['steps']} | {status} | {r['last_step']} | {r['elapsed']}s | {err} |")

    # Per-domain breakdown
    domains = {}
    for r in results:
        if r.get("skipped"):
            continue
        d = r["domain"]
        if d not in domains:
            domains[d] = {"total": 0, "passed": 0}
        domains[d]["total"] += 1
        if r["passed"]:
            domains[d]["passed"] += 1

    print("\n### Per-Domain Pass Rates\n")
    print("| Domain | Tests | Passed | Rate |")
    print("|--------|------:|-------:|-----:|")
    for d, v in sorted(domains.items()):
        rate = f"{v['passed']/v['total']*100:.0f}%" if v["total"] > 0 else "N/A"
        print(f"| {d} | {v['total']} | {v['passed']} | {rate} |")

    # Save results to JSON
    output_path = Path(__file__).resolve().parent / "validation_results.json"
    with open(output_path, "w") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": f"{passed/total*100:.0f}%" if total > 0 else "N/A",
            "results": results,
        }, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
