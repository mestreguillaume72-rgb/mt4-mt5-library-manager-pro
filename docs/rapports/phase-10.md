# Rapport de phase 10 — Interface graphique

> Date : 2026-11-10. Technologie : PySide6 (Qt 6.12), paquet `pyside6-essentials`.

## 1. Livré (F11)

13 écrans, tous reliés aux services réels (aucune logique métier dans l'interface) :

| Écran | Actions réelles |
|---|---|
| Tableau de bord | compteurs calculés depuis la base, dernières tâches, « Tout analyser » |
| Sources | ajouter (sélecteur de dossier), inventorier, retirer (confirmation, aucun fichier supprimé) |
| Analyse | étapes au choix ou tout, **pause / reprise / annulation**, journal, erreurs par tâche |
| Explorateur | recherche sans accents, extensions, type, plateforme, disparus, **pagination** (500/page), détail |
| Détail fichier | métadonnées, empreinte, format réel, type, certitude, preuves, limites, paramètres, imports |
| SET et associations | paramètres bruts/normalisés, associations avec **preuves**, accepter / rejeter / annuler, comparer deux SET, orphelins |
| Familles et versions | recherche, raisons du regroupement, relations, versions et leur base |
| Doublons | exacts (référence, admissibilité, choix de la référence, vérification octet par octet) et similaires séparés |
| Quarantaine et restauration | destination, **simulation obligatoire**, confirmation, lots, restauration, recopie, annulation |
| Bibliothèque organisée | destination, prévisualisation (arborescence, collisions), confirmation, plans |
| Rapports et journal | exports CSV/JSON, export et vérification du journal d'audit, sauvegarde de la base |
| Paramètres | seuil de similarité, calculs parallèles, limites d'archives — utilisés par les traitements |
| Aide | mode d'emploi en français, garanties, **limites des formats opaques** |

Principes techniques :
- **Registre d'actions** : chaque bouton est créé par le registre (identifiant, libellé, nom
  accessible, gestionnaire réel) ; un bouton sans fonction serait affiché désactivé « non
  disponible » avec la raison (aucun dans cette version).
- **Tâches longues dans un fil séparé**, avec leur propre connexion à la base ; l'interface ne
  fait aucune lecture de fichier source ; une seule tâche longue à la fois.
- Erreurs toujours affichées (jamais muettes) et journalisées.
- Navigation clavier (barre latérale, Ctrl+1…9, tabulation sur tous les boutons).
- Textes en français simple.

## 2. Cas de validation (F11)

| Cas imposé | Test (`tests/ui/test_ui.py`) |
|---|---|
| Parcours utilisateur | `test_parcours_complet` : source → analyse → tableau de bord (valeurs = base) → explorateur → détail → acceptation d'association → familles → doublons → quarantaine (simulation, confirmation, copie, restauration) → organisation → export → paramètres ; **originaux inchangés** |
| États vides | `test_etat_vide_honnete` (aucune donnée fictive) |
| Erreurs | `test_erreur_affichee_jamais_muette` |
| Annulation | `test_annulation_et_reactivite` (pause, reprise, annulation ; aucune tâche restée « en cours ») |
| Accessibilité clavier | `test_navigation_au_clavier`, noms accessibles et focus clavier vérifiés pour chaque bouton |
| Aucune action décorative | `test_chaque_bouton_est_enregistre_accessible_et_branche` : **chaque bouton est cliqué** et son gestionnaire réel doit s'exécuter ; tout bouton non enregistré fait échouer le test |
| Réactivité | aucune pause de la boucle d'interface > 0,5 s pendant l'analyse de 3 000 fichiers |

## 3. Résultats réels (Linux, Qt hors écran)

`bash tools/verifier.sh` : **385 passed, 1 skipped**, couverture **92 %**.

Captures de l'application réelle sur corpus fictif : `docs/captures/` (13 écrans).

## 4. Ce qui attend un Mac
Le rendu final macOS (style natif, polices, menus, dialogues natifs de sélection de dossier)
n'est vérifiable que sur macOS ; les tests d'interface s'exécutent aussi en CI macOS.
