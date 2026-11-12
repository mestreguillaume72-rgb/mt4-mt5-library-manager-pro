"""1.3.0 — placement des SET : rangé avec son robot, en vrac, rangé avec un autre robot.

Le placement est une information : tous les SET sont analysés et associés de la même façon."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.context import AppContext, open_app
from mtlm.app.sets import PLACEMENT_LABELS, AssociationService
from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths
from tests.integration.test_quarantine_organize import analyse

SCALPER = (
    "extern double Lots = 0.1;\nextern int TakeProfit = 50;\nextern int StopLoss = 30;\n"
    "extern bool UseTrailing = true;\nint start(){return 0;}\n"
)
GRID = "input int GridStep = 20;\ninput int MaxOrders = 5;\ninput double Multiplier = 1.5;\n"


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def test_trois_placements_et_orphelin(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    (lib / "Experts" / "Scalper").mkdir(parents=True)
    (lib / "Experts" / "Grid").mkdir(parents=True)
    (lib / "Bazar").mkdir()
    (lib / "Experts" / "Scalper" / "Scalper.mq4").write_text(SCALPER, encoding="utf-8")
    (lib / "Experts" / "Grid" / "Grid.mq4").write_text(GRID, encoding="utf-8")

    def params(lots: str, tp: int, sl: int, trailing: str) -> str:
        return f"Lots={lots}\nTakeProfit={tp}\nStopLoss={sl}\nUseTrailing={trailing}\n"

    sets = {
        "Experts/Scalper/Scalper_EURUSD.set": params("0.2", 40, 25, "false"),
        "Bazar/reglage GBP final (2).set": params("0.5", 80, 35, "true"),
        "Experts/Grid/Scalper_GOLD.set": params("0.3", 60, 20, "true"),
        "Bazar/inconnu.set": "Couleur=Rouge\nVitesse=3\n",
    }
    for rel, text in sets.items():
        (lib / rel).write_text(text, encoding="utf-8")
    analyse(ctx, lib)
    service = AssociationService(ctx.conn, ctx.clock, ctx.journal)
    ids = {
        rel: int(
            ctx.conn.execute("SELECT id FROM file_record WHERE rel_path = ?", (rel,)).fetchone()[0]
        )
        for rel in sets
    }
    placements = service.placements()
    assert placements[ids["Experts/Scalper/Scalper_EURUSD.set"]] == "avec_son_robot"
    assert placements[ids["Bazar/reglage GBP final (2).set"]] == "en_vrac"
    assert placements[ids["Experts/Grid/Scalper_GOLD.set"]] == "avec_autre_robot"
    assert ids["Bazar/inconnu.set"] not in placements
    assert service.placement_counts() == {
        "avec_son_robot": 1,
        "en_vrac": 1,
        "avec_autre_robot": 1,
        "orphelins": 1,
    }
    # Les trois SET reliés le sont au même robot, quel que soit leur emplacement.
    for rel in list(sets)[:3]:
        best = service.find(set_file_id=ids[rel], limit=1)[0]
        assert best.robot_path == "Experts/Scalper/Scalper.mq4"
        assert best.placement in PLACEMENT_LABELS
