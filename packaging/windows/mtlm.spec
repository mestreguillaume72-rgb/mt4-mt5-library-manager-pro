# Spécification PyInstaller — application Windows « MT4 MT5 Library Manager PRO ».
# Construction (Windows) : uv run --group build pyinstaller --noconfirm packaging/windows/mtlm.spec
# Seuls le paquet « mtlm » et ses dépendances sont embarqués (aucun test, aucune donnée).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parents[1]  # noqa: F821 — variable fournie par PyInstaller
ICON = ROOT / "packaging/windows/AppIcon.ico"

analysis = Analysis(  # noqa: F821
    [str(ROOT / "packaging/macos/launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=collect_data_files("mtlm", includes=["**/*.sql", "core/locales/*.json"]),
    excludes=["tests", "pytest", "hypothesis", "tkinter", "PySide6.QtWebEngineCore",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, analysis.scripts, [], exclude_binaries=True, name="MT4-MT5-Library-Manager-PRO",
    console=False, debug=False, strip=False, upx=False,
    icon=str(ICON) if ICON.exists() else None,
)
COLLECT(  # noqa: F821
    exe, analysis.binaries, analysis.datas, strip=False, upx=False,
    name="MT4-MT5-Library-Manager-PRO",
)
