"""Phase 7 — service familles sur corpus fictif + CLI."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.context import AppContext, open_app
from mtlm.app.families import FamilyService
from mtlm.app.formats import FormatService
from mtlm.app.hashing import HashService
from mtlm.app.recognize import RecognitionService
from mtlm.app.scan import ScanService
from mtlm.app.sets import AssociationService, SetService
from mtlm.app.sources import SourceService
from mtlm.cli.main import EXIT_OK, main
from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths
from tests.synthetic.generate import generate_corpus


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def analyse(ctx: AppContext, root: Path) -> None:
    source = SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).add(root)
    for run in (
        ScanService(ctx.conn, ctx.clock, ctx.journal).scan,
        HashService(ctx.conn, ctx.clock, ctx.journal).run,
        FormatService(ctx.conn, ctx.clock, ctx.journal).run,
        RecognitionService(ctx.conn, ctx.clock, ctx.journal).run,
        SetService(ctx.conn, ctx.clock, ctx.journal).parse_all,
    ):
        run(source.id)
    AssociationService(ctx.conn, ctx.clock, ctx.journal).compute()


def test_familles_sur_corpus(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    manifest = generate_corpus(root, seed=41, n_files=1500)
    analyse(ctx, root)
    summary = FamilyService(ctx.conn, ctx.clock, ctx.journal).rebuild()
    assert summary.families > 0 and summary.with_sets > 0
    # Dans chaque groupe de N sources identiques : une référence et N-1 copies.
    import unicodedata
    from collections import defaultdict

    relations = dict(
        ctx.conn.execute(
            "SELECT f.rel_path, fm.relation FROM family_member fm JOIN file_record f"
            " ON f.id = fm.file_id"
        ).fetchall()
    )
    groups: dict[str, list[str]] = defaultdict(list)
    for e in manifest.entries:
        if e.kind in ("mq4", "mq5"):
            groups[e.sha256].append(unicodedata.normalize("NFC", e.rel_path))
    duplicated = [g for g in groups.values() if len(g) > 1]
    assert duplicated
    for group in duplicated:
        kinds = [relations[p] for p in group]
        assert sum(k in ("exact_copy", "renamed_copy") for k in kinds) == len(group) - 1
    # Recalcul identique (familles dérivées, déterministes).
    again = FamilyService(ctx.conn, ctx.clock, ctx.journal).rebuild()
    assert (again.families, again.members) == (summary.families, summary.members)


def test_cli_familles(tmp_path: Path, environ: dict[str, str], clock: FixedClock) -> None:
    root = tmp_path / "lib"
    (root / "MQL4" / "Experts").mkdir(parents=True)
    (root / "MQL4" / "Presets").mkdir(parents=True)
    src = '#property version "{v}"\nextern double Lots = 0.1;\nint start(){{return 0;}}\n'
    (root / "MQL4" / "Experts" / "Scalper.mq4").write_text(src.format(v="1.0"), encoding="utf-8")
    (root / "MQL4" / "Experts" / "Scalper_v2.mq4").write_text(src.format(v="2.0"), encoding="utf-8")
    (root / "MQL4" / "Experts" / "Scalper.ex4").write_bytes(bytes(range(256)))
    (root / "MQL4" / "Presets" / "Scalper_EURUSD.set").write_text("Lots=0.2\n", encoding="utf-8")

    def run(args: list[str]) -> str:
        out = io.StringIO()
        assert main(args, environ=environ, clock=clock, out=out, err=io.StringIO()) == EXIT_OK
        return out.getvalue()

    for args in (
        ["source", "ajouter", str(root)],
        ["scanner"],
        ["empreintes"],
        ["formats"],
        ["reconnaitre"],
        ["sets"],
        ["associer"],
    ):
        run(args)
    out = run(["regrouper"])
    assert "1 famille(s), 4 membre(s)" in out
    assert "Scalper\tmt4\t4 membre(s)" in run(["familles"])
    detail = run(["famille", "1"])
    assert "version 2.0 (#property version)" in detail and "SET associé" in detail
    assert "compilé" in detail
    assert "Famille 1" in run(["famille", "1", "--fichier"])
