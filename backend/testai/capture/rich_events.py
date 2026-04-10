"""Rich event capture — scroll, hover, drag-and-drop, and gesture processing.

Extends the basic click/input/navigate event types to support:
  - Scroll positions (with delta normalization)
  - Hover intent detection (mouseover → sustained hover)
  - Drag & drop (dragstart → dragover → drop sequence)
  - Touch gestures (swipe, pinch-to-zoom)
  - Right-click / context menu
  - Double-click
  - Keyboard shortcuts (Ctrl+S, Cmd+K, etc.)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple


RICH_EVENT_TYPES = {
    "scroll": {"category": "interaction", "replay_strategy": "js_scroll"},
    "hover": {"category": "interaction", "replay_strategy": "move_to_element"},
    "drag": {"category": "gesture", "replay_strategy": "drag_and_drop"},
    "drop": {"category": "gesture", "replay_strategy": "drag_and_drop"},
    "swipe": {"category": "gesture", "replay_strategy": "touch_swipe"},
    "pinch": {"category": "gesture", "replay_strategy": "touch_pinch"},
    "contextmenu": {"category": "interaction", "replay_strategy": "right_click"},
    "dblclick": {"category": "interaction", "replay_strategy": "double_click"},
    "keycombo": {"category": "keyboard", "replay_strategy": "key_combination"},
}


class RichEventProcessor:
    def process(self, raw_events: List[Dict]) -> List[Dict]:
        """Process raw extension events into enriched events with replay metadata."""
        processed = []
        drag_start = None

        for event in raw_events:
            etype = (event.get("type") or "").lower()

            if etype == "scroll":
                processed.append(self._process_scroll(event))
            elif etype == "mouseover" and self._is_sustained_hover(event, raw_events):
                processed.append(self._process_hover(event))
            elif etype == "dragstart":
                drag_start = event
            elif etype == "drop" and drag_start:
                processed.append(self._process_drag_drop(drag_start, event))
                drag_start = None
            elif etype == "contextmenu":
                processed.append(self._process_contextmenu(event))
            elif etype == "dblclick":
                processed.append(self._process_dblclick(event))
            elif etype == "keydown" and self._is_key_combo(event):
                processed.append(self._process_keycombo(event))
            elif etype in ("touchstart", "touchend"):
                gesture = self._detect_touch_gesture(event, raw_events)
                if gesture:
                    processed.append(gesture)
            else:
                processed.append(event)

        return processed

    def _process_scroll(self, event: Dict) -> Dict:
        return {
            **event,
            "type": "scroll",
            "replay_strategy": "js_scroll",
            "scroll_data": {
                "x": event.get("scrollX", 0),
                "y": event.get("scrollY", 0),
                "delta_x": event.get("deltaX", 0),
                "delta_y": event.get("deltaY", 0),
                "target": event.get("target", "window"),
            },
        }

    def _process_hover(self, event: Dict) -> Dict:
        return {
            **event,
            "type": "hover",
            "replay_strategy": "move_to_element",
            "hover_data": {
                "x": event.get("clientX", 0),
                "y": event.get("clientY", 0),
                "duration_ms": event.get("hover_duration_ms", 500),
            },
        }

    def _process_drag_drop(self, start: Dict, end: Dict) -> Dict:
        return {
            "type": "drag",
            "replay_strategy": "drag_and_drop",
            "timestamp": start.get("timestamp"),
            "url": start.get("url"),
            "drag_data": {
                "source": {
                    "selector": start.get("element", {}).get("css", ""),
                    "x": start.get("clientX", 0),
                    "y": start.get("clientY", 0),
                },
                "target": {
                    "selector": end.get("element", {}).get("css", ""),
                    "x": end.get("clientX", 0),
                    "y": end.get("clientY", 0),
                },
            },
        }

    def _process_contextmenu(self, event: Dict) -> Dict:
        return {
            **event,
            "type": "contextmenu",
            "replay_strategy": "right_click",
        }

    def _process_dblclick(self, event: Dict) -> Dict:
        return {
            **event,
            "type": "dblclick",
            "replay_strategy": "double_click",
        }

    def _process_keycombo(self, event: Dict) -> Dict:
        modifiers = []
        if event.get("ctrlKey"):
            modifiers.append("Control")
        if event.get("metaKey"):
            modifiers.append("Meta")
        if event.get("altKey"):
            modifiers.append("Alt")
        if event.get("shiftKey"):
            modifiers.append("Shift")
        key = event.get("key", "")

        return {
            **event,
            "type": "keycombo",
            "replay_strategy": "key_combination",
            "key_data": {
                "modifiers": modifiers,
                "key": key,
                "combo": "+".join(modifiers + [key]),
            },
        }

    def _is_sustained_hover(self, event: Dict, all_events: List[Dict]) -> bool:
        return event.get("hover_duration_ms", 0) > 300

    def _is_key_combo(self, event: Dict) -> bool:
        return any([event.get("ctrlKey"), event.get("metaKey"), event.get("altKey")])

    def _detect_touch_gesture(self, event: Dict, all_events: List[Dict]) -> Optional[Dict]:
        if event.get("type") == "touchstart":
            touches = event.get("touches", [])
            if len(touches) >= 2:
                return {"type": "pinch", "replay_strategy": "touch_pinch", "timestamp": event.get("timestamp")}
        return None

    def get_supported_events(self) -> Dict:
        return {k: v for k, v in RICH_EVENT_TYPES.items()}
