"""Règles de sécurité vérifiées statiquement sur le code de l'application (PLAN_DE_TESTS § 7).

* Aucune exécution de programme, chargement de bibliothèque ou accès réseau (spécification § 6).
* Les modules d'analyse n'ont aucune fonction d'écriture (lecture seule des sources).
* Règles de dépendances entre couches (ARCHITECTURE § 4).

Chaque règle est accompagnée d'un auto-test prouvant qu'elle détecte bien une violation
(un test qui ne peut pas échouer ne prouve rien).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "mtlm"

FORBIDDEN_IMPORTS = {
    "subprocess",
    "ctypes",
    "cffi",
    "socket",
    "ssl",
    "urllib",
    "http",
    "ftplib",
    "smtplib",
    "requests",
    "webbrowser",
    "runpy",
    "pickle",
    "shelve",
    "marshal",
    "multiprocessing.popen",
}
FORBIDDEN_CALLS = {
    "os.system",
    "os.popen",
    "os.startfile",
    "os.execv",
    "os.execve",
    "os.execl",
    "os.execle",
    "os.execlp",
    "os.execlpe",
    "os.execvp",
    "os.execvpe",
    "os.spawnv",
    "os.spawnve",
    "os.spawnl",
    "os.spawnle",
    "os.posix_spawn",
    "os.posix_spawnp",
    "os.fork",
    "os.forkpty",
    "importlib.import_module",
    "eval",
    "exec",
    "compile",
    "__import__",
}
# Modules qui lisent les sources de l'utilisateur : aucune écriture possible.
ANALYSIS_MODULES = ("fs", "hashing", "formats", "metatrader", "setfiles", "matching")
WRITE_CALLS = {
    "os.remove",
    "os.unlink",
    "os.rename",
    "os.replace",
    "os.rmdir",
    "os.removedirs",
    "os.chmod",
    "os.chown",
    "os.utime",
    "os.truncate",
    "os.link",
    "os.symlink",
    "os.mkdir",
    "os.makedirs",
    "os.setxattr",
    "os.removexattr",
    "os.write",
    "shutil.copy",
    "shutil.copy2",
    "shutil.copyfile",
    "shutil.move",
    "shutil.rmtree",
    "shutil.copytree",
}
WRITE_METHODS = {
    "write_text",
    "write_bytes",
    "unlink",
    "rename",
    "rmdir",
    "mkdir",
    "touch",
    "chmod",
    "symlink_to",
    "hardlink_to",
}

# Couches : un module ne peut importer que les sous-paquets listés (ARCHITECTURE § 4).
ALLOWED_DEPENDENCIES: dict[str, set[str]] = {
    "core": set(),
    "store": {"core"},
    "audit": {"core", "store"},
    "fs": {"core"},
    "hashing": {"core", "fs"},
    "formats": {"core", "fs", "hashing"},
    "metatrader": {"core", "fs", "formats"},
    "setfiles": {"core", "fs", "formats"},
    "matching": {"core", "store", "metatrader", "setfiles"},
    "transfer": {"core", "fs", "hashing", "store", "audit"},
    "reports": {"core", "store", "transfer"},
    "app": {
        "core",
        "store",
        "audit",
        "fs",
        "hashing",
        "formats",
        "metatrader",
        "setfiles",
        "matching",
        "transfer",
        "reports",
    },
    "cli": {"core", "store", "audit", "app"},
    "ui": {"core", "app"},
}


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    message: str


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _open_mode_writes(call: ast.Call, position: int = 1) -> bool:
    """Vrai si l'appel ouvre en écriture. ``position`` : index du mode (1 pour open(), 0 pour
    Path.open())."""
    mode: ast.AST | None = None
    if len(call.args) > position:
        mode = call.args[position]
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return any(flag in mode.value for flag in "wax+")
    return True  # mode non littéral : refusé par prudence


def _method_open_writes(call: ast.Call) -> bool:
    """Méthode ``.open`` (Path.open, ZipFile.open…) : écriture si un argument littéral contient
    un drapeau d'écriture, ou si ``mode=`` n'est pas littéral."""
    for arg in call.args:
        if (
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and any(flag in arg.value for flag in "wax+")
        ):
            return True
    for keyword in call.keywords:
        if keyword.arg == "mode":
            value = keyword.value
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                return True
            if any(flag in value.value for flag in "wax+"):
                return True
    return False


def check_source(
    code: str, filename: str, *, analysis: bool, package: str | None
) -> list[Violation]:
    tree = ast.parse(code, filename=filename)
    found: list[Violation] = []

    def flag(node: ast.AST, message: str) -> None:
        found.append(Violation(filename, getattr(node, "lineno", 0), message))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                root = name.split(".")[0]
                if name in FORBIDDEN_IMPORTS or root in FORBIDDEN_IMPORTS:
                    flag(node, f"import interdit : {name}")
                if root == "PySide6" and package not in (None, "ui"):
                    flag(node, f"le moteur ne doit pas dépendre de l'interface : {name}")
                if package and name.startswith("mtlm."):
                    target = name.split(".")[1]
                    allowed = ALLOWED_DEPENDENCIES.get(package, set())
                    if target != package and target not in allowed:
                        flag(node, f"dépendance interdite {package} -> {target}")
        elif isinstance(node, ast.Call):
            call_name = _dotted(node.func)
            name = call_name or ""
            if name in FORBIDDEN_CALLS:
                flag(node, f"appel interdit : {name}")
            if analysis:
                if name in WRITE_CALLS:
                    flag(node, f"écriture interdite dans un module d'analyse : {name}")
                if name in ("open", "io.open") and _open_mode_writes(node):
                    flag(node, "ouverture en écriture interdite dans un module d'analyse")
                if isinstance(node.func, ast.Attribute):
                    # Path.replace(cible) prend 1 argument ; str.replace(a, b) en prend 2.
                    if node.func.attr == "replace" and len(node.args) == 1:
                        flag(node, "méthode d'écriture interdite : replace (Path.replace)")
                    if node.func.attr in WRITE_METHODS:
                        flag(node, f"méthode d'écriture interdite : {node.func.attr}")
                    if (
                        node.func.attr == "open"
                        and name not in ("os.open", "io.open")
                        and _method_open_writes(node)
                    ):
                        flag(node, "Path.open en écriture interdit dans un module d'analyse")
                if name == "os.open":
                    flag_os_open = any(
                        (_dotted(a) or "").startswith("os.O_")
                        and _dotted(a)
                        not in ("os.O_RDONLY", "os.O_NOFOLLOW", "os.O_CLOEXEC", "os.O_NONBLOCK")
                        for a in ast.walk(node)
                        if isinstance(a, ast.Attribute)
                    )
                    if flag_os_open:
                        flag(node, "os.open avec un drapeau d'écriture interdit")
    return found


def iter_sources() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def package_of(path: Path) -> str | None:
    rel = path.relative_to(SRC)
    return rel.parts[0] if len(rel.parts) > 1 else None


def test_sources_trouvees() -> None:
    assert len(iter_sources()) >= 10


def test_aucune_regle_de_securite_violee() -> None:
    violations: list[Violation] = []
    for path in iter_sources():
        package = package_of(path)
        violations += check_source(
            path.read_text(encoding="utf-8"),
            str(path.relative_to(SRC)),
            analysis=package in ANALYSIS_MODULES,
            package=package,
        )
    assert violations == []


def test_tous_les_sous_paquets_sont_declares_dans_les_couches() -> None:
    packages = {p.name for p in SRC.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    assert packages <= set(ALLOWED_DEPENDENCIES), packages - set(ALLOWED_DEPENDENCIES)


# --- auto-tests : chaque règle détecte bien ce qu'elle doit détecter --------------------


@pytest.mark.parametrize(
    "snippet",
    [
        "import subprocess",
        "from ctypes import CDLL",
        "import socket",
        "import urllib.request",
        "import os\nos.system('x')",
        "import os\nos.execv('a', [])",
        "eval('1')",
        "import importlib\nimportlib.import_module('x')",
        "import pickle",
    ],
)
def test_detecte_execution_et_reseau(snippet: str) -> None:
    assert check_source(snippet, "x.py", analysis=False, package="app")


@pytest.mark.parametrize(
    "snippet",
    [
        "open('f', 'w')",
        "open('f', mode='a')",
        "open('f', 'r+b')",
        "from pathlib import Path\nPath('f').write_bytes(b'')",
        "from pathlib import Path\nPath('f').open('wb')",
        "import zipfile\nzipfile.ZipFile('a').open('x', 'w')",
        "from pathlib import Path\nPath('f').open(mode=m)",
        "from pathlib import Path\nPath('f').unlink()",
        "import os\nos.remove('f')",
        "import os\nos.rename('a', 'b')",
        "import shutil\nshutil.copy('a', 'b')",
        "import os\nos.open('f', os.O_WRONLY)",
        "import os\nos.open('f', os.O_RDONLY | os.O_CREAT)",
        "from pathlib import Path\nPath('a').replace('b')",
        "open('f', m)",
    ],
)
def test_detecte_ecriture_dans_analyse(snippet: str) -> None:
    assert check_source(snippet, "x.py", analysis=True, package="fs")


@pytest.mark.parametrize(
    "snippet",
    [
        "open('f')",
        "open('f', 'rb')",
        "import os\nos.open('f', os.O_RDONLY | os.O_NOFOLLOW)",
        "from pathlib import Path\nPath('f').read_bytes()",
        "import zipfile\nzipfile.ZipFile('a').open(info)",
        "x = 'a/b'.replace('/', '-')",
    ],
)
def test_lecture_autorisee_dans_analyse(snippet: str) -> None:
    assert check_source(snippet, "x.py", analysis=True, package="fs") == []


@pytest.mark.parametrize(
    "package, snippet",
    [
        ("core", "from mtlm.store import database"),
        ("store", "from mtlm.audit import journal"),
        ("fs", "from mtlm.transfer import x"),
        ("cli", "from mtlm.ui import x"),
        ("app", "import PySide6"),
    ],
)
def test_detecte_dependance_interdite(package: str, snippet: str) -> None:
    assert check_source(snippet, "x.py", analysis=False, package=package)
