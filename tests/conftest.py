"""Configuration commune des tests.

* Aucun accès réseau : toute tentative de connexion échoue (spécification § 6 :
  pas de télémétrie ni de transfert).
* Chaque test utilise un dossier d'application temporaire (``MTLM_HOME``) : les tests
  ne touchent jamais aux vraies données de l'utilisateur.
"""

from __future__ import annotations

import socket
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths, default_paths
from mtlm.store.database import connect

ConnectDb = Callable[[Path], sqlite3.Connection]


class NetworkAccessError(RuntimeError):
    pass


def _refuse(*_args: Any, **_kwargs: Any) -> Any:
    raise NetworkAccessError("Accès réseau interdit pendant les tests")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)
    yield


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC))


@pytest.fixture
def app_home(tmp_path: Path) -> Path:
    return tmp_path / "mtlm-home"


@pytest.fixture
def environ(app_home: Path) -> dict[str, str]:
    return {"MTLM_HOME": str(app_home)}


@pytest.fixture
def paths(environ: dict[str, str]) -> AppPaths:
    return default_paths(environ)


@pytest.fixture
def connect_db() -> Iterator[ConnectDb]:
    """Ouvre des connexions SQLite qui seront toutes fermées à la fin du test."""
    opened: list[sqlite3.Connection] = []

    def _open(path: Path) -> sqlite3.Connection:
        conn = connect(path)
        opened.append(conn)
        return conn

    yield _open
    for conn in opened:
        conn.close()
