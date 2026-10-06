-- 0003: run progress + plan link for the job runner; fallback flag for quota meters.

ALTER TABLE agent_runs ADD COLUMN current_step TEXT;
ALTER TABLE agent_runs ADD COLUMN progress REAL;
ALTER TABLE agent_runs ADD COLUMN plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL;
ALTER TABLE agent_runs ADD COLUMN created_at TEXT;
CREATE INDEX ix_agent_runs_plan ON agent_runs(plan_id);

-- 1 when the call succeeded on a fallback (not the route's first usable provider).
ALTER TABLE provider_usage ADD COLUMN fallback INTEGER NOT NULL DEFAULT 0;
