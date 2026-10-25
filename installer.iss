#ifndef AppVer
  #define AppVer "1.0.0"
#endif
#define AppName "Floppy Studio"
#define AppExe "FloppyStudio.exe"
[Setup]
AppId={{3F1A9C52-7E4D-4B8A-A6D2-F10BB1E5D0C7}
AppName={#AppName}
AppVersion={#AppVer}
AppVerName={#AppName} {#AppVer}
AppPublisher=Davy
AppPublisherURL=https://github.com/Darkmind64/Floppy-Studio
AppSupportURL=https://github.com/Darkmind64/Floppy-Studio/issues
DefaultDirName={autopf}\Floppy Studio
DefaultGroupName={#AppName}
OutputDir=installer
OutputBaseFilename=FloppyStudio_Setup_{#AppVer}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
ChangesAssociations=yes

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
fr.AssocImages=Proposer Floppy Studio dans « Ouvrir avec » pour les images disquette (ADF, ST, D64, FD, DSK, HFE, SCP…)
en.AssocImages=Add Floppy Studio to "Open with" for floppy images (ADF, ST, D64, FD, DSK, HFE, SCP…)
fr.Assoc=Associations
en.Assoc=Associations

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assoc"; Description: "{cm:AssocImages}"; GroupDescription: "{cm:Assoc}"

[Files]
Source: "dist_setup\FloppyStudio\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\FloppyStudio.Image"; ValueType: string; ValueData: "Image disquette"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\FloppyStudio.Image\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\FloppyStudio.Image\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".adf"; ValueData: ""; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.adf\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.st\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.msa\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.d64\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.d71\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.d81\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.fd\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.dsk\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.edsk\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.hfe\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.scp\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.imd\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.ima\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.td0\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.dim\OpenWithProgids"; ValueType: string; ValueName: "FloppyStudio.Image"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: WizardSilent
