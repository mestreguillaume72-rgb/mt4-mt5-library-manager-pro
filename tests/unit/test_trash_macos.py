"""Vraie Corbeille du Mac (NSFileManager) : exécuté uniquement sur macOS (CI « CI macOS »)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from mtlm.transfer.trash import TrashError, default_backend, put_back

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Corbeille du Mac uniquement")


def test_corbeille_reelle_puis_remise_en_place(tmp_path: Path) -> None:
    backend = default_backend()
    assert backend is not None
    original = tmp_path / "mtlm-test-corbeille.set"
    original.write_text("Lots=0.1\n", encoding="utf-8")
    location = backend(os.fsencode(original))
    try:
        assert not original.exists()
        assert os.path.exists(location)
        assert b".Trash" in location
        put_back(location, os.fsencode(original))
        assert original.read_text(encoding="utf-8") == "Lots=0.1\n"
        assert not os.path.exists(location)
    finally:
        if os.path.exists(location):
            os.unlink(location)


def test_corbeille_refuse_un_fichier_absent(tmp_path: Path) -> None:
    backend = default_backend()
    assert backend is not None
    with pytest.raises(TrashError):
        backend(os.fsencode(tmp_path / "absent.set"))
