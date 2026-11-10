from __future__ import annotations

import itertools
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mtlm.audit.journal import GENESIS_HASH, AuditJournal
from mtlm.core.clock import FixedClock
from mtlm.core.errors import AuditError, ExportError
from mtlm.store.database import connect
from mtlm.store.migrations_engine import Migrator


def new_journal(path: Path, clock: FixedClock) -> tuple[sqlite3.Connection, AuditJournal]:
    conn = connect(path)
    Migrator(conn, clock=clock, app_version="test").migrate()
    return conn, AuditJournal(conn, clock)


@pytest.fixture
def journal(tmp_path: Path, clock: FixedClock) -> Iterator[tuple[sqlite3.Connection, AuditJournal]]:
    conn, j = new_journal(tmp_path / "a.sqlite", clock)
    yield conn, j
    conn.close()


def fill(journal: AuditJournal, clock: FixedClock, n: int) -> None:
    for i in range(n):
        journal.append("utilisateur", "test.action", f"objet-{i}", details={"i": i, "é": "ü"})
        clock.advance(1)


def test_chainage(journal: tuple[sqlite3.Connection, AuditJournal], clock: FixedClock) -> None:
    _, j = journal
    fill(j, clock, 5)
    records = list(j)
    assert records[0].prev_hash == GENESIS_HASH
    for previous, current in itertools.pairwise(records):
        assert current.prev_hash == previous.hash
    assert j.verify().ok and j.verify().checked == 5


def test_modification_et_suppression_refusees_par_la_base(
    journal: tuple[sqlite3.Connection, AuditJournal], clock: FixedClock
) -> None:
    conn, j = journal
    fill(j, clock, 2)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_event SET object = 'x' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_event WHERE id = 1")


def test_alteration_detectee_meme_triggers_retires(
    journal: tuple[sqlite3.Connection, AuditJournal], clock: FixedClock
) -> None:
    conn, j = journal
    fill(j, clock, 4)
    conn.execute("DROP TRIGGER audit_event_no_update")  # simulation d'un accès direct malveillant
    conn.execute("UPDATE audit_event SET object = 'falsifié' WHERE id = 3")
    result = j.verify()
    assert not result.ok and result.first_invalid_id == 3 and result.checked == 2


def test_suppression_intermediaire_detectee(
    journal: tuple[sqlite3.Connection, AuditJournal], clock: FixedClock
) -> None:
    conn, j = journal
    fill(j, clock, 4)
    conn.execute("DROP TRIGGER audit_event_no_delete")
    conn.execute("DELETE FROM audit_event WHERE id = 2")
    result = j.verify()
    assert not result.ok and result.first_invalid_id == 3


def test_acteur_obligatoire(journal: tuple[sqlite3.Connection, AuditJournal]) -> None:
    with pytest.raises(AuditError):
        journal[1].append("", "x", "y")


def test_resultat_hors_liste_refuse(journal: tuple[sqlite3.Connection, AuditJournal]) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        journal[1].append("utilisateur", "x", "y", result="peut-être")  # type: ignore[arg-type]


def test_export_jsonl(
    tmp_path: Path, journal: tuple[sqlite3.Connection, AuditJournal], clock: FixedClock
) -> None:
    _, j = journal
    fill(j, clock, 3)
    dest = tmp_path / "audit.jsonl"
    assert j.export_jsonl(dest) == 3
    lines = dest.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["object"] for line in lines] == ["objet-0", "objet-1", "objet-2"]
    assert json.loads(lines[0])["details"] == {"i": 0, "é": "ü"}


def test_export_n_ecrase_jamais(
    tmp_path: Path, journal: tuple[sqlite3.Connection, AuditJournal]
) -> None:
    dest = tmp_path / "existant.jsonl"
    dest.write_text("précieux", encoding="utf-8")
    with pytest.raises(ExportError, match="ne sera pas écrasé"):
        journal[1].export_jsonl(dest)
    assert dest.read_text(encoding="utf-8") == "précieux"


def test_export_dossier_inexistant(
    tmp_path: Path, journal: tuple[sqlite3.Connection, AuditJournal]
) -> None:
    with pytest.raises(ExportError, match="impossible"):
        journal[1].export_jsonl(tmp_path / "absent" / "a.jsonl")


@settings(max_examples=40, deadline=None)
@given(
    events=st.lists(
        st.tuples(
            st.text(min_size=1, max_size=20),
            st.text(max_size=40),
            st.dictionaries(st.text(max_size=10), st.integers() | st.text(max_size=10), max_size=4),
        ),
        min_size=1,
        max_size=15,
    )
)
def test_propriete_chaine_toujours_valide(
    tmp_path_factory: pytest.TempPathFactory, events: list[tuple[str, str, dict[str, object]]]
) -> None:
    from datetime import UTC, datetime

    clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    conn, j = new_journal(tmp_path_factory.mktemp("h") / "a.sqlite", clock)
    try:
        for action, obj, details in events:
            j.append("utilisateur", action, obj, details=details)
        assert j.verify().ok and j.count() == len(events)
    finally:
        conn.close()
