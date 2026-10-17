; SesKlon Windows kurulum sihirbazı (Inno Setup).
; Derlemek için: ücretsiz Inno Setup'ı (https://jrsoftware.org/isinfo.php) Windows'a
; kurun, bu dosyayı (SesKlon.iss) Inno Setup Compiler'da açın, "Compile" deyin.
; Çıktı: Output\SesKlon-Kurulum.exe — çift tıklanabilir klasik "İleri/İleri/Kur/Bitti" kurulum.
;
; Not: Bu sihirbaz sadece dosyaları kopyalar + kısayol oluşturur. Ağır Python
; ortamı/bağımlılık kurulumu (birkaç dakika sürer) ilk "SesKlon'u Başlat"
; tıklamasında baslat.bat tarafından yapılır — aynı, zaten test edilmiş mantık.

#define MyAppName "SesKlon"
#define MyAppVersion "1.0"
#define MyAppPublisher "SesKlon katkıda bulunanları"
#define MyAppURL "https://github.com/hamarat52/sesklon"

[Setup]
AppId={{E4B6C4B2-7F1A-4D3E-9C2A-5A1F0B6D8E21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
; Yönetici hakkı istemeden kullanıcı klasörüne kurar (model indirmesi/venv için daha az sürtünme)
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=SesKlon-Kurulum
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\baslat.bat
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "Masaüstü simgesi oluştur"; GroupDescription: "Ek simgeler:"

[Files]
Source: "..\app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\baslat.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\tests\*"; DestDir: "{app}\tests"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\baslat.bat"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\baslat.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\baslat.bat"; Description: "{cm:LaunchProgram,SesKlon (ilk kurulum birkaç dakika sürebilir)}"; Flags: postinstall skipifsilent shellexec nowait; WorkingDir: "{app}"

[UninstallDelete]
; Kaldırırken Python ortamını (.venv) da temizle — kurulumdan SONRA oluştuğu için
; Inno bunu otomatik silmez. Model önbelleği (~/.cache/huggingface) buraya dahil
; DEĞİLDİR; diğer araçlarla paylaşıldığı için kasıtlı olarak dokunulmaz.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\outputs"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
function PythonInstalled(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('py', '-3.11 --version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  if not Result then
    Result := Exec('python', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if not PythonInstalled() then
  begin
    if MsgBox('Python 3.10-3.12 bulunamadı. SesKlon çalışmak için Python gerektirir.' + #13#10 +
      #13#10 + 'Şimdi python.org indirme sayfasını açmak ister misiniz? Python''u kurduktan ' +
      'sonra bu kurulumu tekrar çalıştırın.',
      mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', 'https://www.python.org/downloads/', '', '', SW_SHOW, ewNoWait, ResultCode);
    Result := False;
  end;
end;
