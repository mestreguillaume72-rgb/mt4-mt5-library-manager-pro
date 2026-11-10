# ARCHITECTURE — MT4 MT5 Library Manager PRO

> **Phase 0 — Audit.** Statut : **APPROUVÉ par le propriétaire le 2026-11-10** (porte de validation de la Phase 0, spécification § 8) — voir [docs/VALIDATIONS.md](docs/VALIDATIONS.md). Décisions du propriétaire : Python/PySide6 ; quarantaine **par copie uniquement**, proposée puis exécutée seulement après confirmation.
>
> Référence contractuelle : [`docs/specification/MT4-MT5-Library-Manager-PRO_dossier-developpeur_v3.0.pdf`](docs/specification/MT4-MT5-Library-Manager-PRO_dossier-developpeur_v3.0.pdf) (version 3.0, SHA-256 `dee061af…5e57cd`), appelée « la spécification » (§ = section de la spécification).
>
> Documents liés : [DECISIONS.md](DECISIONS.md) · [RISQUES.md](RISQUES.md) · [PLAN_DE_TESTS.md](PLAN_DE_TESTS.md)

---

## 1. Audit du dépôt

| Élément | Constat |
|---|---|
| Dépôt | `mestreguillaume72-rgb/mt4-mt5-library-manager-pro`, **privé** (conforme § 9) |
| Contenu | `README.md` (1 ligne), ces documents de Phase 0, la spécification PDF |
| Code | Aucun — projet vierge, aucune dette technique |
| CI | Aucune |
| Données sensibles | Aucune. Règle : **jamais** de robots, SET, DLL, données de trading ou secrets dans le dépôt (§ 9) ; seulement des données **synthétiques générées** |
| Environnement de développement distant | Conteneur Linux x86_64 : Python 3.13 et SQLite 3.53 (avec FTS5) disponibles, PySide6 installable ; **pas de Swift ni de Xcode** ; pas de macOS |
| Matériel du propriétaire | Android maintenant, Mac plus tard (modèle, architecture et version de macOS inconnus — Q-02) |

**Conséquence majeure de l'audit** : les phases 1 à 11 seront développées et testées **sans Mac**. Le choix technique doit permettre d'exécuter *réellement* les tests (moteur **et** interface) dans l'environnement distant, et en plus sur de vrais macOS via la CI GitHub, avant que le propriétaire ait son Mac (§ 9 : « faire exécuter les tests dans l'environnement distant »).

---

## 2. Exigences retenues (synthèse de la spécification)

Décisions verrouillées (§ 1) : **périmètre ALL** · **analyse SET maximum** · **quarantaine restaurable** · **50 000 fichiers minimum** · **sources en lecture seule** · **macOS (.app + DMG)** · **pilotage Android, Mac plus tard**.

| Réf. | Capacité | Phase de dév. (§ 8) |
|---|---|---|
| F1 | Sources + inventaire récursif, lecture seule, robuste (Unicode, chemins longs, symlinks cycliques, permissions) | 2 |
| F2 | Métadonnées + SHA-256 en flux, états de hash, reprise, fichier modifié pendant le scan | 3 |
| F3 | Formats (extension + signature binaire) et **archives ZIP** inspectées avec limites (bombe, traversal, chiffrées) | 4 |
| F4 | Reconnaissance MetaTrader avec **niveau de certitude** et limites affichées | 5 |
| F5 | **Analyse SET maximale** + moteur de correspondance robot/SET avec score, preuves, incertitudes | 6 |
| F6 | Familles et versions : identité logique séparée de l'empreinte | 7 |
| F7 | Doublons : exacts (taille → SHA-256 + stabilité) strictement séparés des similaires | 8 |
| F8 | Quarantaine : simulation, confirmation, manifeste transactionnel, vérification par hash, restauration, **pas de purge** | 8 |
| F9 | Bibliothèque organisée : règles, prévisualisation, **copie vérifiée** vers une destination | 9 |
| F10 | Recherche, filtres, pagination, exports CSV/JSON, rapports | 10 (moteur dès 2) |
| F11 | Interface : 13 écrans, progression, **pause/reprise/annulation**, accessibilité clavier, aucune action décorative | 10 |
| F12 | Performance et fiabilité : 50k puis 100k synthétiques, reprise après fermeture, mémoire bornée, journaux rotatifs | 11 |
| F13 | Livraison macOS : .app, DMG, Intel/Apple Silicon/Universal2, signature, matrice de compatibilité **prouvée** | 12 |

Exclusions (§ 2) : aucune exécution de contenu analysé ; pas de décompilation EX4/EX5 ni d'extraction de paramètres inaccessibles ; aucune suppression automatique de versions/similaires/associations incertaines ; aucune modification des originaux ; aucune compatibilité macOS annoncée sans preuve.

---

## 3. Choix technologique (résumé — détail et matrice pondérée dans [DECISIONS.md D-001](DECISIONS.md#d-001--pile-technologique))

**Recommandation : Python 3.12+ / PySide6 (Qt 6)**, moteur métier en paquet Python pur sans dépendance à l'interface, livré en `.app` Universal2 + DMG.
**Alternative crédible : Swift 6 / SwiftUI** natif, préférable si le propriétaire privilégie l'intégration macOS et accepte que l'interface ne soit vérifiable qu'en CI macOS (payante en dépôt privé) puis sur son Mac.

Raisons principales de la recommandation :
1. **Tests réellement exécutables maintenant** : moteur *et* interface (Qt en mode `offscreen`) testables dans l'environnement distant Linux, et sur macOS réel via GitHub Actions. Avec Swift, l'interface n'est testable que sur macOS.
2. **Lisibilité pour un propriétaire débutant** et maintenance plus accessible.
3. Les points forts de Swift (sandbox, bookmarks à portée de sécurité) ne sont **pas exigés** par la spécification (distribution hors App Store).
4. Performance suffisante : `hashlib` (C, sans verrou global pendant le hachage), `os.scandir`, SQLite intégré, `QTableView` paginé à 100 000 lignes.

Prix accepté : application plus lourde (~150–250 Mo), signature/notarisation plus délicate (nombreuses bibliothèques à signer), aspect « Qt » plutôt que 100 % natif.
**Choix du propriétaire (2026-11-10) : Python/PySide6** — D-001 acceptée.

> Le reste de ce document décrit l'architecture avec la pile recommandée. Le découpage en modules, le modèle de données, les algorithmes et la stratégie de tests sont **indépendants du langage** et restent valables avec Swift (correspondances indiquées dans D-001).

---

## 4. Vue d'ensemble en couches

```
┌───────────────────────── Interface (PySide6) — mtlm.ui ─────────────────────────┐
│ Tableau de bord · Sources · Scan · Explorateur · Détail fichier · SET ·          │
│ Familles/versions · Doublons · Quarantaine/Restauration · Organisation ·         │
│ Rapports · Paramètres · Aide           (aucune logique métier ; actions → services)│
└──────────────┬──────────────────────────────────────────────────▲────────────────┘
               │ commandes                                         │ événements (progression,
┌──────────────▼─────────────── Services applicatifs — mtlm.app ───┴───────────────┐
│ ScanService · HashService · ArchiveService · RecognitionService · SetService ·    │
│ MatchingService · FamilyService · DuplicateService · QuarantineService ·          │
│ OrganizeService · ReportService · JobManager (file bornée, pause/reprise/annul.)  │
└──┬──────────┬──────────┬───────────┬───────────┬───────────┬──────────┬──────────┘
   │          │          │           │           │           │          │
┌──▼───┐ ┌────▼───┐ ┌────▼────┐ ┌────▼─────┐ ┌───▼────┐ ┌────▼────┐ ┌───▼─────┐
│ fs   │ │hashing │ │ formats │ │metatrader│ │setfiles│ │matching │ │transfer │
│lecture│ │SHA-256 │ │signature│ │lexer MQL │ │parser  │ │familles │ │copie    │
│seule │ │en flux │ │+ ZIP    │ │+ classif.│ │+ norm. │ │doublons │ │vérifiée │
└──┬───┘ └────┬───┘ └────┬────┘ └────┬─────┘ └───┬────┘ └────┬────┘ └───┬─────┘
   └──────────┴──────────┴─────┬─────┴───────────┴───────────┴──────────┘
                   ┌───────────▼───────────┐     ┌───────────────────────┐
                   │ store : SQLite (WAL),  │     │ audit + logs          │
                   │ migrations, sauvegardes│     │ (append-only, rotatifs)│
                   └───────────┬───────────┘     └───────────────────────┘
                   ┌───────────▼───────────┐
                   │ core : types, erreurs, │
                   │ horloge, config        │
                   └───────────────────────┘
        + mtlm.cli : interface en ligne de commande (même services, sans GUI)
```

**Règles de dépendance** (vérifiées par un test automatique, `import-linter`) :
- Les dépendances ne descendent jamais vers le haut ; `core` ne dépend de rien.
- `ui` n'importe que `app` ; aucun module moteur n'importe Qt.
- **Seul `transfer` peut écrire des fichiers** (copie vers quarantaine, bibliothèque organisée, restauration). `fs`, `hashing`, `formats`, `metatrader`, `setfiles` n'ont **aucune** fonction d'écriture.
- Aucun module n'importe `subprocess`, `ctypes`, `importlib` sur des chemins analysés, `os.system`, `os.exec*`, `os.startfile`, `webbrowser`, `runpy`, `pickle` (vérifié par test statique, voir PLAN_DE_TESTS § 7).

---

## 5. Découpage en modules (paquet `mtlm`)

| Module | Responsabilité | Entrées → sorties | Écrit des fichiers ? |
|---|---|---|---|
| `mtlm.core` | Types de domaine (dataclasses figées), erreurs typées, `Clock`/`IdProvider` injectables, configuration, version du moteur | — | Non |
| `mtlm.store` | SQLite WAL, schéma, **migrations versionnées**, sauvegarde de la base (`sqlite3.backup`), écrivain unique + lecteurs, pagination par clé | requêtes → lignes | Base de l'app uniquement |
| `mtlm.audit` | Journal d'audit **append-only chaîné par hash** (table + export JSONL), journaux techniques rotatifs (`logging` + `RotatingFileHandler`) | événements → journal | Dossier de l'app uniquement |
| `mtlm.fs` | Racines, énumération récursive `os.scandir` sans suivre les symlinks, détection de cycles (device, inode), stat, lecture `O_RDONLY | O_NOFOLLOW` par blocs, détection fichiers iCloud non téléchargés (macOS) | chemin → `FileRecord` | **Non** |
| `mtlm.hashing` | SHA-256 en flux (blocs 1 Mio), états de hash, contrôle de stabilité, pré-hash optionnel | fichier → empreinte | Non |
| `mtlm.formats` | Détection par extension **et** signature (magic bytes) ; inspection ZIP **sans extraction sur disque** avec limites ; identification RAR/7z/autres par signature uniquement | fichier → format, entrées d'archive | Non |
| `mtlm.metatrader` | Encodages MQL, lexer tolérant, extraction `#property`, `input/extern/sinput`, `#include`, `#import`, fonctions d'entrée ; classification EA/indicateur/script/bibliothèque/include/service/SET/DLL/ressource avec **certitude** ; EX4/EX5 opaques | fichier → `FileAnalysis` | Non |
| `mtlm.setfiles` | Parser SET MT4/MT5, encodages, commentaires, suffixes d'optimisation, normalisation typée **en conservant la valeur brute**, comparaison SET↔SET | SET → `SetParameter[]` | Non |
| `mtlm.matching` | Moteur d'association robot↔SET (score pondéré explicable), familles/versions, doublons exacts, similarité textuelle | analyses → associations, familles, groupes | Non |
| `mtlm.transfer` | **Seul module d'écriture** : copie en flux + hash + `fsync`, vérification, manifeste transactionnel, quarantaine, restauration, copie organisée, contrôle d'espace disque, refus si destination dans une source | plan confirmé → fichiers copiés vérifiés | **Oui, uniquement vers destinations autorisées** |
| `mtlm.reports` | Exports CSV/JSON, rapports lisibles (HTML/Markdown) générés **depuis la base** | requêtes → fichiers d'export | Destination choisie par l'utilisateur, via `transfer` |
| `mtlm.app` | Services, `JobManager` (file de tâches bornée, priorité, pause/reprise/annulation, points de reprise persistés) | commandes → événements | Non (délègue) |
| `mtlm.cli` | Commandes `scan`, `hash`, `report`, `quarantine --dry-run`, etc. — utiles aux tests, au diagnostic et au travail sans Mac | arguments → sortie | Via services |
| `mtlm.ui` | PySide6 : écrans, modèles Qt paginés, registre des actions | — | Non |
| `tests/synthetic` *(hors application)* | Générateur de corpus synthétique reproductible (graine), vérité terrain JSON | paramètres → arborescence | Dossier temporaire de test |

Le générateur synthétique n'est **pas empaqueté** dans l'application (test de contenu du bundle) : aucune donnée de démonstration ne peut apparaître comme réelle.

---

## 6. Modèle de données

Base SQLite unique : `~/Library/Application Support/MT4MT5LibraryManagerPro/library.sqlite` (macOS) — **jamais dans un dossier source**. Mode WAL, `foreign_keys=ON`, `PRAGMA user_version` + table `schema_migration`. Sauvegarde automatique avant chaque migration et avant chaque opération de quarantaine.

### 6.1 Correspondance avec le modèle minimal de la spécification (§ 4)

| Entité (§ 4) | Table(s) | Compléments |
|---|---|---|
| SourceRoot | `source_root` | statut lecture seule vérifié, volume, accessibilité |
| FileRecord | `file_record`, `content` | `hash_state`, version du moteur, signature binaire |
| FileAnalysis | `file_analysis`, `mql_source_meta`, `mql_input`, `mql_include`, `mql_import` | provenance de chaque déduction + certitude |
| SetParameter | `set_file`, `set_parameter` | valeur brute **et** normalisée, bornes d'optimisation |
| Association | `association`, `association_evidence` | preuves et incertitudes ligne par ligne, validation utilisateur |
| FileFamily | `file_family`, `family_member` | relation, raison, confiance, version estimée |
| DuplicateGroup | `duplicate_group`, `duplicate_member`, `similarity_pair` | exact et similaire **dans des tables/types distincts** |
| QuarantineEntry | `quarantine_batch`, `quarantine_entry` | états transactionnels |
| ScanJob | `job`, `job_checkpoint` | pause, reprise, annulation, erreurs |
| AuditEvent | `audit_event` | append-only, chaînage `prev_hash` |
| *(ajouts)* | `archive_entry`, `organize_plan`, `organize_item`, `scan_error`, `setting` | F3, F9, F1 |

### 6.2 Schéma (extrait normatif)

```sql
source_root(id PK, path TEXT, display_name, added_at, last_scan_job_id,
            device INTEGER, read_only_verified INTEGER,      -- l'app n'a pas demandé d'écriture
            status TEXT CHECK(status IN ('ok','unreachable','permission_denied','removed')))

job(id PK, kind TEXT,                          -- scan|hash|archives|recognize|sets|match|families|duplicates|quarantine|restore|organize|report
    params_json, state TEXT CHECK(state IN ('queued','running','paused','cancelling','cancelled','completed','failed','interrupted')),
    progress_done INTEGER, progress_total INTEGER, started_at, updated_at, finished_at,
    errors_count INTEGER, engine_version TEXT)
job_checkpoint(job_id FK, key TEXT, value_json, updated_at)   -- reprise après fermeture

file_record(id PK, root_id FK, rel_path TEXT,                -- normalisé NFC pour l'affichage/recherche
            rel_path_bytes BLOB,                             -- octets exacts du système de fichiers
            name, ext, size INTEGER, mtime_ns, ctime_ns, birthtime_ns, inode, device, mode,
            is_symlink, is_dataless, magic TEXT,             -- signature binaire détectée
            content_id FK NULL,
            hash_state TEXT CHECK(hash_state IN ('not_computed','in_progress','validated','error','stale')),
            hash_error TEXT, hashed_with_engine TEXT,
            presence TEXT CHECK(presence IN ('present','missing')),
            first_seen_job, last_seen_job,
            UNIQUE(root_id, rel_path_bytes))
content(id PK, sha256 BLOB UNIQUE, size INTEGER)
scan_error(id PK, job_id FK, root_id FK, rel_path_bytes, errno, message, at)

archive_entry(id PK, archive_file_id FK, inner_path TEXT, depth INTEGER, size, compressed_size,
              is_encrypted, is_dir, content_id FK NULL,
              status TEXT,                                   -- inspected|skipped_limit|rejected_traversal|rejected_symlink|encrypted|corrupt
              reason TEXT)

file_analysis(file_id PK FK, detected_type TEXT,             -- ea|indicator|script|library|include|service|set|dll|template|resource|unknown
              platform TEXT CHECK(platform IN ('mt4','mt5','unknown')),
              certainty TEXT CHECK(certainty IN ('certain','probable','possible','unknown')),
              basis_json TEXT,                               -- règles appliquées : extension, signature, dossier, #property, OnTick…
              limits TEXT,                                   -- ex. « binaire compilé opaque : contenu non analysé »
              engine_version TEXT)
mql_source_meta(content_id PK FK, encoding, encoding_confidence, line_count,
                prop_version, prop_copyright, prop_link, prop_description, prop_strict,
                normalized_sha256 BLOB, minhash BLOB, warnings_json)
mql_input(content_id FK, ordinal, name, mql_type, default_raw, modifier TEXT, line)   -- input|extern|sinput
mql_include(content_id FK, target, is_system, line)
mql_import(content_id FK, module, line)                     -- signalé, jamais chargé

set_file(file_id PK FK, format TEXT,                         -- mt4|mt5|unknown
         encoding, line_count, param_count, duplicate_keys_json, warnings_json, normalized_sha256 BLOB)
set_parameter(file_id FK, ordinal, name, raw_value TEXT, normalized_value TEXT,
              estimated_type TEXT,                           -- bool|int|double|string|datetime|color|enum_int|unknown
              opt_start, opt_step, opt_stop, opt_enabled,    -- bornes d'optimisation si présentes
              comment TEXT, line INTEGER)

association(id PK, robot_file_id FK, set_file_id FK, score REAL, level TEXT,  -- forte|moyenne|faible|a_verifier
            engine_version, computed_at,
            user_decision TEXT CHECK(user_decision IN ('none','accepted','rejected')), decided_at)
association_evidence(association_id FK, kind TEXT, weight REAL, value REAL,
                     polarity TEXT CHECK(polarity IN ('pour','contre','incertitude')), detail_json)

file_family(id PK, logical_key TEXT, display_name, basis_json, confidence)
family_member(family_id FK, file_id FK,
              relation TEXT,              -- exact_copy|renamed_copy|version_variant|source_of|compiled_variant|homonym_different|set_for
              estimated_version TEXT, version_basis TEXT, confidence)

duplicate_group(id PK, sha256 BLOB, size, member_count, reference_file_id FK,
                verified_at, verification TEXT)           -- sha256|sha256+bytewise
duplicate_member(group_id FK, file_id FK, is_reference, admissible_for_quarantine, inadmissible_reason)
similarity_pair(file_a FK, file_b FK, kind TEXT,           -- text_normalized_equal|text_similar|set_similar
                score REAL, method TEXT, computed_at, PRIMARY KEY(file_a, file_b, kind))

quarantine_batch(id PK, created_at, destination_root,          -- copie uniquement (D-007)
                 dry_run_report_path, confirmed_at, confirmation_token, status, manifest_path)
quarantine_entry(id PK, batch_id FK, file_id FK, source_path_bytes, dest_path_bytes,
                 sha256 BLOB, size, source_mtime_ns, decision TEXT, reason TEXT,
                 state TEXT CHECK(state IN ('planned','copying','copied','verified',
                                           'restoring','restored','failed','conflict')),
                 updated_at, error)

organize_plan(id PK, created_at, destination_root, rules_json, status, collisions_count)
organize_item(plan_id FK, file_id FK, target_rel_path, collision_of FK NULL,
              state TEXT, sha256_dest BLOB, error)

audit_event(id PK, ts, actor TEXT, action TEXT, object TEXT, result TEXT, details_json,
            prev_hash BLOB, hash BLOB)                     -- triggers SQL interdisant UPDATE/DELETE
setting(key PK, value_json)

CREATE VIRTUAL TABLE search_fts USING fts5(name, rel_path, prop_description, prop_copyright, set_params);
```

Index : `file_record(root_id, presence)`, `(content_id)`, `(size)`, `(ext)`, `(hash_state)` ; `set_parameter(name)` ; `mql_input(name)` ; `association(robot_file_id)`, `(set_file_id)` ; `family_member(file_id)`.

### 6.3 Principes
- **Chemin ≠ contenu ≠ identité logique** : `file_record` = un emplacement, `content` = des octets uniques, `file_family` = « le même robot » au sens métier.
- **Rien d'inventé** : un champ inconnu reste `NULL` et s'affiche « Inconnu ». Chaque déduction stocke sa **base** et sa **certitude**.
- **Résultats versionnés** : chaque résultat porte `engine_version` ; un changement d'algorithme marque les anciens résultats « à recalculer », jamais de mélange silencieux.

---

## 7. Sécurité et protection des sources (§ 6)

| ID | Garantie | Mécanisme | Preuve |
|---|---|---|---|
| S-01 | Sources en **lecture seule** pendant les analyses | `fs` n'expose que des lectures (`os.open(O_RDONLY | O_NOFOLLOW)`), aucune écriture/renommage/`chmod`/`utime`/xattr ; aucun fichier créé dans les sources (base, journaux, caches, temporaires hors sources) | Test d'invariant avant/après (PLAN_DE_TESTS § 5) à 50k et 100k, sur Linux **et** macOS |
| S-02 | **Aucune exécution** | Aucun `subprocess`/`ctypes`/`os.exec*`/`os.system`/`open` (Finder)/import dynamique ; DLL et `#import` seulement signalés ; aucune prévisualisation Quick Look | Test statique sur le code + inspection du bundle |
| S-03 | Archives **sans extraction sur disque**, limites strictes | Lecture en flux de chaque entrée vers le hacheur, limites configurables (§ 8.3) | Tests archives hostiles |
| S-04 | Quarantaine et bibliothèque organisée sur des **destinations distinctes des sources** | Refus si la destination est dans une racine source, contient une racine source, ou est la même ; vérif. sur chemins résolus (realpath) et (device, inode) | Tests unitaires + intégration |
| S-05 | Pas de permission d'écriture sur les sources | La quarantaine est une **copie uniquement** (décision du propriétaire) : l'application n'écrit, ne déplace ni ne supprime **jamais** rien dans les sources, à aucun moment | Invariant « sources inchangées » incluant la quarantaine |
| S-06 | **En cas de doute : arrêt et demande d'intervention** | Changement de fichier (taille/mtime/inode/hash), permission insuffisante, espace insuffisant, hash incohérent → l'opération s'arrête, état persistant, message clair | Tests d'injection de fautes |
| S-07 | **Pas de télémétrie**, pas de réseau | Aucune bibliothèque réseau utilisée ; test statique ; aucun envoi de noms/chemins/contenus | Test statique |
| S-08 | Fichiers iCloud non téléchargés (macOS) | Détectés (`SF_DATALESS`) et **non lus** (la lecture déclencherait un téléchargement) | Test macOS |
| S-09 | Robustesse aux fichiers hostiles | Chaque analyseur s'exécute dans un garde (exception capturée, délai max, taille max lue) ; un fichier malformé n'arrête jamais le scan | Fuzz |

---

## 8. Moteurs et algorithmes

### 8.1 Inventaire (F1)
`os.scandir` itératif (pile explicite, pas de récursion Python), `follow_symlinks=False` ; les liens sont enregistrés comme liens, jamais suivis ; ensemble (device, inode) des dossiers visités contre les cycles (y compris via montages) ; erreurs (`EACCES`, `ENAMETOOLONG`, `ELOOP`…) consignées dans `scan_error` sans interrompre. Écriture en base par lots (2 000 lignes / transaction). Re-scan incrémental : (inode, size, mtime_ns) inchangés ⇒ pas de re-hash. Fichiers disparus ⇒ `presence='missing'` (historique conservé).

### 8.2 Empreintes (F2)
SHA-256 `hashlib` en blocs de 1 Mio, mémoire constante. Protocole de **stabilité** : `fstat` avant → hash → `fstat` après sur le même descripteur + `stat` du chemin ; différence ⇒ `hash_state='error'` (« modifié pendant la lecture »), nouvelle tentative différée. États : `not_computed → in_progress → validated | error`, `stale` si le fichier a changé depuis. Reprise : les `in_progress` trouvés au redémarrage repassent `not_computed`. Parallélisme borné (N threads, `hashlib` libère le GIL), file bornée pour la mémoire.

### 8.3 Formats et archives (F3)
- Signatures lues sur les 64 premiers octets (ZIP `PK\x03\x04`, RAR, 7z, GZIP, PE/DLL `MZ`, Mach-O, PDF, PNG/JPEG/BMP, UTF-16 BOM…). Incohérence extension/signature ⇒ signalée (« extension trompeuse »).
- **ZIP** (module standard `zipfile`, lecture seule) : on lit le répertoire central puis chaque entrée **en flux vers le hacheur** sans rien écrire. Limites par défaut (configurables, à valider Q-09) : profondeur d'imbrication ≤ 2, entrées ≤ 10 000, taille décompressée totale ≤ 2 Gio, par entrée ≤ 512 Mio, ratio ≤ 100:1 (compté sur les octets réellement décompressés, pas sur l'en-tête déclaré). Rejet : chemins absolus, `..`, lecteurs Windows `C:`, entrées symlink, noms en double ⇒ consignés. Chiffrées ⇒ `encrypted`, non inspectées. Corrompues ⇒ échec propre journalisé.
- RAR/7z/autres : **identification par signature uniquement** en v1 (pas de dépendance externe ni d'exécutable `unrar`).
- Les entrées d'archives ont leur empreinte : elles participent aux doublons exacts (« copie identique dans une archive »), jamais à la quarantaine (on ne modifie pas une archive).

### 8.4 Reconnaissance MetaTrader (F4)
| Fichier | Ce qui est lu | Classement et certitude |
|---|---|---|
| `.mq4/.mq5/.mqh` | Texte (encodage détecté : BOM UTF-16/UTF-8, sinon heuristique UTF-8 strict → CP1252) | Type par fonctions d'entrée (`OnTick`/`start` ⇒ EA, `OnCalculate`/`#property indicator_*` ⇒ indicateur, `OnStart` ⇒ script, `#property library`, `OnStart` dans `Services` ⇒ service) ; certitude `certain` si cohérent extension+contenu, `probable` sinon |
| `.ex4/.ex5` | **Rien d'autre que métadonnées + hash** | Type déduit **uniquement** du dossier (`Experts/`, `Indicators/`…) ou d'une source appariée : certitude ≤ `probable`, mention « binaire compilé opaque » |
| `.set` | Voir § 8.5 | `set`, plateforme selon syntaxe |
| `.dll` | Signature `MZ` uniquement | `dll`, jamais chargée |
| `.tpl .chr .ini .csv .htm .bmp .ico .wav…` | Signature | `resource`/`template`, certitude selon cohérence |
| autre | Signature | `unknown`, conservé (périmètre ALL) |

Limites affichées dans l'interface pour chaque fichier (champ `limits`).

### 8.5 Analyse SET maximale (F5)
- **Formats** : MT4 `Nom=Valeur` + lignes d'optimisation `Nom,F=`, `Nom,1=` (début), `Nom,2=` (pas), `Nom,3=` (fin) ; MT5 `Nom=Valeur||début||pas||fin||Y/N` ; commentaires `;` ; encodages UTF-16 LE BOM, UTF-8 (BOM ou non), CP1252.
- **Normalisation** (sans perdre la valeur brute) : booléens (`true/false/1/0` → bool **seulement** si le type source le confirme, sinon `ambigu`), nombres (point/virgule décimale, exposants), chaînes, couleurs, dates, énumérations (entiers). Clés en double ⇒ toutes conservées + avertissement ; lignes mal formées ⇒ conservées comme avertissements.
- **SET ↔ SET** : groupes de SET « presque identiques » (mêmes clés, valeurs différentes), diff paramètre par paramètre.
- **Orphelins** : SET sans aucun robot candidat au-dessus du seuil « faible ».

### 8.6 Moteur de correspondance robot ↔ SET (F5)
Score explicable 0–100, somme pondérée de critères ; **chaque critère produit une preuve** (`association_evidence`) pour, contre ou incertitude. Pondérations initiales (à calibrer sur données fictives, Q-08) :

| Critère | Poids | Disponible si |
|---|---|---|
| Couverture des noms de paramètres (|clés SET ∩ inputs source| / |clés SET| et / |inputs|) | 40 | source `.mq4/.mq5` disponible |
| Compatibilité des types (valeur SET parsable dans le type de l'input) | 15 | source disponible |
| Concordance des valeurs par défaut | 5 | source disponible |
| Similarité de noms de fichiers (nom du SET contient le nom normalisé du robot…) | 15 | toujours |
| Proximité d'emplacement (même dossier, même archive, `Presets/` voisin) | 10 | toujours |
| Cohérence de plateforme (format SET MT4/MT5 vs robot) | 10 | toujours |
| Paramètres du SET absents du robot (critère **contre**) | −20 max | source disponible |
| Cohérence de dates (indice faible) | 5 | toujours |

Niveaux : **forte** ≥ 75 *et* preuve paramétrique ; **moyenne** 50–74 ; **faible** 25–49 ; sinon non proposée. **Règle dure** : sans source lisible (robot uniquement en EX4/EX5), le niveau est plafonné à **« à vérifier »**, car les paramètres ne sont pas accessibles. Une association n'est jamais « validée » sans action de l'utilisateur. Complexité : index inversé `nom_de_paramètre → robots` pour éviter le produit cartésien SET × robots.

### 8.7 Familles et versions (F6)
Identité logique = clé normalisée du nom (minuscules, suppression des marqueurs de version `v1.2`, `_2023`, `(1)`, `copy`, `- Copie`, séparateurs) **combinée** avec `#property description`/`copyright` et la signature d'inputs (ensemble des noms). Relations (`family_member.relation`) : `exact_copy` (même SHA-256), `renamed_copy` (même SHA-256, nom différent), `version_variant` (même identité, contenu différent), `source_of` (`.mq4` ↔ `.ex4` même nom/dossier — hypothèse, certitude `possible`), `compiled_variant` (deux `.ex4` même nom, hash différent), `homonym_different` (même nom, identité différente : inputs/description divergents). Version estimée : `#property version` > version dans le nom > ordre des dates (marqué « supposé »). La raison et la confiance sont affichées.

### 8.8 Doublons (F7) — séparation stricte
| Classe | Définition | Quarantaine possible ? |
|---|---|---|
| **Doublon exact** | Même taille **et** même SHA-256, empreintes `validated`, fichiers **stables** (revérifiés juste avant toute action) ; option comparaison octet par octet | Oui, après simulation + confirmation, si *admissible* |
| **Équivalent normalisé** | Sources/SET identiques après normalisation (encodage, fins de ligne, espaces, commentaires) mais octets différents | **Non** |
| **Similaire** | Similarité de texte (Jaccard sur shingles de 5 tokens, estimée par MinHash 128 + LSH, **recalculée exactement** pour l'affichage) ≥ seuil (défaut 0,80) | **Non** |
| **Version différente** | Même identité logique (§ 8.7), contenu différent | **Non** |

**Admissibilité à la quarantaine** d'un membre d'un groupe exact : il n'est pas la référence ; la référence existe, est lisible et a le même hash vérifié à l'instant T ; le membre est stable ; il n'est pas dans une archive ; il n'est pas un lien symbolique. Il reste **toujours au moins une copie** (la référence) dans les sources. Référence proposée : chemin le plus court/plus ancien, modifiable par l'utilisateur.

### 8.9 Quarantaine et restauration (F8)
1. **Simulation (dry-run)** obligatoire : liste, tailles, destination, espace requis, motifs d'inadmissibilité → rapport enregistré.
2. **Confirmation explicite** de l'utilisateur (jeton lié au rapport de simulation ; tout changement invalide la confirmation).
3. Pour chaque entrée, **manifeste transactionnel** (JSON dans la destination + table) : `planned → copying → copied → verified`. Copie en flux vers un fichier temporaire dans la destination, `fsync`, hash de la copie = hash attendu, renommage atomique au nom final, puis `verified`.
4. **Copie uniquement** (décision du propriétaire, D-007) : la source n'est jamais touchée. La quarantaine est **proposée** (simulation) et n'est exécutée **qu'après confirmation** ; les fichiers en quarantaine sont marqués comme tels dans l'index et exclus de la bibliothèque organisée (F9). Il n'existe aucun mode de déplacement ni de suppression.
5. **Échec** à toute étape (disque plein, interruption, hash différent, destination existante) ⇒ arrêt, état persistant, **l'original est toujours intact** ; une copie partielle est signalée et jamais marquée `verified`.
6. **Restauration** (sortie de quarantaine) : le fichier est retiré de l'état « en quarantaine » dans l'index ; si l'original a disparu entre-temps (supprimé hors de l'application), la copie vérifiée peut être recopiée vers son chemin d'origine si libre ; conflit ⇒ arrêt et choix utilisateur (autre nom/annuler), jamais d'écrasement ; vérification du hash après restauration ; la copie de quarantaine est conservée.
7. **Aucun bouton de purge**. Au redémarrage, les lots non terminés sont présentés pour reprise ou annulation (jamais d'action automatique destructive).

### 8.10 Bibliothèque organisée (F9)
Règles configurables (gabarit de chemin) : `{plateforme}/{type}/{famille}/{version}/{nom}` + dossiers `SET/associés`, `SET/à vérifier`, `SET/orphelins`, `Inconnus/`. Prévisualisation complète (arborescence + collisions de noms + espace nécessaire) avant copie. Copie via `transfer` (même protocole que la quarantaine : flux, `fsync`, hash, renommage atomique), **reprise** possible (les éléments `verified` sont sautés), collisions résolues par suffixe déterministe et **rapportées**. Doublons exacts copiés **une seule fois** (option). Originaux jamais modifiés.

### 8.11 Recherche, filtres, rapports (F10)
FTS5 + filtres combinables (plateforme, type, certitude, état de hash, famille, statut SET, doublon, erreurs), pagination par clé (`WHERE (tri, id) > (?, ?) LIMIT n`) stable à 100k. Exports CSV (UTF-8 avec BOM pour Excel, échappement RFC 4180) et JSON (schéma documenté), rapports HTML lisibles. Tout est calculé depuis la base.

---

## 9. Tâches, concurrence, reprise (F11, F12)

- `JobManager` : file **bornée** de tâches persistées (`job`), un worker par type lourd, parallélisme configurable (hash : nb cœurs ; disques réseau : 1–2).
- **Pause** : les workers terminent l'élément en cours puis attendent (événement). **Annulation** : arrêt à la frontière d'élément, état cohérent, `cancelled`. **Reprise après fermeture** : au démarrage, les jobs `running`/`paused` passent `interrupted` et sont proposés à la reprise depuis `job_checkpoint` (curseur de scan, éléments déjà traités).
- Écrivain SQLite unique (thread dédié + file) ; lecteurs WAL concurrents pour l'interface.
- L'interface ne fait **jamais** d'E/S sur le thread principal ; progression transmise par signaux Qt, limitée à ~10 rafraîchissements/s.
- Mémoire bornée : aucun chargement complet d'inventaire ; modèles Qt paginés (`fetchMore`) ; caches LRU dimensionnés.

### Budgets de performance (proposés, à valider — Q-07 ; mesurés en CI macOS et en local)

| Mesure | 50 000 fichiers | 100 000 fichiers |
|---|---|---|
| Inventaire initial (sans hash), SSD | ≤ 60 s | ≤ 120 s |
| Re-scan sans changement | ≤ 20 s | ≤ 40 s |
| Hash complet | ≥ 60 % du débit séquentiel mesuré du disque | idem |
| RAM maximale (processus) | ≤ 600 Mo | ≤ 800 Mo |
| Filtre/tri dans l'explorateur | ≤ 300 ms | ≤ 500 ms |
| Temps de reprise après fermeture | ≤ 10 s avant reprise effective | ≤ 15 s |
| Thread d'interface bloqué | jamais > 200 ms | idem |

Les rapports de charge consignent : durée, débit (fichiers/s, Mo/s), RAM max, erreurs, temps de reprise, matériel, OS, commande exécutée (§ F12).

---

## 10. Journaux et audit

- **Journaux techniques** rotatifs (`logging`, 10 × 5 Mo) dans `~/Library/Logs/MT4MT5LibraryManagerPro/` ; niveaux ; chaque tâche logge début, fin (durée, compteurs) ou échec (erreur typée).
- **Journal d'audit append-only** : ajout/retrait de source, scans, simulations, confirmations, chaque copie/vérification/suppression/restauration, validations d'associations, exports. Chaînage par hash (`prev_hash`) ⇒ toute altération est détectable ; triggers SQL interdisant `UPDATE`/`DELETE` ; export JSONL.
- **Rapports de phase** : `docs/rapports/phase-NN.md` (commandes exécutées, environnement, résultats réels, ce qui attend le Mac) — exigence § 7 et § 9.

---

## 11. Interface (F11)

13 écrans (§ F11) : **Tableau de bord** (compteurs réels, tâches en cours) · **Sources** · **Scan** (progression, pause, reprise, annulation, erreurs) · **Explorateur** (table paginée, filtres) · **Détail fichier** (métadonnées, certitude, limites, preuves, familles, associations, historique) · **SET** (paramètres bruts/normalisés, associations avec preuves, validation accepter/rejeter) · **Familles/versions** · **Doublons** (exacts vs similaires dans des onglets distincts) · **Quarantaine/Restauration** (simulation, confirmation, manifeste, restauration) · **Organisation** (règles, prévisualisation, copie) · **Rapports** · **Paramètres** (limites d'archives, seuils, parallélisme) · **Aide** (en français, limites des formats opaques).

Règles :
- **Registre d'actions** central : chaque bouton/menu est une `Action` liée à un service réel. Une action non encore disponible est **visible mais désactivée avec le libellé « non disponible »** et une explication (§ 7) ; aucune action ne simule un succès.
- Un test parcourt le registre et **échoue** si une action activée n'a pas de gestionnaire réel ou si un gestionnaire est un bouchon.
- États vides honnêtes (« Aucune source ajoutée » + bouton « Ajouter un dossier… » fonctionnel).
- Accessibilité clavier complète, libellés accessibles, contraste ; textes en français simple pour un débutant.
- Dialogues natifs macOS de sélection de dossier (`QFileDialog` natif).

---

## 12. Livraison macOS (F13)

- Empaquetage : **PyInstaller** (`--windowed`, bundle `.app`) — Briefcase en alternative ; Python officiel *universal2* + roues PySide6 *universal2* ⇒ **Universal2 visé**, à confirmer par build réel (sinon deux builds arm64 / x86_64).
- DMG : `hdiutil create` (outil système macOS).
- Signature Developer ID + notarisation (`notarytool`) si distribution hors usage local : **nécessite un compte Apple Developer** (Q-03). Sans compte : usage local documenté (ouverture via clic droit → Ouvrir), limites indiquées.
- **Matrice de compatibilité** (`docs/COMPATIBILITE.md`) : version macOS × architecture × statut × **preuve** (lien vers run CI ou rapport de test sur Mac réel) × limites. Aucune ligne sans preuve.
- CI : GitHub Actions `macos-14` (Apple Silicon) et `macos-13` (Intel) pour tests + build `.app`/DMG ; Linux pour l'essentiel des tests à chaque commit (coût : minutes macOS ×10 en dépôt privé — R-12).
- Documentation utilisateur (français) : installation, mise à jour, désinstallation, sauvegarde/restauration de la base et procédure de restauration de quarantaine.

---

## 13. Plan de développement et portes de validation (§ 8)

Chaque phase : branche dédiée → code + tests + doc → **rapport de phase** (commandes et résultats réels) → **attente de l'accord du propriétaire** avant la phase suivante.

| Phase | Livrable | Critères d'acceptation observables | Besoin d'un Mac ? |
|---|---|---|---|
| **0 — Audit** | Ces 4 documents + spécification dans le dépôt | Approbation écrite | Non |
| **1 — Socle** | Structure du paquet, config, `audit`/logs, `store` + migrations + sauvegarde, CLI minimale, CI Linux + macOS, tests statiques de sécurité, générateur synthétique | `pytest` vert en CI Linux et macOS ; migration aller sur base vide et base N-1 ; installation reproductible (`uv`/`pip` + verrou) | Non (CI macOS) |
| **2 — Scanner** | Inventaire universel lecture seule (CLI + service) | Compteurs **exacts** = vérité terrain ; extensions inconnues conservées ; cycles/permissions/Unicode OK ; invariant lecture seule vert | Non |
| **3 — Métadonnées** | SHA-256 en flux, états, stabilité, reprise | Hashes = `sha256sum` ; originaux inchangés ; fichier modifié pendant lecture détecté ; reprise après arrêt forcé | Non |
| **4 — Archives** | Inspection ZIP sécurisée | Archives saines/corrompues/bombe/traversal/doublons/chiffrées : comportement attendu, échec propre journalisé | Non |
| **5 — MetaTrader** | Reconnaissance + certitude + limites | Corpus fictif classé conformément ; extensions trompeuses signalées ; EX4/EX5 « opaques » | Non |
| **6 — SET** | Parser + correspondance | Tous les cas § F5 ; associations avec preuves ; ambiguïtés → « à vérifier » | Non |
| **7 — Versions** | Familles et variantes | Tous les cas § F6 distingués correctement | Non |
| **8 — Doublons** | Détection + quarantaine + restauration | Tous les cas § F7/F8, dry-run et restauration testés, injection de fautes | Non (+ CI macOS) |
| **9 — Organisation** | Prévisualisation + copie vérifiée | Hash destination conforme, collisions rapportées, reprise | Non |
| **10 — Interface** | 13 écrans reliés aux moteurs | Parcours complets pytest-qt, registre d'actions vérifié, clavier | Partiel (rendu final sur Mac) |
| **11 — Performance** | Charge 50k/100k + sécurité | Rapport mesuré (durée, débit, RAM, erreurs, reprise) dans les budgets validés | CI macOS + Mac réel recommandé |
| **12 — Mac** | `.app`, DMG, signature, matrice | Installation et tests sur **Mac réel** du propriétaire | **Oui** |

---

## 14. Arborescence cible

```
README.md  ARCHITECTURE.md  DECISIONS.md  RISQUES.md  PLAN_DE_TESTS.md  CHANGELOG.md
docs/specification/…pdf          spécification contractuelle
docs/TRACABILITE.md              exigence → module → tests → preuve
docs/COMPATIBILITE.md            matrice macOS (phase 12)
docs/rapports/phase-NN.md        rapports de phase (résultats réels)
docs/utilisateur/                guide FR (installation, sauvegarde, restauration)
pyproject.toml  uv.lock          dépendances épinglées
src/mtlm/{core,store,audit,fs,hashing,formats,metatrader,setfiles,matching,transfer,reports,app,cli,ui}/
tests/{unit,integration,ui,security,perf}/
tests/synthetic/                 générateur de corpus (non empaqueté)
packaging/macos/                 spec PyInstaller, Info.plist, script DMG
.github/workflows/{ci.yml,macos.yml,perf-nightly.yml}
```

---

## 15. Traçabilité spécification → architecture

| Spécification | Section ici | Tests (PLAN_DE_TESTS) |
|---|---|---|
| § 1 Décisions | § 2, 7 | § 5, 7 |
| F1 | § 8.1 | § 3.2 |
| F2 | § 8.2 | § 3.3 |
| F3 | § 8.3 | § 3.4 |
| F4 | § 8.4 | § 3.5 |
| F5 | § 8.5, 8.6 | § 3.6, 3.7 |
| F6 | § 8.7 | § 3.8 |
| F7 | § 8.8 | § 3.9 |
| F8 | § 8.9 | § 3.10 |
| F9 | § 8.10 | § 3.11 |
| F10 | § 8.11 | § 3.12 |
| F11 | § 11 | § 3.13 |
| F12 | § 9 | § 4, 5 |
| F13 | § 12 | § 3.14 |
| § 4 Modèle | § 6 | § 3.1 |
| § 5 Architecture | § 4, 5, 9 | § 7 |
| § 6 Sécurité | § 7 | § 5, 6, 7 |
| § 7 Qualité | § 11, 13 | § 8 |
| § 11 Livraison | § 12 | § 3.14 |

Le détail ligne à ligne sera maintenu dans `docs/TRACABILITE.md` à partir de la Phase 1.
