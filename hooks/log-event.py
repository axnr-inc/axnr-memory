#!/usr/bin/env python3
"""Hook handler: append structured events to the local axnr event log.

Invocation (from hooks.json):
    python3 log-event.py <event_type>

Where <event_type> is one of:
    session_start   (from SessionStart hook)
    post_tool_use   (from PostToolUse hook)
    session_end     (from Stop hook)

Reads the hook payload on stdin, builds a compact event record, appends it to
~/.axnr/events/<session_id>.jsonl. Never fails a session: every exception is
swallowed, exit status is always 0.

No network. No third-party dependencies. Python stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PLUGIN_VERSION = "0.5.0"
DEBUG_LOG = os.environ.get("AXNR_DEBUG_LOG")  # set to a file path to tail hook activity


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _plugin_root() -> Path:
    if env := os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return Path(env)
    return Path(__file__).resolve().parent.parent


def load_settings() -> dict:
    defaults = {
        "events_root": "~/.axnr/events",
        "log_successful_tool_calls": False,
        "enabled": True,
    }
    try:
        with (_plugin_root() / "settings.json").open() as f:
            defaults.update(json.load(f))
    except Exception:
        pass
    if os.environ.get("AXNR_EVENTS_ROOT"):
        defaults["events_root"] = os.environ["AXNR_EVENTS_ROOT"]
    if os.environ.get("AXNR_ENABLED") == "false":
        defaults["enabled"] = False
    if os.environ.get("AXNR_LOG_SUCCESSFUL_TOOL_CALLS") == "true":
        defaults["log_successful_tool_calls"] = True
    return defaults


def _resolve(path_str: str) -> Path:
    return Path(os.path.expanduser(str(path_str))).resolve()


# ---------------------------------------------------------------------------
# Payload extraction (defensive — every .get() survives missing keys)
# ---------------------------------------------------------------------------

def _get_session_id(payload: dict) -> str:
    return (
        payload.get("session_id")
        or payload.get("sessionId")
        or "unknown"
    )


def _build_session_start(payload: dict) -> dict | None:
    return {
        "event": "session_start",
        "session_id": _get_session_id(payload),
        "cwd": payload.get("cwd", ""),
        "git_branch": payload.get("gitBranch") or payload.get("git_branch") or "",
        "ts": int(time.time()),
    }


def _build_post_tool_use(payload: dict, log_successful: bool) -> dict | None:
    tool_name = payload.get("tool_name", "unknown")
    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response") or {}

    # Error detection: is_error flag, or error key, or non-zero exit code for Bash
    is_error = bool(
        tool_response.get("is_error")
        or tool_response.get("error")
        or (isinstance(tool_response, dict) and str(tool_response.get("exitCode") or "0") not in ("0", ""))
    )

    if is_error:
        error_preview = ""
        if isinstance(tool_response, dict):
            error_preview = str(
                tool_response.get("error")
                or tool_response.get("content")
                or tool_response.get("stderr")
                or ""
            )[:300]
        elif isinstance(tool_response, str):
            error_preview = tool_response[:300]

        input_preview = ""
        if isinstance(tool_input, dict):
            try:
                input_preview = json.dumps(tool_input)[:300]
            except (TypeError, ValueError):
                input_preview = str(tool_input)[:300]
        else:
            input_preview = str(tool_input)[:300]

        return {
            "event": "tool_error",
            "session_id": _get_session_id(payload),
            "tool": tool_name,
            "input_preview": input_preview,
            "error_preview": error_preview,
            "ts": int(time.time()),
        }

    if log_successful:
        return {
            "event": "tool_call",
            "session_id": _get_session_id(payload),
            "tool": tool_name,
            "success": True,
            "ts": int(time.time()),
        }

    return None


def _build_session_end(payload: dict) -> dict | None:
    return {
        "event": "session_end",
        "session_id": _get_session_id(payload),
        "stop_hook_active": bool(payload.get("stop_hook_active")),
        "ts": int(time.time()),
    }


EVENT_BUILDERS = {
    "session_start": lambda payload, settings: _build_session_start(payload),
    "post_tool_use": lambda payload, settings: _build_post_tool_use(
        payload, settings.get("log_successful_tool_calls", False)
    ),
    "session_end": lambda payload, settings: _build_session_end(payload),
}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _append(events_root: Path, session_id: str, event: dict) -> None:
    events_root.mkdir(parents=True, exist_ok=True)
    path = events_root / f"{session_id}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(event) + "\n")


def _debug(msg: str) -> None:
    if not DEBUG_LOG:
        return
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{int(time.time())}] {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        if len(sys.argv) < 2:
            return 0
        event_type = sys.argv[1]
        builder = EVENT_BUILDERS.get(event_type)
        if not builder:
            _debug(f"unknown event type: {event_type}")
            return 0

        settings = load_settings()
        if not settings.get("enabled", True):
            return 0

        raw = sys.stdin.read()
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            _debug(f"bad json for {event_type}: {raw[:200]!r}")
            payload = {}

        event = builder(payload, settings)
        if event is None:
            return 0  # e.g. successful tool call with logging disabled

        event["plugin_version"] = PLUGIN_VERSION
        session_id = event.get("session_id", "unknown")
        _append(_resolve(settings["events_root"]), session_id, event)
        _debug(f"wrote {event_type} for {session_id[:8]}")
    except Exception as e:
        _debug(f"unhandled: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
