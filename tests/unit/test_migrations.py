from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mtlm.core.clock import FixedClock
from mtlm.core.errors import DatabaseTooNewError, MigrationError, MigrationIntegrityError
from mtlm.store.backup import backup_database
from mtlm.store.database import integrity_ok, transaction, user_version
from mtlm.store.migrations_engine import (
    Migration,
    Migrator,
    packaged_migrations,
    split_statements,
    validate_sequence,
)
from tests.conftest import ConnectDb

EXPECTED_TABLES = {
    "source_root",
    "deletion_record",
    "job",
    "job_checkpoint",
    "content",
    "file_record",
    "scan_error",
    "archive_entry",
    "archive_scan",
    "file_analysis",
    "mql_source_meta",
    "mql_input",
    "mql_include",
    "mql_import",
    "set_file",
    "set_parameter",
    "association",
    "association_evidence",
    "file_family",
    "family_member",
    "duplicate_group",
    "duplicate_member",
    "similarity_pair",
    "quarantine_batch",
    "quarantine_entry",
    "organize_plan",
    "organize_item",
    "audit_event",
    "setting",
    "schema_migration",
    "search_fts",
}


def tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows if not r[0].startswith("search_fts_") and r[0] != "sqlite_sequence"}


@pytest.fixture
def conn(tmp_path: Path, connect_db: ConnectDb) -> sqlite3.Connection:
    return connect_db(tmp_path / "t.sqlite")


def migrator(conn: sqlite3.Connection, clock: FixedClock, **kw: object) -> Migrator:
    return Migrator(conn, clock=clock, app_version="test", **kw)  # type: ignore[arg-type]


def test_base_vide_migree_jusqu_a_la_derniere_version(
    conn: sqlite3.Connection, clock: FixedClock
) -> None:
    applied = migrator(conn, clock).migrate()
    assert applied == [m.version for m in packaged_migrations()]
    assert user_version(conn) == packaged_migrations()[-1].version
    assert tables(conn) == EXPECTED_TABLES
    assert integrity_ok(conn)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_idempotente(conn: sqlite3.Connection, clock: FixedClock) -> None:
    migrator(conn, clock).migrate()
    assert migrator(conn, clock).migrate() == []
    assert migrator(conn, clock).status().up_to_date


def test_pragmas_de_fiabilite(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL


def test_echec_de_migration_annule_tout(conn: sqlite3.Connection, clock: FixedClock) -> None:
    good = Migration(1, "ok", "CREATE TABLE a (x INTEGER) STRICT;")
    bad = Migration(
        2, "ko", "CREATE TABLE b (x INTEGER) STRICT;\nINSERT INTO inexistante VALUES (1);"
    )
    migrator(conn, clock, migrations=[good]).migrate()
    with pytest.raises(MigrationError, match="état précédent"):
        migrator(conn, clock, migrations=[good, bad]).migrate()
    assert user_version(conn) == 1
    assert "b" not in tables(conn)
    versions = [r[0] for r in conn.execute("SELECT version FROM schema_migration")]
    assert versions == [1]


def test_script_modifie_apres_application_refuse(
    conn: sqlite3.Connection, clock: FixedClock
) -> None:
    migrator(conn, clock, migrations=[Migration(1, "a", "CREATE TABLE a (x INTEGER);")]).migrate()
    tampered = Migration(1, "a", "CREATE TABLE a (x INTEGER, y INTEGER);")
    with pytest.raises(MigrationIntegrityError):
        migrator(conn, clock, migrations=[tampered]).migrate()


def test_base_plus_recente_jamais_modifiee(conn: sqlite3.Connection, clock: FixedClock) -> None:
    first = Migration(1, "a", "CREATE TABLE a (x INTEGER);")
    second = Migration(2, "b", "CREATE TABLE b (x INTEGER);")
    migrator(conn, clock, migrations=[first, second]).migrate()
    before = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    with pytest.raises(DatabaseTooNewError):
        migrator(conn, clock, migrations=[first]).migrate()
    assert conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == before


def test_sequence_non_contigue_refusee() -> None:
    with pytest.raises(MigrationError, match="Séquence"):
        validate_sequence([Migration(1, "a", "SELECT 1;"), Migration(3, "c", "SELECT 1;")])


def test_sauvegarde_avant_migration_d_une_base_existante(
    tmp_path: Path, conn: sqlite3.Connection, clock: FixedClock
) -> None:
    first = Migration(1, "a", "CREATE TABLE a (x INTEGER);")
    second = Migration(2, "b", "CREATE TABLE b (x INTEGER);")
    backups: list[Path] = []

    def hook(c: sqlite3.Connection, label: str) -> Path:
        path = backup_database(c, tmp_path / "bk", clock, label)
        backups.append(path)
        return path

    migrator(conn, clock, migrations=[first], backup=hook).migrate()
    assert backups == []  # base neuve : rien à sauvegarder
    migrator(conn, clock, migrations=[first, second], backup=hook).migrate()
    assert len(backups) == 1
    saved = sqlite3.connect(backups[0])
    try:
        assert saved.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        saved.close()


def test_decoupage_des_instructions_avec_trigger() -> None:
    sql = """
    -- commentaire
    CREATE TABLE t (x INTEGER);
    CREATE TRIGGER tr BEFORE DELETE ON t
    BEGIN
        SELECT RAISE(ABORT, 'non; vraiment');
    END;
    -- fin
    """
    statements = split_statements(sql)
    assert len(statements) == 2
    assert statements[1].endswith("END;")


def test_instruction_incomplete_refusee() -> None:
    with pytest.raises(MigrationError, match="incomplet"):
        split_statements("CREATE TABLE t (x INTEGER)")


def test_transaction_annulee_sur_exception(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(RuntimeError), transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
        raise RuntimeError("boom")
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 0


# --- contraintes du schéma ---------------------------------------------------------------


@pytest.fixture
def db(conn: sqlite3.Connection, clock: FixedClock) -> sqlite3.Connection:
    migrator(conn, clock).migrate()
    conn.execute(
        "INSERT INTO source_root(id, path, display_name, added_at) VALUES (1, '/src', 'S', 't')"
    )
    conn.execute(
        "INSERT INTO file_record(id, root_id, rel_path, rel_path_bytes, name)"
        " VALUES (1, 1, 'a', x'61', 'a'), (2, 1, 'b', x'62', 'b')"
    )
    return conn


def test_tables_strictes_refusent_un_mauvais_type(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE file_record SET size = 'grand' WHERE id = 1")


def test_hash_valide_exige_un_contenu(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE file_record SET hash_state = 'validated' WHERE id = 1")


def test_cle_etrangere_appliquee(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO file_record(root_id, rel_path, rel_path_bytes, name)"
            " VALUES (99, 'x', x'78', 'x')"
        )


def test_reference_de_doublon_jamais_admissible_en_quarantaine(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO duplicate_group(id, sha256, size, member_count) VALUES (1, zeroblob(32), 0, 2)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO duplicate_member(group_id, file_id, is_reference,"
            " admissible_for_quarantine) VALUES (1, 1, 1, 1)"
        )


def test_similarite_ordonnee_et_bornee(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO similarity_pair VALUES (2, 1, 'text_similar', 0.9, 'm', 't')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO similarity_pair VALUES (1, 2, 'text_similar', 1.5, 'm', 't')")


def test_quarantaine_confirmee_exige_une_confirmation(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO quarantine_batch(created_at, destination_root, status)"
            " VALUES ('t', '/q', 'confirmed')"
        )


def test_aucun_etat_de_quarantaine_ne_touche_l_original(db: sqlite3.Connection) -> None:
    """Décision du propriétaire : copie uniquement ; aucun état « source supprimée »."""
    db.execute(
        "INSERT INTO quarantine_batch(id, created_at, destination_root) VALUES (1, 't', '/q')"
    )
    for forbidden in ("source_removed", "moved", "deleted"):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO quarantine_entry(batch_id, file_id, source_path_bytes,"
                " dest_path_bytes, sha256, size, source_mtime_ns, decision, reason, state,"
                " updated_at) VALUES (1, 1, x'61', x'62', zeroblob(32), 0, 0, 'd', 'r', ?, 't')",
                (forbidden,),
            )


def test_association_decidee_exige_une_date(db: sqlite3.Connection) -> None:
    db.execute("INSERT INTO set_file(file_id, format) VALUES (2, 'mt4')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO association(robot_file_id, set_file_id, score, level, engine_version,"
            " computed_at, user_decision) VALUES (1, 2, 80, 'forte', 'e', 't', 'accepted')"
        )


def test_recherche_plein_texte_sans_accents(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO search_fts(name, rel_path) VALUES ('Élan Expert', 'MQL4/Experts/Élan.mq4')"
    )
    rows = db.execute("SELECT name FROM search_fts WHERE search_fts MATCH 'elan'").fetchall()
    assert rows == [("Élan Expert",)]
