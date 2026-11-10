"""Copie vérifiée et contrôles de destination (F8, F9) — l'original reste toujours intact."""

from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from mtlm.fs.reader import path_identity
from mtlm.transfer.copy import PARTIAL_SUFFIX, CopyError, copy_verified
from mtlm.transfer.guards import DestinationError, check_destination, check_space
from tests.support.fs_snapshot import diff_snapshots, take_snapshot


def b(p: Path) -> bytes:
    return os.fsencode(p)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    src = tmp_path / "src" / "Robot.mq4"
    src.parent.mkdir()
    src.write_bytes(os.urandom(3_000_000))
    os.utime(src, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    return src


def sha(p: Path) -> bytes:
    return hashlib.sha256(p.read_bytes()).digest()


def test_copie_verifiee(tmp_path: Path, source: Path) -> None:
    before = take_snapshot(source.parent)
    dest = tmp_path / "q" / "a" / "b" / "Robot.mq4"
    result = copy_verified(
        b(source), b(dest), expected_sha256=sha(source), expected_identity=path_identity(b(source))
    )
    assert dest.read_bytes() == source.read_bytes() and result.size == 3_000_000
    assert dest.stat().st_mtime_ns == source.stat().st_mtime_ns  # date d'origine conservée
    assert diff_snapshots(before, take_snapshot(source.parent)) == []  # original intact
    assert not list(dest.parent.glob("*.mtlm-partial"))


def test_destination_existante_jamais_ecrasee(tmp_path: Path, source: Path) -> None:
    dest = tmp_path / "Robot.mq4"
    dest.write_bytes(b"precieux")
    with pytest.raises(CopyError, match="existe déjà"):
        copy_verified(b(source), b(dest), expected_sha256=sha(source))
    assert dest.read_bytes() == b"precieux"


def test_original_modifie_depuis_inventaire(tmp_path: Path, source: Path) -> None:
    identity = path_identity(b(source))
    source.write_bytes(source.read_bytes() + b"!")
    with pytest.raises(CopyError, match="changé depuis l'inventaire"):
        copy_verified(
            b(source), b(tmp_path / "d"), expected_sha256=sha(source), expected_identity=identity
        )
    assert not (tmp_path / "d").exists()


def test_empreinte_differente(tmp_path: Path, source: Path) -> None:
    with pytest.raises(CopyError, match="empreinte"):
        copy_verified(b(source), b(tmp_path / "d"), expected_sha256=b"\x00" * 32)
    assert not (tmp_path / "d").exists()
    assert not list(tmp_path.glob("*" + PARTIAL_SUFFIX.decode()))


def test_copie_corrompue_detectee_a_la_relecture(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = os.write

    def corrupt(fd: int, data: Any) -> int:
        data = bytes(data)
        return real_write(fd, b"X" + data[1:]) if data else real_write(fd, data)

    monkeypatch.setattr(os, "write", corrupt)
    with pytest.raises(CopyError, match="corrompue"):
        copy_verified(b(source), b(tmp_path / "d"), expected_sha256=sha(source))
    assert not (tmp_path / "d").exists()


def test_disque_plein(tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def full(_fd: int, _data: Any) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")

    original = source.read_bytes()
    monkeypatch.setattr(os, "write", full)
    with pytest.raises(CopyError, match="plein"):
        copy_verified(b(source), b(tmp_path / "d"), expected_sha256=sha(source))
    assert source.read_bytes() == original
    assert not list(tmp_path.glob("d*"))


def test_systeme_sans_liens_materiels(
    tmp_path: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_link(*_a: Any, **_k: Any) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_link)
    copy_verified(b(source), b(tmp_path / "d"), expected_sha256=sha(source))
    assert (tmp_path / "d").read_bytes() == source.read_bytes()


def test_reste_de_copie_interrompue_remplace(tmp_path: Path, source: Path) -> None:
    leftover = tmp_path / ("d" + PARTIAL_SUFFIX.decode())
    leftover.write_bytes(b"moitie")
    copy_verified(b(source), b(tmp_path / "d"), expected_sha256=sha(source))
    assert not leftover.exists() and (tmp_path / "d").exists()


def test_destination_dans_une_source_refusee(tmp_path: Path) -> None:
    src = tmp_path / "bibliotheque"
    (src / "sous").mkdir(parents=True)
    app = tmp_path / "app"
    app.mkdir()
    for bad in (src / "sous" / "quarantaine", src, tmp_path, app / "x"):
        with pytest.raises(DestinationError):
            check_destination(bad, [src], [app])
    ok = check_destination(tmp_path / "ailleurs" / "q", [src], [app])
    assert ok.name == "q"


def test_destination_via_lien_vers_la_source_refusee(tmp_path: Path) -> None:
    src = tmp_path / "bibliotheque"
    src.mkdir()
    (tmp_path / "raccourci").symlink_to(src)
    with pytest.raises(DestinationError):
        check_destination(tmp_path / "raccourci" / "q", [src], [])


def test_espace_insuffisant(tmp_path: Path) -> None:
    with pytest.raises(DestinationError, match="Espace insuffisant"):
        check_space(tmp_path, needed=10**18)
    check_space(tmp_path, needed=1, margin=0)
