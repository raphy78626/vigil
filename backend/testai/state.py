"""Shared application state for TestAI-Pro. Avoids circular imports between server and routers."""

from __future__ import annotations

import sys
from pathlib import Path

from testai.storage.db import Database
from testai.llm import get_provider

db = Database()
db.connect()

llm = get_provider()

from testai.query.coverage import CoverageAnalyzer
from testai.export.playwright import PlaywrightExporter
from testai.export.cypress import CypressExporter
from testai.export.selenium import SeleniumExporter
from testai.healing import OllamaHealer
from testai.hitl.review import ReviewManager
from testai.hitl.learner import LabelLearner
from testai.visual import VisualRegression
from testai.api_testing import APITestRunner
from testai.monitoring import MonitorScheduler
from testai.team import TeamAuth
from testai.integrations import SlackBot
from testai.cluster.noise_filter import NoiseFilter
from testai.cluster.merger import JourneyMerger
from testai.cluster.suite_gen import SuiteGenerator
from testai.credentials import CredentialManager
from testai.capture import RichEventProcessor, ShadowDOMHandler

coverage_analyzer = CoverageAnalyzer(db)
playwright_exporter = PlaywrightExporter()
cypress_exporter = CypressExporter()
selenium_exporter = SeleniumExporter()
ollama_healer = OllamaHealer()
review_manager = ReviewManager(db)
label_learner = LabelLearner(db)
visual_regression = VisualRegression()
api_test_runner = APITestRunner()
monitor_scheduler = MonitorScheduler()
team_auth = TeamAuth(db)
slack_bot = SlackBot()
noise_filter = NoiseFilter()
journey_merger = JourneyMerger()
suite_generator = SuiteGenerator()
credential_manager = CredentialManager()
rich_event_processor = RichEventProcessor()
shadow_dom_handler = ShadowDOMHandler()

try:
    team_auth.ensure_admin_exists()
except Exception as _e:
    print(f"[warn] team auth init: {_e}", file=sys.stderr)

try:
    monitor_scheduler.start(db)
except Exception:
    pass


DEVICE_PROFILES = {
    "iphone_14": {"width": 390, "height": 844, "device_scale_factor": 3, "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"},
    "iphone_14_pro_max": {"width": 430, "height": 932, "device_scale_factor": 3, "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"},
    "pixel_7": {"width": 412, "height": 915, "device_scale_factor": 2.625, "user_agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"},
    "galaxy_s23": {"width": 360, "height": 780, "device_scale_factor": 3, "user_agent": "Mozilla/5.0 (Linux; Android 13; SM-S911B) AppleWebKit/537.36"},
    "ipad_pro_11": {"width": 834, "height": 1194, "device_scale_factor": 2, "user_agent": "Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15"},
    "ipad_mini": {"width": 768, "height": 1024, "device_scale_factor": 2, "user_agent": "Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15"},
}

SUPPORTED_BROWSERS = ["chromium", "firefox", "webkit"]
