# Matrice de compatibilité macOS (F13)

Règle : **aucune compatibilité n'est annoncée sans preuve**. Chaque ligne renvoie à une
exécution réelle.

| macOS | Architecture | Ce qui a été vérifié | Preuve | Statut |
|---|---|---|---|---|
| 15 (GitHub `macos-15`) | Apple Silicon (arm64) | suite de tests complète + invariant 50 000 fichiers | CI « CI macOS » à chaque envoi | ✅ moteur et interface (hors écran) |
| 15 (GitHub `macos-15-intel`) | Intel (x86_64) | idem | CI « CI macOS » à chaque envoi | ✅ moteur et interface (hors écran) |
| 15 (GitHub `macos-15`) | Apple Silicon | construction `.app`, signature ad hoc vérifiée, auto-diagnostic, DMG vérifié, application lancée depuis le DMG monté | run 42919451282 | ✅ |
| 15 (GitHub `macos-15-intel`) | Intel | idem | run 42919451282 | ✅ |
| Mac du propriétaire : iMac Retina 5K 27" fin 2015, macOS 12.7.6 Monterey | Intel (x86_64) | v1.2.0 : refus (Qt 6.12 exige macOS 14) ; v1.2.1 : application Apple Silicon ouverte par erreur — corrigé en v1.2.2 (universelle) | retours du propriétaire | ⏳ v1.2.2 à confirmer par le propriétaire |
| macOS 12 à 14 | Intel et Apple Silicon | **chaque binaire** de l'application exige au plus macOS 12.0 (`tools/verifier_minos.sh`, échec de la CI sinon) ; aucun Mac 12–14 disponible en CI (exécution non testée) | CI « Application macOS », fichier `minos.txt` | ⏳ lancement à confirmer sur le Mac du propriétaire |

Limites :
- Application **non notarisée** (pas de compte Apple Developer, Q-03) : ouverture par clic droit
  au premier lancement.
- **Universal2 produit depuis 1.2.2** : une seule application (x86_64 + arm64), testée sur les
  deux architectures.

Leçon (v1.2.0) : la version minimale **déclarée** (Info.plist) ne prouve rien. Les bibliothèques
Qt fournies par PySide6 6.10+ exigent macOS 13, et 6.12 exige macOS 14 : l'application 1.2.0 ne
s'ouvrait pas sur macOS 12. Depuis 1.2.1, PySide6 est limité à la branche 6.9 (macOS 12) et la
CI lit la version minimale réelle de chaque binaire Mach-O (`LC_BUILD_VERSION` / `minos`).

v1.2.1 → v1.2.2 : sur l'iMac Intel du propriétaire, l'application Apple Silicon (premier des deux
DMG) avait été ouverte : « n'est pas prise en charge sur ce Mac ». Le DMG Intel 1.2.1, examiné
binaire par binaire, était correct (x86_64, macOS ≤ 12.0). Depuis 1.2.2 : **une seule
application universelle** (x86_64 + arm64), construite avec le Python python.org universel et
testée sur les Mac GitHub `macos-15` (arm64) et `macos-15-intel` (x86_64) en exécution native.
