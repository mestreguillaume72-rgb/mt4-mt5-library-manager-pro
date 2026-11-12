"""Fichiers liés à un outil (1.3.0) : images, sons, documents, modèles, includes.

Pour chaque fichier annexe, on cherche l'outil (robot, indicateur, script…) avec lequel il a
été fait, à partir d'indices **expliqués** :

* **certain** : le fichier est **cité dans le code** de l'outil (``#resource``, chaîne
  « logo.bmp », ``#include``, ``#import "x.dll"``), ou c'est un **modèle de graphique**
  (``.tpl``) qui charge cet outil ;
* **probable** : même dossier que l'outil et nom proche, ou même dossier et **créés ensemble**
  (petit lot de fichiers datés du même instant) ;
* **possible** : seul outil du dossier, créés ensemble dans un autre dossier, ou même nom
  ailleurs.

Seuls les liens du meilleur niveau sont gardés (au plus 5 outils). Le **placement** dit si le
fichier est rangé avec son outil, en vrac, ou rangé avec un autre outil.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from mtlm.matching.associations import name_similarity
from mtlm.matching.names import logical_key

METHOD_VERSION = "fichiers-lies-v1"
KINDS = {
    "bmp": "image",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "gif": "image",
    "ico": "image",
    "wav": "son",
    "mp3": "son",
    "pdf": "document",
    "txt": "document",
    "htm": "document",
    "html": "document",
    "csv": "document",
    "ini": "document",
    "tpl": "modele",
    "mqh": "include",
    "dll": "dll",
}
LEVELS = {3: "certain", 2: "probable", 1: "possible"}
MAX_TOOLS = 10


@dataclass(frozen=True)
class Tool:
    file_id: int
    root_id: int
    directory: str
    name: str
    batch: int | None = None


@dataclass(frozen=True)
class Companion:
    file_id: int
    root_id: int
    directory: str
    name: str
    kind: str
    batch: int | None = None


@dataclass
class Link:
    companion_id: int
    tool_id: int
    confidence: str
    placement: str
    evidence: list[str] = field(default_factory=list)


#: Dossiers prévus par MetaTrader pour ces fichiers (ils n'y sont donc pas « en vrac »).
STANDARD_DIRS = {"libraries", "include", "images", "sounds", "files", "templates", "presets"}


def is_standard_dir(directory: str) -> bool:
    return directory.rpartition("/")[2].casefold() in STANDARD_DIRS


def placement(companion: Companion, tool: Tool, tool_dirs: set[tuple[int, str]]) -> str:
    if (companion.root_id, companion.directory) == (tool.root_id, tool.directory):
        return "avec_son_robot"
    if is_standard_dir(companion.directory):
        return "dossier_standard"
    if (companion.root_id, companion.directory) in tool_dirs:
        return "avec_autre_robot"
    return "en_vrac"


def _stem_key(name: str) -> str:
    stem, dot, _ext = name.rpartition(".")
    return (stem if dot else name).casefold()


def _ext(name: str) -> str:
    return name.rpartition(".")[2].casefold() if "." in name else ""


@dataclass(frozen=True)
class Dependency:
    user_id: int
    used_id: int
    kind: str  # icustom | import | resource
    evidence: str


_FAMILY = {"mq4": "4", "ex4": "4", "mq5": "5", "ex5": "5"}


def link_tools(tools: list[Tool], calls: list[tuple[int, str, str]]) -> list[Dependency]:
    """Outil → outils dont il a besoin. ``calls`` : (outil, cible en minuscules, nature) avec
    nature « icustom » (nom d'indicateur sans extension), « import » ou « resource » (nom de
    fichier .ex4/.ex5 complet). Un indicateur appelé depuis un robot MT4 n'est cherché que
    parmi les fichiers MT4 (et de même pour MT5)."""
    by_id = {t.file_id: t for t in tools}
    by_stem: dict[str, list[Tool]] = defaultdict(list)
    by_name: dict[str, list[Tool]] = defaultdict(list)
    for tool in tools:
        by_stem[_stem_key(tool.name)].append(tool)
        by_name[tool.name.casefold()].append(tool)
    labels = {
        "icustom": "appelé par iCustom dans le code",
        "import": "bibliothèque importée (#import)",
        "resource": "intégré comme ressource (#resource)",
    }
    found: dict[tuple[int, int], Dependency] = {}
    for user_id, target, kind in calls:
        user = by_id.get(user_id)
        if user is None:
            continue
        if kind == "icustom":
            family = _FAMILY.get(_ext(user.name))
            candidates = [
                t for t in by_stem.get(target, []) if family in (None, _FAMILY.get(_ext(t.name)))
            ]
        else:
            candidates = by_name.get(target, [])
        for used in candidates:
            if used.file_id != user_id:
                found.setdefault(
                    (user_id, used.file_id),
                    Dependency(user_id, used.file_id, kind, labels[kind]),
                )
    return sorted(found.values(), key=lambda d: (d.user_id, d.used_id))


def link_companions(
    companions: list[Companion],
    tools: list[Tool],
    cited_by: dict[str, set[int]],
    cites: dict[int, set[str]] | None = None,
) -> list[Link]:
    """``cited_by`` : nom de fichier (minuscules) → outils dont le code le cite ;
    ``cites`` : fichier annexe (modèle .tpl) → noms d'outils qu'il charge (minuscules)."""
    cites = cites or {}
    by_id = {t.file_id: t for t in tools}
    by_dir: dict[tuple[int, str], list[Tool]] = defaultdict(list)
    by_batch: dict[int, list[Tool]] = defaultdict(list)
    by_key: dict[str, list[Tool]] = defaultdict(list)
    by_stem: dict[str, list[Tool]] = defaultdict(list)
    for tool in tools:
        by_stem[_stem_key(tool.name)].append(tool)
        by_dir[(tool.root_id, tool.directory)].append(tool)
        if tool.batch is not None:
            by_batch[tool.batch].append(tool)
        key = logical_key(tool.name)
        if key:
            by_key[key].append(tool)
    tool_dirs = set(by_dir)
    links: list[Link] = []
    for companion in companions:
        found: dict[int, tuple[int, list[str]]] = {}

        def add(
            tool: Tool, rank: int, reason: str, found: dict[int, tuple[int, list[str]]] = found
        ) -> None:
            current_rank, reasons = found.get(tool.file_id, (0, []))
            if reason not in reasons:
                reasons = [*reasons, reason]
            found[tool.file_id] = (max(current_rank, rank), reasons)

        for tool_id in sorted(cited_by.get(companion.name.casefold(), ())):
            if tool_id in by_id:
                add(by_id[tool_id], 3, "cité dans le code de l'outil")
        for stem in sorted(cites.get(companion.file_id, ())):
            for tool in by_stem.get(stem, []):
                add(tool, 3, "le modèle de graphique charge cet outil")
        same_dir = by_dir.get((companion.root_id, companion.directory), [])
        distinct = {logical_key(t.name) for t in same_dir}
        together = (
            {t.file_id for t in by_batch.get(companion.batch, [])}
            if companion.batch is not None
            else set()
        )
        for tool in same_dir:
            if name_similarity(tool.name, companion.name) >= 0.85:
                add(tool, 2, "même dossier et nom proche")
            if tool.file_id in together:
                add(tool, 2, "même dossier et créés ensemble")
            if len(distinct) == 1:
                add(tool, 1, "seul outil du dossier")
        for tool_id in together:
            add(by_id[tool_id], 1, "créés ensemble (même date de modification, petit lot)")
        for tool in by_key.get(logical_key(companion.name), []):
            add(tool, 1, "même nom")
        if not found:
            continue
        best = max(rank for rank, _ in found.values())
        chosen = sorted(tool_id for tool_id, (rank, _) in found.items() if rank == best)
        for tool_id in chosen[:MAX_TOOLS]:
            tool = by_id[tool_id]
            links.append(
                Link(
                    companion.file_id,
                    tool_id,
                    LEVELS[best],
                    placement(companion, tool, tool_dirs),
                    found[tool_id][1],
                )
            )
    return links
