# Phase 7 progress (Notion sync)

Resume note in case a session hits the usage limit.

## Design (decided)
- Notion API `Notion-Version: 2026-03-11` (checked 2026-10-06): pages live under a data source
  (`parent.type = data_source_id`, from `GET /v1/databases/{id}` → `data_sources`), queries go to
  `POST /v1/data_sources/{id}/query`, `archived` → `in_trash`. Rate limit ~3 req/s average
  (non-Enterprise); 429 → `Retry-After`. Rich text ≤ 2000 chars.
- `apps/api/notion_sync.py`: httpx client with pacing (≤ 3 req/s), 429/5xx retry; schema check;
  pull (Status + Notes, newest `updated_at` wins) then push (create/update changed stories).
  Mapping via `stories.notion_page_id` + an `Engine ID` number property.
- Properties: Title (title), Status/Series/Format (select), Hook (rich_text, "UNVERIFIED LEAD: "
  prefix like the UI badge), Scores (rich_text), Gap Score (number), Sources (rich_text), Updated (date),
  Notes (rich_text, pulled back), Engine ID (number).
- Settings: Sync now, auto-sync toggle (settings table; debounced push after `story.changed`,
  periodic pull while on), last-sync summary. No token → everything disabled, app unaffected.
- One-time DB creation with the Notion connector (owner's account); app syncs with NOTION_TOKEN.

## Checkpoints
- [x] Phase 6 review fixes pushed (eddd0e6)
- [x] notion_sync.py + config + endpoints + tests (fake API via httpx.MockTransport) (261c9ee)
- [x] Settings UI (Notion card) (ecb11eb)
- [x] DB created via connector: "wyrd.exe Stories" (18b09686f09640aeb42a07a7aed75d26); NOTION_DATABASE_ID set in .env
- [ ] Owner: add NOTION_TOKEN, add the integration to the database (••• → Connections), Reload .env
- [ ] Live: push stories, change Status in Notion, sync back
