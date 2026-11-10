"""Lanceur de l'application empaquetée (PyInstaller)."""

import sys

from mtlm.ui.main import main

if __name__ == "__main__":
    sys.exit(main())
