# Rapport des phases 8 et 9 — Doublons, quarantaine, bibliothèque organisée

> Date : 2026-11-10. Décision du propriétaire appliquée : quarantaine **par copie uniquement**,
> proposée (simulation) puis exécutée seulement après confirmation.

## 1. Livré

| Élément | Comportement | Fichiers |
|---|---|---|
| Module `transfer` | **Seul** module qui écrit hors de l'application. Copie vérifiée : source en lecture seule, identité contrôlée, fichier temporaire exclusif, `fsync`, **relecture et contrôle SHA-256**, mise en place **sans écrasement possible**, date d'origine reportée sur la copie ; échec ⇒ temporaire supprimé, original intact | `src/mtlm/transfer/copy.py`, `records.py`, `exports.py` |
| Contrôle des destinations | Refus : destination dans une source ou la contenant (y compris via lien symbolique), dossiers de l'application, **destination absente (disque débranché)**, non inscriptible ; contrôle d'espace libre avec marge | `src/mtlm/transfer/guards.py` |
| Doublons (F7) | Exacts = même taille + SHA-256 validé ; **référence** conservée (hors dossiers « copie/backup/old », mieux reconnue, chemin court) modifiable par l'utilisateur et conservée lors d'un recalcul ; admissibilité expliquée ; vérification **octet par octet** (collision théorique) ; équivalents normalisés, sources similaires (esquisse « bottom-k » 128) et SET similaires **dans une table séparée** | `src/mtlm/app/duplicates.py` |
| Quarantaine (F8) | Simulation (rapport JSON + jeton) → confirmation par jeton → copie vérifiée par fichier ; plan invalidé si un fichier a changé ; **référence revérifiée** juste avant ; arrêt au premier doute ; manifeste + journal JSONL dans le lot ; reprise d'un lot interrompu ou en échec ; restauration (retrait de la marque ; recopie d'un original disparu sur demande, conflits jamais écrasés) ; aucune purge | `src/mtlm/app/quarantine.py` |
| Organisation (F9) | Prévisualisation (arborescence par plateforme/type/famille/version, SET par statut associés/à vérifier/orphelins, annexes, inconnus ; collisions résolues et rapportées ; espace) → confirmation par jeton → copie vérifiée dans un **nouveau dossier** ; reprise ; doublons copiés une seule fois ; quarantaine exclue ; manifeste | `src/mtlm/app/organize.py` |
| Exports (F10) | Inventaire, associations, doublons, similaires, familles, erreurs, paramètres SET — CSV (Excel, « ; ») ou JSON ; jamais d'écrasement ni d'écriture dans une source | `src/mtlm/app/reports.py` |
| Paramètres, pipeline | Paramètres persistants utilisés par les traitements ; pipeline complet `mtlm analyser` | `src/mtlm/app/settings.py`, `pipeline.py` |
| Migration 0005 | Choix de référence, jeton de plan, tailles | `src/mtlm/store/migrations/0005_quarantine_organize.sql` |
| Documentation | Mode d'emploi quarantaine/restauration | `docs/utilisateur/quarantaine-et-restauration.md` |

## 2. Cas de validation

| Spécification | Cas imposé | Test |
|---|---|---|
| F7 | copie exacte, même contenu renommé | `test_doublons_exacts_et_similaires_separes` |
| F7 | fichier presque identique, homonyme différent | idem (jamais doublons exacts) |
| F7 | collision théorique : vérification supplémentaire | `test_collision_theorique_verification_octet_par_octet` |
| F8 | dry-run | `test_quarantaine_complete_et_restauration` (rien copié pendant la simulation) |
| F8 | confirmation | jeton incorrect refusé ; plan invalidé si modification ; référence modifiée/absente |
| F8 | disque plein | `test_disque_plein`, `test_disque_plein_et_reprise` |
| F8 | interruption | `test_interruption_detectee_au_redemarrage` |
| F8 | destination existante | `test_destination_existante_jamais_ecrasee`, `test_destination_existante_et_dans_la_source` |
| F8 | hash différent | `test_empreinte_differente`, `test_copie_corrompue_detectee_a_la_relecture` |
| F8 | restauration, conflit de chemin | `test_restauration_conflit_et_original_disparu` |
| F8 | « tout échec préserve une copie vérifiée » | les originaux ne sont jamais touchés : invariant vérifié après chaque scénario |
| F9 | collision de nom | `test_organisation_complete` (« Grid (2).mq4 ») |
| F9 | reprise de copie, hash non conforme | `test_organisation_reprise_et_hash_non_conforme` |
| F9 | destination indisponible, espace insuffisant | `test_organisation_destination_indisponible_ou_pleine` |

## 3. Résultats réels (Linux x86_64, Python 3.13)

| Commande | Résultat |
|---|---|
| `bash tools/verifier.sh` (lint, format, types, tests, paquet) | **377 passed, 1 skipped**, couverture **93 %** |
| `uv run pytest -m slow -s` | **2 passed** |

Charge avec **écritures réelles** (corpus « tiny ») — l'invariant inclut maintenant quarantaine
exécutée, restauration et copie organisée complète :

| Étape | 50 000 fichiers | 100 000 fichiers |
|---|---|---|
| Inventaires (2) | 2,5 s | 5,5 s |
| Empreintes | 11,3 s | 22,3 s |
| Reconnaissance | 9,3 s | 19,3 s |
| Associations | 10,3 s | 34,2 s |
| Doublons | 1,6 s | 4,3 s |
| Quarantaine (simulation + copie vérifiée + restauration) | 22,8 s | 49,4 s |
| Organisation (prévisualisation + copie vérifiée de tous les fichiers) | 35,4 s | 72,3 s |
| RAM max du processus de test (générateur et instantanés compris) | 340 Mio | 719 Mio |
| **Sources après toutes ces opérations** | **inchangées (0 différence)** | **inchangées (0 différence)** |

## 4. Défauts trouvés par les tests et corrigés
1. Contrôle de destination : une destination encore inexistante était évaluée sur son premier
   parent existant, ce qui refusait à tort `/tmp/ailleurs` si `/tmp` contenait la source.
2. **Sécurité** : une destination sur disque externe débranché aurait été recréée sur le disque
   interne (le point de montage parent existe) — la destination doit désormais exister.
3. **Sécurité** : la référence conservée n'était pas revérifiée avant la quarantaine — elle l'est
   maintenant à l'instant de l'exécution (empreinte recalculée).
4. Disque plein : l'échec d'écriture du journal du lot faisait planter l'opération — l'arrêt est
   désormais propre et tracé dans l'audit.
5. Restauration : un fichier en « conflit » ne pouvait plus être restauré après correction.
6. Référence : la règle « chemin le plus court » choisissait une copie rangée dans « Copies ».
7. Processus : la CI Linux de la phase 6 a échoué (vérification des types non relancée avant
   l'envoi) ; corrigé en phase 7 et prévenu par le script `tools/verifier.sh`.

## 5. Limites
- La similarité des sources est estimée (esquisse de 128 valeurs) : le score exact n'est pas
  recalculé à l'affichage dans cette version (méthode indiquée avec chaque résultat).
- Une destination sur un système de fichiers sans liens matériels (exFAT, partages) utilise un
  repli contrôlé (vérification d'absence puis renommage).
