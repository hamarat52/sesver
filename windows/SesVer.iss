; SesVer — Windows kurulum programı (Inno Setup 6)
;
; Derleme (Windows'ta, Inno Setup 6 kurulu):
;   ISCC.exe windows\SesVer.iss
;   ISCC.exe /DAppVersion=1.2.3 windows\SesVer.iss      (sürümü dışarıdan ver)
; Çıktı: windows\Output\SesVer-Kurulum-<sürüm>.exe
; CI: .github/workflows/windows-installer.yml aynı komutu windows-latest'te çalıştırır.
;
; TASARIM
; - Bu kurulum programı Python'u ve ~3 GB'lık paketleri (torch vb.) İÇERMEZ.
;   Yalnız SesVer'in kaynak dosyalarını kopyalar. Ortam kurulumu, ZIP ile
;   dağıtımda olduğu gibi WINDOWS_BASLAT.bat tarafından yapılır (taşınabilir
;   python-embed indirme, SHA256 doğrulama, pip kurulumu, .venv yedek yolu,
;   yarıda kalınca devam etme). Mantık tek yerde kalsın diye burada tekrar
;   yazılmadı; macOS'taki macos_ortak.sh deseninin Windows karşılığı budur.
; - Kurulum klasörü kullanıcıya özeldir: %LOCALAPPDATA%\Programs\SesVer.
;   WINDOWS_BASLAT.bat python-embed\, outputs\, voices\seslerim\ ve günlükleri
;   uygulama klasörünün İÇİNE yazar; Program Files yönetici izni olmadan
;   yazılamadığı için kullanılmaz. Bu yüzden kurulum yönetici izni istemez.
; - Kısayollar (Başlat Menüsü + Masaüstü):
;     python-embed hazırsa (python-embed\pythonw.exe + sesver_kurulum_tamam.txt)
;     VE WebView2 Runtime kuruluysa -> doğrudan  pythonw.exe -E -s desktop.py
;     aksi halde                    -> WINDOWS_BASLAT.bat (önce kurulum akışı)
;   -E/-s bayrakları WINDOWS_BASLAT.bat'taki PYTHONHOME/PYTHONPATH temizliğinin
;   ve PYTHONNOUSERSITE=1'in karşılığıdır. WebView2 yokken doğrudan pythonw
;   kısayolu sessizce kapanırdı (desktop.py "pencere_yok" durumunda konsollu
;   yönteme dönmeyi başlatıcıya bırakır), bu yüzden o durumda .bat kullanılır.
; - Son ekranda "İlk kurulumu şimdi başlat" seçeneği WINDOWS_BASLAT.bat'ı
;   çalıştırır; o bitince (SesVer penceresi açılınca) kısayollar yukarıdaki
;   kurala göre yeniden değerlendirilir ve gerekiyorsa doğrudan pythonw'ye
;   çevrilir (PostSetupAfterRun).
; - Kaldırma: kopyalanan dosyalar + indirilen python-embed\ ve geçici/günlük
;   dosyaları silinir. KULLANICI VERİSİ SİLİNMEZ: voices\seslerim\ (kişisel
;   ses klonları) ve outputs\ (üretilen sesler) klasörde kalır.

#define AppName "SesVer"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppPublisher "HamaratLabs"
#define AppURL "https://github.com/hamarat52/sesver"
; Kaynak kök: bu dosya windows\ altında, proje kökü bir üst klasör.
#define SrcRoot ".."

[Setup]
; AppId kurulum kimliğidir; yükseltme/kaldırma bununla eşleşir. DEĞİŞTİRMEYİN.
AppId={{12D750B7-D7C7-400A-A81A-2A083B04A266}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
UsedUserAreasWarning=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#SrcRoot}\LICENSE
OutputDir=Output
OutputBaseFilename=SesVer-Kurulum-{#AppVersion}
SetupIconFile=SesVer.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
CloseApplications=yes
SetupLogging=yes

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
turkish.DesktopIconTask=Masaüstüne SesVer kısayolu oluştur
english.DesktopIconTask=Create a SesVer desktop shortcut
turkish.RunFirstSetup=İlk kurulumu şimdi başlat (Python ve modeller indirilir, internet gerekir, uzun sürebilir)
english.RunFirstSetup=Start first-time setup now (downloads Python and packages, needs internet, may take a while)
turkish.ShortcutComment=SesVer — yerel Türkçe ses üretimi
english.ShortcutComment=SesVer — local Turkish voice generation
turkish.SetupGuideName=SesVer kurulum ve sorun giderme rehberi
english.SetupGuideName=SesVer setup and troubleshooting guide
turkish.UninstallName=SesVer'i kaldır
english.UninstallName=Uninstall SesVer

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIconTask}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Uygulama kodu: kökteki tüm Python modülleri (app.py, desktop.py, hata_rehberi.py, ...).
Source: "{#SrcRoot}\*.py"; DestDir: "{app}"; Flags: ignoreversion
; voice_designer.py'nin çalışma zamanında okuduğu eşleme dosyası.
Source: "{#SrcRoot}\voice_design_map.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
; Ortam kurulumunu yapan başlatıcı (kısayol ve son ekran bunu çağırır).
Source: "{#SrcRoot}\WINDOWS_BASLAT.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion
; hata_rehberi.py hata mesajlarında "SesVer klasöründeki AI_KURULUM.md"ye yönlendirir.
Source: "{#SrcRoot}\AI_KURULUM.md"; DestDir: "{app}"; Flags: ignoreversion
; Kısayol ve uygulama ikonu.
Source: "SesVer.ico"; DestDir: "{app}"; Flags: ignoreversion
; Hazır (sentetik) sesler. voices\seslerim\ kişisel klonlardır; asla pakete girmez.
Source: "{#SrcRoot}\voices\hazir\*"; DestDir: "{app}\voices\hazir"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; Kullanıcının kendi sesleri burada tutulur; kaldırmada silinmez.
Name: "{app}\voices\seslerim"; Flags: uninsneveruninstall

[Icons]
; Kısayol hedefi kurulum anında seçilir (bkz. üstteki TASARIM notu). Aynı
; yoldaki iki girişten yalnız Check'i doğru olanı oluşturulur.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\python-embed\pythonw.exe"; Parameters: "-E -s ""{app}\desktop.py"""; WorkingDir: "{app}"; Comment: "{cm:ShortcutComment}"; IconFilename: "{app}\SesVer.ico"; Check: DirectLaunchReady
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\WINDOWS_BASLAT.bat"; WorkingDir: "{app}"; Comment: "{cm:ShortcutComment}"; IconFilename: "{app}\SesVer.ico"; Check: not DirectLaunchReady
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python-embed\pythonw.exe"; Parameters: "-E -s ""{app}\desktop.py"""; WorkingDir: "{app}"; Comment: "{cm:ShortcutComment}"; Tasks: desktopicon; IconFilename: "{app}\SesVer.ico"; Check: DirectLaunchReady
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\WINDOWS_BASLAT.bat"; WorkingDir: "{app}"; Comment: "{cm:ShortcutComment}"; IconFilename: "{app}\SesVer.ico"; Tasks: desktopicon; Check: not DirectLaunchReady
Name: "{autoprograms}\{#AppName} Klasörü\{cm:SetupGuideName}"; Filename: "{app}\AI_KURULUM.md"
Name: "{autoprograms}\{#AppName} Klasörü\{cm:UninstallName}"; Filename: "{uninstallexe}"

[Run]
; Son ekran seçeneği: ortam kurulumunu WINDOWS_BASLAT.bat ile yapar ve SesVer'i açar.
; Sessiz kurulumda (CI, /VERYSILENT) çalışmaz: ~3 GB indirme başlatmasın.
Filename: "{app}\WINDOWS_BASLAT.bat"; WorkingDir: "{app}"; Description: "{cm:RunFirstSetup}"; Flags: postinstall skipifsilent waituntilterminated; AfterInstall: PostSetupAfterRun

[UninstallDelete]
; Çalışma zamanında oluşan, kurulumun kopyalamadığı dosyalar. Kullanıcı verisi
; (voices\seslerim\, outputs\) bilerek listede YOK.
Type: filesandordirs; Name: "{app}\python-embed"
; .venv: WINDOWS_BASLAT.bat'ın python-embed indirilemezse kullandığı yedek ortam.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\pbs_tmp"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\pbs_*"
Type: files; Name: "{app}\sesver_log.txt"
Type: files; Name: "{app}\sesver_durum.tmp"

[Code]
const
  WebView2ClientKey = 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

// WINDOWS_BASLAT.bat'ın "kurulum tamam" ölçütü: python-embed içindeki
// Python + yalnız tüm adımlar başarıyla bitince yazılan işaret dosyası.
function EmbedReady(): Boolean;
var
  App: String;
begin
  App := ExpandConstant('{app}');
  Result := FileExists(App + '\python-embed\pythonw.exe') and
            FileExists(App + '\python-embed\sesver_kurulum_tamam.txt');
end;

// Microsoft'un belgelediği WebView2 Runtime algılaması: "pv" değeri dolu ve
// 0.0.0.0 değilse kuruludur (makine geneli 64/32 bit ve kullanıcı kurulumu).
function WebView2VersionOk(RootKey: Integer; SubKey: String): Boolean;
var
  Pv: String;
begin
  Result := RegQueryStringValue(RootKey, SubKey, 'pv', Pv) and (Pv <> '') and (Pv <> '0.0.0.0');
end;

function WebView2Installed(): Boolean;
begin
  Result := WebView2VersionOk(HKLM, 'SOFTWARE\WOW6432Node\' + WebView2ClientKey) or
            WebView2VersionOk(HKLM, 'SOFTWARE\' + WebView2ClientKey) or
            WebView2VersionOk(HKCU, 'Software\' + WebView2ClientKey);
end;

function DirectLaunchReady(): Boolean;
begin
  Result := EmbedReady() and WebView2Installed();
end;

// Var olan bir kısayolu doğrudan pythonw.exe -E -s desktop.py'ye çevirir.
procedure PointShortcutToPythonw(const LinkPath: String);
var
  App: String;
begin
  if not FileExists(LinkPath) then
    Exit;
  App := ExpandConstant('{app}');
  try
    CreateShellLink(LinkPath, CustomMessage('ShortcutComment'),
      App + '\python-embed\pythonw.exe', '-E -s "' + App + '\desktop.py"',
      App, '', 0, SW_SHOWNORMAL);
    Log('Kısayol doğrudan pythonw.exe''ye çevrildi: ' + LinkPath);
  except
    Log('Kısayol güncellenemedi (' + LinkPath + '): ' + GetExceptionMessage);
  end;
end;

// Son ekrandaki ilk kurulum (WINDOWS_BASLAT.bat) bittikten sonra çağrılır.
// Kurulum başarıyla tamamlandıysa kısayollar konsol penceresi açmayan
// doğrudan başlatmaya geçer; tamamlanmadıysa .bat'ta kalır (bir sonraki
// açılışta kurulum kaldığı yerden devam eder).
procedure PostSetupAfterRun();
begin
  if DirectLaunchReady() then
  begin
    PointShortcutToPythonw(ExpandConstant('{autoprograms}\{#AppName}.lnk'));
    PointShortcutToPythonw(ExpandConstant('{autodesktop}\{#AppName}.lnk'));
  end
  else
    Log('İlk kurulum sonrası doğrudan başlatma hazır değil (python-embed=' +
        IntToStr(Ord(EmbedReady())) + ', WebView2=' + IntToStr(Ord(WebView2Installed())) +
        '); kısayollar WINDOWS_BASLAT.bat''ta kaldı.');
end;
