# Changelog

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
