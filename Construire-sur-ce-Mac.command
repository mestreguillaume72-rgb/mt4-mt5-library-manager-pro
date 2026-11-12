#!/bin/bash
# Construit MT4 MT5 Library Manager PRO directement sur CE Mac, sans GitHub.
# Double-cliquez sur ce fichier (la première fois : clic droit → Ouvrir → Ouvrir).
#
# Ce que fait ce script, dans le dossier du projet uniquement :
#   1. vérifie la version de macOS (12 Monterey ou plus récent) ;
#   2. installe si besoin l'outil « uv » (Astral) dans votre dossier personnel, sans droits
#      administrateur ; uv télécharge ensuite Python et les bibliothèques exactes du projet
#      (fichier uv.lock) — connexion Internet nécessaire la première fois ;
#   3. construit l'application pour ce Mac (Intel ou Apple Silicon) ;
#   4. la teste (auto-diagnostic : 13 écrans, analyse complète d'un dossier de test) ;
#   5. crée l'image d'installation .dmg dans le dossier « dist » ;
#   6. propose de l'installer dans Applications.
# Il ne touche jamais à vos fichiers MetaTrader.
#
# Options (variables d'environnement) : MTLM_TESTS=1 lance aussi les 400+ tests ;
# MTLM_NO_INSTALL=1 n'installe pas ; MTLM_NO_PAUSE=1 ne demande rien (tests automatiques) ;
# MTLM_UV_DOWNLOAD=1 télécharge uv même s'il est déjà présent.
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
APP_NAME="MT4 MT5 Library Manager PRO"
APP="dist/${APP_NAME}.app"
BUNDLE_ID="fr.mtlm.library-manager-pro"
LOG="$ROOT/construction-locale.log"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

pause() {
    if [ "${MTLM_NO_PAUSE:-0}" != "1" ]; then
        read -r -p "Appuyez sur Entrée pour fermer… " _ || true
    fi
}

finish() {
    local code=$?
    echo
    if [ "$code" -eq 0 ]; then
        echo "✅  Terminé. Application : ${ROOT}/${APP}"
    else
        echo "❌  La construction s'est arrêtée (étape ci-dessus). Vos fichiers MetaTrader ne"
        echo "    sont pas concernés. Le détail est dans : ${LOG}"
    fi
    pause
    exit "$code"
}
trap finish EXIT

step() { echo; echo "▶ $*"; }

echo "=== Construction de ${APP_NAME} sur ce Mac ==="

# 1. Vérifications
step "Vérification du Mac"
if [ ! -f pyproject.toml ] || [ ! -f packaging/macos/mtlm.spec ]; then
    echo "Ce fichier doit rester dans le dossier du projet (avec pyproject.toml)."
    exit 1
fi
OS_VERSION="$(sw_vers -productVersion)"
MAJOR="${OS_VERSION%%.*}"
echo "macOS ${OS_VERSION}, processeur $(uname -m)"
if [ "$MAJOR" -lt 12 ]; then
    echo "macOS 12 Monterey ou plus récent est nécessaire."
    exit 1
fi

# 2. Outil uv (installé dans votre dossier personnel, sans droits administrateur)
step "Outil de construction « uv »"
UV="$(command -v uv || true)"
if [ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ]; then
    UV="$HOME/.local/bin/uv"
fi
if [ -z "$UV" ] || [ "${MTLM_UV_DOWNLOAD:-0}" = "1" ]; then
    echo "Téléchargement de uv (https://astral.sh/uv)…"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
    UV="$HOME/.local/bin/uv"
fi
"$UV" --version

# 3. Python et bibliothèques exactes du projet
step "Python et bibliothèques (versions verrouillées)"
if [ "${MTLM_TESTS:-0}" = "1" ]; then
    "$UV" sync --frozen --all-groups
else
    "$UV" sync --frozen --group build
fi

if [ "${MTLM_TESTS:-0}" = "1" ]; then
    step "Tests complets (quelques minutes)"
    QT_QPA_PLATFORM=offscreen "$UV" run pytest -q
fi

# 4. Icône et application
step "Icône de l'application"
rm -rf packaging/macos/AppIcon.iconset
"$UV" run python tools/icone.py packaging/macos/AppIcon.iconset
iconutil -c icns packaging/macos/AppIcon.iconset -o packaging/macos/AppIcon.icns

step "Construction de l'application pour ce Mac"
rm -rf build "$APP"
"$UV" run --group build pyinstaller --noconfirm packaging/macos/mtlm.spec
codesign --verify --deep --strict "$APP"

# 5. Auto-diagnostic
step "Auto-diagnostic de l'application"
QT_QPA_PLATFORM=offscreen "$APP/Contents/MacOS/mtlm-gui" --autotest "$APP/Contents"

# 6. Image d'installation
step "Image d'installation (.dmg)"
VERSION="$("$UV" run python -c "import mtlm; print(mtlm.__version__)")"
DMG="dist/MT4-MT5-Library-Manager-PRO-${VERSION}-macOS-ce-Mac.dmg"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/mtlm-dmg.XXXXXX")"
ditto "$APP" "$STAGE/${APP_NAME}.app"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -quiet -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
echo "Image créée : ${ROOT}/${DMG}"

# 7. Installation (sur demande)
if [ "${MTLM_NO_INSTALL:-0}" = "1" ] || [ "${MTLM_NO_PAUSE:-0}" = "1" ]; then
    exit 0
fi
step "Installation"
read -r -p "Installer maintenant dans Applications (remplace l'ancienne version) ? [o/N] " answer
case "$answer" in
    o | O | oui | OUI) ;;
    *)
        echo "Non installé. Vous pourrez ouvrir l'image .dmg plus tard."
        exit 0
        ;;
esac
DEST="/Applications"
[ -w "$DEST" ] || DEST="$HOME/Applications"
mkdir -p "$DEST"
if [ -e "$DEST/${APP_NAME}.app" ]; then
    existing="$(/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" \
        "$DEST/${APP_NAME}.app/Contents/Info.plist" 2>/dev/null || true)"
    if [ "$existing" != "$BUNDLE_ID" ]; then
        echo "Un autre élément nommé « ${APP_NAME}.app » existe dans $DEST : je n'y touche pas."
        exit 1
    fi
    rm -rf "${DEST:?}/${APP_NAME}.app"
fi
ditto "$APP" "$DEST/${APP_NAME}.app"
echo "Installée dans $DEST (vos données et réglages sont conservés)."
open "$DEST/${APP_NAME}.app"
