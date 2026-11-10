# Rapport de phase 6 — Analyse SET et associations robot ↔ SET

> Date : 2026-11-10.

## 1. Livré (F5, scénario B)

| Élément | Comportement | Fichiers |
|---|---|---|
| Lecteur SET | MT4 (`nom=valeur`, `nom,F/1/2/3=`) et MT5 (`valeur||début||pas||fin||Y/N`, commentaires `;`) ; encodages via le détecteur commun ; **valeur brute conservée**, valeur normalisée et type estimé (bool, int, double, datetime, couleur, texte) ; lignes mal formées, clés en double et optimisations orphelines **signalées** ; format déterminé avec sa justification | `src/mtlm/setfiles/parser.py` |
| Comparaison SET ↔ SET | Paramètre par paramètre (identique, différent, présent d'un seul côté) ; empreinte normalisée (ordre et écriture des nombres indifférents) | idem |
| Moteur d'association | Score 0–100 **explicable** : couverture des noms de paramètres (40), compatibilité des types (15), valeurs par défaut (5), similarité des noms (20), emplacement (10), plateforme (10), pénalité jusqu'à −20 pour les paramètres inconnus du robot. Chaque critère = une preuve « pour », « contre » ou « incertitude » | `src/mtlm/matching/associations.py`, `src/mtlm/matching/names.py` |
| Règles dures | « forte » ⇒ score ≥ 75 **et** ≥ 80 % des paramètres du SET présents dans le robot ; robot sans source (EX4/EX5) ⇒ **« à vérifier »** au mieux ; ambiguïté entre robots distincts ⇒ « moyenne » au mieux ; copies et paires source/compilé ne sont pas une ambiguïté ; **aucune validation automatique** | idem |
| Service | Candidats par index (noms de paramètres, nom logique, dossier) — pas de produit cartésien ; décisions de l'utilisateur **conservées** lors d'un recalcul ; chaque décision journalisée ; SET orphelins | `src/mtlm/app/sets.py`, migration `0004` |
| CLI | `sets`, `set ID`, `comparer-sets A B`, `associer`, `associations [--set] [--robot] [--niveau]`, `association ID` (preuves), `valider ID --accepter / --rejeter / --annuler`, `orphelins` | `src/mtlm/cli/main.py` |

## 2. Cas de validation (F5)

| Cas imposé | Test |
|---|---|
| SET vide | `test_set_vide` |
| SET mal formé | `test_set_mal_forme_conserve_et_signale`, `test_optimisation_orpheline` |
| Encodages | `test_encodages` (UTF-16 BOM, CP1252, UTF-8, UTF-8 BOM) |
| Doublons de clés | `test_cles_en_double` |
| Paramètres inconnus | `test_parametres_inconnus_penalisent` |
| Variantes MT4/MT5 | `test_mt4_et_optimisation`, `test_mt5_et_commentaires`, `test_format_indetermine_et_indice_utf16` |
| SET presque identiques | `test_sets_presque_identiques`, `comparer-sets` (CLI) |
| Association non prouvée ⇒ « à vérifier » | `test_robot_sans_source_plafonne_a_verifier`, `test_orphelin_et_robot_compile_a_verifier` |
| Ambiguïté | `test_ambiguite_deux_robots_distincts`, `test_copies_du_meme_robot_ne_sont_pas_une_ambiguite` |
| Preuves, confiance, incertitudes affichées | `test_association_forte_avec_preuves`, `mtlm association ID` |

## 3. Résultats réels (Linux, Python 3.13)

| Mesure | Résultat |
|---|---|
| Tests de la phase | 34 unitaires + 4 intégration : **réussis** |
| Corpus fictif 10 000 fichiers (1 928 SET, 5 350 robots) | 1er candidat correct **1 928/1 928** ; précision des « fortes » **1,000** ; durée du calcul **0,9 s** |

**Réserve honnête** : dans le corpus synthétique, chaque SET est construit à partir des
paramètres exacts d'un robot fictif ; c'est un cas favorable. La qualité sur une vraie
bibliothèque (SET incomplets, robots renommés, versions multiples) devra être mesurée sur les
exemples fictifs fournis par le propriétaire (Annexe de la spécification) ; les poids sont
versionnés (`associations-v1`) pour pouvoir être recalibrés sans mélanger les résultats.

## 4. Écart avec l'architecture
Le critère « cohérence de dates » (poids 5) prévu en ARCHITECTURE § 8.6 n'a pas été retenu :
indice trop peu fiable (dates modifiées par les copies). Son poids est reporté sur la similarité
des noms (15 → 20). Documenté dans le code (`METHOD_VERSION = associations-v1`).
