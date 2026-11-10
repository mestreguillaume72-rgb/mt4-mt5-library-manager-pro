"""Phase 6 — SET et associations sur un corpus fictif dont la vérité terrain est connue."""

from __future__ import annotations

import io
import unicodedata
from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.context import AppContext, open_app
from mtlm.app.formats import FormatService
from mtlm.app.hashing import HashService
from mtlm.app.recognize import RecognitionService
from mtlm.app.scan import ScanService
from mtlm.app.sets import AssociationError, AssociationService, SetService
from mtlm.app.sources import SourceService
from mtlm.cli.main import EXIT_ERROR, EXIT_OK, main
from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths
from mtlm.matching.names import logical_key
from tests.support.fs_snapshot import diff_snapshots, take_snapshot
from tests.synthetic.generate import generate_corpus


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def analyse(ctx: AppContext, root: Path) -> None:
    source = SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).add(root)
    for service in (
        ScanService(ctx.conn, ctx.clock, ctx.journal).scan,
        HashService(ctx.conn, ctx.clock, ctx.journal).run,
        FormatService(ctx.conn, ctx.clock, ctx.journal).run,
        RecognitionService(ctx.conn, ctx.clock, ctx.journal).run,
        SetService(ctx.conn, ctx.clock, ctx.journal).parse_all,
    ):
        service(source.id)


def test_precision_sur_verite_terrain(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    manifest = generate_corpus(root, seed=31, n_files=2500)
    analyse(ctx, root)
    before = take_snapshot(root)
    summary = AssociationService(ctx.conn, ctx.clock, ctx.journal).compute()
    assert diff_snapshots(before, take_snapshot(root)) == []
    ids = {r[1]: int(r[0]) for r in ctx.conn.execute("SELECT id, rel_path FROM file_record")}
    paths = {v: k for k, v in ids.items()}
    truth = {
        ids[unicodedata.normalize("NFC", e.rel_path)]: unicodedata.normalize("NFC", e.set_for)
        for e in manifest.entries
        if e.kind == "set" and e.set_for
    }
    assert summary.sets == len(truth)
    service = AssociationService(ctx.conn, ctx.clock, ctx.journal)
    strong = service.find(level="forte", limit=100_000)
    assert len(strong) >= 0.8 * len(truth)  # rappel des associations fortes
    correct = sum(
        1
        for a in strong
        if logical_key(paths[a.robot_file_id]) == logical_key(truth[a.set_file_id])
        and paths[a.robot_file_id].rsplit(".", 1)[-1] in ("mq4", "mq5")
    )
    assert correct / len(strong) >= 0.95  # précision exigée (PLAN_DE_TESTS § 3.7)
    assert all(a.user_decision == "none" for a in service.find(limit=100_000))


def test_decisions_conservees_et_auditees(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    generate_corpus(root, seed=32, n_files=400)
    analyse(ctx, root)
    service = AssociationService(ctx.conn, ctx.clock, ctx.journal)
    service.compute()
    first, second = service.find(limit=2)
    service.decide(first.id, "accepted")
    service.decide(second.id, "rejected")
    summary = service.compute()  # recalcul : les décisions restent
    assert summary.decisions_kept == 2
    decisions = {a.id: a.user_decision for a in service.find(limit=100_000)}
    assert decisions[first.id] == "accepted" and decisions[second.id] == "rejected"
    actions = [r.action for r in ctx.journal]
    assert "association.accepted" in actions and "association.rejected" in actions
    with pytest.raises(AssociationError):
        service.decide(999_999, "accepted")
    with pytest.raises(AssociationError):
        service.decide(first.id, "peut-être")


def test_orphelin_et_robot_compile_a_verifier(tmp_path: Path, ctx: AppContext) -> None:
    root = tmp_path / "lib"
    (root / "MQL4" / "Experts").mkdir(parents=True)
    (root / "MQL4" / "Presets").mkdir(parents=True)
    (root / "MQL4" / "Experts" / "Opaque.ex4").write_bytes(bytes(range(256)))
    (root / "MQL4" / "Presets" / "Opaque_EURUSD.set").write_text(
        "Lots=0.1\nTP=5\n", encoding="utf-8"
    )
    (root / "MQL4" / "Presets" / "Inconnu.set").write_text("Zzz=1\n", encoding="utf-8")
    analyse(ctx, root)
    service = AssociationService(ctx.conn, ctx.clock, ctx.journal)
    service.compute()
    rows = service.find()
    assert [(r.level, r.robot_path.endswith("Opaque.ex4")) for r in rows] == [("a_verifier", True)]
    assert [p for _, p in service.orphans()] == ["MQL4/Presets/Inconnu.set"]
    kinds = {e[0] for e in service.evidence(rows[0].id)}
    assert "parametres_inaccessibles" in kinds


def test_cli_sets_associations(tmp_path: Path, environ: dict[str, str], clock: FixedClock) -> None:
    root = tmp_path / "lib"
    (root / "MQL5" / "Experts").mkdir(parents=True)
    (root / "MQL5" / "Presets").mkdir(parents=True)
    (root / "MQL5" / "Experts" / "Tendance.mq5").write_text(
        "input double Lots = 0.1;\ninput int Periode = 14;\nvoid OnTick(){}\n", encoding="utf-8"
    )
    (root / "MQL5" / "Presets" / "Tendance_H1.set").write_bytes(
        b"\xff\xfe" + "Lots=0.2||0.1||0.1||1||Y\nPeriode=21||7||1||50||N\n".encode("utf-16-le")
    )
    (root / "MQL5" / "Presets" / "Tendance_H4.set").write_bytes(
        b"\xff\xfe" + "Lots=0.2||0.1||0.1||1||Y\nPeriode=28||7||1||50||N\n".encode("utf-16-le")
    )

    def run(args: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        code = main(args, environ=environ, clock=clock, out=out, err=io.StringIO())
        return code, out.getvalue()

    for args in (
        ["source", "ajouter", str(root)],
        ["scanner"],
        ["empreintes"],
        ["formats"],
        ["reconnaitre"],
    ):
        assert run(args)[0] == EXIT_OK
    code, out = run(["sets"])
    assert code == EXIT_OK and "2 analysé(s) — 0 MT4, 2 MT5" in out
    code, out = run(["set", "2"])
    assert "Periode = 21" in out and "optimisation désactivée" in out
    code, out = run(["comparer-sets", "2", "3"])
    assert "1 identique(s) sur 2" in out and "Periode" in out
    code, out = run(["associer"])
    assert "2 proposée(s)" in out and "validée automatiquement" in out
    code, out = run(["associations", "--niveau", "forte"])
    assert out.count("forte") == 2 and "non décidée" in out
    code, out = run(["association", "1"])
    assert "+ couverture_parametres" in out and "Score :" in out
    code, out = run(["valider", "1", "--accepter"])
    assert "ACCEPTÉE" in out
    code, out = run(["orphelins"])
    assert "0 SET orphelin(s)" in out
    assert run(["set", "1"])[0] == EXIT_ERROR
