-- 0005: orchestrator chat (Phase 5).
-- provider_usage.turns: agentic turns of a Claude Code call (the Claude meter counts calls,
-- duration and turns per day; Pro plan usage isn't available programmatically).
ALTER TABLE provider_usage ADD COLUMN turns INTEGER NOT NULL DEFAULT 0;
-- chats.chat_id on usage rows lets the meter show which chat spent Claude time.
ALTER TABLE provider_usage ADD COLUMN chat_id INTEGER REFERENCES chats(id) ON DELETE SET NULL;
CREATE INDEX ix_messages_chat_created ON messages(chat_id, created_at);
CREATE INDEX ix_plans_chat ON plans(chat_id);
