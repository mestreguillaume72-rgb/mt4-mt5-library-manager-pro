# Rapport de phase 12 — Livraison macOS (F13)

> Date : 2026-11-10. Tout le travail Mac est fait par GitHub Actions sur de vrais Mac
> (décision du propriétaire). Exécution de référence : workflow « Application macOS »,
> run 42919451282 (commit `3a13261`).

## 1. Livré

| Élément | Détail |
|---|---|
| Application | `MT4 MT5 Library Manager PRO.app` (PyInstaller, Python 3.12, Qt 6.12), identifiant `fr.mtlm.library-manager-pro`, macOS minimal déclaré 12.0 |
| Images disque | `MT4-MT5-Library-Manager-PRO-<version>-macOS-Apple-Silicon.dmg` et `…-macOS-Intel.dmg` (UDZO, glisser-déposer vers Applications), empreinte `.sha256` fournie |
| Construction reproductible | `packaging/macos/mtlm.spec`, dépendances verrouillées (`uv.lock`, groupe `build`) |
| Auto-diagnostic | `mtlm-gui --autotest DOSSIER` : 13 écrans, analyse complète en lecture seule, contrôle des résultats |
| Publication | sur étiquette `v*` : pré-version GitHub avec les deux DMG |
| Documentation | `docs/utilisateur/installation.md` (installation, premier lancement, mise à jour, sauvegarde, désinstallation), `docs/COMPATIBILITE.md` |

## 2. Vérifications réelles sur Mac (run 42919451282)

| Vérification | Apple Silicon (macos-15) | Intel (macos-15-intel) |
|---|---|---|
| Construction `.app` | ✅ | ✅ |
| Signature (ad hoc) `codesign --verify --deep --strict` | ✅ | ✅ |
| Auto-diagnostic sur l'application construite + contenu inchangé après analyse | ✅ | ✅ |
| DMG créé et `hdiutil verify` | ✅ | ✅ |
| Application lancée **depuis le DMG monté** : auto-diagnostic | ✅ « RÉUSSI — 13 écran(s), 268 fichier(s) analysé(s) » | ✅ |
| Gatekeeper `spctl --assess` | « rejected » (attendu : non notarisée) | idem |

Taille du DMG Apple Silicon : ≈ 33 Mo (compressé).

## 3. Ce qui reste à faire par le propriétaire (seule action manuelle)
1. Télécharger le DMG de son Mac depuis l'onglet **Releases** du dépôt.
2. L'installer et l'ouvrir la première fois par **clic droit → Ouvrir** (application non
   notarisée faute de compte Apple Developer — Q-03).
3. Signaler toute anomalie ; la matrice de compatibilité sera complétée avec son modèle de Mac
   et sa version de macOS (Q-02).

## 4. Limites
- Non notarisée (pas de compte Apple Developer) ; signature ad hoc seulement.
- Universal2 non produit : un DMG par architecture, chacun construit et testé sur sa machine.
- Rendu visuel final (style natif) vérifié uniquement par l'auto-diagnostic hors écran : un
  contrôle visuel sur le Mac du propriétaire reste souhaitable.
