from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel


class EventType(str, Enum):
    CLICK = "click"
    INPUT = "input"
    NAVIGATION = "navigation"
    SCROLL = "scroll"
    SUBMIT = "submit"
    PAGELOAD = "pageload"
    KEYPRESS = "keypress"
    KEYCOMBO = "keycombo"
    CHANGE = "change"
    FOCUS = "focus"
    DBLCLICK = "dblclick"
    CONTEXTMENU = "contextmenu"
    DRAG = "drag"
    PASTE = "paste"
    COPY = "copy"
    HOVER = "hover"
    PERFORMANCE = "performance"


class ElementSelectors(BaseModel):
    css: str = ""
    xpath: Optional[str] = None
    text: Optional[str] = None
    full_text: Optional[str] = None
    aria_label: Optional[str] = None
    test_id: Optional[str] = None
    test_id_attr: Optional[str] = None
    role: Optional[str] = None
    label: Optional[str] = None
    name: Optional[str] = None
    placeholder: Optional[str] = None
    title: Optional[str] = None
    href: Optional[str] = None
    class_name: Optional[str] = None
    data_attributes: Optional[Dict[str, str]] = None


class ElementContext(BaseModel):
    tag_name: str
    selectors: ElementSelectors
    input_type: Optional[str] = None
    value: Optional[str] = None
    coordinates: Optional[Dict[str, float]] = None


class NavigationContext(BaseModel):
    from_url: str
    to_url: str
    trigger: str


class KeyEventContext(BaseModel):
    key: str = ""
    code: str = ""
    combo: str = ""
    ctrl_key: bool = False
    meta_key: bool = False
    alt_key: bool = False
    shift_key: bool = False


class Event(BaseModel):
    id: str
    timestamp: datetime
    type: EventType
    url: str
    page_title: str = ""
    element: Optional[ElementContext] = None
    navigation: Optional[NavigationContext] = None
    key_event: Optional[KeyEventContext] = None
    tab_id: int = 0
    session_id: str = ""
    screenshot_path: Optional[str] = None
