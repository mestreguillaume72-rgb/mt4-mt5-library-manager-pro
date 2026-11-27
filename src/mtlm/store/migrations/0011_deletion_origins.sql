-- Migration 0011 — suppression « où je veux » (1.6.0) : la Corbeille est possible depuis
-- l'Explorateur, les SET, les sources MQ4/MQ5, les robots et indicateurs isolés et les
-- fichiers à risque. Seules les origines autorisées changent.
DROP INDEX IF EXISTS idx_deletion_file;
CREATE TABLE deletion_record_new (
    id                  INTEGER PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES file_record(id),
    origin              TEXT    NOT NULL CHECK (origin IN ('doublons', 'quarantaine', 'familles',
                                                           'archives', 'explorateur', 'sets',
                                                           'sources', 'outils', 'risques')),
    original_path_bytes BLOB    NOT NULL,
    trash_path_bytes    BLOB    NOT NULL,
    sha256              BLOB    NOT NULL CHECK (length(sha256) = 32),
    size                INTEGER NOT NULL CHECK (size >= 0),
    keeper_kind         TEXT    NOT NULL CHECK (keeper_kind IN ('fichier', 'quarantaine', 'aucun',
                                                                'extraction')),
    keeper_file_id      INTEGER REFERENCES file_record(id),
    keeper_path_bytes   BLOB,
    state               TEXT    NOT NULL CHECK (state IN ('trashed', 'restored')),
    created_at          TEXT    NOT NULL,
    restored_at         TEXT,
    CHECK (keeper_kind = 'aucun' OR keeper_path_bytes IS NOT NULL),
    CHECK (state = 'trashed' OR restored_at IS NOT NULL)
) STRICT;
INSERT INTO deletion_record_new SELECT * FROM deletion_record;
DROP TABLE deletion_record;
ALTER TABLE deletion_record_new RENAME TO deletion_record;
CREATE INDEX idx_deletion_file ON deletion_record(file_id);
