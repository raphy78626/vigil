"""CI/CD Workflow Generator — GitHub Actions YAML for Playwright & Cypress tests.

Supports: cross-browser matrix, parallel sharding, retry on failure, visual regression
artifact uploads, and Slack/webhook notifications.
"""

from __future__ import annotations

from typing import List, Literal


def generate_github_actions(
    framework: Literal["playwright", "cypress"] = "playwright",
    base_url: str = "https://your-app.example.com",
    cron: str = "",
    node_version: str = "20",
    python_version: str = "3.11",
    has_auth: bool = False,
    browsers: List[str] | None = None,
    parallel_shards: int = 1,
    retries: int = 2,
    visual_regression: bool = False,
    slack_webhook: bool = False,
) -> str:
    if framework == "cypress":
        return _cypress_workflow(base_url, cron, node_version, has_auth, browsers, retries, slack_webhook)
    return _playwright_workflow(
        base_url, cron, python_version, has_auth,
        browsers or ["chromium"], parallel_shards, retries,
        visual_regression, slack_webhook,
    )


def _playwright_workflow(
    base_url: str, cron: str, python_version: str, has_auth: bool,
    browsers: List[str], parallel_shards: int, retries: int,
    visual_regression: bool, slack_webhook: bool,
) -> str:
    trigger = f"""
  schedule:
    - cron: '{cron or "0 6 * * 1-5"}'""" if cron else ""

    auth_step = """
      - name: Restore auth state
        if: env.AUTH_JSON != ''
        run: echo "$AUTH_JSON" > auth.json
        env:
          AUTH_JSON: ${{ secrets.AUTH_JSON }}
""" if has_auth else ""

    auth_env = "\n          STORAGE_STATE: auth.json" if has_auth else ""

    browser_list = json.dumps(browsers) if len(browsers) > 1 else ""
    matrix_block = ""
    if len(browsers) > 1 or parallel_shards > 1:
        parts = []
        if len(browsers) > 1:
            parts.append(f"          browser: {json.dumps(browsers)}")
        if parallel_shards > 1:
            parts.append(f"          shard: [{', '.join(str(i+1) for i in range(parallel_shards))}]")
        matrix_block = f"""
    strategy:
      fail-fast: false
      matrix:
{chr(10).join(parts)}"""

    browser_install = browsers[0] if len(browsers) == 1 else "${{ matrix.browser }}"
    browser_arg = f"--browser {browsers[0]}" if len(browsers) == 1 else "--browser ${{ matrix.browser }}"
    shard_arg = f" --shard ${{{{ matrix.shard }}}}/{parallel_shards}" if parallel_shards > 1 else ""

    vr_step = """
      - name: Visual regression check
        if: always()
        run: |
          python -c "
          import json, sys
          from pathlib import Path
          diffs = list(Path('screenshots').glob('*_diff.png'))
          if diffs:
              print(f'⚠ {len(diffs)} visual regression(s) detected')
              for d in diffs: print(f'  - {d.name}')
              sys.exit(1)
          print('✓ No visual regressions')
          "
""" if visual_regression else ""

    slack_step = """
      - name: Notify Slack
        if: failure()
        uses: 8398a7/action-slack@v3
        with:
          status: ${{ job.status }}
          fields: repo,message,commit,author,action,eventName,ref,workflow
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
""" if slack_webhook else ""

    job_name = "Playwright Tests"
    if len(browsers) > 1:
        job_name = "Playwright (${{ matrix.browser }})"
    if parallel_shards > 1:
        job_name += " [shard ${{ matrix.shard }}]"

    return f"""# Vigil — Playwright E2E Tests (Multi-Browser, Auto-Retry)
# Auto-generated CI/CD workflow
#
# Required secrets:
#   BASE_URL — target application URL (or set default below)
{"#   AUTH_JSON — browser auth state JSON (for authenticated tests)" if has_auth else "#"}
{"#   SLACK_WEBHOOK_URL — Slack incoming webhook for failure notifications" if slack_webhook else "#"}
#
# Features: cross-browser matrix, {retries}x retry, {"visual regression, " if visual_regression else ""}{"parallel sharding, " if parallel_shards > 1 else ""}artifact uploads

name: Vigil E2E Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]{trigger}
  workflow_dispatch:

jobs:
  test:
    name: {job_name}
    runs-on: ubuntu-latest
    timeout-minutes: 30{matrix_block}

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '{python_version}'

      - name: Install dependencies
        run: |
          pip install pytest pytest-playwright
          playwright install --with-deps {browser_install}
{auth_step}
      - name: Run tests (attempt 1)
        id: test1
        continue-on-error: true
        run: |
          pytest test_replay.py -v \\
            --base-url ${{{{ env.BASE_URL }}}} \\
            {browser_arg} \\
            --tb=short{shard_arg} \\
            --junitxml=results.xml
        env:
          BASE_URL: ${{{{ secrets.BASE_URL || '{base_url}' }}}}{auth_env}
          SCREENSHOT_DIR: screenshots

      - name: Retry failed tests
        if: steps.test1.outcome == 'failure'
        run: |
          echo "Retrying failed tests ({retries - 1} retries remaining)..."
          pytest test_replay.py -v \\
            --base-url ${{{{ env.BASE_URL }}}} \\
            {browser_arg} \\
            --tb=short{shard_arg} \\
            --junitxml=results-retry.xml \\
            --last-failed
        env:
          BASE_URL: ${{{{ secrets.BASE_URL || '{base_url}' }}}}{auth_env}
          SCREENSHOT_DIR: screenshots
{vr_step}
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-results-{browsers[0] if len(browsers) == 1 else "${{ matrix.browser }}"}
          path: |
            results.xml
            results-retry.xml
            screenshots/

      - name: Upload screenshots
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: failure-screenshots-{browsers[0] if len(browsers) == 1 else "${{ matrix.browser }}"}
          path: screenshots/
{slack_step}"""


def _cypress_workflow(
    base_url: str, cron: str, node_version: str, has_auth: bool,
    browsers: list | None, retries: int, slack_webhook: bool,
) -> str:
    trigger = f"""
  schedule:
    - cron: '{cron or "0 6 * * 1-5"}'""" if cron else ""

    browser_list = browsers or ["chrome"]
    matrix_block = ""
    if len(browser_list) > 1:
        import json
        matrix_block = f"""
    strategy:
      fail-fast: false
      matrix:
          browser: {json.dumps(browser_list)}"""

    browser_val = browser_list[0] if len(browser_list) == 1 else "${{ matrix.browser }}"

    slack_step = """
      - name: Notify Slack
        if: failure()
        uses: 8398a7/action-slack@v3
        with:
          status: ${{ job.status }}
          fields: repo,message,commit,author
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
""" if slack_webhook else ""

    return f"""# Vigil — Cypress E2E Tests (Multi-Browser, Auto-Retry)
# Auto-generated CI/CD workflow

name: Vigil Cypress Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]{trigger}
  workflow_dispatch:

jobs:
  test:
    name: Cypress Tests ({browser_val})
    runs-on: ubuntu-latest
    timeout-minutes: 30{matrix_block}

    steps:
      - uses: actions/checkout@v4

      - name: Cypress run
        uses: cypress-io/github-action@v6
        with:
          browser: {browser_val}
          config: retries={retries}
        env:
          CYPRESS_BASE_URL: ${{{{ secrets.BASE_URL || '{base_url}' }}}}

      - name: Retry on failure
        if: failure()
        uses: cypress-io/github-action@v6
        with:
          browser: {browser_val}
          config: retries=1
        env:
          CYPRESS_BASE_URL: ${{{{ secrets.BASE_URL || '{base_url}' }}}}

      - name: Upload screenshots
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: cypress-screenshots-{browser_val}
          path: cypress/screenshots/

      - name: Upload videos
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: cypress-videos-{browser_val}
          path: cypress/videos/
{slack_step}"""


import json
