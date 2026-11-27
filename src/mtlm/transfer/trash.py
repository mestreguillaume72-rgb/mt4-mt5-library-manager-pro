"""Mise à la **Corbeille** (Mac ou Windows) et remise en place (décision du propriétaire,
1.3.0 ; Windows depuis 1.8.0).

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

Sur Windows, ``SHFileOperationW`` (``shell32.dll``, avec annulation possible) envoie le
fichier dans la Corbeille de Windows ; ``kernel32.dll`` sert seulement à refuser les disques
réseau, qui n'ont pas de Corbeille (le fichier serait effacé pour de bon). Le fichier mis à
la Corbeille est retrouvé dans ``$Recycle.Bin`` pour permettre « Remettre en place ».
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

#: Bibliothèques système de Windows (jamais un fichier de l'utilisateur).
SHELL32 = "shell32.dll"
KERNEL32 = "kernel32.dll"
#: Emplacement inconnu dans la Corbeille de Windows : remise en place par l'Explorateur.
WINDOWS_UNKNOWN = b"?corbeille-windows"

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


def _recycled_location(original: str, drive: str) -> bytes:
    """Fichier ``$R…`` de la Corbeille de Windows qui correspond à ``original`` (le plus
    récent), d'après son fichier d'information ``$I…`` ; sinon :data:`WINDOWS_UNKNOWN`."""
    base = os.path.join(drive + "\\", "$Recycle.Bin")
    best: tuple[float, str] | None = None
    try:
        owners = [os.path.join(base, d) for d in os.listdir(base)]
    except OSError:
        return WINDOWS_UNKNOWN
    wanted = os.path.normcase(os.path.normpath(original))
    for owner in owners:
        try:
            names = [n for n in os.listdir(owner) if n.startswith("$I")]
        except OSError:
            continue
        for name in names:
            info = os.path.join(owner, name)
            try:
                with open(info, "rb") as handle:
                    data = handle.read(65536)
                mtime = os.stat(info).st_mtime
            except OSError:
                continue
            version = int.from_bytes(data[:8], "little")
            if version == 2:
                length = int.from_bytes(data[24:28], "little")
                path = data[28 : 28 + 2 * length].decode("utf-16-le", "replace")
            else:
                path = data[24 : 24 + 520].decode("utf-16-le", "replace")
            path = path.split("\x00", 1)[0]
            if os.path.normcase(os.path.normpath(path)) != wanted:
                continue
            recycled = os.path.join(owner, "$R" + name[2:])
            if os.path.lexists(recycled) and (best is None or mtime > best[0]):
                best = (mtime, recycled)
    return os.fsencode(best[1]) if best else WINDOWS_UNKNOWN


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


_FO_DELETE = 3
_FOF_SILENT, _FOF_NOCONFIRMATION, _FOF_ALLOWUNDO, _FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
_FOF_WANTNUKEWARNING = 0x4000
_DRIVE_REMOTE = 4


def windows_trash(path: bytes) -> bytes:
    """Met ``path`` dans la Corbeille de Windows ; retourne son chemin dans la Corbeille (ou
    :data:`WINDOWS_UNKNOWN` s'il n'a pas pu être retrouvé)."""
    text = os.path.abspath(os.fsdecode(path))
    if not os.path.isabs(os.fsdecode(path)):
        raise TrashError("chemin relatif refusé")
    if not os.path.lexists(text):
        raise TrashError("fichier absent")
    drive = os.path.splitdrive(text)[0]
    kernel = ctypes.WinDLL(KERNEL32)  # type: ignore[attr-defined]
    if not drive or drive.startswith("\\\\") or kernel.GetDriveTypeW(drive + "\\") == _DRIVE_REMOTE:
        raise TrashError("disque réseau : Windows n'a pas de Corbeille pour ce disque")
    shell = ctypes.WinDLL(SHELL32)  # type: ignore[attr-defined]
    operation = _SHFILEOPSTRUCTW()
    operation.wFunc = _FO_DELETE
    operation.pFrom = text + "\x00"  # liste terminée par un double zéro
    operation.fFlags = (
        _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI | _FOF_WANTNUKEWARNING
    )
    code = shell.SHFileOperationW(ctypes.byref(operation))
    if code != 0 or operation.fAnyOperationsAborted or os.path.lexists(text):
        raise TrashError(f"la Corbeille de Windows a refusé ce fichier (code {code})")
    return _recycled_location(text, drive)


def default_backend() -> TrashBackend | None:
    """La Corbeille du Mac ou de Windows ; ``None`` ailleurs (jamais simulée)."""
    if sys.platform == "darwin":
        return macos_trash
    if sys.platform == "win32":
        return windows_trash
    return None


def put_back(trashed: bytes, original: bytes) -> None:
    """Remet un fichier de la Corbeille à son emplacement d'origine, **sans écraser** : refus
    si l'emplacement d'origine est occupé ou si le fichier n'est plus dans la Corbeille."""
    if trashed == WINDOWS_UNKNOWN:
        raise TrashError(
            "ouvrez la Corbeille de Windows, clic droit sur le fichier → « Restaurer »"
        )
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
    # Windows : la fiche « $I… » qui accompagne « $R… » dans la Corbeille est retirée aussi.
    folder, name = os.path.split(trashed)
    if name.startswith(b"$R"):
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(folder, b"$I" + name[2:]))
