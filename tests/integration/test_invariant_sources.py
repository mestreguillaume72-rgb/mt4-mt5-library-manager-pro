"""Invariant « sources inchangées » (PLAN_DE_TESTS § 5, spécification § 1 et F1).

Exécute toutes les commandes existantes — dont celles qui LISENT la source — sur un corpus
présent sur le disque, puis vérifie qu'aucun octet ni aucune métadonnée du corpus n'a
changé et qu'aucun fichier n'y a été créé. Étendu à chaque phase avec les nouveaux moteurs.
"""

from __future__ import annotations

import io
import resource
import sys
import time
from pathlib import Path

import pytest

from mtlm.cli.main import EXIT_OK, main
from mtlm.core.clock import FixedClock
from tests.support.fs_snapshot import diff_snapshots, take_snapshot
from tests.synthetic.generate import generate_corpus


def all_commands(corpus: Path, export_dir: Path) -> list[list[str]]:
    return [
        ["version"],
        ["init"],
        ["etat"],
        ["sauvegarder"],
        ["audit", "verifier"],
        ["source", "ajouter", str(corpus)],
        ["source", "lister"],
        ["scanner"],
        ["scanner"],  # inventaire initial puis incrémental
        ["inventaire"],
        ["fichiers", "--limite", "10"],
        ["taches"],
        ["erreurs", "1"],
        ["audit", "exporter", str(export_dir / "audit.jsonl")],
    ]


def run_all_commands(
    environ: dict[str, str], clock: FixedClock, corpus: Path, export_dir: Path
) -> dict[str, float]:
    """Exécute toutes les commandes ; retourne la durée cumulée par commande."""
    durations: dict[str, float] = {}
    for args in all_commands(corpus, export_dir):
        started = time.perf_counter()
        code = main(args, environ=environ, clock=clock, out=io.StringIO(), err=io.StringIO())
        assert code == EXIT_OK, args
        durations[args[0]] = durations.get(args[0], 0.0) + time.perf_counter() - started
    return durations


def test_snapshot_detecte_les_changements(tmp_path: Path) -> None:
    root = tmp_path / "c"
    generate_corpus(root, seed=1, n_files=50)
    before = take_snapshot(root)
    victim = next(p for p in root.rglob("*") if p.is_file() and p.stat().st_size > 0)
    victim.write_bytes(victim.read_bytes()[:-1] + b"!")
    (root / "nouveau.txt").write_bytes(b"x")
    problems = diff_snapshots(before, take_snapshot(root))
    assert any(p.startswith("modifié") for p in problems)
    assert any(p.startswith("créé") for p in problems)


def test_commandes_ne_touchent_pas_les_sources(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock
) -> None:
    corpus = tmp_path / "corpus"
    generate_corpus(corpus, seed=11, n_files=2000)
    before = take_snapshot(corpus)
    run_all_commands(environ, clock, corpus, tmp_path)
    assert diff_snapshots(before, take_snapshot(corpus)) == []


@pytest.mark.slow
@pytest.mark.parametrize("n_files", [50_000, 100_000])
def test_charge_corpus_et_invariant(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock, n_files: int
) -> None:
    corpus = tmp_path / "corpus"
    started = time.perf_counter()
    manifest = generate_corpus(corpus, seed=2026, n_files=n_files, size_profile="tiny")
    generated = time.perf_counter()
    before = take_snapshot(corpus)
    snap = time.perf_counter()
    durations = run_all_commands(environ, clock, corpus, tmp_path)
    after = take_snapshot(corpus)
    files = sum(1 for state in after.values() if state.kind == "file")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mib = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024  # octets / Kio
    print(
        f"\n[charge {n_files}] génération {generated - started:.1f}s ; "
        f"instantané {snap - generated:.1f}s ; fichiers {files} ; "
        f"octets {sum(e.size for e in manifest.entries)} ; "
        f"2 inventaires (initial + incrémental) {durations['scanner']:.1f}s ; "
        f"RAM max processus {rss_mib:.0f} Mio"
    )
    assert files == n_files == len(manifest.entries)
    assert diff_snapshots(before, after) == []
