"""Connexion SQLite configurée pour la fiabilité.

* ``foreign_keys=ON`` : intégrité référentielle ;
* ``journal_mode=WAL`` : lecteurs concurrents pendant les écritures ;
* ``synchronous=FULL`` : durabilité maximale (journal d'audit, quarantaine) ;
* mode « autocommit » de Python désactivé au profit de transactions explicites
  (:func:`transaction`), pour maîtriser exactement ce qui est atomique.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

BUSY_TIMEOUT_MS = 5000


def connect(path: Path | str, *, read_only: bool = False) -> sqlite3.Connection:
    """Ouvre la base de l'application. ``read_only`` ouvre en lecture seule (URI ``mode=ro``)."""
    if read_only:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    else:
        conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    if not read_only:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transaction explicite ``BEGIN IMMEDIATE`` : tout ou rien.

    En cas d'exception, tout est annulé (``ROLLBACK``) puis l'exception est relancée.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def integrity_ok(conn: sqlite3.Connection) -> bool:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return row is not None and row[0] == "ok"


def user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0
