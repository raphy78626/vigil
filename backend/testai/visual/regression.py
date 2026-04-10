"""Visual regression engine — screenshot diffing with pixel-level comparison."""

from __future__ import annotations

import base64
import io
import uuid
from typing import Dict, List, Optional, Tuple


def _ensure_pillow():
    try:
        from PIL import Image
        return Image
    except ImportError:
        return None


class VisualRegression:
    DIFF_THRESHOLD = 0.5  # percent difference to flag as regression

    def compare_screenshots(
        self, baseline_b64: str, current_b64: str
    ) -> Dict:
        """Compare two base64 PNG screenshots. Returns diff info."""
        Image = _ensure_pillow()
        if not Image:
            return self._fallback_compare(baseline_b64, current_b64)

        baseline_img = Image.open(io.BytesIO(base64.b64decode(baseline_b64))).convert("RGBA")
        current_img = Image.open(io.BytesIO(base64.b64decode(current_b64))).convert("RGBA")

        if baseline_img.size != current_img.size:
            current_img = current_img.resize(baseline_img.size, Image.LANCZOS)

        diff_pixels, total_pixels, diff_img = self._pixel_diff(baseline_img, current_img, Image)
        diff_percent = round((diff_pixels / max(total_pixels, 1)) * 100, 2)
        passed = diff_percent <= self.DIFF_THRESHOLD

        diff_b64 = ""
        if diff_img:
            buf = io.BytesIO()
            diff_img.save(buf, format="PNG")
            diff_b64 = base64.b64encode(buf.getvalue()).decode()

        return {
            "diff_percent": diff_percent,
            "passed": passed,
            "diff_pixels": diff_pixels,
            "total_pixels": total_pixels,
            "diff_b64": diff_b64,
            "dimensions": {"width": baseline_img.size[0], "height": baseline_img.size[1]},
        }

    def _pixel_diff(self, img_a, img_b, Image) -> Tuple[int, int, any]:
        """Count differing pixels and generate a highlighted diff image."""
        w, h = img_a.size
        total = w * h
        diff_count = 0

        px_a = img_a.load()
        px_b = img_b.load()
        diff_img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        px_d = diff_img.load()

        for y in range(h):
            for x in range(w):
                ra, ga, ba, aa = px_a[x, y]
                rb, gb, bb, ab = px_b[x, y]
                if abs(ra - rb) > 10 or abs(ga - gb) > 10 or abs(ba - bb) > 10:
                    diff_count += 1
                    px_d[x, y] = (255, 0, 80, 255)  # red highlight
                else:
                    px_d[x, y] = (ra // 3, ga // 3, ba // 3, 180)  # dimmed original

        return diff_count, total, diff_img

    def _fallback_compare(self, a_b64: str, b_b64: str) -> Dict:
        """Fallback when Pillow is not installed — simple byte comparison."""
        a_bytes = base64.b64decode(a_b64)
        b_bytes = base64.b64decode(b_b64)
        identical = a_bytes == b_bytes
        return {
            "diff_percent": 0.0 if identical else 100.0,
            "passed": identical,
            "diff_pixels": 0 if identical else -1,
            "total_pixels": -1,
            "diff_b64": "",
            "dimensions": {},
            "fallback": True,
        }

    def process_replay_screenshots(
        self, db, journey_id: str, run_id: str, screenshots: List[Dict]
    ) -> List[Dict]:
        """Compare replay screenshots against baselines. Auto-creates baselines if missing."""
        results = []
        for i, shot in enumerate(screenshots):
            step_order = i + 1
            b64 = shot.get("data", "")
            if not b64:
                continue

            baseline = db.get_visual_baseline(journey_id, step_order)

            if not baseline:
                db.upsert_visual_baseline(journey_id, step_order, b64)
                results.append({
                    "step_order": step_order,
                    "status": "baseline_created",
                    "diff_percent": 0.0,
                    "passed": True,
                })
                continue

            diff = self.compare_screenshots(baseline["baseline_b64"], b64)
            diff_record = {
                "id": str(uuid.uuid4()),
                "run_id": run_id,
                "journey_id": journey_id,
                "step_order": step_order,
                "diff_percent": diff["diff_percent"],
                "diff_b64": diff.get("diff_b64", ""),
                "passed": diff["passed"],
            }
            db.insert_visual_diff(diff_record)

            results.append({
                "step_order": step_order,
                "status": "compared",
                "diff_percent": diff["diff_percent"],
                "passed": diff["passed"],
                "has_diff_image": bool(diff.get("diff_b64")),
            })

        return results
