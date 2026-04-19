# axnr (Claude Code Plugin)

Solo introspection over your own Claude Code transcripts plus a lightweight
local event log. Reads `~/.claude/projects/**/*.jsonl` (the transcripts Claude
Code writes) and `~/.axnr/events/<session>.jsonl` (structured events written
by the plugin's hooks). Both are on your machine. Nothing leaves it.

Surfaces concrete automation candidates: repeated corrections, repeated
session-opener phrases, tool failures, frequent Bash commands, error patterns.

## What's in the box

```
plugin/
├── .claude-plugin/
│   ├── plugin.json                Plugin manifest (MCP + skills + hooks)
│   └── marketplace.json           Marketplace manifest (single-plugin marketplace)
├── hooks/
│   ├── hooks.json                 Registers SessionStart / PostToolUse / Stop
│   └── log-event.py               Stdlib-only event logger (swallows all errors)
├── settings.json                  transcripts_root, events_root, window_days, thresholds
├── mcp/analytics-server/
│   ├── server.py                  Stdio MCP server
│   ├── transcripts.py             Parses ~/.claude/projects/*/<session>.jsonl
│   ├── patterns.py                Heuristic pattern detectors
│   └── events.py                  Reader + aggregator for ~/.axnr/events/*.jsonl
├── skills/
│   ├── logs/SKILL.md              /axnr:logs
│   ├── friction/SKILL.md          /axnr:friction
│   └── flow/SKILL.md              /axnr:flow
└── README.md
```

Stdlib only. No `pip install`, no server to run, no data leaves your machine.

## Why this exists

I wanted to understand my own Claude Code patterns and turn them into concrete
skills, memory entries, and CLAUDE.md additions. Claude Code already writes
full transcripts locally — this plugin is a pure reader + heuristic detector
+ skills layer over what already exists on disk, plus a small structured event
log for faster error-pattern queries.

## Install and use

### From GitHub

```
/plugin marketplace add axnr-inc/axnr-memory
/plugin install axnr@axnr-memory
```

The repo root is both the marketplace (via `.claude-plugin/marketplace.json`)
and the plugin (via `.claude-plugin/plugin.json`). `@axnr-memory` references
the marketplace name.

### Local (development / dogfooding)

```
/plugin marketplace add /absolute/path/to/plugin
/plugin install axnr@axnr-memory
```

Point `marketplace add` at the directory that contains `.claude-plugin/`.
Reload Claude Code, and the MCP server, skills, and hooks register
automatically.

### What you get after install

From any Claude Code session:

- `/axnr:logs` — narrative work log for the last 7 days
- `/axnr:friction` — corrections + tool errors
- `/axnr:flow` — ranked skill/memory/plugin proposals

And seven MCP tools for direct or custom-skill use.

## MCP tools

| Tool                             | Returns                                                                |
|----------------------------------|------------------------------------------------------------------------|
| `list_sessions`                  | Session rows with project, branch, duration, first/last prompt         |
| `get_session`                    | Full messages (role, text, tool_uses, tool_results) for one session    |
| `find_repeated_corrections`      | Clusters of "no, not that"-style corrections + preceding context       |
| `find_repeated_session_starts`   | Opener phrases that appear across multiple sessions                    |
| `find_tool_friction`             | Tools that errored + your follow-up — hybrid: prefers event log, falls back to transcripts |
| `find_error_patterns`            | Fast-path error mining from the event log (`~/.axnr/events/`)          |
| `find_bash_patterns`             | Frequently-run Bash commands (normalized)                              |

All accept an optional `window_days` override. Defaults to 7. Pass
`window_days: 0` to scan every session on disk (no time filter). The skills
recognize "all time", "everything", or "full history" in your request and pass
`0` automatically.

## Data on disk

The plugin reads and writes only under these paths:

| Path | Owner | Purpose |
|---|---|---|
| `~/.claude/projects/**/*.jsonl` | Claude Code (not us) | Source of truth for transcripts — we only read |
| `~/.axnr/events/<session>.jsonl` | This plugin | Structured events written by hooks at runtime |

To reset, `rm -rf ~/.axnr`. To keep transcripts but disable this plugin, set
`enabled: false` in `settings.json` or `AXNR_ENABLED=false` in your env.

## Configuration

`settings.json`:

| Field                          | Default                   | Purpose                                      |
|--------------------------------|---------------------------|----------------------------------------------|
| `transcripts_root`             | `~/.claude/projects`      | Where to read transcripts from               |
| `events_root`                  | `~/.axnr/events`          | Where hooks write the structured event log   |
| `window_days`                  | `7`                       | Default query window                         |
| `min_cluster_frequency`        | `2`                       | Threshold for pattern clusters               |
| `max_session_messages_returned`| `200`                     | Cap on `get_session` output                  |
| `log_successful_tool_calls`    | `false`                   | If true, every tool call is logged (not just errors) |
| `enabled`                      | `true`                    | Master kill switch — disables hooks entirely |

Env overrides: `AXNR_TRANSCRIPTS_ROOT`, `AXNR_EVENTS_ROOT`, `AXNR_WINDOW_DAYS`,
`AXNR_ENABLED=false`, `AXNR_LOG_SUCCESSFUL_TOOL_CALLS=true`,
`AXNR_DEBUG_LOG=/path/to/file` (tail hook activity).

## Privacy

Nothing leaves your machine. The MCP server runs in-process under Claude Code.
The hooks run as local Python subprocesses and write to `~/.axnr/events/`. No
HTTP client is imported, no third-party services are called. Every hook
invocation swallows its exceptions and exits 0, so a plugin bug can't fail your
session.

## What's heuristic vs exact

- **Exact**: session counts, durations, tool call frequencies, tool error
  counts, Bash command frequencies, error-pattern groupings.
- **Heuristic**: correction detection (small phrase list), session-start
  phrase clustering (sliding n-grams grouped by identical session-set),
  meta-message filtering (wrapper tag prefixes).

Correction detection in particular is coarse — if it misses the way *you*
phrase corrections, edit `CORRECTION_PHRASES` in `patterns.py`.

## Out of scope (v0.5.0)

- LLM-based synthesis of patterns. Scheduled for v0.6.0 as an opt-in Haiku
  summarization layer.
- Semantic search across transcripts.
- Writing discovered skills/memory entries automatically. Recommend only.
- Streaming/incremental updates — queries re-read the log. Fast enough for
  typical windows on one machine.
