# RISQUES — risques, hypothèses, limites et questions bloquantes

> Statut : **PROPOSITION — en attente de validation.**
> Échelles : Probabilité (P) et Impact (I) de 1 (faible) à 3 (fort). Criticité = P × I.

---

## 1. Questions bloquantes (à trancher avant de coder P1)

| ID | Question | Pourquoi c'est bloquant | Proposition par défaut |
|---|---|---|---|
| **Q-01** | **Où est le cahier des charges PDF ?** Il n'est ni dans le dépôt ni dans l'environnement. | Toutes les exigences de ce plan sont des hypothèses tant qu'il n'est pas lu. | Le committer dans `docs/cahier-des-charges/` ; je produirai la matrice de traçabilité et réviserai ces 4 documents. |
| Q-02 | Version minimale de macOS ? | Conditionne APIs SwiftUI (`@Observable`, `Table`, `Inspector`). | macOS 14 |
| Q-03 | Windows/Linux sont-ils requis (maintenant ou plus tard) ? | Remettrait en cause D-001. | macOS uniquement |
| Q-04 | Distribution : Mac App Store (sandbox obligatoire) ou Developer ID notarisé hors Store ? Compte Apple Developer disponible ? | Sandbox, entitlements, signature CI. | Sandbox activée dans les deux cas ; Developer ID d'abord |
| Q-05 | Emplacement de la quarantaine accepté (dossier caché sur le même volume que la bibliothèque) ? | La règle « préserver strictement les originaux » entre en tension avec un déplacement, même confirmé. | Oui, déplacement confirmé = seule écriture autorisée |
| Q-06 | Suppression définitive (purge de la quarantaine) : autorisée ? | Irréversible. | Hors v1 ; sinon double confirmation + journal |
| Q-07 | Peut-on disposer d'un corpus réel de fichiers MQL **légalement utilisables** pour les tests « golden » (vos propres sources, ou exemples MetaQuotes redistribuables) ? | Les tests sur fichiers réels (encodages, variantes MT4/MT5) ne peuvent pas être uniquement synthétiques. | Corpus fourni par vous, stocké hors dépôt public si non redistribuable |
| Q-08 | Matériel de référence pour les budgets de performance ? | Les chiffres n'ont de sens que sur une machine donnée. | MacBook Air/Pro Apple Silicon M1+, SSD interne |
| Q-09 | Licence du projet ? | Choix des dépendances (GRDB MIT compatible avec tout). | Propriétaire / tous droits réservés |
| Q-10 | Langues de l'interface ? | Localisation dès P1. | Français, anglais en option |
| Q-11 | Seuils d'acceptation de la similarité (précision/rappel) et seuil par défaut ? | Critère d'acceptation P4. | Précision ≥ 0,95 ; rappel ≥ 0,90 ; seuil 0,80 |
| Q-12 | Dépendances tierces acceptées (GRDB.swift, swift-crypto, swift-log) ? | Politique de sécurité de la chaîne d'approvisionnement. | Oui, épinglées et revues |
| Q-13 | Le PDF exige-t-il des informations sur EX4/EX5 au-delà du hash ? | Risque légal et de fiabilité (cf. D-007). | Non |
| Q-14 | Archives (`.zip`, `.rar`) : à inventorier sans extraire, à ignorer, ou à extraire dans un espace temporaire ? | Extraction = écriture + surface d'attaque (zip bombs, chemins `../`). | Inventoriées comme fichiers, non ouvertes en v1 |

---

## 2. Hypothèses

| ID | Hypothèse | Si fausse… |
|---|---|---|
| H-01 | L'application cible uniquement macOS (description du dépôt). | Réévaluer D-001. |
| H-02 | Les bibliothèques sont des dossiers déjà présents sur disque (local, externe, éventuellement réseau), pas un accès direct à un terminal MT4/MT5 en marche. | Ajouter un module d'intégration, hors sécurité actuelle. |
| H-03 | MetaTrader sur Mac (Wine/CrossOver) stocke ses fichiers sous `~/Library/Application Support/net.metaquotes.wine.metatrader{4,5}/drive_c/...` ; l'utilisateur choisit le dossier via un panneau d'ouverture (sandbox). | Seul l'aide au choix change. |
| H-04 | Volume type : 50 000 fichiers, majoritairement < 1 Mo, total quelques Go. | Budgets de perf à revoir si fichiers volumineux (historiques `.hst`, `.hcc`). |
| H-05 | Les sources `.mq4` sont souvent en CP1252/ANSI ou UTF-16 LE, les `.mq5` en UTF-16 LE avec BOM ; des fichiers mal encodés existent. | Le détecteur d'encodage est conçu tolérant ; affiner sur corpus réel. |
| H-06 | Un seul utilisateur, une seule base par compte macOS. | Multi-utilisateur/partage réseau de l'index hors v1. |
| H-07 | L'utilisateur accepte que les seules écritures de l'app hors de son conteneur soient les déplacements de quarantaine confirmés. | Voir Q-05. |

---

## 3. Registre des risques

| ID | Risque | P | I | Crit. | Mitigation | Détection / test |
|---|---|---|---|---|---|---|
| R-01 | **Cahier des charges absent** → plan non aligné | 3 | 3 | **9** | Q-01 ; aucune fonctionnalité codée avant validation ; matrice de traçabilité | Revue du plan vs PDF |
| R-02 | **Modification involontaire des originaux** (atime, xattrs, ouverture en écriture, téléchargement iCloud, création de `.DS_Store` par l'app) | 2 | 3 | **6** | D-006 ; `O_RDONLY`; pas d'API d'écriture exposée ; fichiers dataless non lus ; pas de vue Finder intégrée | Test d'invariant avant/après sur 100k fichiers (contenu, taille, mtime, mode, xattrs, liste) ; note : `atime` peut changer selon le montage, documenté et testé séparément |
| R-03 | **Exécution accidentelle** de contenu (DLL, script, aperçu) | 1 | 3 | 3 | Liste noire d'APIs en CI, pas de Quick Look, sandbox sans réseau | Test statique CI + revue |
| R-04 | **Perte de données en quarantaine** (crash, disque plein, volume éjecté au milieu) | 2 | 3 | **6** | `rename` atomique même volume, protocole 2 phases, manifeste + DB, réconciliation au démarrage, vérification SHA-256 | Tests d'injection de fautes à chaque étape ; 1 000 allers-retours |
| R-05 | **Faux positifs de doublons** conduisant à quarantaine d'un fichier unique | 1 | 3 | 3 | SHA-256 complet obligatoire, option octet par octet, seuls les exacts peuvent être mis en quarantaine en lot | Corpus de collisions taille/préfixe/suffixe |
| R-06 | **Confusion similarité / version / doublon** dans l'esprit de l'utilisateur | 2 | 2 | 4 | Vocabulaire D-008, preuves affichées, vues séparées | Tests UI, relecture des libellés |
| R-07 | **Performance insuffisante** à 100k (UI figée, mémoire) | 2 | 2 | 4 | Pagination, actor DB, lots transactionnels, NSTableView (D-004), signposts | Tests de perf nightly 50k/100k avec seuils |
| R-08 | **Similarité quadratique** (O(n²) paires) | 2 | 2 | 4 | MinHash + LSH (bandes), ne compare que les sources, recalcul exact limité aux candidats | Test perf 50k sources synthétiques |
| R-09 | **Encodages exotiques / fichiers corrompus** faisant planter l'analyse | 2 | 2 | 4 | Lexer tolérant, aucune `fatalError` sur données d'entrée, avertissements stockés | Fuzzing (entrées aléatoires, tronquées, binaires renommés `.mq4`) |
| R-10 | **Cas système de fichiers** : liens symboliques en boucle, alias Finder, paquets, noms NFD/NFC, sensibilité à la casse, chemins > 1024 octets, permissions refusées, volumes réseau lents/déconnectés | 2 | 2 | 4 | Pas de suivi de symlinks, (device, inode) visités, `rel_path_raw` en octets, erreurs comptées et non bloquantes | Corpus synthétique « pathologique » |
| R-11 | **Sandbox & bookmarks** : bookmark périmé après déplacement/renommage du dossier ou changement de volume | 2 | 2 | 4 | Statut `unreachable` + bouton « Relocaliser… » fonctionnel | Test d'intégration macOS |
| R-12 | **Risque légal** : décompilation EX4/EX5, redistribution de fichiers tiers dans les fixtures | 1 | 3 | 3 | D-007 ; fixtures synthétiques ou sous licence vérifiée (Q-07) | Revue des fixtures |
| R-13 | **Environnement de développement de l'agent** sans macOS/Swift : le code ne peut pas être compilé ni testé ici | 3 | 2 | **6** | CI GitHub Actions macOS comme référence ; cœur testable sous Linux si une toolchain Swift est installée ; aucun résultat déclaré « testé » sans exécution réelle en CI | Statut CI obligatoire sur chaque PR |
| R-14 | **Chaîne d'approvisionnement** (dépendances) | 1 | 2 | 2 | Peu de dépendances, versions exactes, `Package.resolved` commité, revue | Dependabot / revue |
| R-15 | **Croissance de la base** (historique, scans répétés) | 2 | 1 | 2 | Index ciblés, `VACUUM` manuel proposé, pas de duplication du contenu des fichiers en base | Test 10 scans successifs à 100k |
| R-16 | **Coût CI macOS** (minutes facturées ×10) et durée des tests 100k | 2 | 1 | 2 | 100k en nightly ; 50k + tests ciblés à chaque PR ; corpus généré à la volée et mis en cache | Suivi durée CI |
| R-17 | **Confusion avec `com.apple.quarantine`** (attribut Gatekeeper) | 1 | 1 | 1 | Ne jamais lire/écrire cet attribut pour notre logique ; terminologie « Quarantaine de la bibliothèque » | Revue |

---

## 4. Limites assumées (v1)

- macOS uniquement.
- Pas d'analyse du contenu des EX4/EX5/DLL ; uniquement métadonnées + empreinte.
- Pas de compilation ni d'exécution de MQL, pas d'intégration directe au terminal.
- L'analyse des sources est **lexicale** (déclarations, inclusions, imports), pas sémantique : pas de résolution complète du préprocesseur conditionnel (`#ifdef`) ni de typage.
- La similarité est **textuelle** : deux codes fonctionnellement équivalents mais réécrits ne seront pas détectés.
- L'ordre des versions n'est fiable que si `#property version` est présent ; sinon il est explicitement « supposé ».
- Quarantaine limitée au même volume que la bibliothèque.
- Archives non ouvertes (Q-14).
- Fichiers iCloud non téléchargés non analysés par défaut.
