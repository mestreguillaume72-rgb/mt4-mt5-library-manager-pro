"""Contrôle des tâches longues : pause, reprise, annulation (F11, F12).

Les moteurs appellent :meth:`TaskControl.checkpoint` entre deux éléments : la pause
bloque à cet endroit, l'annulation lève :class:`Cancelled`. Un élément en cours n'est
donc jamais interrompu au milieu : l'état reste toujours cohérent.
"""

from __future__ import annotations

import threading


class Cancelled(Exception):  # noqa: N818 — nom métier volontaire
    """La tâche a été annulée par l'utilisateur."""


class TaskControl:
    def __init__(self) -> None:
        self._cancel = threading.Event()
        self._running = threading.Event()
        self._running.set()

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._running.set()  # libère une tâche en pause pour qu'elle constate l'annulation

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def checkpoint(self) -> None:
        """Point d'arrêt sûr : attend si en pause, lève :class:`Cancelled` si annulée."""
        self._running.wait()
        if self._cancel.is_set():
            raise Cancelled
