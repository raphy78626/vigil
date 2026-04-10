from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel


class Step(BaseModel):
    id: str = ""
    journey_id: str = ""
    order: int
    description: str
    event_ids: List[str] = []
    url: str = ""
    action_type: str = ""
    element_hint: Optional[str] = None
    selectors: Dict[str, str] = {}
