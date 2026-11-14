"""Phase 4 — service formats : signatures persistées, archives inspectées, idempotence."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.context import AppContext, open_app
from mtlm.app.formats import FormatService
from mtlm.app.hashing import HashService
from mtlm.app.inventory import InventoryService
from mtlm.app.scan import ScanService
from mtlm.app.sources import SourceService
from mtlm.cli.main import EXIT_ERROR, EXIT_OK, main
from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths
from mtlm.formats import libarchive
from tests.support.archives import make_bomb, make_encrypted, make_zip
from tests.support.fs_snapshot import diff_snapshots, take_snapshot


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def build_library(root: Path) -> None:
    (root / "MQL4" / "Experts").mkdir(parents=True)
    (root / "MQL4" / "Experts" / "Robot.mq4").write_bytes(b"#property strict\n")
    (root / "MQL4" / "Experts" / "Faux.mq4").write_bytes(b"MZ\x90\x00binaire")  # trompeuse
    (root / "MQL4" / "Experts" / "Robot.ex4").write_bytes(bytes(range(256)))
    make_zip(
        root / "pack.zip", {"MQL4/Experts/Robot.mq4": b"#property strict\n", "../evil.mq4": b"x"}
    )
    make_bomb(root / "bombe.zip", size=8 * 1024 * 1024)
    make_encrypted(root / "secret.zip")
    (root / "pas_un_zip.zip").write_bytes(b"texte")
    (root / "archive.rar").write_bytes(b"Rar!\x1a\x07\x00reste")


def run_pipeline(ctx: AppContext, root: Path) -> int:
    source = SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).add(root)
    ScanService(ctx.conn, ctx.clock, ctx.journal).scan(source.id)
    HashService(ctx.conn, ctx.clock, ctx.journal).run(source.id)
    return source.id


def test_signatures_et_archives(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    build_library(root)
    source_id = run_pipeline(ctx, root)
    before = take_snapshot(root)
    summary = FormatService(ctx.conn, ctx.clock, ctx.journal).run(source_id)
    assert diff_snapshots(before, take_snapshot(root)) == []
    assert summary.signatures == 8 and summary.misleading == 2  # Faux.mq4 + pas_un_zip.zip
    assert summary.archives == 5
    statuses = dict(
        ctx.conn.execute(
            "SELECT f.name, a.status FROM archive_scan a JOIN file_record f ON f.id = a.file_id"
        ).fetchall()
    )
    assert statuses == {
        "pack.zip": "partial",
        "bombe.zip": "partial",
        "secret.zip": "encrypted",
        "pas_un_zip.zip": "rejected",
        # 1.5.0 : les RAR sont ouverts (libarchive) ; celui-ci est un faux, donc illisible.
        "archive.rar": "corrupt" if libarchive.available() else "not_supported",
    }
    # Le fichier contenu dans pack.zip est un doublon exact de Robot.mq4 : même contenu.
    same = ctx.conn.execute(
        "SELECT count(*) FROM archive_entry e JOIN file_record f ON f.content_id = e.content_id"
        " WHERE f.name = 'Robot.mq4'"
    ).fetchone()[0]
    assert same == 1
    faux = ctx.conn.execute("SELECT id FROM file_record WHERE name = 'Faux.mq4'").fetchone()[0]
    detail = InventoryService(ctx.conn).detail(faux)
    assert detail is not None and detail.misleading_extension and detail.magic == "pe"
    # Idempotence : rien n'est ré-inspecté au deuxième passage.
    again = FormatService(ctx.conn, ctx.clock, ctx.journal).run(source_id)
    assert again.signatures == 0 and again.archive_entries == 0


def test_cli_formats_et_archive(tmp_path: Path, environ: dict[str, str], clock: FixedClock) -> None:
    root = tmp_path / "lib"
    build_library(root)

    def run(args: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = main(args, environ=environ, clock=clock, out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    for args in (["source", "ajouter", str(root)], ["scanner"], ["empreintes"]):
        assert run(args)[0] == EXIT_OK
    code, out, _ = run(["formats"])
    assert code == EXIT_OK and "2 extension(s) trompeuse(s)" in out
    pack = next(i for i in range(1, 9) if "pack.zip" in run(["fichier", str(i)])[1])
    code, out, _ = run(["archive", str(pack)])
    assert code == EXIT_OK and "rejected_traversal" in out and "traversée" in out
    faux = next(i for i in range(1, 9) if "Faux.mq4" in run(["fichier", str(i)])[1])
    assert "EXTENSION TROMPEUSE" in run(["fichier", str(faux)])[1]
    robot = next(i for i in range(1, 9) if "Experts/Robot.mq4" in run(["fichier", str(i)])[1])
    code, _, err = run(["archive", str(robot)])  # pas une archive
    assert code == EXIT_ERROR and "pas été inspecté" in err
