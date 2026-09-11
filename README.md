<p align="center">
  <h1 align="center">Vigil</h1>
  <p align="center"><strong>Open-source passive QA capture &amp; AI test automation</strong></p>
  <p align="center">
    Your team records itself. AI writes the tests.
  </p>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#how-it-works">How It Works</a> &bull;
  <a href="#features">Features</a> &bull;
  <a href="ARCHITECTURE.md">Architecture</a> &bull;
  <a href="#contributing">Contributing</a>
</p>

---

## Project Status

**Early-stage open source** — core pipeline works (capture → cluster → Playwright export → self-healing replay), validated against demo apps and real production sites (GitHub, Wikipedia, Hacker News). Not production-hardened. No external pilot users yet. Actively seeking feedback from QA engineers and SDETs — see [Contributing](#contributing).

> **Real-site validation (Aug 2026):** 6/6 journeys PASSED on GitHub, Wikipedia, and Hacker News. Wikipedia search triggered the self-healing cascade live — CSS selector failed, ARIA fallback recovered. See [how the cascade works](#self-healing-cascade).

---

## What Is Vigil?

Vigil passively captures your team's behavior as they use the app through a Chrome extension, clusters interactions into meaningful journeys using AI, and generates self-healing Playwright tests that adapt when UI changes. Your team records itself — no production users are watched without consent.

**No test scripts to write. No selectors to maintain. No flaky tests.**

```
You browse your app normally
        ↓
Vigil's Chrome extension silently records every click, navigation, and form fill
        ↓
AI clusters raw events into named user journeys ("Guest Checkout with Promo Code")
        ↓
One click → runnable Playwright/Cypress/Selenium tests with self-healing selectors
```

### Why Vigil?

| Problem | Vigil's Approach |
|---------|-----------------|
| Writing E2E tests is slow | Tests are generated from observed behavior — zero authoring |
| Tests break when UI changes | Self-healing engine cascades through 6 selector strategies + LLM repair |
| You don't know what to test | AI discovers journeys from your team's recorded sessions |
| Test data is PII-sensitive | Input values (passwords, emails, cards) redacted at capture. URLs and page titles stored locally. Local-first — data stays on your machine. See [Privacy & Security](#privacy--security). |

---

## Quick Start

### 1. Start the Backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn testai.server:app --port 8000
```

Open http://localhost:8000 for the dashboard.

### 2. Run a Demo (No Extension Needed)

```bash
cd backend
python -m testai demo                  # Quick demo with local clustering
python -m testai demo --use-llm        # Demo with LLM-powered labeling
python -m testai demo-showcase         # Rich showcase (3 apps, 12 journeys)
```

### 3. Install the Chrome Extension

1. Open `chrome://extensions/`
2. Enable **Developer mode**
3. Click **Load unpacked** → select the `extension/` folder
4. Browse any web app — events are captured automatically

---

## How It Works

### The problem Vigil solves

Every time your UI changes, your E2E tests break. Someone has to find the broken selector, fix it, and push a patch. At scale this becomes a full-time job — or teams just stop maintaining tests.

```mermaid
graph LR
    A["🧑‍💻 Engineer changes a button label"] --> B["❌ 12 tests fail\n on CI"]
    B --> C["😩 Someone spends\n half a day fixing selectors"]
    C --> D["🔁 Repeat next sprint"]
```

### What Vigil does instead

```mermaid
graph LR
    A["🧑 Your team uses\n the app normally"] -->|Chrome extension\ncaptures every click| B["📋 Vigil discovers\n user journeys"]
    B -->|AI clusters &\n names them| C["🧪 Runnable tests\n generated automatically"]
    C -->|UI changes?| D["🔧 Self-healing engine\n fixes broken selectors"]
    D -->|Test passes| E["✅ CI stays green\n No human needed"]
```

**The core trade-offs:**
- Needs real usage to capture from (works best on apps people actually use daily)
- Self-healing is best-effort — LLM repair is the last resort, not the first
- Local-first: all data stays on your machine, PII redacted before storage

---

## Self-Healing Cascade

When a selector fails at replay time, Vigil doesn't stop — it tries 8 strategies in order before calling it a failure:

```
1. CSS selector          → exact match from capture
2. XPath                 → structural fallback
3. ARIA role + label     → get_by_role("button", name="Submit")
4. Visible text          → get_by_text("Submit")
5. Placeholder text      → get_by_placeholder("Search...")
6. test-id attributes    → data-testid, data-cy, data-qa (7 variants)
7. nth-of-type           → positional last resort
8. LLM repair            → send failure screenshot + test source → get back a patched function
```

**Real example:** Wikipedia search input (Aug 2026 run)

```
[step 2] fill: #searchInput → TimeoutError (element not found)
[heal]   try XPath: //input[@type="search"] → not found
[heal]   try ARIA: get_by_role("searchbox") → FOUND
[healed] filled focused element with "Large language model"
```

The test continues. No human intervention. The healed selector is logged but not written back — the next run tries CSS first again, so a one-time DOM quirk doesn't permanently degrade the test.

---

## Features

| Feature | Description |
|---------|-------------|
| **Passive Capture** | Chrome extension silently records user interactions — no test authoring |
| **Journey Discovery** | AI clusters events into meaningful, named test flows |
| **Self-Healing Tests** | 6-strategy selector cascade + LLM repair when UI changes |
| **Multi-Framework Export** | Playwright, Cypress, Selenium test generation |
| **Visual Regression** | Pixel-diff screenshot comparison per step |
| **AI Explorer** | Autonomous agent that crawls your app and discovers test flows |
| **HITL Review Queue** | Approve, reject, or correct auto-discovered journeys |
| **Scheduled Monitoring** | Cron-based production test runs with alerts |
| **Flaky Test Detection** | Identify inconsistent pass/fail patterns |
| **Natural Language Query** | Ask "What checkout flows did we test this week?" |
| **CI/CD Export** | One-click GitHub Actions workflow generation |
| **Local-First** | All data stays on your machine. No cloud required |
| **Pluggable LLM** | OpenAI, Anthropic, Google, Ollama (free local models) |
| **Slack Integration** | Alert notifications and `/vigil` slash commands |

---

## Privacy & Security

Vigil is **local-first by design**:

- All data stored locally (IndexedDB + SQLite)
- **Input values** redacted at capture time: passwords, emails, phone numbers, card numbers → `[REDACTED]`. URLs, page titles, and link text are stored unredacted (server-side URL redaction planned — see [PILOT_PLAN.md](docs/PILOT_PLAN.md#wave-2-core-validity-weeks-24)).
- **LLM:** local Ollama is the default; cloud LLM (OpenAI, Anthropic, etc.) is opt-in. When enabled, event summaries including URLs and page titles are sent to the cloud provider. Raw captured values are not included in prompts.
- Domain allowlist — only sites you explicitly add are captured. Empty allowlist captures nothing (fail-closed after v0.4).
- Credential vault encrypted with Fernet (AES-128-CBC + HMAC); key sourced from `VIGIL_VAULT_KEY` env or auto-generated at `~/.vigil/vault.key` (0600 permissions)
- No telemetry, no analytics, no phone-home (font self-hosting planned for v0.4 — see [PILOT_PLAN.md](docs/PILOT_PLAN.md))
- Delete all data anytime via extension settings

---

## LLM Providers

| Provider | Models | Cost |
|----------|--------|------|
| **Ollama** | Qwen 2.5, Llama 3, CodeLlama | Free (local) |
| **OpenAI** | GPT-4o, GPT-4o Mini | Pay-per-use |
| **Anthropic** | Claude Sonnet, Haiku | Pay-per-use |
| **Google** | Gemini 2.0 Flash, 1.5 Pro | Pay-per-use |
| **OpenRouter** | 200+ models | Varies |

Configure via the dashboard Settings page or `~/.vigil/llm.json`.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/ingest` | Ingest captured events |
| GET | `/api/journeys` | List discovered journeys |
| GET | `/api/journeys/{id}` | Journey with steps |
| POST | `/api/journeys/{id}/replay` | Replay a journey |
| GET | `/api/runs` | List test runs |
| POST | `/api/query` | Natural language query |
| POST | `/api/ai/assertions` | AI-generated assertions |
| POST | `/api/ai/generate-test` | Generate test from description |
| GET | `/api/ai/rca` | Root cause analysis |
| GET | `/api/reviews` | Review queue |
| PATCH | `/api/reviews/{id}/approve` | Approve a journey |

Full interactive docs at http://localhost:8000/docs (Swagger UI).

---

## Project Structure

```
vigil/
  backend/
    testai/
      api_testing/     # HTTP API test runner
      audit/           # AI site audit
      capture/         # Rich event processing, Shadow DOM
      cluster/         # Journey clustering, noise filter, suite gen
      credentials/     # Auth credential management
      explorer/        # Autonomous site explorer agent
      export/          # Playwright, Cypress, Selenium exporters
      healing/         # Self-healing selector engine (6 strategies)
      hitl/            # Human-in-the-loop review & learning
      integrations/    # Slack bot
      llm/             # LLM provider abstraction
      models/          # Event, Journey, Step data models
      monitoring/      # Scheduled test monitoring
      routes/          # FastAPI API routes
      storage/         # SQLite database
      visual/          # Visual regression testing
      server.py        # FastAPI application
    requirements.txt
  dashboard/           # Web dashboard (HTML/JS/CSS)
  extension/           # Chrome extension (Manifest V3)
  docs/
    diagrams/          # Excalidraw architecture diagrams
```

---

## Contributing

Contributions are welcome! Areas where help is especially appreciated:

- **Browser support** — Firefox extension port
- **Test framework exports** — TestCafe, WebdriverIO, Robot Framework
- **Clustering quality** — Better journey segmentation algorithms
- **Visual regression** — More robust diff engine
- **Docs & examples** — Getting started guides, video walkthroughs

```bash
# Development setup
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn testai.server:app --reload --port 8000
```

---

## License

MIT — see [LICENSE](LICENSE).
