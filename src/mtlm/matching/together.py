"""Indice « créés ensemble » : petits lots de fichiers datés du même instant.

Des fichiers livrés ensemble (même archive, même téléchargement, même enregistrement) gardent
souvent une date de modification identique à quelques secondes près. Un **petit** lot (au plus
``MAX_BATCH`` fichiers) daté du même instant est un indice qu'ils vont ensemble. Les grands lots
(copie ou extraction de toute une bibliothèque d'un coup) ne prouvent rien et sont ignorés.
C'est un indice, jamais une preuve : il ne fait que compléter les autres.
"""

from __future__ import annotations

WINDOW_NS = 2_000_000_000  # 2 secondes entre deux fichiers consécutifs du lot
MAX_BATCH = 20


def creation_batches(
    items: list[tuple[int, int]], *, window_ns: int = WINDOW_NS, max_size: int = MAX_BATCH
) -> dict[int, tuple[int, int]]:
    """``items`` : (fichier, date de modification en ns). Retourne, pour chaque fichier d'un
    petit lot (2 à ``max_size`` fichiers), (numéro du lot, taille du lot)."""
    ordered = sorted((m, f) for f, m in items if m > 0)
    result: dict[int, tuple[int, int]] = {}
    start = 0
    batch_no = 0
    for index in range(1, len(ordered) + 1):
        if index < len(ordered) and ordered[index][0] - ordered[index - 1][0] <= window_ns:
            continue
        size = index - start
        if 2 <= size <= max_size:
            batch_no += 1
            for _m, file_id in ordered[start:index]:
                result[file_id] = (batch_no, size)
        start = index
    return result
