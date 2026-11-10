"""Familles et versions (F6) : identité logique séparée de l'empreinte binaire.

* Regroupement initial par nom logique (sans version ni « copie ») et plateforme.
* Les sources d'un même nom mais aux **paramètres trop différents** sont séparées en familles
  distinctes (homonymes) — jamais fusionnées.
* Dans une famille : copies exactes (même contenu, même nom), copies renommées (même contenu,
  autre nom), versions (contenus différents), binaires compilés, SET associés.
* Version estimée avec sa base : ``#property version`` > nom du fichier > source appariée
  (supposé) ; sinon ordre par date de modification, marqué « supposé ».
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from mtlm.matching.names import logical_key, parse_version, stem, version_in_name

METHOD_VERSION = "familles-v1"
HOMONYM_THRESHOLD = 0.5  # similarité minimale des noms de paramètres pour rester ensemble


@dataclass(frozen=True)
class FamilyInput:
    file_id: int
    rel_path: str
    root_id: int
    ext: str
    detected_type: str
    platform: str
    content_id: int | None
    prop_version: str | None
    prop_description: str | None
    inputs: frozenset[str]
    mtime_ns: int


@dataclass
class Member:
    file_id: int
    relation: str
    estimated_version: str | None
    version_basis: str | None
    confidence: str


@dataclass
class Family:
    logical_key: str
    display_name: str
    platform: str
    confidence: str
    basis: list[str] = field(default_factory=list)
    members: list[Member] = field(default_factory=list)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


class _UnionFind:
    def __init__(self, items: list[int]) -> None:
        self.parent = {i: i for i in items}

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _split_homonyms(sources: list[FamilyInput]) -> list[list[FamilyInput]]:
    uf = _UnionFind([s.file_id for s in sources])
    for i, a in enumerate(sources):
        for b in sources[i + 1 :]:
            same_content = a.content_id is not None and a.content_id == b.content_id
            same_description = bool(a.prop_description) and a.prop_description == b.prop_description
            if (
                same_content
                or same_description
                or _jaccard(a.inputs, b.inputs) >= HOMONYM_THRESHOLD
            ):
                uf.union(a.file_id, b.file_id)
    clusters: dict[int, list[FamilyInput]] = defaultdict(list)
    for source in sources:
        clusters[uf.find(source.file_id)].append(source)
    return sorted(clusters.values(), key=lambda c: (-len(c), min(s.file_id for s in c)))


def _directory(rel_path: str) -> str:
    return rel_path.rpartition("/")[0]


def _version(item: FamilyInput, paired: FamilyInput | None) -> tuple[str | None, str | None]:
    if item.prop_version:
        return item.prop_version, "#property version"
    from_name = version_in_name(item.rel_path)
    if from_name:
        return from_name, "nom du fichier"
    if paired is not None and paired.prop_version:
        return paired.prop_version, "source appariée (supposé)"
    return None, None


def build_families(items: list[FamilyInput]) -> list[Family]:
    groups: dict[tuple[str, str], list[FamilyInput]] = defaultdict(list)
    for item in items:
        key = logical_key(item.rel_path)
        if key:
            groups[(key, item.platform)].append(item)
    families: list[Family] = []
    for (key, platform), group in sorted(groups.items()):
        sources = [g for g in group if g.ext in ("mq4", "mq5", "mqh")]
        others = [g for g in group if g.ext not in ("mq4", "mq5", "mqh")]
        clusters = _split_homonyms(sources) if sources else [[]]
        cluster_of: dict[int, int] = {}
        for index, cluster in enumerate(clusters):
            for source in cluster:
                cluster_of[source.file_id] = index
        # Rattacher binaires compilés et autres fichiers : source appariée, sinon 1er groupe.
        by_dir_stem = {
            (s.root_id, _directory(s.rel_path), stem(s.rel_path).casefold()): s for s in sources
        }
        paired_of: dict[int, FamilyInput] = {}
        assigned: dict[int, list[FamilyInput]] = defaultdict(list)
        for index, cluster in enumerate(clusters):
            assigned[index].extend(cluster)
        for other in others:
            match = by_dir_stem.get(
                (other.root_id, _directory(other.rel_path), stem(other.rel_path).casefold())
            )
            if match is not None:
                paired_of[other.file_id] = match
                assigned[cluster_of[match.file_id]].append(other)
            else:
                assigned[0].append(other)
        for index in sorted(assigned):
            members_in = assigned[index]
            if not members_in:
                continue
            family = _make_family(
                key,
                platform,
                members_in,
                paired_of,
                homonym=len([c for c in clusters if c]) > 1,
                index=index,
            )
            families.append(family)
    return families


def _make_family(
    key: str,
    platform: str,
    items: list[FamilyInput],
    paired_of: dict[int, FamilyInput],
    *,
    homonym: bool,
    index: int,
) -> Family:
    items = sorted(items, key=lambda i: i.file_id)
    names = sorted({stem(i.rel_path) for i in items}, key=len)
    display = names[0] if names else key
    sources = [i for i in items if i.ext in ("mq4", "mq5", "mqh")]
    basis = [f"nom logique « {key} »", f"plateforme {platform}"]
    if len(sources) > 1:
        basis.append(
            "paramètres des sources comparables (≥ 50 % de noms communs) ou contenu "
            "/ description identiques"
        )
    if homonym:
        basis.append(
            f"HOMONYMES : même nom que d'autres fichiers aux paramètres différents "
            f"(groupe {index + 1})"
        )
    confidence = "probable" if sources else "possible"
    if not sources:
        basis.append("aucune source lisible : regroupement par le nom uniquement")
    family = Family(key, display, platform, confidence, basis)
    reference_by_content: dict[int, FamilyInput] = {}
    distinct_source_contents = {s.content_id for s in sources if s.content_id is not None}
    compiled_stems = {(paired_of[i.file_id].file_id) for i in items if i.file_id in paired_of}
    for item in items:
        paired = paired_of.get(item.file_id)
        version, version_basis = _version(item, paired)
        reference = reference_by_content.get(item.content_id) if item.content_id else None
        if reference is not None:
            same_name = stem(reference.rel_path).casefold() == stem(item.rel_path).casefold()
            relation = "exact_copy" if same_name else "renamed_copy"
            member_confidence = "certain"
        else:
            if item.content_id is not None:
                reference_by_content[item.content_id] = item
            if item.detected_type == "set":
                relation, member_confidence = "set_for", "probable"
            elif item.ext in ("ex4", "ex5"):
                relation = "compiled_variant"
                member_confidence = "probable" if paired is not None else "possible"
            elif item.ext in ("mq4", "mq5", "mqh"):
                if homonym:
                    relation = "homonym_different"
                elif len(distinct_source_contents) > 1 or item.file_id not in compiled_stems:
                    relation = "version_variant"
                else:
                    relation = "source_of"
                member_confidence = "probable"
            else:
                relation, member_confidence = "version_variant", "possible"
        family.members.append(
            Member(item.file_id, relation, version, version_basis, member_confidence)
        )
    _order_versions(family, items)
    return family


def _order_versions(family: Family, items: list[FamilyInput]) -> None:
    """Pour les membres sans version déclarée : ordre par date, marqué « supposé »."""
    by_id = {i.file_id: i for i in items}
    undated = [
        m
        for m in family.members
        if m.estimated_version is None
        and m.relation in ("version_variant", "compiled_variant", "source_of")
    ]
    if len(undated) < 2:
        return
    for rank, member in enumerate(
        sorted(undated, key=lambda m: by_id[m.file_id].mtime_ns), start=1
    ):
        member.estimated_version = f"n°{rank}"
        member.version_basis = "ordre des dates de modification (supposé)"


def version_sort_key(version: str | None) -> tuple[int, ...]:
    return parse_version(version) or (0,)
