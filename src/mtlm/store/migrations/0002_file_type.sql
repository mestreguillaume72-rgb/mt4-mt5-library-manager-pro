-- Migration 0002 — type d'entrée du système de fichiers (Phase 2, scanner).
-- 'file' : fichier ordinaire ; 'symlink' : lien symbolique (enregistré, jamais suivi) ;
-- 'other' : tube, socket, périphérique… (inventorié, jamais lu).
ALTER TABLE file_record ADD COLUMN file_type TEXT NOT NULL DEFAULT 'file'
    CHECK (file_type IN ('file', 'symlink', 'other'));

CREATE INDEX idx_file_last_seen ON file_record(root_id, last_seen_job);
