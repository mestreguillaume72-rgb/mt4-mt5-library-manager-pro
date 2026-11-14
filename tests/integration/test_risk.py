"""1.5.0 — fichiers à risque : signes repérés en lisant seulement (pas un antivirus)."""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.context import AppContext, open_app
from mtlm.app.risk import RiskService
from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths
from mtlm.metatrader.risk import scan_binary, scan_source
from tests.integration.test_quarantine_organize import analyse

DANGEROUS = (
    '#import "urlmon.dll"\nint URLDownloadToFileW(int a, string b, string c, int d, int e);\n'
    '#import\n#import "shell32.dll"\nint ShellExecuteW(int h, string o, string f, string p,'
    " string d, int s);\n#import\nint start(){ return 0; }\n"
)
HONEST = (
    "input int Period = 14;\n"
    'int OnInit(){ string r; WebRequest("GET", "https://x", "", 5, r); return 0; }\n'
)
CLEAN = "extern double Lots = 0.1;\nint start(){ return 0; }\n"


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


def test_regles_source_et_binaire() -> None:
    levels = {f.reason.split(" :")[0]: f.level for f in scan_source(DANGEROUS)}
    assert levels["URLDownloadToFile"] == "élevé" and levels["ShellExecute"] == "élevé"
    assert any("urlmon.dll" in f.reason for f in scan_source(DANGEROUS))
    assert [f.level for f in scan_source(HONEST)] == ["info"]  # WebRequest : information
    assert scan_source(CLEAN) == []
    blob = b"\x00\x01EX4\x00wininet.dll\x00InternetOpenUrlA\x00" + "DeleteFileW".encode("utf-16-le")
    reasons = " ; ".join(f.reason for f in scan_binary(blob))
    assert "InternetOpenUrl" in reasons and "DeleteFile" in reasons and "wininet.dll" in reasons


def test_bibliotheque_avec_signes(tmp_path: Path, ctx: AppContext) -> None:
    lib = tmp_path / "lib"
    (lib / "MQL4" / "Experts").mkdir(parents=True)
    (lib / "MQL4" / "Experts" / "Pirate.mq4").write_text(DANGEROUS, encoding="utf-8")
    (lib / "MQL4" / "Experts" / "Propre.mq4").write_text(CLEAN, encoding="utf-8")
    (lib / "MQL4" / "Libraries").mkdir()
    (lib / "MQL4" / "Libraries" / "Outil.dll").write_bytes(b"MZ\x90\x00" + b"\x00" * 60)
    (lib / "Setup.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 60)
    (lib / "facture.pdf").write_bytes(b"MZ\x90\x00" + b"\x00" * 60)  # programme déguisé
    with zipfile.ZipFile(lib / "bonus.zip", "w") as z:
        z.writestr("installer.bat", b"@echo off")
    analyse(ctx, lib)
    rows = {r.rel_path: r for r in RiskService(ctx.conn).scan()}
    assert rows["MQL4/Experts/Pirate.mq4"].level == "élevé"
    assert "MQL4/Experts/Propre.mq4" not in rows
    assert rows["MQL4/Libraries/Outil.dll"].level == "à surveiller"
    assert rows["Setup.exe"].level == "élevé"
    assert rows["facture.pdf"].level == "élevé" and "déguisé" in rows["facture.pdf"].reasons
    assert rows["bonus.zip"].level == "élevé" and "installer.bat" in rows["bonus.zip"].reasons
    # Le plus risqué d'abord.
    assert next(iter(rows.values())).level == "élevé"
