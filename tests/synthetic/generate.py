"""Générateur de corpus synthétique reproductible (livrable § 11 de la spécification).

Produit une arborescence de type bibliothèque MetaTrader avec des fichiers
**entièrement fictifs** et un manifeste de vérité terrain (JSON).

Garanties :

* reproductible : même graine + mêmes paramètres ⇒ mêmes chemins et mêmes octets ;
* aucun vrai robot, SET ou binaire : les sources sont générées, les ``.ex4/.ex5/.dll``
  sont des octets aléatoires (non exécutables) ;
* sécurité : refuse d'écrire dans un dossier non vide (évite toute écriture
  accidentelle dans une vraie bibliothèque) ;
* ce module vit dans ``tests/`` et n'est jamais empaqueté dans l'application.

Utilisation :
    python -m tests.synthetic.generate --seed 42 --files 50000 --out DOSSIER --manifest m.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

GENERATOR_VERSION = "1"

# Répartition des types de fichiers (le reste : doublons exacts injectés).
KIND_WEIGHTS: list[tuple[str, float]] = [
    ("mq4", 0.12),
    ("mq5", 0.12),
    ("mqh", 0.08),
    ("ex4", 0.12),
    ("ex5", 0.12),
    ("set", 0.18),
    ("dll", 0.03),
    ("tpl", 0.04),
    ("csv", 0.03),
    ("ini", 0.02),
    ("unknown", 0.04),
    ("empty", 0.01),
]
DUPLICATE_RATE = 0.05
UNKNOWN_EXTENSIONS = ["dat", "bak", "xyz", "log", "", "md", "json", "txt"]

SIZE_PROFILES: dict[str, tuple[int, int]] = {
    # (taille min, taille max) en octets pour les fichiers binaires aléatoires
    "tiny": (16, 512),
    "normal": (256, 16384),
}

PLATFORM_ROOTS = {"mt4": "MQL4", "mt5": "MQL5"}
CATEGORIES = ["Experts", "Indicators", "Scripts"]
SYLLABLES = [
    "al",
    "be",
    "co",
    "da",
    "el",
    "fo",
    "ga",
    "hi",
    "io",
    "ka",
    "lu",
    "mo",
    "na",
    "or",
    "pi",
    "qu",
    "ra",
    "so",
    "ti",
    "ul",
    "ve",
    "xo",
    "yu",
    "ze",
]
ACCENTED_WORDS = ["Été", "Élan", "Forêt", "Garçon", "Noël", "Crème", "Öl", "Ñandú", "Señal"]
EMOJI = ["📈", "🚀", "💹"]

INPUT_TYPES = ["int", "double", "bool", "string", "color"]


def _path_key(rel_path: str) -> str:
    return unicodedata.normalize("NFC", rel_path).casefold()


@dataclass
class Entry:
    rel_path: str
    kind: str
    platform: str
    size: int
    sha256: str
    encoding: str | None = None
    duplicate_of: str | None = None
    robot_name: str | None = None
    set_for: str | None = None
    inputs: list[str] = field(default_factory=list)


@dataclass
class Manifest:
    generator_version: str
    seed: int
    requested_files: int
    size_profile: str
    entries: list[Entry]

    def counts(self) -> dict[str, int]:
        return dict(sorted(Counter(e.kind for e in self.entries).items()))

    def to_json(self) -> str:
        data = asdict(self)
        data["counts"] = self.counts()
        data["total_files"] = len(self.entries)
        data["total_bytes"] = sum(e.size for e in self.entries)
        return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)


@dataclass
class _Robot:
    name: str
    platform: str
    rel_path: str
    inputs: list[tuple[str, str, str]]  # (type, nom, valeur par défaut)


class _Generator:
    def __init__(self, root: Path, seed: int, size_profile: str) -> None:
        self.root = root
        self.rng = random.Random(seed)
        self.min_size, self.max_size = SIZE_PROFILES[size_profile]
        self.entries: list[Entry] = []
        self.robots: list[_Robot] = []
        self.robots_by_platform: dict[str, list[_Robot]] = {"mt4": [], "mt5": []}
        self.originals: list[Entry] = []  # fichiers qui ne sont pas des doublons
        self.used_paths: set[str] = set()
        self.dir_counter = 0

    # --- noms -------------------------------------------------------------------------
    def word(self, parts: int = 3) -> str:
        return "".join(self.rng.choice(SYLLABLES) for _ in range(parts)).capitalize()

    def robot_name(self) -> str:
        roll = self.rng.random()
        name = f"{self.word()}{self.word(2)}"
        if roll < 0.05:
            name = f"{self.rng.choice(ACCENTED_WORDS)} {name}"
        elif roll < 0.07:
            name = f"{name} {self.rng.choice(EMOJI)}"
        if self.rng.random() < 0.15:
            name = f"{name}_v{self.rng.randint(1, 4)}.{self.rng.randint(0, 9)}"
        return name

    def folder(self, platform: str, category: str) -> str:
        base = f"{PLATFORM_ROOTS[platform]}/{category}"
        depth = self.rng.choices([0, 1, 2, 3], weights=[4, 3, 2, 1])[0]
        parts = [base] + [f"Groupe{self.rng.randint(1, 40)}" for _ in range(depth)]
        return "/".join(parts)

    def unique(self, rel_path: str) -> str:
        candidate = rel_path
        n = 1
        # Clé insensible à la casse et à la forme Unicode : sur macOS (APFS), « Été » NFC/NFD
        # et « été » peuvent désigner le même fichier.
        while _path_key(candidate) in self.used_paths:
            n += 1
            stem, dot, ext = rel_path.rpartition(".")
            candidate = f"{stem} ({n}).{ext}" if dot and stem else f"{rel_path} ({n})"
        self.used_paths.add(_path_key(candidate))
        return candidate

    def maybe_nfd(self, rel_path: str) -> str:
        # Une partie des noms accentués est écrite en forme décomposée (NFD), comme sur macOS.
        if any(ord(ch) > 127 for ch in rel_path) and self.rng.random() < 0.5:
            return unicodedata.normalize("NFD", rel_path)
        return unicodedata.normalize("NFC", rel_path)

    # --- écriture ---------------------------------------------------------------------
    def write(self, rel_path: str, data: bytes, entry: Entry) -> Entry:
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:  # ne jamais écraser
            handle.write(data)
        entry.rel_path = rel_path
        entry.size = len(data)
        entry.sha256 = hashlib.sha256(data).hexdigest()
        self.entries.append(entry)
        if entry.duplicate_of is None:
            self.originals.append(entry)
        return entry

    def random_bytes(self) -> bytes:
        return self.rng.randbytes(self.rng.randint(self.min_size, self.max_size))

    # --- sources MQL fictives ---------------------------------------------------------
    def make_inputs(self) -> list[tuple[str, str, str]]:
        inputs: list[tuple[str, str, str]] = []
        names: set[str] = set()
        for _ in range(self.rng.randint(2, 12)):
            mql_type = self.rng.choice(INPUT_TYPES)
            name = f"{self.rng.choice(['Inp', 'Ext', ''])}{self.word(2)}{self.word(1)}"
            if name in names:
                continue
            names.add(name)
            default = {
                "int": str(self.rng.randint(0, 500)),
                "double": f"{self.rng.uniform(0, 100):.2f}",
                "bool": self.rng.choice(["true", "false"]),
                "string": f'"{self.word(2)}"',
                "color": self.rng.choice(["clrRed", "clrBlue", "clrGreen"]),
            }[mql_type]
            inputs.append((mql_type, name, default))
        return inputs

    def source_text(self, robot: _Robot, category: str) -> str:
        keyword = "extern" if robot.platform == "mt4" and self.rng.random() < 0.5 else "input"
        lines = [
            f"//| {robot.name} — robot FICTIF généré pour les tests",
            '#property copyright "Exemple fictif — données de test"',
            f'#property version   "1.{self.rng.randint(0, 20):02d}"',
            f'#property description "Fictif {robot.name}"',
        ]
        if robot.platform == "mt4":
            lines.append("#property strict")
        if category == "Indicators":
            lines.append("#property indicator_chart_window")
        lines.append("")
        for mql_type, name, default in robot.inputs:
            lines.append(f"{keyword} {mql_type} {name} = {default};")
        lines.append("")
        entry_fn = {"Experts": "OnTick", "Indicators": "OnCalculate", "Scripts": "OnStart"}[
            category
        ]
        if entry_fn == "OnCalculate":
            lines.append("int OnCalculate(const int rates_total, const int prev_calculated,")
            lines.append("                const int begin, const double &price[])")
            lines.append("  {\n   return(rates_total);\n  }")
        else:
            ret = "void"
            lines.append(f"{ret} {entry_fn}()\n  {{\n   // aucune logique : fichier fictif\n  }}")
        return "\n".join(lines) + "\n"

    def encode_source(self, text: str, platform: str) -> tuple[bytes, str]:
        if platform == "mt5":
            return b"\xff\xfe" + text.encode("utf-16-le"), "utf-16-le-bom"
        choice = self.rng.random()
        if choice < 0.5:
            return text.encode("cp1252", errors="replace"), "cp1252"
        if choice < 0.8:
            return text.encode("utf-8"), "utf-8"
        return b"\xef\xbb\xbf" + text.encode("utf-8"), "utf-8-bom"

    # --- générateurs par type ---------------------------------------------------------
    def gen_source(self, ext: str) -> None:
        platform = "mt4" if ext == "mq4" else "mt5"
        category = self.rng.choice(CATEGORIES)
        name = self.robot_name()
        rel = self.unique(self.maybe_nfd(f"{self.folder(platform, category)}/{name}.{ext}"))
        robot = _Robot(name, platform, rel, self.make_inputs())
        data, encoding = self.encode_source(self.source_text(robot, category), platform)
        self.write(
            rel,
            data,
            Entry(
                rel,
                ext,
                platform,
                0,
                "",
                encoding=encoding,
                robot_name=name,
                inputs=[n for _, n, _ in robot.inputs],
            ),
        )
        self.robots.append(robot)
        self.robots_by_platform[platform].append(robot)

    def gen_include(self) -> None:
        platform = self.rng.choice(["mt4", "mt5"])
        rel = self.unique(f"{PLATFORM_ROOTS[platform]}/Include/{self.word()}.mqh")
        text = (
            f"// Include fictif\n#define FICTIF_{self.word().upper()} {self.rng.randint(1, 99)}\n"
        )
        data, encoding = self.encode_source(text, platform)
        self.write(rel, data, Entry(rel, "mqh", platform, 0, "", encoding=encoding))

    def gen_compiled(self, ext: str) -> None:
        platform = "mt4" if ext == "ex4" else "mt5"
        same_as_source = self.robots_by_platform[platform]
        if same_as_source and self.rng.random() < 0.6:
            robot = self.rng.choice(same_as_source)
            stem = robot.rel_path.rsplit(".", 1)[0]
            rel = self.unique(f"{stem}.{ext}")
            name = robot.name
        else:
            name = self.robot_name()
            category = self.rng.choice(CATEGORIES)
            rel = self.unique(self.maybe_nfd(f"{self.folder(platform, category)}/{name}.{ext}"))
        self.write(rel, self.random_bytes(), Entry(rel, ext, platform, 0, "", robot_name=name))

    def gen_set(self) -> None:
        if not self.robots:
            self.gen_source(self.rng.choice(["mq4", "mq5"]))
            return
        robot = self.rng.choice(self.robots)
        lines: list[str] = []
        if robot.platform == "mt5":
            lines.append("; saved automatically — fichier SET FICTIF")
        for mql_type, name, default in robot.inputs:
            value = default.strip('"')
            if mql_type == "bool":
                value = "true" if value == "true" else "false"
            if robot.platform == "mt4":
                lines.append(f"{name}={value}")
                if mql_type in ("int", "double"):
                    lines += [
                        f"{name},F=0",
                        f"{name},1={value}",
                        f"{name},2=1",
                        f"{name},3={value}",
                    ]
            else:
                lines.append(f"{name}={value}||{value}||1||{value}||N")
        text = "\n".join(lines) + "\n"
        if robot.platform == "mt5":
            data, encoding = b"\xff\xfe" + text.encode("utf-16-le"), "utf-16-le-bom"
        else:
            data, encoding = text.encode("utf-8"), "utf-8"
        suffix = self.rng.choice(["", "_EURUSD", "_M15", " agressif", "_test"])
        rel = self.unique(f"{PLATFORM_ROOTS[robot.platform]}/Presets/{robot.name}{suffix}.set")
        self.write(
            rel,
            data,
            Entry(
                rel,
                "set",
                robot.platform,
                0,
                "",
                encoding=encoding,
                robot_name=robot.name,
                set_for=robot.rel_path,
                inputs=[n for _, n, _ in robot.inputs],
            ),
        )

    def gen_misc(self, kind: str) -> None:
        platform = self.rng.choice(["mt4", "mt5", "unknown"])
        top = PLATFORM_ROOTS.get(platform, "Divers")
        if kind == "dll":
            rel = self.unique(f"{top}/Libraries/{self.word()}.dll")
            self.write(rel, self.random_bytes(), Entry(rel, "dll", platform, 0, ""))
        elif kind == "tpl":
            rel = self.unique(f"Templates/{self.word()}.tpl")
            data = f"<chart>\nsymbol=EURUSD\nperiod={self.rng.choice([1, 15, 60])}\n</chart>\n"
            self.write(rel, data.encode(), Entry(rel, "tpl", "unknown", 0, ""))
        elif kind == "csv":
            rel = self.unique(f"{top}/Files/{self.word()}.csv")
            rows = "\n".join(f"{i};{self.rng.random():.5f}" for i in range(self.rng.randint(1, 30)))
            self.write(rel, rows.encode(), Entry(rel, "csv", platform, 0, ""))
        elif kind == "ini":
            rel = self.unique(f"Config/{self.word()}.ini")
            self.write(rel, b"[Common]\nLogin=0\n", Entry(rel, "ini", "unknown", 0, ""))
        elif kind == "unknown":
            ext = self.rng.choice(UNKNOWN_EXTENSIONS)
            name = self.word() + (f".{ext}" if ext else "")
            rel = self.unique(self.maybe_nfd(f"Vrac/{self.rng.choice(ACCENTED_WORDS)}/{name}"))
            self.write(rel, self.random_bytes(), Entry(rel, "unknown", "unknown", 0, ""))
        elif kind == "empty":
            rel = self.unique(f"Vrac/vide_{self.word()}.txt")
            self.write(rel, b"", Entry(rel, "empty", "unknown", 0, ""))

    def gen_duplicate(self) -> None:
        if not self.originals:
            self.gen_misc("unknown")
            return
        original = self.rng.choice(self.originals)
        data = (self.root / original.rel_path).read_bytes()
        directory, _, filename = original.rel_path.rpartition("/")
        if self.rng.random() < 0.5:
            rel = self.unique(f"Copies/{directory}/{filename}")  # même nom, autre dossier
        else:
            stem, dot, ext = filename.rpartition(".")
            renamed = f"{stem} - Copie.{ext}" if dot and stem else f"{filename} - Copie"
            rel = self.unique(f"{directory}/{renamed}")  # copie renommée
        entry = Entry(
            rel,
            original.kind,
            original.platform,
            0,
            "",
            encoding=original.encoding,
            duplicate_of=original.rel_path,
            robot_name=original.robot_name,
            set_for=original.set_for,
            inputs=list(original.inputs),
        )
        self.write(rel, data, entry)

    def run(self, n_files: int) -> None:
        kinds = [k for k, _ in KIND_WEIGHTS]
        weights = [w for _, w in KIND_WEIGHTS]
        while len(self.entries) < n_files:
            if self.entries and self.rng.random() < DUPLICATE_RATE:
                self.gen_duplicate()
                continue
            kind = self.rng.choices(kinds, weights=weights)[0]
            if kind in ("mq4", "mq5"):
                self.gen_source(kind)
            elif kind == "mqh":
                self.gen_include()
            elif kind in ("ex4", "ex5"):
                self.gen_compiled(kind)
            elif kind == "set":
                self.gen_set()
            else:
                self.gen_misc(kind)
        # gen_set peut créer une source supplémentaire : on tronque proprement si besoin.
        while len(self.entries) > n_files:
            extra = self.entries.pop()
            if self.originals and self.originals[-1] is extra:
                self.originals.pop()
            (self.root / extra.rel_path).unlink()


def generate_corpus(
    root: Path, *, seed: int, n_files: int, size_profile: str = "normal"
) -> Manifest:
    """Génère ``n_files`` fichiers fictifs dans ``root`` (qui doit être vide ou absent)."""
    if n_files < 1:
        raise ValueError("n_files doit être >= 1")
    if size_profile not in SIZE_PROFILES:
        raise ValueError(f"profil de taille inconnu : {size_profile}")
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(
            f"Refus : le dossier {root} n'est pas vide (protection contre l'écriture "
            "dans une vraie bibliothèque)."
        )
    root.mkdir(parents=True, exist_ok=True)
    generator = _Generator(root, seed, size_profile)
    generator.run(n_files)
    return Manifest(GENERATOR_VERSION, seed, n_files, size_profile, generator.entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Génère un corpus synthétique fictif.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--files", type=int, default=1000)
    parser.add_argument("--profile", choices=sorted(SIZE_PROFILES), default="normal")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = generate_corpus(
        args.out, seed=args.seed, n_files=args.files, size_profile=args.profile
    )
    with args.manifest.open("x", encoding="utf-8") as handle:
        handle.write(manifest.to_json())
    print(f"{len(manifest.entries)} fichiers générés dans {args.out} ; manifeste : {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
