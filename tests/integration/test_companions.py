"""1.3.0 — fichiers liés (images, documents, includes) : indices expliqués et placement."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.companions import CompanionService
from mtlm.app.context import AppContext, open_app
from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths
from tests.integration.test_quarantine_organize import analyse

SCALPER = (
    '#resource "\\\\Images\\\\logo.bmp"\n#include <ScalperLib.mqh>\n'
    'extern double Lots = 0.1;\nint start(){ PlaySound("alerte.wav"); return 0;}\n'
)
GRID = "input int GridStep = 20;\nvoid OnTick(){}\n"


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def library(root: Path, *, together: bool = False) -> None:
    files = {
        "MQL4/Experts/Scalper/Scalper.mq4": SCALPER,
        "MQL4/Experts/Scalper/Scalper manuel.pdf": "%PDF-1.4 fictif",
        "MQL4/Images/logo.bmp": "BM fictif",
        "MQL4/Include/ScalperLib.mqh": "int Aide(){return 1;}\n",
        "Telechargements/alerte.wav": "RIFF fictif",
        "MQL4/Experts/Grid/Grid.mq4": GRID,
        "MQL4/Experts/Grid/fond.png": "PNG fictif",
        "MQL4/Experts/Scalper/capture.png": "PNG fictif",
        "Bazar/vacances.jpg": "JPG fictif",
    }
    for index, (rel, text) in enumerate(files.items()):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        stamp = 1_700_000_000 + (0 if together else index * 100)
        os.utime(path, (stamp, stamp))


def links(ctx: AppContext) -> dict[str, tuple[str, str, str]]:
    rows = CompanionService(ctx.conn, ctx.clock, ctx.journal).all()
    return {
        r.companion_path: (r.tool_path.rpartition("/")[2], r.confidence, r.placement) for r in rows
    }


def test_indices_et_placement(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    library(lib)
    analyse(ctx, lib)
    CompanionService(ctx.conn, ctx.clock, ctx.journal).rebuild()
    found = links(ctx)
    # Cités dans le code : certain, même rangés ailleurs.
    # Rangés dans les dossiers prévus par MetaTrader (Images, Include) : pas « en vrac ».
    assert found["MQL4/Images/logo.bmp"] == ("Scalper.mq4", "certain", "dossier_standard")
    assert found["Telechargements/alerte.wav"] == ("Scalper.mq4", "certain", "en_vrac")
    assert found["MQL4/Include/ScalperLib.mqh"] == ("Scalper.mq4", "certain", "dossier_standard")
    # Même dossier et nom proche : probable, rangé avec son outil.
    assert found["MQL4/Experts/Scalper/Scalper manuel.pdf"] == (
        "Scalper.mq4",
        "probable",
        "avec_son_robot",
    )
    # Seul outil du dossier : possible.
    assert found["MQL4/Experts/Grid/fond.png"] == ("Grid.mq4", "possible", "avec_son_robot")
    assert found["MQL4/Experts/Scalper/capture.png"][1] == "possible"
    # Aucun indice : jamais relié au hasard.
    assert "Bazar/vacances.jpg" not in found
    counts = CompanionService(ctx.conn, ctx.clock, ctx.journal).placement_counts()
    assert counts["sans_outil"] == 1 and counts["en_vrac"] == 1
    assert counts["dossier_standard"] == 2


def test_crees_ensemble_relie_un_fichier_range_ailleurs(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    library(lib, together=True)  # tout daté du même instant : petit lot « créés ensemble »
    analyse(ctx, lib)
    CompanionService(ctx.conn, ctx.clock, ctx.journal).rebuild()
    found = links(ctx)
    assert found["Bazar/vacances.jpg"][1] == "possible"
    # Les indices plus forts restent prioritaires.
    assert found["MQL4/Images/logo.bmp"][1] == "certain"


def test_fichiers_lies_suivent_leur_robot_dans_les_dossiers_proposes(
    tmp_path: Path, ctx: AppContext
) -> None:
    from mtlm.app.organize import OrganizeService

    lib = tmp_path / "lib"
    library(lib)
    analyse(ctx, lib)
    CompanionService(ctx.conn, ctx.clock, ctx.journal).rebuild()
    service = OrganizeService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    dest = tmp_path / "Dest"
    dest.mkdir()
    family = int(
        ctx.conn.execute(
            "SELECT fm.family_id FROM family_member fm JOIN file_record f ON f.id = fm.file_id"
            " WHERE f.rel_path = 'MQL4/Experts/Scalper/Scalper.mq4'"
        ).fetchone()[0]
    )
    preview = service.preview_family(dest, family)
    targets = {t for _f, t, _s, _c in service.items(preview.plan_id)}
    assert {"Images/logo.bmp", "Sons/alerte.wav", "Documents/Scalper manuel.pdf"} <= targets
    assert "Images/capture.png" not in targets  # indice seulement « possible » : pas copié
    sources = service.preview_sources(dest)
    isolated = {t for _f, t, _s, _c in service.items(sources.plan_id)}
    assert {"MQ4/Scalper/Scalper.mq4", "MQ4/Scalper/logo.bmp", "MQ4/Scalper/alerte.wav"} <= isolated
