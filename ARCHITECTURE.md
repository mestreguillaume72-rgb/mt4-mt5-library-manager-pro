# ARCHITECTURE — MT4 MT5 Library Manager PRO

> Statut : **PROPOSITION — en attente de validation**. Aucune fonctionnalité n'est codée avant validation de ce plan.
> Documents liés : [DECISIONS.md](DECISIONS.md) · [RISQUES.md](RISQUES.md) · [PLAN_DE_TESTS.md](PLAN_DE_TESTS.md)

---

## 0. Avertissement sur les sources

Le cahier des charges PDF mentionné dans la demande **n'est pas présent dans le dépôt** (le dépôt ne contient qu'un `README.md` d'une ligne) ni ailleurs dans l'environnement de travail. Ce plan est donc construit à partir de :

1. la description du dépôt : « Application macOS de gestion et d'analyse sécurisée de bibliothèques MetaTrader » ;
2. les règles explicites de la demande (lecture seule, aucune exécution, pas de décompilation, distinction doublon / similarité / version, quarantaine réversible et confirmée, 50 000 fichiers minimum, tests à 100 000, pas de données fictives, boutons réellement fonctionnels) ;
3. des hypothèses explicites, toutes listées dans [RISQUES.md § Hypothèses](RISQUES.md#2-hypothèses).

**Q-01 (bloquante)** : fournir le PDF (commit dans `docs/cahier-des-charges/` ou pièce jointe). Ce plan sera ensuite confronté au PDF exigence par exigence (matrice de traçabilité, § 12).

---

## 1. Analyse du dépôt existant

| Élément | Constat |
|---|---|
| Contenu | `README.md` uniquement (1 commit « Initial commit ») |
| Code existant | Aucun — projet vierge, pas de dette technique |
| CI | Aucune |
| Licence | Aucune (voir Q-09) |
| Environnement d'exécution de cet agent | Conteneur Linux x86_64, **sans toolchain Swift ni Xcode** : aucune compilation/exécution macOS possible ici. La CI macOS (GitHub Actions `macos-*`) sera la référence de build et de test. |

Conséquence : l'architecture est libre ; on peut imposer dès le départ les garde-fous (lecture seule, journalisation, tests de performance) plutôt que de les rétrofitter.

---

## 2. Périmètre fonctionnel (hypothèse en attente du PDF)

| ID | Capacité | Phase |
|---|---|---|
| F-01 | Ajouter/retirer des « racines de bibliothèque » (dossiers choisis par l'utilisateur, ex. `MQL4/`, `MQL5/`, archives déjà décompressées, dossiers Wine de MetaTrader pour Mac) | P1 |
| F-02 | Inventaire **en lecture seule** : chemin, taille, dates, type, permissions, extension, empreinte | P1–P2 |
| F-03 | Classification MetaTrader : `.mq4 .mq5 .mqh .ex4 .ex5 .set .tpl .dll .mqproj .csv .ini …` + catégorie déduite du dossier (`Experts`, `Indicators`, `Scripts`, `Include`, `Libraries`, `Presets`, `Files`, `Services`…) | P1 |
| F-04 | Doublons **exacts** (octet pour octet) | P2 |
| F-05 | Analyse statique **textuelle** des sources MQL (`#property`, `#include`, `#import`, `input`/`extern`, fonctions d'entrée) — jamais d'exécution, jamais de compilation | P3 |
| F-06 | **Similarité** de sources (score explicable) et **familles de versions** | P4 |
| F-07 | **Quarantaine** réversible, traçable, toujours confirmée | P5 |
| F-08 | Recherche, filtres, tri, détail fichier, preuves affichées | P1→P6 |
| F-09 | Rapports/export (CSV, JSON) des résultats réels | P7 |
| F-10 | Journal d'audit consultable et exportable | P1→P7 |

Hors périmètre (explicitement) : exécution ou chargement de tout fichier analysé, compilation MQL (`metaeditor`), décompilation/désassemblage EX4/EX5/DLL, connexion à un terminal MetaTrader, accès réseau, suppression définitive automatique.

---

## 3. Choix technologique (résumé — détail dans DECISIONS.md D-001)

**Swift 6 + SwiftUI, avec ponts AppKit ciblés**, cœur métier en Swift Packages indépendants de l'UI.

| Critère | Swift/SwiftUI natif | Electron (TS) | Tauri (Rust + Web) | Qt/C++ ou PySide | Python + Tk/Qt |
|---|---|---|---|---|---|
| Intégration macOS (sandbox, bookmarks, FSEvents, Finder, notarisation) | ★★★ natif | ★ via modules natifs | ★★ via plugins | ★★ | ★ |
| Perf. listes 100 000 lignes | ★★★ (NSTableView) / ★★ (SwiftUI `Table`) | ★★ (virtualisation JS) | ★★ | ★★★ | ★ |
| Empreinte mémoire / taille | ★★★ | ★ (~150 Mo+) | ★★★ | ★★ | ★ |
| Surface d'attaque (runtime embarqué, npm/pip) | ★★★ faible | ★ large | ★★ | ★★ | ★ |
| Hash/IO concurrents | ★★★ (structured concurrency, CryptoKit) | ★★ | ★★★ | ★★★ | ★ (GIL) |
| Testabilité hors Mac | ★★ (cœur Foundation testable sous Linux) | ★★★ | ★★★ | ★★ | ★★★ |
| Multi-plateforme futur | ★ | ★★★ | ★★★ | ★★★ | ★★★ |

Justification : la cible est **macOS** ; les exigences dominantes sont la sécurité (aucune exécution, sandbox App Store possible, accès fichiers par bookmarks à portée de sécurité), la performance à 100 000 fichiers et la fiabilité des opérations de fichiers. Swift natif est le seul choix qui fournit tout cela sans runtime tiers. Le prix (pas de Windows/Linux) est accepté tant que le PDF ne l'exige pas (Q-03).

---

## 4. Vue d'ensemble

```
┌──────────────────────────── App (SwiftUI + AppKit) ─────────────────────────────┐
│  Sidebar racines │ Table fichiers (NSTableView) │ Inspecteur │ Quarantaine │ Journal│
│                 ViewModels (@Observable, @MainActor) — aucune logique métier     │
└───────────────┬─────────────────────────────────────────────────────────────────┘
                │ commandes async / flux de progression (AsyncStream)
┌───────────────▼─────────────────────────── LMApplication ──────────────────────┐
│  Cas d'usage : ScanLibrary, ComputeHashes, FindDuplicates, AnalyzeSources,      │
│  ComputeSimilarity, QuarantineFiles, RestoreFiles, ExportReport                 │
└──┬─────────────┬───────────────┬──────────────┬──────────────┬─────────────────┘
   │             │               │              │              │
┌──▼─────┐ ┌─────▼─────┐ ┌───────▼──────┐ ┌─────▼──────┐ ┌─────▼───────┐
│LMFile- │ │LMHashing  │ │LMMQLAnalysis │ │LMDuplicates│ │LMQuarantine │
│System  │ │           │ │              │ │& Similarity│ │             │
└──┬─────┘ └─────┬─────┘ └───────┬──────┘ └─────┬──────┘ └─────┬───────┘
   └─────────────┴───────┬───────┴──────────────┴──────────────┘
                 ┌───────▼────────┐      ┌──────────────┐
                 │  LMIndexStore  │      │  LMLogging   │  (utilisé par tous)
                 │ SQLite (WAL)   │      │ os.Logger +  │
                 └───────┬────────┘      │ journal JSONL│
                 ┌───────▼────────┐      └──────────────┘
                 │    LMCore      │  types de domaine, erreurs, identifiants
                 └────────────────┘
```

Règle de dépendance : les flèches descendent uniquement. `LMCore` ne dépend de rien. Seuls `LMFileSystem` et `LMQuarantine` touchent le système de fichiers ; **seul `LMQuarantine` peut écrire hors du conteneur de l'application** (voir § 7).

---

## 5. Découpage en modules (Swift Package `LibraryManagerKit`)

| Module | Responsabilité | Dépendances | Linux-testable |
|---|---|---|---|
| `LMCore` | Types de domaine (`FileRecord`, `ContentHash`, `MQLKind`, `DuplicateGroup`…), erreurs typées, identifiants, `Clock`/`UUIDProvider` injectables | — | Oui |
| `LMLogging` | Façade de logs : `os.Logger` (macOS) / `swift-log` (Linux) + **journal d'audit** JSONL append-only, rotation, export | `LMCore` | Oui |
| `LMFileSystem` | Énumération récursive en lecture seule, détection symlinks/boucles, fichiers iCloud non téléchargés (dataless), paquets, volumes réseau ; `ReadOnlyFileReader` (ouverture `O_RDONLY`, jamais `mmap` en écriture) ; bookmarks à portée de sécurité ; FSEvents (macOS) | `LMCore`, `LMLogging` | Partiel (FSEvents/bookmarks macOS) |
| `LMHashing` | SHA-256 en flux (CryptoKit / `swift-crypto`), pré-hash partiel (tête+queue), parallélisme borné, annulation | `LMCore`, `LMFileSystem` | Oui |
| `LMIndexStore` | Persistance SQLite (WAL, FTS5), migrations versionnées, requêtes paginées, transactions par lots | `LMCore` | Oui |
| `LMMQLAnalysis` | Détection d'encodage (UTF-16 LE/BE BOM, UTF-8, CP1252), lexer MQL tolérant, extraction de métadonnées **déclarées**, normalisation pour comparaison | `LMCore` | Oui |
| `LMDuplicates` | Doublons exacts, équivalences normalisées, similarité (shingles + MinHash/Jaccard), familles de versions, **preuves** associées | `LMCore`, `LMIndexStore`, `LMMQLAnalysis` | Oui |
| `LMQuarantine` | Déplacement confirmé, manifeste, restauration, reprise après crash, vérification d'intégrité | `LMCore`, `LMFileSystem`, `LMHashing`, `LMIndexStore`, `LMLogging` | Oui (sauf APIs macOS spécifiques) |
| `LMReports` | Exports CSV/JSON des résultats réels de l'index | `LMCore`, `LMIndexStore` | Oui |
| `LMApplication` | Orchestration des cas d'usage, progression, annulation, file d'attente de tâches | tous ci-dessus | Oui |
| `LMTestSupport` *(cible de test uniquement)* | Générateur de corpus synthétique (50k/100k), comparateur d'instantanés « avant/après » du système de fichiers | `LMCore` | Oui |
| `App` (projet Xcode) | SwiftUI + AppKit, ViewModels, menus, raccourcis, accessibilité | `LMApplication` | Non |

`LMTestSupport` n'est **jamais lié** à la cible App : impossible d'afficher des données synthétiques en production (règle « aucune donnée fictive »), vérifié par un test de dépendances en CI.

---

## 6. Modèle de données (SQLite)

Base unique par utilisateur : `~/Library/Application Support/<bundle-id>/index.sqlite` (dans le conteneur sandbox si App Store). Mode WAL, `foreign_keys=ON`, schéma versionné (`PRAGMA user_version`) avec migrations testées.

### 6.1 Tables

```sql
-- Racines choisies par l'utilisateur
library_root(
  id INTEGER PK, display_name TEXT, path TEXT,           -- chemin affiché
  bookmark BLOB,                                          -- bookmark à portée de sécurité
  volume_uuid TEXT, added_at INTEGER, last_scan_id INTEGER,
  status TEXT CHECK(status IN ('ok','unreachable','permission_denied','removed'))
)

scan_session(
  id INTEGER PK, root_id INTEGER FK, started_at, finished_at,
  status TEXT,                     -- running|completed|cancelled|failed
  files_seen, files_new, files_changed, files_missing, errors_count,
  app_version TEXT
)

-- Un enregistrement par chemin observé
file(
  id INTEGER PK, root_id FK, rel_path TEXT,               -- relatif à la racine, NFC
  rel_path_raw BLOB,                                      -- octets exacts (NFD/casse préservées)
  name TEXT, ext TEXT, size INTEGER,
  mtime_ns INTEGER, ctime_ns INTEGER, birthtime_ns INTEGER,
  inode INTEGER, device INTEGER, mode INTEGER,
  is_symlink INTEGER, is_dataless INTEGER,                -- iCloud non matérialisé
  kind TEXT,                                              -- mq4|mq5|mqh|ex4|ex5|set|tpl|dll|other…
  category TEXT,                                          -- experts|indicators|scripts|include|libraries|…|unknown
  platform TEXT,                                          -- mt4|mt5|unknown (déduit, avec source de la déduction)
  content_id INTEGER FK NULL,                             -- NULL tant que non hashé
  first_seen_scan, last_seen_scan, state TEXT,            -- present|missing|quarantined|error
  UNIQUE(root_id, rel_path_raw)
)

-- Contenu unique (déduplication par empreinte)
content(
  id INTEGER PK, sha256 BLOB UNIQUE, size INTEGER,
  head_tail_hash BLOB,                                    -- pré-filtre
  hashed_at INTEGER, verified_bytewise INTEGER DEFAULT 0
)

-- Métadonnées DÉCLARÉES dans les sources (jamais déduites d'un binaire)
mql_source_meta(
  content_id PK FK, encoding TEXT, encoding_confidence REAL,
  line_count, program_type TEXT,                          -- expert|indicator|script|library|include|service|unknown
  prop_version TEXT, prop_copyright TEXT, prop_link TEXT,
  prop_description TEXT, prop_strict INTEGER,
  normalized_sha256 BLOB,                                 -- empreinte après normalisation
  minhash BLOB,                                           -- signature (ex. 128 × uint32)
  parse_warnings TEXT                                     -- JSON
)
mql_include(content_id FK, target TEXT, is_system INTEGER, line INTEGER)
mql_import(content_id FK, module TEXT, line INTEGER)      -- ex. #import "user32.dll" → signalé, jamais chargé
mql_input(content_id FK, name TEXT, type TEXT, default_text TEXT, line INTEGER)

-- Résultats de comparaison
duplicate_group(id PK, kind TEXT CHECK(kind IN ('exact','normalized')), content_key BLOB, created_scan)
duplicate_member(group_id FK, file_id FK, is_reference INTEGER)
similarity_pair(content_a FK, content_b FK, jaccard_estimate REAL, jaccard_exact REAL NULL,
                method TEXT, computed_at, PRIMARY KEY(content_a, content_b))   -- a < b
version_family(id PK, family_key TEXT, basis TEXT)         -- basis = règle ayant formé la famille
version_member(family_id FK, file_id FK, declared_version TEXT, order_hint INTEGER)

-- Quarantaine & audit
quarantine_batch(id PK, created_at, user_confirmation_id TEXT, reason TEXT,
                 status TEXT)                              -- pending|committed|partially_restored|restored|failed
quarantine_entry(id PK, batch_id FK, file_id FK, original_abs_path BLOB,
                 quarantine_abs_path BLOB, sha256 BLOB, size, original_mode, original_mtime_ns,
                 xattrs_snapshot BLOB, state TEXT,         -- planned|moved|verified|restored|conflict|error
                 moved_at, restored_at)
audit_event(id PK, ts, actor TEXT, action TEXT, target TEXT, details TEXT /*JSON*/, outcome TEXT)

user_tag(id PK, name UNIQUE);  file_tag(file_id FK, tag_id FK)
user_note(file_id FK, text, updated_at)
setting(key PK, value)

-- Recherche plein texte (nom, chemin, #property)
CREATE VIRTUAL TABLE file_fts USING fts5(name, rel_path, prop_description, prop_copyright, content='');
```

Index : `file(root_id, state)`, `file(content_id)`, `file(size)`, `file(ext)`, `file(name)`, `content(size)`, `version_member(file_id)`.

### 6.2 Principes

- **Chemin ≠ contenu** : `file` décrit un emplacement, `content` un contenu unique. Deux fichiers partageant `content_id` sont des doublons exacts par construction.
- **Preuves explicites** : chaque résultat (doublon, similarité, version) stocke la méthode et les valeurs ayant mené à la conclusion, affichées dans l'inspecteur.
- **Provenance des métadonnées** : `program_type`, `platform`, `category` ont une source (extension, dossier, `#property`, fonction d'entrée détectée) ; rien n'est présenté comme certain s'il est déduit.
- **Aucune donnée inventée** : un champ inconnu reste `NULL` et s'affiche « Inconnu », jamais une valeur par défaut plausible.

---

## 7. Garanties de sécurité (non négociables)

| ID | Garantie | Mécanisme | Vérification |
|---|---|---|---|
| S-01 | **Lecture seule** pendant l'analyse | `ReadOnlyFileReader` ouvre en `O_RDONLY | O_NOFOLLOW` ; aucune API d'écriture n'est exposée par `LMFileSystem` ; aucun `setxattr`, `chmod`, `utimes`, `touch` | Test d'invariant avant/après (contenu, taille, mtime, mode, xattrs, liste des fichiers) sur 100k fichiers ; revue de code automatisée (grep des APIs interdites hors `LMQuarantine`) |
| S-02 | **Aucune exécution** | Aucun appel à `Process`, `NSTask`, `dlopen`, `NSWorkspace.open`, `posix_spawn`, Quick Look, `NSAppleScript` sur les fichiers analysés. Entitlements sandbox sans `com.apple.security.cs.disable-library-validation` | Test statique CI (liste noire de symboles dans le binaire et le code) ; revue |
| S-03 | **Pas de décompilation** | EX4/EX5/DLL : uniquement taille, dates, empreinte, appariement par nom avec une source. Aucun parsing de leur contenu en v1 (voir D-007) | Test : le module d'analyse refuse ces extensions |
| S-04 | **Quarantaine confirmée** | Toute action de quarantaine passe par un `QuarantinePlan` affiché (liste, tailles, destinations) + confirmation explicite ; aucun déclenchement automatique, aucune règle « auto-quarantaine » | Tests UI + tests unitaires : l'API exige un `UserConfirmation` non forgeable hors UI |
| S-05 | **Réversibilité** | Déplacement (pas copie+suppression si même volume), manifeste JSON à côté des fichiers + base SQLite, restauration vérifiée par SHA-256 | Tests aller-retour, crash au milieu, conflits |
| S-06 | **Pas de réseau** | Pas d'entitlement `network.client` | Vérif. entitlements en CI |
| S-07 | **Fichiers iCloud non matérialisés** | Détectés (`is_dataless`) et **non lus** par défaut (la lecture déclencherait un téléchargement = modification d'état) | Test dédié |

---

## 8. Pipelines

### 8.1 Scan (inventaire)
1. Résoudre le bookmark → `startAccessingSecurityScopedResource`.
2. Énumérer (`FileManager.enumerator` avec clés préchargées ou `getattrlistbulk` si mesure insuffisante) ; ne **pas** suivre les symlinks (enregistrés comme tels) ; détecter les boucles via (device, inode).
3. Comparer à l'index : (inode, size, mtime_ns) inchangés ⇒ fichier inchangé (pas de re-hash).
4. Écrire par lots de 1 000–5 000 lignes par transaction.
5. Marquer `missing` les fichiers non revus (jamais supprimés de l'index : historique).
6. Émettre progression (`AsyncStream<ScanProgress>`) ; annulable à tout moment sans état incohérent.

### 8.2 Doublons exacts — trois étages
1. Regroupement par **taille** (les tailles uniques ne peuvent pas être doublons).
2. **Pré-hash** tête+queue (64 Kio chacun) pour les collisions de taille.
3. **SHA-256 complet** uniquement sur les collisions restantes (option : SHA-256 de tous les fichiers pour l'intégrité de quarantaine).
4. Option « vérification octet par octet » avant toute quarantaine de doublons (`verified_bytewise`).

### 8.3 Analyse MQL (sources uniquement)
Détection d'encodage → décodage → lexer tolérant (commentaires, chaînes, préprocesseur) → extraction `#property`, `#include`, `#import`, `input`/`extern`/`sinput`, signatures `OnInit/OnTick/OnCalculate/OnStart/OnTimer/OnTester` → type de programme déduit (avec règle appliquée) → normalisation (suppression commentaires, espaces, fins de ligne, BOM) → `normalized_sha256` + MinHash.

### 8.4 Distinction doublon / similarité / version

| Classe | Définition opérationnelle | Preuve affichée | Action proposée |
|---|---|---|---|
| **Doublon exact** | SHA-256 identique (+ taille identique ; option octet par octet) | Empreinte, taille, chemins | Quarantaine possible (confirmée) des copies non-référence |
| **Équivalent normalisé** | Sources dont le `normalized_sha256` est identique mais le SHA-256 brut diffère (encodage, fins de ligne, commentaires, espaces) | Différences de normalisation détectées (encodage A vs B, CRLF vs LF…) | Information ; pas de quarantaine en un clic |
| **Similaire** | Sources avec Jaccard (shingles de tokens, k=5) ≥ seuil configurable (défaut 0,80), estimé par MinHash puis recalculé exactement pour les paires retenues | Score, méthode, seuil, diff textuel côte à côte | Information uniquement |
| **Version différente** | Même identité logique (nom de fichier normalisé et/ou `#property description`/nom de programme) **et** contenu différent ; ordonnancement par `#property version` si présent, sinon par date avec mention « ordre supposé » | Règle de regroupement, versions déclarées, dates | Information ; l'utilisateur choisit |
| **Binaire différent** | EX4/EX5/DLL de même nom, empreinte différente | Tailles, dates, empreintes | Aucune déduction de contenu |

Un fichier peut appartenir à plusieurs classes (ex. `v1.2` similaire à `v1.3`) ; l'UI les présente séparément, jamais fusionnées sous le mot « doublon ».

### 8.5 Quarantaine
- **Emplacement** (proposé, Q-05) : dossier `.LibraryManagerQuarantine/<batch-uuid>/` **sur le même volume** que la racine (déplacement atomique `rename(2)`), arborescence d'origine reproduite. Si non inscriptible : refus avec explication (pas de repli silencieux vers une copie inter-volume en v1).
- **Protocole en deux phases** : (1) écrire l'entrée `planned` en base + manifeste ; (2) `rename` ; (3) vérifier SHA-256 à destination ; (4) passer `verified`. Au démarrage, toute entrée `planned`/`moved` non vérifiée déclenche une **réconciliation** proposée à l'utilisateur (jamais automatique destructive).
- **Restauration** : refusée si le chemin d'origine est occupé (proposition : restaurer sous un nom suffixé, sur confirmation) ; vérification d'empreinte avant/après.
- **Purge définitive** : hors v1 ou derrière double confirmation (Q-06). Jamais automatique.

---

## 9. Concurrence & performance

- Swift 6 strict concurrency ; `actor IndexStore` (un écrivain, lecteurs WAL concurrents) ; `TaskGroup` à parallélisme borné (≈ nombre de cœurs pour le hash, 1–2 pour l'énumération disque rotatif/réseau).
- Le thread principal ne fait jamais d'IO ; la table UI lit par pages (fenêtre visible + marge) via requêtes indexées.
- Liste principale : `NSTableView` en `NSViewRepresentable` si la mesure montre que SwiftUI `Table` ne tient pas les budgets à 100k lignes (décision par mesure, D-004).

**Budgets cibles (à confirmer sur matériel de référence, Q-08 ; Mac Apple Silicon, SSD interne)** :

| Mesure | 50 000 fichiers | 100 000 fichiers (synthétique) |
|---|---|---|
| Inventaire initial (métadonnées, sans hash) | ≤ 15 s | ≤ 30 s |
| Re-scan sans changement | ≤ 5 s | ≤ 10 s |
| Hash complet (corpus ~2 Go) | limité par le débit disque, ≥ 70 % du débit séquentiel mesuré | idem |
| Mémoire résidente pic | ≤ 400 Mo | ≤ 700 Mo |
| Défilement table / filtre simple | 60 i/s ; filtre ≤ 200 ms | filtre ≤ 300 ms |
| Blocage thread principal | aucun > 100 ms (mesuré par signposts) | idem |

---

## 10. Journalisation & observabilité

- **Logs techniques** : `os.Logger(subsystem: "<bundle-id>", category: "scan|hash|mql|dup|quarantine|store|ui")`, chemins marqués `privacy: .private` ; signposts `OSSignposter` pour chaque étape (mesurable dans Instruments).
- **Journal d'audit utilisateur** (table `audit_event` + export JSONL) : ajout/retrait de racine, début/fin de scan, chaque quarantaine/restauration (avec identifiant de confirmation), exports, erreurs. Non effaçable depuis l'UI (seulement exportable/archivable).
- **Erreurs** : typées, jamais avalées ; chaque erreur de fichier est comptée dans `scan_session.errors_count` et consultable.

---

## 11. Interface (principes)

- Fenêtre principale à trois colonnes : racines & filtres ▸ table de fichiers ▸ inspecteur (métadonnées, preuves, inclusions, imports DLL signalés, historique).
- Vues dédiées : Doublons exacts · Équivalents/Similarités · Familles de versions · Quarantaine · Journal.
- **Règle « chaque bouton fonctionne »** : un contrôle n'apparaît que si son cas d'usage est implémenté et testé (pas de bouton désactivé « bientôt ») ; chaque action a un test d'UI (XCUITest) et une entrée de journal.
- États vides honnêtes : « Aucune bibliothèque ajoutée » + bouton fonctionnel « Ajouter un dossier… » ; jamais de données d'exemple.
- Accessibilité (VoiceOver, clavier), localisation FR (EN à confirmer, Q-10).

---

## 12. Roadmap par phases

Chaque phase n'est close que si : tests verts en CI, critères d'acceptation atteints, logs présents, documentation à jour (`docs/` + CHANGELOG), revue.

| Phase | Contenu | Critères d'acceptation principaux |
|---|---|---|
| **P0** Fondations | Package SwiftPM + projet Xcode, CI macOS + Linux, lint (SwiftLint/swift-format), squelette des modules, `LMLogging`, garde-fous statiques (APIs interdites) | Build + tests verts sur les deux CI ; test « API interdite » échoue si on introduit `Process` dans un module d'analyse |
| **P1** Inventaire | Racines + bookmarks, scan, index SQLite, table + recherche par nom/extension | Scan de 50k/100k synthétiques dans les budgets ; invariant lecture seule vérifié ; annulation propre |
| **P2** Empreintes & doublons exacts | Pipeline 3 étages, vue Doublons | 0 faux positif sur corpus de collisions de taille/préfixe ; résultats identiques à `shasum -a 256` |
| **P3** Analyse MQL | Encodages, lexer, métadonnées, inspecteur | Corpus « golden » : 100 % des `#property` attendus extraits ; aucun crash sur 10 000 entrées aléatoires (fuzz) |
| **P4** Similarité & versions | Normalisation, MinHash, familles | Précision/rappel mesurés sur corpus annoté ≥ seuils convenus (Q-11) |
| **P5** Quarantaine | Plan, confirmation, déplacement, restauration, réconciliation | 1 000 allers-retours sans perte ; crash simulé à chaque étape → état récupérable ; jamais d'action sans confirmation |
| **P6** UI complète | Toutes vues, accessibilité, raccourcis | Chaque bouton couvert par XCUITest ; audit accessibilité |
| **P7** Rapports | Export CSV/JSON, export journal | Exports re-lisibles, conformes au schéma documenté |
| **P8** Durcissement & distribution | Signature, notarisation, sandbox, perf finale | Notarisation OK ; budgets de perf tenus sur matériel de référence |

Une **matrice de traçabilité** (`docs/TRACABILITE.md`) reliera chaque exigence du PDF → décision → module → tests, dès réception du PDF.

---

## 13. Arborescence cible du dépôt

```
/ARCHITECTURE.md  /DECISIONS.md  /RISQUES.md  /PLAN_DE_TESTS.md  /CHANGELOG.md
/docs/cahier-des-charges/          ← PDF source (à fournir)
/docs/TRACABILITE.md
/Packages/LibraryManagerKit/Package.swift
/Packages/LibraryManagerKit/Sources/{LMCore,LMLogging,LMFileSystem,LMHashing,LMIndexStore,
                                     LMMQLAnalysis,LMDuplicates,LMQuarantine,LMReports,LMApplication}
/Packages/LibraryManagerKit/Tests/{…Tests, LMTestSupport, PerformanceTests}
/App/LibraryManagerPro.xcodeproj  /App/Sources/…  /App/UITests/…
/Fixtures/golden/                  ← échantillons MQL légalement redistribuables (Q-07)
/.github/workflows/{ci-macos.yml, ci-linux.yml, perf-nightly.yml}
```
