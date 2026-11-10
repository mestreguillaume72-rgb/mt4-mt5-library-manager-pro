"""F3 — signatures et archives : cas imposés (saine, corrompue, bombe, traversée,
doublons, chiffrée) + limites."""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest

from mtlm.formats.archives import ArchiveLimits, inspect_archive, unsafe_name_reason
from mtlm.formats.signatures import is_misleading, sniff
from tests.support.archives import (
    make_bad_crc,
    make_bomb,
    make_encrypted,
    make_symlink_zip,
    make_zip,
    make_zip_entries,
)
from tests.support.fs_snapshot import diff_snapshots, take_snapshot


def b(p: Path) -> bytes:
    return os.fsencode(p)


@pytest.mark.parametrize(
    "head, kind",
    [
        (b"PK\x03\x04rest", "zip"),
        (b"Rar!\x1a\x07\x00", "rar"),
        (b"7z\xbc\xaf\x27\x1c", "7z"),
        (b"MZ\x90\x00", "pe"),
        (b"%PDF-1.7", "pdf"),
        (b"\xff\xfe" + "#property".encode("utf-16-le"), "utf16-text"),
        ("input int X=1;".encode("utf-16-le"), "utf16-text"),
        (b"\xef\xbb\xbf#property strict", "text"),
        ("// Été\n".encode("cp1252"), "text"),
        (b"Lots=0.1\r\nTP=50\r\n", "text"),
        (bytes(range(256)) * 4, "binary"),
        (b"", "empty"),
    ],
)
def test_signatures(head: bytes, kind: str) -> None:
    assert sniff(head).kind == kind


@pytest.mark.parametrize(
    "ext, head, misleading",
    [
        ("mq4", b"MZ\x90\x00", True),  # exécutable déguisé en source
        ("ex4", b"#property strict\n", True),  # texte déguisé en binaire compilé
        ("ex4", bytes(range(256)), False),
        ("dll", b"PK\x03\x04", True),
        ("zip", b"Lots=1", True),
        ("set", b"Lots=1\n", False),
        ("xyz", b"MZ", False),  # extension inconnue : rien à comparer
        ("mq5", b"", False),
    ],
)
def test_extension_trompeuse(ext: str, head: bytes, misleading: bool) -> None:
    assert is_misleading(ext, sniff(head)) is misleading


@pytest.mark.parametrize(
    "name, reason",
    [
        ("a/b.mq4", None),
        ("/etc/passwd", "chemin absolu"),
        ("C:\\win.ini", "lecteur Windows"),
        ("../../x", "traversée"),
        ("a\\..\\..\\x", "traversée"),
        ("ok..mq4", None),
    ],
)
def test_noms_dangereux(name: str, reason: str | None) -> None:
    found = unsafe_name_reason(name)
    assert (found is None) if reason is None else (found is not None and reason in found)


def test_archive_saine(tmp_path: Path) -> None:
    path = make_zip(
        tmp_path / "robots.zip",
        {
            "MQL4/Experts/Robot.mq4": b"// robot fictif",
            "MQL4/Presets/Robot.set": b"Lots=0.1",
            "vide/": b"",
        },
    )
    report = inspect_archive(b(path), "zip")
    assert report.status == "ok" and report.entries_total == 3 and report.entries_read == 2
    import hashlib

    hashes = {e.inner_path: e.sha256 for e in report.entries}
    assert hashes["MQL4/Experts/Robot.mq4"] == hashlib.sha256(b"// robot fictif").digest()


def test_archive_corrompue(tmp_path: Path) -> None:
    bad = tmp_path / "faux.zip"
    bad.write_bytes(b"PK\x03\x04" + os.urandom(500))
    report = inspect_archive(b(bad), "zip")
    assert report.status == "corrupt" and "corrompue" in (report.reason or "")


def test_archive_tronquee(tmp_path: Path) -> None:
    path = make_zip(tmp_path / "t.zip", {"a.mq4": os.urandom(5000)})
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    assert inspect_archive(b(path), "zip").status == "corrupt"


def test_crc_incorrect(tmp_path: Path) -> None:
    report = inspect_archive(b(make_bad_crc(tmp_path / "crc.zip")), "zip")
    statuses = {e.inner_path: e.status for e in report.entries}
    assert statuses == {"a.mq4": "corrupt", "b.mq4": "inspected"}
    assert report.status == "partial"


def test_zip_bomb_simulee(tmp_path: Path) -> None:
    path = make_bomb(tmp_path / "bombe.zip")
    assert path.stat().st_size < 1024 * 1024  # 64 Mio de zéros dans moins de 1 Mio
    report = inspect_archive(b(path), "zip")
    (entry,) = report.entries
    assert entry.status == "skipped_limit" and "ratio" in (entry.reason or "")
    # Arrêt dès que le ratio dépasse 100:1 : au plus ~100 x la taille compressée (+ un bloc)
    # est décompressé, au lieu des 64 Mio annoncés ; la mémoire reste bornée (bloc de 256 Kio).
    assert entry.compressed_size is not None
    assert report.bytes_read <= 100 * entry.compressed_size + 256 * 1024
    assert report.bytes_read < 64 * 1024 * 1024 / 8


def test_limites_taille_et_nombre(tmp_path: Path) -> None:
    path = make_zip(tmp_path / "gros.zip", {f"f{i}.bin": os.urandom(4000) for i in range(30)})
    small = ArchiveLimits(max_entries=10, max_entry_bytes=1_000_000)
    report = inspect_archive(b(path), "zip", small)
    assert sum(e.status == "skipped_limit" for e in report.entries) == 20
    tiny_total = ArchiveLimits(max_total_bytes=10_000)
    report = inspect_archive(b(path), "zip", tiny_total)
    assert any("totale" in (e.reason or "") for e in report.entries)
    per_entry = ArchiveLimits(max_entry_bytes=1000)
    assert all(
        e.status == "skipped_limit" for e in inspect_archive(b(path), "zip", per_entry).entries
    )


def test_noms_traversants_et_absolus(tmp_path: Path) -> None:
    path = make_zip(tmp_path / "t.zip", {"../../evil.mq4": b"x", "/abs.set": b"y", "ok.mq4": b"z"})
    report = inspect_archive(b(path), "zip")
    statuses = {e.inner_path: e.status for e in report.entries}
    assert statuses["../../evil.mq4"] == "rejected_traversal"
    assert statuses["/abs.set"] == "rejected_traversal"
    assert statuses["ok.mq4"] == "inspected"
    assert not (tmp_path.parent / "evil.mq4").exists()


def test_lien_symbolique_dans_l_archive(tmp_path: Path) -> None:
    report = inspect_archive(b(make_symlink_zip(tmp_path / "l.zip")), "zip")
    statuses = {e.inner_path: e.status for e in report.entries}
    assert statuses == {"lien_vers_etc": "rejected_symlink", "normal.mq4": "inspected"}


def test_doublons_d_entrees(tmp_path: Path) -> None:
    path = make_zip_entries(tmp_path / "d.zip", [("Robot.mq4", b"v1"), ("Robot.mq4", b"v2")])
    report = inspect_archive(b(path), "zip")
    assert len(report.entries) == 2
    assert report.entries[1].reason == "nom en double dans l'archive"
    assert report.entries[0].sha256 != report.entries[1].sha256


def test_archive_chiffree(tmp_path: Path) -> None:
    report = inspect_archive(b(make_encrypted(tmp_path / "c.zip")), "zip")
    assert report.status == "encrypted"
    assert report.entries[0].status == "encrypted" and report.entries[0].sha256 is None


def test_archive_imbriquee_et_profondeur(tmp_path: Path) -> None:
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("profond.mq5", b"// niveau 2")
    level2 = inner.getvalue()
    middle = io.BytesIO()
    with zipfile.ZipFile(middle, "w") as z:
        z.writestr("niveau2.zip", level2)
        z.writestr("niveau1.mq4", b"// niveau 1")
    path = make_zip(tmp_path / "n.zip", {"niveau1.zip": middle.getvalue()})
    report = inspect_archive(b(path), "zip", ArchiveLimits(max_depth=2))
    paths = [e.inner_path for e in report.entries]
    assert "niveau1.zip!/niveau1.mq4" in paths
    assert "niveau1.zip!/niveau2.zip!/profond.mq5" not in paths  # profondeur 3 refusée
    deeper = inspect_archive(b(path), "zip", ArchiveLimits(max_depth=3))
    assert "niveau1.zip!/niveau2.zip!/profond.mq5" in [e.inner_path for e in deeper.entries]


@pytest.mark.parametrize("kind", ["rar", "7z", "gzip"])
def test_formats_identifies_non_ouverts(tmp_path: Path, kind: str) -> None:
    f = tmp_path / "a"
    f.write_bytes(b"x")
    assert inspect_archive(b(f), kind).status == "not_supported"


def test_pas_une_archive(tmp_path: Path) -> None:
    f = tmp_path / "a.zip"
    f.write_bytes(b"texte")
    assert inspect_archive(b(f), "text").status == "rejected"


def test_aucune_ecriture_sur_disque(tmp_path: Path) -> None:
    folder = tmp_path / "zone"
    folder.mkdir()
    make_zip(folder / "a.zip", {"../x.mq4": b"1", "b/c.mq4": b"2"})
    make_bomb(folder / "bombe.zip", size=8 * 1024 * 1024)
    make_symlink_zip(folder / "l.zip")
    before = take_snapshot(tmp_path)
    for archive in sorted(folder.iterdir()):
        inspect_archive(b(archive), "zip")
    assert diff_snapshots(before, take_snapshot(tmp_path)) == []
