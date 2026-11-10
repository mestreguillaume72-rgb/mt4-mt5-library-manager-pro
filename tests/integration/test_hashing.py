"""Phase 3 — service d'empreintes : états, reprise, annulation, cohérence."""

from __future__ import annotations

import hashlib
import io
import os
import unicodedata
from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.context import AppContext, open_app
from mtlm.app.hashing import HashService, HashSummary
from mtlm.app.inventory import FileFilter, InventoryService
from mtlm.app.jobs import JobStore
from mtlm.app.scan import ScanService
from mtlm.app.sources import SourceService
from mtlm.cli.main import EXIT_ERROR, EXIT_OK, EXIT_USAGE, main
from mtlm.core.clock import FixedClock
from mtlm.core.control import TaskControl
from mtlm.core.paths import AppPaths
from tests.support.fs_snapshot import diff_snapshots, take_snapshot
from tests.synthetic.generate import Manifest, generate_corpus


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def prepare(ctx: AppContext, root: Path, n: int, seed: int = 1) -> tuple[int, Manifest]:
    manifest = generate_corpus(root, seed=seed, n_files=n)
    source = SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).add(root)
    ScanService(ctx.conn, ctx.clock, ctx.journal).scan(source.id)
    return source.id, manifest


def stored_hashes(ctx: AppContext) -> dict[str, str]:
    rows = ctx.conn.execute(
        "SELECT f.rel_path, c.sha256 FROM file_record f JOIN content c ON c.id = f.content_id"
    )
    return {r[0]: bytes(r[1]).hex() for r in rows}


def test_empreintes_conformes_et_sources_intactes(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    source_id, manifest = prepare(ctx, root, 800)
    before = take_snapshot(root)
    summary = HashService(ctx.conn, ctx.clock, ctx.journal).run(source_id, workers=3, batch_size=64)
    assert (summary.state, summary.hashed, summary.errors) == ("completed", 800, 0)
    assert summary.bytes_read == sum(e.size for e in manifest.entries)
    expected = {unicodedata.normalize("NFC", e.rel_path): e.sha256 for e in manifest.entries}
    assert stored_hashes(ctx) == expected
    assert diff_snapshots(before, take_snapshot(root)) == []
    stats = InventoryService(ctx.conn).stats(source_id)
    assert stats.by_hash_state == {"validated": 800}
    # Les doublons exacts du corpus partagent la même ligne de contenu.
    distinct = len({e.sha256 for e in manifest.entries})
    assert ctx.conn.execute("SELECT count(*) FROM content").fetchone()[0] == distinct


def test_deuxieme_passage_ne_recalcule_rien(tmp_path: Path, ctx: AppContext) -> None:
    source_id, _ = prepare(ctx, tmp_path / "lib", 100)
    service = HashService(ctx.conn, ctx.clock, ctx.journal)
    service.run(source_id)
    again = service.run(source_id)
    assert (again.candidates, again.hashed) == (0, 0)


def test_fichier_modifie_recalcule(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    source_id, manifest = prepare(ctx, root, 50)
    service = HashService(ctx.conn, ctx.clock, ctx.journal)
    service.run(source_id)
    target = root / manifest.entries[0].rel_path
    target.write_bytes(b"nouveau contenu")
    # Sans nouvel inventaire, rien n'est recalculé ; après inventaire, l'empreinte est « stale ».
    ScanService(ctx.conn, ctx.clock, ctx.journal).scan(source_id)
    rerun = service.run(source_id)
    assert (rerun.candidates, rerun.hashed) == (1, 1)
    detail = InventoryService(ctx.conn).page(FileFilter(text=None), limit=1000)
    assert all(r.hash_state == "validated" for r in detail)
    assert hashlib.sha256(b"nouveau contenu").hexdigest() in stored_hashes(ctx).values()


def test_fichier_modifie_apres_inventaire_en_erreur(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    source_id, manifest = prepare(ctx, root, 20)
    victim = root / manifest.entries[3].rel_path
    victim.write_bytes(victim.read_bytes() + b"++")  # changé entre inventaire et empreinte
    summary = HashService(ctx.conn, ctx.clock, ctx.journal).run(source_id)
    assert (summary.hashed, summary.errors) == (19, 1)
    row = ctx.conn.execute(
        "SELECT hash_state, hash_error, content_id FROM file_record WHERE hash_state = 'error'"
    ).fetchone()
    assert row[0] == "error" and "inventaire" in row[1] and row[2] is None
    # Après un nouvel inventaire, l'erreur se résout.
    ScanService(ctx.conn, ctx.clock, ctx.journal).scan(source_id)
    fixed = HashService(ctx.conn, ctx.clock, ctx.journal).run(source_id, retry_errors=True)
    assert (fixed.hashed, fixed.errors) == (1, 0)


def test_annulation_aucune_empreinte_partielle(tmp_path: Path, ctx: AppContext) -> None:
    source_id, _ = prepare(ctx, tmp_path / "lib", 400)
    control = TaskControl()

    def cancel_after_first(summary: HashSummary) -> None:
        control.cancel()

    summary = HashService(ctx.conn, ctx.clock, ctx.journal).run(
        source_id, control=control, progress=cancel_after_first, batch_size=50
    )
    assert summary.state == "cancelled" and summary.hashed == 50
    states = dict(
        ctx.conn.execute(
            "SELECT hash_state, count(*) FROM file_record GROUP BY hash_state"
        ).fetchall()
    )
    assert states == {"validated": 50, "not_computed": 350}
    assert JobStore(ctx.conn, ctx.clock).get(summary.job_id).state == "cancelled"


def test_reprise_apres_fermeture_brutale(
    tmp_path: Path, paths: AppPaths, clock: FixedClock
) -> None:
    with open_app(paths, clock) as ctx:
        source_id, _ = prepare(ctx, tmp_path / "lib", 60)
        # Simulation d'un arrêt brutal au milieu d'un lot : 30 fichiers restés « in_progress ».
        ctx.conn.execute(
            "UPDATE file_record SET hash_state = 'in_progress' WHERE id IN"
            " (SELECT id FROM file_record ORDER BY id LIMIT 30)"
        )
    with open_app(paths, clock) as ctx:
        summary = HashService(ctx.conn, ctx.clock, ctx.journal).run(source_id)
        assert (summary.hashed, summary.errors) == (60, 0)
        assert InventoryService(ctx.conn).stats().by_hash_state == {"validated": 60}


def test_fichiers_non_lus(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    (root / "ok.mq4").write_bytes(b"x")
    os.mkfifo(root / "tube")
    (root / "lien").symlink_to(root / "ok.mq4")
    (root / "icloud.ex4").write_bytes(b"y")
    source = SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).add(root)
    ScanService(ctx.conn, ctx.clock, ctx.journal).scan(source.id)
    ctx.conn.execute("UPDATE file_record SET is_dataless = 1 WHERE name = 'icloud.ex4'")
    summary = HashService(ctx.conn, ctx.clock, ctx.journal).run(source.id)
    assert (summary.candidates, summary.hashed) == (1, 1)
    states = dict(ctx.conn.execute("SELECT name, hash_state FROM file_record").fetchall())
    assert states == {
        "ok.mq4": "validated",
        "tube": "not_computed",
        "lien": "not_computed",
        "icloud.ex4": "not_computed",
    }


def test_fichier_supprime_entre_inventaire_et_empreinte(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    source_id, manifest = prepare(ctx, root, 10)
    (root / manifest.entries[0].rel_path).unlink()
    summary = HashService(ctx.conn, ctx.clock, ctx.journal).run(source_id)
    assert (summary.hashed, summary.errors) == (9, 1)
    error = ctx.conn.execute(
        "SELECT hash_error FROM file_record WHERE hash_state = 'error'"
    ).fetchone()[0]
    assert error.startswith("lecture impossible")


def test_cli_empreintes_et_detail(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock
) -> None:
    root = tmp_path / "lib"
    generate_corpus(root, seed=4, n_files=40)

    def run(args: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        return (
            main(args, environ=environ, clock=clock, out=out, err=err),
            out.getvalue(),
            err.getvalue(),
        )

    run(["source", "ajouter", str(root)])
    run(["scanner"])
    code, out, _ = run(["empreintes", "--travailleurs", "2"])
    assert code == EXIT_OK and "40 calculée(s), 0 erreur(s) sur 40" in out
    code, out, _ = run(["fichier", "1"])
    assert code == EXIT_OK and "État de l'empreinte : validated" in out
    assert "SHA-256 : " in out and "non calculée" not in out
    code, _, err = run(["fichier", "999"])
    assert code == EXIT_ERROR and "inconnu" in err
    code, _, _ = run(["empreintes", "--travailleurs", "0"])
    assert code == EXIT_USAGE
