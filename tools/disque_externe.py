"""Vérification sur un vrai disque externe (CI macOS) : volume exFAT ou FAT32 monté, comme
un disque « Backup Plus ». Aucune erreur d'empreinte attendue, même si le disque est
débranché puis rebranché entre l'inventaire et les empreintes.

Utilisation : python tools/disque_externe.py VOLUME DOSSIER_APPLI inventaire|empreintes
"""

from __future__ import annotations

import sys
from pathlib import Path

from mtlm.app.context import open_app
from mtlm.app.hashing import HashService
from mtlm.app.inventory import InventoryService
from mtlm.app.scan import ScanService
from mtlm.app.sources import SourceService
from mtlm.core.paths import default_paths


def main(volume: Path, home: Path, phase: str) -> int:
    with open_app(default_paths({"MTLM_HOME": str(home)})) as ctx:
        sources = SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
        if phase == "inventaire":
            folder = volume / "MQL4" / "Experts" / "Robot Or"
            folder.mkdir(parents=True, exist_ok=True)
            for i in range(50):
                (folder / f"robot_{i}.mq4").write_text(f"int OnTick(){{return {i};}}\n")
                (folder / f"reglage_{i}.set").write_text(f"Lots=0.{i}\n")
            source = sources.add(volume)
            ScanService(ctx.conn, ctx.clock, ctx.journal).scan(source.id)
            print("inventaire fait")
            return 0
        source = sources.list()[0]
        summary = HashService(ctx.conn, ctx.clock, ctx.journal).run(source.id)
        causes = InventoryService(ctx.conn).hash_error_summary()
    print(f"empreintes : {summary.hashed} calculées, {summary.errors} erreur(s) ; {causes}")
    return 0 if summary.errors == 0 and summary.hashed >= 100 else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]))
