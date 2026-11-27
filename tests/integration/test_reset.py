"""1.6.0 — « Recommencer l'analyse à zéro » : résultats effacés, rien sur le disque, historique
conservé, et une nouvelle analyse retrouve les mêmes résultats."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.context import AppContext, open_app
from mtlm.app.duplicates import DuplicateService
from mtlm.app.pipeline import STEPS, run_steps
from mtlm.app.reset import ANALYSIS_TABLES, ResetService
from mtlm.core.clock import FixedClock
from mtlm.core.control import TaskControl
from mtlm.core.paths import AppPaths
from tests.integration.test_quarantine_organize import analyse, build
from tests.support.fs_snapshot import diff_snapshots, take_snapshot


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def counts(ctx: AppContext) -> dict[str, int]:
    return {
        t: int(ctx.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) for t in ANALYSIS_TABLES
    }


def test_recommencer_a_zero(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    before = counts(ctx)
    groups = len(DuplicateService(ctx.conn, ctx.clock, ctx.journal).groups())
    assert groups and before["file_analysis"]
    disk = take_snapshot(lib)
    summary = ResetService(ctx.conn, ctx.journal).reset()
    assert summary.files_to_reread > 0
    assert all(v == 0 for v in counts(ctx).values())
    assert (
        ctx.conn.execute(
            "SELECT count(*) FROM file_record WHERE hash_state = 'validated'"
        ).fetchone()[0]
        == 0
    )
    assert ctx.conn.execute("SELECT count(*) FROM source_root").fetchone()[0] == 1
    assert diff_snapshots(disk, take_snapshot(lib)) == []
    # Nouvelle analyse complète : mêmes résultats qu'avant.
    run_steps(ctx, [step.key for step in STEPS], TaskControl(), lambda _text: None)
    assert len(DuplicateService(ctx.conn, ctx.clock, ctx.journal).groups()) == groups
    assert counts(ctx)["file_analysis"] == before["file_analysis"]


def test_doublons_avec_une_source_indisponible(tmp_path: Path, ctx: AppContext) -> None:
    """Régression « member_count >= 2 » : une copie dans une source devenue indisponible ne
    crée jamais un groupe d'un seul fichier."""
    first, second = tmp_path / "A", tmp_path / "B"
    for folder in (first, second):
        folder.mkdir()
        (folder / "Robot.mq4").write_text("int start(){return 0;}\n", encoding="utf-8")
    analyse(ctx, first)
    analyse(ctx, second)
    ctx.conn.execute("UPDATE source_root SET status = 'unreachable' WHERE path = ?", (str(second),))
    summary = DuplicateService(ctx.conn, ctx.clock, ctx.journal).compute()
    assert summary.groups == 0
