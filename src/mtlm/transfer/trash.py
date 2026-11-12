"""Mise à la **Corbeille du Mac** et remise en place (décision du propriétaire, 1.3.0).

Seul endroit de l'application qui retire un fichier d'une bibliothèque. Il ne décide de rien :
les vérifications (copie identique conservée, fichier inchangé depuis l'analyse, confirmation
de l'utilisateur) sont faites avant par :mod:`mtlm.app.deletion`.

Sur macOS, l'API officielle d'Apple ``NSFileManager.trashItemAtURL`` est appelée : le fichier
part dans la Corbeille du bon disque (Corbeille personnelle ou ``.Trashes`` d'un disque
externe) et reste récupérable tant que la Corbeille n'est pas vidée (Finder : « Remettre »).
Pour l'appeler sans dépendance supplémentaire, ``ctypes`` charge **uniquement** deux
bibliothèques système d'Apple (``libobjc`` et ``Foundation``) : exception unique et
documentée à la règle « aucun chargement de bibliothèque » (DECISIONS D-016, test statique).
Aucun fichier de l'utilisateur (DLL, EX4…) n'est jamais chargé ni exécuté.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
from collections.abc import Callable
from typing import Any

from mtlm.core.errors import MtlmError

#: Les deux seules bibliothèques chargées (système Apple, chemins absolus fixes).
LIBOBJC = "/usr/lib/libobjc.A.dylib"
FOUNDATION = "/System/Library/Frameworks/Foundation.framework/Foundation"

#: Fonction de mise à la Corbeille : chemin d'origine → chemin dans la Corbeille.
TrashBackend = Callable[[bytes], bytes]


class TrashError(MtlmError):
    """Mise à la Corbeille ou remise en place impossible ; le fichier n'a pas bougé."""


class _ObjC:
    """Accès minimal au runtime Objective-C (prototypes exacts, compatibles arm64)."""

    def __init__(self) -> None:
        self.lib = ctypes.CDLL(LIBOBJC)
        ctypes.CDLL(FOUNDATION)  # enregistre les classes NSFileManager, NSURL…
        self.lib.objc_getClass.restype = ctypes.c_void_p
        self.lib.objc_getClass.argtypes = [ctypes.c_char_p]
        self.lib.sel_registerName.restype = ctypes.c_void_p
        self.lib.sel_registerName.argtypes = [ctypes.c_char_p]
        self.lib.objc_autoreleasePoolPush.restype = ctypes.c_void_p
        self.lib.objc_autoreleasePoolPop.argtypes = [ctypes.c_void_p]
        self._send_address = int(ctypes.cast(self.lib.objc_msgSend, ctypes.c_void_p).value or 0)

    def send(self, restype: Any, *argtypes: Any) -> Callable[..., Any]:
        prototype = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
        return prototype(self._send_address)

    def cls(self, name: bytes) -> int:
        return int(self.lib.objc_getClass(name) or 0)

    def sel(self, name: bytes) -> int:
        return int(self.lib.sel_registerName(name))


_objc: _ObjC | None = None


def _runtime() -> _ObjC:
    global _objc
    if _objc is None:
        _objc = _ObjC()
    return _objc


def _nsstring_text(rt: _ObjC, nsstring: int | None) -> str:
    if not nsstring:
        return ""
    raw = rt.send(ctypes.c_char_p)(nsstring, rt.sel(b"UTF8String"))
    return bytes(raw).decode("utf-8", "replace") if raw else ""


def macos_trash(path: bytes) -> bytes:
    """Met ``path`` à la Corbeille via NSFileManager ; retourne son chemin dans la Corbeille."""
    if not os.path.isabs(path):
        raise TrashError("chemin relatif refusé")
    rt = _runtime()
    pool = rt.lib.objc_autoreleasePoolPush()
    try:
        url = rt.send(ctypes.c_void_p, ctypes.c_char_p, ctypes.c_bool, ctypes.c_void_p)(
            rt.cls(b"NSURL"),
            rt.sel(b"fileURLWithFileSystemRepresentation:isDirectory:relativeToURL:"),
            path,
            False,
            None,
        )
        manager = rt.send(ctypes.c_void_p)(rt.cls(b"NSFileManager"), rt.sel(b"defaultManager"))
        resulting = ctypes.c_void_p()
        error = ctypes.c_void_p()
        ok = rt.send(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        )(
            manager,
            rt.sel(b"trashItemAtURL:resultingItemURL:error:"),
            url,
            ctypes.byref(resulting),
            ctypes.byref(error),
        )
        if not ok:
            description = rt.send(ctypes.c_void_p)(error.value, rt.sel(b"localizedDescription"))
            raise TrashError(_nsstring_text(rt, description) or "la Corbeille a refusé ce fichier")
        location = rt.send(ctypes.c_char_p)(resulting.value, rt.sel(b"fileSystemRepresentation"))
        if not location:
            raise TrashError("emplacement dans la Corbeille inconnu")
        return bytes(location)
    finally:
        rt.lib.objc_autoreleasePoolPop(pool)


def default_backend() -> TrashBackend | None:
    """La Corbeille du Mac ; ``None`` ailleurs (fonction indisponible, jamais simulée)."""
    return macos_trash if sys.platform == "darwin" else None


def put_back(trashed: bytes, original: bytes) -> None:
    """Remet un fichier de la Corbeille à son emplacement d'origine, **sans écraser** : refus
    si l'emplacement d'origine est occupé ou si le fichier n'est plus dans la Corbeille."""
    if not os.path.lexists(trashed):
        raise TrashError("le fichier n'est plus dans la Corbeille (Corbeille vidée ?)")
    if os.path.lexists(original):
        raise TrashError("un fichier occupe déjà l'emplacement d'origine : rien n'est écrasé")
    parent = os.path.dirname(original)
    if not os.path.isdir(parent):
        raise TrashError("le dossier d'origine n'existe plus")
    try:
        os.link(trashed, original)  # échoue si la cible existe : aucun écrasement possible
    except OSError as exc:
        raise TrashError(f"remise en place impossible : {exc.strerror or exc}") from exc
    # Le fichier est en place ; s'il restait aussi dans la Corbeille, ce serait sans effet.
    with contextlib.suppress(OSError):
        os.unlink(trashed)
