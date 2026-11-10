# Changelog

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
