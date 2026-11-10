-- Migration 0003 — inspection des archives (phase 4) et suivi des analyses (phase 5).

-- Résultat global de l'inspection d'une archive (une ligne par fichier archive).
CREATE TABLE archive_scan (
    file_id         INTEGER PRIMARY KEY REFERENCES file_record(id),
    content_id      INTEGER REFERENCES content(id),
    format          TEXT    NOT NULL CHECK (format IN ('zip', 'rar', '7z', 'gzip', 'other')),
    status          TEXT    NOT NULL
                    CHECK (status IN ('ok', 'partial', 'corrupt', 'encrypted', 'not_supported',
                                      'rejected')),
    entries_total   INTEGER NOT NULL DEFAULT 0,
    entries_read    INTEGER NOT NULL DEFAULT 0,
    bytes_read      INTEGER NOT NULL DEFAULT 0,
    reason          TEXT,
    engine_version  TEXT    NOT NULL,
    inspected_at    TEXT    NOT NULL
) STRICT;

-- Contenu analysé : permet de ne ré-analyser que ce qui a changé.
ALTER TABLE file_analysis ADD COLUMN content_id INTEGER REFERENCES content(id);
ALTER TABLE file_analysis ADD COLUMN analyzed_at TEXT;
ALTER TABLE file_analysis ADD COLUMN warnings_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE mql_source_meta ADD COLUMN engine_version TEXT;
ALTER TABLE mql_source_meta ADD COLUMN program_type TEXT;
ALTER TABLE mql_source_meta ADD COLUMN entry_points_json TEXT NOT NULL DEFAULT '[]';

CREATE INDEX idx_file_analysis_type ON file_analysis(detected_type, platform);
