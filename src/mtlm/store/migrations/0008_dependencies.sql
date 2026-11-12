-- Migration 0008 — dépendances entre fichiers (1.4.0) : tout ce qui va avec un outil.
-- Indicateurs appelés par le code : iCustom(symbole, période, "Nom", …).
CREATE TABLE mql_icustom (
    content_id  INTEGER NOT NULL REFERENCES content(id),
    target      TEXT    NOT NULL,
    target_key  TEXT    NOT NULL,
    line        INTEGER NOT NULL
) STRICT;
CREATE INDEX idx_mql_icustom_content ON mql_icustom(content_id);

-- Fichiers liés : table dérivée (recalculée), recréée pour accepter DLL et modèles .tpl.
DROP TABLE companion_link;
CREATE TABLE companion_link (
    id                 INTEGER PRIMARY KEY,
    companion_file_id  INTEGER NOT NULL REFERENCES file_record(id),
    tool_file_id       INTEGER NOT NULL REFERENCES file_record(id),
    kind               TEXT    NOT NULL CHECK (kind IN ('image', 'son', 'document', 'modele',
                                                        'include', 'dll', 'autre')),
    confidence         TEXT    NOT NULL CHECK (confidence IN ('certain', 'probable', 'possible')),
    placement          TEXT    NOT NULL CHECK (placement IN ('avec_son_robot', 'en_vrac',
                                                             'avec_autre_robot',
                                                             'dossier_standard')),
    evidence_json      TEXT    NOT NULL,
    computed_at        TEXT    NOT NULL,
    UNIQUE (companion_file_id, tool_file_id)
) STRICT;
CREATE INDEX idx_companion_tool ON companion_link(tool_file_id);

-- Un outil qui a besoin d'un autre outil : robot → indicateur (iCustom, modèle), robot →
-- bibliothèque compilée (#import "x.ex4"). Dérivé, recalculé à chaque analyse.
CREATE TABLE tool_dependency (
    id              INTEGER PRIMARY KEY,
    user_file_id    INTEGER NOT NULL REFERENCES file_record(id),
    used_file_id    INTEGER NOT NULL REFERENCES file_record(id),
    kind            TEXT    NOT NULL CHECK (kind IN ('icustom', 'import', 'resource')),
    evidence        TEXT    NOT NULL,
    computed_at     TEXT    NOT NULL,
    UNIQUE (user_file_id, used_file_id),
    CHECK (user_file_id <> used_file_id)
) STRICT;
CREATE INDEX idx_tool_dependency_used ON tool_dependency(used_file_id);
