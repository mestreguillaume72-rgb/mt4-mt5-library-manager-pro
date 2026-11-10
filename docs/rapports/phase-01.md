# Rapport de phase 1 — Socle

> Statut : **terminée côté développement, en attente de validation du propriétaire.**
> Date : 2026-11-10 · Version : 0.1.0 · Branche : `claude/mt4-mt5-library-architecture-d90d89`

## 1. Ce qui a été livré (spécification § 8, phase 1 : « dépôt, configuration, logs, base et migrations »)

| Élément | Comportement | Fichiers |
|---|---|---|
| Structure et configuration | Paquet `mtlm` (Python 3.12+), dépendances verrouillées, lint, types, tests | `pyproject.toml`, `uv.lock` |
| Emplacements | Base, sauvegardes et journaux uniquement dans les dossiers de l'application (macOS : `~/Library/Application Support/…` et `~/Library/Logs/…`) ; jamais dans une source | `src/mtlm/core/paths.py` |
| Base locale | SQLite, WAL, `synchronous=FULL`, clés étrangères, tables STRICT, transactions explicites ; schéma complet du modèle de données (29 tables dont FTS5) | `src/mtlm/store/database.py`, `src/mtlm/store/migrations/0001_initial.sql` |
| Migrations | Une transaction par migration (tout ou rien), empreinte SHA-256 des scripts appliqués, refus d'une base plus récente, sauvegarde automatique avant migration d'une base existante | `src/mtlm/store/migrations_engine.py` |
| Sauvegarde / restauration | Sauvegarde en ligne vérifiée (`integrity_check`), jamais d'écrasement ; restauration avec sauvegarde de sécurité préalable et confirmation obligatoire | `src/mtlm/store/backup.py` |
| Journal d'audit | Append-only, chaîné par SHA-256, triggers SQL interdisant modification/suppression, vérification, export JSONL sans écrasement | `src/mtlm/audit/journal.py` |
| Journaux techniques | Fichier rotatif (10 × 5 Mo), horodatage UTC | `src/mtlm/audit/logs.py` |
| Ligne de commande | `mtlm version / init / etat / sauvegarder / restaurer --confirmer / audit verifier / audit exporter` | `src/mtlm/cli/main.py`, `src/mtlm/app/context.py` |
| Corpus synthétique | Générateur fictif reproductible (graine), manifeste de vérité terrain, refus d'écrire dans un dossier non vide ; non livré dans l'application | `tests/synthetic/generate.py` |
| Invariant « sources inchangées » | Instantané (contenu, tailles, dates, droits, attributs étendus) avant/après | `tests/support/fs_snapshot.py`, `tests/integration/test_invariant_sources.py` |
| Garde-fous de sécurité | Règles statiques : pas d'exécution, pas de réseau, aucune écriture dans les modules d'analyse, couches respectées ; chaque règle a des auto-tests | `tests/security/` |
| CI | Linux (3.12, 3.13) à chaque push ; macOS Apple Silicon + Intel sur pull request ou à la demande ; charge 50k/100k à la demande | `.github/workflows/` |

**Entrées / sorties / erreurs** : les commandes ne prennent que des chemins de sauvegarde/export
choisis par l'utilisateur ; sorties en français ; codes de sortie 0 (succès), 1 (erreur), 2 (usage ou
confirmation manquante). Erreurs typées (`MigrationError`, `DatabaseTooNewError`,
`MigrationIntegrityError`, `BackupError`, `ExportError`, `AuditError`) avec message compréhensible ;
dans chaque cas, la base reste dans son état précédent.

## 2. Tests réellement exécutés

Environnement : conteneur Linux x86_64 (noyau 6.18), Python **3.13.18** et **3.12.13**,
SQLite 3.53.1, uv 0.11.32, 4 processeurs, 16 Go de RAM.

| Commande | Résultat |
|---|---|
| `uv run ruff check .` | All checks passed! |
| `uv run ruff format --check .` | 45 files already formatted |
| `uv run mypy` (mode strict) | Success: no issues found in 37 source files |
| `uv run pytest -W error::ResourceWarning --cov --cov-fail-under=85` (Python 3.13) | **117 passed**, 2 deselected (charge) — couverture **97,54 %** |
| `uv run --python 3.12 pytest -W error::ResourceWarning` | **117 passed**, 2 deselected |
| `uv run pytest -m slow -s` | **2 passed** (voir § 3) |
| `uv build --wheel` puis `python tools/check_wheel.py dist/*.whl` | Contenu du paquet conforme (migrations incluses, aucun test ni générateur) |
| Installation du wheel dans un environnement vierge puis `mtlm version`, `mtlm init`, `mtlm audit verifier` | OK : migration 1 appliquée, journal intact |

Répartition des 117 tests : migrations et schéma 20 · sauvegarde/restauration 16 · audit 10 ·
journaux 3 · noyau 9 · ligne de commande 12 · invariant 2 (+2 de charge) · générateur 9 ·
sécurité statique 33 · hygiène du dépôt 3.

Couverture par module : `app/context` 100 %, `audit/journal` 98 %, `audit/logs` 95 %,
`cli/main` 99 %, `core/*` 100 %, `store/backup` 93 %, `store/database` 100 %,
`store/migrations_engine` 97 %.

## 3. Charge (F12) — mesures réelles

Commande : `uv run pytest -m slow -s` — corpus fictif « tiny » (graine 2026), puis toutes les
commandes de la phase 1, puis comparaison stricte des instantanés.

| Corpus | Génération | Instantané (hash de tous les fichiers) | Octets | RAM max du processus de test | Invariant |
|---|---|---|---|---|---|
| 50 000 fichiers | 12,3 s | 0,6 s | 19 134 740 | 137 Mio | **0 différence** |
| 100 000 fichiers | 13,6 s | 1,4 s | 38 314 901 | 229 Mio | **0 différence** |

Remarque honnête : en phase 1, aucune commande ne lit encore les sources ; ce test établit la
référence et prouve l'outillage (génération reproductible, instantané, comparaison). Il sera
étendu à chaque nouveau moteur (scanner en phase 2, hash en phase 3…). La RAM indiquée est celle
du processus de test entier (générateur compris), pas une mesure de l'application.

## 4. Défauts trouvés et corrigés pendant la phase

- Le vérificateur de sécurité statique ne détectait pas `Path.open("wb")` et confondait `os.open`
  avec `Path.open` : détecté par ses propres auto-tests, corrigé.
- Connexions SQLite non fermées dans des tests : corrigé ; la suite tourne désormais avec
  `-W error::ResourceWarning` (toute fuite fait échouer les tests).
- Générateur synthétique non linéaire (100k : 38 s) : corrigé (13,6 s), sortie identique octet pour
  octet pour la même graine.
- Les tests de charge étaient lancés par défaut : désormais uniquement avec `-m slow`.

## 5. Ce qui n'a PAS été vérifié / attend un Mac

- **CI macOS** : les workflows sont écrits mais ne se déclenchent que sur pull request ou à la
  demande ; ils n'ont **pas encore été exécutés**. Les étiquettes de machines `macos-15` et
  `macos-15-intel` sont à confirmer au premier lancement.
- Les chemins macOS (`~/Library/…`) sont testés par simulation (paramètre de plateforme), pas
  encore sur un vrai Mac.
- Aucune interface graphique (PySide6 n'est pas encore une dépendance) ; aucun `.app` ni DMG.

## 6. Critères d'acceptation de la phase 1 (ARCHITECTURE § 13)

| Critère | État |
|---|---|
| `pytest` vert en CI Linux | ✅ run 42905395953 (Python 3.12 et 3.13) |
| `pytest` vert en CI macOS | ⏳ à lancer (pull request ou manuel) |
| Migration sur base vide et base N-1 | ✅ `test_base_vide_migree…`, `test_sauvegarde_avant_migration…` |
| Installation reproductible | ✅ `uv sync --frozen` + wheel installé dans un venv vierge |
| Logs et audit présents et testés | ✅ |
| Aucune donnée réelle, aucune exécution, aucun réseau | ✅ tests de sécurité |

## 7. Résultat de la CI GitHub

Exécution « CI Linux » n° 1 (déclenchée par le push du commit `9235746`) :
https://github.com/mestreguillaume72-rgb/mt4-mt5-library-manager-pro/actions/runs/42905395953

| Tâche | Résultat |
|---|---|
| Tests (Python 3.12.16, ubuntu-latest) | ✅ succès — `117 passed, 2 deselected in 5.63s`, couverture 97,54 % |
| Tests (Python 3.13, ubuntu-latest) | ✅ succès |
| Lint, format, types, construction et vérification du paquet, installation dans un environnement vierge (`mtlm version/init/etat`) | ✅ dans les deux tâches |

Avertissement non bloquant relevé : GitHub signale que les actions `checkout@v4`,
`upload-artifact@v4` et `setup-uv@v6` ciblent Node.js 20 (déprécié). Mise à jour des versions
d'actions prévue en début de phase 2.

**CI macOS : non exécutée à ce jour** (déclenchement sur pull request ou manuel).
