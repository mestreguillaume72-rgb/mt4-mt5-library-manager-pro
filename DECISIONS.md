# DECISIONS — journal des décisions (ADR)

> Statuts : `Verrouillée (spéc.)` = imposée par la spécification § 1 ; `Proposée` = à approuver en Phase 0 ; `Acceptée` après approbation écrite ; `Remplacée par D-xxx` ; `Rejetée`.
> Référence : `docs/specification/MT4-MT5-Library-Manager-PRO_dossier-developpeur_v3.0.pdf`.

---

## Décisions verrouillées par la spécification (§ 1)

| ID | Décision | Conséquence dans l'architecture |
|---|---|---|
| V-1 | Périmètre **ALL** | Tous les fichiers inventoriés, extensions inconnues conservées (`detected_type='unknown'`) |
| V-2 | Analyse SET **maximum** | Modules `setfiles` + `matching`, preuves et incertitudes |
| V-3 | Nettoyage par **quarantaine restaurable** | Module `transfer`, manifeste, pas de purge |
| V-4 | **50 000+** fichiers | Flux, index, pagination, tests 50k/100k |
| V-5 | Sources en **lecture seule** pendant les analyses | Modules d'analyse sans écriture ; invariant testé |
| V-6 | **macOS**, `.app` + DMG, compatibilité **testée** | CI macOS + matrice avec preuves |
| V-7 | Pilotage **Android**, Mac plus tard | Tout testable sans Mac jusqu'à la phase 12 |

---

## D-001 — Pile technologique

**Statut : Proposée — choix final au propriétaire (Q-01).**

**Contexte.** La spécification (§ 5) impose de comparer au moins une solution native (Swift/SwiftUI) et une solution multiplateforme (ex. Python/PySide), selon : dépendances, performances, compatibilité macOS, signature, maintenance, facilité de build. Contexte décisif : le propriétaire est **débutant**, pilote **depuis Android**, et n'aura un Mac qu'en **phase 12** ; chaque phase doit fournir des **résultats de tests réellement exécutés** (§ 7, § 9). L'environnement de développement distant est Linux (Python 3.13 présent, PySide6 installable ; pas de Swift).

> Note : une première version de ce document (avant lecture du PDF) recommandait Swift. La lecture de la spécification — en particulier le développement sans Mac jusqu'à la phase 12 et l'obligation de résultats de tests réels à chaque phase — a inversé la recommandation.

**Options comparées.**

| Critère (poids) | A. Swift 6 / SwiftUI (+AppKit) | B. Python 3.12+ / PySide6 | C. Tauri (Rust + web) | D. Electron (TypeScript) |
|---|---|---|---|---|
| Tests réels sans Mac — moteur (20) | 3/5 : Swift sur Linux possible mais toolchain à installer ; APIs macOS (FSEvents, bookmarks) non testables | **5/5** : tout le moteur tourne et se teste ici | 4/5 | 4/5 |
| Tests réels sans Mac — interface (15) | **1/5** : SwiftUI uniquement sur macOS (CI payante) | **4/5** : Qt `offscreen` + pytest-qt ici ; rendu final à vérifier sur Mac | 3/5 : WebDriver, WebView différente selon OS | 3/5 |
| Performance 50k–100k (15) | **5/5** | 4/5 : `hashlib`/`scandir`/SQLite en C ; `QTableView` paginé | 5/5 | 3/5 |
| Compatibilité macOS / intégration (10) | **5/5** natif | 3/5 : dialogues natifs, aspect Qt | 3/5 | 3/5 |
| Signature / notarisation / build (10) | **5/5** Xcode | 3/5 : PyInstaller + signature de nombreux binaires, faisable | 4/5 | 3/5 |
| Universal2 Intel + Apple Silicon (5) | **5/5** | 4/5 : roues PySide6 universal2, à prouver par build | 4/5 | 4/5 |
| Taille / mémoire (5) | **5/5** (~10–20 Mo) | 2/5 (~150–250 Mo) | 5/5 | 1/5 |
| Maintenance par un débutant (10) | 2/5 | **5/5** | 2/5 (deux langages) | 3/5 |
| Dépendances / chaîne d'approvisionnement (5) | **5/5** (quasi aucune) | 4/5 (PySide6 + quelques libs de test) | 3/5 | 1/5 (npm) |
| Multiplateforme futur (5) | 1/5 | **5/5** | 5/5 | 5/5 |
| **Score pondéré /500** | **350** | **405** | **375** | **315** |

(Score = Σ note × poids ; ex. A = 60+15+75+50+50+25+25+20+25+5 = 350 ; B = 100+60+60+30+30+20+10+50+20+25 = 405. Les notes sont des jugements d'ingénierie argumentés ci-dessus, pas des mesures. Les poids reflètent les priorités de la spécification : « fiabilité, traçabilité et protection avant vitesse ou apparence ».)

**Recommandation : B — Python 3.12+ / PySide6.**
- Toutes les phases 1 à 11 produisent des **résultats de tests réels** dès maintenant (Linux) et sur macOS réel via GitHub Actions (`macos-14` arm64, `macos-13` Intel).
- Le moteur est un paquet Python pur, testable sans interface (§ 5).
- Plus lisible et explicable au propriétaire.

**Quand préférer A (Swift)** : si le propriétaire valorise un rendu 100 % natif, une application légère et une intégration macOS maximale, et accepte que l'interface ne soit vérifiée qu'en CI macOS (minutes payantes en dépôt privé) puis sur son Mac. L'architecture (modules, modèle de données, algorithmes, tests) se transpose : `mtlm.*` → Swift Packages `LM*`, SQLite via GRDB, `hashlib` → CryptoKit, pytest → Swift Testing/XCUITest.

**Conséquences de B.** Python officiel universal2 pour le build ; PySide6 épinglé ; PyInstaller ; signature de tous les binaires embarqués ; taille plus importante assumée.

---

## D-002 — Version minimale de macOS

**Statut : Proposée, à arbitrer selon le Mac du propriétaire (Q-02).**
Proposition : **macOS 12 Monterey ou plus récent** (PySide6 6.x récent exige macOS 12+ ; à revérifier sur la version épinglée). Rien n'est annoncé compatible sans preuve (matrice § F13).

---

## D-003 — Persistance : SQLite (module standard `sqlite3`), WAL, FTS5

**Statut : Proposée.** Conforme § F10 (« SQLite ou équivalent »). Aucune dépendance externe ; transactions, migrations versionnées maison (scripts SQL numérotés + `PRAGMA user_version`), sauvegarde par `sqlite3.Connection.backup` avant migration et avant chaque quarantaine. ORM rejeté : contrôle fin des lots et des requêtes paginées nécessaire à 100k.

---

## D-004 — Empreinte : SHA-256 en flux, protocole de stabilité

**Statut : Proposée** (SHA-256 imposé § F2/F7). Blocs de 1 Mio, `fstat` avant/après, quatre états + `stale`. Collision « théorique » (§ F7) : option comparaison octet par octet avant quarantaine.

---

## D-005 — EX4/EX5 : binaires opaques

**Statut : Proposée** (conforme § 2, § F4). Seuls nom, taille, dates, signature et SHA-256. Type déduit seulement du dossier ou d'une source appariée, certitude ≤ « probable ». Aucune lecture de structure interne, aucune décompilation, aucune extraction de paramètres. Toute éventuelle lecture d'en-tête future exigerait une documentation publique vérifiable et une nouvelle décision.

---

## D-006 — Archives : ZIP en lecture en flux sans extraction ; autres formats identifiés seulement

**Statut : Proposée.** `zipfile` standard ; aucune écriture sur disque ; limites de profondeur, taille, ratio, nombre d'entrées (valeurs § ARCHITECTURE 8.3, à valider Q-09). RAR/7z : signature uniquement (éviter dépendances natives et outils externes = risque d'exécution). Les fichiers dans des archives ne sont jamais mis en quarantaine.

---

## D-007 — Quarantaine : destination distincte, copie vérifiée, mode `copy` par défaut

**Statut : Proposée — mode `move` à trancher (Q-04).**
- Destination choisie par l'utilisateur, **hors de toute source** (§ 6) ; vérification par chemins résolus et (device, inode).
- Protocole : simulation → confirmation (jeton lié à la simulation) → copie en flux vers fichier temporaire → `fsync` → hash → renommage atomique → `verified`.
- **`copy` (défaut)** : sources jamais modifiées ; la quarantaine sert de mise à l'écart vérifiée, et la bibliothèque organisée (F9) exclut les doublons.
- **`move` (option)** : suppression de l'original **après** `verified` et re-vérification de stabilité ; seule opération de toute l'application qui écrit dans une source ; nécessite confirmation renforcée.
- Pas de corbeille macOS (non traçable), pas de purge (§ F8).

---

## D-008 — Distinction doublon exact / équivalent / similaire / version

**Statut : Proposée** (§ F6, F7). Quatre classes, tables et onglets distincts ; seuls les doublons **exacts admissibles** peuvent entrer en quarantaine. Similarité : Jaccard sur shingles de 5 tokens, MinHash 128 + LSH, recalcul exact affiché, seuil par défaut 0,80 (Q-10). `engine_version` stocké avec chaque résultat.

---

## D-009 — Associations robot↔SET : score pondéré explicable, plafonné sans source

**Statut : Proposée** (§ F5). Critères et poids : ARCHITECTURE § 8.6. Règles dures : pas de niveau « forte » sans preuve paramétrique ; robot sans source lisible ⇒ plafond « à vérifier » ; aucune association validée sans l'utilisateur.

---

## D-010 — Audit append-only chaîné + journaux rotatifs

**Statut : Proposée** (§ 5, § F12). Table `audit_event` avec `prev_hash`/`hash`, triggers interdisant `UPDATE`/`DELETE`, export JSONL ; `logging` rotatif.

---

## D-011 — Aucune maquette, actions « non disponible » explicites

**Statut : Proposée** (§ 7). Registre central d'actions ; action non implémentée = désactivée avec libellé « non disponible » ; test qui échoue si une action activée n'est pas branchée ; générateur synthétique non empaqueté (test de contenu du bundle).

---

## D-012 — Outillage qualité

**Statut : Proposée.** `uv` (ou `pip-tools`) avec fichier de verrouillage ; `ruff` (lint + format) ; `mypy --strict` sur `src/mtlm` ; `pytest`, `pytest-qt`, `hypothesis` (tests de propriétés), `pytest-cov` ; `import-linter` (règles de dépendances) ; couverture ≥ 85 % moteur, 100 % des branches de `transfer`.

---

## D-013 — CI : Linux à chaque commit, macOS ciblé, charge 100k la nuit

**Statut : Proposée** (coût macOS — R-12). `ci.yml` (Linux) : lint, types, tests, sécurité statique, invariant lecture seule 50k. `macos.yml` (PR + manuel) : tests sur `macos-14`/`macos-13`, invariant macOS, build `.app`. `perf-nightly.yml` (manuel/planifié) : 100k, rapport de charge en artefact.

---

## D-014 — Données de test : 100 % synthétiques dans le dépôt

**Statut : Proposée** (§ 9). Générateur à graine fixe produisant robots/SET **fictifs** et vérité terrain ; les exemples fictifs fournis par le propriétaire (Annexe) sont acceptés s'ils ne contiennent aucune donnée réelle. Aucun vrai robot, SET, DLL dans Git (contrôle `.gitignore` + test qui refuse `.ex4/.ex5/.dll` hors `tests/synthetic` générés à la volée).

---

## D-015 — Nom du plan de tests

Le document « PLAN DE TESTS.md » est nommé `PLAN_DE_TESTS.md` (sans espaces) pour la robustesse des scripts et des liens. Renommage trivial si l'orthographe exacte est exigée.
