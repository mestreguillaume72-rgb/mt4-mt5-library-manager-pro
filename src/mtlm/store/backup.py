"""Sauvegarde et restauration de la base de l'application (spécification § 5, D-003).

* La sauvegarde utilise l'API de sauvegarde en ligne de SQLite (cohérente même
  pendant l'utilisation), écrit d'abord un fichier temporaire, vérifie son
  intégrité, puis lui donne son nom final. Une sauvegarde existante n'est jamais écrasée.
* La restauration vérifie la sauvegarde, sauvegarde d'abord la base actuelle,
  puis remplace son contenu.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from mtlm.core.clock import Clock
from mtlm.core.errors import BackupError
from mtlm.store.database import connect, integrity_ok, user_version

log = logging.getLogger("mtlm.store.backup")

BACKUP_SUFFIX = ".sqlite"


def _safe_label(label: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label)
    return cleaned.strip("-") or "sauvegarde"


def backup_database(conn: sqlite3.Connection, backups_dir: Path, clock: Clock, label: str) -> Path:
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = clock.now().strftime("%Y%m%dT%H%M%S%fZ")
    base = f"library-{stamp}-{_safe_label(label)}"
    final = backups_dir / f"{base}{BACKUP_SUFFIX}"
    counter = 1
    while final.exists():
        counter += 1
        final = backups_dir / f"{base}-{counter}{BACKUP_SUFFIX}"
    partial = final.with_name(final.name + ".partial")
    if partial.exists():
        partial.unlink()

    source_version = user_version(conn)
    try:
        dest = sqlite3.connect(partial)
        try:
            conn.backup(dest)
        finally:
            dest.close()
        check = sqlite3.connect(partial)
        try:
            if not integrity_ok(check):
                raise BackupError(f"Sauvegarde corrompue : {partial}")
            if user_version(check) != source_version:
                raise BackupError("Version de schéma différente dans la sauvegarde")
        finally:
            check.close()
        if final.exists():
            raise BackupError(f"Le fichier de sauvegarde existe déjà : {final}")
        partial.rename(final)
    except (sqlite3.Error, OSError) as exc:
        raise BackupError(f"La sauvegarde a échoué : {exc}") from exc
    finally:
        if partial.exists():
            partial.unlink()
    log.info("Sauvegarde créée : %s", final)
    return final


def inspect_backup(path: Path) -> int:
    """Vérifie qu'un fichier est une sauvegarde valide de l'application ; retourne sa version."""
    if not path.is_file():
        raise BackupError(f"Fichier de sauvegarde introuvable : {path}")
    try:
        conn = connect(path, read_only=True)
    except sqlite3.Error as exc:
        raise BackupError(f"Fichier illisible comme base SQLite : {exc}") from exc
    try:
        if not integrity_ok(conn):
            raise BackupError("La sauvegarde est corrompue (contrôle d'intégrité en échec)")
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration'"
        ).fetchone()
        if not has_table:
            raise BackupError("Ce fichier n'est pas une base de MT4 MT5 Library Manager PRO")
        return user_version(conn)
    except sqlite3.Error as exc:
        raise BackupError(f"Sauvegarde illisible : {exc}") from exc
    finally:
        conn.close()


def restore_database(
    backup_path: Path,
    database_path: Path,
    backups_dir: Path,
    clock: Clock,
    latest_version: int,
) -> Path | None:
    """Restaure ``backup_path`` dans ``database_path``.

    Retourne le chemin de la sauvegarde de sécurité de la base remplacée (ou ``None``
    s'il n'existait pas de base). Refuse une sauvegarde plus récente que l'application.
    """
    version = inspect_backup(backup_path)
    if version > latest_version:
        raise BackupError(
            f"La sauvegarde est en version de schéma {version}, plus récente que l'application "
            f"({latest_version}). Restauration refusée."
        )
    if backup_path.resolve() == database_path.resolve():
        raise BackupError("La sauvegarde et la base sont le même fichier")

    safety: Path | None = None
    if database_path.exists():
        current = connect(database_path)
        try:
            safety = backup_database(current, backups_dir, clock, "avant-restauration")
        finally:
            current.close()

    source = connect(backup_path, read_only=True)
    target = connect(database_path)
    try:
        source.backup(target)
        if not integrity_ok(target):
            raise BackupError("Base restaurée invalide ; la sauvegarde de sécurité est conservée")
    except sqlite3.Error as exc:
        raise BackupError(f"La restauration a échoué : {exc}") from exc
    finally:
        source.close()
        target.close()
    log.info("Base restaurée depuis %s", backup_path)
    return safety
