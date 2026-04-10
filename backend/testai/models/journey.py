from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from testai.models.step import Step


class Journey(BaseModel):
    id: str = ""
    name: str
    domain: str = ""
    feature: str = ""
    steps: List[Step] = []
    confidence: float = 0.0
    discovered_at: datetime = datetime.now()
    discovered_by: str = ""
    session_id: str = ""
    tags: List[str] = []
    variant_of: Optional[str] = None
