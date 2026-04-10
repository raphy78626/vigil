"""Vision-based coordinate healer — screenshot -> LLM -> (x, y) click.

Inspired by Claude's computer use: send a screenshot to a vision-capable LLM,
ask it to locate the target element, and return pixel coordinates for
page.mouse.click(). Used as a last-resort fallback when all CSS/text/ARIA
locators fail.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a visual element locator for web UI testing. You receive a screenshot
of a web page and a description of the element the tester wants to interact with.

Your job: find that element in the screenshot and return its CENTER pixel
coordinates so a testing tool can click there.

Return ONLY valid JSON with this exact structure:
{"x": <int>, "y": <int>, "confidence": <float 0.0-1.0>, "reasoning": "<brief>"}

Rules:
- x and y are pixel coordinates relative to the top-left corner of the screenshot
- Return the CENTER of the target element, not an edge or corner
- confidence: 1.0 = certain, 0.7+ = likely correct, below 0.5 = guessing
- If you cannot find the element at all, return {"x": 0, "y": 0, "confidence": 0.0, "reasoning": "not found"}
- Do NOT return markdown or explanation — only the JSON object
"""


@dataclass
class VisionCoordinate:
    x: int
    y: int
    confidence: float
    reasoning: str = ""


def locate_element(
    llm,
    screenshot_b64: str,
    description: str,
    action_type: str = "click",
    viewport_width: int = 1280,
    viewport_height: int = 720,
) -> Optional[VisionCoordinate]:
    """Send a screenshot to a vision LLM and get back click coordinates.

    Args:
        llm: The LLMProvider instance (must support vision / images).
        screenshot_b64: Base64-encoded PNG screenshot.
        description: Human-readable description of the target element.
        action_type: The intended action (click, fill, etc.).
        viewport_width: Screenshot width in pixels.
        viewport_height: Screenshot height in pixels.

    Returns:
        VisionCoordinate with (x, y, confidence) or None on failure.
    """
    if not llm:
        return None

    status = llm.get_status()
    if not status.get("has_key", False) and status.get("provider") != "ollama":
        return None

    if not status.get("has_vision", False):
        logger.debug("Vision heal skipped — LLM does not support vision")
        return None

    prompt = (
        f"Screenshot dimensions: {viewport_width}x{viewport_height} pixels.\n\n"
        f"Find this element: \"{description}\"\n"
        f"Action to perform: {action_type}\n\n"
        f"Return the CENTER coordinates of the element as JSON."
    )

    try:
        response = llm.ask(
            prompt,
            system=_SYSTEM_PROMPT,
            max_tokens=256,
            images=[screenshot_b64],
        )
    except Exception as e:
        logger.warning("Vision heal LLM call failed: %s", e)
        return None

    if not response:
        return None

    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Vision heal response was not valid JSON: %s", text[:200])
        return None

    x = int(data.get("x", 0))
    y = int(data.get("y", 0))
    confidence = float(data.get("confidence", 0.0))
    reasoning = str(data.get("reasoning", ""))

    if x < 0 or y < 0 or x > viewport_width or y > viewport_height:
        logger.warning("Vision heal returned out-of-bounds coordinates: (%d, %d)", x, y)
        return None

    return VisionCoordinate(x=x, y=y, confidence=confidence, reasoning=reasoning)
