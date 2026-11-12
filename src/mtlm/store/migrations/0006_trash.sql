-- Migration 0006 — mise à la Corbeille du Mac (1.3.0, décision du propriétaire).
-- Chaque fichier retiré d'une bibliothèque est tracé : d'où il vient, où il est dans la
-- Corbeille, son empreinte, et la copie identique conservée qui a été vérifiée avant.
CREATE TABLE deletion_record (
    id                  INTEGER PRIMARY KEY,
    file_id             INTEGER NOT NULL REFERENCES file_record(id),
    origin              TEXT    NOT NULL CHECK (origin IN ('doublons', 'quarantaine', 'familles')),
    original_path_bytes BLOB    NOT NULL,
    trash_path_bytes    BLOB    NOT NULL,
    sha256              BLOB    NOT NULL CHECK (length(sha256) = 32),
    size                INTEGER NOT NULL CHECK (size >= 0),
    keeper_kind         TEXT    NOT NULL CHECK (keeper_kind IN ('fichier', 'quarantaine', 'aucun')),
    keeper_file_id      INTEGER REFERENCES file_record(id),
    keeper_path_bytes   BLOB,
    state               TEXT    NOT NULL CHECK (state IN ('trashed', 'restored')),
    created_at          TEXT    NOT NULL,
    restored_at         TEXT,
    CHECK (keeper_kind = 'aucun' OR keeper_path_bytes IS NOT NULL),
    CHECK (state = 'trashed' OR restored_at IS NOT NULL)
) STRICT;

CREATE INDEX idx_deletion_file ON deletion_record(file_id);
