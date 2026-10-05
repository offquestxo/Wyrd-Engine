-- 0002: FTS5 full-text indexes (external-content tables kept in sync by triggers).

CREATE VIRTUAL TABLE messages_fts USING fts5(
    content, content='messages', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER messages_fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER messages_fts_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER messages_fts_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE VIRTUAL TABLE stories_fts USING fts5(
    title, hook, notes, content='stories', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER stories_fts_ai AFTER INSERT ON stories BEGIN
    INSERT INTO stories_fts(rowid, title, hook, notes) VALUES (new.id, new.title, new.hook, new.notes);
END;
CREATE TRIGGER stories_fts_ad AFTER DELETE ON stories BEGIN
    INSERT INTO stories_fts(stories_fts, rowid, title, hook, notes)
        VALUES ('delete', old.id, old.title, old.hook, old.notes);
END;
CREATE TRIGGER stories_fts_au AFTER UPDATE ON stories BEGIN
    INSERT INTO stories_fts(stories_fts, rowid, title, hook, notes)
        VALUES ('delete', old.id, old.title, old.hook, old.notes);
    INSERT INTO stories_fts(rowid, title, hook, notes) VALUES (new.id, new.title, new.hook, new.notes);
END;

CREATE VIRTUAL TABLE dossiers_fts USING fts5(
    markdown, content='dossiers', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER dossiers_fts_ai AFTER INSERT ON dossiers BEGIN
    INSERT INTO dossiers_fts(rowid, markdown) VALUES (new.id, new.markdown);
END;
CREATE TRIGGER dossiers_fts_ad AFTER DELETE ON dossiers BEGIN
    INSERT INTO dossiers_fts(dossiers_fts, rowid, markdown) VALUES ('delete', old.id, old.markdown);
END;
CREATE TRIGGER dossiers_fts_au AFTER UPDATE ON dossiers BEGIN
    INSERT INTO dossiers_fts(dossiers_fts, rowid, markdown) VALUES ('delete', old.id, old.markdown);
    INSERT INTO dossiers_fts(rowid, markdown) VALUES (new.id, new.markdown);
END;
