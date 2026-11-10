"""Invariant « sources inchangées » (PLAN_DE_TESTS § 5) — version Phase 1.

En Phase 1, aucun moteur ne lit encore les sources. Ce test établit la référence :
il exécute toutes les commandes existantes avec un corpus présent sur le disque et
vérifie qu'aucun octet ni aucune métadonnée du corpus n'a changé. Il sera étendu à
chaque phase avec les nouveaux moteurs (scan, hash, archives…).
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

PHASE1_COMMANDS: list[list[str]] = [
    ["version"],
    ["init"],
    ["etat"],
    ["sauvegarder"],
    ["audit", "verifier"],
]


def run_all_commands(environ: dict[str, str], clock: FixedClock, export_dir: Path) -> None:
    for args in [*PHASE1_COMMANDS, ["audit", "exporter", str(export_dir / "audit.jsonl")]]:
        code = main(args, environ=environ, clock=clock, out=io.StringIO(), err=io.StringIO())
        assert code == EXIT_OK, args


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


def test_commandes_phase1_ne_touchent_pas_les_sources(
    tmp_path: Path, environ: dict[str, str], clock: FixedClock
) -> None:
    corpus = tmp_path / "corpus"
    generate_corpus(corpus, seed=11, n_files=2000)
    before = take_snapshot(corpus)
    run_all_commands(environ, clock, tmp_path)
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
    run_all_commands(environ, clock, tmp_path)
    after = take_snapshot(corpus)
    files = sum(1 for state in after.values() if state.kind == "file")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mib = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024  # octets vs Kio
    print(
        f"\n[charge {n_files}] génération {generated - started:.1f}s ; "
        f"instantané {snap - generated:.1f}s ; fichiers {files} ; "
        f"octets {sum(e.size for e in manifest.entries)} ; RAM max processus {rss_mib:.0f} Mio"
    )
    assert files == n_files == len(manifest.entries)
    assert diff_snapshots(before, after) == []
