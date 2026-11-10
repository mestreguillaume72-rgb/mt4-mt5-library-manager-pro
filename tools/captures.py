"""Captures d'écran de l'application RÉELLE alimentée par un corpus synthétique FICTIF.

Utilisation : QT_QPA_PLATFORM=offscreen python tools/captures.py DOSSIER_SORTIE
Les captures sont produites sur Linux (rendu Qt hors écran) : l'apparence sur macOS diffère
(polices, style natif). Les données affichées sont fictives et générées pour l'occasion.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication
from tests.synthetic.generate import generate_corpus
from tests.ui.conftest import FakeDialogs

from mtlm.core.paths import default_paths
from mtlm.ui.main import build_window


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    from mtlm.ui.theme import apply_theme

    apply_theme(app)  # type: ignore[arg-type]
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        library = base / "Bibliotheque-FICTIVE"
        generate_corpus(library, seed=2026, n_files=1500)
        dialogs = FakeDialogs()
        window = build_window(default_paths({"MTLM_HOME": str(base / "app")}), dialogs)
        window.resize(1400, 860)
        window.show()
        dialogs.directories.append(library)
        window.pages["sources"].add()
        window.pages["analyse"].start_all()
        while window.app.busy:
            app.processEvents()
            window.app.wait(50)
        app.processEvents()
        for index, (key, page) in enumerate(window.pages.items(), start=1):
            window.navigate(key)
            if key == "explorateur":
                page.search()
            if key in ("sets", "doublons", "familles") and page.findChildren(object):
                table = {"sets": "sets", "doublons": "groups", "familles": "families"}[key]
                getattr(page, table).selectRow(0)
            if key == "detail":
                page.show_item(1)
            app.processEvents()
            window.grab().save(str(out / f"{index:02d}-{key}.png"))
        window.app.ctx.close()
    print(f"Captures enregistrées dans {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
