"""Mesure de performance (F12) : l'application SEULE sur un corpus synthétique fictif.

Étapes : génération du corpus (processus séparé, non mesuré), puis dans un processus neuf :
pipeline complet étape par étape, latence des recherches de l'explorateur, temps
d'ouverture/reprise après fermeture brutale, mémoire maximale du processus de l'application.

Utilisation : PYTHONPATH=. python tools/mesure_performance.py 50000 [100000 …]
"""

from __future__ import annotations

import json
import os
import platform
import resource
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

MEASURE = r"""
import json, resource, sys, time
from pathlib import Path
from mtlm.app.context import open_app
from mtlm.app.inventory import FileFilter, InventoryService
from mtlm.app.pipeline import STEPS
from mtlm.app.sources import SourceService
from mtlm.core.control import TaskControl
from mtlm.core.paths import default_paths

library, home = Path(sys.argv[1]), sys.argv[2]
paths = default_paths({"MTLM_HOME": home})
result = {"etapes": {}, "recherches_ms": {}}
with open_app(paths) as ctx:
    SourceService(ctx.conn, ctx.clock, ctx.journal, paths).add(library)
    for step in STEPS:
        t = time.perf_counter()
        step.run(ctx, TaskControl(), lambda _m: None)
        result["etapes"][step.label] = round(time.perf_counter() - t, 2)
    t = time.perf_counter()
    STEPS[0].run(ctx, TaskControl(), lambda _m: None)
    result["etapes"]["Ré-inventaire sans changement"] = round(time.perf_counter() - t, 2)
    inv = InventoryService(ctx.conn)
    for label, flt in (("premiere page", FileFilter()),
                       ("filtre extension", FileFilter(extensions=("mq4", "ex4"))),
                       ("filtre type", FileFilter(detected_type="ea")),
                       ("recherche texte", FileFilter(text="robot")),
                       ("filtres combines", FileFilter(extensions=("set",), text="eurusd",
                                                       platform="mt4"))):
        t = time.perf_counter()
        inv.count(flt)
        inv.page(flt, limit=500)
        result["recherches_ms"][label] = round((time.perf_counter() - t) * 1000, 1)
    # Fermeture brutale simulée : une tâche laissée « en cours ».
    from mtlm.app.jobs import JobStore
    JobStore(ctx.conn, ctx.clock).create("hash", {})
t = time.perf_counter()
with open_app(paths) as ctx:
    interrupted = ctx.conn.execute(
        "SELECT count(*) FROM job WHERE state = 'interrupted'").fetchone()[0]
    t_open = time.perf_counter() - t
    t2 = time.perf_counter()
    STEPS[1].run(ctx, TaskControl(), lambda _m: None)   # reprise des empreintes
    t_resume = time.perf_counter() - t2
result["reprise"] = {"ouverture_s": round(t_open, 2), "taches_interrompues": interrupted,
                     "reprise_empreintes_s": round(t_resume, 2)}
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
result["ram_max_mio"] = round(rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024)
print(json.dumps(result))
"""


def run(n_files: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="mtlm-perf-") as tmp:
        library = Path(tmp) / "bibliotheque-fictive"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.synthetic.generate",
                "--seed",
                "2026",
                "--files",
                str(n_files),
                "--profile",
                "tiny",
                "--out",
                str(library),
                "--manifest",
                str(Path(tmp) / "manifeste.json"),
            ],
            check=True,
            capture_output=True,
        )
        started = time.perf_counter()
        output = subprocess.run(
            [sys.executable, "-c", MEASURE, str(library), str(Path(tmp) / "app")],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(Path.cwd())},
        )
        data: dict[str, object] = json.loads(output.stdout.strip().splitlines()[-1])
        data["total_s"] = round(time.perf_counter() - started, 1)
        data["fichiers"] = n_files
        return data


def main(sizes: list[int]) -> int:
    print(
        f"Mesure du {datetime.now(UTC):%Y-%m-%d %H:%M} UTC — {platform.platform()} — "
        f"Python {platform.python_version()} — {os.cpu_count()} cœurs"
    )
    for size in sizes:
        print(json.dumps(run(size), ensure_ascii=False))
    _ = resource
    return 0


if __name__ == "__main__":
    sys.exit(main([int(a) for a in sys.argv[1:]] or [50_000]))
