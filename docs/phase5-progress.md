# Phase 5 progress (orchestrator + chat)

Resume note in case a session hits the usage limit. Newest status at the bottom of each list.

## Design (decided)
- MCP server: FastMCP 4.x mounted in FastAPI at `/mcp` (streamable HTTP, not under `/api`, so the
  web proxy never exposes it). Chat id passed per session in the `X-Wyrd-Chat` header via `--mcp-config`.
- Orchestrator: `claude -p` per turn, `--session-id` on the first turn, `--resume` after; stream-json
  events → SSE `chat.*`. cwd outside the repo so the project CLAUDE.md isn't loaded.
- Status changes via `update_story` → hidden `story_update` agent in a plan (approval flow reused).
- @mention fast path: Groq `parse_mention` → plan; failure/ambiguity → orchestrator.
- Results loop: PlanService plan-finished hook → result card message + compact summary to orchestrator.
- Memory: FTS5 (messages/stories/dossiers) + embeddings (ref_type message/story/dossier), RRF merge.
- Claude meter: `provider_usage` rows with provider `claude` (+ `turns` column); soft cap in settings table.
- Browser → Next rewrites `/api/*` → 127.0.0.1:8000 (same origin).

## Checkpoints
- [x] Pushed Phase 4 commits (origin == local at 4e10546)
- [x] Verified `claude --help` (2.1.196) and FastMCP 4.0.11 docs
- [ ] Backend: migration, memory, MCP server, orchestrator runner, chat service, endpoints, tests
- [ ] Frontend: same-origin proxy, real chat UI, plan cards, result cards, @-autocomplete, meter
- [ ] Live acceptance (once): two-step plan, summary, recall in new chat, @scout fast path
