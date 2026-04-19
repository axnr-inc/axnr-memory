#!/usr/bin/env python3
"""MCP server for axnr.

Reads your Claude Code transcripts (~/.claude/projects/**/*.jsonl) and exposes
tools for querying, searching, and surfacing automation candidates from your
own work. Your data, full fidelity — no anonymization.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import events  # noqa: E402
import patterns  # noqa: E402
import transcripts  # noqa: E402


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "axnr"
SERVER_VERSION = "0.5.0"


def load_settings() -> dict:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).resolve().parent.parent.parent)
    settings_path = Path(plugin_root) / "settings.json"
    defaults = {
        "transcripts_root": "~/.claude/projects",
        "events_root": "~/.axnr/events",
        "window_days": 7,
        "min_cluster_frequency": 2,
        "max_session_messages_returned": 200,
    }
    try:
        with settings_path.open() as f:
            defaults.update(json.load(f))
    except Exception:
        pass
    if os.environ.get("AXNR_TRANSCRIPTS_ROOT"):
        defaults["transcripts_root"] = os.environ["AXNR_TRANSCRIPTS_ROOT"]
    if os.environ.get("AXNR_EVENTS_ROOT"):
        defaults["events_root"] = os.environ["AXNR_EVENTS_ROOT"]
    if os.environ.get("AXNR_WINDOW_DAYS"):
        try:
            defaults["window_days"] = int(os.environ["AXNR_WINDOW_DAYS"])
        except ValueError:
            pass
    return defaults


def _coalesce_int(value, default):
    """Like `value or default` but treats 0 as a real value, not a fallback trigger."""
    if value is None:
        return int(default)
    return int(value)


def _load(args: dict) -> tuple[list, dict]:
    settings = load_settings()
    window = _coalesce_int(args.get("window_days"), settings["window_days"])
    sessions = transcripts.load_sessions(settings["transcripts_root"], window_days=window)
    return sessions, {
        "window_days": window,
        "min_cluster_frequency": int(settings["min_cluster_frequency"]),
        "events_root": settings["events_root"],
    }


def _load_events(args: dict) -> tuple[list[dict], int, str]:
    settings = load_settings()
    window = _coalesce_int(args.get("window_days"), settings["window_days"])
    evs = events.load_events(settings["events_root"], window_days=window)
    return evs, window, settings["events_root"]


TOOLS = [
    {
        "name": "list_sessions",
        "description": "List Claude Code sessions in the window with metadata (project, branch, duration, prompt count, first/last prompt). Optionally filter by project substring.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "window_days": {"type": "integer", "description": "Override the configured window. Default 7."},
                "project": {"type": "string", "description": "Filter by substring match against cwd or project_slug."},
            },
        },
    },
    {
        "name": "get_session",
        "description": "Return full message-by-message content for one session (role, text, tool_uses, tool_results). Meta/system messages are dropped. Truncated to max_session_messages_returned.",
        "inputSchema": {
            "type": "object",
            "required": ["session_id"],
            "properties": {
                "session_id": {"type": "string", "description": "Session UUID from list_sessions."},
            },
        },
    },
    {
        "name": "find_repeated_corrections",
        "description": "Surface moments where you corrected Claude ('no, not that', 'wrong', 'undo', etc.), clustered by the preceding tool use and the opening of the correction. Each cluster is a candidate for a skill or memory entry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "window_days": {"type": "integer"},
                "min_frequency": {"type": "integer", "description": "Minimum cluster size. Defaults to config."},
            },
        },
    },
    {
        "name": "find_repeated_session_starts",
        "description": "Surface phrases (4-8 words) that appear in the opening prompt of multiple sessions. These are CLAUDE.md / memory candidates — things you keep having to tell Claude.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "window_days": {"type": "integer"},
                "min_sessions": {"type": "integer"},
            },
        },
    },
    {
        "name": "find_tool_friction",
        "description": "List tool calls that returned errors, grouped by tool name, with the error preview and your follow-up message. Tools that fail often are candidates for pre-flight skills. Prefers the structured event log (~/.axnr/events/) when populated; falls back to walking transcripts.",
        "inputSchema": {
            "type": "object",
            "properties": {"window_days": {"type": "integer"}},
        },
    },
    {
        "name": "find_error_patterns",
        "description": "Fast-path error pattern mining from the local event log (~/.axnr/events/). Groups tool errors by (tool, error_signature) and returns frequency + example sessions. Requires the axnr hooks to have been installed and fired. Returns an empty result with a notes field if no events exist.",
        "inputSchema": {
            "type": "object",
            "properties": {"window_days": {"type": "integer"}},
        },
    },
    {
        "name": "find_bash_patterns",
        "description": "Frequently-invoked Bash commands (normalized to their first verb/subcommand) with frequency and example invocations. Candidates for command shortcut skills.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "window_days": {"type": "integer"},
                "min_frequency": {"type": "integer"},
            },
        },
    },
]


def tool_list_sessions(args: dict) -> dict:
    sessions, ctx = _load(args)
    rows = patterns.sessions_summary(sessions, project=args.get("project"))
    return {
        "window_days": ctx["window_days"],
        "count": len(rows),
        "sessions": rows,
    }


def tool_get_session(args: dict) -> dict:
    settings = load_settings()
    sid = args.get("session_id")
    if not sid:
        return {"error": "session_id is required"}
    session = transcripts.find_session(settings["transcripts_root"], sid)
    if session is None:
        return {"error": f"session not found: {sid}"}

    max_msgs = int(settings.get("max_session_messages_returned", 200))
    msgs = [m for m in session.messages if not m.is_meta]
    truncated = len(msgs) > max_msgs
    if truncated:
        msgs = msgs[:max_msgs]

    serialized = []
    for m in msgs:
        serialized.append({
            "role": m.role,
            "ts": m.ts,
            "text": m.text,
            "tool_uses": m.tool_uses,
            "tool_results": m.tool_results,
        })

    return {
        "session_id": session.session_id,
        "project_slug": session.project_slug,
        "cwd": session.cwd,
        "git_branch": session.git_branch,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "duration_minutes": session.duration_minutes,
        "message_count": len(serialized),
        "truncated": truncated,
        "messages": serialized,
    }


def tool_find_repeated_corrections(args: dict) -> dict:
    sessions, ctx = _load(args)
    min_freq = _coalesce_int(args.get("min_frequency"), ctx["min_cluster_frequency"])
    clusters = patterns.find_repeated_corrections(sessions, min_frequency=min_freq)
    return {
        "window_days": ctx["window_days"],
        "sessions_scanned": len(sessions),
        "cluster_count": len(clusters),
        "clusters": clusters,
    }


def tool_find_repeated_session_starts(args: dict) -> dict:
    sessions, ctx = _load(args)
    min_sessions = _coalesce_int(args.get("min_sessions"), ctx["min_cluster_frequency"])
    phrases = patterns.find_repeated_session_starts(sessions, min_sessions=min_sessions)
    return {
        "window_days": ctx["window_days"],
        "sessions_scanned": len(sessions),
        "phrase_count": len(phrases),
        "phrases": phrases,
    }


def tool_find_error_patterns(args: dict) -> dict:
    evs, window, root = _load_events(args)
    if not evs:
        return {
            "window_days": window,
            "events_scanned": 0,
            "pattern_count": 0,
            "patterns": [],
            "notes": f"No events in window at {root}. Use Claude Code with axnr hooks installed to populate.",
        }
    patterns_out = events.aggregate_tool_errors(evs)
    return {
        "window_days": window,
        "events_scanned": len(evs),
        "pattern_count": len(patterns_out),
        "patterns": patterns_out,
    }


def tool_find_tool_friction(args: dict) -> dict:
    """Hybrid path: prefer the structured event log; fall back to transcript walk.

    The event log captures friction in-flight via hooks (cheap, structured). The
    transcript walk reads the full assistant transcript post-hoc (richer context
    but slower). Callers shouldn't care which ran, but `source` tells them.
    """
    settings = load_settings()
    window = _coalesce_int(args.get("window_days"), settings["window_days"])

    if events.has_any_events(settings["events_root"]):
        evs = events.load_events(settings["events_root"], window_days=window)
        grouped = events.aggregate_tool_errors(evs)
        # Collapse by tool for a shape comparable to the transcript-walk output
        by_tool: dict[str, dict] = {}
        for g in grouped:
            t = g["tool"]
            if t not in by_tool:
                by_tool[t] = {"tool": t, "frequency": 0, "examples": []}
            by_tool[t]["frequency"] += g["frequency"]
            for ex in g["example_sessions"][:2]:
                if len(by_tool[t]["examples"]) < 3:
                    by_tool[t]["examples"].append({
                        "session_id": ex.get("session_id", ""),
                        "project": "",
                        "error_preview": ex.get("error_preview", ""),
                        "next_user_text": "",
                    })
        tools = sorted(by_tool.values(), key=lambda r: r["frequency"], reverse=True)
        return {
            "source": "events",
            "window_days": window,
            "events_scanned": len(evs),
            "tool_count": len(tools),
            "tools": tools,
        }

    sessions, ctx = _load(args)
    results = patterns.find_tool_friction(sessions)
    return {
        "source": "transcripts",
        "window_days": ctx["window_days"],
        "sessions_scanned": len(sessions),
        "tool_count": len(results),
        "tools": results,
    }


def tool_find_bash_patterns(args: dict) -> dict:
    sessions, ctx = _load(args)
    min_freq = _coalesce_int(args.get("min_frequency"), ctx["min_cluster_frequency"])
    results = patterns.find_bash_patterns(sessions, min_frequency=min_freq)
    return {
        "window_days": ctx["window_days"],
        "sessions_scanned": len(sessions),
        "pattern_count": len(results),
        "patterns": results,
    }


HANDLERS = {
    "list_sessions": tool_list_sessions,
    "get_session": tool_get_session,
    "find_repeated_corrections": tool_find_repeated_corrections,
    "find_repeated_session_starts": tool_find_repeated_session_starts,
    "find_tool_friction": tool_find_tool_friction,
    "find_error_patterns": tool_find_error_patterns,
    "find_bash_patterns": tool_find_bash_patterns,
}


def make_response(req_id, result=None, error=None):
    resp = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result
    return resp


def handle_request(req: dict) -> dict | None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if not handler:
            return make_response(req_id, error={"code": -32601, "message": f"unknown tool: {name}"})
        try:
            result = handler(args)
        except Exception as e:
            return make_response(req_id, error={"code": -32603, "message": f"tool error: {e}"})
        return make_response(req_id, {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]})

    if method == "ping":
        return make_response(req_id, {})

    if req_id is None:
        return None

    return make_response(req_id, error={"code": -32601, "message": f"unknown method: {method}"})


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
