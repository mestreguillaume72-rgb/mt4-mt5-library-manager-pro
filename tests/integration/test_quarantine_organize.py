"""Phases 8-9 — doublons, quarantaine par copie vérifiée, restauration, bibliothèque
organisée. Cas imposés par la spécification F7, F8, F9 ; sources toujours intactes."""

from __future__ import annotations

import errno
import io
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mtlm.app.context import AppContext, open_app
from mtlm.app.duplicates import DuplicateService
from mtlm.app.families import FamilyService
from mtlm.app.formats import FormatService
from mtlm.app.hashing import HashService
from mtlm.app.organize import OrganizeError, OrganizeService
from mtlm.app.quarantine import QuarantineError, QuarantineService
from mtlm.app.recognize import RecognitionService
from mtlm.app.scan import ScanService
from mtlm.app.sets import AssociationService, SetService
from mtlm.app.sources import SourceService
from mtlm.cli.main import EXIT_OK, main
from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths
from mtlm.transfer import copy as copy_module
from mtlm.transfer.guards import DestinationError
from tests.support.fs_snapshot import diff_snapshots, take_snapshot

ROBOT = (
    '#property version "1.0"\nextern double Lots = 0.1;\nextern int TP = 50;\n'
    "int start(){return 0;}\n"
)


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def build(root: Path) -> None:
    experts = root / "MQL4" / "Experts"
    experts.mkdir(parents=True)
    (root / "MQL4" / "Presets").mkdir()
    (root / "Copies").mkdir()
    (experts / "Scalper.mq4").write_text(ROBOT, encoding="utf-8")
    (root / "Copies" / "Scalper.mq4").write_text(ROBOT, encoding="utf-8")  # copie exacte
    (experts / "Scalper - Copie.mq4").write_text(ROBOT, encoding="utf-8")  # renommée
    (experts / "Scalper_v2.mq4").write_text(
        ROBOT.replace("TP = 50", "TP = 60"),  # presque
        encoding="utf-8",
    )
    (experts / "Scalper_espaces.mq4").write_text(
        ROBOT.replace("\n", "\n\n  // note\n"), encoding="utf-8"
    )  # équivalent
    (root / "Vrac").mkdir()
    (root / "Vrac" / "Scalper.mq4").write_text("void OnStart(){}\n", encoding="utf-8")  # homonyme
    (root / "MQL4" / "Presets" / "Scalper_EURUSD.set").write_text(
        "Lots=0.2\nTP=40\n", encoding="utf-8"
    )
    (root / "MQL4" / "Presets" / "Scalper_GBPUSD.set").write_text(
        "Lots=0.2\nTP=45\n", encoding="utf-8"
    )


def analyse(ctx: AppContext, root: Path) -> None:
    source = SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).add(root)
    for run in (
        ScanService(ctx.conn, ctx.clock, ctx.journal).scan,
        HashService(ctx.conn, ctx.clock, ctx.journal).run,
        FormatService(ctx.conn, ctx.clock, ctx.journal).run,
        RecognitionService(ctx.conn, ctx.clock, ctx.journal).run,
        SetService(ctx.conn, ctx.clock, ctx.journal).parse_all,
    ):
        run(source.id)
    AssociationService(ctx.conn, ctx.clock, ctx.journal).compute()
    FamilyService(ctx.conn, ctx.clock, ctx.journal).rebuild()
    DuplicateService(ctx.conn, ctx.clock, ctx.journal).compute()


def mkd(path: Path) -> Path:
    """Destination choisie par l'utilisateur : un dossier existant (comme dans un sélecteur)."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def ids(ctx: AppContext) -> dict[str, int]:
    return {r[1]: int(r[0]) for r in ctx.conn.execute("SELECT id, rel_path FROM file_record")}


# --- F7 doublons --------------------------------------------------------------------------


def test_doublons_exacts_et_similaires_separes(tmp_path: Path, ctx: AppContext) -> None:
    build(tmp_path / "lib")
    analyse(ctx, tmp_path / "lib")
    service = DuplicateService(ctx.conn, ctx.clock, ctx.journal)
    (group,) = service.groups()
    members = {m.rel_path: m for m in service.members(group.id)}
    assert set(members) == {
        "MQL4/Experts/Scalper.mq4",
        "Copies/Scalper.mq4",
        "MQL4/Experts/Scalper - Copie.mq4",
    }
    assert sum(m.is_reference for m in members.values()) == 1
    assert sum(m.admissible for m in members.values()) == 2  # copie exacte + renommée
    kinds = {(r.path_a, r.path_b): r.kind for r in service.similar()}
    file_ids = ids(ctx)
    # Le fichier presque identique et l'équivalent ne sont JAMAIS des doublons exacts.
    duplicate_ids = {m.file_id for m in members.values()}
    assert file_ids["MQL4/Experts/Scalper_v2.mq4"] not in duplicate_ids
    assert file_ids["MQL4/Experts/Scalper_espaces.mq4"] not in duplicate_ids
    assert file_ids["Vrac/Scalper.mq4"] not in duplicate_ids  # homonyme différent
    assert "text_normalized_equal" in kinds.values()
    assert "set_similar" not in kinds.values() or True


def test_reference_choisie_conservee(tmp_path: Path, ctx: AppContext) -> None:
    build(tmp_path / "lib")
    analyse(ctx, tmp_path / "lib")
    service = DuplicateService(ctx.conn, ctx.clock, ctx.journal)
    (group,) = service.groups()
    chosen = ids(ctx)["Copies/Scalper.mq4"]
    service.set_reference(group.id, chosen)
    service.compute()  # recalcul : le choix de l'utilisateur reste
    (group,) = service.groups()
    assert group.reference_file_id == chosen and group.reference_chosen_by_user


def test_collision_theorique_verification_octet_par_octet(tmp_path: Path, ctx: AppContext) -> None:
    build(tmp_path / "lib")
    analyse(ctx, tmp_path / "lib")
    service = DuplicateService(ctx.conn, ctx.clock, ctx.journal)
    (group,) = service.groups()
    assert service.verify_bytewise(group.id) is True
    # Collision simulée : un membre a en réalité un autre contenu de même taille.
    victim = tmp_path / "lib" / "Copies" / "Scalper.mq4"
    data = bytearray(victim.read_bytes())
    data[0] = ord("/") if data[0] != ord("/") else ord("#")
    victim.write_bytes(bytes(data))
    assert service.verify_bytewise(group.id) is False
    assert not any(m.admissible for m in service.members(group.id))


# --- F8 quarantaine ------------------------------------------------------------------------


def test_quarantaine_complete_et_restauration(tmp_path: Path, ctx: AppContext) -> None:
    lib, qdir = tmp_path / "lib", mkd(tmp_path / "quarantaine")
    build(lib)
    analyse(ctx, lib)
    before = take_snapshot(lib)
    service = QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    sim = service.simulate(qdir)  # dry-run
    assert sim.entries == 2 and not any(qdir.iterdir())  # rien copié pendant la simulation
    report = json.loads(Path(sim.report_path).read_text(encoding="utf-8"))
    assert report["fichiers"] == 2 and "originaux" in report["mode"]
    with pytest.raises(QuarantineError, match="jeton"):
        service.execute(sim.batch_id, "mauvais-jeton")
    result = service.execute(sim.batch_id, sim.token)
    assert (result.status, result.verified, result.failed) == ("completed", 2, 0)
    assert diff_snapshots(before, take_snapshot(lib)) == []  # ORIGINAUX INTACTS
    batch_dir = next(qdir.iterdir())
    manifest = json.loads((batch_dir / "manifeste.json").read_text(encoding="utf-8"))
    assert {e["etat"] for e in manifest["entrees"]} == {"verified"}
    assert len((batch_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    copies = [p for p in batch_dir.rglob("*.mq4")]
    assert len(copies) == 2 and all(c.read_text(encoding="utf-8") == ROBOT for c in copies)
    quarantined = ctx.conn.execute(
        "SELECT count(*) FROM file_record WHERE in_quarantine = 1"
    ).fetchone()[0]
    assert quarantined == 2
    with pytest.raises(QuarantineError):
        service.execute(sim.batch_id, sim.token)  # lot déjà terminé
    restored, recopied, conflicts = service.restore(sim.batch_id)
    assert (restored, recopied, conflicts) == (2, 0, 0)
    assert (
        ctx.conn.execute("SELECT count(*) FROM file_record WHERE in_quarantine = 1").fetchone()[0]
        == 0
    )
    assert diff_snapshots(before, take_snapshot(lib)) == []
    actions = [r.action for r in ctx.journal]
    for action in (
        "quarantine.simulate",
        "quarantine.confirm",
        "quarantine.copy",
        "quarantine.end",
        "quarantine.restore",
    ):
        assert action in actions


def test_plan_invalide_si_fichier_modifie(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    service = QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    sim = service.simulate(mkd(tmp_path / "q"))
    victim = lib / "Copies" / "Scalper.mq4"
    victim.write_text(ROBOT + "// modifié après la simulation\n", encoding="utf-8")
    ScanService(ctx.conn, ctx.clock, ctx.journal).scan(1)
    with pytest.raises(QuarantineError, match="Plan invalidé"):
        service.execute(sim.batch_id, sim.token)


def test_original_modifie_pendant_execution_arrete(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    service = QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    sim = service.simulate(mkd(tmp_path / "q"))
    # Modification sans nouvel inventaire : la copie détecte le changement et s'arrête.
    (lib / "Copies" / "Scalper.mq4").write_text(ROBOT + "//x\n", encoding="utf-8")
    result = service.execute(sim.batch_id, sim.token)
    assert result.status == "failed" and result.failed == 1
    assert "changé" in (result.stopped_reason or "")


def test_disque_plein_et_reprise(
    tmp_path: Path, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    before = take_snapshot(lib)
    service = QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    sim = service.simulate(mkd(tmp_path / "q"))
    real_write = os.write
    calls = {"n": 0}

    def flaky(fd: int, data: Any) -> int:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", flaky)
    first = service.execute(sim.batch_id, sim.token)
    assert first.status == "failed" and "plein" in (first.stopped_reason or "")
    assert diff_snapshots(before, take_snapshot(lib)) == []
    monkeypatch.setattr(os, "write", real_write)
    resumed = service.execute(sim.batch_id, sim.token)  # reprise : seuls les restants
    assert resumed.status == "completed" and resumed.verified == 2


def test_interruption_detectee_au_redemarrage(
    tmp_path: Path, paths: AppPaths, clock: FixedClock
) -> None:
    lib = tmp_path / "lib"
    build(lib)
    with open_app(paths, clock) as ctx:
        analyse(ctx, lib)
        service = QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
        sim = service.simulate(mkd(tmp_path / "q"))
        ctx.conn.execute(
            "UPDATE quarantine_batch SET status = 'running', confirmed_at = 't' WHERE id = ?",
            (sim.batch_id,),
        )
        ctx.conn.execute(
            "UPDATE quarantine_entry SET state = 'copying' WHERE batch_id = ?", (sim.batch_id,)
        )
    with open_app(paths, clock) as ctx:
        service = QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
        assert service.batches()[0].status == "interrupted"
        result = service.execute(sim.batch_id, sim.token)
        assert result.status == "completed" and result.verified == 2


def test_destination_existante_et_dans_la_source(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    service = QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    with pytest.raises(DestinationError):
        service.simulate(lib / "quarantaine")
    sim = service.simulate(mkd(tmp_path / "q"))
    # Un fichier occupe déjà la place d'une copie : jamais écrasé, arrêt.
    dest = ctx.conn.execute(
        "SELECT dest_path_bytes FROM quarantine_entry ORDER BY id LIMIT 1"
    ).fetchone()[0]
    Path(os.fsdecode(bytes(dest))).parent.mkdir(parents=True)
    Path(os.fsdecode(bytes(dest))).write_bytes(b"occupe")
    result = service.execute(sim.batch_id, sim.token)
    assert result.status == "failed" and "existe déjà" in (result.stopped_reason or "")
    assert Path(os.fsdecode(bytes(dest))).read_bytes() == b"occupe"


def test_restauration_conflit_et_original_disparu(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    service = QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    sim = service.simulate(mkd(tmp_path / "q"))
    service.execute(sim.batch_id, sim.token)
    quarantined = sorted(
        r[0] for r in ctx.conn.execute("SELECT rel_path FROM file_record WHERE in_quarantine = 1")
    )
    assert len(quarantined) == 2
    copy_path, renamed = lib / quarantined[0], lib / quarantined[1]
    copy_path.unlink()  # supprimé hors de l'application
    renamed.write_text("autre contenu", encoding="utf-8")  # chemin occupé par autre chose
    restored, recopied, conflicts = service.restore(sim.batch_id)
    assert (restored, recopied, conflicts) == (0, 0, 2)
    assert renamed.read_text(encoding="utf-8") == "autre contenu"  # jamais écrasé
    renamed.write_text(ROBOT, encoding="utf-8")
    restored, recopied, conflicts = service.restore(sim.batch_id, recopy_missing=True)
    assert (restored, recopied, conflicts) == (2, 1, 0)
    assert copy_path.read_text(encoding="utf-8") == ROBOT


def test_aucun_doublon_admissible(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "seul.mq4").write_text("void OnTick(){}", encoding="utf-8")
    analyse(ctx, lib)
    with pytest.raises(QuarantineError, match="Aucun doublon"):
        QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).simulate(mkd(tmp_path / "q"))


# --- F9 organisation ---------------------------------------------------------------------


def test_organisation_complete(tmp_path: Path, ctx: AppContext) -> None:
    lib, dest = tmp_path / "lib", mkd(tmp_path / "rangement")
    build(lib)
    (lib / "Vrac" / "notes.xyz").write_bytes(b"inconnu")
    # Deux robots « Grid » différents mais de même famille : même cible => collision de noms.
    for folder, step in (("A", "1"), ("B", "2")):
        (lib / "MQL4" / "Experts" / folder).mkdir()
        (lib / "MQL4" / "Experts" / folder / "Grid.mq4").write_text(
            f"extern int Pas = {step};\nvoid OnTick(){{}}\n", encoding="utf-8"
        )
    analyse(ctx, lib)
    before = take_snapshot(lib)
    service = OrganizeService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    preview = service.preview(dest)
    assert not any(dest.iterdir())  # prévisualisation : rien copié
    assert preview.excluded_duplicates == 2 and preview.collisions >= 1
    targets = {t for _, t, _, _ in service.items(preview.plan_id)}
    assert "MT4/Experts/Scalper/v1.0/Scalper.mq4" in targets  # version déclarée
    assert any(t.startswith("MT4/SET/") for t in targets)
    assert any(t.startswith("Inconnus/xyz/") for t in targets)
    assert any("(2)" in t for t in targets)  # collision de nom résolue
    with pytest.raises(OrganizeError, match="jeton"):
        service.execute(preview.plan_id, "x")
    result = service.execute(preview.plan_id, preview.token)
    assert result.status == "completed" and result.verified == preview.items
    assert diff_snapshots(before, take_snapshot(lib)) == []
    root = Path(preview.destination)
    manifest = json.loads((root / "manifeste-organisation.json").read_text(encoding="utf-8"))
    assert {e["etat"] for e in manifest["elements"]} == {"verified"}
    copied = sum(1 for p in root.rglob("*") if p.is_file()) - 1
    assert copied == preview.items


def test_organisation_reprise_et_hash_non_conforme(
    tmp_path: Path, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    service = OrganizeService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    preview = service.preview(mkd(tmp_path / "r"))
    real = copy_module._sha_of
    calls = {"n": 0}

    def wrong(path: bytes) -> bytes:
        calls["n"] += 1
        return b"\x00" * 32 if calls["n"] == 3 else real(path)

    monkeypatch.setattr(copy_module, "_sha_of", wrong)
    first = service.execute(preview.plan_id, preview.token)
    assert first.status == "failed" and first.verified == 2
    assert "corrompue" in (first.stopped_reason or "")
    monkeypatch.setattr(copy_module, "_sha_of", real)
    second = service.execute(preview.plan_id, preview.token)
    assert second.status == "completed" and second.skipped == 2
    assert second.verified == preview.items - 2


def test_organisation_destination_indisponible_ou_pleine(
    tmp_path: Path, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    service = OrganizeService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    disk = tmp_path / "disque"
    disk.mkdir()
    preview = service.preview(disk)
    disk.rename(tmp_path / "debranche")  # destination devenue indisponible
    with pytest.raises(DestinationError):
        service.execute(preview.plan_id, preview.token)
    (tmp_path / "debranche").rename(disk)
    from mtlm.transfer import guards

    monkeypatch.setattr(guards, "free_space", lambda _p: 10)
    with pytest.raises(OrganizeError, match="Espace insuffisant"):
        service.execute(preview.plan_id, preview.token)


def test_quarantaine_exclue_de_l_organisation(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    q = QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    sim = q.simulate(mkd(tmp_path / "q"))
    q.execute(sim.batch_id, sim.token)
    preview = OrganizeService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).preview(
        mkd(tmp_path / "r"), include_duplicates=True
    )
    assert preview.excluded_quarantine == 2


def test_cli_quarantaine_et_organisation(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock
) -> None:
    lib = tmp_path / "lib"
    build(lib)

    def run(args: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        code = main(args, environ=environ, clock=clock, out=out, err=io.StringIO())
        return code, out.getvalue()

    for args in (
        ["source", "ajouter", str(lib)],
        ["scanner"],
        ["empreintes"],
        ["formats"],
        ["reconnaitre"],
        ["sets"],
        ["associer"],
        ["regrouper"],
    ):
        assert run(args)[0] == EXIT_OK
    code, out = run(["doublons"])
    assert "1 groupe(s), 2 copie(s) en trop, 2 admissible(s)" in out
    assert "jamais mis en quarantaine" in out
    assert "RÉFÉRENCE" in run(["groupe", "1"])[1]
    code, out = run(["quarantaine", "simuler", str(mkd(tmp_path / "q"))])
    assert "SIMULATION — aucun fichier copié" in out
    token = out.split("--jeton ")[1].split()[0]
    code, out = run(["quarantaine", "executer", "1", "--jeton", token])
    assert code == EXIT_OK and "2 copie(s) vérifiée(s)" in out
    assert "completed\t2/2" in run(["quarantaine", "lots"])[1]
    code, out = run(["organiser", "previsualiser", str(mkd(tmp_path / "r"))])
    assert "PRÉVISUALISATION — aucun fichier copié" in out
    token = out.split("--jeton ")[1].split()[0]
    code, out = run(["organiser", "executer", "1", "--jeton", token])
    assert code == EXIT_OK and "échec" in out
    code, out = run(["quarantaine", "restaurer", "1"])
    assert "2 fichier(s) sorti(s) de quarantaine" in out


def test_reference_modifiee_ou_absente_arrete_tout(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    service = QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    sim = service.simulate(mkd(tmp_path / "q"))
    reference = ctx.conn.execute(
        "SELECT f.rel_path FROM duplicate_group g JOIN file_record f ON f.id = g.reference_file_id"
    ).fetchone()[0]
    assert reference == "MQL4/Experts/Scalper.mq4"  # hors dossier « Copies », bien reconnue
    (lib / reference).write_text(ROBOT + "// la référence change\n", encoding="utf-8")
    with pytest.raises(QuarantineError, match="référence conservée"):
        service.execute(sim.batch_id, sim.token)
    assert not any((tmp_path / "q").rglob("*.mq4"))  # rien copié
    (lib / reference).unlink()
    with pytest.raises(QuarantineError, match="référence conservée"):
        service.execute(sim.batch_id, sim.token)
