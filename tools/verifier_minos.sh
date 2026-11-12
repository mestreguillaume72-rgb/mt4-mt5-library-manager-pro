#!/bin/bash
# Vérifie qu'AUCUN binaire de l'application n'exige une version de macOS plus récente que la
# version minimale déclarée (LSMinimumSystemVersion). Sans cette preuve, une bibliothèque
# compilée pour un macOS récent empêcherait l'ouverture sur un Mac plus ancien.
# Avec REQUIRED_ARCHS="x86_64 arm64", vérifie aussi que chaque binaire contient ces architectures
# (application universelle : une seule application pour les Mac Intel et Apple Silicon).
# Usage (sur macOS) : tools/verifier_minos.sh "dist/MT4 MT5 Library Manager PRO.app"
set -euo pipefail
APP="$1"
DECLARED="$(plutil -extract LSMinimumSystemVersion raw "$APP/Contents/Info.plist")"
echo "Version minimale déclarée : macOS $DECLARED"

greater() {  # greater 13.0 12.0 -> vrai si $1 > $2
    awk -v a="$1" -v b="$2" 'BEGIN { split(a, x, "."); split(b, y, ".");
        for (i = 1; i <= 3; i++) { if (x[i] + 0 > y[i] + 0) exit 0; if (x[i] + 0 < y[i] + 0) exit 1 }
        exit 1 }'
}

checked=0
bad=0
highest="0"
while IFS= read -r -d '' file; do
    file -b "$file" | grep -q "Mach-O" || continue
    # minos (LC_BUILD_VERSION) ou version (LC_VERSION_MIN_MACOSX), toutes architectures.
    versions="$(otool -arch all -l "$file" 2>/dev/null | awk '
        /cmd LC_BUILD_VERSION/ { mode = 1 } /cmd LC_VERSION_MIN_MACOSX/ { mode = 2 }
        mode == 1 && $1 == "minos" { print $2; mode = 0 }
        mode == 2 && $1 == "version" { print $2; mode = 0 }')"
    checked=$((checked + 1))
    for wanted in ${REQUIRED_ARCHS:-}; do
        if ! lipo -archs "$file" 2>/dev/null | tr ' ' '\n' | grep -qx "$wanted"; then
            echo "ARCHITECTURE MANQUANTE : ${file#"$APP"/} n'a pas $wanted ($(lipo -archs "$file"))"
            bad=$((bad + 1))
        fi
    done
    for v in $versions; do
        if greater "$v" "$highest"; then highest="$v"; fi
        if greater "$v" "$DECLARED"; then
            echo "TROP RÉCENT : ${file#"$APP"/} exige macOS $v"
            bad=$((bad + 1))
        fi
    done
done < <(find "$APP" -type f -print0)

echo "$checked binaire(s) Mach-O vérifié(s) ; exigence la plus haute : macOS $highest"
if [ "$checked" -eq 0 ]; then
    echo "Aucun binaire trouvé : vérification impossible."
    exit 1
fi
if [ "$bad" -gt 0 ]; then
    echo "ÉCHEC : $bad problème(s) de compatibilité (macOS $DECLARED${REQUIRED_ARCHS:+, architectures $REQUIRED_ARCHS})."
    exit 1
fi
echo "OK : tous les binaires fonctionnent à partir de macOS $DECLARED${REQUIRED_ARCHS:+ (architectures : $REQUIRED_ARCHS)}."
