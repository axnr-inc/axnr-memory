"""Claude Code transcript reader.

Parses files under ~/.claude/projects/<encoded-path>/<session>.jsonl into
flattened Session objects. Handles:
  - typed content blocks (text / thinking / tool_use / tool_result)
  - string vs list content (user prompts vs tool_result carriers)
  - meta/system-injected user messages (<local-command-*>, <system-reminder>, etc.)
  - timestamps (ISO 8601 with Z suffix)

Everything is local — your own data, full fidelity, no anonymization.
"""

from __future__ import annotations

import datetime
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


# Wrappers that the CLI injects into user messages — not real user prompts.
META_MARKERS = (
    "<local-command-stdout",
    "<local-command-stderr",
    "<local-command-caveat",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<system-reminder>",
    "<bash-input>",
    "<bash-stderr>",
    "<bash-stdout>",
    "<user-prompt-submit-hook>",
)


def parse_ts(ts: str) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


@dataclass
class Message:
    role: str
    text: str = ""
    tool_uses: list[dict] = field(default_factory=list)      # [{name, input}]
    tool_results: list[dict] = field(default_factory=list)   # [{is_error, preview}]
    ts: float = 0.0
    is_meta: bool = False

    @property
    def is_real_user_prompt(self) -> bool:
        return (
            self.role == "user"
            and bool(self.text)
            and not self.is_meta
            and not self.tool_results
        )


@dataclass
class Session:
    session_id: str
    project_slug: str
    cwd: str
    git_branch: str
    started_at: float
    ended_at: float
    messages: list[Message]
    source_path: str = ""

    @property
    def real_user_prompts(self) -> list[Message]:
        return [m for m in self.messages if m.is_real_user_prompt]

    @property
    def first_prompt(self) -> str:
        prompts = self.real_user_prompts
        return prompts[0].text if prompts else ""

    @property
    def duration_minutes(self) -> float:
        if self.ended_at <= self.started_at:
            return 0.0
        return round((self.ended_at - self.started_at) / 60, 1)


def _flatten_content(content) -> tuple[str, list[dict], list[dict], bool]:
    """Return (text, tool_uses, tool_results, is_meta) from a message content field."""
    if isinstance(content, str):
        stripped = content.lstrip()
        is_meta = any(stripped.startswith(m) for m in META_MARKERS)
        return content, [], [], is_meta

    if not isinstance(content, list):
        return "", [], [], False

    text_parts: list[str] = []
    tool_uses: list[dict] = []
    tool_results: list[dict] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        t = item.get("type")
        if t == "text":
            text_parts.append(str(item.get("text", "")))
        elif t == "tool_use":
            tool_uses.append({
                "name": item.get("name", ""),
                "input": item.get("input") or {},
            })
        elif t == "tool_result":
            preview = ""
            c = item.get("content")
            if isinstance(c, str):
                preview = c[:500]
            elif isinstance(c, list):
                for ci in c:
                    if isinstance(ci, dict) and ci.get("type") == "text":
                        preview = str(ci.get("text", ""))[:500]
                        break
            tool_results.append({
                "is_error": bool(item.get("is_error")),
                "preview": preview,
            })
        # 'thinking' is intentionally dropped
    return "\n".join(text_parts), tool_uses, tool_results, False


def load_session(path: Path) -> Session | None:
    try:
        raw_lines = path.open().read().splitlines()
    except OSError:
        return None

    messages: list[Message] = []
    cwd = ""
    git_branch = ""
    first_ts = last_ts = 0.0

    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue

        rec_type = d.get("type")
        if not cwd:
            cwd = d.get("cwd") or ""
        if not git_branch:
            git_branch = d.get("gitBranch") or ""

        ts = parse_ts(d.get("timestamp", ""))
        if ts:
            if not first_ts or ts < first_ts:
                first_ts = ts
            if ts > last_ts:
                last_ts = ts

        if rec_type not in ("user", "assistant"):
            continue

        msg = d.get("message") or {}
        role = msg.get("role", rec_type)
        content = msg.get("content")
        text, tool_uses, tool_results, content_is_meta = _flatten_content(content)
        is_meta = bool(d.get("isMeta")) or content_is_meta

        messages.append(Message(
            role=role,
            text=text,
            tool_uses=tool_uses,
            tool_results=tool_results,
            ts=ts,
            is_meta=is_meta,
        ))

    if not messages:
        return None

    return Session(
        session_id=path.stem,
        project_slug=path.parent.name,
        cwd=cwd,
        git_branch=git_branch,
        started_at=first_ts,
        ended_at=last_ts or first_ts,
        messages=messages,
        source_path=str(path),
    )


def iter_sessions(root: str | Path, window_days: int = 7) -> Iterator[Session]:
    """Yield Session objects for session files touched within the window."""
    root = Path(os.path.expanduser(str(root)))
    if not root.exists():
        return
    cutoff = time.time() - (window_days * 86400) if window_days > 0 else 0
    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        for session_file in project_dir.glob("*.jsonl"):
            try:
                mtime = session_file.stat().st_mtime
            except OSError:
                continue
            if cutoff and mtime < cutoff:
                continue
            session = load_session(session_file)
            if session is None:
                continue
            if cutoff and session.ended_at and session.ended_at < cutoff:
                continue
            yield session


def load_sessions(root: str | Path, window_days: int = 7) -> list[Session]:
    return list(iter_sessions(root, window_days=window_days))


def find_session(root: str | Path, session_id: str) -> Session | None:
    root = Path(os.path.expanduser(str(root)))
    for project_dir in root.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            return load_session(candidate)
    return None
