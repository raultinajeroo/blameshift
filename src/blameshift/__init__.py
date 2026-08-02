"""blameshift — find the change that broke your latency.

Detects where a latency time series shifted and ranks which recorded change
(deploy, commit, config edit) most likely caused each regression, emitting
evidence cards with before/after statistics and plain-English rationale.
"""

from .blame import Attribution, EvidenceCard, Suspect, attribute
from .detectors import ChangePoint, detect_change_points
from .series import (
    ChangeEvent,
    InputError,
    SeriesPoint,
    load_changes_json,
    load_series_csv,
)
from .simulate import SimulationResult, generate, write_demo

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Attribution",
    "ChangeEvent",
    "ChangePoint",
    "EvidenceCard",
    "InputError",
    "SeriesPoint",
    "SimulationResult",
    "Suspect",
    "attribute",
    "detect_change_points",
    "generate",
    "load_changes_json",
    "load_series_csv",
    "write_demo",
]
