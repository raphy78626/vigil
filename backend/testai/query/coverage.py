"""Coverage Analysis: computes which areas have been explored vs. gaps."""

from __future__ import annotations

from typing import Dict, List, Optional

from testai.storage.db import Database


class CoverageAnalyzer:
    def __init__(self, db: Database):
        self.db = db

    def get_domain_coverage(self) -> List[Dict]:
        rows = self.db.conn.execute(
            """SELECT domain, COUNT(*) as journey_count,
                      AVG(confidence) as avg_confidence,
                      MIN(discovered_at) as first_seen,
                      MAX(discovered_at) as last_seen
            FROM journeys WHERE domain != ''
            GROUP BY domain ORDER BY journey_count DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_feature_coverage(self, domain: Optional[str] = None) -> List[Dict]:
        query = """SELECT domain, feature, COUNT(*) as journey_count,
                          AVG(confidence) as avg_confidence
                   FROM journeys WHERE feature != ''"""
        params: list = []
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        query += " GROUP BY domain, feature ORDER BY journey_count DESC"
        rows = self.db.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_summary(self) -> Dict:
        total = self.db.conn.execute("SELECT COUNT(*) as c FROM journeys").fetchone()
        domains = self.db.conn.execute("SELECT COUNT(DISTINCT domain) as c FROM journeys").fetchone()
        features = self.db.conn.execute("SELECT COUNT(DISTINCT feature) as c FROM journeys").fetchone()
        avg_conf = self.db.conn.execute("SELECT AVG(confidence) as c FROM journeys").fetchone()
        return {
            "total_journeys": total["c"] if total else 0,
            "unique_domains": domains["c"] if domains else 0,
            "unique_features": features["c"] if features else 0,
            "avg_confidence": round(avg_conf["c"], 2) if avg_conf and avg_conf["c"] else 0,
        }
