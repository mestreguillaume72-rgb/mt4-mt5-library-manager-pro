"""F2 — empreintes SHA-256 en flux : cas imposés par la spécification."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tracemalloc
from pathlib import Path

import pytest

from mtlm.fs.reader import FileIdentity, NotRegularFileError, ReadOnlyFile, path_identity
from mtlm.hashing.sha256 import UnstableFileError, hash_file


def b(path: Path) -> bytes:
    return os.fsencode(path)


@pytest.mark.parametrize(
    "data, expected",
    [
        (b"", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
        (b"abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
    ],
)
def test_vecteurs_nist(tmp_path: Path, data: bytes, expected: str) -> None:
    f = tmp_path / "f"
    f.write_bytes(data)
    assert hash_file(b(f)).sha256.hex() == expected


@pytest.mark.parametrize("size", [0, 1, 1024 * 1024 - 1, 1024 * 1024, 1024 * 1024 + 1, 3_000_001])
def test_tailles_limites(tmp_path: Path, size: int) -> None:
    f = tmp_path / "f"
    data = os.urandom(size)
    f.write_bytes(data)
    result = hash_file(b(f), chunk_size=1024 * 1024)
    assert result.sha256 == hashlib.sha256(data).digest() and result.size == size


@pytest.mark.skipif(
    shutil.which("sha256sum") is None and shutil.which("shasum") is None,
    reason="outil système absent",
)
def test_identique_a_l_outil_systeme(tmp_path: Path) -> None:
    f = tmp_path / "f.bin"
    f.write_bytes(os.urandom(200_000))
    tool = shutil.which("sha256sum")
    cmd = [tool, str(f)] if tool else [str(shutil.which("shasum")), "-a", "256", str(f)]
    output = subprocess.run(cmd, capture_output=True, check=True, text=True).stdout
    assert hash_file(b(f)).sha256.hex() == output.split()[0]


def test_memoire_constante_gros_fichier(tmp_path: Path) -> None:
    """Gros fichier : la mémoire ne dépend pas de la taille (jamais chargé en entier)."""
    f = tmp_path / "gros.bin"
    with f.open("wb") as handle:
        handle.truncate(64 * 1024 * 1024)  # fichier creux de 64 Mio
    tracemalloc.start()
    try:
        result = hash_file(b(f))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.size == 64 * 1024 * 1024
    assert peak < 8 * 1024 * 1024


def test_modifie_pendant_la_lecture(tmp_path: Path) -> None:
    f = tmp_path / "f"
    f.write_bytes(b"x" * 300_000)
    calls: list[int] = []

    def grow(_n: int) -> None:
        if not calls:
            with f.open("ab") as handle:  # un autre programme écrit pendant la lecture
                handle.write(b"ajout")
        calls.append(1)

    with pytest.raises(UnstableFileError, match="pendant la lecture"):
        hash_file(b(f), chunk_size=65536, on_chunk=grow)


def test_remplace_pendant_la_lecture(tmp_path: Path) -> None:
    f = tmp_path / "f"
    f.write_bytes(b"a" * 200_000)

    def swap(_n: int) -> None:
        if f.exists() and f.read_bytes()[:1] == b"a":
            replacement = tmp_path / "nouveau"
            replacement.write_bytes(b"b" * 200_000)
            replacement.replace(f)

    with pytest.raises(UnstableFileError):
        hash_file(b(f), chunk_size=65536, on_chunk=swap)


def test_modifie_depuis_l_inventaire(tmp_path: Path) -> None:
    f = tmp_path / "f"
    f.write_bytes(b"v1")
    seen = path_identity(b(f))
    f.write_bytes(b"version 2")
    with pytest.raises(UnstableFileError, match="depuis l'inventaire"):
        hash_file(b(f), expected=seen)


def test_identite_attendue_acceptee(tmp_path: Path) -> None:
    f = tmp_path / "f"
    f.write_bytes(b"stable")
    assert hash_file(b(f), expected=path_identity(b(f))).size == 6


def test_lecture_interrompue_propage_l_erreur(tmp_path: Path) -> None:
    f = tmp_path / "f"
    f.write_bytes(b"x" * 200_000)

    class StopError(Exception):
        pass

    def stop(_n: int) -> None:
        raise StopError

    with pytest.raises(StopError):
        hash_file(b(f), chunk_size=65536, on_chunk=stop)
    assert f.read_bytes() == b"x" * 200_000  # rien n'a été écrit


def test_lien_symbolique_jamais_suivi(tmp_path: Path) -> None:
    target = tmp_path / "cible"
    target.write_bytes(b"x")
    link = tmp_path / "lien"
    link.symlink_to(target)
    with pytest.raises(OSError):
        hash_file(b(link))


def test_tube_jamais_lu(tmp_path: Path) -> None:
    fifo = tmp_path / "tube"
    os.mkfifo(fifo)
    with pytest.raises(NotRegularFileError):
        ReadOnlyFile(b(fifo))


def test_identite() -> None:
    st = os.stat(__file__)
    assert FileIdentity.of(st).size == st.st_size
