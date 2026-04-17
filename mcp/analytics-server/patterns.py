"""Heuristic pattern detectors over parsed sessions.

Surfaces automation candidates:
  - find_repeated_corrections  — "no, not that" moments + what Claude did right before
  - find_repeated_session_starts — opening prompts / phrases across many sessions
  - find_tool_friction         — tool calls that errored + the user's follow-up
  - find_bash_patterns         — frequently-run Bash commands (normalized)
  - sessions_summary           — per-session work log rows
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from transcripts import Message, Session


# ---------------------------------------------------------------------------
# Repeated corrections
# ---------------------------------------------------------------------------

CORRECTION_PHRASES = (
    "no, not",
    "no not",
    "not that",
    "that's wrong",
    "thats wrong",
    "that is wrong",
    "don't do",
    "dont do",
    "stop, ",
    "stop.",
    "stop doing",
    "i said ",
    "undo",
    "revert that",
    "revert the",
    "undo that",
    "not what i",
    "that's not what",
    "thats not what",
    "wrong,",
    "wrong.",
    "incorrect",
    "that's incorrect",
    "you're wrong",
    "you are wrong",
    "don't ",
    "please don't",
)

# Avoid false positives on phrases that start with "no" but aren't corrections
CORRECTION_FALSE_POSITIVES = (
    "no problem",
    "no worries",
    "no idea",
    "no need",
    "no big deal",
    "no other",
    "no one",
    "no longer",
)


def is_correction(text: str) -> bool:
    low = text.lower().strip()[:300]
    if not low:
        return False
    if any(fp in low[:40] for fp in CORRECTION_FALSE_POSITIVES):
        return False
    return any(p in low for p in CORRECTION_PHRASES)


def _phrase_signature(text: str, ngram: int = 4) -> str:
    tokens = re.findall(r"\w+", text.lower())
    return " ".join(tokens[:ngram])


def find_repeated_corrections(sessions: list[Session], min_frequency: int = 2) -> list[dict]:
    events = []
    for s in sessions:
        msgs = s.messages
        for i, m in enumerate(msgs):
            if not m.is_real_user_prompt or not is_correction(m.text):
                continue
            prev_text = ""
            prev_tools: list[str] = []
            for j in range(i - 1, -1, -1):
                pm = msgs[j]
                if pm.role == "assistant":
                    if pm.tool_uses:
                        prev_tools = [t.get("name", "") for t in pm.tool_uses]
                    if pm.text:
                        prev_text = pm.text[:400]
                    break
            events.append({
                "session_id": s.session_id,
                "project": s.project_slug,
                "ts": m.ts,
                "correction_text": m.text[:400],
                "preceding_action": prev_text,
                "preceding_tools": prev_tools,
            })

    clusters: dict[tuple, list[dict]] = defaultdict(list)
    for e in events:
        key = (
            tuple(sorted(set(e["preceding_tools"])))[:3],
            _phrase_signature(e["correction_text"], ngram=4),
        )
        clusters[key].append(e)

    results = []
    for key, evts in clusters.items():
        if len(evts) < min_frequency:
            continue
        results.append({
            "frequency": len(evts),
            "signature": " / ".join(str(x) for x in key if x),
            "tools_involved": list(key[0]) if key[0] else [],
            "examples": evts[:3],
        })
    results.sort(key=lambda r: r["frequency"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Repeated session-opener phrases (CLAUDE.md candidates)
# ---------------------------------------------------------------------------

def find_repeated_session_starts(sessions: list[Session], min_sessions: int = 2) -> list[dict]:
    """Group opener phrases by the set of sessions they appear in, then keep
    the longest representative per group. Phrases from the same repeated prompt
    share an identical session-id-set, so grouping collapses sliding-window noise.
    """
    opener_texts: list[tuple[Session, str]] = []
    for s in sessions:
        prompts = s.real_user_prompts
        if prompts:
            opener_texts.append((s, prompts[0].text))

    phrase_sessions: dict[str, set] = defaultdict(set)
    for s, text in opener_texts:
        tokens = re.findall(r"\w+", text.lower())
        for size in (4, 5, 6, 7, 8):
            if len(tokens) < size:
                continue
            for i in range(len(tokens) - size + 1):
                phrase = " ".join(tokens[i : i + size])
                phrase_sessions[phrase].add(s.session_id)

    # Group phrases by identical session-set — same prompt produces many n-grams
    groups: dict[frozenset, list[str]] = defaultdict(list)
    for phrase, session_set in phrase_sessions.items():
        if len(session_set) < min_sessions:
            continue
        groups[frozenset(session_set)].append(phrase)

    representatives = []
    for session_set, phrases in groups.items():
        # Prefer the longest phrase (most words, then most chars) as the group label
        best = max(phrases, key=lambda p: (len(p.split()), len(p)))
        representatives.append({
            "phrase": best,
            "session_count": len(session_set),
            "word_count": len(best.split()),
            "variant_count": len(phrases),
        })

    representatives.sort(key=lambda c: (c["session_count"], c["word_count"]), reverse=True)
    return representatives[:20]


# ---------------------------------------------------------------------------
# Tool friction — tools that errored, and how the user responded
# ---------------------------------------------------------------------------

def find_tool_friction(sessions: list[Session]) -> list[dict]:
    per_tool: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        msgs = s.messages
        for i, m in enumerate(msgs):
            for tr in m.tool_results:
                if not tr.get("is_error"):
                    continue
                tool_name = "?"
                for j in range(i - 1, -1, -1):
                    pm = msgs[j]
                    if pm.role == "assistant" and pm.tool_uses:
                        tool_name = pm.tool_uses[-1].get("name", "?")
                        break
                next_user_text = ""
                for j in range(i + 1, len(msgs)):
                    nm = msgs[j]
                    if nm.role == "user" and nm.text and not nm.is_meta:
                        next_user_text = nm.text[:300]
                        break
                    if nm.role == "assistant" and nm.text:
                        break
                per_tool[tool_name].append({
                    "session_id": s.session_id,
                    "project": s.project_slug,
                    "error_preview": tr.get("preview", "")[:300],
                    "next_user_text": next_user_text,
                })

    results = []
    for tool, items in per_tool.items():
        results.append({
            "tool": tool,
            "frequency": len(items),
            "examples": items[:3],
        })
    results.sort(key=lambda r: r["frequency"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Bash command patterns
# ---------------------------------------------------------------------------

def normalize_bash(cmd: str) -> str:
    if not cmd:
        return ""
    parts = cmd.strip().split()
    prefix: list[str] = []
    for p in parts[:6]:
        if p in ("&&", "||", ";", "|"):
            break
        if p.startswith("-") or "/" in p or "=" in p:
            prefix.append("…")
            break
        prefix.append(p)
    return " ".join(prefix[:3])


def find_bash_patterns(sessions: list[Session], min_frequency: int = 2) -> list[dict]:
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for s in sessions:
        for m in s.messages:
            if m.role != "assistant":
                continue
            for tu in m.tool_uses:
                if tu.get("name") != "Bash":
                    continue
                cmd = str((tu.get("input") or {}).get("command", ""))
                norm = normalize_bash(cmd)
                if not norm:
                    continue
                counts[norm] += 1
                if len(examples[norm]) < 3:
                    examples[norm].append(cmd[:200])

    results = []
    for norm, count in counts.most_common(50):
        if count < min_frequency:
            continue
        results.append({
            "normalized": norm,
            "frequency": count,
            "examples": examples[norm],
        })
    return results


# ---------------------------------------------------------------------------
# Per-session summary
# ---------------------------------------------------------------------------

def sessions_summary(sessions: list[Session], project: str | None = None) -> list[dict]:
    rows = []
    for s in sorted(sessions, key=lambda x: x.started_at):
        if project and project not in s.cwd and project not in s.project_slug:
            continue
        prompts = s.real_user_prompts
        assistant_replies = sum(1 for m in s.messages if m.role == "assistant" and m.text)
        tool_calls = sum(len(m.tool_uses) for m in s.messages if m.role == "assistant")
        rows.append({
            "session_id": s.session_id,
            "project_slug": s.project_slug,
            "cwd": s.cwd,
            "git_branch": s.git_branch,
            "started_at_iso": _iso(s.started_at),
            "ended_at_iso": _iso(s.ended_at),
            "duration_minutes": s.duration_minutes,
            "prompt_count": len(prompts),
            "assistant_replies": assistant_replies,
            "tool_calls": tool_calls,
            "first_prompt": prompts[0].text[:300] if prompts else "",
            "last_prompt": prompts[-1].text[:300] if prompts else "",
        })
    return rows


def _iso(ts: float) -> str:
    if not ts:
        return ""
    import datetime
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")
