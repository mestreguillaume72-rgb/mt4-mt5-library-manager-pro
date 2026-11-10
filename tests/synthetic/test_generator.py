from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

import pytest

from tests.synthetic.generate import generate_corpus, main


def files_on_disk(root: Path) -> dict[str, bytes]:
    return {
        unicodedata.normalize("NFC", p.relative_to(root).as_posix()): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_reproductible(tmp_path: Path) -> None:
    a = generate_corpus(tmp_path / "a", seed=7, n_files=600)
    b = generate_corpus(tmp_path / "b", seed=7, n_files=600)
    assert a.to_json() == b.to_json()
    assert files_on_disk(tmp_path / "a") == files_on_disk(tmp_path / "b")


def test_graine_differente_corpus_different(tmp_path: Path) -> None:
    a = generate_corpus(tmp_path / "a", seed=1, n_files=200)
    b = generate_corpus(tmp_path / "b", seed=2, n_files=200)
    assert a.to_json() != b.to_json()


def test_manifeste_conforme_au_disque(tmp_path: Path) -> None:
    manifest = generate_corpus(tmp_path / "c", seed=3, n_files=1500)
    disk = files_on_disk(tmp_path / "c")
    assert len(manifest.entries) == 1500 == len(disk)
    for entry in manifest.entries:
        data = disk[unicodedata.normalize("NFC", entry.rel_path)]
        assert len(data) == entry.size
        assert hashlib.sha256(data).hexdigest() == entry.sha256


def test_verite_terrain_doublons_et_set(tmp_path: Path) -> None:
    manifest = generate_corpus(tmp_path / "c", seed=4, n_files=2000)
    by_path = {e.rel_path: e for e in manifest.entries}
    duplicates = [e for e in manifest.entries if e.duplicate_of]
    assert len(duplicates) > 40
    for dup in duplicates:
        assert dup.sha256 == by_path[dup.duplicate_of].sha256  # type: ignore[index]
    sets = [e for e in manifest.entries if e.kind == "set" and not e.duplicate_of]
    assert sets and all(e.set_for in by_path for e in sets)
    kinds = manifest.counts()
    for kind in ("mq4", "mq5", "mqh", "ex4", "ex5", "set", "dll", "unknown", "empty"):
        assert kinds.get(kind, 0) > 0, kind


def test_encodages_et_noms_unicode(tmp_path: Path) -> None:
    manifest = generate_corpus(tmp_path / "c", seed=5, n_files=3000)
    root = tmp_path / "c"
    mq5 = next(e for e in manifest.entries if e.kind == "mq5" and not e.duplicate_of)
    assert (root / mq5.rel_path).read_bytes().startswith(b"\xff\xfe")
    assert any(ord(ch) > 127 for e in manifest.entries for ch in e.rel_path)
    assert any(e.rel_path != unicodedata.normalize("NFC", e.rel_path) for e in manifest.entries)


def test_contenu_fictif_explicite(tmp_path: Path) -> None:
    manifest = generate_corpus(tmp_path / "c", seed=6, n_files=300)
    mq4 = next(e for e in manifest.entries if e.kind == "mq4")
    data = (tmp_path / "c" / mq4.rel_path).read_bytes()
    text = (
        data.decode("utf-8-sig", errors="replace")
        if mq4.encoding != "cp1252"
        else data.decode("cp1252")
    )
    assert "FICTIF" in text and "Exemple fictif" in text


def test_refuse_un_dossier_non_vide(tmp_path: Path) -> None:
    (tmp_path / "bibliotheque").mkdir()
    precious = tmp_path / "bibliotheque" / "robot.txt"
    precious.write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError, match="pas vide"):
        generate_corpus(tmp_path / "bibliotheque", seed=1, n_files=10)
    assert precious.read_text(encoding="utf-8") == "original"


def test_parametres_invalides(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        generate_corpus(tmp_path / "x", seed=1, n_files=0)
    with pytest.raises(ValueError):
        generate_corpus(tmp_path / "y", seed=1, n_files=1, size_profile="enorme")


def test_ligne_de_commande(tmp_path: Path) -> None:
    out, manifest = tmp_path / "corpus", tmp_path / "m.json"
    assert (
        main(["--seed", "9", "--files", "50", "--out", str(out), "--manifest", str(manifest)]) == 0
    )
    assert json.loads(manifest.read_text(encoding="utf-8"))["total_files"] == 50
