# Changelog

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
