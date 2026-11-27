"""Outil de développement (1.9.0) : entoure les textes affichés de ``tr(...)``.

Utilisation : python tools/i18n_codemod.py FICHIER... (réécrit les fichiers sur place).

* Seuls les textes **dans des fonctions** sont traités (ceux des modules et des classes sont
  traduits là où ils sont affichés) ; les docstrings, clés, comparaisons, requêtes SQL,
  identifiants et messages de journal ne sont jamais touchés.
* Une f-chaîne devient ``tr("modèle {valeur}", valeur=expression)``.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

WORD = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
SQL = re.compile(
    r"^\s*\(?\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|FROM|WHERE|AND|OR|JOIN|LEFT|"
    r"ORDER|GROUP|VALUES|ON|SET|WITH|PRAGMA|UNION|HAVING|LIMIT|NOT|EXISTS|CASE|WHEN|THEN|"
    r"ELSE|END|IN|AS|SUM|COUNT|count|sum|coalesce|lower|substr|min|max)\b"
)
SKIP_CALLS = {
    "setObjectName",
    "findChild",
    "findChildren",
    "setProperty",
    "property",
    "getattr",
    "setattr",
    "hasattr",
    "startswith",
    "endswith",
    "split",
    "rsplit",
    "partition",
    "rpartition",
    "replace",
    "join",
    "strip",
    "lstrip",
    "rstrip",
    "encode",
    "decode",
    "execute",
    "executemany",
    "executescript",
    "strftime",
    "strptime",
    "fromisoformat",
    "getLogger",
    "debug",
    "info_log",
    "warning",
    "exception",
    "critical",
    "append_audit",
    "compile",
    "match",
    "fullmatch",
    "search",
    "sub",
    "findall",
    "finditer",
    "re",
    "fsencode",
    "fsdecode",
    "Path",
    "open",
    "with_suffix",
    "with_name",
    "glob",
    "rglob",
    "casefold",
    "lower",
    "upper",
    "count",
    "index",
    "find",
    "setStyleSheet",
    "registry_button",
    "select_buttons",
    "isinstance",
    "dumps",
    "loads",
    "TaskSpec",
    "Evidence",
    "Finding",
    "QColor",
    "QFont",
    "addAction_id",
}
SKIP_KWARGS = {
    "role",
    "objectName",
    "tone",
    "kind",
    "key",
    "origin",
    "encoding",
    "errors",
    "prefix",
    "suffix",
    "sep",
    "end",
    "mode",
    "result",
    "actor",
    "level",
    "format",
}
LOGGER_NAMES = {"log", "logger", "logging", "_journal", "journal"}


def translatable(text: str) -> bool:
    if not WORD.search(text) or SQL.match(text):
        return False
    stripped = text.strip()
    if re.fullmatch(r"[a-z0-9_.\-/:*%]+", stripped):  # identifiants, clés, motifs
        return False
    if re.fullmatch(r"[A-Z0-9_.\-/ ]+", stripped):  # sigles : MQ4, SHA-256, CSV
        return False
    if stripped.startswith(("Q", "#", "{", "*.", "%", "\\")) and " " not in stripped:
        return False
    return (
        " " in stripped
        or bool(re.search(r"[À-ÿ]", stripped))
        or bool(re.fullmatch(r"[A-ZÀ-Ý][a-zà-ÿ'’]+.*", stripped))
    )


def call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def call_owner(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute):
        return func.value.attr
    return ""


class Collector(ast.NodeVisitor):
    def __init__(self, source: str) -> None:
        self.source = source
        self.edits: list[tuple[int, int, str]] = []
        self.depth = 0  # profondeur de fonctions
        self.parents: list[ast.AST] = []

    def generic_visit(self, node: ast.AST) -> None:
        self.parents.append(node)
        super().generic_visit(node)
        self.parents.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            node = ast.FunctionDef(**{**node.__dict__, "body": body[1:]})  # sans la docstring
        self.depth += 1
        self.parents.append(node)
        for child in node.body + node.decorator_list:
            self.visit(child)
        self.parents.pop()
        self.depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]  # noqa: N815

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.generic_visit(node)

    def skipped(self, node: ast.AST) -> bool:
        parent = self.parents[-1] if self.parents else None
        if self.depth == 0:
            return True
        for ancestor in self.parents:
            if isinstance(ancestor, ast.Call) and call_name(ancestor) == "tr":
                return True
            if isinstance(ancestor, ast.Call) and (
                call_owner(ancestor) in LOGGER_NAMES or call_name(ancestor) in SKIP_CALLS
            ):
                return True
            if (
                isinstance(ancestor, (ast.Compare, ast.Subscript, ast.JoinedStr))
                and ancestor is not node
            ):
                if isinstance(ancestor, ast.JoinedStr):
                    return True
                return True
        if isinstance(parent, ast.Dict) and any(k is node for k in parent.keys):
            return True
        if isinstance(parent, ast.keyword) and parent.arg in SKIP_KWARGS:
            return True
        if isinstance(parent, ast.Call):
            name = call_name(parent)
            if name == "btn" and parent.args and parent.args[0] is node:
                return True
            if name == "trash_selected" and len(parent.args) > 1 and parent.args[1] is node:
                return True
            if (
                name == "trash_with_confirmation"
                and len(parent.args) > 1
                and parent.args[1] is node
            ):
                return True
            if name in ("get", "pop", "setdefault") and parent.args and parent.args[0] is node:
                return True
        return False

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and translatable(node.value) and not self.skipped(node):
            segment = ast.get_source_segment(self.source, node)
            if segment is not None:
                self.edits.append(self._edit(node, f"tr({segment})"))

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        if self.skipped(node):
            return
        template, ok = "", True
        values: dict[str, str] = {}
        for part in node.values:
            if isinstance(part, ast.Constant):
                template += str(part.value).replace("{", "{{").replace("}", "}}")
                continue
            if not isinstance(part, ast.FormattedValue):
                ok = False
                break
            expr = ast.get_source_segment(self.source, part.value)
            if expr is None:
                ok = False
                break
            if isinstance(part.value, ast.Name):
                name = part.value.id
            elif isinstance(part.value, ast.Attribute):
                name = part.value.attr
            else:
                name = "v"
            name = re.sub(r"\W", "_", name).strip("_") or "v"
            base, n = name, 2
            while name in values and values[name] != expr:
                name, n = f"{base}{n}", n + 1
            if part.conversion == ord("r"):
                expr = f"repr({expr})"
            elif part.conversion == ord("s"):
                expr = f"str({expr})"
            values[name] = expr
            spec = ""
            fmt = part.format_spec
            if fmt is not None:
                pieces = fmt.values if isinstance(fmt, ast.JoinedStr) else []
                if not all(isinstance(v, ast.Constant) for v in pieces):
                    ok = False
                    break
                spec = ":" + "".join(str(v.value) for v in pieces if isinstance(v, ast.Constant))
            template += "{" + name + spec + "}"
        if not ok or not translatable(re.sub(r"\{[^}]*\}", "", template)):
            return
        args = ", ".join(f"{k}={v}" for k, v in values.items())
        literal = repr(template)
        if '"' not in template:
            literal = '"' + template.replace("\\", "\\\\").replace("\n", "\\n") + '"'
        self.edits.append(self._edit(node, f"tr({literal}{', ' + args if args else ''})"))

    def _edit(self, node: ast.AST, text: str) -> tuple[int, int, str]:
        lines = self.source.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line.encode("utf-8")))
        raw = self.source.encode("utf-8")
        start = offsets[node.lineno - 1] + node.col_offset  # type: ignore[attr-defined]
        end = offsets[node.end_lineno - 1] + node.end_col_offset  # type: ignore[attr-defined]
        _ = raw
        return start, end, text


def rewrite(path: Path) -> int:
    source = path.read_text(encoding="utf-8")
    collector = Collector(source)
    collector.visit(ast.parse(source))
    raw = source.encode("utf-8")
    for start, end, text in sorted(collector.edits, reverse=True):
        raw = raw[:start] + text.encode("utf-8") + raw[end:]
    result = raw.decode("utf-8")
    if collector.edits and "from mtlm.core.i18n import tr" not in result:
        result = re.sub(
            r"^(from __future__ import annotations\n)",
            r"\1\nfrom mtlm.core.i18n import tr\n",
            result,
            count=1,
            flags=re.M,
        )
    path.write_text(result, encoding="utf-8")
    return len(collector.edits)


if __name__ == "__main__":
    for name in sys.argv[1:]:
        print(name, rewrite(Path(name)))
