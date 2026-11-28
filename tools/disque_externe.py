"""Vérification sur un vrai disque externe (CI macOS) : inventaire puis empreintes sur un
volume exFAT ou FAT32 monté, comme un disque « Backup Plus ». Aucune erreur attendue.

Utilisation : python tools/disque_externe.py /Volumes/NOM
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from mtlm.app.context import open_app
from mtlm.app.hashing import HashService
from mtlm.app.inventory import InventoryService
from mtlm.app.scan import ScanService
from mtlm.app.sources import SourceService
from mtlm.core.paths import default_paths


def main(volume: Path) -> int:
    folder = volume / "MQL4" / "Experts" / "Robot Or"
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(50):
        (folder / f"robot_{i}.mq4").write_text(f"int OnTick(){{return {i};}}\n", encoding="utf-8")
        (folder / f"reglage_{i}.set").write_text(f"Lots=0.{i}\n", encoding="utf-8")
    with (
        tempfile.TemporaryDirectory() as home,
        open_app(default_paths({"MTLM_HOME": home})) as ctx,
    ):
        source = SourceService(ctx.conn, ctx.clock, ctx.journal, ctx.paths).add(volume)
        ScanService(ctx.conn, ctx.clock, ctx.journal).scan(source.id)
        summary = HashService(ctx.conn, ctx.clock, ctx.journal).run(source.id)
        causes = InventoryService(ctx.conn).hash_error_summary()
    print(f"empreintes : {summary.hashed} calculées, {summary.errors} erreur(s) ; {causes}")
    return 0 if summary.errors == 0 and summary.hashed >= 100 else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
