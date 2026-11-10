"""Phase 5 — service de reconnaissance sur un corpus fictif complet."""

from __future__ import annotations

import io
import unicodedata
from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.context import AppContext, open_app
from mtlm.app.formats import FormatService
from mtlm.app.hashing import HashService
from mtlm.app.inventory import FileFilter, InventoryService, analysis_of
from mtlm.app.recognize import RecognitionService
from mtlm.app.scan import ScanService
from mtlm.app.sources import SourceService
from mtlm.cli.main import EXIT_OK, main
from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths
from tests.support.fs_snapshot import diff_snapshots, take_snapshot
from tests.synthetic.generate import generate_corpus

FOLDER_TO_TYPE = {"Experts": "ea", "Indicators": "indicator", "Scripts": "script"}


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def pipeline(ctx: AppContext, root: Path) -> int:
    source = SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).add(root)
    ScanService(ctx.conn, ctx.clock, ctx.journal).scan(source.id)
    HashService(ctx.conn, ctx.clock, ctx.journal).run(source.id)
    FormatService(ctx.conn, ctx.clock, ctx.journal).run(source.id)
    return source.id


def test_corpus_classe_selon_la_verite_terrain(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    manifest = generate_corpus(root, seed=12, n_files=1500)
    source_id = pipeline(ctx, root)
    before = take_snapshot(root)
    summary = RecognitionService(ctx.conn, ctx.clock, ctx.journal).run(source_id)
    assert diff_snapshots(before, take_snapshot(root)) == []
    assert summary.classified == 1500 and summary.waiting_for_hash == 0
    rows = ctx.conn.execute(
        "SELECT f.rel_path, a.detected_type, a.platform, a.certainty FROM file_record f"
        " JOIN file_analysis a ON a.file_id = f.id"
    ).fetchall()
    found = {r[0]: (r[1], r[2], r[3]) for r in rows}
    checked = 0
    for entry in manifest.entries:
        path = unicodedata.normalize("NFC", entry.rel_path)
        detected, platform, certainty = found[path]
        folder = next((p for p in entry.rel_path.split("/") if p in FOLDER_TO_TYPE), None)
        if entry.kind in ("mq4", "mq5") and folder and not entry.rel_path.startswith("Copies/"):
            assert (detected, certainty) == (FOLDER_TO_TYPE[folder], "certain"), path
            assert platform == ("mt4" if entry.kind == "mq4" else "mt5")
            checked += 1
        elif entry.kind in ("ex4", "ex5"):
            assert certainty in ("probable", "unknown")
        elif entry.kind == "set":
            assert detected == "set"
        elif entry.kind == "mqh":
            assert detected == "include"
        elif entry.kind == "dll":
            assert detected in ("dll", "unknown")
    assert checked > 100
    # Les copies exactes ne sont analysées qu'une fois (métadonnées par contenu).
    sources = sum(1 for e in manifest.entries if e.kind in ("mq4", "mq5", "mqh"))
    distinct = len({e.sha256 for e in manifest.entries if e.kind in ("mq4", "mq5", "mqh")})
    assert ctx.conn.execute("SELECT count(*) FROM mql_source_meta").fetchone()[0] == distinct
    assert distinct <= sources
    # Idempotence.
    again = RecognitionService(ctx.conn, ctx.clock, ctx.journal).run(source_id)
    assert again.classified == 0


def test_appariement_compile_et_limites(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    (root / "Vrac").mkdir(parents=True)
    (root / "Vrac" / "Tendance.mq5").write_text(
        "#property indicator_separate_window\nint OnCalculate(){return 0;}\n", encoding="utf-8"
    )
    (root / "Vrac" / "Tendance.ex5").write_bytes(bytes(range(256)))
    (root / "Vrac" / "Seul.ex4").write_bytes(bytes(range(200)))
    (root / "Vrac" / "Faux.ex4").write_text("#property strict\n", encoding="utf-8")
    (root / "Vrac" / "inconnu.bin").write_bytes(bytes(range(255, 0, -1)))
    source_id = pipeline(ctx, root)
    RecognitionService(ctx.conn, ctx.clock, ctx.journal).run(source_id)
    ids = dict(ctx.conn.execute("SELECT name, id FROM file_record").fetchall())
    paired = analysis_of(ctx.conn, ids["Tendance.ex5"])
    assert paired is not None and (paired.detected_type, paired.certainty) == (
        "indicator",
        "probable",
    )
    assert paired.limits and "opaque" in paired.limits
    alone = analysis_of(ctx.conn, ids["Seul.ex4"])
    assert alone is not None and alone.detected_type == "unknown"
    fake = analysis_of(ctx.conn, ids["Faux.ex4"])
    assert fake is not None and any("TROMPEUSE" in b for b in fake.basis)
    unknown = analysis_of(ctx.conn, ids["inconnu.bin"])
    assert unknown is not None and unknown.detected_type == "unknown" and unknown.limits
    flt = InventoryService(ctx.conn).count(FileFilter(detected_type="indicator"))
    assert flt == 2


def test_source_modifiee_apres_empreinte_non_analysee(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    (root / "MQL5" / "Experts").mkdir(parents=True)
    target = root / "MQL5" / "Experts" / "R.mq5"
    target.write_text("void OnTick(){}\n", encoding="utf-8")
    source_id = pipeline(ctx, root)
    target.write_text("void OnStart(){} // modifié\n", encoding="utf-8")
    summary = RecognitionService(ctx.conn, ctx.clock, ctx.journal).run(source_id)
    info = analysis_of(ctx.conn, 1)
    assert summary.warnings == 1 and info is not None
    assert any("empreinte" in w for w in info.warnings)


def test_cli_reconnaitre_et_detail(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock
) -> None:
    root = tmp_path / "lib"
    (root / "MQL4" / "Experts").mkdir(parents=True)
    (root / "MQL4" / "Experts" / "Robot.mq4").write_text(
        '#property version "1.2"\n#import "kernel32.dll"\n#import\n'
        "extern double Lots = 0.1;\nint start(){return 0;}\n",
        encoding="utf-8",
    )

    def run(args: list[str]) -> str:
        out = io.StringIO()
        assert main(args, environ=environ, clock=clock, out=out, err=io.StringIO()) == EXIT_OK
        return out.getvalue()

    for args in (["source", "ajouter", str(root)], ["scanner"], ["empreintes"], ["formats"]):
        run(args)
    out = run(["reconnaitre"])
    assert "1 fichier(s) classé(s), 1 source(s) MQL analysée(s)" in out
    detail = run(["fichier", "1"])
    assert "Type reconnu : robot (EA) — plateforme mt4 — certitude certain" in detail
    assert "extern double Lots = 0.1" in detail
    assert "Imports (jamais chargés) : kernel32.dll" in detail
    assert "Version déclarée : 1.2" in detail
    assert "1 affiché(s)" in run(["fichiers", "--type", "ea", "--plateforme", "mt4"])
