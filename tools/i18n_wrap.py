"""Outil de développement : découpe les longs textes de ``tr("…")`` en morceaux de moins de
80 caractères (concaténation implicite), pour respecter la longueur de ligne."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def chunks(text: str, width: int = 72) -> list[str]:
    words, parts, current = text.split(" "), [], ""
    for i, word in enumerate(words):
        piece = word + (" " if i < len(words) - 1 else "")
        if current and len(current) + len(piece) > width:
            parts.append(current)
            current = ""
        current += piece
    if current:
        parts.append(current)
    return parts


def literal(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def rewrite(path: Path) -> int:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line.encode("utf-8")))
    raw = source.encode("utf-8")
    edits = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "tr"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and len(node.args[0].value) > 70
        ):
            arg = node.args[0]
            start = starts[arg.lineno - 1] + arg.col_offset
            end = starts[arg.end_lineno - 1] + arg.end_col_offset  # type: ignore[operator]
            pieces = "\n".join(literal(p) for p in chunks(str(arg.value)))
            edits.append((start, end, pieces if "\n" in pieces else literal(str(arg.value))))
    for start, end, text in sorted(edits, reverse=True):
        raw = raw[:start] + text.encode("utf-8") + raw[end:]
    path.write_text(raw.decode("utf-8"), encoding="utf-8")
    return len(edits)


if __name__ == "__main__":
    for name in sys.argv[1:]:
        print(name, rewrite(Path(name)))
