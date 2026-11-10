# Traçabilité : exigence → code → tests → preuve

Mise à jour à chaque phase. « Preuve » renvoie au rapport de phase contenant les résultats réels.

| Exigence (spécification) | Code | Tests | Preuve | État |
|---|---|---|---|---|
| § 5 Moteur séparé de l'interface, testable sans GUI | `src/mtlm/*` (aucun import Qt) | `tests/security/test_static_rules.py` (règle PySide6 + couches) | phase-01 | ✅ Phase 1 |
| § 5 Base locale transactionnelle | `store/database.py` (`transaction`, WAL, FULL) | `test_migrations.py::test_transaction_annulee_sur_exception`, `test_pragmas_de_fiabilite` | phase-01 | ✅ |
| § 5 Migrations versionnées | `store/migrations_engine.py`, `store/migrations/0001_initial.sql` | `test_migrations.py` (11 tests moteur) | phase-01 | ✅ |
| § 5 Sauvegardes | `store/backup.py`, `mtlm sauvegarder/restaurer` | `test_backup.py` (16), `test_cli.py` | phase-01 | ✅ |
| § 5 Journal d'audit append-only | `audit/journal.py` + triggers SQL | `test_audit.py` (10 dont propriété Hypothesis) | phase-01 | ✅ |
| F12 Journaux rotatifs | `audit/logs.py` | `test_logs.py` | phase-01 | ✅ |
| § 4 Modèle de données minimal (10 entités) | migration 0001 (toutes les tables) | `test_migrations.py` (contraintes) | phase-01 | ✅ schéma ; moteurs à venir |
| D-007 Quarantaine par copie (aucun état touchant l'original) | migration 0001 (`quarantine_entry.state`) | `test_aucun_etat_de_quarantaine_ne_touche_l_original` | phase-01 | ✅ schéma |
| § 6 Aucune exécution / aucun réseau | règles statiques | `test_static_rules.py`, `conftest.no_network` | phase-01 | ✅ |
| § 9 Aucune donnée réelle dans Git | `.gitignore` | `test_repository_hygiene.py` | phase-01 | ✅ |
| § 11 Jeu de données synthétiques reproductible | `tests/synthetic/generate.py` | `tests/synthetic/test_generator.py` | phase-01 | ✅ base (enrichi en phases 2, 4, 6) |
| F12 Tests 50k / 100k | `tests/integration/test_invariant_sources.py` (`-m slow`) | idem | phase-01 | ✅ génération + invariant |
| § 1 Sources en lecture seule | invariant (outil `tests/support/fs_snapshot.py`) | `test_invariant_sources.py` | phase-01 | ✅ référence ; étendu à chaque moteur |
| § 8 Phase 1 « installation reproductible » | `uv.lock`, `tools/check_wheel.py` | CI `ci.yml` + essai local en venv vierge | phase-01 | ✅ Linux ; macOS en CI |
| F1 Sources et inventaire lecture seule | `fs/walker.py`, `fs/paths.py`, `app/sources.py`, `app/scan.py` | `test_walker.py` (20), `test_scan.py` (17), `test_cli.py` | phase-02 | ✅ Phase 2 |
| F11/F12 Pause, reprise, annulation, reprise après fermeture | `core/control.py`, `app/jobs.py` | `test_pause_puis_reprise`, `test_annulation_ne_declare_aucun_manquant`, `test_tache_interrompue_detectee_au_demarrage` | phase-02 | ✅ moteur |
| F10 Recherche paginée, filtres (base) | `app/inventory.py` | `test_pagination_filtres_et_recherche` | phase-02 | ✅ base |
| F2 Métadonnées et empreintes SHA-256 en flux | `fs/reader.py`, `hashing/sha256.py`, `app/hashing.py` | `test_sha256.py` (17), `test_hashing.py` (10) | phase-03 | ✅ Phase 3 |
| F13 Compatibilité testée (macOS réels) | `.github/workflows/macos.yml` | suite complète sur macOS 15 arm64 et Intel | run 42908401882 | ✅ moteur (CI) |
| F3 à F11, F13 (livraison) | — | — | — | ⏳ phases 4 à 12 |
