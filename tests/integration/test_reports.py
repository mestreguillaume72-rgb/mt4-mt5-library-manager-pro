"""F10 — exports : complets, fidèles à la base, Unicode et caractères spéciaux, jamais
d'écrasement ni d'écriture dans une source."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from mtlm.app.context import open_app
from mtlm.app.reports import KINDS, ReportService
from mtlm.cli.main import EXIT_ERROR, EXIT_OK, main
from mtlm.core.clock import FixedClock
from mtlm.core.errors import ExportError
from mtlm.core.paths import AppPaths
from mtlm.transfer.guards import DestinationError

PIPELINE = [
    "scanner",
    "empreintes",
    "formats",
    "reconnaitre",
    "sets",
    "associer",
    "regrouper",
    "doublons",
]


def prepare(tmp_path: Path, environ: dict[str, str], clock: FixedClock) -> Path:
    lib = tmp_path / "lib"
    (lib / "MQL4" / "Experts").mkdir(parents=True)
    (lib / "MQL4" / "Presets").mkdir(parents=True)
    src = 'extern double Lots = 0.1;\nextern string Note = "a;b\\"c";\nint start(){return 0;}\n'
    (lib / "MQL4" / "Experts" / "Été; robot.mq4").write_text(src, encoding="utf-8")
    (lib / "MQL4" / "Experts" / "Copie.mq4").write_text(src, encoding="utf-8")
    (lib / "MQL4" / "Presets" / "Été; robot_EURUSD.set").write_text(
        'Lots=0.2\nNote=x;"y"\n', encoding="utf-8"
    )
    for args in (["source", "ajouter", str(lib)], *[[c] for c in PIPELINE]):
        assert (
            main(args, environ=environ, clock=clock, out=io.StringIO(), err=io.StringIO())
            == EXIT_OK
        )
    out = tmp_path / "exports"
    out.mkdir()
    return out


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_exports_csv_et_json_complets(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock, paths: AppPaths, kind: str
) -> None:
    out = prepare(tmp_path, environ, clock)
    with open_app(paths, clock) as ctx:
        service = ReportService(ctx.conn, ctx.journal, ctx.paths)
        expected = list(service.rows(kind))
        n_csv = service.export(kind, out / f"{kind}.csv")
        service.export(kind, out / f"{kind}.json")
    with (out / f"{kind}.csv").open(encoding="utf-8-sig", newline="") as handle:
        read = list(csv.reader(handle, delimiter=";"))
    assert read[0] == list(KINDS[kind].header)
    assert len(read) - 1 == n_csv == len(expected)
    for row, original in zip(read[1:], expected, strict=True):
        assert row == ["" if v is None else str(v) for v in original]
    document = json.loads((out / f"{kind}.json").read_text(encoding="utf-8"))
    assert document["nombre"] == len(expected) and document["export"] == kind


def test_inventaire_contient_unicode_et_separateurs(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock, paths: AppPaths
) -> None:
    out = prepare(tmp_path, environ, clock)
    with open_app(paths, clock) as ctx:
        ReportService(ctx.conn, ctx.journal, ctx.paths).export("inventaire", out / "i.csv")
    text = (out / "i.csv").read_text(encoding="utf-8-sig")
    assert '"MQL4/Experts/Été; robot.mq4"' in text  # point-virgule protégé par des guillemets


def test_jamais_d_ecrasement_ni_dans_une_source(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock, paths: AppPaths
) -> None:
    out = prepare(tmp_path, environ, clock)
    (out / "deja.csv").write_text("précieux", encoding="utf-8")
    with open_app(paths, clock) as ctx:
        service = ReportService(ctx.conn, ctx.journal, ctx.paths)
        with pytest.raises(ExportError, match="ne sera pas écrasé"):
            service.export("inventaire", out / "deja.csv")
        with pytest.raises(DestinationError):
            service.export("inventaire", tmp_path / "lib" / "export.csv")
        with pytest.raises(ExportError, match="non pris en charge"):
            service.export("inventaire", out / "x.txt")
        with pytest.raises(ExportError, match="inconnu"):
            service.export("rien", out / "x.csv")
    assert (out / "deja.csv").read_text(encoding="utf-8") == "précieux"
    assert not (tmp_path / "lib" / "export.csv").exists()


def test_export_base_vide(tmp_path: Path, paths: AppPaths, clock: FixedClock) -> None:
    with open_app(paths, clock) as ctx:
        count = ReportService(ctx.conn, ctx.journal, ctx.paths).export(
            "doublons", tmp_path / "v.json"
        )
    assert count == 0
    assert json.loads((tmp_path / "v.json").read_text(encoding="utf-8"))["elements"] == []


def test_cli_exporter(tmp_path: Path, environ: dict[str, str], clock: FixedClock) -> None:
    out = prepare(tmp_path, environ, clock)
    buffer = io.StringIO()
    code = main(
        ["exporter", "associations", str(out / "a.csv")],
        environ=environ,
        clock=clock,
        out=buffer,
        err=io.StringIO(),
    )
    assert code == EXIT_OK and "ligne(s) écrite(s)" in buffer.getvalue()
    code = main(
        ["exporter", "associations", str(out / "a.csv")],
        environ=environ,
        clock=clock,
        out=io.StringIO(),
        err=io.StringIO(),
    )
    assert code == EXIT_ERROR


def test_export_dans_un_dossier_qui_contient_la_source(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock, paths: AppPaths
) -> None:
    """Écrire un export dans « Documents » (qui contient la bibliothèque) est autorisé."""
    prepare(tmp_path, environ, clock)
    with open_app(paths, clock) as ctx:
        count = ReportService(ctx.conn, ctx.journal, ctx.paths).export(
            "inventaire", tmp_path / "inventaire.csv"
        )
    assert count == 3 and (tmp_path / "inventaire.csv").exists()
