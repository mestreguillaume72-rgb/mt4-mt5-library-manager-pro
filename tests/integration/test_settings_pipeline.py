"""Paramètres réellement utilisés + pipeline complet (CLI « analyser »)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from mtlm.app.context import open_app
from mtlm.app.pipeline import STEPS, run_steps
from mtlm.app.settings import SettingsError, SettingsService
from mtlm.cli.main import EXIT_ERROR, EXIT_OK, EXIT_USAGE, main
from mtlm.core.clock import FixedClock
from mtlm.core.control import Cancelled, TaskControl
from mtlm.core.paths import AppPaths
from tests.synthetic.generate import generate_corpus


def test_parametres_valides_et_journalises(paths: AppPaths, clock: FixedClock) -> None:
    with open_app(paths, clock) as ctx:
        service = SettingsService(ctx.conn, ctx.journal)
        assert service.get("similarite.seuil") == 0.80
        assert service.set("similarite.seuil", 0.9) == 0.9
        assert service.set("empreintes.travailleurs", 2) == 2
        with pytest.raises(SettingsError, match="entre"):
            service.set("similarite.seuil", 2)
        with pytest.raises(SettingsError, match="entier"):
            service.set("empreintes.travailleurs", 1.5)
        with pytest.raises(SettingsError, match="inconnu"):
            service.get("rien")
        service.set("archives.ratio", 50)
        assert service.archive_limits().max_ratio == 50
        assert service.reset("archives.ratio") == 100
        assert sum(r.action == "settings.set" for r in ctx.journal) == 4


def test_pipeline_complet_et_annulation(tmp_path: Path, paths: AppPaths, clock: FixedClock) -> None:
    generate_corpus(tmp_path / "lib", seed=3, n_files=300)
    with open_app(paths, clock) as ctx:
        from mtlm.app.sources import SourceService

        SourceService(ctx.conn, clock, ctx.journal, paths).add(tmp_path / "lib")
        messages: list[str] = []
        results = run_steps(ctx, [s.key for s in STEPS], TaskControl(), messages.append)
        assert [label for label, _ in results] == [s.label for s in STEPS]
        assert messages and "300 vus" in results[0][1]
        control = TaskControl()
        control.cancel()
        with pytest.raises(Cancelled):
            run_steps(ctx, ["inventaire"], control, messages.append)


def test_cli_analyser_et_parametres(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock
) -> None:
    generate_corpus(tmp_path / "lib", seed=4, n_files=200)

    def run(args: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        return main(args, environ=environ, clock=clock, out=out, err=io.StringIO()), out.getvalue()

    run(["source", "ajouter", str(tmp_path / "lib")])
    code, out = run(["analyser"])
    assert code == EXIT_OK and out.count("\n") == len(STEPS)
    assert "Doublons et similarités" in out
    code, out = run(["parametres"])
    assert "similarite.seuil = 0.8" in out
    assert (
        run(["parametres", "--definir", "similarite.seuil", "0,95"])[1].strip()
        == "similarite.seuil = 0.95"
    )
    assert run(["parametres", "--definir", "similarite.seuil", "abc"])[0] == EXIT_USAGE
    assert run(["parametres", "--definir", "similarite.seuil", "5"])[0] == EXIT_ERROR
    assert "défaut" in run(["parametres", "--reinitialiser", "similarite.seuil"])[1]
    code, out = run(["analyser", "--etapes", "doublons"])
    assert code == EXIT_OK and out.startswith("Doublons")
