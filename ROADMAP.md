# Vigil Roadmap

## Current Status: Pilot-Ready v0.3 (Feb 2026)

The platform is **pilot-ready** with 98 API endpoints and 19 features validated across 4 web applications. All Phase 1.8 pilot-blocking items (9 features) have been implemented: Slack/Teams bot, Selenium export, noise filtering, multi-session merge, test suite generation, credential manager, rich event capture, and Shadow DOM support. Combined with v0.2's 11 capabilities (visual regression, cross-browser, etc.), zero gaps remain for the first external pilot.

---

## What's Done (Phase 1 MVP + Phase 1.5 Roadmap Items)

### Capture Agent (Chrome Extension v1.0 — Production)
- [x] Chrome Manifest V3 extension with content script injection
- [x] Click, input, change, submit, navigation, pageload event capture
- [x] 7 test-ID attributes: `data-testid`, `data-test`, `data-cy`, `data-qa`, `data-automation-id`, `data-e2e`, `data-test-id`
- [x] ARIA capture: `role`, `aria-label`, `aria-labelledby`, `aria-describedby`
- [x] Associated `<label>` text via `for=`, wrapping `<label>`, `aria-labelledby`
- [x] Rich metadata: `placeholder`, `name`, `title`, `href`, `className`
- [x] Interactive ancestor walk (clicks on SVG/span resolve to nearest button/link)
- [x] Stable CSS generation (class selectors preferred over nth-child, generated classes skipped)
- [x] PII auto-redaction (email, phone, card, SSN, passwords)
- [x] Domain allowlist filtering
- [x] IndexedDB local storage with domain index
- [x] JSON export for ingestion
- [x] Backend URL config + one-click flush to API
- [x] 30-min idle session rotation
- [x] `all_frames: true` for iframe capture
- [x] History API interception (`pushState`/`replaceState`) for SPA navigation

### Semantic Clustering Engine
- [x] Session segmentation (5-min gap / domain change)
- [x] Flow grouping by URL path and action sequence
- [x] Rule-based journey labeling (no API key required)
- [x] LLM-powered labeling via LiteLLM (Claude, GPT-4o)
- [x] **Fixed step-event mapping** — labeler now returns `event_indices` per step instead of assigning all events to all steps
- [x] Confidence scoring per journey
- [x] SQLite persistence with full metadata
- [x] Retry deduplication (removes failed form submission retries)
- [x] Distinguishes intentional repeated actions from retries

### AI Explorer (Autonomous Web Crawling)
- [x] LLM-powered autonomous agent crawls any URL
- [x] Discovers all user flows without human guidance
- [x] Tracks explored vs. unexplored elements to avoid loops
- [x] Handles off-domain navigation and blank pages
- [x] SSE streaming of exploration progress
- [x] Session management (start, stop, list, results)

### Dashboard & Query
- [x] Modern dark-mode web dashboard with glassmorphism aesthetic
- [x] Animated SVG hero section with interactive feature carousel
- [x] Feature tooltips for discoverability
- [x] Journey list with domain/feature filtering
- [x] Journey detail modal with step-by-step view
- [x] **AI-powered NL query** — LLM interprets questions with journey index context, keyword fallback
- [x] Coverage grid (domain x feature)
- [x] File upload for event ingestion

### Playwright Export & Replay (Production Grade)
- [x] Playwright test generation with self-healing selectors
- [x] Locator priority follows Playwright best practices: `get_by_role` > `get_by_label` > `aria-label` > CSS+text > `get_by_text` > `get_by_placeholder`
- [x] `networkidle` waits after every navigation (not just domcontentloaded)
- [x] Configurable timeout via `TESTAI_TIMEOUT` env var (default 15s)
- [x] `STORAGE_STATE` support in conftest for authenticated apps
- [x] Environment variable-based credentials (passwords never embedded)
- [x] App-agnostic replay against any Base URL
- [x] Live replay with SSE streaming (progress bar, logs, screenshots)
- [x] Headed mode (watch browser during replay)
- [x] Screenshot capture at every step via reusable `_shot()` helper
- [x] `select_option()` for native dropdown handling
- [x] `.first` locator for duplicate content resilience
- [x] `wait_for_url()` for click-triggered navigation (preserves query params)
- [x] UUID wildcarding for dynamic resource URLs
- [x] SVG stripping from CSS selectors
- [x] React ID handling (`#:rXX:` → `[id=':rXX:']` or skipped)
- [x] Navigation fallbacks (fragile click → `goto()` on timeout)
- [x] Progressive fill deduplication (keystroke-by-keystroke → single final value)
- [x] conftest.py export with `base_url`, `storage_state`, and browser context support

### Cypress Export (NEW)
- [x] `.cy.js` test generation from discovered journeys
- [x] Smart selectors: `data-testid` > `aria-label` > CSS+text > `cy.contains()`
- [x] Environment variable credentials via `Cypress.env()`
- [x] One-click export from dashboard alongside Playwright

### CI/CD Integration (NEW)
- [x] GitHub Actions workflow generation for Playwright
- [x] GitHub Actions workflow generation for Cypress
- [x] Scheduled runs via cron expression
- [x] Auth support via `AUTH_JSON` secret
- [x] Artifact/screenshot upload
- [x] Dynamic `BASE_URL` from secrets

### Journey Versioning & Diffing (NEW)
- [x] Auto-versioning on every event ingest
- [x] Step-level content hashing for change detection
- [x] Diff computation (added/removed steps between versions)
- [x] Human-readable diff summaries
- [x] Version history API endpoint

### Human-in-the-Loop Labeling (NEW)
- [x] PATCH API to update journey name, domain, feature, tags
- [x] Correction audit trail with old/new values
- [x] Learned domain/feature vocabulary endpoint
- [x] Foundation for future clustering model fine-tuning

### Real-Time Event Ingestion (NEW)
- [x] WebSocket endpoint (`ws://localhost:8000/ws/events`)
- [x] Per-session event buffering
- [x] Auto-clustering on flush command or disconnect
- [x] Replaces batch JSON upload friction

### Auto-Healing (2-Level)
- [x] 8-strategy runtime self-healing locator chain
- [x] 5-layer overlay immunity (CSS kill-sheet, MutationObserver, proactive sweep, scrollIntoView, JS click bypass)
- [x] AI-powered healing via any configured LLM
- [x] Vision-capable healing with failure screenshots
- [x] **Full function replacement** — LLM returns entire `def test_...` function, eliminating indentation errors

### Cloud LLM Integration
- [x] 6 providers via LiteLLM: Ollama, OpenAI, Claude, Gemini, OpenRouter, NVIDIA NIM
- [x] Dashboard UI for provider configuration
- [x] Connection testing
- [x] Fallback chain: primary → text-only retry → fallback model → Ollama

### AI Features
- [x] NL test generation from plain English descriptions
- [x] Assertion generation (AI infers `expect()` calls)
- [x] Root cause analysis with flaky test detection
- [x] AI Explorer for autonomous web crawling
- [x] QA Skills system — 11 composable personas shaping AI Explorer curiosity

### QA Skills System (NEW)
- [x] 11 skills: Curious Explorer, Edge Case Hunter, Form Specialist, Navigation Mapper, Accessibility Auditor, Error Recovery Tester, Security Prober, Mobile & Responsive, Workflow Completionist, Performance Observer, Data Integrity Checker
- [x] 5 preset bundles: Quick Scan, Deep QA, Security, Accessibility, Full Regression
- [x] Dynamic LLM prompt composition from selected skills
- [x] Skill-driven fill overrides (XSS payloads, boundary values, realistic data)
- [x] Skill-driven element prioritization in fallback exploration
- [x] Dashboard UI with interactive skill chips and bundle presets
- [x] REST API (`GET /api/explorer/skills`) for skills and bundles
- [x] Validated against SauceDemo with Ollama (Qwen 2.5 Coder 7B)

### Validated Against
- [x] SauceDemo (e-commerce: login, cart, checkout) — 19 steps
- [x] The Internet Herokuapp (forms: login, logout) — 7 steps
- [x] TodoMVC (SPA: add, toggle, filter todos) — 11 steps
- [x] Vigil Dashboard (self-test: chat, browse, export) — 14 steps

---

## Resolved P0/P1/P2 Items

| Priority | Item | Status |
|----------|------|--------|
| P0 | Wire NL QueryEngine into `/api/query` | **Done** — LLM-first with keyword fallback |
| P0 | Fix step-event mapping in labeler | **Done** — `event_indices` per step |
| P1 | Cypress export | **Done** — `.cy.js` with smart selectors |
| P1 | GitHub Actions CI/CD integration | **Done** — Playwright + Cypress workflows |
| P1 | Journey versioning/diffing | **Done** — auto-snapshot + step-level diffs |
| P2 | Real-time clustering via WebSocket | **Done** — per-session buffering + auto-cluster |
| P2 | Human-in-the-loop labeling correction | **Done** — PATCH API + audit trail |
| P1 | QA Skills system for AI Explorer | **Done** — 11 skills, 5 bundles, prompt + fill + priority |
| P0 | Visual regression testing | **Done** (v0.2) — Pixel-level screenshot diffing with baselines |
| P0 | Slack/Teams bot integration | **Done** (v0.3) — 5 slash commands, webhook alerts, rich formatting |
| P1 | Pytest + Selenium export | **Done** (v0.3) — Multi-strategy locator, ActionChains, headless/headed |
| P1 | Smart noise filtering | **Done** (v0.3) — ML-weighted scoring, 25+ noise domains, burst filter |
| P1 | Multi-session merge | **Done** (v0.3) — Duplicate detection + auto-merge |
| P1 | Test suite generation | **Done** (v0.3) — Auto-grouping by feature, coverage gap analysis |
| P2 | Auth credential manager | **Done** (v0.3) — Per-domain encrypted vault, login page detection |
| P2 | Scroll/hover/drag capture | **Done** (v0.3) — 9 rich event types |
| P2 | Shadow DOM support | **Done** (v0.3) — Cross-framework selector piercing |

---

## Phase 1.8: Completed (Feb 2026) ✓

All 9 pilot-blocking items shipped.

| Priority | Item | Status | Details |
|----------|------|--------|---------|
| **P0** | Slack/Teams bot | **Done** | 5 slash commands, webhook alerts, rich Slack formatting |
| **P1** | Pytest + Selenium export | **Done** | Third framework = 80%+ market coverage |
| **P1** | Smart noise filtering | **Done** | ML-weighted scoring, 25+ noise domains, burst detection |
| **P1** | Multi-session merge | **Done** | SequenceMatcher duplicate detection + auto-merge |
| **P1** | Test suite generation | **Done** | Auto-grouping into suites, coverage gap analysis |
| **P2** | Auth credential manager | **Done** | Encrypted per-domain vault, login page detection |
| **P2** | Scroll/hover/drag capture | **Done** | 9 rich event types with replay strategies |
| **P2** | Shadow DOM support | **Done** | Playwright/Selenium/Cypress shadow piercing |

---

## Phase 2: Product — Make It Useful (Q2-Q3 2026)

**Objective**: Turn validated MVP into something a 5-person QA team uses daily.

### 2.1 Capture Agent v2
- [x] One-click flush to backend API (done in v1.0)
- [x] iFrame support via `all_frames: true` (done in v1.0)
- [x] Session rotation on idle (30 min, done in v1.0)
- [x] Real-time event streaming (WebSocket to local backend) — **Done**
- [x] Smart noise filtering (ML-weighted scoring, 25+ noise domains) — **Done v0.3**
- [x] Scroll, hover, drag-and-drop capture (9 event types) — **Done v0.3**
- [x] Shadow DOM support (cross-framework piercing) — **Done v0.3**
- [ ] Multi-tab session tracking
- [ ] Session tagging ("I'm testing checkout now")

### 2.2 Clustering Engine v2
- [x] Real-time incremental clustering — **Done** (WebSocket + auto-cluster)
- [x] Human-in-loop correction ("this label is wrong -> fix it") — **Done**
- [x] Journey versioning (detect flow changes over time) — **Done**
- [x] Journey diffing ("checkout changed since last week") — **Done**
- [x] Multi-session merge (duplicate detection + auto-merge) — **Done v0.3**
- [ ] Feedback loop: corrections improve future labeling

### 2.3 Test Export v2
- [x] Cypress test export — **Done**
- [x] Pytest + Selenium export — **Done v0.3**
- [x] Auto-generated assertions (infer expected outcomes) — **Done**
- [x] Test suite generation (auto-grouping + gap analysis) — **Done v0.3**
- [ ] Data-driven test variants (parameterize from observed variations)

### 2.4 Team Features
- [x] Multi-user support (JWT auth, 3 roles) — **Done v0.2**
- [x] Slack/Teams bot for queries and alerts — **Done v0.3**
- [ ] Team coverage dashboard
- [ ] Journey ownership assignment
- [x] Duplicate detection across team members — **Done v0.3**

---

## Phase 3: Platform — Make It Sticky (Q4 2026 - Q1 2027)

### 3.1 Integrations
- [x] Slack/Teams bot for journey queries — **Done v0.3**
- [ ] Jira: auto-link journeys to tickets
- [x] GitHub Actions CI/CD replay triggers — **Done**
- [ ] Jenkins CI/CD integration
- [ ] GitLab CI/CD integration
- [ ] Import into Testim/Mabl/Cypress Dashboard

### 3.2 Semantic API
- [ ] Public REST API with API key auth
- [ ] Webhook events (new journey, coverage gap detected)
- [ ] Python/JS SDKs
- [ ] Rate limiting

### 3.3 App-Agnostic Expansion
- [ ] Mobile web via Chrome DevTools mobile mode
- [ ] Electron desktop agent
- [ ] Mobile native via Appium/Maestro bridge
- [ ] Desktop app via Accessibility API
- [ ] Legacy app via OpenCV + Vision LLM

### 3.4 Advanced Analytics
- [ ] Risk scoring (high-risk + under-tested)
- [ ] Trend analysis over weeks/months
- [ ] Coverage gap recommendations
- [ ] Journey complexity scoring

---

## Phase 4: Scale — Make It Big (2027)

### 4.1 Enterprise
- [ ] SSO (SAML, OIDC)
- [ ] RBAC
- [ ] On-premise / VPC deployment
- [ ] Audit trails
- [ ] Compliance reports (SOX, HIPAA)
- [ ] Data retention policies

### 4.2 AI Evolution
- [ ] Fine-tuned clustering model (using human-in-the-loop corrections)
- [ ] Local model option (Ollama/vLLM) for air-gapped envs
- [ ] Autonomous test generation for coverage gaps
- [ ] Anomaly detection (journey behaved differently)

### 4.3 Adjacent Markets
- [ ] Process Mining mode (business workflows)
- [ ] Knowledge Base mode (auto-document app behavior)
- [ ] Training mode (onboard new QA with senior patterns)

---

## Key Milestones

| Date | Milestone | Status |
|------|-----------|--------|
| **Feb 2026** | MVP complete, 4-app validation, production-grade exporter & extension v1.0 | **DONE** |
| **Feb 2026** | P0/P1/P2 roadmap items: Cypress, CI/CD, versioning, WebSocket, HITL labeling | **DONE** |
| **Feb 2026** | QA Skills system: 11 composable AI personas, 5 preset bundles | **DONE** |
| **Feb 2026** | v0.3 Pilot-ready: Slack bot, Selenium, noise filter, merge, suites, creds, rich events, Shadow DOM | **DONE** |
| **Mar 2026** | First external pilot (1 QA team, target: 3 journeys/day captured) | **Next** |
| **May 2026** | Product v1 (5 teams, 60% retention) | Planned |
| **Aug 2026** | API beta, 1 external integration | Planned |
| **Nov 2026** | Platform v1, 3 enterprise pilots | Planned |
| **Feb 2027** | Enterprise v1, $100K ARR | Planned |
| **Aug 2027** | Scale, $500K-1M ARR, Series A ready | Planned |

---

## Decision Gates

| Gate | Question | If No |
|------|----------|-------|
| **After MVP** | Do QA engineers find journey labels accurate? | Pivot to manual labeling tool |
| **After Phase 2** | Are teams using it daily without being asked? | Simplify UX or pivot persona |
| **After Phase 3** | Will enterprises pay >$10K/year? | Downmarket to PLG freemium |
| **After Phase 4** | Is the market large enough for VC-scale? | Stay bootstrapped or seek acquisition |
