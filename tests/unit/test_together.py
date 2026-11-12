"""1.3.0 — indice « créés ensemble » : petits lots de fichiers datés du même instant."""

from __future__ import annotations

from mtlm.matching.together import MAX_BATCH, creation_batches

S = 1_000_000_000


def test_petit_lot_reconnu_et_fichiers_isoles_ignores() -> None:
    batches = creation_batches([(1, 100 * S), (2, 101 * S), (3, 102 * S), (4, 500 * S), (5, 0)])
    assert batches[1] == batches[2] == batches[3] == (1, 3)
    assert 4 not in batches and 5 not in batches  # isolé ; date inconnue


def test_grand_lot_ignore_car_il_ne_prouve_rien() -> None:
    items = [(i, 100 * S + i) for i in range(MAX_BATCH + 1)]
    assert creation_batches(items) == {}


def test_lots_separes_par_plus_de_deux_secondes() -> None:
    batches = creation_batches([(1, 10 * S), (2, 11 * S), (3, 20 * S), (4, 21 * S)])
    assert batches[1][0] != batches[3][0]
