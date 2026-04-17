---
name: logs
description: Generate a narrative work log from your Claude Code sessions over the last N days — grouped by project, with first prompts, durations, and tool usage. Use when you want to recall what you worked on, write a weekly update, or orient yourself before a retro.
---

# /axnr:logs

Produce a readable work log from your Claude Code transcripts.

## Steps

1. Call the `list_sessions` MCP tool (from the `axnr` MCP server).
   - If the user said "all time", "everything", "all sessions", "full history", or similar, pass `window_days: 0` to scan every session on disk.
   - If the user gave a number (e.g. "last 30 days"), pass `window_days: 30`.
   - Otherwise pass nothing and let the configured default (7) stand.
2. Group the returned sessions by `project_slug` (preserve insertion order — already sorted by start time).
3. For each project group, render:

   - **Project** (project_slug, then cwd on a separate line in a code fence)
   - One bullet per session:
     - `YYYY-MM-DD HH:MM` (from `started_at_iso`, truncated to minutes)
     - duration (e.g. `23m`)
     - prompt count + tool call count (e.g. `4 prompts, 17 tools`)
     - git branch in parens if non-empty
     - quoted first_prompt, truncated to ~100 chars with "…" if longer

4. End with a totals line: `N sessions across M projects, T total minutes`.

## Output format

Markdown. No preamble. No trailing summary beyond the totals line.

## Notes

- Exclude sessions with `prompt_count == 0` — those are cold starts with no real activity.
- `window_days: 0` means "scan every session on disk" — use it when the user asks for all-time / complete history.
