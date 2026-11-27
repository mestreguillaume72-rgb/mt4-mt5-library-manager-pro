"""Génère le jeu d'icônes macOS (dossier .iconset) à partir du dessin de l'application.

Utilisation : QT_QPA_PLATFORM=offscreen python tools/icone.py packaging/macos/AppIcon.iconset
puis (sur macOS) : iconutil -c icns packaging/macos/AppIcon.iconset -o packaging/macos/AppIcon.icns
Windows : python tools/icone.py packaging/windows/AppIcon.ico (une icône .ico 256 px).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication

from mtlm.ui.theme import icon_pixmap

SIZES = [16, 32, 128, 256, 512]


def main(out: Path) -> int:
    _app = QGuiApplication.instance() or QGuiApplication([])
    if out.suffix.lower() == ".ico":
        out.parent.mkdir(parents=True, exist_ok=True)
        if not icon_pixmap(256).save(str(out), "ICO"):
            print("Écriture de l'icône .ico impossible")
            return 1
        print(f"Icône écrite : {out}")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        icon_pixmap(size).save(str(out / f"icon_{size}x{size}.png"))
        icon_pixmap(size * 2).save(str(out / f"icon_{size}x{size}@2x.png"))
    print(f"{len(SIZES) * 2} images écrites dans {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
