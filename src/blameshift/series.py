"""Data model and input loaders for blameshift.

A latency series is an ordered list of :class:`SeriesPoint` (one latency
sample per timestamp, values in milliseconds). A change log is a list of
:class:`ChangeEvent` (deploys, commits, config changes) with timestamps.

Loaders accept:

* series CSV with header ``timestamp,value`` where ``timestamp`` is either
  epoch seconds (int or float) or an ISO-8601 datetime string;
* changes JSON, either a top-level list of objects or an object with a
  ``"changes"`` key, each object having ``id``, ``timestamp``, ``kind``,
  ``title`` and ``author``.

All malformed input raises :class:`InputError` with a message that names the
file, the location of the problem, and what was expected.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class InputError(ValueError):
    """Raised when an input file is missing, malformed, or inconsistent."""


@dataclass(frozen=True)
class SeriesPoint:
    """One latency sample. ``timestamp`` is epoch seconds, ``value`` is ms."""

    timestamp: float
    value: float


@dataclass(frozen=True)
class ChangeEvent:
    """One recorded change (deploy, commit, config edit, ...)."""

    id: str
    timestamp: float
    kind: str
    title: str
    author: str


def parse_timestamp(raw: object, *, where: str) -> float:
    """Parse epoch seconds or an ISO-8601 datetime into epoch seconds.

    ``where`` is used in the error message to locate the bad value.
    """
    if isinstance(raw, bool):
        raise InputError(f"{where}: expected a timestamp, got boolean {raw!r}")
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise InputError(f"{where}: empty timestamp")
        try:
            return float(text)
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise InputError(
                f"{where}: cannot parse timestamp {text!r}; expected epoch "
                "seconds or an ISO-8601 datetime"
            ) from None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    raise InputError(f"{where}: expected a timestamp, got {type(raw).__name__}")


def _parse_value(raw: object, *, where: str) -> float:
    if isinstance(raw, bool):
        raise InputError(f"{where}: expected a numeric latency, got {raw!r}")
    try:
        value = float(raw)  # accepts int/float/numeric strings
    except (TypeError, ValueError):
        raise InputError(
            f"{where}: cannot parse latency value {raw!r}; expected a number"
        ) from None
    if value != value:  # NaN
        raise InputError(f"{where}: latency value is NaN")
    return value


def load_series_csv(path: str | Path) -> list[SeriesPoint]:
    """Load a latency series from ``timestamp,value`` CSV.

    Rows are sorted by timestamp. Timestamps must be unique.
    """
    path = Path(path)
    if not path.is_file():
        raise InputError(
            f"series file not found: {path}; check the path, or generate "
            "demo data with `blameshift simulate --out DIR`"
        )

    points: list[SeriesPoint] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise InputError(f"{path}: file is empty") from None
        header = [col.strip().lower() for col in header]
        if header[:2] != ["timestamp", "value"]:
            raise InputError(
                f"{path}: expected header 'timestamp,value', got "
                f"{','.join(header)!r}"
            )
        for lineno, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != 2:
                raise InputError(
                    f"{path}: line {lineno}: expected 2 columns "
                    f"(timestamp,value), got {len(row)}"
                )
            where = f"{path}: line {lineno}"
            ts = parse_timestamp(row[0], where=where)
            value = _parse_value(row[1], where=where)
            points.append(SeriesPoint(timestamp=ts, value=value))

    if not points:
        raise InputError(f"{path}: no data rows found")

    points.sort(key=lambda p: p.timestamp)
    for prev, cur in zip(points, points[1:]):
        if cur.timestamp == prev.timestamp:
            raise InputError(
                f"{path}: duplicate timestamp "
                f"{datetime.fromtimestamp(cur.timestamp, timezone.utc).isoformat()}"
            )
    return points


def load_changes_json(path: str | Path) -> list[ChangeEvent]:
    """Load change events from JSON (a list, or an object with ``changes``)."""
    path = Path(path)
    if not path.is_file():
        raise InputError(
            f"changes file not found: {path}; check the path, or generate "
            "demo data with `blameshift simulate --out DIR`"
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"{path}: invalid JSON: {exc}") from None

    if isinstance(payload, dict):
        if "changes" not in payload:
            raise InputError(f"{path}: expected a 'changes' key")
        payload = payload["changes"]
    if not isinstance(payload, list):
        raise InputError(f"{path}: expected a JSON list of change events")

    required = ("id", "timestamp", "kind", "title", "author")
    events: list[ChangeEvent] = []
    for i, item in enumerate(payload):
        where = f"{path}: change[{i}]"
        if not isinstance(item, dict):
            raise InputError(f"{where}: expected an object")
        missing = [key for key in required if key not in item]
        if missing:
            raise InputError(f"{where}: missing required field(s): {', '.join(missing)}")
        for key in ("id", "kind", "title", "author"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise InputError(f"{where}: field {key!r} must be a non-empty string")
        ts = parse_timestamp(item["timestamp"], where=where)
        events.append(
            ChangeEvent(
                id=item["id"].strip(),
                timestamp=ts,
                kind=item["kind"].strip(),
                title=item["title"].strip(),
                author=item["author"].strip(),
            )
        )

    events.sort(key=lambda e: e.timestamp)
    return events
