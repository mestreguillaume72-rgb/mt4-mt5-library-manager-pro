# PLAN DE TESTS — MT4 MT5 Library Manager PRO

> Phase 0 — Statut : **APPROUVÉ le 2026-11-10** (voir [docs/VALIDATIONS.md](docs/VALIDATIONS.md)).
> Référence : `docs/specification/MT4-MT5-Library-Manager-PRO_dossier-developpeur_v3.0.pdf`.
> Principe (§ 7) : une fonctionnalité n'est acceptée que si ses tests existent, ont été **réellement exécutés**, et que la commande, l'environnement et les résultats sont consignés. Les tests doivent **échouer si une fonction n'est pas branchée**.

---

## 1. Outillage et environnements

| Niveau | Outil | Exécution |
|---|---|---|
| Unitaires | `pytest` | Linux (env. distant + CI) à chaque commit ; macOS en CI |
| Propriétés / fuzz | `hypothesis` (graine journalisée) | Chaque PR (court), nuit (long) |
| Intégration système de fichiers | Dossiers temporaires réels (`tmp_path`) | Linux + macOS |
| Interface | `pytest-qt`, Qt `QT_QPA_PLATFORM=offscreen` | Linux + macOS ; vérification visuelle finale sur Mac (phase 12) |
| Sécurité statique | Tests `ast` maison + `import-linter` + `ruff` | Chaque commit |
| Types | `mypy --strict` | Chaque commit |
| Charge | Scripts `tests/perf` + mesure RAM (`resource.getrusage`, `psutil` en test uniquement) | 50k : PR des phases 2, 3, 8, 11 ; 100k : manuel / nuit |
| Installation / bundle | Build PyInstaller + inspection du `.app` | CI macOS dès la phase 1, Mac réel en phase 12 |

**Déterminisme** : horloge, identifiants et graines injectés. Les tests n'accèdent **jamais** au dossier personnel réel ni à des données réelles : uniquement des dossiers temporaires créés puis supprimés par le test.

**Preuve d'exécution** : chaque phase produit `docs/rapports/phase-NN.md` contenant la commande exacte, l'environnement (OS, Python, PySide6, matériel), le résumé `pytest` (réussis/échoués/ignorés), la couverture, les liens vers les runs CI, et la liste de ce qui attend le Mac.

---

## 2. Jeu de données synthétique reproductible (livrable § 11)

`tests/synthetic/generate.py --seed N --files 50000 --out <tmp>` produit une arborescence et un **manifeste de vérité terrain** (JSON). Non empaqueté dans l'application.

| Contenu | Détail |
|---|---|
| Volumes | 1k (unitaire), 10k, **50k**, **100k** |
| Arborescences | `MQL4/` et `MQL5/` (`Experts, Indicators, Scripts, Include, Libraries, Presets, Files, Services, Images`), dossiers « vrac », profondeur 1–12 |
| Sources fictives | `.mq4/.mq5/.mqh` syntaxiquement plausibles avec `#property`, `input/extern/sinput`, `#include`, `#import`, fonctions d'entrée — **robots fictifs** |
| Binaires simulés | `.ex4/.ex5/.dll` = octets **aléatoires** (jamais de vrais binaires), certains appariés par nom à une source |
| SET fictifs | MT4 (`Nom=Val`, `Nom,F/1/2/3=`) et MT5 (`||` d'optimisation), dérivés des inputs des robots fictifs avec variations contrôlées ; SET orphelins ; SET ambigus (compatibles avec 2 robots) ; SET mal formés |
| Encodages | UTF-8, UTF-8 BOM, UTF-16 LE/BE BOM, CP1252, invalides |
| Doublons (vérité connue) | 5 % exacts (dont renommés) ; 2 % équivalents normalisés ; 3 % similaires (mutation 5–40 %) ; familles de versions (version dans le nom, dans `#property`, les deux, aucune) ; homonymes différents |
| Archives ZIP | Saines, imbriquées, corrompues, bombe simulée (ratio élevé, petite taille), traversal `../`, chemins absolus, entrées symlink, doublons d'entrées, chiffrées |
| Pièges | Même taille contenu différent ; même début/fin milieu différent ; fichiers vides, 1 octet, gros (≥ 1 Gio, creux, nuit) ; extension trompeuse (`.mq4` binaire, `.zip` texte) ; extensions inconnues |
| Pathologies FS | Noms accentués NFC/NFD, emoji, casse différente, chemins longs (> 255 octets cumulés), symlinks valides/cassés/cycliques, fichiers et dossiers sans permission de lecture |

---

## 3. Tests par phase et par exigence

Chaque cas listé par la spécification (critères de validation F1–F13) est repris **explicitement** ci-dessous.

### 3.1 Socle (Phase 1) — `store`, `audit`, `core`
- Création de base vide ; migration de chaque version N-1 → N (bases archivées en fixtures) ; sauvegarde avant migration restaurable.
- Atomicité : arrêt simulé au milieu d'un lot ⇒ aucune ligne partielle.
- Audit : `UPDATE`/`DELETE` sur `audit_event` refusés ; chaînage `prev_hash` vérifié ; altération manuelle détectée.
- Journaux rotatifs : rotation à la taille fixée ; pas de chemin de source écrit hors du dossier de logs.
- Installation reproductible : `uv sync --frozen` puis `pytest` sur machine vierge (CI).

### 3.2 F1 — Inventaire (Phase 2)
Cas imposés : **dossiers imbriqués, noms accentués, extensions inconnues, permissions refusées, liens symboliques cycliques, fichier inaccessible ; hashes avant/après identiques.**
- Compteurs exacts = manifeste (fichiers, dossiers, liens, erreurs).
- Symlink cyclique ⇒ pas de boucle, terminé en temps borné, lien enregistré.
- Permission refusée ⇒ entrée `scan_error`, scan continue.
- Re-scan incrémental : seuls les fichiers modifiés sont marqués ; fichiers supprimés ⇒ `missing`.
- Annulation à 10/50/99 % ⇒ état cohérent ; reprise ⇒ résultat final identique à un scan non interrompu.

### 3.3 F2 — Métadonnées et empreintes (Phase 3)
Cas imposés : **fichiers vides, gros fichiers, lecture interrompue, fichier modifié pendant le scan, reprise et cohérence du hash.**
- SHA-256 = vecteurs NIST et = `sha256sum`/`shasum -a 256` sur 1 000 fichiers.
- Mémoire constante : hash d'un fichier de 4 Gio (creux) avec RAM < 100 Mo supplémentaires.
- Modification pendant la lecture (thread qui ajoute des octets) ⇒ `error` « modifié pendant la lecture », jamais `validated`.
- Arrêt forcé (kill) pendant le hash ⇒ au redémarrage `in_progress` → `not_computed`, re-hash identique.
- `engine_version` enregistrée.

### 3.4 F3 — Formats et archives (Phase 4)
Cas imposés : **archive saine, corrompue, zip bomb simulée, noms traversants, doublons d'entrées, archive chiffrée ; échec propre et journalisé.**
- Détection par signature : extension trompeuse signalée.
- Bombe : arrêt dès dépassement du ratio/taille **réellement décompressés**, statut `skipped_limit`, RAM bornée.
- Traversal / absolu / symlink : entrée `rejected_*`, aucune écriture disque (vérifié par snapshot du dossier temporaire et du dossier de l'app).
- Imbrication au-delà de la profondeur max ⇒ `skipped_limit`.
- Chiffrée ⇒ `encrypted`, non inspectée. Corrompue ⇒ `corrupt`, scan continue.

### 3.5 F4 — Reconnaissance MetaTrader (Phase 5)
Cas imposés : **exemples fictifs MT4/MT5, fichiers renommés, extension trompeuse, binaire inconnu ; l'interface affiche les limites.**
- Classement conforme au manifeste (type, plateforme, certitude) ; matrice de confusion publiée dans le rapport.
- `.ex4/.ex5` : aucune lecture au-delà du hash (test : le lecteur est appelé uniquement par `hashing`/`formats` pour la signature) ; champ `limits` renseigné.
- `#import "x.dll"` détecté, jamais chargé.
- Fuzz : 10 000 entrées aléatoires/tronquées ⇒ aucun crash, aucun blocage > 2 s par fichier.

### 3.6 F5 — Analyse SET (Phase 6)
Cas imposés : **SET vide, mal formé, encodages, doublons de clés, paramètres inconnus, variantes MT4/MT5, SET presque identiques.**
- Valeur brute toujours conservée à l'identique (aller-retour brut = original).
- Normalisation : booléens, nombres (virgule/point, exposants), chaînes, couleurs, dates, bornes d'optimisation MT4 et MT5.
- Clés en double : toutes conservées + avertissement.
- SET presque identiques regroupés avec diff paramètre par paramètre.

### 3.7 F5 — Moteur d'association (Phase 6)
- Sur le corpus synthétique : chaque association proposée a des preuves ; précision des associations « forte » ≥ 0,95 (seuil à valider Q-08).
- **Ambiguïté** : SET compatible avec deux robots ⇒ deux candidats, niveau ≤ « moyenne », incertitude explicite.
- Robot sans source (EX uniquement) ⇒ niveau « à vérifier » au maximum.
- **Une association non prouvée reste « à vérifier »** ; aucune `accepted` sans action utilisateur (test).
- Orphelins détectés = manifeste.
- Changement de pondération ⇒ `engine_version` différente, anciens résultats marqués à recalculer.

### 3.8 F6 — Familles et versions (Phase 7)
Cas imposés : **même nom/contenu différent, version dans le nom, version dans les métadonnées, compilation différente, copie identique renommée.**
- Chaque cas produit la relation attendue (`homonym_different` ou `version_variant`, `version_variant` avec version estimée, `compiled_variant`, `renamed_copy`), avec raison et confiance.
- Les versions distinctes ne sont **jamais** fusionnées.

### 3.9 F7 — Doublons (Phase 8)
Cas imposés : **copie exacte, fichier presque identique, homonyme différent, même contenu renommé, collision théorique traitée par vérification supplémentaire.**
- Exacts : précision = rappel = 1,0 sur le manifeste ; 0 faux positif sur les pièges taille/début/fin.
- Presque identique ⇒ « similaire », jamais « exact » (test d'exclusion mutuelle).
- Collision simulée (hacheur injecté renvoyant la même empreinte pour deux contenus différents) ⇒ la vérification octet par octet les sépare.
- Fichier modifié entre détection et action ⇒ groupe invalidé.

### 3.10 F8 — Quarantaine et restauration (Phase 8)
Cas imposés : **dry-run, confirmation, disque plein, interruption, destination existante, hash différent, restauration, conflit de chemin ; tout échec préserve une copie vérifiée.**
- Dry-run : aucun octet écrit (snapshot) ; rapport complet.
- Sans confirmation, ou confirmation liée à une autre simulation ⇒ refus.
- Destination dans une source (ou l'inverse) ⇒ refus.
- Disque plein (système de fichiers de taille limitée en test / écriture injectée échouant) ⇒ arrêt, original intact.
- Interruption (kill) à chaque état `copying/copied/verified` ⇒ au redémarrage, état récupérable, **l'original est intact** et aucune copie partielle n'est marquée `verified`.
- Hash de copie différent (corruption injectée) ⇒ `failed`, source intacte.
- Destination existante ⇒ jamais écrasée.
- Aucune opération de déplacement/suppression n'existe : test statique + invariant « sources inchangées » exécuté **après** une quarantaine réelle.
- Source modifiée entre simulation et exécution ⇒ arrêt, confirmation invalidée.
- Restauration : hash identique ; conflit de chemin ⇒ arrêt + choix ; 1 000 allers-retours sans perte.
- Aucun bouton/commande de purge (test du registre d'actions).
- Chaque étape produit un `audit_event`.

### 3.11 F9 — Organisation (Phase 9)
Cas imposés : **collision de nom, reprise de copie, destination indisponible, espace insuffisant, hash non conforme.**
- Prévisualisation = résultat effectif de la copie (même arborescence).
- Collisions : suffixe déterministe + rapport.
- Reprise : éléments `verified` sautés, résultat final identique.
- Destination démontée/indisponible ⇒ arrêt propre. Espace insuffisant détecté **avant** copie.
- Hash destination ≠ source ⇒ élément en échec, rapport.
- Invariant lecture seule sur les sources après organisation.

### 3.12 F10 — Recherche, filtres, rapports (Phase 10, moteur dès 2)
Cas imposés : **pagination, caractères Unicode, filtres combinés, export complet, volumes élevés.**
- Pagination par clé à 100k : pas de doublon ni de trou entre pages, ordre stable.
- Recherche accentuée / NFD / casse.
- Exports CSV/JSON : ré-import et comparaison à la base (complétude) ; échappement (virgule, guillemet, saut de ligne, emoji).
- Export d'une base vide ⇒ fichier valide sans données inventées.

### 3.13 F11 — Interface (Phase 10)
Cas imposés : **parcours utilisateur, états vides, erreurs, annulation, accessibilité clavier, aucune action décorative.**
- **Registre d'actions** : test qui énumère toutes les actions ; échec si une action activée n'a pas de gestionnaire réel ou si son gestionnaire est un bouchon ; les actions désactivées portent « non disponible ».
- **Branchement réel** : chaque action déclenchée dans le test produit l'effet observable en base/fichiers (pas de mock du service dans ces tests).
- Parcours complet : ajouter source → scanner (pause, reprise, annulation) → explorer/filtrer → détail → SET (accepter/rejeter) → familles → doublons → simulation → confirmation → quarantaine → restauration → organisation → export → journal.
- États vides et messages d'erreur réels (source inaccessible, disque plein).
- Navigation clavier complète (tabulation, raccourcis), libellés accessibles.
- Latence : aucune action ne bloque la boucle Qt > 200 ms pendant un scan 50k.

### 3.14 F13 — Livraison macOS (Phase 12)
- Build `.app` + DMG en CI macOS (arm64, x86_64 ; Universal2 si possible : `lipo -info` sur les binaires).
- Inspection du bundle : générateur synthétique absent ; aucun binaire inattendu.
- `codesign --verify --deep --strict`, `spctl --assess` (si compte Apple, Q-03).
- **Sur le Mac du propriétaire** : installation depuis le DMG, lancement, scan d'un corpus synthétique, quarantaine + restauration, désinstallation ; procédure de sauvegarde/restauration de la base.
- Matrice `docs/COMPATIBILITE.md` : uniquement des lignes avec preuve.

---

## 4. Tests de charge (F12)

| Scénario | Corpus | Mesures consignées | Seuil (proposé, Q-07) |
|---|---|---|---|
| Inventaire initial | 50k / 100k | durée, fichiers/s, RAM max, erreurs | ≤ 60 s / ≤ 120 s ; RAM ≤ 600 / 800 Mo |
| Re-scan inchangé | 50k / 100k | durée | ≤ 20 s / ≤ 40 s |
| Hash complet | 50k / 100k | Mo/s vs débit disque mesuré | ≥ 60 % |
| Pipeline complet (scan → hash → analyses → doublons → associations) | 50k / 100k | durée par étape, RAM max | à établir à la phase 11 puis valider |
| Reprise après fermeture forcée | 50k | temps jusqu'à reprise effective | ≤ 10 s |
| Explorateur : filtre/tri | 100k | latence | ≤ 500 ms |

Exécution sur Linux (env. distant) **et** CI macOS ; rapport `docs/rapports/charge-*.md` avec matériel et commande. Régression > 15 % vs référence = échec signalé.

---

## 5. Invariant « sources inchangées » (critique)

1. Générer le corpus (50k à chaque PR des phases concernées, 100k en manuel/nuit).
2. **Instantané avant** : pour chaque entrée (sans suivre les liens) : chemin en octets, type, taille, SHA-256, `mtime_ns`, `ctime_ns`, mode, propriétaire, xattrs (macOS/Linux) ; liste de chaque dossier.
3. Exécuter tous les moteurs : scan, hash, archives, reconnaissance, SET, associations, familles, doublons, dry-run de quarantaine, quarantaine (copie), restauration, organisation, exports.
4. **Instantané après** : comparaison stricte, **zéro différence** exigée ; aucun fichier créé dans les sources.
5. `atime` : contrôlé et documenté séparément (peut dépendre des options de montage ; l'app n'utilise pas d'API qui le modifie explicitement).
6. Aucune exception : la quarantaine étant une copie (décision du propriétaire), l'application n'a **aucune** opération autorisée à modifier les sources.

---

## 6. Tests de sécurité

- Archives hostiles (§ 3.4), fichiers MQL/SET piégés (fuzz), noms de fichiers malicieux (`../`, caractères de contrôle, très longs).
- Destination de quarantaine/organisation dans une source ⇒ refus (y compris via symlink ou chemin relatif).
- Aucun accès réseau : test qui bloque les sockets pendant toute la suite (`pytest-socket` ou garde maison) ⇒ aucun appel.
- Données réelles dans Git : test CI refusant `.ex4/.ex5/.dll/.set/.mq4/.mq5` versionnés (hors gabarits explicitement fictifs).

## 7. Tests statiques d'architecture

- `import-linter` : `ui` → `app` uniquement ; moteur sans Qt ; seul `transfer` importe des fonctions d'écriture.
- Analyse `ast` : interdits dans `src/mtlm` — `subprocess`, `ctypes`, `os.system`, `os.exec*`, `os.spawn*`, `os.startfile`, `webbrowser`, `runpy`, `pickle`, `importlib` dynamique, `socket`, `urllib`, `http` ; dans les modules d'analyse — `open(..., 'w'/'a'/'x'/'+')`, `os.remove`, `os.rename`, `shutil.*`, `os.chmod`, `os.utime`, `setxattr`.
- `mypy --strict`, `ruff`.

## 8. Logs et audit testés

- Chaque tâche émet début / fin (durée, compteurs) / échec (erreur typée) — vérifié par un gestionnaire de logs de test.
- Chaque opération de quarantaine, restauration, copie organisée, validation d'association, export ⇒ `audit_event` attendu (nombre et contenu).

## 9. Définition de « terminé » d'une phase (§ 7, § 12)

1. Comportement, technique, entrées, sorties, erreurs, logs et critères d'acceptation documentés.
2. Tests unitaires, intégration (et UI si pertinent) écrits **et exécutés** ; résultats réels dans `docs/rapports/phase-NN.md`.
3. Invariant « sources inchangées » vert (Linux + macOS pour les phases 2, 3, 8, 9, 11).
4. Couverture ≥ 85 % sur le moteur modifié ; 100 % des branches de `transfer`.
5. Aucune action non branchée, aucune donnée fictive affichée comme réelle.
6. Liste de ce qui attend le Mac.
7. **Accord du propriétaire** avant la phase suivante.

## 10. CI

| Workflow | Déclencheur | Contenu |
|---|---|---|
| `ci.yml` (Linux) | push / PR | ruff, mypy, pytest (unit, intégration, UI offscreen, sécurité), invariant 10k, couverture |
| `macos.yml` | PR (phases sensibles) + manuel | pytest sur `macos-15` (arm64) et `macos-15-intel` (Intel), invariant 50k, build `.app` |
| `perf.yml` | manuel / planifié | charge 50k/100k, rapport en artefact |
