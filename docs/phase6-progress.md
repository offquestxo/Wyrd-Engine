# Phase 6 progress (@researcher)

Resume note in case a session hits the usage limit.

## Design (decided)
- **Runner** `apps/api/agents/researcher.py`: a job-runner agent that spawns
  `claude -p --agent researcher --agents <json built from .claude/agents/researcher.md>` (cwd outside
  the repo), MCP over HTTP with `X-Wyrd-Run` + token headers. The turn budget per depth
  (scoring.yaml `research.depths`) is enforced by counting tool-use turns in the stream and killing
  the process at the budget. Each run logs one `provider_usage` row (provider `claude`, task `researcher`).
- **MCP tool groups**: orchestrator keeps its 7 tools; researcher gets `get_story`, `search_memory`,
  one `source_<module>` per sources/ module (`action` param where a module has several functions),
  `extract_from_document`, `second_opinion`, `save_dossier` + Claude's WebSearch/WebFetch.
- **Per-run state** (`apps/api/research/session.py`): texts served to the researcher (URL → text) for the
  excerpt check, second-opinion results, run log hook.
- **save_dossier takes structured JSON** (summary, twist, timeline, people, key numbers, beats, hooks,
  angles, open questions, sources); the engine renders the SPEC template markdown. Checks on save:
  excerpt ≤ N words (truncated), excerpt found in cited source text (normalized), figure numbers
  present in their excerpt, primary-source marking by domain. Failing rows → Open Questions.
  Requires `second_opinion` called earlier in the same run.
- **Export**: `research/<slug>/dossier.md` + `sources.json`; DB `dossiers` row (new version).
- **Router**: `headroom_tasks` in providers.yaml → route ordered by remaining daily request fraction.

## Checkpoints
- [x] Pushed Phase 5 (372eb89); CLAUDE.md status; offline MCP-restart tests (760e3cd)
- [x] Config + router headroom ordering (840f98f)
- [x] research/ (texts, checks, render, export, save) + tests
- [x] MCP researcher tools + tests (separate /mcp-research endpoint)
- [x] researcher runner + agent def + prompt + tests (97fc7af)
- [x] Frontend: Research page, Research this, plan card estimate (69c805b)
- [x] Live: one standard Circuit City run (run #10; results in decisions.md)
- [x] Prose number check + fail-fast links (f18938d)
- [ ] Owner review; push after approval

## Chat-test hang log (Phase 5 carry-over)
Not seen again during Phase 6: every pytest run completed (about 25 full and partial runs).
