"""1.8.0 — version Windows : ce qui se vérifie sur tous les systèmes (les vrais appels à
Windows tournent dans la CI « Windows »)."""

from __future__ import annotations

from pathlib import Path

from mtlm.app.mtfolders import metatrader_folders
from mtlm.core.filenames import portable_name
from mtlm.core.paths import default_paths


def test_dossiers_de_l_application_sous_windows(tmp_path: Path) -> None:
    env = {"APPDATA": str(tmp_path / "Roaming"), "LOCALAPPDATA": str(tmp_path / "Local")}
    paths = default_paths(env, "win32", tmp_path)
    assert paths.data_dir == tmp_path / "Roaming" / "MT4MT5LibraryManagerPro"
    assert paths.logs_dir == tmp_path / "Local" / "MT4MT5LibraryManagerPro" / "Logs"


def test_noms_valables_sous_windows() -> None:
    assert portable_name('Robot: "Or" v2?') == "Robot_ _Or_ v2_"
    assert portable_name("CON") == "_CON"
    assert portable_name("nul.txt") == "_nul.txt"
    assert portable_name("Pack. ") == "Pack"
    assert portable_name("...") == "_"
    assert portable_name("x" * 300) == "x" * 120


def test_dossiers_metatrader_trouves_sous_windows(tmp_path: Path) -> None:
    roaming = tmp_path / "Roaming"
    terminal = roaming / "MetaQuotes" / "Terminal" / "D0E8209F77C8CF37AD8BF550E51FF075"
    (terminal / "MQL4" / "Experts").mkdir(parents=True)
    (roaming / "MetaQuotes" / "Terminal" / "Common" / "Files").mkdir(parents=True)
    portable = tmp_path / "Program Files" / "MetaTrader 5"
    (portable / "MQL5").mkdir(parents=True)
    env = {"APPDATA": str(roaming), "ProgramFiles": str(tmp_path / "Program Files")}
    assert metatrader_folders(env, "win32", tmp_path) == [terminal / "MQL4", portable / "MQL5"]


def test_dossiers_metatrader_pour_mac(tmp_path: Path) -> None:
    drive = (
        tmp_path / "Library" / "Application Support" / "net.metaquotes.wine.metatrader4" / "drive_c"
    )
    (drive / "Program Files (x86)" / "MetaTrader 4" / "MQL4").mkdir(parents=True)
    found = metatrader_folders({}, "darwin", tmp_path)
    assert found == [drive / "Program Files (x86)" / "MetaTrader 4" / "MQL4"]
    assert metatrader_folders({}, "linux", tmp_path) == []
