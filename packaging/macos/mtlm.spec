# Spécification PyInstaller — application macOS « MT4 MT5 Library Manager PRO ».
# Construction : uv run --group build pyinstaller --noconfirm packaging/macos/mtlm.spec
# Seuls le paquet « mtlm » et ses dépendances sont embarqués (aucun test, aucune donnée).
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parents[1]  # noqa: F821 — variable fournie par PyInstaller
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "src/mtlm/__init__.py").read_text()).group(1)
NAME = "MT4 MT5 Library Manager PRO"

analysis = Analysis(  # noqa: F821
    [str(ROOT / "packaging/macos/launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=collect_data_files("mtlm", includes=["**/*.sql"]),
    excludes=["tests", "pytest", "hypothesis", "tkinter", "PySide6.QtWebEngineCore",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, analysis.scripts, [], exclude_binaries=True, name="mtlm-gui", console=False,
    debug=False, strip=False, upx=False, argv_emulation=False,
)
collected = COLLECT(  # noqa: F821
    exe, analysis.binaries, analysis.datas, strip=False, upx=False, name="mtlm-gui",
)
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        collected,
        name=f"{NAME}.app",
        icon=None,
        bundle_identifier="fr.mtlm.library-manager-pro",
        version=VERSION,
        info_plist={
            "CFBundleName": NAME,
            "CFBundleDisplayName": NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "Usage privé du propriétaire du projet",
            "LSApplicationCategoryType": "public.app-category.finance",
        },
    )
