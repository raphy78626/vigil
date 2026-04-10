"""Replay API: /api/journeys/{id}/replay, /api/replay/batch."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from testai import state
from testai.auth import get_auth_for_url, _domain_from_url
from testai.models.journey import Journey
from testai.routes.helpers import build_journey

router = APIRouter()


# ---------------------------------------------------------------------------
# Vision-based coordinate healing endpoint
# ---------------------------------------------------------------------------

class VisionHealRequest(BaseModel):
    screenshot_b64: str
    description: str
    action_type: str = "click"
    viewport: dict = {"width": 1280, "height": 720}


@router.post("/api/heal/vision")
async def vision_heal(req: VisionHealRequest):
    """Send screenshot to vision LLM and return (x, y) click coordinates."""
    from testai.healing.vision_healer import locate_element

    loop = asyncio.get_event_loop()
    coord = await loop.run_in_executor(
        None,
        locate_element,
        state.llm,
        req.screenshot_b64,
        req.description,
        req.action_type,
        req.viewport.get("width", 1280),
        req.viewport.get("height", 720),
    )

    if coord is None or coord.confidence < 0.1:
        return {"x": 0, "y": 0, "confidence": 0.0, "reasoning": "not found"}

    return {
        "x": coord.x,
        "y": coord.y,
        "confidence": coord.confidence,
        "reasoning": coord.reasoning,
    }


class ReplayRequest(BaseModel):
    base_url: str = ""
    headed: bool = False
    env_vars: dict = {}
    auto_heal: bool = True
    max_heal_attempts: int = 2
    browser: str = "chromium"
    device: str = ""
    visual_regression: bool = False


class BatchReplayRequest(BaseModel):
    journey_ids: List[str]
    base_url: str = ""
    browser: str = "chromium"
    device: str = ""
    auto_heal: bool = True
    visual_regression: bool = False


async def _stream_replay(
    journey: Journey,
    base_url: str,
    headed: bool,
    env_vars: dict,
    auto_heal: bool = True,
    max_heal_attempts: int = 2,
    browser: str = "chromium",
    device: str = "",
    device_profile: dict = None,
    do_visual_regression: bool = False,
) -> AsyncGenerator[str, None]:
    """Run test with auto-healing, cross-browser, mobile emulation, and visual regression.
    Streams progress as SSE."""
    import base64
    import re as _re

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    collected_screenshots: List[dict] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        screenshot_dir = tmp / "screenshots"
        screenshot_dir.mkdir()

        test_code = state.playwright_exporter.export(journey)
        conftest_code = state.playwright_exporter.export_conftest(journey)

        (tmp / "conftest.py").write_text(conftest_code)
        (tmp / "test_replay.py").write_text(test_code)

        python = sys.executable
        _m = _re.search(r'get\("BASE_URL",\s*"([^"]+)"', conftest_code)
        default_origin = _m.group(1) if _m else "http://localhost"

        cmd = [
            python,
            "-m",
            "pytest",
            "test_replay.py",
            "-v",
            "-s",
            "--tb=short",
            "--no-header",
            "--base-url",
            base_url or default_origin,
            "--browser",
            browser,
        ]
        if headed:
            cmd += ["--headed", "--slowmo", "300"]

        auth_path = get_auth_for_url(base_url) if base_url else None

        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "SCREENSHOT_DIR": str(screenshot_dir),
            **env_vars,
        }
        if device_profile:
            env["VIGIL_DEVICE_WIDTH"] = str(device_profile.get("width", 390))
            env["VIGIL_DEVICE_HEIGHT"] = str(device_profile.get("height", 844))
            env["VIGIL_DEVICE_SCALE"] = str(device_profile.get("device_scale_factor", 2))
            env["VIGIL_DEVICE_UA"] = device_profile.get("user_agent", "")

        if auth_path and "STORAGE_STATE" not in env_vars:
            import shutil

            local_auth = tmp / "auth.json"
            shutil.copy2(auth_path, local_auth)
            env["STORAGE_STATE"] = str(local_auth)

        yield f"data: {json.dumps({'type': 'start', 'cmd': ' '.join(cmd), 'browser': browser, 'device': device})}\n\n"

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=tmpdir,
            env=env,
        )

        step_count = 0
        error_msg = ""
        full_output = []
        console_errors: list = []
        network_failures: list = []
        api_calls: list = []
        step_timings: dict = {}
        web_vitals: dict = {}
        vision_healed = False
        vision_heal_count = 0
        soft_results = {"passed": 0, "failed": 0, "skipped": 0}

        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()

            if "__SCREENSHOT__:" in line:
                fname = line.split("__SCREENSHOT__:")[1].strip()
                spath = screenshot_dir / fname
                if spath.exists():
                    b64 = base64.b64encode(spath.read_bytes()).decode()
                    collected_screenshots.append({"name": fname, "data": b64})
                    yield f"data: {json.dumps({'type': 'screenshot', 'name': fname, 'data': b64})}\n\n"
                continue

            if "__STEP_TIMING__:" in line:
                parts = line.split("__STEP_TIMING__:")[1].strip().split(":")
                if len(parts) >= 2:
                    try:
                        step_timings[parts[0]] = int(parts[1])
                    except ValueError:
                        pass
                continue

            if "__WEB_VITALS__:" in line:
                try:
                    web_vitals = json.loads(line.split("__WEB_VITALS__:")[1].strip())
                    yield f"data: {json.dumps({'type': 'web_vitals', 'data': web_vitals})}\n\n"
                except (json.JSONDecodeError, IndexError):
                    pass
                continue

            if "__CONSOLE_ERROR__:" in line:
                console_errors.append(line.split("__CONSOLE_ERROR__:", 1)[1].strip())
            elif "__NET_FAIL__:" in line:
                network_failures.append(line.split("__NET_FAIL__:", 1)[1].strip())
            elif "__API_CALL__:" in line:
                api_calls.append(line.split("__API_CALL__:", 1)[1].strip())
                full_output.append(line)
                continue

            full_output.append(line)

            step_m = _re.search(r"Step (\d+)/(\d+)", line)
            if step_m:
                step_count = int(step_m.group(1))

            if "[healed] vision click" in line or "[healed] vision fill" in line:
                vision_healed = True
                vision_heal_count += 1
                yield f"data: {json.dumps({'type': 'vision_heal', 'count': vision_heal_count})}\n\n"

            if "__SOFT_RESULTS__:" in line:
                try:
                    parts = line.split("__SOFT_RESULTS__:")[1].strip().split(",")
                    for p in parts:
                        k, v = p.split("=")
                        soft_results[k.strip()] = int(v.strip())
                    yield f"data: {json.dumps({'type': 'soft_results', 'data': soft_results})}\n\n"
                except (ValueError, IndexError):
                    pass

            if "[SOFT FAIL]" in line:
                yield f"data: {json.dumps({'type': 'soft_fail', 'text': line[:300]})}\n\n"

            if "[skip]" in line:
                yield f"data: {json.dumps({'type': 'step_skipped', 'text': line[:200]})}\n\n"

            if "FAILED" in line or "Error" in line:
                error_msg = line[:300]

            yield f"data: {json.dumps({'type': 'line', 'text': line})}\n\n"

        await proc.wait()

        heal_attempt = 0
        current_code = test_code
        healed = False

        _llm_status = state.llm.get_status()
        _use_cloud = _llm_status["has_key"] and _llm_status["provider"] != "ollama"
        _healer_available = _use_cloud or state.ollama_healer.available()

        from testai.healing.ollama_healer import _classify_error as _clf

        _test_output_text = "\n".join(full_output)
        _failure_class = _clf(_test_output_text) if proc.returncode != 0 else ""

        if _failure_class == "auth_redirect":
            _auth_domain = _domain_from_url(base_url) if base_url else "this domain"
            _empty = json.dumps({'type': 'line', 'text': ''})
            _auth_msg = json.dumps({'type': 'line', 'text': '  \u2717 Auth required \u2014 test redirected to login page'})
            _no_auth = json.dumps({'type': 'line', 'text': f'    No auth.json found for {_auth_domain}.'})
            _fix_hint = json.dumps({'type': 'line', 'text': '    Fix: use the Auth tab to generate credentials, then re-run.'})
            _heal_skip = json.dumps({'type': 'heal_fail', 'attempt': 0, 'reason': f'Auth required for {_auth_domain} \u2014 skipping heal loop'})
            yield f"data: {_empty}\n\n"
            yield f"data: {_auth_msg}\n\n"
            yield f"data: {_no_auth}\n\n"
            yield f"data: {_fix_hint}\n\n"
            yield f"data: {_heal_skip}\n\n"

        if _failure_class == "wrong_element":
            _empty = json.dumps({'type': 'line', 'text': ''})
            _wrong_el = json.dumps({'type': 'line', 'text': '  \u26a0 Wrong element \u2014 selector resolved to a non-fillable element (likely on wrong page)'})
            _auto_heal = json.dumps({'type': 'line', 'text': '    Auto-healer will try to fix navigation/auth flow...'})
            yield f"data: {_empty}\n\n"
            yield f"data: {_wrong_el}\n\n"
            yield f"data: {_auto_heal}\n\n"

        while (
            proc.returncode != 0
            and auto_heal
            and heal_attempt < max_heal_attempts
            and _healer_available
            and _failure_class != "auth_redirect"
        ):
            heal_attempt += 1
            yield f"data: {json.dumps({'type': 'heal_start', 'attempt': heal_attempt, 'max': max_heal_attempts})}\n\n"
            yield f"data: {json.dumps({'type': 'line', 'text': ''})}\n\n"
            _heal_msg = json.dumps({'type': 'line', 'text': f'\U0001f527 Auto-healing \u2014 attempt {heal_attempt} of {max_heal_attempts}...'})
            yield f"data: {_heal_msg}\n\n"

            test_output = "\n".join(full_output)
            loop = asyncio.get_event_loop()

            if _use_cloud:
                from testai.healing.ollama_healer import (
                    _parse_failure,
                    _build_prompt,
                    _extract_code,
                    _SYSTEM_PROMPT,
                    HealResult as HR,
                )

                def _cloud_heal():
                    ctx = _parse_failure(test_output, current_code)
                    if not ctx:
                        return HR(False, "", "Could not parse failure", state.llm.model, 1)
                    prompt = _build_prompt(ctx)

                    images = []
                    if state.llm.has_vision:
                        import glob as _glob

                        for sp in sorted(_glob.glob(str(screenshot_dir / "*.png")))[-3:]:
                            images.append(base64.b64encode(Path(sp).read_bytes()).decode())

                    resp = state.llm.ask(
                        prompt, system=_SYSTEM_PROMPT, max_tokens=2048, images=images or None
                    )
                    if not resp:
                        return HR(False, "", "No response from LLM", state.llm.model, 1)
                    patched = _extract_code(resp, current_code)
                    if not patched:
                        return HR(False, "", "Could not extract valid code", state.llm.model, 1)
                    return HR(True, patched, f"Auto-healed step {ctx.step_number}", state.llm.model, 1)

                heal_result = await loop.run_in_executor(None, _cloud_heal)
            else:
                heal_result = await loop.run_in_executor(
                    None, state.ollama_healer.heal, test_output, current_code
                )

            if not heal_result or not heal_result.success:
                _fail_msg = json.dumps({'type': 'line', 'text': '   \u2717 Could not auto-heal this step'})
                _fail_evt = json.dumps({'type': 'heal_fail', 'attempt': heal_attempt, 'reason': 'auto-heal unsuccessful'})
                yield f"data: {_fail_msg}\n\n"
                yield f"data: {_fail_evt}\n\n"
                break

            _fix_msg = json.dumps({'type': 'line', 'text': '   \u2713 Fix generated \u2014 re-running test...'})
            yield f"data: {_fix_msg}\n\n"

            current_code = heal_result.patched_code
            (tmp / "test_replay.py").write_text(current_code)

            for f in screenshot_dir.iterdir():
                f.unlink()

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=tmpdir,
                env=env,
            )

            step_count = 0
            error_msg = ""
            full_output = []

            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()

                if "__SCREENSHOT__:" in line:
                    fname = line.split("__SCREENSHOT__:")[1].strip()
                    spath = screenshot_dir / fname
                    if spath.exists():
                        b64 = base64.b64encode(spath.read_bytes()).decode()
                        yield f"data: {json.dumps({'type': 'screenshot', 'name': fname, 'data': b64})}\n\n"
                    continue

                full_output.append(line)

                step_m = _re.search(r"Step (\d+)/(\d+)", line)
                if step_m:
                    step_count = int(step_m.group(1))

                if "FAILED" in line or "Error" in line:
                    error_msg = line[:300]

                yield f"data: {json.dumps({'type': 'line', 'text': line})}\n\n"

            await proc.wait()

            if proc.returncode == 0:
                healed = True
                yield f"data: {json.dumps({'type': 'heal_success', 'attempt': heal_attempt})}\n\n"
                _pass_msg = json.dumps({'type': 'line', 'text': '   \u2713 Test passed after auto-heal'})
                yield f"data: {_pass_msg}\n\n"
            else:
                full_output = [line async for line in proc.stdout] if proc.stdout else full_output
                _failure_class = _clf("\n".join(str(l) for l in full_output))
                if _failure_class == "auth_redirect":
                    _auth_redir = json.dumps({'type': 'line', 'text': '  Auth redirect detected after heal \u2014 stopping heal loop'})
                    yield f"data: {_auth_redir}\n\n"
                    break

        finished_at = datetime.now(timezone.utc).isoformat()
        passed = proc.returncode == 0
        duration = int(
            (datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)).total_seconds()
            * 1000
        )

        total_m = _re.search(r"All (\d+) steps", current_code)
        total_steps = int(total_m.group(1)) if total_m else step_count

        try:
            state.db.insert_test_run(
                {
                    "id": run_id,
                    "journey_id": journey.id,
                    "base_url": base_url or default_origin,
                    "passed": passed,
                    "total_steps": total_steps,
                    "passed_steps": step_count if passed else step_count,
                    "duration_ms": duration,
                    "exit_code": proc.returncode,
                    "headed": headed,
                    "error_message": "" if passed else error_msg,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "healed": healed or vision_healed,
                    "heal_attempts": heal_attempt,
                    "vision_healed": vision_healed,
                    "vision_heal_count": vision_heal_count,
                    "console_errors": console_errors[:100],
                    "network_failures": network_failures[:100],
                    "api_calls": api_calls[:200],
                    "step_timings": step_timings,
                    "web_vitals": web_vitals,
                }
            )
        except Exception as _e:
            print(f"[warn] failed to record test run {run_id}: {_e}", file=sys.stderr)

        vr_results = []
        if do_visual_regression and collected_screenshots:
            try:
                vr_results = state.visual_regression.process_replay_screenshots(
                    state.db, journey.id, run_id, collected_screenshots
                )
                vr_failed = [r for r in vr_results if not r["passed"]]
                yield f"data: {json.dumps({'type': 'visual_regression', 'results': vr_results, 'regressions': len(vr_failed)})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'line', 'text': f'Visual regression error: {e}'})}\n\n"

        _done_payload = {
            'type': 'done',
            'exit_code': proc.returncode,
            'passed': passed or (soft_results['failed'] == 0 and soft_results['passed'] > 0),
            'run_id': run_id,
            'healed': healed or vision_healed,
            'heal_attempts': heal_attempt,
            'browser': browser,
            'device': device,
            'visual_regressions': len([r for r in vr_results if not r.get('passed', True)]),
            'console_error_count': len(console_errors),
            'network_failure_count': len(network_failures),
            'api_call_count': len(api_calls),
            'step_timings': step_timings,
            'web_vitals': web_vitals,
            'vision_healed': vision_healed,
            'vision_heal_count': vision_heal_count,
            'soft_results': soft_results,
        }
        yield f"data: {json.dumps(_done_payload)}\n\n"


@router.post("/api/journeys/{journey_id}/replay")
async def replay_journey(journey_id: str, req: ReplayRequest):
    """Run the captured journey as a live Playwright test and stream results."""
    journey_data = state.db.get_journey_with_steps(journey_id)
    if not journey_data:
        raise HTTPException(status_code=404, detail="Journey not found")
    journey = build_journey(journey_id, journey_data)

    browser = req.browser if req.browser in state.SUPPORTED_BROWSERS else "chromium"
    device_profile = state.DEVICE_PROFILES.get(req.device) if req.device else None

    return StreamingResponse(
        _stream_replay(
            journey,
            req.base_url,
            req.headed,
            req.env_vars,
            auto_heal=req.auto_heal,
            max_heal_attempts=req.max_heal_attempts,
            browser=browser,
            device=req.device,
            device_profile=device_profile,
            do_visual_regression=req.visual_regression,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/replay/batch")
async def batch_replay(req: BatchReplayRequest):
    """Run multiple journeys in parallel. Returns batch_id for tracking."""
    batch_id = str(uuid.uuid4())[:8]
    results = []

    for jid in req.journey_ids:
        journey_data = state.db.get_journey_with_steps(jid)
        if not journey_data:
            results.append({"journey_id": jid, "status": "not_found"})
            continue

        journey = build_journey(jid, journey_data)
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                screenshot_dir = tmp / "screenshots"
                screenshot_dir.mkdir()

                test_code = state.playwright_exporter.export(journey)
                conftest_code = state.playwright_exporter.export_conftest(journey)
                (tmp / "conftest.py").write_text(conftest_code)
                (tmp / "test_replay.py").write_text(test_code)

                import re as _re

                _m = _re.search(r'get\("BASE_URL",\s*"([^"]+)"', conftest_code)
                default_origin = _m.group(1) if _m else "http://localhost"

                cmd = [
                    sys.executable,
                    "-m",
                    "pytest",
                    "test_replay.py",
                    "-v",
                    "-s",
                    "--tb=short",
                    "--no-header",
                    "--base-url",
                    req.base_url or default_origin,
                    "--browser",
                    req.browser,
                ]
                env = {
                    **os.environ,
                    "PYTHONUNBUFFERED": "1",
                    "SCREENSHOT_DIR": str(screenshot_dir),
                }
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=tmpdir,
                    env=env,
                )
                await proc.wait()
                finished_at = datetime.now(timezone.utc).isoformat()
                duration = int(
                    (
                        datetime.fromisoformat(finished_at)
                        - datetime.fromisoformat(started_at)
                    ).total_seconds()
                    * 1000
                )

                state.db.insert_test_run(
                    {
                        "id": run_id,
                        "journey_id": jid,
                        "base_url": req.base_url or default_origin,
                        "passed": proc.returncode == 0,
                        "duration_ms": duration,
                        "exit_code": proc.returncode,
                        "headed": False,
                        "error_message": "",
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "healed": False,
                        "heal_attempts": 0,
                    }
                )
                results.append(
                    {
                        "journey_id": jid,
                        "run_id": run_id,
                        "passed": proc.returncode == 0,
                        "duration_ms": duration,
                        "browser": req.browser,
                    }
                )
        except Exception as e:
            results.append({"journey_id": jid, "status": "error", "error": str(e)[:200]})

    return {"batch_id": batch_id, "results": results, "total": len(results)}
