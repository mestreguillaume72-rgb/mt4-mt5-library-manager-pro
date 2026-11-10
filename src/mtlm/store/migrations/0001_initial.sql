-- Migration 0001 — schéma initial (ARCHITECTURE § 6, modèle minimal de la spécification § 4).
-- Tables STRICT : SQLite refuse toute valeur du mauvais type.
-- Règle : une migration publiée n'est JAMAIS modifiée (empreinte vérifiée au démarrage) ;
-- toute évolution passe par une nouvelle migration numérotée.

CREATE TABLE source_root (
    id                  INTEGER PRIMARY KEY,
    path                TEXT    NOT NULL UNIQUE,
    display_name        TEXT    NOT NULL,
    added_at            TEXT    NOT NULL,
    last_scan_job_id    INTEGER REFERENCES job(id),
    device              INTEGER,
    read_only_verified  INTEGER NOT NULL DEFAULT 1 CHECK (read_only_verified IN (0, 1)),
    status              TEXT    NOT NULL DEFAULT 'ok'
                        CHECK (status IN ('ok', 'unreachable', 'permission_denied', 'removed'))
) STRICT;

CREATE TABLE job (
    id              INTEGER PRIMARY KEY,
    kind            TEXT    NOT NULL CHECK (kind IN ('scan', 'hash', 'archives', 'recognize', 'sets',
                                                     'match', 'families', 'duplicates', 'quarantine',
                                                     'restore', 'organize', 'report')),
    params_json     TEXT    NOT NULL DEFAULT '{}',
    state           TEXT    NOT NULL DEFAULT 'queued'
                    CHECK (state IN ('queued', 'running', 'paused', 'cancelling', 'cancelled',
                                     'completed', 'failed', 'interrupted')),
    progress_done   INTEGER NOT NULL DEFAULT 0 CHECK (progress_done >= 0),
    progress_total  INTEGER CHECK (progress_total IS NULL OR progress_total >= 0),
    created_at      TEXT    NOT NULL,
    started_at      TEXT,
    updated_at      TEXT,
    finished_at     TEXT,
    errors_count    INTEGER NOT NULL DEFAULT 0 CHECK (errors_count >= 0),
    engine_version  TEXT    NOT NULL
) STRICT;

CREATE TABLE job_checkpoint (
    job_id      INTEGER NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    key         TEXT    NOT NULL,
    value_json  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    PRIMARY KEY (job_id, key)
) STRICT;

CREATE TABLE content (
    id      INTEGER PRIMARY KEY,
    sha256  BLOB    NOT NULL UNIQUE CHECK (length(sha256) = 32),
    size    INTEGER NOT NULL CHECK (size >= 0)
) STRICT;
CREATE INDEX idx_content_size ON content(size);

CREATE TABLE file_record (
    id                  INTEGER PRIMARY KEY,
    root_id             INTEGER NOT NULL REFERENCES source_root(id),
    rel_path            TEXT    NOT NULL,
    rel_path_bytes      BLOB    NOT NULL,
    name                TEXT    NOT NULL,
    ext                 TEXT    NOT NULL DEFAULT '',
    size                INTEGER CHECK (size IS NULL OR size >= 0),
    mtime_ns            INTEGER,
    ctime_ns            INTEGER,
    birthtime_ns        INTEGER,
    inode               INTEGER,
    device              INTEGER,
    mode                INTEGER,
    is_symlink          INTEGER NOT NULL DEFAULT 0 CHECK (is_symlink IN (0, 1)),
    is_dataless         INTEGER NOT NULL DEFAULT 0 CHECK (is_dataless IN (0, 1)),
    magic               TEXT,
    content_id          INTEGER REFERENCES content(id),
    hash_state          TEXT    NOT NULL DEFAULT 'not_computed'
                        CHECK (hash_state IN ('not_computed', 'in_progress', 'validated', 'error', 'stale')),
    hash_error          TEXT,
    hashed_with_engine  TEXT,
    presence            TEXT    NOT NULL DEFAULT 'present' CHECK (presence IN ('present', 'missing')),
    in_quarantine       INTEGER NOT NULL DEFAULT 0 CHECK (in_quarantine IN (0, 1)),
    first_seen_job      INTEGER REFERENCES job(id),
    last_seen_job       INTEGER REFERENCES job(id),
    UNIQUE (root_id, rel_path_bytes),
    CHECK (hash_state <> 'validated' OR content_id IS NOT NULL)
) STRICT;
CREATE INDEX idx_file_root_presence ON file_record(root_id, presence);
CREATE INDEX idx_file_content ON file_record(content_id);
CREATE INDEX idx_file_size ON file_record(size);
CREATE INDEX idx_file_ext ON file_record(ext);
CREATE INDEX idx_file_hash_state ON file_record(hash_state);
CREATE INDEX idx_file_name ON file_record(name);

CREATE TABLE scan_error (
    id              INTEGER PRIMARY KEY,
    job_id          INTEGER NOT NULL REFERENCES job(id),
    root_id         INTEGER NOT NULL REFERENCES source_root(id),
    rel_path_bytes  BLOB    NOT NULL,
    errno           INTEGER,
    message         TEXT    NOT NULL,
    at              TEXT    NOT NULL
) STRICT;

CREATE TABLE archive_entry (
    id               INTEGER PRIMARY KEY,
    archive_file_id  INTEGER NOT NULL REFERENCES file_record(id),
    inner_path       TEXT    NOT NULL,
    depth            INTEGER NOT NULL CHECK (depth >= 1),
    size             INTEGER CHECK (size IS NULL OR size >= 0),
    compressed_size  INTEGER CHECK (compressed_size IS NULL OR compressed_size >= 0),
    is_encrypted     INTEGER NOT NULL DEFAULT 0 CHECK (is_encrypted IN (0, 1)),
    is_dir           INTEGER NOT NULL DEFAULT 0 CHECK (is_dir IN (0, 1)),
    content_id       INTEGER REFERENCES content(id),
    status           TEXT    NOT NULL
                     CHECK (status IN ('inspected', 'skipped_limit', 'rejected_traversal',
                                       'rejected_symlink', 'encrypted', 'corrupt')),
    reason           TEXT
) STRICT;
CREATE INDEX idx_archive_entry_archive ON archive_entry(archive_file_id);

CREATE TABLE file_analysis (
    file_id         INTEGER PRIMARY KEY REFERENCES file_record(id),
    detected_type   TEXT    NOT NULL
                    CHECK (detected_type IN ('ea', 'indicator', 'script', 'library', 'include',
                                             'service', 'set', 'dll', 'template', 'resource', 'unknown')),
    platform        TEXT    NOT NULL CHECK (platform IN ('mt4', 'mt5', 'unknown')),
    certainty       TEXT    NOT NULL CHECK (certainty IN ('certain', 'probable', 'possible', 'unknown')),
    basis_json      TEXT    NOT NULL,
    limits          TEXT,
    engine_version  TEXT    NOT NULL
) STRICT;

CREATE TABLE mql_source_meta (
    content_id           INTEGER PRIMARY KEY REFERENCES content(id),
    encoding             TEXT,
    encoding_confidence  REAL,
    line_count           INTEGER,
    prop_version         TEXT,
    prop_copyright       TEXT,
    prop_link            TEXT,
    prop_description     TEXT,
    prop_strict          INTEGER CHECK (prop_strict IS NULL OR prop_strict IN (0, 1)),
    normalized_sha256    BLOB,
    minhash              BLOB,
    warnings_json        TEXT NOT NULL DEFAULT '[]'
) STRICT;

CREATE TABLE mql_input (
    content_id   INTEGER NOT NULL REFERENCES content(id),
    ordinal      INTEGER NOT NULL,
    name         TEXT    NOT NULL,
    mql_type     TEXT,
    default_raw  TEXT,
    modifier     TEXT    NOT NULL CHECK (modifier IN ('input', 'extern', 'sinput')),
    line         INTEGER,
    PRIMARY KEY (content_id, ordinal)
) STRICT;
CREATE INDEX idx_mql_input_name ON mql_input(name);

CREATE TABLE mql_include (
    content_id  INTEGER NOT NULL REFERENCES content(id),
    target      TEXT    NOT NULL,
    is_system   INTEGER NOT NULL CHECK (is_system IN (0, 1)),
    line        INTEGER
) STRICT;

CREATE TABLE mql_import (
    content_id  INTEGER NOT NULL REFERENCES content(id),
    module      TEXT    NOT NULL,
    line        INTEGER
) STRICT;

CREATE TABLE set_file (
    file_id             INTEGER PRIMARY KEY REFERENCES file_record(id),
    format              TEXT    NOT NULL CHECK (format IN ('mt4', 'mt5', 'unknown')),
    encoding            TEXT,
    line_count          INTEGER,
    param_count         INTEGER,
    duplicate_keys_json TEXT    NOT NULL DEFAULT '[]',
    warnings_json       TEXT    NOT NULL DEFAULT '[]',
    normalized_sha256   BLOB
) STRICT;

CREATE TABLE set_parameter (
    file_id           INTEGER NOT NULL REFERENCES set_file(file_id),
    ordinal           INTEGER NOT NULL,
    name              TEXT    NOT NULL,
    raw_value         TEXT    NOT NULL,
    normalized_value  TEXT,
    estimated_type    TEXT    NOT NULL DEFAULT 'unknown'
                      CHECK (estimated_type IN ('bool', 'int', 'double', 'string', 'datetime',
                                                'color', 'enum_int', 'unknown')),
    opt_start         TEXT,
    opt_step          TEXT,
    opt_stop          TEXT,
    opt_enabled       INTEGER CHECK (opt_enabled IS NULL OR opt_enabled IN (0, 1)),
    comment           TEXT,
    line              INTEGER,
    PRIMARY KEY (file_id, ordinal)
) STRICT;
CREATE INDEX idx_set_parameter_name ON set_parameter(name);

CREATE TABLE association (
    id              INTEGER PRIMARY KEY,
    robot_file_id   INTEGER NOT NULL REFERENCES file_record(id),
    set_file_id     INTEGER NOT NULL REFERENCES set_file(file_id),
    score           REAL    NOT NULL CHECK (score >= 0 AND score <= 100),
    level           TEXT    NOT NULL CHECK (level IN ('forte', 'moyenne', 'faible', 'a_verifier')),
    engine_version  TEXT    NOT NULL,
    computed_at     TEXT    NOT NULL,
    user_decision   TEXT    NOT NULL DEFAULT 'none' CHECK (user_decision IN ('none', 'accepted', 'rejected')),
    decided_at      TEXT,
    UNIQUE (robot_file_id, set_file_id),
    CHECK (user_decision = 'none' OR decided_at IS NOT NULL)
) STRICT;
CREATE INDEX idx_association_robot ON association(robot_file_id);
CREATE INDEX idx_association_set ON association(set_file_id);

CREATE TABLE association_evidence (
    association_id  INTEGER NOT NULL REFERENCES association(id) ON DELETE CASCADE,
    kind            TEXT    NOT NULL,
    weight          REAL    NOT NULL,
    value           REAL    NOT NULL,
    polarity        TEXT    NOT NULL CHECK (polarity IN ('pour', 'contre', 'incertitude')),
    detail_json     TEXT    NOT NULL DEFAULT '{}'
) STRICT;

CREATE TABLE file_family (
    id            INTEGER PRIMARY KEY,
    logical_key   TEXT    NOT NULL,
    display_name  TEXT    NOT NULL,
    basis_json    TEXT    NOT NULL,
    confidence    TEXT    NOT NULL CHECK (confidence IN ('certain', 'probable', 'possible', 'unknown'))
) STRICT;

CREATE TABLE family_member (
    family_id          INTEGER NOT NULL REFERENCES file_family(id) ON DELETE CASCADE,
    file_id            INTEGER NOT NULL REFERENCES file_record(id),
    relation           TEXT    NOT NULL
                       CHECK (relation IN ('exact_copy', 'renamed_copy', 'version_variant', 'source_of',
                                           'compiled_variant', 'homonym_different', 'set_for')),
    estimated_version  TEXT,
    version_basis      TEXT,
    confidence         TEXT    NOT NULL CHECK (confidence IN ('certain', 'probable', 'possible', 'unknown')),
    PRIMARY KEY (family_id, file_id)
) STRICT;
CREATE INDEX idx_family_member_file ON family_member(file_id);

CREATE TABLE duplicate_group (
    id                 INTEGER PRIMARY KEY,
    sha256             BLOB    NOT NULL UNIQUE CHECK (length(sha256) = 32),
    size               INTEGER NOT NULL CHECK (size >= 0),
    member_count       INTEGER NOT NULL CHECK (member_count >= 2),
    reference_file_id  INTEGER REFERENCES file_record(id),
    verified_at        TEXT,
    verification       TEXT    CHECK (verification IS NULL OR verification IN ('sha256', 'sha256+bytewise'))
) STRICT;

CREATE TABLE duplicate_member (
    group_id                   INTEGER NOT NULL REFERENCES duplicate_group(id) ON DELETE CASCADE,
    file_id                    INTEGER NOT NULL REFERENCES file_record(id),
    is_reference               INTEGER NOT NULL DEFAULT 0 CHECK (is_reference IN (0, 1)),
    admissible_for_quarantine  INTEGER NOT NULL DEFAULT 0 CHECK (admissible_for_quarantine IN (0, 1)),
    inadmissible_reason        TEXT,
    PRIMARY KEY (group_id, file_id),
    CHECK (NOT (is_reference = 1 AND admissible_for_quarantine = 1))
) STRICT;

-- Similarités : table distincte des doublons exacts (D-008), jamais confondues.
CREATE TABLE similarity_pair (
    file_a       INTEGER NOT NULL REFERENCES file_record(id),
    file_b       INTEGER NOT NULL REFERENCES file_record(id),
    kind         TEXT    NOT NULL CHECK (kind IN ('text_normalized_equal', 'text_similar', 'set_similar')),
    score        REAL    NOT NULL CHECK (score >= 0 AND score <= 1),
    method       TEXT    NOT NULL,
    computed_at  TEXT    NOT NULL,
    PRIMARY KEY (file_a, file_b, kind),
    CHECK (file_a < file_b)
) STRICT;

-- Quarantaine : copie vérifiée uniquement (D-007, décision du propriétaire du 2026-11-10).
-- Aucun état ne correspond à une modification ou suppression de l'original.
CREATE TABLE quarantine_batch (
    id                   INTEGER PRIMARY KEY,
    created_at           TEXT    NOT NULL,
    destination_root     TEXT    NOT NULL,
    dry_run_report_path  TEXT,
    confirmed_at         TEXT,
    confirmation_token   TEXT,
    status               TEXT    NOT NULL DEFAULT 'simulated'
                         CHECK (status IN ('simulated', 'confirmed', 'running', 'completed',
                                           'failed', 'interrupted', 'cancelled')),
    manifest_path        TEXT,
    CHECK (status = 'simulated' OR status = 'cancelled' OR confirmed_at IS NOT NULL)
) STRICT;

CREATE TABLE quarantine_entry (
    id                 INTEGER PRIMARY KEY,
    batch_id           INTEGER NOT NULL REFERENCES quarantine_batch(id),
    file_id            INTEGER NOT NULL REFERENCES file_record(id),
    source_path_bytes  BLOB    NOT NULL,
    dest_path_bytes    BLOB    NOT NULL,
    sha256             BLOB    NOT NULL CHECK (length(sha256) = 32),
    size               INTEGER NOT NULL CHECK (size >= 0),
    source_mtime_ns    INTEGER NOT NULL,
    decision           TEXT    NOT NULL,
    reason             TEXT    NOT NULL,
    state              TEXT    NOT NULL DEFAULT 'planned'
                       CHECK (state IN ('planned', 'copying', 'copied', 'verified',
                                        'restoring', 'restored', 'failed', 'conflict')),
    updated_at         TEXT    NOT NULL,
    error              TEXT
) STRICT;
CREATE INDEX idx_quarantine_entry_batch ON quarantine_entry(batch_id);

CREATE TABLE organize_plan (
    id                INTEGER PRIMARY KEY,
    created_at        TEXT    NOT NULL,
    destination_root  TEXT    NOT NULL,
    rules_json        TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'preview'
                      CHECK (status IN ('preview', 'running', 'completed', 'failed', 'interrupted', 'cancelled')),
    collisions_count  INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE organize_item (
    plan_id          INTEGER NOT NULL REFERENCES organize_plan(id) ON DELETE CASCADE,
    file_id          INTEGER NOT NULL REFERENCES file_record(id),
    target_rel_path  TEXT    NOT NULL,
    collision_of     INTEGER REFERENCES file_record(id),
    state            TEXT    NOT NULL DEFAULT 'planned'
                     CHECK (state IN ('planned', 'copying', 'copied', 'verified', 'failed', 'skipped')),
    sha256_dest      BLOB,
    error            TEXT,
    PRIMARY KEY (plan_id, file_id)
) STRICT;

-- Journal d'audit append-only, chaîné par empreinte (D-010).
CREATE TABLE audit_event (
    id            INTEGER PRIMARY KEY,
    ts            TEXT    NOT NULL,
    actor         TEXT    NOT NULL,
    action        TEXT    NOT NULL,
    object        TEXT    NOT NULL,
    result        TEXT    NOT NULL CHECK (result IN ('ok', 'refused', 'failed', 'cancelled')),
    details_json  TEXT    NOT NULL DEFAULT '{}',
    prev_hash     BLOB    NOT NULL CHECK (length(prev_hash) = 32),
    hash          BLOB    NOT NULL UNIQUE CHECK (length(hash) = 32)
) STRICT;

CREATE TRIGGER audit_event_no_update BEFORE UPDATE ON audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit_event est append-only : modification interdite');
END;

CREATE TRIGGER audit_event_no_delete BEFORE DELETE ON audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit_event est append-only : suppression interdite');
END;

CREATE TABLE setting (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL
) STRICT;

CREATE VIRTUAL TABLE search_fts USING fts5(
    name, rel_path, prop_description, prop_copyright, set_params,
    tokenize = 'unicode61 remove_diacritics 2'
);
