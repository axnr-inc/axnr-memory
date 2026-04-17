---
name: friction
description: Surface where you lost time or had to correct Claude over the last N days — repeated corrections, tool errors you had to respond to, and tools that fail often. Use when you want a diagnostic of workflow friction before deciding what to automate.
---

# /axnr:friction

Produce a friction diagnostic from your transcripts.

## Steps

1. In parallel, call (from the `axnr` MCP server):
   - `find_repeated_corrections` — clusters of "no, not that" moments
   - `find_tool_friction` — tools that errored, with your follow-up
   - (Pass `window_days` if specified.)

2. Render three sections. If a section has zero results, print `- (none in window)` — do not fabricate.

### Corrections
   For each cluster:
   - **Signature** (the cluster's signature field — the opening words of the correction)
   - Frequency, tools involved
   - Up to 2 examples with: the correction text, what Claude was doing before, and which session (project + session_id truncated to 8 chars)

### Tool errors
   For each tool (ordered by frequency):
   - Tool name + error frequency
   - Up to 2 example error_preview excerpts (first 120 chars)
   - The user's follow-up text if present

### Top irritants
   Combine the above into a prioritized bullet list:
   - Any cluster with frequency >= 3 → top tier
   - Any tool with frequency >= 5 → top tier
   - Everything else → secondary tier

## Output format

Markdown with three level-2 headings. Terse. Quote user corrections verbatim.

## Notes

- This skill is diagnostic only. `/axnr:flow` translates friction into skill/memory recommendations.
