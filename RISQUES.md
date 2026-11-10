# RISQUES — questions bloquantes, hypothèses, risques et limites

> Phase 0 — Statut : **PROPOSITION, en attente de validation.**
> Référence : `docs/specification/MT4-MT5-Library-Manager-PRO_dossier-developpeur_v3.0.pdf`.
> Échelles : Probabilité (P) et Impact (I) de 1 à 3 ; Criticité = P × I.

---

## 1. Questions au propriétaire

### 1.1 Bloquantes pour démarrer la Phase 1

| ID | Question | Pourquoi | Proposition par défaut |
|---|---|---|---|
| **Q-01** | **Choix de la technologie** : Python/PySide6 (recommandé) ou Swift/SwiftUI ? | La spécification (Annexe) vous laisse ce choix après présentation des avantages/inconvénients (DECISIONS D-001). | Python/PySide6 |
| **Q-04** | Quarantaine : **copie seule** (originaux jamais touchés) ou aussi **déplacement** (l'original est retiré des sources après copie vérifiée, sur confirmation) ? | Le déplacement serait la seule écriture dans vos sources ; la spécification autorise « déplacer ou copier ». | Copie seule en premier ; déplacement plus tard si vous le demandez |
| **Q-05** | Approuvez-vous ce plan de Phase 0 (architecture, tests, risques) ? | Porte de validation obligatoire (§ 8). | — |

### 1.2 Nécessaires plus tard (non bloquantes maintenant)

| ID | Question | Pour quelle phase | Proposition |
|---|---|---|---|
| Q-02 | Modèle de Mac, puce (Intel/Apple Silicon) et version de macOS | 12 (et version min. D-002) | macOS 12+ testé en CI, Mac réel en phase 12 |
| Q-03 | Compte Apple Developer (99 $/an) pour signer/notariser ? | 12 | Sinon : usage local, ouverture par clic droit, documenté |
| Q-06 | Exemples **fictifs** de SET et sources MQ4/MQ5 (Annexe) | 5–6 | Le générateur synthétique suffit pour démarrer |
| Q-07 | Validation des budgets de performance (ARCHITECTURE § 9) | 11 | Valeurs proposées |
| Q-08 | Validation des poids/seuils du moteur d'association | 6 | Valeurs ARCHITECTURE § 8.6, calibrées sur données fictives |
| Q-09 | Limites d'archives (profondeur 2, 10 000 entrées, 2 Gio, ratio 100:1) | 4 | Valeurs proposées, configurables |
| Q-10 | Seuil de similarité par défaut | 8 | 0,80 |
| Q-11 | Langue : français seul, ou anglais aussi ? | 10 | Français seul (§ 11) |
| Q-12 | La spécification évoque « deux documents » (cahier des charges V2 + guide) ; le PDF V3.0 les consolide. Y a-t-il un autre document ? | — | Le PDF V3.0 fait foi |
| Q-13 | Une **sauvegarde indépendante** de vos originaux existe-t-elle (Annexe) ? | Avant toute quarantaine | Fortement recommandée avant la phase 8 |

---

## 2. Hypothèses

| ID | Hypothèse | Si fausse… |
|---|---|---|
| H-01 | Distribution hors Mac App Store (pas de sandbox Apple obligatoire). | Avec App Store : sandbox + bookmarks ; Swift redevient plus favorable (D-001). |
| H-02 | Les sources sont des dossiers sur disque local ou externe ; aucun accès à un terminal MetaTrader en marche. | Module d'intégration supplémentaire, hors périmètre. |
| H-03 | Format SET MT4 : `Nom=Valeur` et lignes `Nom,F/1/2/3=` ; MT5 : `Nom=Valeur||début||pas||fin||Y/N`. Encodages : UTF-16 LE BOM (MT5), CP1252/UTF-8 (MT4). | Le parser est tolérant ; à confirmer sur exemples fictifs (Q-06). |
| H-04 | Les sources MQ4/MQ5 déclarent leurs paramètres via `input`/`extern`/`sinput`. | Les associations seront plus faibles (score plafonné). |
| H-05 | Collection initiale ≈ 6 000 robots ; plusieurs dizaines de milliers de fichiers au total ; fichiers majoritairement < 10 Mo. | Budgets revus si gros historiques (`.hst`, `.hcc`). |
| H-06 | Un seul utilisateur, une seule base locale. | Partage multi-postes hors v1. |
| H-07 | GitHub Actions est disponible sur le dépôt privé avec des minutes macOS suffisantes. | Tests macOS réduits ; plus de vérifications reportées à la phase 12 (R-12). |

---

## 3. Registre des risques

| ID | Risque | P | I | Crit. | Mitigation | Détection |
|---|---|---|---|---|---|---|
| R-01 | **Modification involontaire d'un original** (écriture, renommage, `.DS_Store`, xattr, téléchargement iCloud, ouverture par le Finder) | 2 | 3 | **6** | Modules d'analyse sans écriture ; seul `transfer` écrit, uniquement hors sources ; fichiers dataless non lus ; aucun lancement de Finder/Quick Look | Invariant avant/après 50k/100k Linux + macOS ; test statique |
| R-02 | **Perte de données en quarantaine** (crash, disque plein, éjection, hash différent) | 2 | 3 | **6** | Copie → `fsync` → hash → renommage atomique ; mode `copy` par défaut ; `move` seulement après `verified` ; sauvegarde de la base ; arrêt au moindre doute | Injection de fautes à chaque état ; 1 000 allers-retours |
| R-03 | **Exécution de contenu** (DLL, EA, script, archive) | 1 | 3 | 3 | Aucune API d'exécution ; ZIP lu en flux sans extraction ; pas de RAR/7z natif | Test statique code + bundle |
| R-04 | **Archive hostile** (bombe, traversal, symlink, millions d'entrées) | 2 | 2 | 4 | Limites comptées sur octets réellement décompressés ; rejets journalisés ; aucune écriture disque | Corpus d'archives hostiles |
| R-05 | **Faux doublon** menant à mettre en quarantaine un fichier unique | 1 | 3 | 3 | Taille + SHA-256 validés + stabilité + option octet par octet ; référence toujours conservée | Corpus de pièges |
| R-06 | **Associations SET trompeuses** présentées comme sûres | 2 | 3 | **6** | Score explicable, preuves pour/contre, plafond « à vérifier » sans source, aucune validation automatique | Tests d'ambiguïté (§ F5) |
| R-07 | **Confusion** exact / similaire / version / homonyme | 2 | 2 | 4 | Quatre classes séparées (D-008), libellés clairs, onglets distincts | Tests + revue de l'interface |
| R-08 | **Performance / mémoire** insuffisantes à 100k (Python) | 2 | 2 | 4 | Flux, lots, pagination par clé, threads pour le hash, budgets mesurés en CI ; profilage | Tests de charge, RAM max |
| R-09 | **Interface figée** pendant les tâches | 2 | 2 | 4 | Aucune E/S sur le thread d'interface ; progression limitée à 10/s | Test de latence de la boucle Qt |
| R-10 | **Cas du système de fichiers** : Unicode NFD/NFC, insensibilité à la casse (APFS), chemins longs, symlinks cycliques, permissions, volumes réseau, fichiers modifiés pendant le scan | 2 | 2 | 4 | Chemins en octets, pas de suivi de symlinks, (device, inode), stabilité, erreurs non bloquantes | Corpus pathologique, tests **sur macOS** en CI |
| R-11 | **Différences Linux / macOS** non détectées (développement sur Linux) | 2 | 2 | 4 | CI macOS sur chaque PR des phases sensibles (2, 3, 8, 9) ; tests spécifiques macOS (dataless, NFD, casse) | Run CI macOS obligatoire |
| R-12 | **Coût / quota des minutes macOS** GitHub (×10 en dépôt privé) | 2 | 1 | 2 | Linux pour l'essentiel ; macOS ciblé ; 100k en exécution manuelle | Suivi de consommation |
| R-13 | **Empaquetage macOS** Python/PySide6 (taille, Universal2, signature de nombreux binaires, notarisation) | 2 | 2 | 4 | Build `.app` en CI macOS dès la phase 1 (« walking skeleton ») pour détecter tôt | Run CI de build |
| R-14 | **Compatibilité annoncée sans preuve** | 1 | 3 | 3 | Matrice avec lien de preuve obligatoire ; rien hors matrice | Revue phase 12 |
| R-15 | **Fausse déclaration** de tests exécutés ou de connexion GitHub | 1 | 3 | 3 | Rapports de phase avec commandes et sorties réelles ; liens vers runs CI | Revue par le propriétaire |
| R-16 | **Données réelles poussées dans Git** (robots, SET, DLL) | 1 | 3 | 3 | `.gitignore`, test refusant ces extensions hors corpus généré, rappel au propriétaire | Hook / test CI |
| R-17 | **Propriétaire débutant** : mauvaise manipulation, incompréhension d'une commande | 2 | 2 | 4 | Une action à la fois, explications sans jargon, aucune commande touchant les originaux sans explication préalable (§ 10) | Retour du propriétaire |
| R-18 | **Encodages exotiques / fichiers corrompus** faisant planter un analyseur | 2 | 1 | 2 | Analyseurs gardés (exception, délai, taille max), avertissements | Fuzz |
| R-19 | **Décisions d'algorithmes changeantes** rendant les résultats incohérents | 1 | 2 | 2 | `engine_version` sur chaque résultat, recalcul explicite | Tests de migration |
| R-20 | **Dépendances tierces** (PySide6, PyInstaller) : vulnérabilité, rupture | 1 | 2 | 2 | Peu de dépendances, versions épinglées, verrou, revue des mises à jour | Audit des dépendances |

---

## 4. Limites assumées (à afficher dans l'application et la documentation)

- **EX4/EX5** : binaires compilés opaques. Ni décompilation, ni extraction de paramètres, ni « informations cachées ». Type déduit seulement du dossier ou d'une source appariée.
- **Associations SET ↔ robot sans source** : ne peuvent pas dépasser « à vérifier ».
- **Analyse MQL lexicale**, pas sémantique : pas de résolution complète du préprocesseur conditionnel.
- **Similarité textuelle** : deux codes équivalents mais réécrits ne seront pas détectés.
- **Versions** : ordre fiable seulement si déclaré (`#property version` ou nom) ; sinon « supposé ».
- **Archives** : ZIP inspecté ; RAR/7z et autres identifiés mais non ouverts ; archives chiffrées non inspectées ; contenu d'archive jamais mis en quarantaine.
- **Fichiers iCloud non téléchargés** : non lus (signalés).
- **Compatibilité macOS** : uniquement ce qui figure dans la matrice avec preuve.
- **Développement sans Mac jusqu'à la phase 12** : l'apparence finale et l'installation ne sont garanties qu'après tests sur le Mac du propriétaire.
