---
name: researcher
description: Deep research on a wyrd.exe story; builds a sourced dossier with exact excerpts and saves it with save_dossier.
tools: mcp__wyrd, WebSearch, WebFetch
model: sonnet
---

wyrd.exe @researcher. The engine runs this agent headless for approved @researcher plans
(`apps/api/agents/researcher.py`): it reads this file's frontmatter (name, description, tools,
model), passes the rendered `prompts/researcher.md` as the agent's prompt, sets the turn budget for
the run's depth (`config/scoring.yaml` → research.depths), and connects only the engine's
researcher MCP tools (`/mcp-research`).

Allowed tools: the engine's MCP tools (source_* wrappers over every sources/ module,
extract_from_document, second_opinion, save_dossier, get_story, search_memory), WebSearch and
WebFetch. No shell, no file reads or writes: save_dossier does all writing (DB + research/<slug>/).

Follow prompts/researcher.md.
