; Script Inno Setup pour Kinesis (gratuit : https://jrsoftware.org/isinfo.php)
; Utilisation : générer d'abord dist\Kinesis avec build_exe.bat, puis ouvrir ce fichier
; dans Inno Setup et faire Build > Compile (Ctrl+F9).
; Résultat : installer\Kinesis_Setup_1.0.0.exe

#define AppName "Kinesis"
#define AppVersion "1.0.0"

[Setup]
AppId={{21C04B4E-5080-4CBC-98BA-7EADE4DCEB8F}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=Kinesis_Setup_{#AppVersion}
SetupIconFile=kinesis.ico
UninstallDisplayIcon={app}\Kinesis.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau / Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\Kinesis\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Kinesis.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Kinesis.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Kinesis.exe"; Description: "Lancer Kinesis / Launch Kinesis"; Flags: nowait postinstall skipifsilent

[Registry]
; À la désinstallation, retire le démarrage automatique avec Windows s'il était activé
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Kinesis"; ValueType: none; Flags: dontcreatekey uninsdeletevalue

[UninstallRun]
; Ferme Kinesis avant de le désinstaller
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM Kinesis.exe"; Flags: runhidden; RunOnceId: "KillKinesis"
