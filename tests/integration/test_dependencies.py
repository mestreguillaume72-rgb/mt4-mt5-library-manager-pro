"""1.4.0 — tout ce qui va avec un outil : indicateurs appelés (iCustom), DLL et bibliothèques
importées (#import), modèles de graphique (.tpl). Les DLL ne sont jamais chargées."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.companions import CompanionService
from mtlm.app.context import AppContext, open_app
from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths
from mtlm.metatrader.templates import parse_template
from tests.integration.test_quarantine_organize import analyse

ROBOT = (
    '#import "Helper.dll"\nint Calc(int a);\n#import\n#import "MathLib.ex4"\ndouble Avg();\n'
    "#import\nextern double Lots = 0.1;\n"
    'int start(){ double v = iCustom(NULL, 0, "SuperTrend", 10, 0, 1); return 0; }\n'
)
INDICATOR = (
    "#property indicator_chart_window\n#property indicator_buffers 1\n"
    "input int Period = 10;\nint OnCalculate(const int rates_total){ return 0; }\n"
)
TEMPLATE = (
    "<chart>\nsymbol=EURUSD\n<expert>\nname=Gold Robot\nflags=279\n</expert>\n<window>\n"
    "<indicator>\nname=Custom Indicator\n<ind>\npath=\nname=SuperTrend\n</ind>\n</indicator>\n"
    "<indicator>\nname=Moving Average\n</indicator>\n</window>\n</chart>\n"
)


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def build(root: Path) -> None:
    files: dict[str, str | bytes] = {
        "MQL4/Experts/Gold/Gold Robot.mq4": ROBOT,
        "MQL4/Indicators/SuperTrend.mq4": INDICATOR,
        "MQL4/Indicators/SuperTrend.ex4": b"EX4 fictif",
        "MQL4/Libraries/Helper.dll": b"MZ fictif - jamais charge",
        "MQL4/Libraries/MathLib.ex4": b"EX4 fictif - bibliotheque",
        "Telechargements/gold setup.tpl": TEMPLATE.encode("utf-16"),
        "Telechargements/autre.dll": b"MZ fictif",
    }
    for index, (rel, content) in enumerate(files.items()):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        stamp = 1_700_000_000 + index * 100
        os.utime(path, (stamp, stamp))


def test_modele_mt4_et_mt5() -> None:
    names = {(t.kind, t.name) for t in parse_template(TEMPLATE)}
    assert names == {
        ("robot", "Gold Robot"),
        ("indicateur", "SuperTrend"),
        ("indicateur", "Moving Average"),
    }


def test_robot_indicateur_dll_bibliotheque_et_modele(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    service = CompanionService(ctx.conn, ctx.clock, ctx.journal)
    summary = service.rebuild()
    ids = {r[1]: int(r[0]) for r in ctx.conn.execute("SELECT id, rel_path FROM file_record")}
    robot = ids["MQL4/Experts/Gold/Gold Robot.mq4"]
    deps = {(d.used_path, d.kind) for d in service.dependencies([robot])}
    # iCustom MT4 : la source et le compilé de l'indicateur ; bibliothèque importée.
    assert ("MQL4/Indicators/SuperTrend.mq4", "icustom") in deps
    assert ("MQL4/Indicators/SuperTrend.ex4", "icustom") in deps
    assert ("MQL4/Libraries/MathLib.ex4", "import") in deps
    assert summary.dependencies >= 3
    links = {
        (r.companion_path, r.tool_path.rpartition("/")[2], r.confidence, r.placement)
        for r in service.all()
    }
    assert (
        "MQL4/Libraries/Helper.dll",
        "Gold Robot.mq4",
        "certain",
        "dossier_standard",
    ) in links
    # Le modèle charge le robot et l'indicateur : relié de façon certaine aux deux.
    tpl = {(t, c) for p, t, c, _pl in links if p == "Telechargements/gold setup.tpl"}
    assert ("Gold Robot.mq4", "certain") in tpl and ("SuperTrend.mq4", "certain") in tpl
    # DLL sans indice : jamais reliée au hasard.
    assert not any(p == "Telechargements/autre.dll" for p, *_ in links)
    # Avant une suppression : qui a besoin de quoi.
    needed = service.needed_by(
        [ids["MQL4/Indicators/SuperTrend.ex4"], ids["MQL4/Libraries/Helper.dll"]]
    )
    assert needed[ids["MQL4/Indicators/SuperTrend.ex4"]] == ["MQL4/Experts/Gold/Gold Robot.mq4"]
    assert needed[ids["MQL4/Libraries/Helper.dll"]] == ["MQL4/Experts/Gold/Gold Robot.mq4"]


def test_tout_ensemble_dans_les_dossiers_proposes(tmp_path: Path, ctx: AppContext) -> None:
    from mtlm.app.organize import OrganizeService

    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    CompanionService(ctx.conn, ctx.clock, ctx.journal).rebuild()
    service = OrganizeService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    dest = tmp_path / "Dest"
    dest.mkdir()
    family = int(
        ctx.conn.execute(
            "SELECT fm.family_id FROM family_member fm JOIN file_record f ON f.id = fm.file_id"
            " WHERE f.rel_path = 'MQL4/Experts/Gold/Gold Robot.mq4'"
        ).fetchone()[0]
    )
    preview = service.preview_family(dest, family)
    targets = {t for _f, t, _s, _c in service.items(preview.plan_id)}
    assert {
        "Gold/Gold Robot.mq4",
        "Indicateurs utilisés/SuperTrend.mq4",
        "Indicateurs utilisés/SuperTrend.ex4",
        "Bibliothèques/MathLib.ex4",
        "Bibliothèques/Helper.dll",
        "Modèles/gold setup.tpl",
    } <= targets
    result = service.execute(preview.plan_id, preview.token)
    assert result.status == "completed"
    assert (dest / "Gold Robot" / "Bibliothèques" / "Helper.dll").is_file()
    # Isolement MQ4/MQ5 : l'indicateur utilisé va avec le robot qui l'utilise.
    sources = service.preview_sources(dest)
    isolated = {t for _f, t, _s, _c in service.items(sources.plan_id)}
    assert {
        "MQ4/Gold Robot/Gold Robot.mq4",
        "MQ4/Gold Robot/SuperTrend.ex4",
        "MQ4/Gold Robot/SuperTrend.mq4",
        "MQ4/Gold Robot/Helper.dll",
    } <= isolated
    assert not any(t.startswith("MQ4/SuperTrend/") for t in isolated)
    # Plusieurs familles d'un coup : un dossier « Familles réunies ».
    other = int(
        ctx.conn.execute(
            "SELECT fm.family_id FROM family_member fm JOIN file_record f ON f.id = fm.file_id"
            " WHERE f.rel_path = 'MQL4/Indicators/SuperTrend.mq4'"
        ).fetchone()[0]
    )
    both = service.preview_families(dest, [family, other])
    assert Path(both.destination).name.startswith("Familles réunies")
    shared = [t for _f, t, _s, _c in service.items(both.plan_id, limit=5000)]
    assert {t.split("/")[0] for t in shared} <= {"Gold Robot", "SuperTrend"}
    # Un indicateur partagé n'est copié qu'une fois (avec le premier robot qui l'utilise).
    assert sum(t.endswith("SuperTrend.mq4") for t in shared) == 1
