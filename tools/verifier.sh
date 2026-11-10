#!/usr/bin/env bash
# Vérification complète avant chaque envoi (mêmes contrôles que la CI Linux).
# Utilisation : bash tools/verifier.sh
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== Lint";    uv run ruff check .
echo "== Format";  uv run ruff format --check .
echo "== Types";   uv run mypy
echo "== Tests";   uv run pytest -q -W error::ResourceWarning --cov --cov-fail-under=85
echo "== Paquet";  rm -rf dist && uv build --wheel -q && uv run python tools/check_wheel.py dist/*.whl && rm -rf dist
echo "OK : toutes les vérifications sont passées."
