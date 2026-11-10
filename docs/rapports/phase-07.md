# Rapport de phase 7 — Familles et versions

> Date : 2026-11-10.

## 1. Livré (F6, scénario C)

| Élément | Comportement | Fichiers |
|---|---|---|
| Identité logique | Clé de nom normalisée (minuscules, sans accents, sans version, sans « copie », « (2) »…) + plateforme ; **séparée de l'empreinte binaire** | `src/mtlm/matching/names.py` |
| Homonymes | Sources de même nom aux paramètres trop différents (< 50 % de noms communs, contenu et description différents) ⇒ **familles distinctes**, marquées « homonyme distinct » — jamais fusionnées | `src/mtlm/matching/families.py` |
| Relations | copie exacte, copie renommée, version, source, compilé, homonyme distinct, SET associé — chacune avec sa confiance | idem |
| Versions | `#property version` > version dans le nom > source appariée (« supposé ») > ordre des dates (« supposé ») — la base est toujours affichée | idem |
| SET | Rattachés à la famille de leur robot si l'association est acceptée par l'utilisateur, ou « forte » et non rejetée | `src/mtlm/app/families.py` |
| CLI | `mtlm regrouper`, `mtlm familles [--recherche] [--min-membres]`, `mtlm famille ID [--fichier]` | `src/mtlm/cli/main.py` |

## 2. Cas de validation (F6)

| Cas imposé | Test |
|---|---|
| Même nom / contenu différent | `test_meme_nom_contenu_different_homonymes` (robots différents ⇒ 2 familles) et `test_meme_nom_contenu_different_meme_robot` (même robot ⇒ 2 versions) |
| Version dans le nom | `test_version_dans_le_nom` |
| Version dans les métadonnées | `test_version_dans_les_metadonnees` |
| Compilation différente | `test_compilation_differente` |
| Copie identique renommée | `test_copie_identique_renommee` |
| Raison et confiance affichées | `test_cli_familles` (`mtlm famille ID`) |

## 3. Résultats réels (Linux, Python 3.13)

| Commande | Résultat |
|---|---|
| `uv run pytest -W error::ResourceWarning --cov` | **331 passed, 1 skipped**, couverture 95 % |
| `uv run pytest -m slow -s` | **2 passed** |

Charge, pipeline complet (corpus « tiny ») :

| Étape | 50 000 fichiers | 100 000 fichiers |
|---|---|---|
| 2 inventaires | 2,2 s | 5,3 s |
| Empreintes | 11,7 s | 22,9 s |
| Formats | 1,1 s | 2,0 s |
| Reconnaissance | 9,6 s | 19,5 s |
| SET | 2,0 s | 3,9 s |
| Associations | 10,0 s | 34,5 s |
| Familles | 1,3 s | 2,9 s |
| RAM max du processus de test | 181 Mio | 304 Mio |
| Sources | inchangées | inchangées |

Point à surveiller (phase 11) : le calcul des associations croît plus vite que linéairement
(×3,5 pour ×2 fichiers) ; il reste acceptable à 100 000 fichiers.
