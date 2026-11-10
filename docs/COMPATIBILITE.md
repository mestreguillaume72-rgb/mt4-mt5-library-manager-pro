# Matrice de compatibilité macOS (F13)

Règle : **aucune compatibilité n'est annoncée sans preuve**. Chaque ligne renvoie à une
exécution réelle.

| macOS | Architecture | Ce qui a été vérifié | Preuve | Statut |
|---|---|---|---|---|
| 15 (GitHub `macos-15`) | Apple Silicon (arm64) | suite de tests complète + invariant 50 000 fichiers | CI « CI macOS » à chaque envoi | ✅ moteur et interface (hors écran) |
| 15 (GitHub `macos-15-intel`) | Intel (x86_64) | idem | CI « CI macOS » à chaque envoi | ✅ moteur et interface (hors écran) |
| 15 (GitHub `macos-15`) | Apple Silicon | construction `.app`, signature ad hoc vérifiée, auto-diagnostic, DMG vérifié, application lancée depuis le DMG monté | run 42919451282 | ✅ |
| 15 (GitHub `macos-15-intel`) | Intel | idem | run 42919451282 | ✅ |
| Mac du propriétaire | à préciser (Q-02) | installation depuis le DMG, lancement, analyse réelle | à faire par le propriétaire | ⏳ non testé |
| macOS 12 à 14 | — | **non testé** (version minimale déclarée dans l'application : 12.0, imposée par Qt 6) | — | ⏳ non annoncé |

Limites :
- Application **non notarisée** (pas de compte Apple Developer, Q-03) : ouverture par clic droit
  au premier lancement.
- **Universal2 non produit** : deux DMG distincts (Apple Silicon, Intel), chacun construit et
  testé sur son architecture.
