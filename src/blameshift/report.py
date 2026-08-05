"""Rendering: terminal table, JSON export, and a single-file HTML report.

The terminal and JSON outputs carry the same information; the HTML report is
a self-contained file (inline CSS, inline SVG, no JavaScript, no external
assets) suitable for attaching to a ticket or a CI artifact.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from .blame import Attribution, format_duration
from .detectors import ChangePoint
from .series import SeriesPoint


def fmt_time(epoch_seconds: float) -> str:
    """UTC timestamp in a compact ISO-8601 form."""
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def _fmt_signed_pct(pct: float) -> str:
    return f"{'+' if pct >= 0 else ''}{pct:.1f}%"


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------

def render_terminal(
    points: list[SeriesPoint],
    attributions: list[Attribution],
    *,
    metric_label: str = "latency (ms)",
) -> str:
    """Render the full analysis as aligned plain text."""
    lines: list[str] = []
    lines.append(
        f"blameshift: {len(points)} samples, "
        f"{fmt_time(points[0].timestamp)} -> {fmt_time(points[-1].timestamp)}"
    )
    lines.append(f"metric: {metric_label}")
    lines.append("")

    cps = [a.change_point for a in attributions]
    if not cps:
        lines.append("No change points detected. The series looks stable.")
        return "\n".join(lines)

    lines.append(f"Detected {len(cps)} change point(s):")
    header = (
        f"{'#':>3}  {'time':<20}  {'direction':<11}  {'effect':>9}  "
        f"{'effect%':>8}  {'conf':>5}  top suspect"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for n, attr in enumerate(attributions, start=1):
        cp = attr.change_point
        top = attr.top_suspect
        if top is not None:
            suspect = f"{top.event.id} (score {top.score:.2f})"
        elif attr.unattributed_reason:
            suspect = "unattributed"
        else:
            suspect = "-"
        lines.append(
            f"{n:>3}  {fmt_time(cp.timestamp):<20}  {cp.direction:<11}  "
            f"{cp.effect_ms:>+8.1f}ms  {_fmt_signed_pct(cp.effect_pct):>8}  "
            f"{cp.confidence:>5.2f}  {suspect}"
        )
    lines.append("")

    for n, attr in enumerate(attributions, start=1):
        cp = attr.change_point
        lines.append(f"[change point {n}] {fmt_time(cp.timestamp)} — {cp.direction}")
        lines.append(
            f"  median {cp.median_before:.1f}ms -> {cp.median_after:.1f}ms "
            f"({_fmt_signed_pct(cp.effect_pct)}), z={cp.z:.1f}, "
            f"persistence {cp.persist_count}/{cp.window}"
        )
        if attr.card is not None:
            card = attr.card
            lines.append(f"  evidence card:")
            lines.append(
                f"    suspect : {card.change_id} — {card.title} ({card.kind})"
            )
            lines.append(f"    author  : {card.author}")
            lines.append(
                f"    score   : {card.score:.2f} "
                f"(temporal {card.temporal_score:.2f} + "
                f"effect {card.effect_score:.2f} + "
                f"persistence {card.persistence_score:.2f})"
            )
            lines.append(f"    why     : {card.rationale}")
        elif attr.unattributed_reason:
            lines.append(f"  {attr.unattributed_reason}")
        else:
            lines.append("  improvement — no blame assigned")
        if len(attr.suspects) > 1:
            lines.append("  other candidates:")
            for s in attr.suspects[1:4]:
                lines.append(
                    f"    {s.event.id} "
                    f"(score {s.score:.2f}, {format_duration(s.dt_seconds)} before)"
                )
        lines.append("")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def to_json_dict(
    points: list[SeriesPoint],
    attributions: list[Attribution],
    *,
    metric_label: str = "latency (ms)",
) -> dict:
    """Build the JSON-serializable result document."""
    change_points: list[dict] = []
    for attr in attributions:
        cp: ChangePoint = attr.change_point
        entry: dict = {
            "index": cp.index,
            "timestamp": cp.timestamp,
            "time_utc": fmt_time(cp.timestamp),
            "direction": cp.direction,
            "effect_ms": round(cp.effect_ms, 4),
            "effect_pct": round(cp.effect_pct, 4),
            "confidence": round(cp.confidence, 4),
            "z": round(cp.z, 4),
            "median_before_ms": round(cp.median_before, 4),
            "median_after_ms": round(cp.median_after, 4),
            "persistence": round(cp.persistence, 4),
            "persist_count": cp.persist_count,
            "window": cp.window,
            "attribution": None,
        }
        if attr.card is not None:
            card = attr.card
            entry["attribution"] = {
                "change_id": card.change_id,
                "kind": card.kind,
                "title": card.title,
                "author": card.author,
                "dt_seconds": card.dt_seconds,
                "score": round(card.score, 4),
                "score_breakdown": {
                    "temporal": round(card.temporal_score, 4),
                    "effect": round(card.effect_score, 4),
                    "persistence": round(card.persistence_score, 4),
                },
                "rationale": card.rationale,
            }
        elif attr.unattributed_reason:
            entry["attribution"] = {"unattributed": attr.unattributed_reason}
        entry["suspects"] = [
            {
                "change_id": s.event.id,
                "kind": s.event.kind,
                "title": s.event.title,
                "author": s.event.author,
                "dt_seconds": s.dt_seconds,
                "score": round(s.score, 4),
            }
            for s in attr.suspects
        ]
        change_points.append(entry)

    return {
        "tool": "blameshift",
        "version": _version(),
        "metric": metric_label,
        "samples": len(points),
        "range_utc": [fmt_time(points[0].timestamp), fmt_time(points[-1].timestamp)],
        "change_points": change_points,
    }


def _version() -> str:
    from . import __version__

    return __version__


def write_json(doc: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_HTML_CSS = """
:root { color-scheme: light; }
body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       margin: 0 auto; max-width: 960px; padding: 32px 24px; color: #1c2430;
       background: #fbfbfd; line-height: 1.5; }
h1 { font-size: 1.4rem; margin: 0 0 4px; }
h2 { font-size: 1.05rem; margin: 28px 0 8px; color: #344054; }
.meta { color: #667085; font-size: 0.85rem; margin-bottom: 20px; }
table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #e4e7ec; }
th { color: #475467; font-weight: 600; background: #f2f4f7; }
tr:last-child td { border-bottom: none; }
.regression { color: #b42318; font-weight: 600; }
.improvement { color: #067647; font-weight: 600; }
.card { border: 1px solid #e4e7ec; border-left: 4px solid #b42318; border-radius: 6px;
        padding: 12px 16px; margin: 12px 0; background: #ffffff; }
.card h3 { margin: 0 0 6px; font-size: 0.95rem; }
.card .scores { color: #667085; font-size: 0.8rem; margin: 6px 0; }
.card p { margin: 6px 0 0; font-size: 0.88rem; }
svg { display: block; width: 100%; height: auto; background: #ffffff;
      border: 1px solid #e4e7ec; border-radius: 6px; }
.stable { color: #067647; font-weight: 600; }
"""


def _sparkline_svg(points: list[SeriesPoint], change_points: list[ChangePoint]) -> str:
    """Inline SVG of the series with change points marked. No JS."""
    width, height, pad = 920, 220, 12
    values = [p.value for p in points]
    v_min, v_max = min(values), max(values)
    span = (v_max - v_min) or 1.0
    n = len(values)

    def x_of(i: int) -> float:
        return pad + (width - 2 * pad) * i / max(n - 1, 1)

    def y_of(v: float) -> float:
        return height - pad - (height - 2 * pad) * (v - v_min) / span

    polyline = " ".join(
        f"{x_of(i):.1f},{y_of(v):.1f}" for i, v in enumerate(values)
    )
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="latency series with change points">',
        f'<polyline points="{polyline}" fill="none" stroke="#2e5eaa" '
        f'stroke-width="1.2"/>',
    ]
    for cp in change_points:
        x = x_of(cp.index)
        color = "#b42318" if cp.direction == "regression" else "#067647"
        parts.append(
            f'<line x1="{x:.1f}" y1="{pad}" x2="{x:.1f}" y2="{height - pad}" '
            f'stroke="{color}" stroke-width="1" stroke-dasharray="4 3"/>'
        )
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y_of(values[cp.index]):.1f}" r="3.5" '
            f'fill="{color}"/>'
        )
    parts.append(
        f'<text x="{pad}" y="{pad + 4}" font-size="10" fill="#98a2b3">'
        f'{v_max:.0f}ms</text>'
    )
    parts.append(
        f'<text x="{pad}" y="{height - 4}" font-size="10" fill="#98a2b3">'
        f'{v_min:.0f}ms</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def render_html(
    points: list[SeriesPoint],
    attributions: list[Attribution],
    *,
    metric_label: str = "latency (ms)",
    title: str = "blameshift report",
) -> str:
    """Render a single self-contained HTML report file."""
    esc = html.escape
    cps = [a.change_point for a in attributions]

    rows = []
    for n, attr in enumerate(attributions, start=1):
        cp = attr.change_point
        top = attr.top_suspect
        if top is not None:
            suspect = f"{esc(top.event.id)} (score {top.score:.2f})"
        elif attr.unattributed_reason:
            suspect = "unattributed"
        else:
            suspect = "-"
        rows.append(
            "<tr>"
            f"<td>{n}</td>"
            f"<td>{esc(fmt_time(cp.timestamp))}</td>"
            f'<td class="{cp.direction}">{cp.direction}</td>'
            f"<td>{cp.effect_ms:+.1f}ms</td>"
            f"<td>{_fmt_signed_pct(cp.effect_pct)}</td>"
            f"<td>{cp.confidence:.2f}</td>"
            f"<td>{suspect}</td>"
            "</tr>"
        )

    if rows:
        table = (
            "<table><thead><tr><th>#</th><th>time</th><th>direction</th>"
            "<th>effect</th><th>effect %</th><th>conf</th>"
            "<th>top suspect</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    else:
        table = '<p class="stable">No change points detected. The series looks stable.</p>'

    cards = []
    for n, attr in enumerate(attributions, start=1):
        cp = attr.change_point
        if attr.card is None:
            continue
        card = attr.card
        cards.append(
            f'<div class="card">'
            f"<h3>#{n} {esc(card.change_id)} — {esc(card.title)}</h3>"
            f'<div class="scores">{esc(card.kind)} by {esc(card.author)} &middot; '
            f"median {card.median_before:.1f}ms &rarr; {card.median_after:.1f}ms "
            f"({_fmt_signed_pct(card.effect_pct)}) &middot; "
            f"score {card.score:.2f} (temporal {card.temporal_score:.2f} + "
            f"effect {card.effect_score:.2f} + "
            f"persistence {card.persistence_score:.2f})</div>"
            f"<p>{esc(card.rationale)}</p>"
            f"</div>"
        )

    doc = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(title)}</title>",
        f"<style>{_HTML_CSS}</style></head><body>",
        f"<h1>{esc(title)}</h1>",
        f'<div class="meta">{len(points)} samples &middot; '
        f"{esc(fmt_time(points[0].timestamp))} &rarr; "
        f"{esc(fmt_time(points[-1].timestamp))} &middot; "
        f"{esc(metric_label)} &middot; generated by blameshift {_version()}</div>",
        "<h2>series</h2>",
        _sparkline_svg(points, cps),
        f"<h2>change points ({len(cps)})</h2>",
        table,
    ]
    if cards:
        doc.append("<h2>evidence cards</h2>")
        doc.extend(cards)
    doc.append("</body></html>")
    return "\n".join(doc)


def write_html(content: str, path: str | Path) -> None:
    Path(path).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# PR comment (markdown)
# ---------------------------------------------------------------------------

def render_pr_comment(
    points: list[SeriesPoint],
    attributions: list[Attribution],
    *,
    series_path: str,
    changes_path: str,
    metric_label: str = "latency (ms)",
) -> str:
    """Render a markdown PR comment: change points, blame, evidence cards.

    Every number comes from the two input files named in the footer, which
    are stated explicitly so the comment can never be mistaken for anything
    other than this run's inputs.
    """
    lines: list[str] = []
    lines.append("### blameshift: latency change-point triage")
    lines.append("")
    cps = [a.change_point for a in attributions]
    regressions = [cp for cp in cps if cp.direction == "regression"]

    if not cps:
        lines.append(
            f"No change points detected in `{series_path}` "
            f"({len(points)} samples). The series looks stable."
        )
    else:
        lines.append(
            f"Detected **{len(cps)} change point(s)** "
            f"({len(regressions)} regression(s)) in "
            f"{len(points)} samples, {fmt_time(points[0].timestamp)} -> "
            f"{fmt_time(points[-1].timestamp)}:"
        )
        lines.append("")
        lines.append(
            "| # | time (UTC) | direction | effect | effect % | confidence | top suspect |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for n, attr in enumerate(attributions, start=1):
            cp = attr.change_point
            top = attr.top_suspect
            if top is not None:
                suspect = f"`{top.event.id}` (score {top.score:.2f})"
            elif attr.unattributed_reason:
                suspect = "unattributed"
            else:
                suspect = "-"
            lines.append(
                f"| {n} | {fmt_time(cp.timestamp)} | {cp.direction} | "
                f"{cp.effect_ms:+.1f}ms | {_fmt_signed_pct(cp.effect_pct)} | "
                f"{cp.confidence:.2f} | {suspect} |"
            )
        lines.append("")

        for n, attr in enumerate(attributions, start=1):
            cp = attr.change_point
            lines.append(
                f"**Change point {n}** — {fmt_time(cp.timestamp)} "
                f"({cp.direction}, median {cp.median_before:.1f}ms -> "
                f"{cp.median_after:.1f}ms, z={cp.z:.1f}, "
                f"persistence {cp.persist_count}/{cp.window})"
            )
            if attr.card is not None:
                card = attr.card
                lines.append(f"> {card.rationale}")
            elif attr.unattributed_reason:
                lines.append(f"> {attr.unattributed_reason}")
            else:
                lines.append("> improvement — no blame assigned")
            if len(attr.suspects) > 1:
                others = ", ".join(
                    f"`{s.event.id}` ({s.score:.2f})" for s in attr.suspects[1:4]
                )
                lines.append(f"> other candidates: {others}")
            lines.append("")

    lines.append("---")
    lines.append(
        f"<sub>Computed by blameshift {_version()} from `{series_path}` and "
        f"`{changes_path}` in this CI run ({metric_label}). Numbers describe "
        "these two input files only. JSON and HTML reports are attached as "
        "workflow artifacts.</sub>"
    )
    return "\n".join(lines)
