"""Interface graphique PySide6 (F11). Aucune logique métier : chaque action appelle un service
de :mod:`mtlm.app`. Tous les boutons passent par le registre d'actions (:mod:`mtlm.ui.base`),
ce qui permet aux tests de vérifier qu'aucun bouton n'est décoratif."""
