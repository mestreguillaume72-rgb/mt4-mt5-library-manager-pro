# Rapport de phase 3 — Métadonnées et empreintes SHA-256

> Date : 2026-11-10.

## 1. Livré (F2)

| Élément | Comportement | Fichiers |
|---|---|---|
| Lecture seule en flux | `O_RDONLY | O_NOFOLLOW | O_NONBLOCK`, refus des fichiers non ordinaires avant lecture, blocs de 1 Mio | `src/mtlm/fs/reader.py` |
| SHA-256 + stabilité | Identité (taille, date, inode, périphérique) comparée avant/après sur le descripteur **et** le chemin ; octets lus = taille ; refus si modifié depuis l'inventaire | `src/mtlm/hashing/sha256.py` |
| Service | États `not_computed → in_progress → validated | error`, `stale` après modification ; lots transactionnels ; calcul parallèle borné ; pause/annulation entre deux blocs, aucune empreinte partielle ; reprise des `in_progress` après fermeture brutale ; version du moteur enregistrée ; contenus dédupliqués (table `content`) | `src/mtlm/app/hashing.py` |
| Fichiers jamais lus | Liens symboliques, tubes/périphériques, fichiers iCloud non téléchargés | idem |
| CLI | `mtlm empreintes [--source] [--reessayer-erreurs] [--travailleurs N]`, `mtlm fichier ID` (détail : chemin, taille, état et valeur de l'empreinte, erreur, autres emplacements au contenu identique) | `src/mtlm/cli/main.py` |

## 2. Cas de validation (F2)

| Cas imposé | Test |
|---|---|
| Fichiers vides | `test_vecteurs_nist[...]` (vecteur NIST de la chaîne vide), `test_tailles_limites[0]` |
| Gros fichiers | `test_memoire_constante_gros_fichier` (64 Mio, pic mémoire < 8 Mio), `test_tailles_limites` (frontières de blocs) |
| Lecture interrompue | `test_lecture_interrompue_propage_l_erreur`, `test_annulation_aucune_empreinte_partielle` |
| Fichier modifié pendant le scan | `test_modifie_pendant_la_lecture`, `test_remplace_pendant_la_lecture`, `test_modifie_depuis_l_inventaire`, `test_fichier_modifie_apres_inventaire_en_erreur` |
| Reprise et cohérence du hash | `test_reprise_apres_fermeture_brutale`, `test_deuxieme_passage_ne_recalcule_rien`, `test_fichier_modifie_recalcule` |
| Conformité | `test_identique_a_l_outil_systeme` (`sha256sum`/`shasum -a 256`), `test_empreintes_conformes_et_sources_intactes` (800 fichiers = manifeste) |

## 3. Résultats réels

| Environnement | Commande | Résultat |
|---|---|---|
| Linux x86_64, Python 3.13.18 | `uv run pytest -W error::ResourceWarning --cov` | **183 passed, 1 skipped**, couverture 96 % |
| Linux | `uv run pytest -m slow -s` | **2 passed** |
| **macOS 15 Apple Silicon** (GitHub, Python 3.12.10) — run 42908401882 | suite complète + invariant 50 000 | ✅ succès (code de la phase 2) |
| **macOS 15 Intel** (GitHub) — run 42908401882 | suite complète + invariant 50 000 | ✅ succès (code de la phase 2) |

Charge (Linux, corpus « tiny ») :

| Corpus | 2 inventaires | Empreintes (2 passages) | RAM max du processus de test | Invariant |
|---|---|---|---|---|
| 50 000 | 2,5 s | 11,7 s | 152 Mio | 0 différence |
| 100 000 | 5,5 s | 23,7 s | 256 Mio | 0 différence |

Sur des fichiers minuscules, le coût est dominé par l'ouverture des fichiers (~4 200 fichiers/s) ;
sur des fichiers volumineux il est limité par le débit du disque.

## 4. Limites
- La date de dernier accès (`atime`) peut être mise à jour par le système lors d'une lecture selon
  les options de montage ; elle est exclue de l'invariant (documenté au PLAN_DE_TESTS § 5).
- Une collision SHA-256 (même empreinte, tailles différentes) arrête l'enregistrement par sécurité ;
  la vérification octet par octet des doublons viendra en phase 8.
