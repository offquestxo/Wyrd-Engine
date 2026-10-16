-- 0007: thumbnail ideas (redesign stage 4). A striking figure and a ≤ 5-word caption, taken
-- only from the story's source text. Whether a dossier confirms the figure is computed when
-- stories are read (from the latest dossier's Key Numbers), so it is never stored stale.
ALTER TABLE stories ADD COLUMN hook_figure TEXT;
ALTER TABLE stories ADD COLUMN hook_caption TEXT;
