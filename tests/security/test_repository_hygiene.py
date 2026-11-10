"""Le dépôt ne doit contenir aucune donnée MetaTrader réelle (spécification § 9)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_SUFFIXES = {
    ".ex4",
    ".ex5",
    ".dll",
    ".mq4",
    ".mq5",
    ".mqh",
    ".set",
    ".hst",
    ".hcc",
    ".zip",
    ".rar",
    ".7z",
    ".exe",
    ".sqlite",
}


def tracked_files() -> list[str]:
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("dépôt Git indisponible")
    result = subprocess.run([git, "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [p for p in result.stdout.decode("utf-8").split("\0") if p]


def test_aucun_fichier_metatrader_ni_binaire_versionne() -> None:
    offending = [p for p in tracked_files() if Path(p).suffix.lower() in FORBIDDEN_SUFFIXES]
    assert offending == []


def test_gitignore_protege_les_extensions_metatrader() -> None:
    content = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for suffix in (".ex4", ".ex5", ".dll", ".mq4", ".mq5", ".set"):
        assert f"*{suffix}" in content


def test_generateur_synthetique_hors_du_paquet() -> None:
    package = ROOT / "src" / "mtlm"
    assert not list(package.rglob("*synthetic*"))
    assert not list(package.rglob("generate*.py"))
