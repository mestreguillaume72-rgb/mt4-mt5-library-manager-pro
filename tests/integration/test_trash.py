"""1.3.0 — mise à la Corbeille des doublons (quarantaine validée, Doublons, Familles).

Une Corbeille de test (un dossier) remplace celle du Mac ; la vraie Corbeille est testée sur
macOS par ``tests/unit/test_trash_macos.py``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from mtlm.app.context import AppContext, open_app
from mtlm.app.deletion import DeletionError, DeletionService
from mtlm.app.duplicates import DuplicateService
from mtlm.app.quarantine import QuarantineService
from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths
from mtlm.transfer.trash import TrashError
from tests.integration.test_quarantine_organize import analyse, build, mkd


class FakeTrash:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.calls: list[bytes] = []
        self.fail = False

    def __call__(self, path: bytes) -> bytes:
        if self.fail:
            raise TrashError("Corbeille pleine (test)")
        self.calls.append(path)
        target = os.path.join(
            os.fsencode(self.folder), f"{len(self.calls)}-".encode() + os.path.basename(path)
        )
        os.rename(path, target)
        return target


@pytest.fixture
def ctx(paths: AppPaths, clock: FixedClock) -> Iterator[AppContext]:
    with open_app(paths, clock) as context:
        yield context


@pytest.fixture
def trash(tmp_path: Path) -> FakeTrash:
    return FakeTrash(tmp_path / "Corbeille")


def service(ctx: AppContext, trash: FakeTrash | None) -> DeletionService:
    return DeletionService(ctx.conn, ctx.clock, ctx.journal, trash)


def scalper_group(ctx: AppContext) -> int:
    rows = ctx.conn.execute(
        "SELECT g.id FROM duplicate_group g WHERE g.member_count = 3"
    ).fetchall()
    assert len(rows) == 1
    return int(rows[0][0])


def path_of(ctx: AppContext, file_id: int) -> Path:
    root, rel = ctx.conn.execute(
        "SELECT s.path, f.rel_path FROM file_record f JOIN source_root s ON s.id = f.root_id"
        " WHERE f.id = ?",
        (file_id,),
    ).fetchone()
    return Path(str(root)) / str(rel)


def test_copies_en_trop_a_la_corbeille_reference_conservee(
    tmp_path: Path, ctx: AppContext, trash: FakeTrash
) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    group = scalper_group(ctx)
    reference = int(
        ctx.conn.execute(
            "SELECT reference_file_id FROM duplicate_group WHERE id = ?", (group,)
        ).fetchone()[0]
    )
    deletion = service(ctx, trash)
    surplus = deletion.surplus_of_group(group)
    assert len(surplus) == 2 and reference not in surplus
    paths = [path_of(ctx, f) for f in surplus]
    result = deletion.trash(surplus, "doublons")
    assert (result.trashed, result.unique, result.refused) == (2, 0, [])
    assert not any(p.exists() for p in paths)
    assert path_of(ctx, reference).exists()
    assert len(list(trash.folder.iterdir())) == 2
    # Le groupe n'a plus qu'un fichier : il disparaît ; les fichiers sont marqués absents.
    assert (
        ctx.conn.execute("SELECT 1 FROM duplicate_group WHERE id = ?", (group,)).fetchone() is None
    )
    assert {
        r[0]
        for r in ctx.conn.execute(
            f"SELECT presence FROM file_record WHERE id IN ({','.join('?' * len(surplus))})",
            surplus,
        )
    } == {"missing"}
    records = deletion.records()
    assert [r.keeper for r in records] == ["copie identique conservée"] * 2
    assert all(r.state == "trashed" and r.origin == "doublons" for r in records)
    actions = [r[0] for r in ctx.conn.execute("SELECT action FROM audit_event")]
    assert actions.count("trash.file") == 2


def test_exemplaire_unique_refuse_sauf_accord_explicite(
    tmp_path: Path, ctx: AppContext, trash: FakeTrash
) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    unique = int(
        ctx.conn.execute(
            "SELECT id FROM file_record WHERE rel_path = 'MQL4/Experts/Scalper_v2.mq4'"
        ).fetchone()[0]
    )
    deletion = service(ctx, trash)
    refused = deletion.trash([unique], "familles")
    assert refused.trashed == 0
    assert "exemplaire unique" in refused.refused[0][1]
    assert path_of(ctx, unique).exists()
    accepted = deletion.trash([unique], "familles", allow_unique=True)
    assert (accepted.trashed, accepted.unique) == (1, 1)
    assert deletion.records()[0].keeper == "aucune (exemplaire unique)"


def test_tout_le_groupe_la_derniere_copie_reste(
    tmp_path: Path, ctx: AppContext, trash: FakeTrash
) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    group = scalper_group(ctx)
    members = [
        int(r[0])
        for r in ctx.conn.execute(
            "SELECT file_id FROM duplicate_member WHERE group_id = ? ORDER BY file_id", (group,)
        )
    ]
    result = service(ctx, trash).trash(members, "doublons")
    # Une copie retirée pendant l'opération ne compte jamais comme copie conservée.
    assert result.trashed == 2
    assert len(result.refused) == 1 and "exemplaire unique" in result.refused[0][1]
    assert sum(path_of(ctx, f).exists() for f in members) == 1


def test_fichier_modifie_depuis_l_analyse_refuse(
    tmp_path: Path, ctx: AppContext, trash: FakeTrash
) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    group = scalper_group(ctx)
    victim = service(ctx, trash).surplus_of_group(group)[0]
    path_of(ctx, victim).write_text("modifié par l'utilisateur", encoding="utf-8")
    result = service(ctx, trash).trash([victim], "doublons")
    assert result.trashed == 0 and "modifié" in result.refused[0][1]
    assert trash.calls == []


def test_quarantaine_validee_puis_originaux_a_la_corbeille(
    tmp_path: Path, ctx: AppContext, trash: FakeTrash
) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    quarantine = QuarantineService(ctx.conn, ctx.clock, ctx.journal, ctx.paths)
    sim = quarantine.simulate(mkd(tmp_path / "Q"))
    quarantine.execute(sim.batch_id, sim.token)
    deletion = service(ctx, trash)
    originals = deletion.originals_of_batch(sim.batch_id)
    assert len(originals) == sim.entries > 0
    # La référence disparaît hors de l'application : la copie en quarantaine sert de garantie.
    reference = int(
        ctx.conn.execute(
            "SELECT reference_file_id FROM duplicate_group WHERE member_count = 3"
        ).fetchone()[0]
    )
    path_of(ctx, reference).unlink()
    result = deletion.trash(originals, "quarantaine")
    assert result.trashed == len(originals) and result.refused == []
    kinds = {r.keeper for r in deletion.records()}
    assert "copie en quarantaine" in kinds


def test_remettre_en_place_sans_ecraser(tmp_path: Path, ctx: AppContext, trash: FakeTrash) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    deletion = service(ctx, trash)
    victim = deletion.surplus_of_group(scalper_group(ctx))[0]
    original = path_of(ctx, victim)
    content = original.read_bytes()
    deletion.trash([victim], "doublons")
    record = deletion.records()[0]
    # Un fichier occupe l'emplacement d'origine : refus, rien n'est écrasé.
    original.write_text("nouveau fichier", encoding="utf-8")
    with pytest.raises(DeletionError, match="occupe"):
        deletion.put_back(record.id)
    original.unlink()
    deletion.put_back(record.id)
    assert original.read_bytes() == content
    assert deletion.records()[0].state == "restored"
    assert (
        ctx.conn.execute("SELECT presence FROM file_record WHERE id = ?", (victim,)).fetchone()[0]
        == "present"
    )
    with pytest.raises(DeletionError, match="déjà"):
        deletion.put_back(record.id)


def test_corbeille_indisponible_ou_en_erreur(
    tmp_path: Path, ctx: AppContext, trash: FakeTrash
) -> None:
    lib = tmp_path / "lib"
    build(lib)
    analyse(ctx, lib)
    group = scalper_group(ctx)
    with pytest.raises(DeletionError, match="Mac"):
        service(ctx, None).trash([1], "doublons")
    trash.fail = True
    victim = service(ctx, trash).surplus_of_group(group)[0]
    result = service(ctx, trash).trash([victim], "doublons")
    assert result.trashed == 0 and "Corbeille" in result.refused[0][1]
    assert path_of(ctx, victim).exists()
    assert DuplicateService(ctx.conn, ctx.clock, ctx.journal).members(group)
