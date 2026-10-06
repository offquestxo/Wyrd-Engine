-- 0004: @outlier details. channels.is_own lets v2 analytics store the owner's channel here too.

ALTER TABLE channels ADD COLUMN is_own INTEGER NOT NULL DEFAULT 0;
ALTER TABLE channels ADD COLUMN subscribers INTEGER;

ALTER TABLE videos ADD COLUMN thumbnail_url TEXT;
ALTER TABLE videos ADD COLUMN vertical INTEGER;          -- 1 = square/vertical player, 0 = horizontal
ALTER TABLE videos ADD COLUMN channel_median REAL;       -- median views of its channel+format at scan time
ALTER TABLE videos ADD COLUMN scanned_at TEXT;
ALTER TABLE videos ADD COLUMN last_run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL;
CREATE INDEX ix_videos_outlier ON videos(outlier_score);
