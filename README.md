# MT4 MT5 Library Manager PRO

Application macOS de gestion et d'analyse **sécurisée** de bibliothèques MetaTrader 4 et 5 :
inventaire, reconnaissance des robots/indicateurs/scripts, analyse des SET et associations
robot ↔ SET expliquées, familles et versions, doublons exacts et similarités, quarantaine par
copie vérifiée (après simulation et confirmation), bibliothèque organisée, rapports.

**Vos fichiers d'origine ne sont jamais modifiés, déplacés ni supprimés. Aucun fichier
analysé n'est jamais exécuté. Aucune donnée n'est envoyée sur Internet.**

## Obtenir l'application
Onglet **Releases** du dépôt → DMG « Apple-Silicon » ou « Intel » →
[guide d'installation](docs/utilisateur/installation.md).

Aperçu de l'application réelle (données fictives) : [docs/captures/](docs/captures/).

## État : version 1.0.0 — phases 0 à 12 livrées

| Phase | Rapport |
|---|---|
| 0 Audit, architecture | [ARCHITECTURE](ARCHITECTURE.md), [DECISIONS](DECISIONS.md), [RISQUES](RISQUES.md), [PLAN DE TESTS](PLAN_DE_TESTS.md) |
| 1 Socle | [phase-01](docs/rapports/phase-01.md) |
| 2 Scanner lecture seule | [phase-02](docs/rapports/phase-02.md) |
| 3 Empreintes SHA-256 | [phase-03](docs/rapports/phase-03.md) |
| 4 Formats et archives | [phase-04](docs/rapports/phase-04.md) |
| 5 Reconnaissance MetaTrader | [phase-05](docs/rapports/phase-05.md) |
| 6 SET et associations | [phase-06](docs/rapports/phase-06.md) |
| 7 Familles et versions | [phase-07](docs/rapports/phase-07.md) |
| 8-9 Doublons, quarantaine, organisation | [phase-08-09](docs/rapports/phase-08-09.md) |
| 10 Interface | [phase-10](docs/rapports/phase-10.md) |
| 11 Performance | [phase-11](docs/rapports/phase-11.md) |
| 12 Livraison macOS | [phase-12](docs/rapports/phase-12.md), [compatibilité](docs/COMPATIBILITE.md) |

Autres documents : [traçabilité exigences → tests](docs/TRACABILITE.md) ·
[validations du propriétaire](docs/VALIDATIONS.md) · [quarantaine et restauration](docs/utilisateur/quarantaine-et-restauration.md) ·
[spécification](docs/specification/) · [historique](CHANGELOG.md).

## Pour les développeurs

Prérequis : Python 3.12+, [uv](https://docs.astral.sh/uv/).

```bash
uv sync --frozen                    # installation reproductible
bash tools/verifier.sh              # lint, format, types, tests, paquet (comme la CI)
uv run pytest -m slow -s            # charge 50 000 / 100 000 fichiers fictifs
uv run mtlm-gui                     # interface graphique
uv run mtlm --help                  # ligne de commande (mêmes fonctions)
uv run --group build pyinstaller --noconfirm packaging/macos/mtlm.spec   # .app (sur macOS)
```

Ligne de commande, parcours type :
```bash
mtlm source ajouter ~/MetaTrader      # lecture seule
mtlm analyser                         # tout le pipeline
mtlm associations --niveau forte ; mtlm valider ID --accepter
mtlm doublons ; mtlm quarantaine simuler /Volumes/Sauvegarde/Quarantaine
mtlm organiser previsualiser /Volumes/Sauvegarde/Rangement
mtlm exporter inventaire inventaire.csv
```

## Règles permanentes
- Aucune donnée réelle (robots, SET, DLL, données de trading) dans ce dépôt : uniquement des
  corpus **fictifs** générés (`tests/synthetic/generate.py`).
- EX4/EX5 restent des binaires opaques : ni décompilation, ni extraction de paramètres.
- Doublons exacts, similaires et versions différentes ne sont jamais confondus.
