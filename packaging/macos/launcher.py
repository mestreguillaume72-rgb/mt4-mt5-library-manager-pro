"""Lanceur de l'application empaquetée (PyInstaller)."""

import os
import sys

# Application fenêtrée (Windows) : pas de console, sys.stdout/sys.stderr valent None ; tout
# message (journalisation, avertissement) échouerait. On les dirige vers « nul ».
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115, PTH123

from mtlm.ui.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
