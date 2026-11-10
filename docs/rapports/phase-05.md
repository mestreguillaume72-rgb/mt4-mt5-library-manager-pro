# Rapport de phase 5 — Reconnaissance MetaTrader

> Date : 2026-11-10.

## 1. Livré (F4)

| Élément | Comportement | Fichiers |
|---|---|---|
| Encodages | BOM UTF-8/UTF-16, UTF-16 sans BOM, UTF-8, Windows-1252, Latin-1 — avec **niveau de confiance** | `src/mtlm/metatrader/encoding.py` |
| Analyse lexicale MQL | Commentaires et chaînes neutralisés avant analyse ; `#property` (dont descriptions multi-lignes), `#include`, `#import` (signalé, **jamais chargé**), paramètres `input`/`extern`/`sinput` déclarés au niveau global (déclarations multiples, `input group` ignoré), fonctions d'entrée (`OnTick`, `OnCalculate`, `OnStart`, `start()` MQL4…) ; empreinte normalisée (sans commentaires ni espaces) et esquisse de similarité pour la phase 8 | `src/mtlm/metatrader/mql.py` |
| Classement | Type (EA, indicateur, script, bibliothèque, include, service, SET, DLL, modèle, annexe, inconnu), plateforme, **certitude** (certain/probable/possible/inconnue), **preuves** listées, **limites** affichées. EX4/EX5 : binaires opaques, type seulement par dossier ou source appariée (« appariement par nom, non vérifié ») | `src/mtlm/metatrader/classify.py` |
| Service | Lecture seule ≤ 8 Mio par source, contrôle que les octets lus correspondent à l'empreinte validée, métadonnées stockées **par contenu** (copies analysées une fois), lots transactionnels, ré-analyse seulement si contenu ou moteur changent ; un fichier malformé n'arrête rien | `src/mtlm/app/recognize.py` |
| CLI | `mtlm reconnaitre`, `mtlm fichiers --type ea --plateforme mt4`, `mtlm fichier ID` (type, certitude, preuves, limites, encodage, version, paramètres, inclusions, imports) | `src/mtlm/cli/main.py` |

## 2. Cas de validation (F4)

| Cas imposé | Test |
|---|---|
| Exemples fictifs MT4/MT5 | `test_proprietes_includes_imports`, `test_parametres_declares_seulement`, `test_mt5_fonctions_d_entree`, `test_corpus_classe_selon_la_verite_terrain` (1 500 fichiers) |
| Fichiers renommés | `test_fichier_renomme_garde_son_contenu` (le contenu prime sur le nom) |
| Extension trompeuse | `test_extension_trompeuse`, `test_appariement_compile_et_limites` |
| Binaire inconnu | `test_autres_fichiers` (`xyz`, sans extension), `test_appariement_compile_et_limites` |
| Limites affichées | champ `limits` + `mtlm fichier ID` (`test_cli_reconnaitre_et_detail`) |
| Robustesse | `test_entrees_malformees_sans_plantage` (8 entrées hostiles) |

## 3. Résultats réels (Linux x86_64, Python 3.13)

| Commande | Résultat |
|---|---|
| `uv run pytest -W error::ResourceWarning --cov` | **282 passed, 1 skipped**, couverture 95 % |
| `uv run pytest -m slow -s` | **2 passed** |

Charge (corpus « tiny ») : 50 000 fichiers → reconnaissance 9,5 s ; 100 000 → 19,9 s ;
sources toujours inchangées.

## 4. Défaut de performance trouvé et corrigé
La première version prenait **386 s** à 100 000 fichiers (croissance quadratique) :
recherche de la source appariée par requête non indexée pour chaque EX4/EX5, et une
transaction avec écriture disque forcée par fichier. Correction : index des sources construit
une seule fois et lots de 500 fichiers par transaction (la base n'est jamais laissée verrouillée
pendant une pause). Résultat : **19,9 s**, croissance linéaire.

## 5. Limites
- Analyse lexicale : pas de résolution du préprocesseur conditionnel (`#ifdef`), ni des macros.
- `start()` (MQL4 ancien) sans dossier explicite : type inconnu (jamais deviné).
- EX4/EX5 : aucun contenu interne n'est lu ; leur type reste « probable » au mieux.
