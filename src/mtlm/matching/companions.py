"""Fichiers liés à un outil (1.3.0) : images, sons, documents, modèles, includes.

Pour chaque fichier annexe, on cherche l'outil (robot, indicateur, script…) avec lequel il a
été fait, à partir d'indices **expliqués** :

* **certain** : le fichier est **cité dans le code** de l'outil (``#resource``, ou chaîne
  « logo.bmp », « alerte.wav »…) ;
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
}
LEVELS = {3: "certain", 2: "probable", 1: "possible"}
MAX_TOOLS = 5


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


def placement(companion: Companion, tool: Tool, tool_dirs: set[tuple[int, str]]) -> str:
    if (companion.root_id, companion.directory) == (tool.root_id, tool.directory):
        return "avec_son_robot"
    if (companion.root_id, companion.directory) in tool_dirs:
        return "avec_autre_robot"
    return "en_vrac"


def link_companions(
    companions: list[Companion],
    tools: list[Tool],
    cited_by: dict[str, set[int]],
) -> list[Link]:
    """``cited_by`` : nom de fichier (minuscules) → outils dont le code le cite."""
    by_id = {t.file_id: t for t in tools}
    by_dir: dict[tuple[int, str], list[Tool]] = defaultdict(list)
    by_batch: dict[int, list[Tool]] = defaultdict(list)
    by_key: dict[str, list[Tool]] = defaultdict(list)
    for tool in tools:
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
