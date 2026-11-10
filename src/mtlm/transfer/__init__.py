"""SEUL module autorisé à écrire des fichiers hors des dossiers de l'application (S-04, D-007).

Il n'écrit que dans des destinations choisies par l'utilisateur, **distinctes des sources**,
et uniquement après simulation et confirmation (la vérification est faite par les services).
Il ne modifie, ne déplace et ne supprime jamais un fichier source.
"""
