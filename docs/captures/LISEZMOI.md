# Captures d'écran

Captures de l'application **réelle** (pas une maquette), produites automatiquement par
`tools/captures.py` après une analyse complète d'un **corpus synthétique FICTIF** de 1 500
fichiers (aucun vrai robot, aucun vrai SET).

Elles sont rendues sous Linux (Qt hors écran) : sur macOS, l'aspect sera natif (polices et
style du système), mais les écrans, les boutons et les données sont les mêmes.

Régénérer : `QT_QPA_PLATFORM=offscreen PYTHONPATH=. uv run python tools/captures.py docs/captures`
