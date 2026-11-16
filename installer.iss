; Script Inno Setup (https://jrsoftware.org/isinfo.php) - gratuit.
; Prerequis : avoir execute build_windows.bat (le dossier dist\GestionParfumerie doit exister).
; Ouvrez ce fichier avec Inno Setup, puis Build > Compile.
; Resultat : installer\Setup_GestionParfumerie.exe (a donner au client).

[Setup]
AppName=Nevada Gestion
AppVersion=1.0.0
AppPublisher=Nevada Parfumerie Cosmetics
SetupIconFile=assets\icone.ico
UninstallDisplayIcon={app}\GestionParfumerie.exe
DefaultDirName={autopf}\GestionParfumerie
DefaultGroupName=Nevada Gestion
OutputDir=installer
OutputBaseFilename=Setup_GestionParfumerie
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
; Installation sans droits administrateur possible (dossier de l'utilisateur)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayName=Nevada Gestion

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "dist\GestionParfumerie\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Nevada Gestion"; Filename: "{app}\GestionParfumerie.exe"
Name: "{autodesktop}\Nevada Gestion"; Filename: "{app}\GestionParfumerie.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\GestionParfumerie.exe"; Description: "Lancer Nevada Gestion"; Flags: nowait postinstall skipifsilent

; NB : la désinstallation ne supprime PAS les données du client
; (dossier %APPDATA%\GestionParfumerie), c'est voulu.
