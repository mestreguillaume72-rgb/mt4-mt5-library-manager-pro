"""Emplacements des données de l'application.

Règle de sécurité : la base, les sauvegardes et les journaux de l'application
sont toujours dans des dossiers propres à l'application, **jamais** dans un
dossier source analysé (ARCHITECTURE § 6, § 7).

La variable d'environnement ``MTLM_HOME`` permet de choisir un autre dossier
(tests, diagnostic). Sinon :

* macOS : ``~/Library/Application Support/MT4MT5LibraryManagerPro`` et
  ``~/Library/Logs/MT4MT5LibraryManagerPro`` ;
* autres systèmes (développement) : ``$XDG_DATA_HOME/mt4mt5-library-manager-pro``.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

MACOS_DIR_NAME = "MT4MT5LibraryManagerPro"
XDG_DIR_NAME = "mt4mt5-library-manager-pro"
DATABASE_FILE_NAME = "library.sqlite"


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path
    logs_dir: Path

    @property
    def database(self) -> Path:
        return self.data_dir / DATABASE_FILE_NAME

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    def ensure(self) -> None:
        """Crée les dossiers de l'application (uniquement les siens) s'ils manquent."""
        for directory in (self.data_dir, self.logs_dir, self.backups_dir):
            directory.mkdir(parents=True, exist_ok=True)


def default_paths(
    environ: dict[str, str] | None = None,
    platform: str | None = None,
    home: Path | None = None,
) -> AppPaths:
    env = dict(os.environ) if environ is None else environ
    plat = sys.platform if platform is None else platform
    user_home = Path.home() if home is None else home

    override = env.get("MTLM_HOME")
    if override:
        root = Path(override).expanduser()
        return AppPaths(data_dir=root / "data", logs_dir=root / "logs")

    if plat == "darwin":
        library = user_home / "Library"
        return AppPaths(
            data_dir=library / "Application Support" / MACOS_DIR_NAME,
            logs_dir=library / "Logs" / MACOS_DIR_NAME,
        )

    xdg = env.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else user_home / ".local" / "share"
    root = base / XDG_DIR_NAME
    return AppPaths(data_dir=root, logs_dir=root / "logs")
