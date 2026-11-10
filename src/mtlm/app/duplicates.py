"""Doublons et similarités (F7, phase 8) — séparation stricte (D-008).

* **Doublon exact** : même taille **et** même SHA-256 validé. Un groupe a une **référence**
  (proposée : chemin le plus court puis le plus ancien ; modifiable par l'utilisateur), qui
  reste toujours en place. Les autres membres sont *admissibles à la quarantaine* seulement
  s'ils sont stables, présents, ordinaires, non iCloud, pas déjà en quarantaine.
* **Équivalent normalisé** : sources MQL identiques une fois commentaires et espaces retirés,
  mais octets différents → table ``similarity_pair`` (``text_normalized_equal``).
* **Similaire** : sources dont la similarité estimée (esquisse « bottom-k » de 128 valeurs sur
  des fragments de 5 jetons) dépasse le seuil (0,80 par défaut) → ``text_similar`` ;
  SET de mêmes paramètres aux valeurs proches → ``set_similar``.
* Seuls les doublons exacts admissibles peuvent être proposés à la quarantaine.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass

from mtlm import ENGINE_VERSION
from mtlm.app.jobs import JobStore
from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock, iso_utc
from mtlm.core.errors import MtlmError
from mtlm.fs.reader import ReadOnlyFile
from mtlm.store.database import transaction

SIMILARITY_THRESHOLD = 0.80
SKETCH_SIZE = 128
MIN_SHARED = 16  # valeurs d'esquisse communes minimales pour être candidat
MAX_SET_GROUP = 60
METHOD_TEXT = "bottom-k-128/shingle-5"
METHOD_SET = "set-valeurs-normalisees"


CERTAINTY_RANK = {"certain": 0, "probable": 1, "possible": 2, "unknown": 3}
_COPY_WORDS = re.compile(
    r"(?:^|[^a-z])(copie|copies|copy|backup|sauvegarde|old|ancien|tmp)"
    r"(?:[^a-z]|$)",
    re.I,
)


def reference_rank(rel_path: str, mtime_ns: int, file_id: int, certainty: int) -> tuple[int, ...]:
    """Ordre de préférence de la copie conservée : hors dossiers « copie/backup/old », mieux
    reconnue, chemin le plus court, plus ancienne, plus petit identifiant."""
    noisy = 1 if _COPY_WORDS.search(rel_path) else 0
    return (noisy, certainty, len(rel_path), mtime_ns, file_id)


class DuplicateError(MtlmError):
    """Groupe ou fichier inconnu, ou choix de référence invalide."""


@dataclass
class DuplicateSummary:
    job_id: int
    state: str
    groups: int = 0
    duplicate_files: int = 0
    admissible: int = 0
    reclaimable_bytes: int = 0
    normalized_equal: int = 0
    similar_text: int = 0
    similar_sets: int = 0


@dataclass(frozen=True)
class GroupRow:
    id: int
    sha256_hex: str
    size: int
    member_count: int
    reference_file_id: int | None
    reference_chosen_by_user: bool


@dataclass(frozen=True)
class MemberRow:
    file_id: int
    rel_path: str
    source_path: str
    is_reference: bool
    admissible: bool
    reason: str | None


@dataclass(frozen=True)
class SimilarRow:
    file_a: int
    path_a: str
    file_b: int
    path_b: str
    kind: str
    score: float
    method: str


def _unpack(sketch: bytes) -> list[int]:
    return [int.from_bytes(sketch[i : i + 8], "big") for i in range(0, len(sketch), 8)]


def estimate_jaccard(a: list[int], b: list[int], k: int = SKETCH_SIZE) -> float:
    """Estimateur « bottom-k » : parmi les k plus petites valeurs de l'union, part de celles
    présentes dans les deux esquisses."""
    if not a or not b:
        return 0.0
    union = sorted(set(a) | set(b))[:k]
    sa, sb = set(a), set(b)
    return sum(1 for h in union if h in sa and h in sb) / len(union)


class DuplicateService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, journal: AuditJournal) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal
        self._jobs = JobStore(conn, clock)

    # ---- calcul ----------------------------------------------------------------------------
    def compute(self, *, threshold: float = SIMILARITY_THRESHOLD) -> DuplicateSummary:
        job_id = self._jobs.create("duplicates", {"seuil": threshold})
        summary = DuplicateSummary(job_id=job_id, state="running")
        now = iso_utc(self._clock.now())
        with transaction(self._conn):
            self._exact_groups(summary, now)
            self._conn.execute("DELETE FROM similarity_pair")
            self._normalized_and_similar(summary, threshold, now)
            self._similar_sets(summary, now)
        summary.state = "completed"
        self._jobs.finish(job_id, "completed", asdict(summary))
        self._journal.append(
            ACTOR_USER, "duplicates.compute", f"seuil={threshold}", details=asdict(summary)
        )
        return summary

    def _exact_groups(self, summary: DuplicateSummary, now: str) -> None:
        certainty = {
            int(fid): CERTAINTY_RANK.get(level, 9)
            for fid, level in self._conn.execute("SELECT file_id, certainty FROM file_analysis")
        }
        user_refs = {
            bytes(sha): int(ref)
            for sha, ref in self._conn.execute(
                "SELECT sha256, reference_file_id FROM duplicate_group"
                " WHERE reference_chosen_by_user = 1 AND reference_file_id IS NOT NULL"
            )
        }
        self._conn.execute("DELETE FROM duplicate_member")
        self._conn.execute("DELETE FROM duplicate_group")
        members: dict[int, list[tuple[int, str, int, int, int, int, str]]] = defaultdict(list)
        for row in self._conn.execute(
            "SELECT f.content_id, f.id, f.rel_path, f.mtime_ns, f.in_quarantine, f.is_dataless,"
            " f.file_type, f.size FROM file_record f JOIN source_root s ON s.id = f.root_id"
            " WHERE s.status = 'ok' AND f.presence = 'present' AND f.hash_state = 'validated'"
            " AND f.content_id IN (SELECT content_id FROM file_record WHERE presence = 'present'"
            "   AND hash_state = 'validated' GROUP BY content_id HAVING count(*) > 1)"
            " ORDER BY f.content_id, f.id"
        ):
            members[int(row[0])].append(
                (
                    int(row[1]),
                    row[2],
                    int(row[3] or 0),
                    int(row[4]),
                    int(row[5]),
                    int(row[7] or 0),
                    row[6],
                )
            )
        shas = dict(
            self._conn.execute(
                "SELECT id, sha256 FROM content WHERE id IN"
                f" ({','.join(str(c) for c in members) or 'NULL'})"
            ).fetchall()
        )
        for content_id, files in members.items():
            sha = bytes(shas[content_id])
            size = files[0][5]
            ids = {f[0] for f in files}
            chosen = user_refs.get(sha)
            by_user = chosen in ids
            reference = (
                chosen
                if by_user
                else min(
                    files, key=lambda f: reference_rank(f[1], f[2], f[0], certainty.get(f[0], 9))
                )[0]
            )
            cursor = self._conn.execute(
                "INSERT INTO duplicate_group(sha256, size, member_count, reference_file_id,"
                " verified_at, verification, reference_chosen_by_user, engine_version)"
                " VALUES (?, ?, ?, ?, ?, 'sha256', ?, ?)",
                (sha, size, len(files), reference, now, int(by_user), ENGINE_VERSION),
            )
            group_id = int(cursor.lastrowid or 0)
            summary.groups += 1
            summary.duplicate_files += len(files) - 1
            for file_id, _path, _mtime, quarantined, dataless, _size, file_type in files:
                is_ref = file_id == reference
                reason = None
                if is_ref:
                    reason = "référence du groupe (reste en place)"
                elif quarantined:
                    reason = "déjà en quarantaine"
                elif dataless:
                    reason = "fichier iCloud non téléchargé"
                elif file_type != "file":
                    reason = "pas un fichier ordinaire"
                admissible = not is_ref and reason is None
                summary.admissible += admissible
                summary.reclaimable_bytes += size if admissible else 0
                self._conn.execute(
                    "INSERT INTO duplicate_member(group_id, file_id, is_reference,"
                    " admissible_for_quarantine, inadmissible_reason) VALUES (?, ?, ?, ?, ?)",
                    (group_id, file_id, int(is_ref), int(admissible), reason),
                )

    def _representatives(self) -> dict[int, int]:
        """Contenu → fichier présent représentatif (plus petit identifiant)."""
        return {
            int(c): int(f)
            for c, f in self._conn.execute(
                "SELECT content_id, min(id) FROM file_record WHERE presence = 'present'"
                " AND hash_state = 'validated' GROUP BY content_id"
            )
        }

    def _add_pair(self, a: int, b: int, kind: str, score: float, method: str, now: str) -> None:
        low, high = sorted((a, b))
        self._conn.execute(
            "INSERT OR REPLACE INTO similarity_pair(file_a, file_b, kind, score, method,"
            " computed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (low, high, kind, round(score, 4), method, now),
        )

    def _normalized_and_similar(
        self, summary: DuplicateSummary, threshold: float, now: str
    ) -> None:
        reps = self._representatives()
        sources = [
            (int(c), bytes(n) if n is not None else b"", bytes(m) if m is not None else b"")
            for c, n, m in self._conn.execute(
                "SELECT content_id, normalized_sha256, minhash FROM mql_source_meta"
            )
            if int(c) in reps
        ]
        by_normalized: dict[bytes, list[int]] = defaultdict(list)
        for content_id, normalized, _ in sources:
            if normalized:
                by_normalized[normalized].append(content_id)
        equal_pairs: set[tuple[int, int]] = set()
        for contents in by_normalized.values():
            for i, a in enumerate(contents):
                for b in contents[i + 1 :]:
                    self._add_pair(
                        reps[a],
                        reps[b],
                        "text_normalized_equal",
                        1.0,
                        "texte normalisé identique",
                        now,
                    )
                    equal_pairs.add((min(a, b), max(a, b)))
                    summary.normalized_equal += 1
        sketches = {c: _unpack(m) for c, _, m in sources if m}
        index: dict[int, list[int]] = defaultdict(list)
        for content_id, values in sketches.items():
            for value in values:
                index[value].append(content_id)
        shared: dict[tuple[int, int], int] = defaultdict(int)
        for contents in index.values():
            if len(contents) > 200:  # fragment omniprésent (ex. modèle commun) : non discriminant
                continue
            for i, a in enumerate(contents):
                for b in contents[i + 1 :]:
                    shared[(min(a, b), max(a, b))] += 1
        for (a, b), count in shared.items():
            if count < MIN_SHARED or (a, b) in equal_pairs:
                continue
            score = estimate_jaccard(sketches[a], sketches[b])
            if score >= threshold:
                self._add_pair(reps[a], reps[b], "text_similar", score, METHOD_TEXT, now)
                summary.similar_text += 1

    def _similar_sets(self, summary: DuplicateSummary, now: str) -> None:
        params: dict[int, dict[str, str]] = defaultdict(dict)
        for file_id, name, value in self._conn.execute(
            "SELECT sp.file_id, sp.name, coalesce(sp.normalized_value, sp.raw_value)"
            " FROM set_parameter sp JOIN file_record f ON f.id = sp.file_id"
            " WHERE f.presence = 'present'"
        ):
            params[int(file_id)][name] = value
        contents = dict(
            self._conn.execute(
                "SELECT id, content_id FROM file_record WHERE ext = 'set' AND presence = 'present'"
            ).fetchall()
        )
        groups: dict[frozenset[str], list[int]] = defaultdict(list)
        for file_id, values in params.items():
            if values:
                groups[frozenset(values)].append(file_id)
        for members in groups.values():
            members = sorted(members)[:MAX_SET_GROUP]
            for i, a in enumerate(members):
                for b in members[i + 1 :]:
                    if contents.get(a) == contents.get(b):
                        continue  # doublon exact : déjà traité comme tel
                    same = sum(params[a][k] == params[b][k] for k in params[a])
                    score = same / len(params[a])
                    if score >= SIMILARITY_THRESHOLD:
                        self._add_pair(a, b, "set_similar", score, METHOD_SET, now)
                        summary.similar_sets += 1

    # ---- consultation ------------------------------------------------------------------------
    def groups(self, limit: int = 200, after_id: int = 0) -> list[GroupRow]:
        return [
            GroupRow(int(r[0]), bytes(r[1]).hex(), int(r[2]), int(r[3]), r[4], bool(r[5]))
            for r in self._conn.execute(
                "SELECT id, sha256, size, member_count, reference_file_id,"
                " reference_chosen_by_user FROM duplicate_group WHERE id > ?"
                " ORDER BY size * (member_count - 1) DESC, id LIMIT ?",
                (after_id, limit),
            )
        ]

    def members(self, group_id: int) -> list[MemberRow]:
        return [
            MemberRow(int(r[0]), r[1], r[2], bool(r[3]), bool(r[4]), r[5])
            for r in self._conn.execute(
                "SELECT m.file_id, f.rel_path, s.path, m.is_reference,"
                " m.admissible_for_quarantine, m.inadmissible_reason FROM duplicate_member m"
                " JOIN file_record f ON f.id = m.file_id JOIN source_root s ON s.id = f.root_id"
                " WHERE m.group_id = ? ORDER BY m.is_reference DESC, f.rel_path",
                (group_id,),
            )
        ]

    def similar(self, kind: str | None = None, limit: int = 200) -> list[SimilarRow]:
        clause, params = ("WHERE p.kind = ?", [kind]) if kind else ("", [])
        return [
            SimilarRow(int(r[0]), r[1], int(r[2]), r[3], r[4], float(r[5]), r[6])
            for r in self._conn.execute(
                "SELECT p.file_a, fa.rel_path, p.file_b, fb.rel_path, p.kind, p.score, p.method"
                " FROM similarity_pair p JOIN file_record fa ON fa.id = p.file_a"
                f" JOIN file_record fb ON fb.id = p.file_b {clause}"
                " ORDER BY p.score DESC, p.file_a LIMIT ?",
                (*params, limit),
            )
        ]

    def set_reference(self, group_id: int, file_id: int) -> None:
        member = self._conn.execute(
            "SELECT 1 FROM duplicate_member WHERE group_id = ? AND file_id = ?",
            (group_id, file_id),
        ).fetchone()
        if member is None:
            raise DuplicateError(f"Le fichier {file_id} n'appartient pas au groupe {group_id}")
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE duplicate_group SET reference_file_id = ?, reference_chosen_by_user = 1"
                " WHERE id = ?",
                (file_id, group_id),
            )
            self._conn.execute(
                "UPDATE duplicate_member SET is_reference = (file_id = ?),"
                " admissible_for_quarantine = 0,"
                " inadmissible_reason = CASE WHEN file_id = ? THEN"
                " 'référence du groupe (reste en place)' ELSE inadmissible_reason END"
                " WHERE group_id = ?",
                (file_id, file_id, group_id),
            )
            self._conn.execute(
                "UPDATE duplicate_member SET admissible_for_quarantine = 1,"
                " inadmissible_reason = NULL WHERE group_id = ? AND file_id <> ? AND file_id IN"
                " (SELECT id FROM file_record WHERE in_quarantine = 0 AND is_dataless = 0"
                "  AND file_type = 'file' AND presence = 'present')",
                (group_id, file_id),
            )
        self._journal.append(
            ACTOR_USER, "duplicates.reference", f"groupe={group_id}", details={"reference": file_id}
        )

    # ---- vérification octet par octet (collision théorique) ---------------------------------
    def verify_bytewise(self, group_id: int) -> bool:
        """Compare octet par octet chaque membre à la référence (lecture seule). Retourne vrai
        si tous sont identiques ; sinon le groupe est marqué non vérifié et rien n'est admis."""
        rows = self._conn.execute(
            "SELECT m.file_id, s.path, f.rel_path_bytes, m.is_reference FROM duplicate_member m"
            " JOIN file_record f ON f.id = m.file_id JOIN source_root s ON s.id = f.root_id"
            " WHERE m.group_id = ? ORDER BY m.is_reference DESC",
            (group_id,),
        ).fetchall()
        if not rows:
            raise DuplicateError(f"Groupe {group_id} inconnu")
        paths = [os.path.join(os.fsencode(r[1]), bytes(r[2])) for r in rows]  # noqa: PTH118
        identical = all(_same_bytes(paths[0], other) for other in paths[1:])
        with transaction(self._conn):
            if identical:
                self._conn.execute(
                    "UPDATE duplicate_group SET verification = 'sha256+bytewise', verified_at = ?"
                    " WHERE id = ?",
                    (iso_utc(self._clock.now()), group_id),
                )
            else:
                self._conn.execute(
                    "UPDATE duplicate_member SET admissible_for_quarantine = 0,"
                    " inadmissible_reason = 'contenu différent à la vérification octet par octet'"
                    " WHERE group_id = ?",
                    (group_id,),
                )
        self._journal.append(
            ACTOR_USER,
            "duplicates.bytewise",
            f"groupe={group_id}",
            result="ok" if identical else "refused",
            details={"identiques": identical},
        )
        return identical


def _same_bytes(a: bytes, b: bytes) -> bool:
    try:
        with ReadOnlyFile(a) as fa, ReadOnlyFile(b) as fb:
            if fa.opened_identity.size != fb.opened_identity.size:
                return False
            return all(left == right for left, right in zip(fa.chunks(), fb.chunks(), strict=False))
    except OSError:
        return False
