# Rapport de phase 2 — Scanner (inventaire en lecture seule)

> Date : 2026-11-10 · Développement autonome autorisé par le propriétaire (docs/VALIDATIONS.md).

## 1. Livré (F1, scénario A)

| Élément | Comportement | Fichiers |
|---|---|---|
| Énumération | Itérative, chemins en octets (aucun nom perdu), liens symboliques enregistrés mais **jamais suivis**, cycles évités par (périphérique, inode), erreurs consignées sans interrompre ; seuls `scandir`/`stat` sont utilisés : **aucun fichier n'est ouvert** | `src/mtlm/fs/walker.py` |
| Comparaison de dossiers | Identité (périphérique, inode) : robuste aux différences de casse et de forme Unicode (macOS) | `src/mtlm/fs/paths.py` |
| Sources | Ajout (refus : absent, fichier, illisible, chevauchement d'une autre source, dossier de l'application), liste, retrait sans suppression de fichier, ré-ajout | `src/mtlm/app/sources.py` |
| Inventaire | Incrémental (nouveau / modifié / inchangé / disparu), lots transactionnels, empreinte « stale » si le fichier change, aucun « disparu » déclaré si l'inventaire est annulé, source inaccessible détectée | `src/mtlm/app/scan.py` |
| Tâches | Pause, reprise, annulation à un point sûr ; tâches restées « en cours » après une fermeture brutale marquées « interrompues » au démarrage | `src/mtlm/core/control.py`, `src/mtlm/app/jobs.py` |
| Consultation | Statistiques, liste paginée par clé, filtres (source, extensions, présence, état d'empreinte, type), recherche plein texte insensible aux accents et protégée contre l'injection, erreurs par tâche | `src/mtlm/app/inventory.py` |
| Migration 0002 | Type d'entrée (`file`/`symlink`/`other`) — les tubes, sockets… sont inventoriés mais ne seront jamais lus | `src/mtlm/store/migrations/0002_file_type.sql` |
| CLI | `source ajouter/lister/retirer --confirmer`, `scanner`, `inventaire`, `fichiers`, `taches`, `erreurs` | `src/mtlm/cli/main.py` |

## 2. Cas de validation de la spécification (F1)

| Cas imposé | Test |
|---|---|
| Dossiers imbriqués | `test_corpus_compte_exact_et_unicode` (profondeur jusqu'à 6), `test_chemin_long` |
| Noms accentués (NFC et NFD) | `test_corpus_compte_exact_et_unicode`, `test_display_path_normalise_nfc`, `test_nom_non_utf8_conserve_en_octets` |
| Extensions inconnues | corpus (8 extensions inconnues + sans extension), `test_extension` |
| Permissions refusées | `test_dossier_illisible_simule` (toujours), `test_dossier_illisible_reel` (ignoré sous l'administrateur, qui contourne les permissions — exécuté en CI macOS) |
| Liens symboliques cycliques | `test_liens_symboliques_cycliques_non_suivis`, `test_meme_dossier_atteint_deux_fois_ignore` |
| Fichier inaccessible | `test_fichier_inaccessible_n_arrete_pas`, `test_erreurs_consignees` |
| Hashes avant/après identiques | invariant « sources inchangées » : `test_commandes_ne_touchent_pas_les_sources` (2 000 fichiers) et charge 50k/100k |

## 3. Résultats réels

Environnement : Linux x86_64, Python 3.13.18, SQLite 3.53.1.

| Commande | Résultat |
|---|---|
| `uv run ruff check .` / `ruff format --check` / `mypy` | OK / OK / « no issues found in 47 source files » |
| `uv run pytest -W error::ResourceWarning --cov` | **156 passed, 1 skipped**, couverture totale 96 % (`fs/walker` 98 %, `app/scan` 98 %, `app/sources` 96 %, `app/inventory` 94 %) |
| `uv run pytest -m slow -s` | **2 passed** |

Charge (corpus fictif « tiny », graine 2026) :

| Corpus | 2 inventaires (initial + incrémental) | RAM max du processus de test | Invariant |
|---|---|---|---|
| 50 000 fichiers | 2,3 s | 138 Mio | 0 différence |
| 100 000 fichiers | 5,4 s | 231 Mio | 0 différence |

## 4. Limites connues

- macOS limite un chemin absolu à 1 024 octets : au-delà, le système renvoie `ENAMETOOLONG`, consigné comme erreur (l'inventaire continue).
- Le test de permission réelle est ignoré sous un compte administrateur (cas de ce conteneur) ; il s'exécute en CI macOS.
- La reprise d'un inventaire interrompu se fait en relançant l'inventaire : grâce à l'incrémental, les fichiers déjà connus ne coûtent qu'une comparaison de métadonnées.
