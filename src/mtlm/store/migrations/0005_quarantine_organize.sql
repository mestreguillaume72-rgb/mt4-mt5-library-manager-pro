-- Migration 0005 — doublons, quarantaine par copie (phase 8), bibliothèque organisée (phase 9).
ALTER TABLE duplicate_group ADD COLUMN reference_chosen_by_user INTEGER NOT NULL DEFAULT 0
    CHECK (reference_chosen_by_user IN (0, 1));
ALTER TABLE duplicate_group ADD COLUMN engine_version TEXT;

ALTER TABLE quarantine_batch ADD COLUMN batch_uuid TEXT;
ALTER TABLE quarantine_batch ADD COLUMN plan_sha256 TEXT;
ALTER TABLE quarantine_batch ADD COLUMN total_bytes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE quarantine_batch ADD COLUMN reason TEXT;

ALTER TABLE organize_plan ADD COLUMN plan_sha256 TEXT;
ALTER TABLE organize_plan ADD COLUMN template TEXT;
ALTER TABLE organize_plan ADD COLUMN total_bytes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE organize_item ADD COLUMN size INTEGER;
ALTER TABLE organize_item ADD COLUMN sha256_expected BLOB;

CREATE INDEX idx_duplicate_member_file ON duplicate_member(file_id);
CREATE INDEX idx_quarantine_entry_file ON quarantine_entry(file_id);
CREATE INDEX idx_similarity_b ON similarity_pair(file_b);
