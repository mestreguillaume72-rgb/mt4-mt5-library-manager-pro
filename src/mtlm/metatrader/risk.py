"""Signes de risque dans les fichiers (1.5.0) — **analyse locale, ce n'est pas un antivirus**.

On cherche, en lisant seulement les octets ou le texte (jamais d'exécution, aucun envoi sur
Internet), ce qu'un fichier MetaTrader **pourrait** faire de dangereux :

* fonctions Windows appelées par un robot ou une DLL : téléchargement, lancement de
  programmes, effacement de fichiers, registre, espionnage du clavier, injection ;
* programmes et scripts (``.exe``, ``.bat``, ``.vbs``…) ou fichiers déguisés sous une fausse
  extension.

Un signe de risque n'est **pas** une preuve de virus : beaucoup d'outils honnêtes utilisent
Internet ou une DLL. C'est une liste de fichiers à regarder de plus près.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Fonction Windows → (niveau, explication). « élevé » : rarement nécessaire à un robot.
DANGEROUS_FUNCTIONS: dict[str, tuple[str, str]] = {
    "URLDownloadToFile": ("élevé", "télécharge un fichier depuis Internet"),
    "ShellExecute": ("élevé", "lance un programme ou ouvre un fichier"),
    "WinExec": ("élevé", "lance un programme"),
    "CreateProcess": ("élevé", "lance un programme"),
    "WriteProcessMemory": ("élevé", "écrit dans la mémoire d'un autre programme (injection)"),
    "CreateRemoteThread": ("élevé", "agit dans un autre programme (injection)"),
    "VirtualAllocEx": ("élevé", "réserve de la mémoire dans un autre programme (injection)"),
    "SetWindowsHookEx": ("élevé", "intercepte le clavier ou la souris"),
    "GetAsyncKeyState": ("élevé", "lit les touches du clavier"),
    "RegSetValue": ("à surveiller", "modifie le registre de Windows"),
    "RegCreateKey": ("à surveiller", "modifie le registre de Windows"),
    "DeleteFile": ("à surveiller", "efface des fichiers"),
    "RemoveDirectory": ("à surveiller", "efface des dossiers"),
    "MoveFileEx": ("à surveiller", "déplace ou remplace des fichiers"),
    "InternetOpen": ("à surveiller", "accède à Internet"),
    "InternetOpenUrl": ("à surveiller", "accède à Internet"),
    "HttpSendRequest": ("à surveiller", "envoie des données sur Internet"),
    "WinHttpOpen": ("à surveiller", "accède à Internet"),
    "WSAStartup": ("à surveiller", "ouvre des connexions réseau"),
}
#: DLL de Windows dont l'import signale un accès à Internet ou au système.
SENSITIVE_DLLS: dict[str, tuple[str, str]] = {
    "urlmon.dll": ("à surveiller", "bibliothèque Windows de téléchargement"),
    "wininet.dll": ("à surveiller", "bibliothèque Windows d'accès à Internet"),
    "winhttp.dll": ("à surveiller", "bibliothèque Windows d'accès à Internet"),
    "ws2_32.dll": ("à surveiller", "bibliothèque Windows de réseau"),
    "shell32.dll": ("à surveiller", "bibliothèque Windows qui peut lancer des programmes"),
}
#: Fonction MQL normale mais à connaître.
MQL_INFO: dict[str, str] = {
    "WebRequest": "envoie ou reçoit des données sur Internet (fonction MQL)",
    "SendFTP": "envoie des fichiers par FTP",
    "SendMail": "envoie des e-mails",
}
EXECUTABLE_EXTS = {
    "exe": "programme Windows",
    "com": "programme Windows",
    "scr": "économiseur d'écran Windows (programme)",
    "pif": "raccourci de programme Windows",
    "msi": "installateur Windows",
    "bat": "script Windows",
    "cmd": "script Windows",
    "vbs": "script Windows (VBScript)",
    "vbe": "script Windows (VBScript)",
    "js": "script (JavaScript)",
    "jse": "script (JavaScript)",
    "wsf": "script Windows",
    "hta": "application HTML Windows",
    "ps1": "script PowerShell",
    "jar": "programme Java",
    "lnk": "raccourci Windows",
    "sh": "script",
    "command": "script macOS",
    "app": "application macOS",
}
_WORD = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{3,40}")
_WORD16 = re.compile(rb"(?:[A-Za-z_]\x00)(?:[A-Za-z0-9_]\x00){3,40}")


@dataclass(frozen=True)
class Finding:
    level: str  # élevé | à surveiller | info
    reason: str


def _names_in(blob: bytes) -> set[str]:
    """Mots ASCII et UTF-16 présents dans des octets (noms de fonctions importées)."""
    words = {m.group().decode() for m in _WORD.finditer(blob)}
    words |= {m.group().decode("utf-16-le") for m in _WORD16.finditer(blob)}
    return words


def _match(names: set[str]) -> list[Finding]:
    """Fonctions dangereuses citées (aussi au milieu d'un mot : dans un binaire, les noms
    se suivent parfois sans séparateur, ou portent un suffixe A/W)."""
    found: list[Finding] = []
    for base, (level, why) in DANGEROUS_FUNCTIONS.items():
        if any(base in name for name in names):
            found.append(Finding(level, f"{base} : {why}"))
    return found


def scan_binary(blob: bytes) -> list[Finding]:
    """Compilé (.ex4/.ex5) ou DLL : fonctions et DLL sensibles citées dans le fichier."""
    names = _names_in(blob)
    findings = _match(names)
    lowered = blob.lower()
    for dll, (level, why) in SENSITIVE_DLLS.items():
        if dll.encode() in lowered or dll.encode("utf-16-le") in lowered:
            findings.append(Finding(level, f"{dll} : {why}"))
    return findings


def scan_source(text: str) -> list[Finding]:
    """Source MQL : fonctions Windows importées, DLL importées, fonctions MQL réseau."""
    names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,40}", text))
    findings = _match(names)
    lowered = text.lower()
    for dll, (level, why) in SENSITIVE_DLLS.items():
        if dll in lowered:
            findings.append(Finding(level, f"importe {dll} : {why}"))
    for name, why in MQL_INFO.items():
        if re.search(rf"\b{name}\s*\(", text):
            findings.append(Finding("info", f"{name} : {why}"))
    if "#import" in text and ".dll" in lowered:
        findings.append(Finding("à surveiller", "importe une DLL : elle peut tout faire"))
    return findings


def level_rank(level: str) -> int:
    return {"élevé": 0, "à surveiller": 1, "info": 2}.get(level, 3)
