"""F1 — énumération lecture seule : cas imposés par la spécification."""

from __future__ import annotations

import errno
import os
import sys
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mtlm.fs import walker as walker_module
from mtlm.fs.walker import WalkEntry, WalkError, WalkStats, display_path, extension_of, walk
from tests.synthetic.generate import generate_corpus


def entries(root: Path) -> list[WalkEntry]:
    return [e for e in walk(root) if isinstance(e, WalkEntry)]


@pytest.mark.parametrize(
    "name, ext",
    [
        ("robot.mq4", "mq4"),
        ("ROBOT.EX4", "ex4"),
        ("archive.tar.gz", "gz"),
        (".bashrc", ""),
        ("sans", ""),
        ("fin.", ""),
        ("Été v1.2.set", "set"),
    ],
)
def test_extension(name: str, ext: str) -> None:
    assert extension_of(name) == ext


def test_corpus_compte_exact_et_unicode(tmp_path: Path) -> None:
    manifest = generate_corpus(tmp_path / "c", seed=21, n_files=1200)
    found = entries(tmp_path / "c")
    assert len(found) == 1200
    expected = {unicodedata.normalize("NFC", e.rel_path) for e in manifest.entries}
    assert {e.rel_path for e in found} == expected
    assert all(e.file_type == "file" for e in found)
    by_path = {unicodedata.normalize("NFC", e.rel_path): e for e in manifest.entries}
    assert all(e.size == by_path[e.rel_path].size for e in found)
    assert {e.ext for e in found} >= {"mq4", "mq5", "ex4", "set", "dll"}


def test_ordre_deterministe(tmp_path: Path) -> None:
    generate_corpus(tmp_path / "c", seed=3, n_files=300)
    assert [e.rel_path for e in entries(tmp_path / "c")] == [
        e.rel_path for e in entries(tmp_path / "c")
    ]


def test_liens_symboliques_cycliques_non_suivis(tmp_path: Path) -> None:
    root = tmp_path / "src"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "f.mq4").write_bytes(b"x")
    (root / "a" / "b" / "vers_racine").symlink_to(root)
    (root / "a" / "vers_parent").symlink_to("..")
    (root / "casse").symlink_to(root / "inexistant")
    stats = WalkStats()
    found = {e.rel_path: e for e in walk(root, stats=stats) if isinstance(e, WalkEntry)}
    assert set(found) == {"a/b/f.mq4", "a/b/vers_racine", "a/vers_parent", "casse"}
    assert found["casse"].file_type == "symlink"
    assert stats.directories == 3


def test_meme_dossier_atteint_deux_fois_ignore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un montage ou un lien matériel de dossier peut faire réapparaître un dossier déjà
    visité : il est reconnu par (périphérique, inode) et ignoré, sans boucle."""
    root = tmp_path / "src"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    (root / "a" / "f").write_bytes(b"1")
    a_stat = os.stat(root / "a")
    real_scandir = os.scandir

    class _Alias:
        def __init__(self, inner: os.DirEntry[bytes]) -> None:
            self.name = inner.name
            self.path = inner.path

        def stat(self, follow_symlinks: bool = True) -> os.stat_result:
            return a_stat  # « b » se présente comme le même dossier que « a »

    class _Wrap(_Scandir):
        def __iter__(self) -> Iterator[Any]:
            for entry in self.inner:
                yield _Alias(entry) if entry.name == b"b" else entry

    monkeypatch.setattr(os, "scandir", lambda p: _Wrap(iter(list(real_scandir(p))), b""))
    stats = WalkStats()
    found = [e.rel_path for e in walk(root, stats=stats) if isinstance(e, WalkEntry)]
    assert found == ["a/f"]
    assert stats.cycles_skipped == 1 and stats.directories == 2


def test_dossier_illisible_simule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "src"
    (root / "ferme").mkdir(parents=True)
    (root / "ferme" / "secret.set").write_bytes(b"x")
    (root / "ouvert.mq4").write_bytes(b"x")
    real_scandir = os.scandir

    def fake_scandir(path: Any) -> Any:
        if os.fsencode(path).endswith(b"ferme"):
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)
    items = list(walk(root))
    errors = [i for i in items if isinstance(i, WalkError)]
    assert [e.rel_path for e in errors] == ["ferme"]
    assert errors[0].errno == errno.EACCES and "EACCES" in errors[0].message
    assert [i.rel_path for i in items if isinstance(i, WalkEntry)] == ["ouvert.mq4"]


@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="l'administrateur ignore les permissions"
)
def test_dossier_illisible_reel(tmp_path: Path) -> None:
    root = tmp_path / "src"
    (root / "ferme").mkdir(parents=True)
    (root / "ferme" / "x").write_bytes(b"x")
    (root / "ferme").chmod(0)
    try:
        errors = [i for i in walk(root) if isinstance(i, WalkError)]
        assert [e.rel_path for e in errors] == ["ferme"]
    finally:
        (root / "ferme").chmod(0o755)


class _BrokenEntry:
    def __init__(self, inner: os.DirEntry[bytes]) -> None:
        self.name = inner.name
        self.path = inner.path

    def stat(self, follow_symlinks: bool = True) -> os.stat_result:
        raise FileNotFoundError(errno.ENOENT, "disparu pendant l'inventaire")


class _Scandir:
    def __init__(self, inner: Iterator[Any], broken: bytes) -> None:
        self.inner = inner
        self.broken = broken

    def __enter__(self) -> _Scandir:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def __iter__(self) -> Iterator[Any]:
        for entry in self.inner:
            yield _BrokenEntry(entry) if entry.name == self.broken else entry


def test_fichier_inaccessible_n_arrete_pas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "src"
    root.mkdir()
    for name in ("a.mq4", "b.mq4", "c.mq4"):
        (root / name).write_bytes(b"x")
    real_scandir = os.scandir
    monkeypatch.setattr(os, "scandir", lambda p: _Scandir(iter(list(real_scandir(p))), b"b.mq4"))
    items = list(walk(root))
    assert [i.rel_path for i in items if isinstance(i, WalkEntry)] == ["a.mq4", "c.mq4"]
    assert [i.rel_path for i in items if isinstance(i, WalkError)] == ["b.mq4"]


@pytest.mark.skipif(sys.platform == "darwin", reason="APFS refuse les noms non UTF-8")
def test_nom_non_utf8_conserve_en_octets(tmp_path: Path) -> None:
    root = tmp_path / "src"
    root.mkdir()
    raw = b"robot_\xe9t\xe9.mq4"  # Latin-1, invalide en UTF-8
    with open(os.path.join(os.fsencode(root), raw), "wb") as handle:
        handle.write(b"x")
    (entry,) = entries(root)
    assert entry.rel_path_bytes == raw
    assert entry.rel_path == "robot_�t�.mq4"
    assert entry.ext == "mq4"


def test_tube_inventorie_sans_etre_lu(tmp_path: Path) -> None:
    root = tmp_path / "src"
    root.mkdir()
    os.mkfifo(root / "tube")
    (entry,) = entries(root)
    assert entry.file_type == "other"


def test_chemin_long(tmp_path: Path) -> None:
    """Chemin relatif > 800 octets (macOS limite le chemin absolu à 1024 octets ; au-delà,
    le système renvoie ENAMETOOLONG, consigné comme erreur sans arrêter l'inventaire)."""
    root = tmp_path / "src"
    deep = root
    for i in range(25):
        deep = deep / f"niveau_{i:02d}_avec_un_nom_assez_long"
    deep.mkdir(parents=True)
    (deep / "f.set").write_bytes(b"x")
    (entry,) = entries(root)
    assert len(entry.rel_path_bytes) > 800


def test_racine_qui_n_est_pas_un_dossier(tmp_path: Path) -> None:
    f = tmp_path / "f"
    f.write_bytes(b"x")
    with pytest.raises(NotADirectoryError):
        list(walk(f))


def test_display_path_normalise_nfc() -> None:
    nfd = unicodedata.normalize("NFD", "Été/Noël.mq4").encode()
    assert display_path(nfd) == "Été/Noël.mq4"


def test_dataless_et_date_de_creation_macos() -> None:
    """Simulation des champs propres à macOS (st_flags, st_birthtime)."""
    fake = SimpleNamespace(
        st_mode=0o100644,
        st_size=10,
        st_mtime_ns=1,
        st_ctime_ns=2,
        st_ino=3,
        st_dev=4,
        st_flags=walker_module.SF_DATALESS,
        st_birthtime=1.5,
    )
    entry = walker_module._entry_from_stat(b"f.mq4", fake)  # type: ignore[arg-type]
    assert entry.is_dataless is True
    assert entry.birthtime_ns == 1_500_000_000
