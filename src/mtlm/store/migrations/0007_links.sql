-- Migration 0007 — indices « faits pour aller ensemble » (1.3.0).
-- Fichiers cités par le code d'un outil (#resource, chaînes « logo.bmp », « alerte.wav »…).
CREATE TABLE mql_reference (
    content_id  INTEGER NOT NULL REFERENCES content(id),
    target      TEXT    NOT NULL,
    target_key  TEXT    NOT NULL,
    kind        TEXT    NOT NULL CHECK (kind IN ('resource', 'chaine')),
    line        INTEGER NOT NULL
) STRICT;
CREATE INDEX idx_mql_reference_content ON mql_reference(content_id);
CREATE INDEX idx_mql_reference_key ON mql_reference(target_key);

-- Nom du robot écrit par MetaTrader dans l'en-tête d'un SET (MT5).
ALTER TABLE set_file ADD COLUMN robot_named TEXT;

-- Fichiers liés à un outil (images, sons, documents, modèles, includes) : dérivé, recalculé.
CREATE TABLE companion_link (
    id                 INTEGER PRIMARY KEY,
    companion_file_id  INTEGER NOT NULL REFERENCES file_record(id),
    tool_file_id       INTEGER NOT NULL REFERENCES file_record(id),
    kind               TEXT    NOT NULL CHECK (kind IN ('image', 'son', 'document', 'modele',
                                                        'include', 'autre')),
    confidence         TEXT    NOT NULL CHECK (confidence IN ('certain', 'probable', 'possible')),
    placement          TEXT    NOT NULL CHECK (placement IN ('avec_son_robot', 'en_vrac',
                                                             'avec_autre_robot')),
    evidence_json      TEXT    NOT NULL,
    computed_at        TEXT    NOT NULL,
    UNIQUE (companion_file_id, tool_file_id)
) STRICT;
CREATE INDEX idx_companion_tool ON companion_link(tool_file_id);
