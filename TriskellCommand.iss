; ===========================================================================
; Inno Setup script — Triskell Command (Triskell Studio)
;
; Pour compiler :
;   1. Ouvre Inno Setup Compiler
;   2. File → Open → sélectionne ce fichier (TriskellCommand.iss)
;   3. Build → Compile (ou F9)
;   4. L'installateur TriskellCommand_Setup.exe sera créé dans Output\
;
; Ou en ligne de commande :
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" TriskellCommand.iss
;
; Ce script :
;   - Installe Triskell Command dans Program Files\Triskell Studio\Triskell Command
;     (ou %LOCALAPPDATA%\Programs si pas admin)
;   - Crée raccourcis Bureau + Menu Démarrer (optionnels)
;   - Crée un uninstaller propre
;   - Pas de prérequis système (CTk fonctionne nativement, pas de WebView2)
; ===========================================================================

#define MyAppName      "Triskell Command"
#define MyAppVersion   "0.1.0"
#define MyAppPublisher "Triskell Studio"
#define MyAppURL       "https://triskell-studio.fr"
#define MyAppExeName   "Triskell Command.exe"
#define MySourceDir    "dist\Triskell Command"

[Setup]
; Identifiant unique (UUID v4 — ne JAMAIS modifier d'une version à l'autre)
AppId={{B7E4F8C3-2D5A-4F91-9A7C-TRISKELL-CMD01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppPublisher}\{#MyAppName}
DefaultGroupName={#MyAppPublisher}
DisableProgramGroupPage=yes
LicenseFile=
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=TriskellCommand_Setup
SetupIconFile=assets\triskell.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
DisableWelcomePage=no
UninstallDisplayName={#MyAppName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoCopyright=© 2026 {#MyAppPublisher}
VersionInfoDescription=Installateur Triskell Command — Cockpit interne Triskell
VersionInfoProductName={#MyAppName}
VersionInfoVersion={#MyAppVersion}.0

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"; Flags: unchecked
Name: "quicklaunchicon"; Description: "Créer un raccourci dans la barre de lancement rapide"; GroupDescription: "Raccourcis :"; Flags: unchecked

[Files]
; L'exe principal
Source: "{#MySourceDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Tout le contenu du dossier _internal/ (Python embarqué, libs, triskell_core)
Source: "{#MySourceDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Menu Démarrer
Name: "{autoprograms}\{#MyAppPublisher}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\{#MyAppPublisher}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
; Raccourci Bureau (optionnel)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
; Quick Launch
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName} maintenant"; Flags: nowait postinstall skipifsilent
