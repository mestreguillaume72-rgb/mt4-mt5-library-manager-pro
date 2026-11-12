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


def test_isoler_sources_mq_avec_leurs_set(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    before = take_snapshot(lib)
    service = organize(ctx)
    preview = service.preview_sources(mkd(tmp_path / "Dest"))
    assert Path(preview.destination).name.startswith("Sources MQ4-MQ5 avec SET")
    targets = [t for _f, t, _s, _c in service.items(preview.plan_id)]
    assert all(t.startswith("MQ4/") for t in targets)
    sets = [t for t in targets if t.endswith(".set")]
    assert sets, "les SET associés doivent accompagner leur robot"
    folders_with_source = {t.rpartition("/")[0] for t in targets if t.endswith(".mq4")}
    assert all(t.rpartition("/")[0] in folders_with_source for t in sets)
    result = service.execute(preview.plan_id, preview.token)
    assert result.status == "completed"
    for target in targets:
        assert (Path(preview.destination) / target).is_file()
    assert diff_snapshots(before, take_snapshot(lib)) == []


def test_propositions_refusees_si_destination_invalide(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    service = organize(ctx)
    with pytest.raises(DestinationError):
        service.preview_sources(lib / "MQL4")  # dans une source : refusé
    with pytest.raises(OrganizeError, match="inconnue"):
        service.preview_family(mkd(tmp_path / "Dest"), 999_999)
