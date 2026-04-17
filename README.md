# axnr (Claude Code Plugin)

Solo introspection over your own Claude Code transcripts. Reads
`~/.claude/projects/**/*.jsonl` — full fidelity, no anonymization, local only —
and surfaces concrete automation candidates: repeated corrections, repeated
session-opener phrases, tool failures, frequent Bash commands.

## What's in the box

```
plugin/
├── .claude-plugin/
│   ├── plugin.json                Plugin manifest (MCP + skills)
│   └── marketplace.json           Marketplace manifest (single-plugin marketplace)
├── settings.json                  transcripts_root, window_days, thresholds
├── mcp/analytics-server/
│   ├── server.py                  Stdio MCP server
│   ├── transcripts.py             Parses ~/.claude/projects/*/<session>.jsonl
│   └── patterns.py                Heuristic pattern detectors
├── skills/
│   ├── logs/SKILL.md              /axnr:logs
│   ├── friction/SKILL.md          /axnr:friction
│   └── flow/SKILL.md              /axnr:flow
└── README.md
```

Stdlib only. No `pip install`, no hooks, no server to run, no data leaves your
machine.

## Why this exists

I wanted to understand my own Claude Code patterns and turn them into concrete
skills, memory entries, and CLAUDE.md additions. Claude Code already writes
full transcripts locally — this plugin is a pure reader + heuristic detector
+ skills layer over what already exists on disk.

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
Reload Claude Code, and the MCP server and skills register automatically.

### What you get after install

From any Claude Code session:

- `/axnr:logs` — narrative work log for the last 7 days
- `/axnr:friction` — corrections + tool errors
- `/axnr:flow` — ranked skill/memory/plugin proposals

And six MCP tools for direct or custom-skill use.

## MCP tools

| Tool                             | Returns                                                                |
|----------------------------------|------------------------------------------------------------------------|
| `list_sessions`                  | Session rows with project, branch, duration, first/last prompt         |
| `get_session`                    | Full messages (role, text, tool_uses, tool_results) for one session    |
| `find_repeated_corrections`      | Clusters of "no, not that"-style corrections + preceding context       |
| `find_repeated_session_starts`   | Opener phrases that appear across multiple sessions                    |
| `find_tool_friction`             | Tools that errored + your follow-up                                    |
| `find_bash_patterns`             | Frequently-run Bash commands (normalized)                              |

All accept an optional `window_days` override. Defaults to 7. Pass
`window_days: 0` to scan every session on disk (no time filter). The skills
recognize "all time", "everything", or "full history" in your request and pass
`0` automatically.

## Configuration

`settings.json`:

| Field                          | Default                   | Purpose                                      |
|--------------------------------|---------------------------|----------------------------------------------|
| `transcripts_root`             | `~/.claude/projects`      | Where to read transcripts from               |
| `window_days`                  | `7`                       | Default query window                         |
| `min_cluster_frequency`        | `2`                       | Threshold for pattern clusters               |
| `max_session_messages_returned`| `200`                     | Cap on `get_session` output                  |

Env overrides: `AXNR_TRANSCRIPTS_ROOT`, `AXNR_WINDOW_DAYS`.

## Privacy

Your transcripts stay on your machine. The MCP server runs in-process under
Claude Code. Nothing is sent anywhere — there's no HTTP client, no hooks,
no `requests` import.

## What's heuristic vs exact

- **Exact**: session counts, durations, tool call frequencies, Bash command
  frequencies.
- **Heuristic**: correction detection (small phrase list), session-start
  phrase clustering (sliding n-grams grouped by identical session-set),
  meta-message filtering (wrapper tag prefixes).

Correction detection in particular is coarse — if it misses the way *you*
phrase corrections, edit `CORRECTION_PHRASES` in `patterns.py`.

## Out of scope

- LLM-based synthesis of patterns. Heuristics first, Claude API calls later if
  heuristics feel thin.
- Semantic search across transcripts.
- Writing discovered skills/memory entries automatically. Recommend only.
- Streaming/incremental updates — the plugin re-scans on every MCP call.
  Fast enough for 7-day windows on one machine.
