#ifndef MyAppName
#define MyAppName "Local TTS"
#endif
#ifndef MyAppVersion
#define MyAppVersion "0.1.0"
#endif
#ifndef MyAppPublisher
#define MyAppPublisher "Local TTS"
#endif
#ifndef MyAppExeName
#define MyAppExeName "LocalTTS.exe"
#endif
#ifndef MyOutputBaseFilename
#define MyOutputBaseFilename "LocalTTS-Setup"
#endif

[Setup]
AppId={{F5C3CC17-4F86-46DF-BD72-3B24A239A9E7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
OutputDir=..\..\dist-installer
OutputBaseFilename={#MyOutputBaseFilename}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\..\dist\LocalTTS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
