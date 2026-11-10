-- Migration 0004 — analyse SET (phase 6) et familles (phase 7).
ALTER TABLE set_file ADD COLUMN content_id INTEGER REFERENCES content(id);
ALTER TABLE set_file ADD COLUMN engine_version TEXT;
ALTER TABLE set_file ADD COLUMN format_basis TEXT;

ALTER TABLE file_family ADD COLUMN platform TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE file_family ADD COLUMN engine_version TEXT;

CREATE INDEX idx_association_level ON association(level);
CREATE INDEX idx_family_key ON file_family(logical_key);
