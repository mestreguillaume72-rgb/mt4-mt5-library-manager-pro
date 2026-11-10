from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from mtlm.core.clock import FixedClock
from mtlm.core.errors import BackupError
from mtlm.store import backup as backup_module
from mtlm.store.backup import backup_database, inspect_backup, restore_database
from mtlm.store.migrations_engine import Migrator, packaged_migrations
from tests.conftest import ConnectDb

LATEST = packaged_migrations()[-1].version

MakeDb = Callable[[Path, FixedClock, str], sqlite3.Connection]


@pytest.fixture
def make_db(connect_db: ConnectDb) -> MakeDb:
    def _make(path: Path, clock: FixedClock, value: str) -> sqlite3.Connection:
        conn = connect_db(path)
        Migrator(conn, clock=clock, app_version="test").migrate()
        conn.execute("INSERT OR REPLACE INTO setting VALUES ('k', ?)", (f'"{value}"',))
        return conn

    return _make


def setting(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return str(conn.execute("SELECT value_json FROM setting WHERE key='k'").fetchone()[0])
    finally:
        conn.close()


def test_sauvegarde_verifiee_et_lisible(tmp_path: Path, clock: FixedClock, make_db: MakeDb) -> None:
    conn = make_db(tmp_path / "db.sqlite", clock, "v1")
    path = backup_database(conn, tmp_path / "bk", clock, "test")
    assert path.name == "library-20261110T120000000000Z-test.sqlite"
    assert inspect_backup(path) == LATEST
    assert setting(path) == '"v1"'
    assert not list((tmp_path / "bk").glob("*.partial"))


def test_sauvegarde_n_ecrase_jamais(tmp_path: Path, clock: FixedClock, make_db: MakeDb) -> None:
    conn = make_db(tmp_path / "db.sqlite", clock, "v1")
    first = backup_database(conn, tmp_path / "bk", clock, "x")
    second = backup_database(conn, tmp_path / "bk", clock, "x")
    assert first != second
    assert second.name.endswith("-x-2.sqlite")


def test_libelle_nettoye(tmp_path: Path, clock: FixedClock, make_db: MakeDb) -> None:
    conn = make_db(tmp_path / "db.sqlite", clock, "v1")
    path = backup_database(conn, tmp_path / "bk", clock, "../../etc/passwd")
    assert path.parent == tmp_path / "bk"
    assert backup_database(conn, tmp_path / "bk", clock, "///").name.endswith("-sauvegarde.sqlite")


def test_fichier_partiel_orphelin_remplace(
    tmp_path: Path, clock: FixedClock, make_db: MakeDb
) -> None:
    conn = make_db(tmp_path / "db.sqlite", clock, "v1")
    orphan = tmp_path / "bk" / "library-20261110T120000000000Z-x.sqlite.partial"
    orphan.parent.mkdir()
    orphan.write_bytes(b"reste d'une sauvegarde interrompue")
    path = backup_database(conn, tmp_path / "bk", clock, "x")
    assert inspect_backup(path) == LATEST and not orphan.exists()


def test_sauvegarde_corrompue_refusee(
    tmp_path: Path, clock: FixedClock, make_db: MakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = make_db(tmp_path / "db.sqlite", clock, "v1")
    monkeypatch.setattr(backup_module, "integrity_ok", lambda _c: False)
    with pytest.raises(BackupError, match="corrompue"):
        backup_database(conn, tmp_path / "bk", clock, "x")
    assert list((tmp_path / "bk").iterdir()) == []  # aucun fichier douteux laissé


def test_sauvegarde_version_incoherente_refusee(
    tmp_path: Path, clock: FixedClock, make_db: MakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = make_db(tmp_path / "db.sqlite", clock, "v1")
    versions = iter([LATEST, 0])
    monkeypatch.setattr(backup_module, "user_version", lambda _c: next(versions))
    with pytest.raises(BackupError, match="Version de schéma"):
        backup_database(conn, tmp_path / "bk", clock, "x")


def test_erreur_systeme_convertie(
    tmp_path: Path, clock: FixedClock, make_db: MakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = make_db(tmp_path / "db.sqlite", clock, "v1")

    def boom(*_args: object, **_kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("disque plein (simulé)")

    monkeypatch.setattr(sqlite3, "connect", boom)
    with pytest.raises(BackupError, match="disque plein"):
        backup_database(conn, tmp_path / "bk", clock, "x")


@pytest.mark.parametrize(
    "content, message",
    [(b"pas une base", "illisible|corrompue"), (b"", "pas une base")],
)
def test_inspection_refuse_les_fichiers_invalides(
    tmp_path: Path, content: bytes, message: str
) -> None:
    path = tmp_path / "faux.sqlite"
    path.write_bytes(content)
    with pytest.raises(BackupError, match=message):
        inspect_backup(path)


def test_inspection_refuse_une_base_etrangere(tmp_path: Path) -> None:
    path = tmp_path / "autre.sqlite"
    other = sqlite3.connect(path)
    other.execute("CREATE TABLE x (y)")
    other.commit()
    other.close()
    with pytest.raises(BackupError, match="pas une base"):
        inspect_backup(path)


def test_inspection_fichier_absent(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="introuvable"):
        inspect_backup(tmp_path / "absent.sqlite")


def test_inspection_integrite_en_echec(
    tmp_path: Path, clock: FixedClock, make_db: MakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = make_db(tmp_path / "db.sqlite", clock, "v")
    saved = backup_database(conn, tmp_path / "bk", clock, "x")
    monkeypatch.setattr(backup_module, "integrity_ok", lambda _c: False)
    with pytest.raises(BackupError, match="corrompue"):
        inspect_backup(saved)


def test_restauration_avec_sauvegarde_de_securite(
    tmp_path: Path, clock: FixedClock, make_db: MakeDb
) -> None:
    db_path = tmp_path / "db.sqlite"
    conn = make_db(db_path, clock, "original")
    saved = backup_database(conn, tmp_path / "bk", clock, "avant")
    conn.execute("UPDATE setting SET value_json = '\"modifie\"' WHERE key = 'k'")
    conn.close()
    clock.advance(1)
    safety = restore_database(saved, db_path, tmp_path / "bk", clock, latest_version=LATEST)
    assert setting(db_path) == '"original"'
    assert safety is not None and setting(safety) == '"modifie"'


def test_restauration_refuse_une_version_future(
    tmp_path: Path, clock: FixedClock, make_db: MakeDb
) -> None:
    conn = make_db(tmp_path / "db.sqlite", clock, "v")
    saved = backup_database(conn, tmp_path / "bk", clock, "x")
    with pytest.raises(BackupError, match="plus récente"):
        restore_database(saved, tmp_path / "db.sqlite", tmp_path / "bk", clock, latest_version=0)
    assert setting(tmp_path / "db.sqlite") == '"v"'


def test_restauration_refuse_le_meme_fichier(
    tmp_path: Path, clock: FixedClock, make_db: MakeDb
) -> None:
    db_path = tmp_path / "db.sqlite"
    make_db(db_path, clock, "v").close()
    with pytest.raises(BackupError, match="même fichier"):
        restore_database(db_path, db_path, tmp_path / "bk", clock, latest_version=LATEST)


def test_restauration_sans_base_existante(
    tmp_path: Path, clock: FixedClock, make_db: MakeDb
) -> None:
    conn = make_db(tmp_path / "src.sqlite", clock, "v")
    saved = backup_database(conn, tmp_path / "bk", clock, "x")
    target = tmp_path / "nouvelle.sqlite"
    assert restore_database(saved, target, tmp_path / "bk", clock, latest_version=LATEST) is None
    assert setting(target) == '"v"'
