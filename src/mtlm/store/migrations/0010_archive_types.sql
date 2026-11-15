-- Migration 0010 — type reconnu des fichiers contenus dans une archive (1.6.0) : robot,
-- indicateur, script… (source lue en mémoire, ou compilé apparié / rangé dans un dossier).
ALTER TABLE archive_entry ADD COLUMN detected_type TEXT
    CHECK (detected_type IS NULL OR detected_type IN ('ea', 'indicator', 'script', 'library',
                                                      'service'));
ALTER TABLE archive_entry ADD COLUMN type_basis TEXT;
