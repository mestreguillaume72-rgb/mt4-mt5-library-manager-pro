# Changelog

## [1.8.0] — Version Windows

### Ajouté
- **Windows 10 et 11 (64 bits)** : installateur `…-Windows-Setup.exe` (sans droits
  administrateur), raccourcis Menu Démarrer et Bureau, guide PDF. Testé à chaque version sur
  un vrai Windows (tous les tests, application construite, installation silencieuse puis
  auto-diagnostic de l'application installée).
  - Lecture en mode binaire, identité réelle des fichiers (numéros NTFS/ReFS jusqu'à 128 bits),
    jonctions jamais suivies, fichiers OneDrive non téléchargés jamais lus.
  - **Corbeille de Windows** avec « Remettre en place » ; disques réseau refusés (pas de
    Corbeille, le fichier serait perdu).
  - Archives RAR / 7z / TAR… lues avec la bibliothèque fournie par Windows.
  - Données dans `%APPDATA%\MT4MT5LibraryManagerPro`.
- **« Ajouter les dossiers MetaTrader trouvés… »** (Mes dossiers) : MQL4 / MQL5 de Windows
  (`AppData\Roaming\MetaQuotes\Terminal…`, Program Files) et de MetaTrader pour Mac.
- **Erreurs d'empreinte** visibles : « Voir les erreurs de la tâche choisie » les regroupe
  par cause avec un exemple ; si macOS refuse la lecture, l'application explique comment
  donner l'« Accès complet au disque ».

### Modifié
- Noms créés (dossiers proposés, quarantaine, décompression) valables sous Windows
  (caractères interdits, noms réservés).
- Textes « Corbeille » communs au Mac et à Windows.

## [1.7.0] — Supprimer où je veux, analyse à zéro, progression, SET en vrac

### Corrigé
- **« check constraint failed: member_count >= 2 »** à l'étape « Doublons et similarités » :
  une copie rangée dans un dossier devenu indisponible ne crée plus de groupe d'un seul
  fichier. Les doublons et les similarités sont de nouveau calculés.
- **Décompression des archives** : deux noms qui ne diffèrent que par les majuscules
  (« Lot.set » / « lot.set ») bloquaient tout sur le disque du Mac ; même contenu = écrit une
  fois, contenu différent = « (2) ». Une archive pas encore lue en entier peut être
  décompressée et mise à la Corbeille ; les motifs de refus sont affichés.

### Ajouté
- **Supprimer où je veux** : bouton « Mettre à la Corbeille » dans l'Explorateur, les SET,
  les sources MQ4/MQ5, les robots isolés et les indicateurs isolés (en plus de Doublons,
  Familles, Quarantaine, Archives, Fichiers à risque). Dans **Doublons**, les fichiers choisis
  partent tels quels, **références comprises** (une autre copie devient la référence).
  Un fichier qui serait le **seul exemplaire** de son contenu est signalé et **vous
  décidez** (deuxième confirmation). Un fichier pas encore lu en entier est vérifié au moment
  de partir. Toujours récupérable avec « Remettre en place ».
- **Recommencer l'analyse à zéro** (écran Analyse) : efface les résultats d'analyse, jamais
  les fichiers ; dossiers ajoutés, quarantaine et Corbeille conservés.
- **Progression de chaque étape** : « Étape 3/8 — Archives : 120/450 lue(s) (26 %, reste
  environ 12 min) », aussi pour les formats et la reconnaissance.
- **Nombre d'éléments sous chaque liste** et nombre sélectionné : « 1 234 fichiers — 3
  sélectionnés ».
- **Archives protégées par mot de passe** : filtre « Protégées par mot de passe », ZIP
  partiellement protégés signalés, nombre affiché sur l'Accueil.
- **SET en vrac** : un robot qui n'existe qu'en EX4/EX5 apprend ses noms de paramètres des
  SET rangés avec lui ; les SET en vrac qui ont les mêmes paramètres lui sont proposés
  (« probable », à valider). Pour un SET sans robot, l'écran explique **pourquoi**.

## [1.6.0] — Analyse d'un disque entier plus rapide, rangement Robots / Indicateurs

### Modifié
- **Dossier entier, sans doublon** (Robots isolés, Indicateurs isolés, Sources MQ4/MQ5) :
  un robot ou indicateur est copié avec **son dossier entier** (sous-dossiers, SET, notices,
  images), même s'il n'y a que l'EX4/EX5. Le dossier du robot est trouvé au-dessus des
  dossiers standard (`Gold Pack/MQL4/Experts/Gold.ex4` → dossier `Gold Pack`). Une copie
  identique n'est **jamais recopiée** ; un dossier qui n'apporte rien de nouveau est laissé
  de côté.
- **Empreintes ciblées** (réglage « Lire en entier tous les fichiers du disque », 0 par
  défaut) : seuls les fichiers MetaTrader (.mq4, .mq5, .mqh, .ex4, .ex5, .set, .tpl, .chr,
  .dll, .ini…), les archives, et les fichiers rangés dans un dossier de robot (ou jusqu'à
  2 niveaux en dessous) sont lus en entier. Les autres fichiers du disque (vidéos, photos,
  images disque…) sont seulement listés : l'analyse d'un disque entier est bien plus rapide.
  Les empreintes déjà calculées sont conservées.
- **Progression des empreintes** : Go lus / Go à lire, vitesse et **temps restant estimé**.
- **Accueil** : nombre de fichiers lus dans les archives (dont robots, indicateurs et SET).

### Ajouté
- **L'application dit ce qu'est chaque source**, même rangée n'importe où : robot,
  indicateur, script… reconnu en lisant le code (OnTick, OnCalculate, `#property
  indicator_…`, et pour les vieux MQ4 avec `start()` : passage d'ordres = robot, tampons
  `SetIndexBuffer` = indicateur). « Peut-être mal rangé » si le dossier dit le contraire.
- Écran **Sources MQ4/MQ5** : cases **« Robots MQ4 / MQ5 »**, **« Indicateurs MQ4 / MQ5 »**
  et « Autres », colonnes « C'est un… » et « Reconnu par », compteur robots / indicateurs.
- **Archives** : les sources MQ4/MQ5 contenues sont lues en mémoire (rien n'est extrait) et
  reconnues ; les compilés prennent le type de leur source ou de leur dossier. Colonne
  « Contient » (« 2 robots, 3 indicateurs ») et type de chaque fichier contenu.
- Deux écrans à part, **sans mélange avec « Sources MQ4/MQ5 »** : **Robots isolés** et
  **Indicateurs isolés**. Chaque robot ou indicateur (MQ4, MQ5, EX4, EX5) vient avec tout ce
  qui va avec (versions, compilés, SET, indicateurs utilisés, DLL, modèles, images).
  - **Groupes de dossiers** : « Mettre dans un groupe… » réunit les outils cliqués dans un
    groupe nommé (par exemple « Or », « Scalpers ») qui devient un dossier.
  - Rangement au choix : **un dossier par outil** ou **un seul grand dossier** (tous les
    fichiers ensemble).
  - Nouveau dossier « Robots isolés <date> » ou « Indicateurs isolés <date> » ; aperçu, puis
    copie vérifiée après validation.

## [1.5.0] — Archives, SET en vrac, isolement fidèle, fichiers à risque

### Ajouté
- **Toutes les archives** : RAR, 7z, GZ, BZ2, XZ, TAR (en plus des ZIP) lues sans extraction
  grâce à la bibliothèque de macOS (libarchive) ; chaque fichier contenu a son empreinte.
- Écran **Archives** : « Déjà décompressée : tout est sur le disque » ou « Contient N
  fichier(s) absent(s) du disque », contenu détaillé (type, présent sur le disque où ?),
  décompression des archives choisies, Corbeille des archives déjà décompressées.
- Case **« Décompresser les archives (ZIP, RAR, 7z…) et mettre l'archive à la Corbeille »**
  (écran Analyse, avec confirmation) : extraction vérifiée dans un dossier à côté de
  l'archive, Corbeille seulement si tout est vérifié ; les fichiers extraits sont analysés.
- Écran **Fichiers à risque** : signes repérés en lisant seulement (DLL, téléchargement,
  lancement de programme, effacement, clavier, programmes et scripts, fichiers déguisés,
  archives protégées). Analyse locale, rien envoyé sur Internet — ce n'est pas un antivirus.

### Modifié
- **SET** : l'écran s'ouvre sur les SET **à traiter** (en vrac, peut-être mal rangés, dans
  Presets, sans robot) ; ceux déjà rangés avec leur robot sont considérés comme réglés.
  Certitude en mots : certain / très probable / probable / possible. Accueil : « SET en vrac
  à relier ».
- **Isolement MQ4/MQ5** : un robot qui a son propre dossier est copié avec le **dossier
  complet, tel quel** ; un fichier seul est copié seul. Les fichiers qui peuvent aller avec
  (SET, images, DLL, indicateurs utilisés…) sont **proposés à cocher** : seuls ceux validés
  par l'utilisateur sont ajoutés.

## [1.4.1] — Écran « Sources MQ4/MQ5 », sélection au simple clic

### Ajouté
- Nouvel écran **Sources MQ4/MQ5** (menu Actions) : toutes les sources avec leur type,
  plateforme, SET liés, fichiers liés et dépendances ; filtres ; « Isoler les sources
  choisies… » (une, deux, trois ou plus) ou « Isoler toutes les sources… ». L'isolement quitte
  l'écran « Bibliothèque rangée ».

### Modifié
- Sélection multiple **au simple clic** (un clic ajoute la ligne, un second la retire, sans
  clavier) avec un compteur « N sélectionné(s) » ; « Tout sélectionner » reste disponible.

## [1.4.0] — Tout ce qui va avec un outil, indicateurs, sélection multiple

### Ajouté
- **Indicateurs** : les modèles de graphique `.tpl` sont lus (texte, MT4 et MT5) et reliés de
  façon certaine aux robots et indicateurs qu'ils chargent ; les appels `iCustom(…)` relient un
  robot aux indicateurs qu'il utilise ; filtre Robots / Indicateurs / Scripts dans « Familles
  et versions », colonne Type.
- **DLL et bibliothèques** : `#import "x.dll"` relie la DLL à son robot (elle est seulement
  copiée, jamais chargée ni exécutée) ; `#import "x.ex4"` et `#resource "…ex4"` relient les
  bibliothèques et indicateurs intégrés.
- **Tout ensemble** : le dossier de famille réunit aussi les indicateurs utilisés
  (« Indicateurs utilisés »), bibliothèques et DLL (« Bibliothèques »), modèles (« Modèles »),
  images, sons et documents ; l'isolement MQ4/MQ5 place les indicateurs utilisés avec le robot.
  Plusieurs familles d'un coup : « Familles réunies <date> », un sous-dossier par robot.
- Onglet **Dépendances** (qui utilise quoi) dans « Familles et versions ».
- **Avertissement** avant de mettre à la Corbeille un fichier dont un autre outil a besoin
  (indicateur appelé, DLL, bibliothèque, include), avec le nom de l'outil concerné.
- Placement **« Rangé dans le dossier MetaTrader prévu »** (Libraries, Include, Images,
  Sounds, Files, Templates, Presets) : ces fichiers ne sont plus comptés « en vrac ».
- **Sélection multiple** (Cmd+clic, Maj+clic, Cmd+A) et boutons « Tout sélectionner » /
  « Tout désélectionner » : Corbeille de plusieurs groupes ou fichiers, accepter/rejeter
  plusieurs associations, « Accepter la meilleure proposition des SET choisis », lots de
  quarantaine et remise en place groupées — une seule confirmation à chaque fois.

## [1.3.0] — Corbeille, placement des SET, familles réunies, dossiers proposés

### Ajouté
- **Placement des SET** (écran Robots et SET : colonne et filtre ; résumé sur l'Accueil) :
  « Rangé avec son robot », « En vrac — correspondance trouvée », « Rangé avec un autre robot ».
  Information seulement : tous les SET sont analysés de la même façon.
- **Suppression validée → Corbeille du Mac** : depuis la Quarantaine (« 4. Valider »), les
  Doublons (copies en trop d'un groupe, ou un fichier) et les Familles (un fichier). Copie
  identique conservée vérifiée octet par octet juste avant ; exemplaire unique signalé ;
  historique et « Remettre en place » (onglet Corbeille). Décision D-016.
- **Familles** : un même robot (contenu identique) enregistré sous d'autres noms rejoint sa
  famille.
- **Propositions à valider** (Familles et versions) : dossier de toute une famille au nom du
  robot ; isoler toutes les sources MQ4/MQ5 avec leurs SET associés. Aperçu, puis copie
  vérifiée seulement après validation.

- **Indices « faits pour aller ensemble »** pour relier les SET : nom du robot écrit par
  MetaTrader dans l'en-tête du SET ; petit lot de fichiers datés du même instant (« créés
  ensemble »). Preuves affichées en français.
- **Fichiers liés** (images, sons, documents, modèles, includes) reliés à leur outil : cités
  dans le code (`#resource`, « logo.bmp »…) = certain ; même dossier et nom proche ou créés
  ensemble = probable ; seul outil du dossier = possible. Placement : rangé avec son outil /
  en vrac / rangé avec un autre outil. Onglet dans « Familles et versions », résumé sur
  l'Accueil ; ils suivent leur robot dans les dossiers proposés (Images, Sons, Documents…).
- **Bulles d'aide en français** sur chaque bouton, chaque écran du menu et les listes
  (test : aucun bouton sans bulle).

### Modifié
- « Isoler les MQ4/MQ5 » est séparé du dossier de famille : il se trouve dans « Bibliothèque
  rangée », avec sa propre explication.
- Textes de sécurité : l'analyse ne modifie jamais rien ; seuls les fichiers que vous choisissez
  de supprimer partent dans la Corbeille du Mac, après confirmation.
- Écran Quarantaine en deux onglets : « Lots de quarantaine » et « Corbeille ».
- CI : l'installation « environnement vierge » utilise le Python du projet (le Python système
  d'Ubuntu, plus récent, n'est pas pris en charge par Qt 6.9).

## [1.2.2] — Application universelle (Intel + Apple Silicon)

### Corrigé
- Sur l'iMac Intel du propriétaire (macOS 12.7.6), l'application ouverte affichait « n'est pas
  prise en charge sur ce Mac » : c'était l'application Apple Silicon (le dossier contenait deux
  DMG, le premier de la liste étant celui des puces M). Le DMG Intel 1.2.1 a été vérifié :
  90 binaires, tous x86_64 et compatibles macOS 12.0.
- Désormais **une seule application universelle** (Intel + Apple Silicon), construite avec le
  Python officiel python.org universel, puis testée sur de vrais Mac des deux architectures :
  plus rien à choisir.
- `tools/verifier_minos.sh` exige aussi les deux architectures dans chaque binaire.
- Installateur : vérifie avant toute copie que l'application contient le code du processeur de
  ce Mac (6ᵉ scénario testé en CI) ; guide mis à jour (clic droit → Ouvrir, une seule image).

## [1.2.1] — Compatibilité macOS 12 Monterey (Mac Intel 2015-2016)

### Corrigé
- L'application 1.2.0 ne s'ouvrait pas sur macOS 12 : PySide6 6.12 exige macOS 14 alors que
  l'application déclarait 12.0. PySide6 est désormais limité à la branche 6.9 (macOS 12).
- Nouvelle preuve en CI : `tools/verifier_minos.sh` lit la version minimale réelle de chaque
  binaire de l'application et fait échouer la construction si l'un d'eux exige plus que macOS 12.
- Installateur : refus clair, avant toute copie, si le Mac est trop ancien (scénario testé en
  CI) ; lecture des réglages avec PlistBuddy (disponible sur toutes les versions de macOS).

## [1.2.0] — Direction artistique « Sombre Pro »

### Ajouté
- Dossier d'installation prêt à l'emploi (`…-Installation-macOS.zip`) : `Installer.command`
  (choix automatique Apple Silicon / Intel, vérification SHA-256, installation dans
  Applications, autorisation de l'application, lancement), guide PDF illustré et les deux DMG.
  Installateur testé en CI sur Mac (installation, mise à jour, élément étranger, fichier abîmé).

### Modifié
- Thème sombre haut de gamme : fond `#0B0F19`, cartes surélevées `#131C31` à bordures fines,
  titres blancs, textes secondaires gris doux, marges plus aérées, police système moderne.
- Cartes de résultats de l'accueil interactives (clic = écran concerné) avec halo et liseré
  colorés selon les données réelles : vert « Tout est en ordre », ambre « Action recommandée »
  (doublons, associations à vérifier, copies en trop), bleu pour l'information.
- Tableaux modernisés : en-têtes en petites capitales, lignes alternées très discrètes, sans
  quadrillage, et badges d'état colorés (terminée, erreur, à vérifier, référence…).
- Boutons principaux en dégradé bleu → indigo avec survol lumineux ; boutons de danger
  en contour rouge.

## [1.1.0] — Interface simple et soignée

### Ajouté / modifié
- Nouveau design : barre latérale sombre organisée en sections avec icônes, cartes, couleurs,
  boutons principaux mis en valeur, tableaux aérés ; mode sombre de macOS suivi
  automatiquement ; icône d'application (Finder, Dock).
- Accueil guidé en 3 étapes (choisir la bibliothèque, analyser, voir les résultats) avec la
  progression affichée sur l'accueil, pause/annulation, résumé en phrases simples et cartes
  de résultats cliquables.
- Écrans renommés en langage simple (« Mes dossiers », « Robots et SET », « Bibliothèque
  rangée »…), sous-titre explicatif sur chaque écran, étapes numérotées pour la quarantaine
  et le rangement, explorateur avec nom, type, plateforme et dossier en clair.

## [1.0.0] — Phases 11 et 12 : performance et livraison macOS

### Ajouté
- Application macOS `.app` + DMG (Apple Silicon et Intel) construits et testés sur de vrais Mac.
- Auto-diagnostic `--autotest`, mesure de performance `tools/mesure_performance.py`.
- Guide d'installation, matrice de compatibilité, rapports des phases 11 et 12.

## [0.10.0] — Phase 10 : interface graphique

### Ajouté
- Application PySide6 (`mtlm-gui`) : 13 écrans reliés aux services réels.
- Registre d'actions, tâches de fond avec pause/reprise/annulation, dialogues natifs.
- Tests d'interface sans écran ; captures d'écran réelles sur corpus fictif.

## [0.9.0] — Phases 8 et 9 : doublons, quarantaine par copie, bibliothèque organisée

### Ajouté
- Module `transfer` (seul écrivain) : copie vérifiée sans écrasement, contrôles de destination.
- Doublons exacts avec référence choisie, vérification octet par octet ; similarités séparées.
- Quarantaine : simulation, confirmation par jeton, copie vérifiée, manifeste, reprise, restauration.
- Bibliothèque organisée : prévisualisation, collisions rapportées, copie vérifiée, reprise.
- Exports CSV/JSON, paramètres persistants, pipeline `analyser`. Migration 0005.

## [0.7.0] — Phase 7 : familles et versions

### Ajouté
- Identité logique, séparation des homonymes, relations et versions estimées avec leur base.
- CLI : regrouper, familles, famille.

## [0.6.0] — Phase 6 : SET et associations

### Ajouté
- Lecteur SET MT4/MT5 (valeurs brutes + normalisées, optimisation, avertissements).
- Moteur d'association explicable (preuves pour/contre/incertitude, règles dures, ambiguïté).
- Décisions utilisateur conservées et journalisées. Migration 0004.
- CLI : sets, set, comparer-sets, associer, associations, association, valider, orphelins.

## [0.5.0] — Phase 5 : reconnaissance MetaTrader

### Ajouté
- Détection d'encodage, analyse lexicale MQL (propriétés, paramètres, inclusions, imports).
- Classement type/plateforme/certitude avec preuves et limites ; EX4/EX5 opaques.
- CLI : `reconnaitre`, filtres `--type`/`--plateforme`, détail enrichi.

## [0.4.0] — Phase 4 : formats et archives

### Ajouté
- Signatures binaires, extensions trompeuses.
- Inspection ZIP sans extraction, limites anti-archives piégées, refus des noms dangereux.
- Migration 0003 (`archive_scan`, suivi des analyses). CLI : `formats`, `archive ID`.

## [0.3.0] — Phase 3 : empreintes SHA-256

### Ajouté
- Lecture seule en flux, SHA-256 avec protocole de stabilité, états d'empreinte, reprise.
- Service d'empreintes parallèle, pause/annulation sans empreinte partielle.
- CLI : `empreintes`, `fichier ID`.

## [0.2.0] — Phase 2 : scanner en lecture seule

### Ajouté
- Énumération lecture seule (octets, liens non suivis, cycles évités, erreurs non bloquantes).
- Gestion des sources (ajout avec contrôles, retrait sans suppression).
- Inventaire incrémental avec pause, reprise, annulation ; tâches interrompues détectées.
- Consultation : statistiques, pagination, filtres, recherche plein texte.
- Migration 0002 (type d'entrée). CLI : source, scanner, inventaire, fichiers, taches, erreurs.
- CI macOS lancée à chaque envoi (décision du propriétaire).

## [0.1.0] — Phase 1 : socle (en attente de validation)

### Ajouté
- Paquet Python `mtlm` (Python 3.12+), dépendances verrouillées (`uv.lock`).
- Base locale SQLite (WAL, `synchronous=FULL`, clés étrangères, tables STRICT) avec le schéma
  complet du modèle de données (migration 0001), recherche plein texte FTS5.
- Moteur de migrations versionnées : une transaction par migration, empreinte des scripts
  vérifiée, refus d'une base plus récente, sauvegarde automatique avant migration.
- Sauvegarde vérifiée et restauration (avec sauvegarde de sécurité préalable) de la base.
- Journal d'audit append-only chaîné par SHA-256 (triggers anti-modification, vérification,
  export JSONL sans écrasement).
- Journaux techniques rotatifs horodatés en UTC.
- Ligne de commande `mtlm` : `version`, `init`, `etat`, `sauvegarder`, `restaurer`,
  `audit verifier`, `audit exporter`.
- Générateur de corpus synthétique fictif reproductible (hors application) + outil
  d'instantané pour l'invariant « sources inchangées ».
- Tests : unitaires, intégration, propriétés (Hypothesis), sécurité statique, hygiène du dépôt,
  charge 50 000 / 100 000 fichiers.
- CI GitHub Actions : Linux (Python 3.12 et 3.13), macOS (Apple Silicon et Intel), charge.

### Décisions
- Technologie Python/PySide6 (D-001) ; quarantaine par copie uniquement, après
  confirmation (D-007) — validées par le propriétaire le 2026-11-10.
