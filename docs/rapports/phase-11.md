# Rapport de phase 11 — Performance, sécurité et fiabilité (F12)

> Date : 2026-11-10. Outil : `tools/mesure_performance.py` (l'application seule, dans un
> processus séparé du générateur de données ; corpus synthétique fictif « tiny », graine 2026).
> Environnement : Linux x86_64, 4 cœurs, Python 3.13.18.

## 1. Mesures réelles et budgets (ARCHITECTURE § 9)

| Mesure | 50 000 fichiers | 100 000 fichiers | Budget proposé | Verdict |
|---|---|---|---|---|
| Inventaire initial | 1,3 s | 3,2 s | ≤ 60 s / ≤ 120 s | ✅ |
| Ré-inventaire sans changement | 0,9 s | 1,9 s | ≤ 20 s / ≤ 40 s | ✅ |
| Empreintes SHA-256 | 11,0 s | 23,9 s | limité par le disque | ✅ (≈ 4 200 fichiers/s sur fichiers minuscules) |
| Formats et archives | 0,9 s | 2,4 s | — | ✅ |
| Reconnaissance MetaTrader | 9,1 s | 20,3 s | — | ✅ (corrigé : 386 s avant optimisation) |
| Analyse des SET | 1,7 s | 4,2 s | — | ✅ |
| Associations robot ↔ SET | 10,0 s | 34,6 s | — | ⚠️ croissance plus que linéaire (×3,5 pour ×2) |
| Familles | 1,2 s | 2,5 s | — | ✅ |
| Doublons et similarités | 1,7 s | 3,8 s | — | ✅ |
| **Pipeline complet** | **38 s** | **97 s** | — | ✅ |
| Explorateur : 1re page | 8 ms | 9 ms | ≤ 300 / 500 ms | ✅ |
| Explorateur : filtre extension | 15 ms | 23 ms | idem | ✅ |
| Explorateur : filtres combinés | 29 ms | 45 ms | idem | ✅ |
| Ouverture + détection des tâches interrompues | < 0,1 s | < 0,1 s | ≤ 10 s / 15 s | ✅ |
| Reprise des empreintes après fermeture brutale | < 0,1 s | < 0,1 s | — | ✅ |
| **RAM maximale de l'application** | **260 Mio** | **580 Mio** | ≤ 600 / 800 Mio | ✅ |
| Interface bloquée pendant une analyse | < 0,5 s (3 000 fichiers) | — | jamais > 200 ms visé | ⚠️ seuil de test 0,5 s |

Avec écritures réelles (tests de charge `pytest -m slow`, rapport des phases 8-9) : quarantaine
de tous les doublons + restauration 49 s, copie organisée de toute la bibliothèque 72 s à
100 000 fichiers, **sources inchangées à l'octet près**.

## 2. Sécurité et fiabilité (récapitulatif)
- Lecture seule des sources prouvée par instantané avant/après à 50 000 et 100 000 fichiers,
  y compris après quarantaine, restauration et organisation (Linux) et à 50 000 (macOS, CI).
- Archives hostiles (bombe, traversée, liens, chiffrées) : refus sans écriture disque.
- Aucune exécution, aucun réseau : règles statiques vérifiées à chaque envoi.
- Reprise après fermeture : tâches, lots de quarantaine et plans d'organisation marqués
  « interrompus » et repris sans perte.
- Journaux techniques rotatifs ; journal d'audit append-only chaîné.

## 3. Limites et pistes
- Associations : la génération des candidats par préfixe de nom croît plus vite que
  linéairement ; acceptable à 100 000 fichiers (35 s), à optimiser si la bibliothèque réelle
  dépasse nettement ce volume.
- Mesures faites sur fichiers minuscules : sur de vrais robots (quelques dizaines à centaines
  de Kio), le calcul d'empreintes sera limité par la vitesse du disque.
- Mesure de référence sur le Mac du propriétaire : `PYTHONPATH=. uv run python
  tools/mesure_performance.py 50000 100000` (ou workflow « Charge 50k-100k » sur GitHub).
