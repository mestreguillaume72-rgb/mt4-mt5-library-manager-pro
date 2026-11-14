"""1.3.0 — propositions à valider : dossier d'une famille au nom du robot, sources MQ4/MQ5
isolées avec leurs SET. Copie vérifiée ; les sources restent intactes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.context import AppContext, open_app
from mtlm.app.organize import OrganizeError, OrganizeService
from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths
from mtlm.transfer.guards import DestinationError
from tests.integration.test_quarantine_organize import analyse, build, mkd
from tests.support.fs_snapshot import diff_snapshots, take_snapshot


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def organize(ctx: AppContext) -> OrganizeService:
    return OrganizeService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)


def family_of(ctx: AppContext, rel_path: str) -> int:
    return int(
        ctx.conn.execute(
            "SELECT fm.family_id FROM family_member fm JOIN file_record f ON f.id = fm.file_id"
            " WHERE f.rel_path = ?",
            (rel_path,),
        ).fetchone()[0]
    )


def test_dossier_de_famille_au_nom_du_robot(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    before = take_snapshot(lib)
    family = family_of(ctx, "MQL4/Experts/Scalper.mq4")
    service = organize(ctx)
    preview = service.preview_family(mkd(tmp_path / "Dest"), family)
    assert Path(preview.destination).name == "Scalper"
    targets = {t for _f, t, _s, _c in service.items(preview.plan_id)}
    # Versions réunies, sous le nom de leur dossier d'origine ; copies identiques une seule fois.
    assert {"Experts/Scalper.mq4", "Experts/Scalper_v2.mq4"} <= targets
    assert not any("Copie" in t for t in targets)
    assert preview.excluded_duplicates >= 1
    result = service.execute(preview.plan_id, preview.token)
    assert result.status == "completed" and result.failed == 0
    folder = tmp_path / "Dest" / "Scalper"
    assert (folder / "Experts" / "Scalper_v2.mq4").is_file()
    assert (folder / "manifeste-organisation.json").is_file()
    assert diff_snapshots(before, take_snapshot(lib)) == []
    # Une nouvelle proposition ne mélange jamais avec le dossier existant.
    again = service.preview_family(tmp_path / "Dest", family)
    assert Path(again.destination).name == "Scalper (2)"


def test_isoler_sources_mq_fichier_seul_et_set_valides(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    before = take_snapshot(lib)
    service = organize(ctx)
    preview = service.preview_sources(mkd(tmp_path / "Dest"))
    assert Path(preview.destination).name.startswith("Sources MQ4-MQ5 isolées")
    targets = [t for _f, t, _s, _c in service.items(preview.plan_id)]
    # Rangées dans « Experts » (dossier partagé) : chaque source est copiée seule.
    assert "MQ4/Scalper_v2/Scalper_v2.mq4" in targets
    assert not any(t.endswith(".set") for t in targets)  # rien sans validation
    sources = [int(r[0]) for r in ctx.conn.execute("SELECT id FROM file_record WHERE ext = 'mq4'")]
    candidates = service.isolation_candidates(sources)
    sets = {c.file_id: c.source_id for c in candidates if c.rel_path.endswith(".set")}
    assert sets
    validated = service.preview_sources(mkd(tmp_path / "Dest2"), None, sets)
    with_sets = [t for _f, t, _s, _c in service.items(validated.plan_id)]
    folders_with_source = {t.rpartition("/")[0] for t in with_sets if t.endswith(".mq4")}
    assert all(t.rpartition("/")[0] in folders_with_source for t in with_sets if t.endswith(".set"))
    result = service.execute(validated.plan_id, validated.token)
    assert result.status == "completed"
    assert diff_snapshots(before, take_snapshot(lib)) == []


def test_dossier_propre_copie_complet_tel_quel(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    robot_dir = lib / "MQL4" / "Experts" / "Gold Scalper Pro"
    (robot_dir / "Presets").mkdir(parents=True)
    (robot_dir / "Images").mkdir()
    (robot_dir / "Gold Scalper Pro.mq4").write_text("extern int X = 1;\n", encoding="utf-8")
    (robot_dir / "Gold Scalper Pro.ex4").write_bytes(b"EX4 fictif")
    (robot_dir / "Presets" / "eurusd.set").write_text("X=2\n", encoding="utf-8")
    (robot_dir / "Presets" / "copie.set").write_text("X=2\n", encoding="utf-8")  # copie
    (robot_dir / "Images" / "logo.png").write_bytes(b"PNG fictif")
    analyse(ctx, lib)
    source = int(ctx.conn.execute("SELECT id FROM file_record WHERE ext = 'mq4'").fetchone()[0])
    service = organize(ctx)
    assert service.source_layout([source]) == {source: ("dossier", "MQL4/Experts/Gold Scalper Pro")}
    preview = service.preview_sources(mkd(tmp_path / "Dest"), [source])
    assert {t for _f, t, _s, _c in service.items(preview.plan_id)} == {
        "MQ4/Gold Scalper Pro/Gold Scalper Pro.mq4",
        "MQ4/Gold Scalper Pro/Gold Scalper Pro.ex4",
        "MQ4/Gold Scalper Pro/Presets/eurusd.set",
        "MQ4/Gold Scalper Pro/Presets/copie.set",
        "MQ4/Gold Scalper Pro/Images/logo.png",
    }
    assert service.execute(preview.plan_id, preview.token).status == "completed"


def test_propositions_refusees_si_destination_invalide(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    service = organize(ctx)
    with pytest.raises(DestinationError):
        service.preview_sources(lib / "MQL4")  # dans une source : refusé
    with pytest.raises(OrganizeError, match="inconnue"):
        service.preview_family(mkd(tmp_path / "Dest"), 999_999)
