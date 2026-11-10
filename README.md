# MT4 MT5 Library Manager PRO

Application macOS de gestion et d'analyse **sécurisée** de bibliothèques MetaTrader 4 et 5 :
inventaire, reconnaissance, analyse des SET, familles et versions, doublons, quarantaine
restaurable (par copie, après confirmation) et bibliothèque organisée — sans jamais modifier
les fichiers originaux.

> **État : Phase 1 (socle) terminée, en attente de validation.** Aucun écran ni moteur
> d'analyse n'existe encore : seuls le socle technique (base, migrations, sauvegardes,
> journal d'audit, journaux, ligne de commande) et les outils de test sont livrés.
> Voir [docs/rapports/phase-01.md](docs/rapports/phase-01.md).

## Documents

| Document | Contenu |
|---|---|
| [docs/specification/](docs/specification/) | Spécification contractuelle (PDF V3.0) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Architecture, modules, modèle de données, phases |
| [DECISIONS.md](DECISIONS.md) | Décisions (technologie Python/PySide6, quarantaine par copie…) |
| [RISQUES.md](RISQUES.md) | Risques, hypothèses, limites, questions ouvertes |
| [PLAN_DE_TESTS.md](PLAN_DE_TESTS.md) | Stratégie et cas de tests |
| [docs/VALIDATIONS.md](docs/VALIDATIONS.md) | Validations du propriétaire, phase par phase |
| [docs/TRACABILITE.md](docs/TRACABILITE.md) | Exigence → code → tests → preuve |
| [docs/rapports/](docs/rapports/) | Rapports de phase (résultats réels des tests) |
| [CHANGELOG.md](CHANGELOG.md) | Historique des versions |

## Pour les développeurs

Prérequis : Python 3.12 ou plus récent, [uv](https://docs.astral.sh/uv/).

```bash
uv sync --frozen                 # installation reproductible (verrou uv.lock)
uv run pytest                    # tests (hors charge)
uv run pytest -m slow -s         # charge : corpus synthétiques de 50 000 et 100 000 fichiers
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Ligne de commande (socle) — elle n'utilise que les dossiers propres à l'application
(`MTLM_HOME` permet d'en choisir un autre pour les essais) :

```bash
uv run mtlm version
uv run mtlm init                 # crée ou met à jour la base locale
uv run mtlm etat                 # base, journal d'audit, sauvegardes
uv run mtlm sauvegarder          # sauvegarde vérifiée de la base
uv run mtlm restaurer FICHIER --confirmer
uv run mtlm audit verifier
uv run mtlm audit exporter FICHIER.jsonl
```

Corpus de test **fictif** reproductible :

```bash
uv run python -m tests.synthetic.generate --seed 42 --files 50000 --out /tmp/corpus --manifest /tmp/m.json
```

## Règles permanentes

- Aucune donnée réelle (robots, SET, DLL, données de trading) dans ce dépôt.
- Aucun fichier analysé n'est jamais exécuté ; EX4/EX5 restent des binaires opaques.
- Les sources ne sont jamais modifiées ; la quarantaine est une copie vérifiée, après confirmation.
