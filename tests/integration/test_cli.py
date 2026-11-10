"""Tests de bout en bout de la commande ``mtlm`` (chaque commande réellement exécutée)."""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pytest

from mtlm.cli.main import EXIT_ERROR, EXIT_OK, EXIT_USAGE, main
from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths


def run(args: list[str], environ: dict[str, str], clock: FixedClock) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(args, environ=environ, clock=clock, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def audit_actions(paths: AppPaths) -> list[str]:
    conn = sqlite3.connect(paths.database)
    try:
        return [r[0] for r in conn.execute("SELECT action FROM audit_event ORDER BY id")]
    finally:
        conn.close()


def test_version(environ: dict[str, str], clock: FixedClock, app_home: Path) -> None:
    code, out, _ = run(["version"], environ, clock)
    assert code == EXIT_OK and "MT4 MT5 Library Manager PRO 0.1.0" in out
    assert not app_home.exists()  # « version » ne crée rien


def test_init_puis_etat(environ: dict[str, str], clock: FixedClock, paths: AppPaths) -> None:
    code, out, _ = run(["init"], environ, clock)
    assert code == EXIT_OK and "Migrations appliquées : 1" in out
    code, out, _ = run(["init"], environ, clock)
    assert code == EXIT_OK and "déjà à jour" in out
    code, out, _ = run(["etat"], environ, clock)
    assert code == EXIT_OK
    assert "Intégrité de la base : OK" in out and "chaîne OK" in out
    assert audit_actions(paths) == ["db.migrate"]
    assert (paths.logs_dir / "mtlm.log").read_text(encoding="utf-8").count("Démarrage") == 3


def test_sauvegarder(environ: dict[str, str], clock: FixedClock, paths: AppPaths) -> None:
    code, out, _ = run(["sauvegarder", "--libelle", "avant-test"], environ, clock)
    assert code == EXIT_OK and "vérifiée" in out
    assert len(list(paths.backups_dir.glob("*-avant-test.sqlite"))) == 1
    assert audit_actions(paths) == ["db.migrate", "db.backup"]


def test_audit_verifier_et_exporter(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock, paths: AppPaths
) -> None:
    run(["init"], environ, clock)
    code, out, _ = run(["audit", "verifier"], environ, clock)
    assert code == EXIT_OK and "intact" in out
    dest = tmp_path / "export.jsonl"
    code, out, _ = run(["audit", "exporter", str(dest)], environ, clock)
    assert code == EXIT_OK and "1 événement(s)" in out
    assert json.loads(dest.read_text(encoding="utf-8"))["action"] == "db.migrate"
    code, _, err = run(["audit", "exporter", str(dest)], environ, clock)
    assert code == EXIT_ERROR and "ne sera pas écrasé" in err
    assert audit_actions(paths) == ["db.migrate", "audit.export"]


def test_audit_altere_detecte(environ: dict[str, str], clock: FixedClock, paths: AppPaths) -> None:
    run(["sauvegarder"], environ, clock)
    conn = sqlite3.connect(paths.database)
    conn.execute("DROP TRIGGER audit_event_no_update")
    conn.execute("UPDATE audit_event SET object = 'x' WHERE id = 2")
    conn.commit()
    conn.close()
    code, _, err = run(["audit", "verifier"], environ, clock)
    assert code == EXIT_ERROR and "ALTÉRÉ à l'événement 2" in err
    code, out, _ = run(["etat"], environ, clock)
    assert code == EXIT_ERROR and "chaîne ERREUR" in out


def test_restaurer_exige_une_confirmation(
    environ: dict[str, str], clock: FixedClock, paths: AppPaths
) -> None:
    run(["sauvegarder"], environ, clock)
    backup = next(paths.backups_dir.glob("*.sqlite"))
    before = paths.database.read_bytes()
    code, _, err = run(["restaurer", str(backup)], environ, clock)
    assert code == EXIT_USAGE and "NON effectuée" in err
    assert paths.database.read_bytes() == before


def test_restaurer_confirme(environ: dict[str, str], clock: FixedClock, paths: AppPaths) -> None:
    # La sauvegarde est prise avant l'inscription de son propre événement « db.backup » :
    # elle contient donc uniquement « db.migrate ».
    run(["sauvegarder", "--libelle", "point"], environ, clock)
    backup = next(paths.backups_dir.glob("*-point.sqlite"))
    clock.advance(1)
    run(["audit", "exporter", str(paths.data_dir / "e.jsonl")], environ, clock)
    clock.advance(1)
    code, out, _ = run(["restaurer", str(backup), "--confirmer"], environ, clock)
    assert code == EXIT_OK and "avant restauration" in out
    # Base revenue à l'état de la sauvegarde, puis restauration journalisée.
    assert audit_actions(paths) == ["db.migrate", "db.restore"]
    assert len(list(paths.backups_dir.glob("*-avant-restauration.sqlite"))) == 1
    code, _, _ = run(["audit", "verifier"], environ, clock)
    assert code == EXIT_OK


def test_restaurer_fichier_invalide(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock
) -> None:
    bogus = tmp_path / "faux.sqlite"
    bogus.write_bytes(b"rien")
    code, _, err = run(["restaurer", str(bogus), "--confirmer"], environ, clock)
    assert code == EXIT_ERROR and "Erreur" in err


@pytest.mark.parametrize("args", [[], ["inconnue"], ["audit"]])
def test_usage_incorrect(args: list[str], environ: dict[str, str], clock: FixedClock) -> None:
    code, _, _ = run(args, environ, clock)
    assert code == EXIT_USAGE


def test_base_trop_recente_signalee(
    environ: dict[str, str], clock: FixedClock, paths: AppPaths
) -> None:
    run(["init"], environ, clock)
    conn = sqlite3.connect(paths.database)
    conn.execute("PRAGMA user_version = 999")
    conn.close()
    code, _, err = run(["etat"], environ, clock)
    assert code == EXIT_ERROR and "version de schéma 999" in err
