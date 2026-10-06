-- 0006: structured dossiers (Phase 6). `data` holds Key Numbers, Timeline, people, etc. as JSON
-- (each fact with source number + excerpt), so v2 @graphics can render from verified data.
-- `checks` holds the excerpt-check results; `run_id` the @researcher run that wrote it.
ALTER TABLE dossiers ADD COLUMN data TEXT;
ALTER TABLE dossiers ADD COLUMN checks TEXT;
ALTER TABLE dossiers ADD COLUMN run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL;
ALTER TABLE dossiers ADD COLUMN export_path TEXT;
