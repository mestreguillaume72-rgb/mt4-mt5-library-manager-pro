"""Erreurs typées de l'application.

Chaque erreur porte un message destiné à l'utilisateur (en français simple)
et reste exploitable par le code (type, attributs).
"""


class MtlmError(Exception):
    """Erreur de base de l'application."""


class StoreError(MtlmError):
    """Erreur liée à la base de données locale."""


class MigrationError(StoreError):
    """Une migration n'a pas pu être appliquée ; la base est restée dans son état précédent."""


class MigrationIntegrityError(StoreError):
    """Une migration déjà appliquée a été modifiée depuis son application."""


class DatabaseTooNewError(StoreError):
    """La base a été créée par une version plus récente de l'application."""


class BackupError(StoreError):
    """La sauvegarde de la base a échoué ou n'a pas pu être vérifiée."""


class AuditError(MtlmError):
    """Erreur du journal d'audit."""


class ExportError(MtlmError):
    """Un export n'a pas pu être écrit."""
