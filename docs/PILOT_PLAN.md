# Vigil: 90-Day Pilot Plan

**Start date:** 2026-09-11  
**Kill metric:** ≥3 journeys/team/week captured, reviewed in <10 min/day, ≥1 exported Playwright suite running in pilot team's CI.  
**Decision rule:** ≥2 of 3+ pilots hit the bar by week 12 → double down. Otherwise stop or reposition.

---

## Positioning

**Thesis:** Passively capture your team's own behavior as they use the app → AI clusters it into named journeys → export self-healing Playwright tests. Your team records itself; you don't write tests, and nobody watches your users without consent.

**Tagline:** *"Tests from what your team actually did — you don't write them, and nobody watches your users without consent."*

**vs. Meticulous / Octomind (same thesis, both defunct):**
- **Local-first + open-source trust** — closed SaaS ingesting production user sessions. Vigil runs on the team's own machine with inspectable, MIT-licensed code. Trust is the wedge.
- **Internal-team consent wedge** — they captured production users (Chrome Web Store Limited Use / GDPR quicksand). Vigil captures only consenting team members recording themselves; different regulatory floor entirely.
- **Price/distribution undercut** — their contracts were $20–50K/yr enterprise sales. Vigil: free solo, $40/seat/month team tier, bottom-up adoption.

**Open-core line:**
| Tier | Price | Includes |
|------|-------|----------|
| Free / open-source | $0 | Full solo value: capture, local pipeline, journey naming, Playwright export |
| Team | $40/seat/mo | Shared journey graph, Slack/eng-leader reports, SSO/RBAC, CI dashboards |

---

## P0 Fix Checklist

These must be done before any external pilot. Internal company pilot can start after Wave 1 (trust), as long as Wave 2 is scoped to weeks 2–4.

### Wave 1: Trust (weeks 1–2) — do before any pilot

- [ ] **C0: Extension consolidation** — Make `extension/src/*.ts` the single source of truth; one build to `extension/dist/`; update `manifest.json` to load from `dist/`; delete diverged `extension/*.js` and `extension/src/*.js` copies. Keep `getVisibleText` but pipe its output through `redactPII`.
- [ ] **C1: Auth enforcement** — Add `require_auth` / `require_role` FastAPI dependencies in `backend/testai/team/auth.py`; apply to all 112 endpoints via router-level `dependencies=` in `backend/testai/server.py`; exempt only `/api/team/login`, `/`, `/docs`, `/redoc`, `/openapi.json`, `/static/*`. Covered endpoints include: `GET /api/auth/download/{domain}` (`routes/auth_routes.py:59`), `GET /api/team/users` (`routes/misc.py:343`), `POST /api/ingest/file` (`routes/ingest.py:116`), `WS /ws/events` (`routes/ingest.py:147`).
- [ ] **C1b: Strip role from registration** — Remove `role` field from `RegisterRequest` at `routes/misc.py:293`; always create "member"; add separate admin-only `POST /api/team/users/{id}/role` endpoint with `require_role("admin")`.
- [ ] **C1c: Kill default admin/admin** — Move `team_auth.ensure_admin_exists()` from `state.py:54` to FastAPI `@app.on_event("startup")`; generate a random password on first run, print it once, and save to `~/.vigil/admin.passwd` (mode 0600).
- [ ] **C1d: Fix token security** — Remove `[:32]` truncation from `team/auth.py:98`; use full HMAC-SHA256 hex. Load secret from `VIGIL_SECRET_KEY` env or auto-generate to `~/.vigil/secret` (mode 0600, 32 random bytes hex); never fall back to the committed default string.
- [ ] **C2: Bind loopback** — `server.py:81`: change `host="0.0.0.0"` to `host=os.environ.get("VIGIL_HOST", "127.0.0.1")`; add a console warning when `VIGIL_HOST` is set to anything other than loopback: "⚠️  Binding to {host} — your API is reachable on the network."
- [ ] **C3: Drop `debugger` permission** — Remove `"debugger"` from `extension/manifest.json` and `extension/src/manifest.json`. It is requested but never used (`grep -r "chrome.debugger" extension/` → zero hits).
- [ ] **C4: Persist SW state on cold start** — Add top-level state restoration from `chrome.storage.local` in `extension/background.js` (not only in `onInstalled`). Gate event handling on the restore completing (Promise pattern, no top-level await needed). See `background.js:14-33`.
- [ ] **C4b: Fail closed on empty allowlist** — Change `handleCapturedEvent` at `background.js:120-127`: empty allowlist (no entries, or entries stripped to zero) → capture nothing, not everything. Support explicit `"all"` or `"*"` as opt-in wildcards.
- [ ] **C5: Unblock localhost for allowlisted sites** — Remove `'127.0.0.1', 'localhost'` from `NOISE_DOMAIN_PATTERNS` at `background.js:101`. Replace the self-recording guard with an exact-origin match: parse `state.backendUrl` and block only that origin. Add a note for users: "To also block the Vigil dashboard, add its port to your deny list in settings."

### Wave 2: Core validity (weeks 2–4)

- [ ] **SPA capture — MAIN world injection** — Add a second content script entry in `manifest.json` with `"world": "MAIN"` for the `pushState`/`replaceState` patch only (the isolated-world entry at `content.js:527-536` never intercepts real navigation). `content.js:540-544`: change `MutationObserver` to `subtree: true` on `document.body` (not `document.documentElement`) with 300 ms debounce.
- [ ] **Fix noise-pattern false positives** — `extension/content.js:29-42`: substring-match `'ad.'`, `'analytics.'`, `'pixel.'`, `'tracking.'` against hostname only (not full URL); use a regex anchored to hostname to avoid matching `broadcast.example.com` on `'ad.'`.
- [ ] **Server-side redaction at ingest** — Add a `_redact_event(event: dict) -> dict` function in `backend/testai/routes/ingest.py` that strips PII patterns from `url`, `page_title`, `href`, `text` fields before persisting. Apply at `ingest_events`, `ingest_file`, and the WS handler.
- [ ] **Stop baking raw values into descriptions** — `backend/testai/cluster/pipeline_local.py:307-308`: replace `val = el.value or "text"` / `desc = f"Type '{val[:30]}' into {field_name}"` with a non-identifying description like `f"Fill {field_name}"`. The raw value is already captured in the step; the description doesn't need to repeat it.
- [ ] **Labeler uses local LLM default** — `backend/testai/cluster/labeler.py:51`: replace hardcoded `model = "gpt-4o-mini"` with `model = state.llm.model_id` (respecting the provider chosen in `backend/testai/llm/provider.py:117-121`).
- [ ] **Self-host Inter font** — `dashboard/index.html:7-9`: download Inter woff2 files to `dashboard/static/fonts/`; replace Google Fonts CDN links with local `@font-face` declarations. Eliminates the only phone-home from the local-first tool.
- [ ] **Lossless event flush** — Verify the extension doesn't lose buffered events on SW termination; implement an explicit flush-before-terminate handler if needed.

### Wave 3: Wire or delete (weeks 4–6)

- [ ] **Journey merge persistence** — `routes/journeys.py:97-118`: `state.journey_merger.merge(...)` result is returned but never written to DB. Add `state.db.save_journey(merged)` (or equivalent) after merge. Same for auto-merge.
- [ ] **Noise filter into ingest path** — Wire `state.noise_filter.filter(events)` into `routes/ingest.py` before clustering, or delete `NoiseFilter` and its standalone endpoints (`routes/misc.py:397-410`). It currently has zero call sites in the ingest path.
- [ ] **Credential vault: consume or delete** — `credentials/manager.py:91` `get_login_credential()` has zero call sites. Either wire it into `explorer/` and `replay.py` (so the vault actually feeds past login walls), or remove the credential manager endpoints and document the feature as "planned."
- [ ] **Delete dead QueryEngine** — `query/engine.py` defines `class QueryEngine` with zero call sites. Remove or add a route that exposes it; don't keep dead code that the feature table claims works.
- [ ] **Honest feature dict** — `routes/misc.py:509-528`: `"journey_merging": True` when it doesn't persist, `"noise_filtering": True` when it's not in the ingest path, `"credential_manager": True` when `get_login_credential` has no call sites — all wrong. Set these to `False` or `"partial"` until Wave 3 is complete.
- [ ] **CI + healing tests** — Add GitHub Actions workflow (`backend/ci.yml`): `pip install -r requirements.txt && python -m pytest tests/ -v`. Add tests for `healing/ollama_healer.py` and `healing/vision_healer.py` (currently zero coverage).

---

## Pilot Protocol

### Consent & privacy posture

The pilot runs in **team-records-itself mode**: the extension is installed by consenting team members who record themselves using their own app. No production users are captured. Include this language in onboarding:

> "Vigil captures your own browsing of [App Name] while you're logged in as a tester. It records clicks, page loads, and form fills (input values are redacted). Data stays on your machine; nothing is sent to third parties. You can stop capture at any time via the extension icon."

### Security sign-off packet (for internal company pilot)

Provide the security team with:
1. Data flow diagram: browser → `127.0.0.1:8000` → SQLite at `~/.vigil/` (local only)
2. Auth model: HMAC-SHA256 tokens, loopback bind, role-based endpoint protection
3. Redaction spec: input values masked at capture; URLs/titles stored locally; cloud LLM is explicit opt-in
4. Network egress: none (local-only default; Google Fonts removed by Wave 2)

### Onboarding checklist (per pilot team)

- [ ] Install sideloaded extension (unpacked, from `extension/dist/` after C0)
- [ ] Configure backend URL in extension popup (should be `http://127.0.0.1:8000`)
- [ ] Add the pilot app's domain to the allowlist in extension settings
- [ ] Run the backend: `cd backend && python -m uvicorn testai.server:app --port 8000`
- [ ] Browse the app for 20 minutes (normal work, not scripted)
- [ ] Click "Flush to backend" in the extension popup
- [ ] Open dashboard at `http://localhost:8000` → verify ≥1 named journey appeared
- [ ] Export one journey as Playwright → drop into their project's `e2e/` directory → run `npx playwright test`

### Weekly pilot check-in

Collect per team per week:
- Journeys captured (count)
- Minutes spent reviewing in Vigil dashboard
- Playwright suites exported + added to CI (count)
- Top friction point (free text)

---

## Kill / Double-down Decision Rule

**Measurement window:** weeks 8–12 of pilot.  
**Go signal (double down):** ≥2 of the first 3 pilots hit ALL THREE:
- ≥3 journeys captured per team per week (averaged over 4 weeks)
- <10 min/day spent reviewing in the dashboard
- ≥1 Playwright suite exported and running in the team's actual CI

**Stop / reposition signal:** fewer than 2 pilots hit the bar.  
What "reposition" means: if journeys are captured but CI export isn't sticking, the product is a journey discovery tool, not a test generation tool — price and market accordingly.

---

## Launch Plan (week ~12)

**Prerequisite:** Chrome Web Store submission approved (submit week 10 with Limited Use disclosure and privacy policy).

**Primary: Show HN** — headline: *"Vigil: your team records itself, AI writes the E2E tests (open source, local-first)"*. Body: demo GIF showing 3 journeys auto-generated from 15 min of browsing. Link to GitHub + live demo.

**Echo (same day/week):**
- Product Hunt: category Engineering Tools, tagline same
- r/QualityAssurance + dev.to post: *"We built a Playwright test generator that needs zero authoring — here's what actually works and what doesn't"*

**Metric to declare success at launch:** ≥3 GitHub stars/day in the first week, ≥1 inbound pilot request from a team we don't already know.

---

## Open Questions for Post-Launch (out of scope for 90 days)

- Firefox extension port
- Production-user capture mode (requires consent tooling, DPA, GDPR work — separate milestone)
- Team tier billing infrastructure ($40/seat; likely Stripe + a simple per-seat license check)
- Hosted Vigil cloud (relay events to a shared server, share journey graphs across org)
