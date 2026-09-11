from testai.cluster.segmenter import SessionSegmenter
from testai.cluster.grouper import FlowGrouper

# JourneyLabeler requires litellm (a cloud-LLM dependency). Import it lazily
# so the offline pipeline and demo work without the full requirements installed.
def __getattr__(name: str):
    if name == "JourneyLabeler":
        from testai.cluster.labeler import JourneyLabeler
        return JourneyLabeler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["SessionSegmenter", "FlowGrouper", "JourneyLabeler"]
