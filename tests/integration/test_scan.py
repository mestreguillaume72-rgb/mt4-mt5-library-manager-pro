"""F1 / Phase 2 — sources, inventaire incrémental, annulation, pause, reprise."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.context import AppContext, open_app
from mtlm.app.inventory import FileFilter, InventoryService
from mtlm.app.jobs import JobStore
from mtlm.app.scan import ScanError, ScanService, ScanSummary
from mtlm.app.sources import SourceError, SourceService
from mtlm.core.clock import FixedClock
from mtlm.core.control import TaskControl
from mtlm.core.paths import AppPaths
from mtlm.store.database import connect
from tests.support.fs_snapshot import diff_snapshots, take_snapshot
from tests.synthetic.generate import generate_corpus


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def services(ctx: AppContext) -> tuple[SourceService, ScanService, InventoryService]:
    return (
        SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths),
        ScanService(ctx.conn, ctx.clock, ctx.journal),
        InventoryService(ctx.conn),
    )


def audit(ctx: AppContext) -> list[tuple[str, str]]:
    return [(r.action, r.result) for r in ctx.journal]


# --- sources ------------------------------------------------------------------------------


def test_ajout_de_source_n_ecrit_rien(tmp_path: Path, ctx: AppContext) -> None:
    src = tmp_path / "lib"
    generate_corpus(src, seed=1, n_files=50)
    before = take_snapshot(src)
    sources, _, _ = services(ctx)
    added = sources.add(src, "Ma bibliothèque")
    assert added.display_name == "Ma bibliothèque" and added.status == "ok"
    assert diff_snapshots(before, take_snapshot(src)) == []
    assert ("source.add", "ok") in audit(ctx)


@pytest.mark.parametrize("case", ["absent", "fichier", "imbrique", "parent", "app"])
def test_sources_refusees(tmp_path: Path, ctx: AppContext, case: str) -> None:
    sources, _, _ = services(ctx)
    lib = tmp_path / "lib"
    (lib / "sous").mkdir(parents=True)
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    sources.add(lib)
    target = {
        "absent": tmp_path / "nulle-part",
        "fichier": tmp_path / "f.txt",
        "imbrique": lib / "sous",
        "parent": tmp_path,
        "app": ctx.paths.data_dir.parent,
    }[case]
    with pytest.raises(SourceError, match="Source refusée"):
        sources.add(target)
    assert ("source.add", "refused") in audit(ctx)


def test_retrait_puis_rajout(tmp_path: Path, ctx: AppContext) -> None:
    sources, _, _ = services(ctx)
    (tmp_path / "lib").mkdir()
    first = sources.add(tmp_path / "lib")
    sources.remove(first.id)
    assert sources.list() == []
    with pytest.raises(SourceError, match="déjà retirée"):
        sources.remove(first.id)
    again = sources.add(tmp_path / "lib")
    assert again.id == first.id and again.status == "ok"
    assert (tmp_path / "lib").exists()


def test_source_inconnue(ctx: AppContext) -> None:
    sources, scanner, _ = services(ctx)
    with pytest.raises(SourceError):
        sources.get(42)
    with pytest.raises(ScanError, match="inconnue"):
        scanner.scan(42)


# --- inventaire ---------------------------------------------------------------------------


def test_inventaire_complet_et_incremental(tmp_path: Path, ctx: AppContext) -> None:
    src = tmp_path / "lib"
    manifest = generate_corpus(src, seed=5, n_files=1500)
    sources, scanner, inventory = services(ctx)
    source = sources.add(src)
    before = take_snapshot(src)

    first = scanner.scan(source.id, batch_size=100)
    assert first.state == "completed"
    assert (first.seen, first.new, first.changed, first.missing, first.errors) == (
        1500,
        1500,
        0,
        0,
        0,
    )
    assert diff_snapshots(before, take_snapshot(src)) == []  # lecture seule prouvée
    stats = inventory.stats(source.id)
    assert stats.files == 1500
    assert stats.total_bytes == sum(e.size for e in manifest.entries)
    assert stats.by_hash_state == {"not_computed": 1500}

    second = scanner.scan(source.id)
    assert (second.new, second.changed, second.unchanged, second.missing) == (0, 0, 1500, 0)

    entries = sorted(manifest.entries, key=lambda e: e.rel_path)
    modified, deleted = src / entries[0].rel_path, src / entries[1].rel_path
    modified.write_bytes(modified.read_bytes() + b"modification")
    deleted.unlink()
    (src / "nouveau.mq4").write_bytes(b"// nouveau")
    # Une empreinte validée doit devenir « stale » si le fichier change.
    fid = ctx.conn.execute(
        "SELECT id FROM file_record WHERE rel_path = ?", (entries[0].rel_path,)
    ).fetchone()
    if fid is None:  # nom en NFD sur disque : rel_path est stocké en NFC
        import unicodedata

        fid = ctx.conn.execute(
            "SELECT id FROM file_record WHERE rel_path = ?",
            (unicodedata.normalize("NFC", entries[0].rel_path),),
        ).fetchone()
    ctx.conn.execute("INSERT INTO content(id, sha256, size) VALUES (1, zeroblob(32), 0)")
    ctx.conn.execute(
        "UPDATE file_record SET hash_state = 'validated', content_id = 1 WHERE id = ?", (fid[0],)
    )

    third = scanner.scan(source.id)
    assert (third.new, third.changed, third.missing) == (1, 1, 1)
    assert third.unchanged == 1498
    assert inventory.count(FileFilter(source_id=source.id, presence="missing")) == 1
    state = ctx.conn.execute(
        "SELECT hash_state FROM file_record WHERE id = ?", (fid[0],)
    ).fetchone()[0]
    assert state == "stale"
    assert inventory.stats(source.id).files == 1500

    deleted.write_bytes(b"revenu")
    fourth = scanner.scan(source.id)
    assert fourth.missing == 0
    assert inventory.count(FileFilter(source_id=source.id, presence="missing")) == 0


def test_annulation_ne_declare_aucun_manquant(tmp_path: Path, ctx: AppContext) -> None:
    src = tmp_path / "lib"
    generate_corpus(src, seed=6, n_files=600)
    sources, scanner, inventory = services(ctx)
    source = sources.add(src)
    scanner.scan(source.id)
    control = TaskControl()
    seen: list[int] = []

    def on_progress(summary: ScanSummary) -> None:
        seen.append(summary.seen)
        if summary.seen >= 100:
            control.cancel()

    result = scanner.scan(source.id, control=control, progress=on_progress, batch_size=50)
    assert result.state == "cancelled"
    assert 100 <= result.seen < 600
    assert inventory.count(FileFilter(source_id=source.id, presence="missing")) == 0
    assert JobStore(ctx.conn, ctx.clock).get(result.job_id).state == "cancelled"
    assert ("scan.end", "cancelled") in audit(ctx)
    final = scanner.scan(source.id)  # reprise : un nouvel inventaire complet est cohérent
    assert (final.state, final.unchanged, final.missing) == ("completed", 600, 0)


def test_pause_puis_reprise(tmp_path: Path, paths: AppPaths, clock: FixedClock) -> None:
    src = tmp_path / "lib"
    generate_corpus(src, seed=7, n_files=300)
    with open_app(paths, clock) as ctx:
        source_id = SourceService(ctx.conn, clock, ctx.journal, paths).add(src).id
    control = TaskControl()
    control.pause()
    result: list[ScanSummary] = []

    def worker() -> None:
        with open_app(paths, clock) as wctx:
            result.append(
                ScanService(wctx.conn, clock, wctx.journal).scan(
                    source_id, control=control, batch_size=10
                )
            )

    thread = threading.Thread(target=worker)
    thread.start()
    time.sleep(0.3)
    reader = connect(paths.database)
    try:
        progress = reader.execute("SELECT max(progress_done) FROM job").fetchone()[0]
        assert progress in (None, 0)  # en pause : rien n'a avancé
        assert thread.is_alive() and control.paused
        control.resume()
        thread.join(timeout=30)
    finally:
        reader.close()
    assert result and result[0].state == "completed" and result[0].seen == 300


def test_source_devenue_inaccessible(tmp_path: Path, ctx: AppContext) -> None:
    src = tmp_path / "lib"
    src.mkdir()
    sources, scanner, _ = services(ctx)
    source = sources.add(src)
    src.rename(tmp_path / "deplace")  # disque débranché ou dossier déplacé
    with pytest.raises(ScanError, match="inaccessible"):
        scanner.scan(source.id)
    assert sources.get(source.id).status == "unreachable"
    assert ("scan.end", "failed") in audit(ctx)


def test_source_retiree_non_inventoriable(tmp_path: Path, ctx: AppContext) -> None:
    (tmp_path / "lib").mkdir()
    sources, scanner, _ = services(ctx)
    source = sources.add(tmp_path / "lib")
    sources.remove(source.id)
    with pytest.raises(ScanError, match="retirée"):
        scanner.scan(source.id)


def test_tache_interrompue_detectee_au_demarrage(paths: AppPaths, clock: FixedClock) -> None:
    with open_app(paths, clock) as ctx:
        job = JobStore(ctx.conn, clock).create("scan", {"source_id": 1})
    with open_app(paths, clock) as ctx:
        assert JobStore(ctx.conn, clock).get(job).state == "interrupted"
        assert ("job.interrupted", "ok") in audit(ctx)


# --- consultation -------------------------------------------------------------------------


def test_pagination_filtres_et_recherche(tmp_path: Path, ctx: AppContext) -> None:
    src = tmp_path / "lib"
    manifest = generate_corpus(src, seed=8, n_files=900)
    (src / "Élan Spécial.mq4").write_bytes(b"x")
    sources, scanner, inventory = services(ctx)
    source = sources.add(src)
    scanner.scan(source.id)
    collected: list[int] = []
    after = 0
    while page := inventory.page(FileFilter(), after_id=after, limit=97):
        collected += [r.id for r in page]
        after = page[-1].id
    assert len(collected) == len(set(collected)) == 901
    expected_mq4 = sum(1 for e in manifest.entries if e.rel_path.endswith(".mq4")) + 1
    assert inventory.count(FileFilter(extensions=("MQ4",))) == expected_mq4
    found = inventory.page(FileFilter(text="elan special"))
    assert [r.name for r in found] == ["Élan Spécial.mq4"]
    assert inventory.page(FileFilter(text='"; DROP TABLE file_record; --')) == []


def test_erreurs_consignees(
    tmp_path: Path, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno
    import os

    src = tmp_path / "lib"
    (src / "ferme").mkdir(parents=True)
    (src / "ok.set").write_bytes(b"a=1")
    real = os.scandir

    def fake(path: object) -> object:
        if os.fsencode(path).endswith(b"ferme"):  # type: ignore[arg-type]
            raise PermissionError(errno.EACCES, "Permission denied")
        return real(path)  # type: ignore[call-overload]

    monkeypatch.setattr(os, "scandir", fake)
    sources, scanner, inventory = services(ctx)
    source = sources.add(src)
    summary = scanner.scan(source.id)
    assert summary.errors == 1 and summary.seen == 1
    (error,) = inventory.errors(summary.job_id)
    assert error.rel_path == "ferme" and "EACCES" in error.message
    assert JobStore(ctx.conn, ctx.clock).get(summary.job_id).errors_count == 1


def test_base_coherente_apres_inventaire(tmp_path: Path, ctx: AppContext) -> None:
    src = tmp_path / "lib"
    generate_corpus(src, seed=9, n_files=200)
    sources, scanner, _ = services(ctx)
    scanner.scan(sources.add(src).id)
    assert ctx.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    fts = ctx.conn.execute("SELECT count(*) FROM search_fts").fetchone()[0]
    assert fts == 200
    assert isinstance(ctx.conn, sqlite3.Connection)
