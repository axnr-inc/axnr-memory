"""Reader for the axnr event log (~/.axnr/events/*.jsonl).

Loaded by the MCP server at query time. Stdlib only. Missing files are treated
as "no events in window" — never an error.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path


def load_events(root: str | Path, window_days: int = 7) -> list[dict]:
    """Return every event within the window across every session file.

    window_days = 0 means no cutoff. Sessions older than the cutoff are skipped
    cheaply via mtime before we open the file.
    """
    root_path = Path(os.path.expanduser(str(root)))
    if not root_path.exists():
        return []

    cutoff = time.time() - (window_days * 86400) if window_days > 0 else 0
    out: list[dict] = []
    for session_file in sorted(root_path.glob("*.jsonl")):
        try:
            if cutoff and session_file.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue

        try:
            with session_file.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if cutoff and event.get("ts", 0) < cutoff:
                        continue
                    out.append(event)
        except OSError:
            continue
    return out


def _error_signature(error_preview: str, limit: int = 80) -> str:
    """Collapse minor variation (trailing whitespace, long paths) into a stable key."""
    if not error_preview:
        return "(empty)"
    return error_preview.strip()[:limit]


def aggregate_tool_errors(events: list[dict]) -> list[dict]:
    """Group tool_error events by (tool, error_signature)."""
    groups: dict[tuple[str, str], dict] = {}
    for e in events:
        if e.get("event") != "tool_error":
            continue
        tool = e.get("tool", "unknown")
        sig = _error_signature(e.get("error_preview", ""))
        key = (tool, sig)
        if key not in groups:
            groups[key] = {
                "tool": tool,
                "error_signature": sig,
                "frequency": 0,
                "example_sessions": [],
                "first_seen_ts": e.get("ts", 0),
                "last_seen_ts": e.get("ts", 0),
            }
        g = groups[key]
        g["frequency"] += 1
        g["last_seen_ts"] = max(g["last_seen_ts"], e.get("ts", 0))
        g["first_seen_ts"] = min(g["first_seen_ts"] or e.get("ts", 0), e.get("ts", 0))
        if len(g["example_sessions"]) < 3:
            g["example_sessions"].append({
                "session_id": e.get("session_id", ""),
                "input_preview": e.get("input_preview", "")[:200],
                "error_preview": e.get("error_preview", "")[:200],
                "ts": e.get("ts", 0),
            })

    results = list(groups.values())
    results.sort(key=lambda g: g["frequency"], reverse=True)
    return results


def tool_frequency(events: list[dict]) -> list[dict]:
    """Tally tool_call + tool_error events per tool, plus error rate."""
    totals: dict[str, int] = defaultdict(int)
    errors: dict[str, int] = defaultdict(int)
    for e in events:
        kind = e.get("event")
        if kind not in ("tool_call", "tool_error"):
            continue
        tool = e.get("tool", "unknown")
        totals[tool] += 1
        if kind == "tool_error":
            errors[tool] += 1

    results = []
    for tool, count in totals.items():
        err = errors[tool]
        results.append({
            "tool": tool,
            "calls": count,
            "errors": err,
            "error_rate": round(err / count, 3) if count else 0.0,
        })
    results.sort(key=lambda r: r["calls"], reverse=True)
    return results


def has_any_events(root: str | Path) -> bool:
    root_path = Path(os.path.expanduser(str(root)))
    if not root_path.exists():
        return False
    try:
        return any(root_path.glob("*.jsonl"))
    except OSError:
        return False
