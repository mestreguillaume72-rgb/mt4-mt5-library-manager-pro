#!/bin/bash
# Installation de MT4 MT5 Library Manager PRO — double-cliquez sur ce fichier.
#
# Ce que fait ce script, et rien d'autre :
#   1. prend l'image d'installation (application universelle : Intel et Apple Silicon) et
#      vérifie qu'elle convient au processeur et à la version de macOS de ce Mac ;
#   2. vérifie son empreinte SHA-256 (fichier intact) ;
#   3. copie l'application dans le dossier Applications (une ancienne version de CETTE
#      application est remplacée ; vos données et réglages, rangés ailleurs, sont conservés) ;
#   4. retire l'avertissement « téléchargé d'Internet » de CETTE application uniquement ;
#   5. ouvre l'application.
# Il ne touche à aucun autre fichier, et jamais à vos fichiers MetaTrader.
#
# Variables pour les tests automatiques : MTLM_INSTALL_DIR (dossier de destination),
# MTLM_NO_LAUNCH=1 (ne pas ouvrir l'application), MTLM_NO_PAUSE=1 (ne pas attendre Entrée).
# MTLM_FAKE_OS_VERSION / MTLM_FAKE_CPU (simuler un autre Mac pour tester les refus).
set -euo pipefail

APP_NAME="MT4 MT5 Library Manager PRO"
APP="${APP_NAME}.app"
BUNDLE_ID="fr.mtlm.library-manager-pro"
HERE="$(cd "$(dirname "$0")" && pwd)"
FILES="${HERE}/Fichiers d'installation"
MNT=""

finish() {
    local code=$?
    if [ -n "$MNT" ] && [ -d "$MNT" ]; then
        hdiutil detach -quiet "$MNT" >/dev/null 2>&1 || true
        rmdir "$MNT" 2>/dev/null || true
    fi
    echo
    if [ "$code" -eq 0 ]; then
        echo "✅  Installation terminée. Vous pouvez fermer cette fenêtre."
    else
        echo "❌  L'installation n'a pas abouti (rien n'a été modifié sur vos fichiers)."
        echo "    Suivez la méthode manuelle du « Guide d'installation.pdf »."
    fi
    if [ "${MTLM_NO_PAUSE:-0}" != "1" ]; then
        read -r -p "Appuyez sur Entrée pour fermer… " _ || true
    fi
    exit "$code"
}
trap finish EXIT

echo "=== Installation de ${APP_NAME} ==="
echo

# 1. Type de Mac (hw.optional.arm64 reste juste même si le Terminal tourne sous Rosetta).
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ]; then
    KIND="Apple-Silicon"
    CPU="arm64"
    echo "• Mac détecté : Apple Silicon (puce M1, M2, M3, M4…)"
else
    KIND="Intel"
    CPU="x86_64"
    echo "• Mac détecté : processeur Intel"
fi
CPU="${MTLM_FAKE_CPU:-$CPU}"

# Image universelle (…-macOS.dmg) ; à défaut, ancienne image propre à ce type de Mac.
DMG=""
for candidate in "$FILES"/*-macOS.dmg "$FILES"/*-macOS-"${KIND}".dmg; do
    if [ -z "$DMG" ] && [ -f "$candidate" ]; then DMG="$candidate"; fi
done
if [ -z "$DMG" ]; then
    echo "Image d'installation introuvable pour ce Mac dans « Fichiers d'installation »."
    exit 1
fi
echo "• Fichier utilisé : $(basename "$DMG")"

# 2. Intégrité.
if [ -f "${DMG}.sha256" ]; then
    expected="$(awk '{print $1}' "${DMG}.sha256")"
    actual="$(shasum -a 256 "$DMG" | awk '{print $1}')"
    if [ "$expected" != "$actual" ]; then
        echo "Le fichier d'installation est abîmé (empreinte différente). Retéléchargez le dossier."
        exit 1
    fi
    echo "• Fichier vérifié : intact"
fi

# 3. Copie dans Applications.
DEST="${MTLM_INSTALL_DIR:-/Applications}"
if [ ! -w "$DEST" ]; then
    DEST="${HOME}/Applications"
    mkdir -p "$DEST"
    echo "• Dossier Applications protégé : installation dans votre dossier personnel ($DEST)"
fi

MNT="$(mktemp -d "${TMPDIR:-/tmp}/mtlm-install.XXXXXX")"
hdiutil attach -nobrowse -readonly -noautoopen -mountpoint "$MNT" "$DMG" >/dev/null
if [ ! -d "$MNT/$APP" ]; then
    echo "Application absente de l'image d'installation."
    exit 1
fi

# Version de macOS : refus clair AVANT toute copie si ce Mac est trop ancien.
version_ge() {  # version_ge 12.7.6 12.0 -> vrai si $1 >= $2
    awk -v a="$1" -v b="$2" 'BEGIN { split(a, x, "."); split(b, y, ".");
        for (i = 1; i <= 3; i++) { if (x[i] + 0 > y[i] + 0) exit 0; if (x[i] + 0 < y[i] + 0) exit 1 }
        exit 0 }'
}
OS_VERSION="${MTLM_FAKE_OS_VERSION:-$(sw_vers -productVersion)}"
MIN_VERSION="$(/usr/libexec/PlistBuddy -c "Print :LSMinimumSystemVersion" \
    "$MNT/$APP/Contents/Info.plist" 2>/dev/null || echo 0)"
if ! version_ge "$OS_VERSION" "$MIN_VERSION"; then
    echo "Ce Mac a macOS ${OS_VERSION} ; cette application demande macOS ${MIN_VERSION} ou plus récent."
    echo "Rien n'a été installé."
    exit 1
fi
echo "• macOS ${OS_VERSION} : compatible (minimum ${MIN_VERSION})"

# Processeur : l'application doit contenir le code de CE Mac (sinon macOS dirait « n'est pas
# prise en charge sur ce Mac »). « file » est présent sur tous les Mac, sans outils Xcode.
APP_CPUS="$(file -b "$MNT/$APP/Contents/MacOS/mtlm-gui")"
case "$APP_CPUS" in
    *"$CPU"*) ;;
    *)
        echo "Cette image ne contient pas l'application pour ce Mac (${KIND}) : ${APP_CPUS}."
        echo "Rien n'a été installé. Retéléchargez le dossier d'installation le plus récent."
        exit 1
        ;;
esac
echo "• Processeur : compatible (${CPU})"

if [ -e "$DEST/$APP" ]; then
    existing_id="$(/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" \
        "$DEST/$APP/Contents/Info.plist" 2>/dev/null || true)"
    if [ "$existing_id" != "$BUNDLE_ID" ]; then
        echo "Un autre élément nommé « $APP » existe déjà dans $DEST : je n'y touche pas."
        exit 1
    fi
    osascript -e "if application \"${APP_NAME}\" is running then tell application \"${APP_NAME}\" to quit" \
        >/dev/null 2>&1 || true
    rm -rf "${DEST:?}/$APP"
    echo "• Ancienne version remplacée (vos données et réglages sont conservés)"
fi

ditto "$MNT/$APP" "$DEST/$APP"
echo "• Application copiée dans : $DEST"

# 4. Autoriser l'ouverture de cette application (non notarisée par Apple).
xattr -dr com.apple.quarantine "$DEST/$APP" 2>/dev/null || true
codesign --verify --deep --strict "$DEST/$APP"
echo "• Application vérifiée et autorisée"

# 5. Lancement.
if [ "${MTLM_NO_LAUNCH:-0}" != "1" ]; then
    open "$DEST/$APP"
    echo "• Application ouverte"
fi
