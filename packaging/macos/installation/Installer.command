#!/bin/bash
# Installation de MT4 MT5 Library Manager PRO — double-cliquez sur ce fichier.
#
# Ce que fait ce script, et rien d'autre :
#   1. choisit l'image d'installation adaptée à ce Mac (Apple Silicon ou Intel) ;
#   2. vérifie son empreinte SHA-256 (fichier intact) ;
#   3. copie l'application dans le dossier Applications (une ancienne version de CETTE
#      application est remplacée ; vos données et réglages, rangés ailleurs, sont conservés) ;
#   4. retire l'avertissement « téléchargé d'Internet » de CETTE application uniquement ;
#   5. ouvre l'application.
# Il ne touche à aucun autre fichier, et jamais à vos fichiers MetaTrader.
#
# Variables pour les tests automatiques : MTLM_INSTALL_DIR (dossier de destination),
# MTLM_NO_LAUNCH=1 (ne pas ouvrir l'application), MTLM_NO_PAUSE=1 (ne pas attendre Entrée).
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
    echo "• Mac détecté : Apple Silicon (puce M1, M2, M3, M4…)"
else
    KIND="Intel"
    echo "• Mac détecté : processeur Intel"
fi

DMG=""
for candidate in "$FILES"/*-macOS-"${KIND}".dmg; do
    [ -f "$candidate" ] && DMG="$candidate"
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

if [ -e "$DEST/$APP" ]; then
    existing_id="$(plutil -extract CFBundleIdentifier raw "$DEST/$APP/Contents/Info.plist" \
        2>/dev/null || true)"
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
