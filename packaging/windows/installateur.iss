; Installateur Windows (Inno Setup 6) — MT4 MT5 Library Manager PRO.
; Construction (CI Windows) : iscc /DVersion=1.8.0 packaging\windows\installateur.iss
; Installation pour l'utilisateur seul (aucun droit administrateur), raccourcis Menu Démarrer
; et Bureau (au choix), désinstallation propre. Les données de l'application
; (%APPDATA%\MT4MT5LibraryManagerPro) sont gardées à la désinstallation.
#ifndef Version
  #define Version "0.0.0"
#endif
#define Nom "MT4 MT5 Library Manager PRO"
#define Exe "MT4-MT5-Library-Manager-PRO.exe"

[Setup]
AppId={{6B1F3C52-8D0E-4E7A-9C61-2F4A9B7D3E11}
AppName={#Nom}
AppVersion={#Version}
AppVerName={#Nom} {#Version}
AppPublisher={#Nom}
DefaultDirName={autopf}\{#Nom}
DefaultGroupName={#Nom}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=MT4-MT5-Library-Manager-PRO-{#Version}-Windows-Setup
SetupIconFile=AppIcon.ico
UninstallDisplayIcon={app}\{#Exe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "bureau"; Description: "Créer une icône sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "..\..\dist\MT4-MT5-Library-Manager-PRO\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#Nom}"; Filename: "{app}\{#Exe}"
Name: "{group}\Désinstaller {#Nom}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#Nom}"; Filename: "{app}\{#Exe}"; Tasks: bureau

[Run]
Filename: "{app}\{#Exe}"; Description: "Lancer {#Nom}"; Flags: nowait postinstall skipifsilent
