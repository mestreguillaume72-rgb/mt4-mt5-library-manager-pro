"""Vérifie le contenu du paquet construit (wheel).

* les migrations SQL sont incluses ;
* aucun fichier de test ni le générateur synthétique (aucune donnée fictive livrée) ;
* aucun fichier MetaTrader ni binaire inattendu.

Utilisation : python tools/check_wheel.py dist/mtlm-*.whl
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import PurePosixPath

REQUIRED = {"mtlm/store/migrations/0001_initial.sql", "mtlm/cli/main.py"}
FORBIDDEN_SUFFIXES = {
    ".ex4",
    ".ex5",
    ".dll",
    ".mq4",
    ".mq5",
    ".mqh",
    ".set",
    ".so",
    ".dylib",
    ".exe",
    ".sqlite",
    ".zip",
}


def check(path: str) -> list[str]:
    problems: list[str] = []
    with zipfile.ZipFile(path) as wheel:
        names = set(wheel.namelist())
    for required in sorted(REQUIRED - names):
        problems.append(f"fichier manquant : {required}")
    for name in sorted(names):
        parts = PurePosixPath(name).parts
        if parts[0] == "tests" or "synthetic" in name or "generate" in parts[-1]:
            problems.append(f"fichier de test embarqué : {name}")
        if PurePosixPath(name).suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(f"fichier interdit embarqué : {name}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage : check_wheel.py FICHIER.whl", file=sys.stderr)
        return 2
    problems = check(argv[0])
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"Contenu du paquet conforme : {argv[0]}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
