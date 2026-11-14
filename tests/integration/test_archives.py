"""1.5.0 — archives : « déjà décompressée » / fichiers absents du disque, décompression
vérifiée puis archive à la Corbeille (option de l'utilisateur)."""

from __future__ import annotations

import io
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.archives import ArchiveService, folder_name
from mtlm.app.context import AppContext, open_app
from mtlm.app.pipeline import STEPS, run_steps
from mtlm.app.settings import SettingsService
from mtlm.app.sources import SourceService
from mtlm.core.clock import FixedClock
from mtlm.core.control import TaskControl
from mtlm.core.paths import AppPaths
from mtlm.formats import libarchive
from tests.integration.test_quarantine_organize import analyse
from tests.integration.test_trash import FakeTrash

ROBOT = b"extern double Lots = 0.1;\nextern int TP = 50;\nint start(){return 0;}\n"
SET = b"Lots=0.2\nTP=40\n"


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def build(root: Path) -> None:
    (root / "MQL4" / "Experts").mkdir(parents=True)
    (root / "Telechargements").mkdir()
    (root / "MQL4" / "Experts" / "Scalper.mq4").write_bytes(ROBOT)
    with zipfile.ZipFile(root / "Telechargements" / "Scalper deja.zip", "w") as z:
        z.writestr("Scalper/Scalper.mq4", ROBOT)  # déjà sur le disque
    with zipfile.ZipFile(root / "Telechargements" / "Scalper pack.zip", "w") as z:
        z.writestr("Scalper/Scalper.mq4", ROBOT)
        z.writestr("Scalper/Scalper_EURUSD.set", SET)  # absent du disque
    if libarchive.available():
        with tarfile.open(root / "Telechargements" / "Grid.tar.gz", "w:gz") as t:
            data = b"input int GridStep = 20;\n"
            info = tarfile.TarInfo("Grid/Grid.mq4")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))


def rows(ctx: AppContext) -> dict[str, object]:
    return {
        r.rel_path.rpartition("/")[2]: r
        for r in ArchiveService(ctx.conn, ctx.clock, ctx.journal).rows()
    }


def test_noms_de_dossier() -> None:
    assert folder_name("Pack.zip") == "Pack"
    assert folder_name("Grid.tar.gz") == "Grid"
    assert folder_name("sans_extension") == "sans_extension"


def test_deja_decompressee_et_fichiers_absents(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    found = rows(ctx)
    deja, pack = found["Scalper deja.zip"], found["Scalper pack.zip"]
    assert deja.verdict == "Déjà décompressée : tout est sur le disque"  # type: ignore[attr-defined]
    assert pack.verdict == "Contient 1 fichier(s) absent(s) du disque"  # type: ignore[attr-defined]
    assert (pack.tools, pack.sets) == (1, 1)  # type: ignore[attr-defined]
    if libarchive.available():
        assert found["Grid.tar.gz"].status == "ok"  # type: ignore[attr-defined]
    service = ArchiveService(ctx.conn, ctx.clock, ctx.journal)
    entries = service.entries(pack.file_id)  # type: ignore[attr-defined]
    assert entries[1][:2] == ("Scalper/Scalper_EURUSD.set", "SET")
    assert entries[1][4] == "non (absent du disque)"
    assert entries[0][4] == "oui : MQL4/Experts/Scalper.mq4"


def test_decompression_verifiee_puis_corbeille(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    trash = FakeTrash(tmp_path / "Corbeille")
    service = ArchiveService(ctx.conn, ctx.clock, ctx.journal)
    pack = rows(ctx)["Scalper pack.zip"].file_id  # type: ignore[attr-defined]
    done = service.extract([pack], trash, trash_archive=True)
    assert (done.extracted, done.files, done.trashed, done.refused) == (1, 2, 1, [])
    folder = lib / "Telechargements" / "Scalper pack"
    assert (folder / "Scalper" / "Scalper_EURUSD.set").read_bytes() == SET
    assert not (lib / "Telechargements" / "Scalper pack.zip").exists()
    assert len(list(trash.folder.iterdir())) == 1
    # Déjà décompressée : plus proposée ; une 2e fois n'écrase jamais rien.
    assert pack not in service.eligible()


def test_archive_modifiee_jamais_touchee(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    archive = lib / "Telechargements" / "Scalper pack.zip"
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr("ajout.txt", b"modifie apres analyse")
    trash = FakeTrash(tmp_path / "Corbeille")
    pack = rows(ctx)["Scalper pack.zip"].file_id  # type: ignore[attr-defined]
    done = ArchiveService(ctx.conn, ctx.clock, ctx.journal).extract(
        [pack], trash, trash_archive=True
    )
    assert done.extracted == 0 and "modifiée" in done.refused[0][1]
    assert archive.exists() and not (lib / "Telechargements" / "Scalper pack").exists()


def test_option_dans_l_analyse(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    ctx.trash = FakeTrash(tmp_path / "Corbeille")
    SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).add(lib)
    SettingsService(ctx.conn, ctx.journal).set("archives.decompresser", 1)
    results = dict(run_steps(ctx, [s.key for s in STEPS], TaskControl(), lambda _m: None))
    assert "décompressée(s)" in results["Formats et archives"]
    # Les fichiers extraits sont inventoriés et analysés comme les autres.
    extracted = ctx.conn.execute(
        "SELECT count(*) FROM file_record WHERE rel_path LIKE 'Telechargements/Scalper pack/%'"
        " AND presence = 'present'"
    ).fetchone()[0]
    assert extracted == 2
    sets = ctx.conn.execute(
        "SELECT count(*) FROM set_file sf JOIN file_record f ON f.id = sf.file_id"
        " WHERE f.rel_path LIKE 'Telechargements/Scalper pack/%'"
    ).fetchone()[0]
    assert sets == 1
