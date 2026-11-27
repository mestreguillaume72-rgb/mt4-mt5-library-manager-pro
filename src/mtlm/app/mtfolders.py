"""Dossiers MetaTrader **trouvés sur cet ordinateur** (1.8.0), proposés à l'ajout.

Lecture seule de quelques emplacements connus ; rien n'est ajouté sans l'accord de
l'utilisateur.

* Windows : ``%APPDATA%\\MetaQuotes\\Terminal\\<identifiant>\\MQL4|MQL5`` (dossiers de données)
  et les installations ``Program Files\\*\\MQL4|MQL5`` (mode portable) ;
* Mac : MetaTrader 4/5 pour Mac (Wine) :
  ``~/Library/Application Support/net.metaquotes.wine.metatrader4|5/drive_c/…``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

MQL_DIRS = ("MQL4", "MQL5")


def _mql_children(folder: Path) -> list[Path]:
    found = []
    for name in MQL_DIRS:
        candidate = folder / name
        try:
            if candidate.is_dir():
                found.append(candidate)
        except OSError:
            continue
    return found


def _children(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.is_dir())
    except OSError:
        return []


def metatrader_folders(
    environ: dict[str, str] | None = None,
    platform: str | None = None,
    home: Path | None = None,
) -> list[Path]:
    """Dossiers MQL4/MQL5 existants, sans doublon, dans l'ordre trouvé."""
    env = dict(os.environ) if environ is None else environ
    plat = sys.platform if platform is None else platform
    user = Path.home() if home is None else home
    found: list[Path] = []
    if plat == "win32":
        appdata = Path(env.get("APPDATA") or user / "AppData" / "Roaming")
        for terminal in _children(appdata / "MetaQuotes" / "Terminal"):
            found += _mql_children(terminal)
        for key in ("ProgramFiles", "ProgramFiles(x86)"):
            if env.get(key):
                for install in _children(Path(env[key])):
                    found += _mql_children(install)
    elif plat == "darwin":
        support = user / "Library" / "Application Support"
        for bottle in ("net.metaquotes.wine.metatrader4", "net.metaquotes.wine.metatrader5"):
            drive = support / bottle / "drive_c"
            for base in (drive / "Program Files", drive / "Program Files (x86)"):
                for install in _children(base):
                    found += _mql_children(install)
            users = drive / "users"
            for profile in _children(users):
                terminals = profile / "AppData" / "Roaming" / "MetaQuotes" / "Terminal"
                for terminal in _children(terminals):
                    found += _mql_children(terminal)
    return list(dict.fromkeys(found))
