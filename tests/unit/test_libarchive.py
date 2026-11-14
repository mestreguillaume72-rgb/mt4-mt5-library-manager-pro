"""1.5.0 — archives RAR, 7z, GZIP, BZIP2, XZ, TAR lues sans extraction (libarchive)."""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from mtlm.formats import libarchive
from mtlm.formats.archives import ArchiveLimits, inspect_archive
from mtlm.formats.signatures import sniff

pytestmark = pytest.mark.skipif(not libarchive.available(), reason="libarchive absente")
SET = b"Lots=0.1\nTP=50\n"
ROBOT = b"extern double Lots = 0.1;\nint start(){return 0;}\n"


def kind(path: Path) -> str:
    return sniff(path.read_bytes()[:4096]).kind


def make_tar(path: Path, mode: str, files: dict[str, bytes]) -> None:
    with tarfile.open(path, mode) as archive:  # type: ignore[call-overload]
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


@pytest.mark.parametrize(
    ("name", "mode", "expected"),
    [
        ("lot.tar.gz", "w:gz", "gzip"),
        ("lot.tar.xz", "w:xz", "xz"),
        ("lot.tar.bz2", "w:bz2", "bzip2"),
        ("lot.tar", "w", "tar"),
    ],
)
def test_tar_compresses(tmp_path: Path, name: str, mode: str, expected: str) -> None:
    path = tmp_path / name
    make_tar(path, mode, {"Robot/Scalper.mq4": ROBOT, "Robot/Scalper.set": SET})
    assert kind(path) == expected
    report = inspect_archive(os.fsencode(path), expected)
    assert report.status == "ok"
    found = {e.inner_path: e.sha256 for e in report.entries if not e.is_dir}
    assert found == {
        "Robot/Scalper.mq4": hashlib.sha256(ROBOT).digest(),
        "Robot/Scalper.set": hashlib.sha256(SET).digest(),
    }


def test_gzip_d_un_seul_fichier(tmp_path: Path) -> None:
    path = tmp_path / "reglage.set.gz"
    path.write_bytes(gzip.compress(SET))
    report = inspect_archive(os.fsencode(path), "gzip")
    assert report.status == "ok"
    assert [e.sha256 for e in report.entries] == [hashlib.sha256(SET).digest()]


def test_chemin_piege_refuse(tmp_path: Path) -> None:
    path = tmp_path / "piege.tar.gz"
    make_tar(path, "w:gz", {"../../evil.set": SET, "ok.set": SET})
    report = inspect_archive(os.fsencode(path), "gzip")
    statuses = {e.inner_path: e.status for e in report.entries}
    assert statuses["../../evil.set"] == "rejected_traversal"
    assert statuses["ok.set"] == "inspected"
    assert report.status == "partial"


def test_limite_de_taille(tmp_path: Path) -> None:
    path = tmp_path / "gros.tar.gz"
    make_tar(path, "w:gz", {"gros.bin": b"\0" * 300_000})
    report = inspect_archive(os.fsencode(path), "gzip", ArchiveLimits(max_entry_bytes=100_000))
    assert report.entries[0].status == "skipped_limit"


def test_archive_corrompue(tmp_path: Path) -> None:
    path = tmp_path / "abime.7z"
    path.write_bytes(b"7z\xbc\xaf\x27\x1c" + os.urandom(200))
    report = inspect_archive(os.fsencode(path), "7z")
    assert report.status in ("corrupt", "partial")


SEVEN = shutil.which("7z") or shutil.which("7za") or shutil.which("7zz")


@pytest.mark.skipif(SEVEN is None, reason="outil 7z absent pour fabriquer l'archive de test")
def test_7z_normal_et_protege_par_mot_de_passe(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "Robot").mkdir(parents=True)
    (src / "Robot" / "Scalper.set").write_bytes(SET)
    plain, locked = tmp_path / "lot.7z", tmp_path / "secret.7z"
    for target, extra in ((plain, []), (locked, ["-pSECRET", "-mhe=on"])):
        subprocess.run(
            [str(SEVEN), "a", "-bd", "-y", *extra, str(target), "Robot"],
            cwd=src,
            check=True,
            capture_output=True,
        )
    assert kind(plain) == "7z"
    report = inspect_archive(os.fsencode(plain), "7z")
    assert report.status == "ok"
    assert [e.sha256 for e in report.entries if not e.is_dir] == [hashlib.sha256(SET).digest()]
    assert inspect_archive(os.fsencode(locked), "7z").status == "encrypted"
