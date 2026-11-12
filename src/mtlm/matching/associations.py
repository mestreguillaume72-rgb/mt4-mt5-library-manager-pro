"""Moteur d'association robot ↔ SET : score pondéré **explicable** (F5, D-009).

Chaque critère produit une preuve « pour », « contre » ou « incertitude » avec sa valeur et
son poids. Le score (0–100) est la somme pondérée ; le niveau en découle avec des règles dures :

* « forte » exige ≥ 75 **et** une preuve paramétrique (≥ 80 % des paramètres du SET existent
  dans le robot) ;
* un robot sans source lisible (EX4/EX5 seul) est plafonné à « à vérifier » : ses paramètres
  ne sont pas accessibles ;
* deux robots distincts presque aussi plausibles ⇒ ambiguïté : niveau plafonné à « moyenne » ;
* aucune association n'est jamais validée sans action de l'utilisateur.

Pondérations : couverture des noms de paramètres 40, compatibilité des types 15,
valeurs par défaut 5, similarité des noms de fichiers 20, emplacement 10, plateforme 10,
pénalité paramètres inconnus du robot jusqu'à −20.

Version 2 (1.3.0), indices « faits pour aller ensemble » :

* le **nom du robot écrit par MetaTrader dans l'en-tête du SET** compte comme un nom identique
  (et un nom différent y est signalé « contre ») ;
* robot et SET d'un **petit lot de fichiers datés du même instant** (voir
  :mod:`mtlm.matching.together`) : l'emplacement vaut au moins « créés ensemble » (0,7).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from mtlm.matching.names import logical_key

METHOD_VERSION = "associations-v2"
WEIGHTS = {
    "coverage": 40.0,
    "types": 15.0,
    "defaults": 5.0,
    "name": 20.0,
    "location": 10.0,
    "platform": 10.0,
}
PENALTY_UNKNOWN = 20.0
MIN_SCORE = 25.0
AMBIGUITY_GAP = 5.0

_INT_TYPES = {"int", "uint", "long", "ulong", "short", "ushort", "char", "uchar"}
_FLOAT_TYPES = {"double", "float"}


@dataclass(frozen=True)
class RobotInfo:
    file_id: int
    name: str  # nom de fichier
    directory: str
    root_id: int
    platform: str
    content_id: int | None
    has_source: bool
    inputs: dict[str, tuple[str, str | None]]  # nom → (type MQL, défaut brut)
    batch: tuple[int, int] | None = None  # petit lot « créés ensemble » : (numéro, taille)


@dataclass(frozen=True)
class SetInfo:
    file_id: int
    name: str
    directory: str
    root_id: int
    format: str
    params: dict[str, tuple[str, str | None, str]]  # nom → (brut, normalisé, type estimé)
    named_robot: str | None = None  # nom du robot écrit dans l'en-tête du SET
    batch: tuple[int, int] | None = None


@dataclass(frozen=True)
class Evidence:
    kind: str
    weight: float
    value: float
    polarity: str  # pour | contre | incertitude
    detail: dict[str, object]


@dataclass
class Candidate:
    robot: RobotInfo
    score: float
    level: str
    evidence: list[Evidence] = field(default_factory=list)
    coverage: float = 0.0


def value_fits_type(mql_type: str, raw: str, normalized: str | None) -> bool:
    t = mql_type.lower()
    value = (normalized if normalized is not None else raw).strip()
    if t in _INT_TYPES or t.startswith("enum_"):
        return bool(re.fullmatch(r"[+-]?\d+", value))
    if t in _FLOAT_TYPES:
        try:
            float(value.replace(",", "."))
            return True
        except ValueError:
            return False
    if t == "bool":
        return value.lower() in ("true", "false", "0", "1")
    return True  # string, color, datetime, types énumérés de l'utilisateur : tout est lisible


def normalize_default(mql_type: str, default: str | None) -> str | None:
    if default is None:
        return None
    value = default.strip().strip('"')
    t = mql_type.lower()
    try:
        if t in _FLOAT_TYPES:
            return repr(float(value))
        if t in _INT_TYPES:
            return str(int(value))
    except ValueError:
        return value
    if t == "bool":
        return value.lower()
    return value


def name_similarity(robot_name: str, set_name: str) -> float:
    r, s = logical_key(robot_name), logical_key(set_name)
    if not r or not s:
        return 0.0
    if s == r or s.startswith(r) or r.startswith(s):
        return 1.0
    if r in s:
        return 0.85
    return difflib.SequenceMatcher(None, r, s).ratio() * 0.8


def location_score(robot: RobotInfo, set_info: SetInfo) -> tuple[float, str]:
    if robot.root_id == set_info.root_id and robot.directory == set_info.directory:
        return 1.0, "même dossier"
    robot_top = robot.directory.split("/")[0].casefold()
    set_top = set_info.directory.split("/")[0].casefold()
    if robot.root_id == set_info.root_id and robot_top and robot_top == set_top:
        return 0.5, f"même arborescence « {robot.directory.split('/')[0]} »"
    if robot.root_id == set_info.root_id:
        return 0.2, "même source"
    return 0.0, "sources différentes"


def score_pair(robot: RobotInfo, set_info: SetInfo) -> Candidate:
    evidence: list[Evidence] = []
    total = 0.0
    coverage = 0.0
    keys = set(set_info.params)
    if robot.has_source and robot.inputs:
        inputs = set(robot.inputs)
        common = keys & inputs
        cov_set = len(common) / len(keys) if keys else 0.0
        cov_robot = len(common) / len(inputs)
        coverage = cov_set
        value = 0.75 * cov_set + 0.25 * cov_robot
        total += WEIGHTS["coverage"] * value
        evidence.append(
            Evidence(
                "couverture_parametres",
                WEIGHTS["coverage"],
                value,
                "pour" if common else "contre",
                {
                    "communs": len(common),
                    "parametres_set": len(keys),
                    "parametres_robot": len(inputs),
                    "exemples": sorted(common)[:8],
                },
            )
        )
        if common:
            fits = [
                n
                for n in common
                if value_fits_type(robot.inputs[n][0], set_info.params[n][0], set_info.params[n][1])
            ]
            ratio = len(fits) / len(common)
            total += WEIGHTS["types"] * ratio
            evidence.append(
                Evidence(
                    "compatibilite_types",
                    WEIGHTS["types"],
                    ratio,
                    "pour" if ratio >= 0.9 else "contre",
                    {
                        "compatibles": len(fits),
                        "verifies": len(common),
                        "incompatibles": sorted(common - set(fits))[:8],
                    },
                )
            )
            equal = [
                n
                for n in common
                if normalize_default(robot.inputs[n][0], robot.inputs[n][1])
                == set_info.params[n][1]
            ]
            ratio_defaults = len(equal) / len(common)
            total += WEIGHTS["defaults"] * ratio_defaults
            evidence.append(
                Evidence(
                    "valeurs_par_defaut",
                    WEIGHTS["defaults"],
                    ratio_defaults,
                    "pour",
                    {"identiques": len(equal), "verifies": len(common)},
                )
            )
        unknown = keys - inputs
        if keys and unknown:
            fraction = len(unknown) / len(keys)
            total -= PENALTY_UNKNOWN * fraction
            evidence.append(
                Evidence(
                    "parametres_inconnus_du_robot",
                    -PENALTY_UNKNOWN,
                    fraction,
                    "contre",
                    {"inconnus": len(unknown), "exemples": sorted(unknown)[:8]},
                )
            )
    else:
        evidence.append(
            Evidence(
                "parametres_inaccessibles",
                0.0,
                0.0,
                "incertitude",
                {
                    "motif": "robot sans source lisible (EX4/EX5 opaque) : "
                    "paramètres non vérifiables"
                },
            )
        )
    similarity = name_similarity(robot.name, set_info.name)
    if set_info.named_robot:
        named = name_similarity(robot.name, set_info.named_robot) >= 1.0
        evidence.append(
            Evidence(
                "nom_du_robot_dans_le_set",
                0.0,
                1.0 if named else 0.0,
                "pour" if named else "contre",
                {"ecrit_dans_le_set": set_info.named_robot, "robot": robot.name},
            )
        )
        similarity = 1.0 if named else similarity * 0.5
    total += WEIGHTS["name"] * similarity
    evidence.append(
        Evidence(
            "similarite_noms",
            WEIGHTS["name"],
            similarity,
            "pour" if similarity >= 0.6 else "contre",
            {"robot": robot.name, "set": set_info.name},
        )
    )
    location, label = location_score(robot, set_info)
    if robot.batch is not None and robot.batch == set_info.batch:
        evidence.append(
            Evidence(
                "crees_ensemble",
                0.0,
                1.0,
                "pour",
                {
                    "constat": "même date de modification (à 2 s près) dans un petit lot",
                    "fichiers_du_lot": robot.batch[1],
                },
            )
        )
        if location < 0.7:
            location, label = 0.7, f"{label} ; créés ensemble"
    total += WEIGHTS["location"] * location
    evidence.append(
        Evidence(
            "emplacement",
            WEIGHTS["location"],
            location,
            "pour" if location > 0 else "incertitude",
            {"constat": label},
        )
    )
    if set_info.format == "unknown" or robot.platform == "unknown":
        platform_value, polarity = 0.5, "incertitude"
    elif set_info.format == robot.platform:
        platform_value, polarity = 1.0, "pour"
    else:
        platform_value, polarity = 0.0, "contre"
    total += WEIGHTS["platform"] * platform_value
    evidence.append(
        Evidence(
            "plateforme",
            WEIGHTS["platform"],
            platform_value,
            polarity,
            {"set": set_info.format, "robot": robot.platform},
        )
    )
    score = max(0.0, min(100.0, round(total, 1)))
    return Candidate(robot, score, level_for(score, robot.has_source, coverage), evidence, coverage)


def level_for(score: float, has_source: bool, coverage: float) -> str:
    if score < MIN_SCORE:
        return "none"
    if not has_source:
        return "a_verifier"
    if score >= 75 and coverage >= 0.8:
        return "forte"
    if score >= 50:
        return "moyenne"
    return "faible"


def identity_of(robot: RobotInfo) -> tuple[str, str]:
    """Identité logique (copies et paires source/compilé = même robot)."""
    return logical_key(robot.name), robot.platform


def rank_candidates(set_info: SetInfo, robots: list[RobotInfo], limit: int = 5) -> list[Candidate]:
    scored = [score_pair(r, set_info) for r in robots]
    kept = sorted(
        (c for c in scored if c.level != "none"), key=lambda c: (-c.score, c.robot.file_id)
    )
    if len(kept) >= 2:
        best = kept[0]
        rivals = [
            c
            for c in kept[1:]
            if identity_of(c.robot) != identity_of(best.robot)
            and best.score - c.score <= AMBIGUITY_GAP
            and c.score >= 50
        ]
        if rivals:
            for candidate in [best, *rivals]:
                if candidate.level == "forte":
                    candidate.level = "moyenne"
                candidate.evidence.append(
                    Evidence(
                        "ambiguite",
                        0.0,
                        0.0,
                        "incertitude",
                        {
                            "motif": "plusieurs robots distincts presque aussi plausibles",
                            "ecart_max": AMBIGUITY_GAP,
                        },
                    )
                )
    return kept[:limit]
