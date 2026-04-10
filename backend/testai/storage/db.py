"""SQLite storage for TestAI-Pro — events, journeys, steps, and platform data."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from testai.models.event import Event
from testai.models.journey import Journey

DEFAULT_DB_PATH = Path.home() / ".vigil" / "vigil.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    type TEXT NOT NULL,
    url TEXT NOT NULL,
    page_title TEXT DEFAULT '',
    element_json TEXT,
    navigation_json TEXT,
    tab_id INTEGER DEFAULT 0,
    session_id TEXT NOT NULL,
    screenshot_path TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS journeys (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT DEFAULT '',
    feature TEXT DEFAULT '',
    confidence REAL DEFAULT 0.0,
    discovered_at TEXT NOT NULL,
    discovered_by TEXT DEFAULT '',
    session_id TEXT DEFAULT '',
    variant_of TEXT,
    tags TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS steps (
    id TEXT PRIMARY KEY,
    journey_id TEXT NOT NULL REFERENCES journeys(id),
    step_order INTEGER NOT NULL,
    description TEXT NOT NULL,
    url TEXT DEFAULT '',
    action_type TEXT DEFAULT '',
    element_hint TEXT,
    selectors TEXT DEFAULT '{}',
    event_ids TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test_runs (
    id TEXT PRIMARY KEY,
    journey_id TEXT NOT NULL REFERENCES journeys(id),
    base_url TEXT NOT NULL,
    passed INTEGER NOT NULL DEFAULT 0,
    total_steps INTEGER DEFAULT 0,
    passed_steps INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    exit_code INTEGER DEFAULT -1,
    headed INTEGER DEFAULT 0,
    error_message TEXT DEFAULT '',
    healed INTEGER DEFAULT 0,
    heal_attempts INTEGER DEFAULT 0,
    browser TEXT DEFAULT 'chromium',
    device TEXT DEFAULT '',
    console_errors TEXT DEFAULT '[]',
    network_failures TEXT DEFAULT '[]',
    api_calls TEXT DEFAULT '[]',
    step_timings TEXT DEFAULT '{}',
    web_vitals TEXT DEFAULT '{}',
    vision_healed INTEGER DEFAULT 0,
    vision_heal_count INTEGER DEFAULT 0,
    started_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_journeys_domain ON journeys(domain);
CREATE INDEX IF NOT EXISTS idx_journeys_discovered ON journeys(discovered_at);
CREATE INDEX IF NOT EXISTS idx_steps_journey ON steps(journey_id);
CREATE TABLE IF NOT EXISTS explorer_sessions (
    id TEXT PRIMARY KEY,
    base_url TEXT NOT NULL,
    strategy TEXT DEFAULT 'bfs',
    status TEXT DEFAULT 'running',
    pages_visited INTEGER DEFAULT 0,
    flows_discovered INTEGER DEFAULT 0,
    config_json TEXT DEFAULT '{}',
    results_json TEXT DEFAULT '{}',
    started_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS journey_versions (
    id TEXT PRIMARY KEY,
    journey_id TEXT NOT NULL REFERENCES journeys(id),
    version INTEGER NOT NULL DEFAULT 1,
    step_hash TEXT NOT NULL,
    step_count INTEGER NOT NULL DEFAULT 0,
    steps_json TEXT NOT NULL DEFAULT '[]',
    diff_json TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS label_corrections (
    id TEXT PRIMARY KEY,
    journey_id TEXT NOT NULL REFERENCES journeys(id),
    field TEXT NOT NULL,
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Visual regression baselines
CREATE TABLE IF NOT EXISTS visual_baselines (
    id TEXT PRIMARY KEY,
    journey_id TEXT NOT NULL REFERENCES journeys(id),
    step_order INTEGER NOT NULL,
    baseline_b64 TEXT NOT NULL,
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(journey_id, step_order)
);

CREATE TABLE IF NOT EXISTS visual_diffs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES test_runs(id),
    journey_id TEXT NOT NULL REFERENCES journeys(id),
    step_order INTEGER NOT NULL,
    diff_percent REAL DEFAULT 0.0,
    diff_b64 TEXT DEFAULT '',
    passed INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- API tests
CREATE TABLE IF NOT EXISTS api_tests (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    method TEXT NOT NULL DEFAULT 'GET',
    url TEXT NOT NULL,
    headers_json TEXT DEFAULT '{}',
    body_json TEXT DEFAULT '',
    assertions_json TEXT DEFAULT '[]',
    tags TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS api_test_runs (
    id TEXT PRIMARY KEY,
    test_id TEXT NOT NULL REFERENCES api_tests(id),
    passed INTEGER NOT NULL DEFAULT 0,
    status_code INTEGER DEFAULT 0,
    response_time_ms INTEGER DEFAULT 0,
    response_body TEXT DEFAULT '',
    assertion_results TEXT DEFAULT '[]',
    error_message TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

-- Scheduled monitoring
CREATE TABLE IF NOT EXISTS scheduled_monitors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    monitor_type TEXT NOT NULL DEFAULT 'journey',
    target_id TEXT NOT NULL,
    base_url TEXT DEFAULT '',
    cron_expr TEXT DEFAULT '0 */6 * * *',
    browser TEXT DEFAULT 'chromium',
    enabled INTEGER DEFAULT 1,
    webhook_url TEXT DEFAULT '',
    last_run_at TEXT,
    last_status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS monitor_alerts (
    id TEXT PRIMARY KEY,
    monitor_id TEXT NOT NULL REFERENCES scheduled_monitors(id),
    alert_type TEXT NOT NULL DEFAULT 'failure',
    message TEXT NOT NULL,
    acknowledged INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Users and teams
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TEXT DEFAULT (datetime('now')),
    last_login TEXT
);

-- Flaky test tracking
CREATE TABLE IF NOT EXISTS flaky_tests (
    id TEXT PRIMARY KEY,
    journey_id TEXT NOT NULL REFERENCES journeys(id),
    flake_rate REAL DEFAULT 0.0,
    total_runs INTEGER DEFAULT 0,
    total_failures INTEGER DEFAULT 0,
    quarantined INTEGER DEFAULT 0,
    last_analyzed TEXT DEFAULT (datetime('now')),
    UNIQUE(journey_id)
);

CREATE INDEX IF NOT EXISTS idx_label_corrections_journey ON label_corrections(journey_id);
CREATE INDEX IF NOT EXISTS idx_test_runs_journey ON test_runs(journey_id);
CREATE INDEX IF NOT EXISTS idx_test_runs_started ON test_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_explorer_sessions_started ON explorer_sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_journey_versions_journey ON journey_versions(journey_id);

CREATE TABLE IF NOT EXISTS review_actions (
    id TEXT PRIMARY KEY,
    journey_id TEXT NOT NULL REFERENCES journeys(id),
    action TEXT NOT NULL,
    reviewer TEXT DEFAULT '',
    note TEXT DEFAULT '',
    changes_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS hitl_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_review_actions_journey ON review_actions(journey_id);
CREATE INDEX IF NOT EXISTS idx_visual_baselines_journey ON visual_baselines(journey_id);
CREATE INDEX IF NOT EXISTS idx_visual_diffs_run ON visual_diffs(run_id);
CREATE INDEX IF NOT EXISTS idx_api_tests_name ON api_tests(name);
CREATE INDEX IF NOT EXISTS idx_api_test_runs_test ON api_test_runs(test_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_monitors_type ON scheduled_monitors(monitor_type);
CREATE INDEX IF NOT EXISTS idx_flaky_tests_journey ON flaky_tests(journey_id);

CREATE TABLE IF NOT EXISTS explorations (
    id TEXT PRIMARY KEY,
    journey_id TEXT NOT NULL REFERENCES journeys(id),
    base_url TEXT DEFAULT '',
    total_variants INTEGER DEFAULT 0,
    bugs_found INTEGER DEFAULT 0,
    results_json TEXT DEFAULT '[]',
    started_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_explorations_journey ON explorations(journey_id);

"""


class Database:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Add columns that may be missing from older schemas."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(test_runs)").fetchall()}
        if "healed" not in cols:
            self._conn.execute("ALTER TABLE test_runs ADD COLUMN healed INTEGER DEFAULT 0")
        if "heal_attempts" not in cols:
            self._conn.execute("ALTER TABLE test_runs ADD COLUMN heal_attempts INTEGER DEFAULT 0")
        if "browser" not in cols:
            self._conn.execute("ALTER TABLE test_runs ADD COLUMN browser TEXT DEFAULT 'chromium'")
        if "device" not in cols:
            self._conn.execute("ALTER TABLE test_runs ADD COLUMN device TEXT DEFAULT ''")
        if "console_errors" not in cols:
            self._conn.execute("ALTER TABLE test_runs ADD COLUMN console_errors TEXT DEFAULT '[]'")
        if "network_failures" not in cols:
            self._conn.execute("ALTER TABLE test_runs ADD COLUMN network_failures TEXT DEFAULT '[]'")
        if "api_calls" not in cols:
            self._conn.execute("ALTER TABLE test_runs ADD COLUMN api_calls TEXT DEFAULT '[]'")
        if "step_timings" not in cols:
            self._conn.execute("ALTER TABLE test_runs ADD COLUMN step_timings TEXT DEFAULT '{}'")
        if "web_vitals" not in cols:
            self._conn.execute("ALTER TABLE test_runs ADD COLUMN web_vitals TEXT DEFAULT '{}'")
        if "vision_healed" not in cols:
            self._conn.execute("ALTER TABLE test_runs ADD COLUMN vision_healed INTEGER DEFAULT 0")
        if "vision_heal_count" not in cols:
            self._conn.execute("ALTER TABLE test_runs ADD COLUMN vision_heal_count INTEGER DEFAULT 0")

        # HITL review columns on journeys
        j_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(journeys)").fetchall()}
        if "review_status" not in j_cols:
            self._conn.execute("ALTER TABLE journeys ADD COLUMN review_status TEXT DEFAULT 'pending_review'")
        if "reviewed_by" not in j_cols:
            self._conn.execute("ALTER TABLE journeys ADD COLUMN reviewed_by TEXT DEFAULT ''")
        if "reviewed_at" not in j_cols:
            self._conn.execute("ALTER TABLE journeys ADD COLUMN reviewed_at TEXT DEFAULT ''")
        if "review_note" not in j_cols:
            self._conn.execute("ALTER TABLE journeys ADD COLUMN review_note TEXT DEFAULT ''")

        # Seed default HITL config
        self._conn.execute(
            "INSERT OR IGNORE INTO hitl_config (key, value) VALUES (?, ?)",
            ("auto_approve_threshold", "0.85"),
        )

        # Backfill: auto-approve existing high-confidence journeys that have no status yet
        self._conn.execute(
            """UPDATE journeys SET review_status = 'auto_approved', reviewed_by = 'system'
            WHERE review_status = 'pending_review' AND confidence >= 0.85
            AND reviewed_by = ''""",
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        return self._conn

    def insert_event(self, event: Event) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO events
            (id, timestamp, type, url, page_title, element_json, navigation_json,
             tab_id, session_id, screenshot_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.id,
                event.timestamp.isoformat(),
                event.type.value,
                event.url,
                event.page_title,
                event.element.model_dump_json() if event.element else None,
                event.navigation.model_dump_json() if event.navigation else None,
                event.tab_id,
                event.session_id,
                event.screenshot_path,
            ),
        )
        self.conn.commit()

    def insert_events(self, events: List[Event]) -> None:
        for event in events:
            self.insert_event(event)

    def insert_journey(self, journey: Journey) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO journeys
            (id, name, domain, feature, confidence, discovered_at,
             discovered_by, session_id, variant_of, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                journey.id,
                journey.name,
                journey.domain,
                journey.feature,
                journey.confidence,
                journey.discovered_at.isoformat(),
                journey.discovered_by,
                journey.session_id,
                journey.variant_of,
                json.dumps(journey.tags),
            ),
        )
        for step in journey.steps:
            self.conn.execute(
                """INSERT OR REPLACE INTO steps
                (id, journey_id, step_order, description, url, action_type,
                 element_hint, selectors, event_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    step.id,
                    journey.id,
                    step.order,
                    step.description,
                    step.url,
                    step.action_type,
                    step.element_hint,
                    json.dumps(step.selectors),
                    json.dumps(step.event_ids),
                ),
            )
        self.conn.commit()

    def get_journeys(
        self,
        domain: Optional[str] = None,
        feature: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        query = "SELECT * FROM journeys WHERE 1=1"
        params: list = []
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        if feature:
            query += " AND feature = ?"
            params.append(feature)
        query += " ORDER BY discovered_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_journey_with_steps(self, journey_id: str) -> Optional[Dict]:
        row = self.conn.execute("SELECT * FROM journeys WHERE id = ?", (journey_id,)).fetchone()
        if not row:
            return None
        journey = dict(row)
        steps = self.conn.execute(
            "SELECT * FROM steps WHERE journey_id = ? ORDER BY step_order", (journey_id,)
        ).fetchall()
        journey["steps"] = [dict(s) for s in steps]
        return journey

    def get_all_domains(self) -> List[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT domain FROM journeys WHERE domain != '' ORDER BY domain"
        ).fetchall()
        return [row["domain"] for row in rows]

    def search_journeys(self, query: str, limit: int = 20) -> List[Dict]:
        rows = self.conn.execute(
            """SELECT * FROM journeys
            WHERE name LIKE ? OR domain LIKE ? OR feature LIKE ? OR tags LIKE ?
            ORDER BY discovered_at DESC LIMIT ?""",
            ("%%%s%%" % query, "%%%s%%" % query, "%%%s%%" % query, "%%%s%%" % query, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    # --- Test Run History ---

    def insert_test_run(self, run: Dict) -> None:
        self.conn.execute(
            """INSERT INTO test_runs
            (id, journey_id, base_url, passed, total_steps, passed_steps,
             duration_ms, exit_code, headed, error_message,
             healed, heal_attempts, started_at, finished_at,
             console_errors, network_failures, api_calls,
             step_timings, web_vitals,
             vision_healed, vision_heal_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run["id"], run["journey_id"], run["base_url"],
                1 if run.get("passed") else 0,
                run.get("total_steps", 0), run.get("passed_steps", 0),
                run.get("duration_ms", 0), run.get("exit_code", -1),
                1 if run.get("headed") else 0,
                run.get("error_message", ""),
                1 if run.get("healed") else 0,
                run.get("heal_attempts", 0),
                run.get("started_at", ""), run.get("finished_at", ""),
                json.dumps(run.get("console_errors", [])),
                json.dumps(run.get("network_failures", [])),
                json.dumps(run.get("api_calls", [])),
                json.dumps(run.get("step_timings", {})),
                json.dumps(run.get("web_vitals", {})),
                1 if run.get("vision_healed") else 0,
                run.get("vision_heal_count", 0),
            ),
        )
        self.conn.commit()

    def get_run_diagnostics(self, run_id: str) -> Optional[Dict]:
        """Return console errors, network failures, and API calls for a completed run."""
        row = self.conn.execute(
            """SELECT id, journey_id, passed, started_at, finished_at,
                      console_errors, network_failures, api_calls
               FROM test_runs WHERE id = ?""",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        r = dict(row)
        r["console_errors"] = json.loads(r.get("console_errors") or "[]")
        r["network_failures"] = json.loads(r.get("network_failures") or "[]")
        r["api_calls"] = json.loads(r.get("api_calls") or "[]")
        return r

    def get_test_runs(self, journey_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
        if journey_id:
            rows = self.conn.execute(
                """SELECT tr.*, j.name as journey_name, j.domain
                FROM test_runs tr JOIN journeys j ON tr.journey_id = j.id
                WHERE tr.journey_id = ?
                ORDER BY tr.started_at DESC LIMIT ?""",
                (journey_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT tr.*, j.name as journey_name, j.domain
                FROM test_runs tr JOIN journeys j ON tr.journey_id = j.id
                ORDER BY tr.started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # --- Explorer Sessions ---

    def insert_explorer_session(self, session: Dict) -> None:
        self.conn.execute(
            """INSERT INTO explorer_sessions
            (id, base_url, strategy, status, pages_visited, flows_discovered,
             config_json, results_json, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session["id"], session["base_url"], session.get("strategy", "bfs"),
                session.get("status", "running"),
                session.get("pages_visited", 0), session.get("flows_discovered", 0),
                session.get("config_json", "{}"), session.get("results_json", "{}"),
                session.get("started_at", ""), session.get("finished_at"),
            ),
        )
        self.conn.commit()

    def update_explorer_session(self, session_id: str, updates: Dict) -> None:
        sets = []
        params = []
        for key in ("status", "pages_visited", "flows_discovered",
                     "config_json", "results_json", "finished_at"):
            if key in updates:
                sets.append(f"{key} = ?")
                params.append(updates[key])
        if not sets:
            return
        params.append(session_id)
        self.conn.execute(
            f"UPDATE explorer_sessions SET {', '.join(sets)} WHERE id = ?", params
        )
        self.conn.commit()

    def get_explorer_session(self, session_id: str) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT * FROM explorer_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_explorer_sessions(self, limit: int = 20) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT * FROM explorer_sessions ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_run_stats(self) -> Dict:
        row = self.conn.execute(
            """SELECT
                COUNT(*) as total_runs,
                SUM(passed) as total_passed,
                COUNT(*) - SUM(passed) as total_failed,
                AVG(duration_ms) as avg_duration_ms,
                ROUND(SUM(passed) * 100.0 / MAX(COUNT(*), 1), 1) as pass_rate
            FROM test_runs"""
        ).fetchone()
        return dict(row) if row else {}

    # --- Journey Versioning ---

    def _step_hash(self, steps: List[Dict]) -> str:
        import hashlib
        sig = "|".join(
            f"{s.get('action_type','')}/{s.get('description','')}/{s.get('url','')}"
            for s in sorted(steps, key=lambda x: x.get("step_order", 0))
        )
        return hashlib.sha256(sig.encode()).hexdigest()[:16]

    def record_journey_version(self, journey_id: str) -> Optional[Dict]:
        journey = self.get_journey_with_steps(journey_id)
        if not journey:
            return None

        steps = journey.get("steps", [])
        new_hash = self._step_hash(steps)

        prev = self.conn.execute(
            "SELECT * FROM journey_versions WHERE journey_id = ? ORDER BY version DESC LIMIT 1",
            (journey_id,),
        ).fetchone()

        if prev and dict(prev)["step_hash"] == new_hash:
            return None

        version = (dict(prev)["version"] + 1) if prev else 1
        diff = None
        if prev:
            old_steps = json.loads(dict(prev)["steps_json"])
            diff = self._compute_diff(old_steps, steps)

        import uuid
        vid = str(uuid.uuid4())
        self.conn.execute(
            """INSERT INTO journey_versions
            (id, journey_id, version, step_hash, step_count, steps_json, diff_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (vid, journey_id, version, new_hash, len(steps),
             json.dumps(steps), json.dumps(diff) if diff else None),
        )
        self.conn.commit()
        return {"version": version, "diff": diff}

    def _compute_diff(self, old_steps: List[Dict], new_steps: List[Dict]) -> Dict:
        old_descs = [s.get("description", "") for s in old_steps]
        new_descs = [s.get("description", "") for s in new_steps]

        added = [d for d in new_descs if d not in old_descs]
        removed = [d for d in old_descs if d not in new_descs]

        return {
            "old_step_count": len(old_steps),
            "new_step_count": len(new_steps),
            "added": added,
            "removed": removed,
            "changed": len(added) > 0 or len(removed) > 0,
            "summary": self._diff_summary(old_steps, new_steps, added, removed),
        }

    def _diff_summary(self, old: List, new: List, added: List, removed: List) -> str:
        parts = []
        delta = len(new) - len(old)
        if delta > 0:
            parts.append(f"{delta} step(s) added")
        elif delta < 0:
            parts.append(f"{abs(delta)} step(s) removed")
        if added:
            parts.append(f"New: {', '.join(added[:3])}")
        if removed:
            parts.append(f"Gone: {', '.join(removed[:3])}")
        return " | ".join(parts) if parts else "No changes"

    def get_journey_versions(self, journey_id: str, limit: int = 20) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT * FROM journey_versions WHERE journey_id = ? ORDER BY version DESC LIMIT ?",
            (journey_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Human-in-the-loop Label Corrections ---

    def update_journey_label(self, journey_id: str, updates: Dict) -> Optional[Dict]:
        journey = self.conn.execute("SELECT * FROM journeys WHERE id = ?", (journey_id,)).fetchone()
        if not journey:
            return None
        journey = dict(journey)

        import uuid
        allowed = {"name", "domain", "feature", "tags"}
        sets = []
        params = []
        for field, new_val in updates.items():
            if field not in allowed:
                continue
            old_val = journey.get(field, "")
            if field == "tags":
                new_val_str = json.dumps(new_val) if isinstance(new_val, list) else new_val
                old_val = journey.get("tags", "[]")
            else:
                new_val_str = new_val

            if str(old_val) != str(new_val_str):
                sets.append(f"{field} = ?")
                params.append(new_val_str)

                self.conn.execute(
                    "INSERT INTO label_corrections (id, journey_id, field, old_value, new_value) VALUES (?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), journey_id, field, str(old_val), str(new_val_str)),
                )

        if sets:
            sets.append("updated_at = datetime('now')")
            params.append(journey_id)
            self.conn.execute(f"UPDATE journeys SET {', '.join(sets)} WHERE id = ?", params)
            self.conn.commit()

        return self.get_journey_with_steps(journey_id)

    def get_label_corrections(self, limit: int = 100) -> List[Dict]:
        rows = self.conn.execute(
            """SELECT lc.*, j.name as journey_name
            FROM label_corrections lc
            LEFT JOIN journeys j ON j.id = lc.journey_id
            ORDER BY lc.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_domain_vocabulary(self) -> Dict:
        """Return the learned domain/feature vocabulary from all corrections and current data."""
        domains = [r["domain"] for r in self.conn.execute(
            "SELECT DISTINCT domain FROM journeys WHERE domain != ''"
        ).fetchall()]
        features = [r["feature"] for r in self.conn.execute(
            "SELECT DISTINCT feature FROM journeys WHERE feature != ''"
        ).fetchall()]
        corrections = self.get_label_corrections(limit=200)
        return {
            "domains": sorted(set(domains)),
            "features": sorted(set(features)),
            "corrections_count": len(corrections),
        }

    # --- HITL Review Queue ---

    def set_review_status(
        self, journey_id: str, status: str, reviewer: str = "", note: str = ""
    ) -> bool:
        row = self.conn.execute("SELECT id FROM journeys WHERE id = ?", (journey_id,)).fetchone()
        if not row:
            return False
        self.conn.execute(
            """UPDATE journeys
            SET review_status = ?, reviewed_by = ?, reviewed_at = datetime('now'),
                review_note = ?, updated_at = datetime('now')
            WHERE id = ?""",
            (status, reviewer, note, journey_id),
        )
        self.conn.commit()
        return True

    def get_review_queue(
        self,
        status: Optional[str] = None,
        domain: Optional[str] = None,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict]:
        query = "SELECT * FROM journeys WHERE 1=1"
        params: list = []
        if status:
            query += " AND review_status = ?"
            params.append(status)
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        if min_confidence is not None:
            query += " AND confidence >= ?"
            params.append(min_confidence)
        if max_confidence is not None:
            query += " AND confidence <= ?"
            params.append(max_confidence)
        query += " ORDER BY confidence ASC, discovered_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self.conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            j = dict(row)
            step_count = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM steps WHERE journey_id = ?", (j["id"],)
            ).fetchone()
            j["step_count"] = step_count["cnt"] if step_count else 0
            result.append(j)
        return result

    def get_review_stats(self) -> Dict:
        rows = self.conn.execute(
            """SELECT review_status, COUNT(*) as count,
                      AVG(confidence) as avg_confidence
            FROM journeys GROUP BY review_status"""
        ).fetchall()
        stats = {r["review_status"]: {"count": r["count"], "avg_confidence": r["avg_confidence"]}
                 for r in rows}
        total = sum(s["count"] for s in stats.values())
        approved = stats.get("approved", {}).get("count", 0) + stats.get("auto_approved", {}).get("count", 0)
        corrected = self.conn.execute(
            "SELECT COUNT(DISTINCT journey_id) as cnt FROM label_corrections"
        ).fetchone()
        corrected_count = corrected["cnt"] if corrected else 0
        return {
            "by_status": stats,
            "total": total,
            "approved_count": approved,
            "corrected_count": corrected_count,
            "accuracy_rate": round(1 - (corrected_count / max(total, 1)), 2),
        }

    def log_review_action(
        self, journey_id: str, action: str, reviewer: str = "",
        note: str = "", changes: Optional[Dict] = None,
    ) -> None:
        import uuid
        self.conn.execute(
            """INSERT INTO review_actions (id, journey_id, action, reviewer, note, changes_json)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), journey_id, action, reviewer, note,
             json.dumps(changes) if changes else "{}"),
        )
        self.conn.commit()

    def get_review_actions(self, journey_id: str, limit: int = 50) -> List[Dict]:
        rows = self.conn.execute(
            """SELECT ra.*, j.name as journey_name
            FROM review_actions ra
            LEFT JOIN journeys j ON j.id = ra.journey_id
            WHERE ra.journey_id = ?
            ORDER BY ra.created_at DESC LIMIT ?""",
            (journey_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def batch_update_review_status(
        self, journey_ids: List[str], status: str, reviewer: str = ""
    ) -> int:
        import uuid
        count = 0
        for jid in journey_ids:
            updated = self.conn.execute(
                """UPDATE journeys
                SET review_status = ?, reviewed_by = ?, reviewed_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ?""",
                (status, reviewer, jid),
            ).rowcount
            if updated:
                count += updated
                self.conn.execute(
                    """INSERT INTO review_actions (id, journey_id, action, reviewer, note)
                    VALUES (?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), jid, "batch_" + status, reviewer, "Batch operation"),
                )
        self.conn.commit()
        return count

    def get_hitl_config(self) -> Dict:
        rows = self.conn.execute("SELECT key, value FROM hitl_config").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def set_hitl_config(self, key: str, value: str) -> None:
        self.conn.execute(
            """INSERT INTO hitl_config (key, value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = datetime('now')""",
            (key, value, value),
        )
        self.conn.commit()

    def get_correction_patterns(self, limit: int = 20) -> List[Dict]:
        rows = self.conn.execute(
            """SELECT field, old_value, new_value, COUNT(*) as count
            FROM label_corrections
            GROUP BY field, old_value, new_value
            ORDER BY count DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_accuracy_trend(self, days: int = 30) -> List[Dict]:
        rows = self.conn.execute(
            """SELECT date(created_at) as day,
                      COUNT(*) as total,
                      SUM(CASE WHEN review_status IN ('auto_approved') THEN 1 ELSE 0 END) as auto_approved,
                      SUM(CASE WHEN review_status = 'approved' THEN 1 ELSE 0 END) as human_approved,
                      SUM(CASE WHEN review_status = 'rejected' THEN 1 ELSE 0 END) as rejected
            FROM journeys
            WHERE created_at >= datetime('now', ?)
            GROUP BY day ORDER BY day""",
            (f"-{days} days",),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Visual Regression ---

    def upsert_visual_baseline(self, journey_id: str, step_order: int, b64: str, w: int = 0, h: int = 0) -> None:
        import uuid
        self.conn.execute(
            """INSERT INTO visual_baselines (id, journey_id, step_order, baseline_b64, width, height)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(journey_id, step_order) DO UPDATE SET
                baseline_b64=excluded.baseline_b64, width=excluded.width, height=excluded.height,
                updated_at=datetime('now')""",
            (str(uuid.uuid4()), journey_id, step_order, b64, w, h),
        )
        self.conn.commit()

    def get_visual_baseline(self, journey_id: str, step_order: int) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT * FROM visual_baselines WHERE journey_id = ? AND step_order = ?",
            (journey_id, step_order),
        ).fetchone()
        return dict(row) if row else None

    def get_visual_baselines(self, journey_id: str) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT * FROM visual_baselines WHERE journey_id = ? ORDER BY step_order",
            (journey_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def insert_visual_diff(self, diff: Dict) -> None:
        self.conn.execute(
            """INSERT INTO visual_diffs (id, run_id, journey_id, step_order, diff_percent, diff_b64, passed)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (diff["id"], diff["run_id"], diff["journey_id"], diff["step_order"],
             diff["diff_percent"], diff.get("diff_b64", ""), 1 if diff["passed"] else 0),
        )
        self.conn.commit()

    def get_visual_diffs(self, run_id: str) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT * FROM visual_diffs WHERE run_id = ? ORDER BY step_order", (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- API Tests ---

    def insert_api_test(self, test: Dict) -> None:
        self.conn.execute(
            """INSERT INTO api_tests (id, name, description, method, url, headers_json, body_json, assertions_json, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (test["id"], test["name"], test.get("description", ""),
             test["method"], test["url"],
             json.dumps(test.get("headers", {})),
             json.dumps(test.get("body", "")),
             json.dumps(test.get("assertions", [])),
             json.dumps(test.get("tags", []))),
        )
        self.conn.commit()

    def get_api_tests(self, limit: int = 50) -> List[Dict]:
        rows = self.conn.execute("SELECT * FROM api_tests ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["headers"] = json.loads(d.pop("headers_json", "{}"))
            d["body"] = json.loads(d.pop("body_json", '""'))
            d["assertions"] = json.loads(d.pop("assertions_json", "[]"))
            d["tags"] = json.loads(d.get("tags", "[]"))
            result.append(d)
        return result

    def get_api_test(self, test_id: str) -> Optional[Dict]:
        row = self.conn.execute("SELECT * FROM api_tests WHERE id = ?", (test_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["headers"] = json.loads(d.pop("headers_json", "{}"))
        d["body"] = json.loads(d.pop("body_json", '""'))
        d["assertions"] = json.loads(d.pop("assertions_json", "[]"))
        d["tags"] = json.loads(d.get("tags", "[]"))
        return d

    def delete_api_test(self, test_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM api_tests WHERE id = ?", (test_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def insert_api_test_run(self, run: Dict) -> None:
        self.conn.execute(
            """INSERT INTO api_test_runs (id, test_id, passed, status_code, response_time_ms, response_body, assertion_results, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run["id"], run["test_id"], 1 if run["passed"] else 0,
             run.get("status_code", 0), run.get("response_time_ms", 0),
             run.get("response_body", "")[:10000],
             json.dumps(run.get("assertion_results", [])),
             run.get("error_message", "")),
        )
        self.conn.commit()

    def get_api_test_runs(self, test_id: str, limit: int = 20) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT * FROM api_test_runs WHERE test_id = ? ORDER BY created_at DESC LIMIT ?",
            (test_id, limit),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["assertion_results"] = json.loads(d.get("assertion_results", "[]"))
            result.append(d)
        return result

    # --- Scheduled Monitors ---

    def insert_monitor(self, mon: Dict) -> None:
        self.conn.execute(
            """INSERT INTO scheduled_monitors
            (id, name, monitor_type, target_id, base_url, cron_expr, browser, enabled, webhook_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mon["id"], mon["name"], mon.get("monitor_type", "journey"),
             mon["target_id"], mon.get("base_url", ""),
             mon.get("cron_expr", "0 */6 * * *"), mon.get("browser", "chromium"),
             1 if mon.get("enabled", True) else 0, mon.get("webhook_url", "")),
        )
        self.conn.commit()

    def get_monitors(self, limit: int = 50) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT * FROM scheduled_monitors ORDER BY created_at DESC LIMIT ?", (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_monitor(self, monitor_id: str) -> Optional[Dict]:
        row = self.conn.execute("SELECT * FROM scheduled_monitors WHERE id = ?", (monitor_id,)).fetchone()
        return dict(row) if row else None

    def update_monitor(self, monitor_id: str, updates: Dict) -> None:
        allowed = {"name", "cron_expr", "browser", "enabled", "webhook_url", "base_url", "last_run_at", "last_status"}
        sets, params = [], []
        for k, v in updates.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                params.append(v)
        if sets:
            params.append(monitor_id)
            self.conn.execute(f"UPDATE scheduled_monitors SET {', '.join(sets)} WHERE id = ?", params)
            self.conn.commit()

    def delete_monitor(self, monitor_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM scheduled_monitors WHERE id = ?", (monitor_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def insert_alert(self, alert: Dict) -> None:
        self.conn.execute(
            "INSERT INTO monitor_alerts (id, monitor_id, alert_type, message) VALUES (?, ?, ?, ?)",
            (alert["id"], alert["monitor_id"], alert.get("alert_type", "failure"), alert["message"]),
        )
        self.conn.commit()

    def get_alerts(self, limit: int = 50) -> List[Dict]:
        rows = self.conn.execute(
            """SELECT ma.*, sm.name as monitor_name
            FROM monitor_alerts ma LEFT JOIN scheduled_monitors sm ON sm.id = ma.monitor_id
            ORDER BY ma.created_at DESC LIMIT ?""", (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def acknowledge_alert(self, alert_id: str) -> None:
        self.conn.execute("UPDATE monitor_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
        self.conn.commit()

    # --- Users / Team ---

    def insert_user(self, user: Dict) -> None:
        self.conn.execute(
            "INSERT INTO users (id, username, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
            (user["id"], user["username"], user.get("email", ""),
             user["password_hash"], user.get("role", "member")),
        )
        self.conn.commit()

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        row = self.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    def get_user(self, user_id: str) -> Optional[Dict]:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_users(self) -> List[Dict]:
        rows = self.conn.execute("SELECT id, username, email, role, created_at, last_login FROM users ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def update_user_login(self, user_id: str) -> None:
        self.conn.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (user_id,))
        self.conn.commit()

    # --- Flaky Test Management ---

    def analyze_flaky_tests(self) -> List[Dict]:
        """Identify journeys with inconsistent pass/fail results."""
        rows = self.conn.execute("""
            SELECT journey_id, j.name as journey_name,
                   COUNT(*) as total_runs,
                   SUM(passed) as passes,
                   COUNT(*) - SUM(passed) as failures,
                   ROUND((COUNT(*) - SUM(passed)) * 100.0 / MAX(COUNT(*), 1), 1) as fail_rate,
                   MAX(tr.started_at) as last_run
            FROM test_runs tr
            JOIN journeys j ON j.id = tr.journey_id
            GROUP BY journey_id
            HAVING total_runs >= 2 AND passes > 0 AND failures > 0
            ORDER BY fail_rate DESC
        """).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            flake_rate = d["fail_rate"]
            d["flake_rate"] = flake_rate
            d["is_flaky"] = 0 < flake_rate < 100
            import uuid
            self.conn.execute(
                """INSERT INTO flaky_tests (id, journey_id, flake_rate, total_runs, total_failures, last_analyzed)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(journey_id) DO UPDATE SET
                    flake_rate=excluded.flake_rate, total_runs=excluded.total_runs,
                    total_failures=excluded.total_failures, last_analyzed=datetime('now')""",
                (str(uuid.uuid4()), d["journey_id"], flake_rate, d["total_runs"], d["failures"]),
            )
            results.append(d)
        self.conn.commit()
        return results

    def get_flaky_tests(self) -> List[Dict]:
        rows = self.conn.execute(
            """SELECT ft.*, j.name as journey_name
            FROM flaky_tests ft JOIN journeys j ON j.id = ft.journey_id
            ORDER BY ft.flake_rate DESC""",
        ).fetchall()
        return [dict(r) for r in rows]

    def quarantine_test(self, journey_id: str, quarantine: bool = True) -> None:
        self.conn.execute(
            "UPDATE flaky_tests SET quarantined = ? WHERE journey_id = ?",
            (1 if quarantine else 0, journey_id),
        )
        self.conn.commit()

    def get_run_history_for_journey(self, journey_id: str, limit: int = 30) -> List[Dict]:
        rows = self.conn.execute(
            """SELECT id, passed, duration_ms, browser, device, error_message, started_at
            FROM test_runs WHERE journey_id = ? ORDER BY started_at DESC LIMIT ?""",
            (journey_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Explorations ---

    def insert_exploration(self, data: Dict) -> None:
        self.conn.execute(
            """INSERT INTO explorations
            (id, journey_id, base_url, total_variants, bugs_found, results_json, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                data["id"],
                data["journey_id"],
                data.get("base_url", ""),
                data.get("total_variants", 0),
                data.get("bugs_found", 0),
                data.get("results_json", "[]"),
                data.get("finished_at", ""),
            ),
        )
        self.conn.commit()

    def get_exploration(self, exploration_id: str) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT * FROM explorations WHERE id = ?", (exploration_id,)
        ).fetchone()
        if not row:
            return None
        r = dict(row)
        r["results_json"] = json.loads(r.get("results_json") or "[]")
        return r

    def get_explorations_for_journey(self, journey_id: str) -> List[Dict]:
        rows = self.conn.execute(
            """SELECT id, journey_id, base_url, total_variants, bugs_found, started_at, finished_at
            FROM explorations WHERE journey_id = ? ORDER BY started_at DESC""",
            (journey_id,),
        ).fetchall()
        return [dict(r) for r in rows]

