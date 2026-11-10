# DECISIONS — journal des décisions d'architecture (ADR)

> Format : chaque décision a un identifiant stable, un statut (`Proposée`, `Acceptée`, `Remplacée par D-xxx`, `Rejetée`), un contexte, les options étudiées, la décision et ses conséquences.
> Toutes les décisions ci-dessous sont **Proposées** : elles deviennent `Acceptées` après validation du plan par le porteur du projet et confrontation au cahier des charges PDF (non reçu, voir Q-01 dans [RISQUES.md](RISQUES.md)).

---

## D-001 — Technologie : Swift 6 + SwiftUI natif, ponts AppKit

**Contexte.** Application macOS d'analyse sécurisée, 50 000 à 100 000 fichiers, opérations de fichiers sensibles (quarantaine), aucune exécution de code tiers.

**Options.**

| Option | Pour | Contre |
|---|---|---|
| **A. Swift/SwiftUI + AppKit** | Natif : sandbox, bookmarks à portée de sécurité, FSEvents, CryptoKit, notarisation, Instruments ; faible empreinte ; pas de runtime tiers ; concurrence structurée | macOS uniquement ; SwiftUI `Table` moins mature qu'`NSTableView` pour 100k lignes ; recrutement Swift plus étroit |
| B. Electron + TypeScript | Écosystème large, multi-plateforme, UI rapide à produire | Runtime Chromium (~150 Mo, mémoire), surface d'attaque npm, accès sandbox/bookmarks via modules natifs, IO gros volumes moins performantes |
| C. Tauri (Rust + WebView) | Léger, Rust performant et sûr pour le cœur, multi-plateforme | Deux langages ; intégration sandbox/bookmarks macOS via plugins à écrire ; table 100k lignes en web à virtualiser soi-même |
| D. Qt (C++) / PySide | Multi-plateforme, `QTableView` performant | Look non natif, distribution/notarisation plus lourde, C++ moins sûr mémoire ; Python : GIL, packaging, perf hash |
| E. Kotlin Multiplatform / Compose Desktop | Multi-plateforme | JVM embarquée, intégration macOS faible |

**Décision.** A. Le cœur est écrit en **Swift pur, sans dépendance UI**, organisé en Swift Packages testables aussi sous Linux, ce qui garde ouverte une future CLI ou un portage du cœur.

**Conséquences.** CI macOS obligatoire pour l'app ; cible Linux pour le cœur (feedback rapide). Si le PDF exige Windows (Q-03), réévaluer C (Tauri) — le modèle de données et les algorithmes de ce plan restent valables.

---

## D-002 — Cible minimale : macOS 14 Sonoma (proposition)

**Raison.** Macro `@Observable`, SwiftUI `Table` et `Inspector` stables, Swift 6. macOS 13 possible avec `ObservableObject` (coût modéré). **À confirmer (Q-02).**

---

## D-003 — Persistance : SQLite (WAL + FTS5) via GRDB.swift

**Options.** Core Data · SwiftData · SQLite via GRDB · SQLite C brut · fichiers JSON.

**Décision.** SQLite via **GRDB.swift** (licence MIT, mature, migrations, observation de requêtes, FTS5).
- Core Data/SwiftData : non disponibles sous Linux (tests du cœur), contrôle fin des requêtes et des lots plus difficile, SwiftData encore jeune pour 100k+ lignes.
- SQLite brut : possible, mais réimplémente migrations/observation ; gardé en repli si la dépendance est refusée (Q-12).
- JSON : inadapté aux requêtes et à la cohérence transactionnelle.

**Conséquences.** Une dépendance tierce, épinglée par version exacte et revue. Le schéma est la source de vérité, documenté dans ARCHITECTURE § 6.

---

## D-004 — Table principale : NSTableView si la mesure l'exige

**Décision.** Prototyper la table en SwiftUI `Table` avec données paginées ; si les budgets (défilement fluide, tri/filtre ≤ 300 ms à 100k) ne sont pas atteints sur le matériel de référence, basculer sur `NSTableView` encapsulé (`NSViewRepresentable`). **Décision par mesure, consignée ici avec les chiffres.**

---

## D-005 — Empreinte : SHA-256 (CryptoKit / swift-crypto)

**Options.** MD5/SHA-1 (rapides, cassés en collisions) · xxHash/BLAKE3 (très rapides, non cryptographiques ou dépendance externe) · SHA-256.

**Décision.** **SHA-256** pour l'identité de contenu (résistant aux collisions, outillage standard `shasum -a 256` pour vérification croisée, accélération matérielle sur Apple Silicon). Pré-filtre par taille puis hash tête+queue pour éviter de tout hasher inutilement. Option « vérification octet par octet » avant quarantaine.

**Conséquences.** `swift-crypto` (Apple, API identique à CryptoKit) pour la compilation Linux du cœur.

---

## D-006 — Lecture seule stricte et absence d'exécution, garanties par conception

**Décision.**
1. `LMFileSystem` n'expose **aucune** API d'écriture ; seul `LMQuarantine` contient du code de déplacement, et il exige un `UserConfirmation` créé uniquement par la couche UI après confirmation.
2. Liste noire vérifiée en CI : `Process`, `NSTask`, `posix_spawn`, `dlopen`, `NSWorkspace.open`, `QLPreview*`, `NSAppleScript`, `setxattr`, `chmod`, `utimes`, `FileManager.removeItem` (hors `LMQuarantine`/conteneur app).
3. Pas d'entitlement réseau ; pas de `disable-library-validation`.
4. Fichiers iCloud non matérialisés : non lus par défaut.

**Conséquences.** Certaines fonctionnalités « pratiques » (ouvrir dans MetaEditor, aperçu Quick Look) sont exclues ou limitées à « Afficher dans le Finder » (qui sélectionne sans ouvrir).

---

## D-007 — EX4 / EX5 / DLL : métadonnées de système de fichiers uniquement

**Contexte.** Les binaires compilés MQL sont des formats propriétaires ; leur décompilation est contraire aux conditions d'utilisation de MetaQuotes et potentiellement illégale ; toute « information cachée » qu'on prétendrait en extraire serait non fiable.

**Décision.** En v1, pour `.ex4/.ex5/.dll` : nom, taille, dates, permissions, SHA-256, appariement avec une source de même nom dans la même bibliothèque (marqué « appariement par nom, non vérifié »). **Aucune lecture de contenu au-delà du hash.** L'UI l'indique explicitement : « Fichier compilé — contenu non analysé ».

**Question ouverte (Q-13).** Lecture éventuelle d'en-têtes publiquement documentés : seulement si le PDF l'exige, avec source documentaire citée, présentée comme « indice », et testée sur fichiers légaux.

---

## D-008 — Trois niveaux de ressemblance, jamais confondus

**Décision.** Vocabulaire et calculs distincts :
- **Doublon exact** = même SHA-256 (et même taille).
- **Équivalent normalisé** = même empreinte après normalisation documentée (encodage, fins de ligne, espaces, commentaires).
- **Similaire** = Jaccard sur shingles de 5 tokens ≥ seuil (défaut 0,80, réglable), estimé par MinHash (128 permutations) + LSH, puis **recalculé exactement** pour les paires affichées.
- **Version différente** = même identité logique, contenu différent ; ordre selon `#property version`, sinon « ordre supposé par date ».

Seuls les doublons exacts peuvent alimenter une proposition de quarantaine « en lot » ; les autres classes sont informatives.

**Conséquence.** Les seuils et la normalisation sont versionnés (`method` stocké) : un changement d'algorithme invalide et recalcule les résultats, jamais de mélange silencieux.

---

## D-009 — Quarantaine par déplacement sur le même volume, transactionnelle

**Options.** Corbeille macOS (`trashItem`) · dossier de quarantaine dans le conteneur de l'app · dossier de quarantaine sur le même volume · copie + suppression.

**Décision.** Dossier `.LibraryManagerQuarantine/<batch-uuid>/` sur **le même volume** que la racine : `rename(2)` atomique, aucun octet réécrit, métadonnées préservées. Manifeste JSON dans le lot **et** enregistrements SQLite (double traçabilité). Protocole en deux phases + réconciliation au démarrage. Pas de corbeille macOS (vidable par l'utilisateur hors de notre contrôle → non traçable).

**Conséquences.** Nécessite le droit d'écriture sur la racine (bookmark en lecture-écriture, demandé seulement au moment de la première quarantaine). Hors même volume : refus explicite en v1. **À valider (Q-05).**

---

## D-010 — Journalisation à deux niveaux

`os.Logger` + signposts (diagnostic, chemins en `.private`) ; table `audit_event` + export JSONL (actions utilisateur, traçabilité quarantaine). Le journal d'audit n'est pas modifiable depuis l'UI.

---

## D-011 — Aucune donnée fictive dans l'application livrée

Le générateur de corpus synthétique vit dans `LMTestSupport`, cible de test non liée à l'app ; test CI vérifiant le graphe de dépendances. Pas de « mode démo ». Les états vides sont réels.

---

## D-012 — Pas de fonctionnalité visible non implémentée

Un bouton/menu n'est ajouté qu'avec son cas d'usage implémenté, son test XCUITest et son entrée de journal. Pas de contrôles « à venir ». Feature flags compilés pour le travail en cours, désactivés en build Release.

---

## D-013 — Organisation du code : monorepo, Swift Package + projet Xcode mince

Le projet Xcode ne contient que l'app SwiftUI ; toute logique est dans `Packages/LibraryManagerKit`. Permet tests rapides (`swift test`), CI Linux du cœur, revue plus simple.

---

## D-014 — Qualité : Swift 6 strict concurrency, swift-format, SwiftLint

Avertissements traités comme erreurs en CI. Couverture mesurée (cible ≥ 85 % lignes sur le cœur, 100 % des chemins de `LMQuarantine`).

---

## D-015 — Nom de fichier du plan de tests

Le document demandé « PLAN DE TESTS.md » est nommé `PLAN_DE_TESTS.md` (sans espaces) pour éviter les problèmes d'échappement dans les scripts/CI et les liens Markdown. Renommage trivial si l'orthographe exacte est exigée.
