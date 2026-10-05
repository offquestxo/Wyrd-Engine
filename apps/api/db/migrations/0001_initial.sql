-- 0001: core tables (SPEC §7). JSON columns are TEXT holding JSON.

CREATE TABLE stories (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    company TEXT,
    status TEXT NOT NULL DEFAULT 'Inbox' CHECK (status IN (
        'Inbox', 'Shortlisted', 'Researching', 'Scripting', 'Fact-check',
        'Recording', 'Editing', 'Published', 'Archived')),
    series TEXT,
    format TEXT,
    hook TEXT,
    scores TEXT,
    gap_score REAL,
    outlier_ref INTEGER REFERENCES videos(id) ON DELETE SET NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    notion_page_id TEXT,
    notion_synced_at TEXT
);
CREATE INDEX ix_stories_status ON stories(status);

CREATE TABLE story_sources (
    id INTEGER PRIMARY KEY,
    story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    title TEXT,
    source_type TEXT NOT NULL DEFAULT 'secondary' CHECK (source_type IN ('primary', 'secondary')),
    excerpt TEXT,
    added_by TEXT
);
CREATE INDEX ix_story_sources_story ON story_sources(story_id);

CREATE TABLE dossiers (
    id INTEGER PRIMARY KEY,
    story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    markdown TEXT NOT NULL,
    sources_json TEXT,
    second_opinion TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (story_id, version)
);

CREATE TABLE channels (
    id INTEGER PRIMARY KEY,
    handle TEXT NOT NULL UNIQUE,
    channel_id TEXT,
    name TEXT,
    uploads_playlist_id TEXT,
    last_scanned_at TEXT
);

CREATE TABLE videos (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    published_at TEXT,
    duration_s INTEGER,
    is_short INTEGER NOT NULL DEFAULT 0,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    outlier_score REAL,
    analysis TEXT
);
CREATE INDEX ix_videos_channel ON videos(channel_id);

CREATE TABLE chats (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    claude_session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'agent')),
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX ix_messages_chat ON messages(chat_id);

CREATE TABLE plans (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER REFERENCES chats(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'approved', 'cancelled', 'done', 'failed')),
    summary TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE TABLE agent_runs (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    params TEXT,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued', 'running', 'succeeded', 'failed', 'cancelled')),
    started_at TEXT,
    finished_at TEXT,
    result TEXT,
    error TEXT
);
CREATE INDEX ix_agent_runs_status ON agent_runs(status);

CREATE TABLE plan_steps (
    id INTEGER PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    "order" INTEGER NOT NULL,
    agent TEXT NOT NULL,
    params TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    run_id INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL
);

CREATE TABLE run_logs (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    data TEXT
);
CREATE INDEX ix_run_logs_run ON run_logs(run_id);

CREATE TABLE provider_usage (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT,
    task TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    units INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL,
    error TEXT,
    ts TEXT NOT NULL
);
CREATE INDEX ix_provider_usage_provider_ts ON provider_usage(provider, ts);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY,
    ref_type TEXT NOT NULL,
    ref_id INTEGER NOT NULL,
    vector BLOB NOT NULL,
    model TEXT NOT NULL,
    UNIQUE (ref_type, ref_id, model)
);
