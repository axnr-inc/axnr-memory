---
name: flow
description: Propose specific skills, memory entries, CLAUDE.md additions, or plugin ideas to build — derived from patterns in your own Claude Code transcripts over the last N days. Use when you want a ranked action list for improving your workflow.
---

# /axnr:flow

Translate observed patterns into concrete automation proposals.

## Steps

1. In parallel, call all four pattern tools (from the `axnr` MCP server):
   - `find_repeated_session_starts`
   - `find_repeated_corrections`
   - `find_tool_friction`
   - `find_bash_patterns`
   - Pass `window_days` if specified.

2. For each pattern result, synthesize a proposal. Use your judgment — these heuristics surface candidates, the framing is yours:

   - **Repeated session-opener phrases** → **CLAUDE.md entry** (global or project-scoped). Quote the phrase. Suggest where it should live (global `~/.claude/CLAUDE.md` if it's workflow-agnostic, project `CLAUDE.md` if domain-specific).
   - **Repeated corrections** → **Skill or memory entry**. Look at what Claude was doing (preceding_tools) and what the correction said. Propose a skill name + one-line purpose.
   - **Tool friction** → **Pre-flight skill or memory entry**. For each erroring tool, propose how to avoid the class of error (e.g., Read token limit → "check file size before reading" skill; ssh timeout → "retry/backoff" guidance in memory).
   - **Bash patterns** → **Command shortcut skill or slash command**. High-frequency commands become slash-commands. Pattern like `python3 <<'EOF'` 41 times → propose a `/run-inline-python` skill or template.

3. Rank proposals by expected impact:
   - **High** — frequency ≥ 5 OR tool error that blocked work
   - **Medium** — frequency 2-4 with clear automation shape
   - **Low** — frequency 2 with ambiguous shape

4. Render as markdown with three level-2 headings (High / Medium / Low). For each proposal:

   - **Title** — short, imperative (e.g., "Add CLAUDE.md entry: grounded-documentation rule")
   - **Type** — one of: `CLAUDE.md entry`, `skill`, `plugin`, `memory`
   - **Scope** — global / project:<name> / org
   - **Evidence** — one-line summary of the pattern (frequency, example)
   - **Proposed action** — one or two sentences on what to build

5. End with a one-line count: `N proposals (H high / M medium / L low)`.

## Output format

Clean markdown. Be specific, not generic. Name the skills. Quote the phrases.

## Notes

- If a pattern has frequency == 2 AND no clear shape, skip it rather than padding the list.
- Never recommend something without supporting evidence from the tool output.
- The user wants actionable proposals they can implement next, not a taxonomy.
