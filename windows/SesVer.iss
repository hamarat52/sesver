; SesVer — Windows kurulum programı (Inno Setup 6)
;
; Derleme (Windows'ta, Inno Setup 6 kurulu):
;   ISCC.exe windows\SesVer.iss
;   ISCC.exe /DAppVersion=1.2.3 windows\SesVer.iss      (sürümü dışarıdan ver)
; Sürümün tek kaynağı kökteki VERSION dosyasıdır: /DAppVersion verilmezse oradan
; okunur. CI her zaman /DAppVersion verir ve v* tag'iyle VERSION'ın eşit olduğunu
; derlemeden önce denetler.
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
; - İlk kurulum SİHİRBAZIN İÇİNDE yapılır (konsol penceresi açılmaz): dosyalar
;   kopyalandıktan sonra (CurStepChanged(ssPostInstall)) "SesVer hazırlanıyor"
;   ilerleme sayfası açılır ve WINDOWS_BASLAT.bat yalnız-kurulum kipinde
;   (/yalniz-kurulum) GİZLİ çalıştırılır: SesVer'i başlatmaz, pause beklemez,
;   her adımda {app}\kurulum_durum.txt'ye "<adım>/<toplam>|<metin>" yazar, tüm
;   çıktısı {app}\kurulum_log.txt'ye gider. Biçimin tek kaynağı
;   tools/kurulum_durum_bicimi.py; tests/test_windows_kurulum.py eşleşmeyi sınar.
;   * Gizli başlatma: ExecAndLogOutput konsol programlarını CREATE_NO_WINDOW ile
;     başlatır (Windows Terminal varsayılan olsa bile pencere yok). Beklemeyi
;     kendi döngümüz yapsın diye o cmd.exe yalnız "start /b" ile asıl cmd.exe'yi
;     aynı (penceresiz) konsolda başlatıp hemen çıkar. Exec(ewNoWait) burada
;     kullanılmaz: yalnız SW_HIDE verir, Windows 11'de Terminal penceresi açılabilir.
;   * Bitişin izlenmesi: durum dosyasındaki "tamam" / "hata:<ADIM>" satırı
;     (zaman aşımı YOK; torch indirmesi yavaş bağlantıda saatler sürebilir) +
;     bat'ın yazdığı kurulum_pid.txt'deki cmd.exe süreci: OpenProcess/
;     GetExitCodeProcess ile canlılık; süreç son satırı yazmadan biterse hata.
;   * İptal: sayfadaki "Kurulumu durdur" → taskkill /T /F /PID <pid> (süreç
;     ağacı). Yarım kurulum işaret dosyası yazılmadığı için bat'ın mevcut
;     "kaldığı yerden devam" mantığıyla sonraki çift tıkta sürer.
;   * Başarı: kısayollar aşağıdaki kurala göre pythonw'ye çevrilir; Bitir
;     sayfasında "SesVer'i şimdi aç" (pythonw, konsolsuz).
;   * Hata/iptal: Bitir sayfasında açık metin + kurulum_log.txt yolu + e-posta
;     adresi + "Günlüğü aç"; kısayollar WINDOWS_BASLAT.bat'ı gösterir.
;   * Sessiz kurulum (/SILENT, /VERYSILENT): ortam kurulumu varsayılan olarak
;     ATLANIR (eski davranış); /ORTAMKUR verilirse sessizce yapılır ve başarısız
;     olursa Setup 30 çıkış koduyla biter (CI tam testi bunu kullanır).
; - Kaldırma: kopyalanan dosyalar + indirilen python-embed\ ve geçici/günlük
;   dosyaları silinir. KULLANICI VERİSİ SİLİNMEZ: voices\seslerim\ (kişisel
;   ses klonları) ve outputs\ (üretilen sesler) klasörde kalır.

#define AppName "SesVer"
; [Code] ExecAndLogOutput ve LoadStringFromLockedFile kullanır: Inno Setup 6.3.0+.
#if VER < EncodeVer(6, 3, 0)
  #error Bu betik Inno Setup 6.3.0 ya da daha yenisini gerektirir
#endif
#ifndef AppVersion
  #define VersionFile FileOpen(AddBackslash(SourcePath) + "..\VERSION")
  #if !VersionFile
    #error Kökteki VERSION dosyası okunamadı
  #endif
  #define AppVersion Trim(FileRead(VersionFile))
  #expr FileClose(VersionFile)
  #undef VersionFile
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
turkish.LaunchSesVer=SesVer'i şimdi aç
english.LaunchSesVer=Open SesVer now
turkish.ShortcutComment=SesVer — yerel Türkçe ses üretimi
english.ShortcutComment=SesVer — local Turkish voice generation
turkish.SetupGuideName=SesVer kurulum ve sorun giderme rehberi
english.SetupGuideName=SesVer setup and troubleshooting guide
turkish.UninstallName=SesVer'i kaldır
english.UninstallName=Uninstall SesVer
; --- İlk kurulum (ortam) ilerleme sayfası ---
turkish.OrtamSayfaBaslik=SesVer hazırlanıyor
english.OrtamSayfaBaslik=Preparing SesVer
turkish.OrtamSayfaAciklama=İlk kurulum 5–30 dakika sürebilir; yaklaşık 3 GB indirilir, internet bağlantısı gerekir.
english.OrtamSayfaAciklama=First-time setup can take 5–30 minutes; about 3 GB is downloaded and an internet connection is required.
turkish.OrtamNotu=Bu sırada başka bir pencere açılmaz; bilgisayarı kapatmayın. Durdurursanız SesVer'i ilk açtığınızda kurulum kaldığı yerden devam eder.
english.OrtamNotu=No other window will open meanwhile; please keep the computer on. If you stop, setup resumes where it left off the first time you open SesVer.
turkish.OrtamBasliyor=Kurulum başlatılıyor...
english.OrtamBasliyor=Starting setup...
turkish.OrtamAdimMetni=Adım %1/%2: %3
english.OrtamAdimMetni=Step %1 of %2: %3
turkish.OrtamAyrinti=%1 · geçen süre %2
english.OrtamAyrinti=%1 · elapsed %2
turkish.OrtamAdim0=Hazırlanıyor
english.OrtamAdim0=Getting ready
turkish.OrtamAdim1=Python indiriliyor
english.OrtamAdim1=Downloading Python
turkish.OrtamAdim2=pip hazırlanıyor
english.OrtamAdim2=Preparing pip
turkish.OrtamAdim3=Ekran kartı algılanıyor
english.OrtamAdim3=Detecting the graphics card
turkish.OrtamAdim4=PyTorch kuruluyor (en uzun adım)
english.OrtamAdim4=Installing PyTorch (longest step)
turkish.OrtamAdim5=Ses modeli paketi (voxcpm) kuruluyor
english.OrtamAdim5=Installing the voice model package (voxcpm)
turkish.OrtamAdim6=Paketler kuruluyor
english.OrtamAdim6=Installing packages
turkish.OrtamIptalDugmesi=Kurulumu durdur
english.OrtamIptalDugmesi=Stop setup
turkish.OrtamIptalOnay=İlk kurulum durdurulsun mu?%n%nSesVer dosyaları kurulu kalır; SesVer'i ilk açtığınızda kurulum kaldığı yerden devam eder.
english.OrtamIptalOnay=Stop the first-time setup?%n%nSesVer's files stay installed; setup resumes where it left off the first time you open SesVer.
turkish.OrtamDurduruluyor=Durduruluyor...
english.OrtamDurduruluyor=Stopping...
turkish.OrtamBaslatilamadi=kurulum başlatıcısı çalıştırılamadı (%1)
english.OrtamBaslatilamadi=the setup launcher could not be started (%1)
turkish.OrtamBeklenmedikCikis=kurulum beklenmedik şekilde durdu (çıkış kodu %1)
english.OrtamBeklenmedikCikis=setup stopped unexpectedly (exit code %1)
turkish.OrtamBitirBaslikEksik=SesVer kuruldu, ilk hazırlık tamamlanamadı
english.OrtamBitirBaslikEksik=SesVer is installed, but first-time setup did not finish
turkish.OrtamHataMetni=İlk hazırlık şu adımda durdu: %1%n%nİnternet bağlantınızı kontrol edip masaüstündeki ya da Başlat menüsündeki SesVer simgesine çift tıklayın; kurulum kaldığı yerden devam eder.%n%nAyrıntılar: %2%nSorun sürerse kurulum_log.txt dosyasını hermes.agent.hamarat@gmail.com adresine gönderin.
english.OrtamHataMetni=First-time setup stopped at this step: %1%n%nCheck your internet connection, then double-click the SesVer icon on the desktop or in the Start menu; setup resumes where it left off.%n%nDetails: %2%nIf the problem persists, send the kurulum_log.txt file to hermes.agent.hamarat@gmail.com.
turkish.OrtamIptalMetni=İlk hazırlık durduruldu.%n%nMasaüstündeki ya da Başlat menüsündeki SesVer simgesine çift tıkladığınızda kurulum kaldığı yerden devam eder.%n%nAyrıntılar: %1
english.OrtamIptalMetni=First-time setup was stopped.%n%nDouble-click the SesVer icon on the desktop or in the Start menu and setup resumes where it left off.%n%nDetails: %1
turkish.GunluguAc=Günlüğü aç
english.GunluguAc=Open log
turkish.GunlukAcilamadi=Günlük açılamadı: %1%n%n%2
english.GunlukAcilamadi=Could not open the log: %1%n%n%2

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIconTask}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Uygulama kodu: kökteki tüm Python modülleri (app.py, desktop.py, hata_rehberi.py, ...).
Source: "{#SrcRoot}\*.py"; DestDir: "{app}"; Flags: ignoreversion
; Hızlı Mod (EMA Lightning) motoru paketi; ağırlıklar kurulumda değil, sekmedeki "indir" ile gelir.
Source: "{#SrcRoot}\engines\*.py"; DestDir: "{app}\engines"; Flags: ignoreversion
; voice_designer.py'nin çalışma zamanında okuduğu eşleme dosyası.
Source: "{#SrcRoot}\voice_design_map.json"; DestDir: "{app}"; Flags: ignoreversion
; Arayüz çevirileri (i18n.py okur); yoksa arayüz Türkçe kalır.
Source: "{#SrcRoot}\locales\*.json"; DestDir: "{app}\locales"; Flags: ignoreversion
Source: "{#SrcRoot}\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
; Uygulama sürümü (surum.py okur; "Yeni sürüm var" kontrolü bununla karşılaştırır).
Source: "{#SrcRoot}\VERSION"; DestDir: "{app}"; Flags: ignoreversion
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
; İlk kurulum artık sihirbazın içinde yapılır ([Code] CurStepChanged). Bitir
; sayfası yalnız SesVer'i açmayı önerir; sessiz kurulumda çalışmaz.
; Ortam hazır + WebView2 var → doğrudan pythonw (konsol penceresi yok).
Filename: "{app}\python-embed\pythonw.exe"; Parameters: "-E -s ""{app}\desktop.py"""; WorkingDir: "{app}"; Description: "{cm:LaunchSesVer}"; Flags: postinstall nowait skipifsilent; Check: OrtamHazirDogrudanAcilir
; Ortam hazır ama doğrudan açılamıyor (WebView2 yok ya da .venv yedek yolu) →
; başlatıcı (WebView2 yoksa konsollu yönteme kendisi döner).
Filename: "{app}\WINDOWS_BASLAT.bat"; WorkingDir: "{app}"; Description: "{cm:LaunchSesVer}"; Flags: postinstall nowait skipifsilent; Check: OrtamHazirBaslaticiGerekli

[UninstallDelete]
; Çalışma zamanında oluşan, kurulumun kopyalamadığı dosyalar. Kullanıcı verisi
; (voices\seslerim\, outputs\) bilerek listede YOK.
Type: filesandordirs; Name: "{app}\python-embed"
; .venv: WINDOWS_BASLAT.bat'ın python-embed indirilemezse kullandığı yedek ortam.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\pbs_tmp"
Type: filesandordirs; Name: "{app}\__pycache__"
; Hızlı Mod: indirilen EMA ağırlıkları (~34 MB, sekmedeki "indir" ile gelir) ve motor önbelleği.
Type: filesandordirs; Name: "{app}\models\ema-lightning"
Type: dirifempty; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\engines\__pycache__"
Type: files; Name: "{app}\pbs_*"
Type: files; Name: "{app}\sesver_log.txt"
Type: files; Name: "{app}\sesver_durum.tmp"
; Sihirbazın ilk kurulum adımı (WINDOWS_BASLAT.bat /yalniz-kurulum) dosyaları.
Type: files; Name: "{app}\kurulum_log.txt"
Type: files; Name: "{app}\kurulum_durum.txt"
Type: files; Name: "{app}\kurulum_pid.txt"

[Code]
const
  WebView2ClientKey = 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

  // --- İlk kurulum (ortam): WINDOWS_BASLAT.bat yalnız-kurulum kipiyle ortak biçim ---
  // Tek kaynak: tools/kurulum_durum_bicimi.py. tests/test_windows_kurulum.py bu
  // sabitlerin oradakilerle ve bat'ın yazdığı satırlarla eşleştiğini sınar.
  OrtamDurumDosyasi = 'kurulum_durum.txt';
  OrtamGunlukDosyasi = 'kurulum_log.txt';
  OrtamPidDosyasi = 'kurulum_pid.txt';
  OrtamYalnizKurulumArg = '/yalniz-kurulum';
  OrtamToplamAdim = 6;
  OrtamDurumTamam = 'tamam';
  OrtamDurumHataOneki = 'hata:';
  // Sessiz kurulumda ortam kurulumunu açan komut satırı parametresi.
  OrtamKurParametresi = '/ORTAMKUR';
  // Sessiz /ORTAMKUR kurulumunda ilk kurulum tamamlanamazsa Setup'ın çıkış kodu.
  OrtamHataCikisKodu = 30;
  // İlerleme çubuğu ölçeği (binde) ve durum dosyası okuma aralığı.
  OrtamCubukMax = 1000;
  OrtamOkumaAraligiMs = 500;
  // kernel32: PROCESS_QUERY_LIMITED_INFORMATION ve STILL_ACTIVE.
  OrtamSurecSorguErisimi = $1000;
  OrtamSurecCalisiyor = 259;

type
  TOrtamSonuc = (osDenenmedi, osTamam, osHata, osIptal);

var
  OrtamSonuc: TOrtamSonuc;
  OrtamHataAdimi: String;
  OrtamIptalIstendi: Boolean;
  OrtamSayfasi: TOutputProgressWizardPage;
  OrtamIptalDugmesi: TNewButton;
  OrtamNotuEtiketi: TNewStaticText;
  GunlukDugmesi: TNewButton;

function OpenProcess(dwDesiredAccess: DWORD; bInheritHandle: BOOL; dwProcessId: DWORD): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function GetExitCodeProcess(hProcess: THandle; var lpExitCode: DWORD): BOOL;
  external 'GetExitCodeProcess@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';
function GetTickCount: DWORD;
  external 'GetTickCount@kernel32.dll stdcall';

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

// Var olan bir kısayolun hedefini değiştirir (kısayol yoksa dokunmaz).
procedure SetShortcutTarget(const LinkPath, Target, Params: String);
var
  App: String;
begin
  if not FileExists(LinkPath) then
    Exit;
  App := ExpandConstant('{app}');
  try
    CreateShellLink(LinkPath, CustomMessage('ShortcutComment'), Target, Params,
      App, App + '\SesVer.ico', 0, SW_SHOWNORMAL);
    Log('Kısayol güncellendi: ' + LinkPath + ' -> ' + Target + ' ' + Params);
  except
    Log('Kısayol güncellenemedi (' + LinkPath + '): ' + GetExceptionMessage);
  end;
end;

procedure SetShortcutsTarget(const Target, Params: String);
begin
  SetShortcutTarget(ExpandConstant('{autoprograms}\{#AppName}.lnk'), Target, Params);
  SetShortcutTarget(ExpandConstant('{autodesktop}\{#AppName}.lnk'), Target, Params);
end;

// İlk kurulum başarıyla bittiyse kısayollar konsol penceresi açmayan doğrudan
// başlatmaya (pythonw.exe -E -s desktop.py) geçer; doğrudan başlatma hazır
// değilse (.venv yedek yolu ya da WebView2 yok) .bat'ta kalır.
procedure PostSetupShortcuts();
var
  App: String;
begin
  App := ExpandConstant('{app}');
  if DirectLaunchReady() then
    SetShortcutsTarget(App + '\python-embed\pythonw.exe', '-E -s "' + App + '\desktop.py"')
  else
    Log('İlk kurulum sonrası doğrudan başlatma hazır değil (python-embed=' +
        IntToStr(Ord(EmbedReady())) + ', WebView2=' + IntToStr(Ord(WebView2Installed())) +
        '); kısayollar WINDOWS_BASLAT.bat''ta kaldı.');
end;

// İlk kurulum tamamlanmadıysa (hata/iptal) kısayollar başlatıcıyı göstermeli:
// sonraki çift tıkta kurulum kaldığı yerden devam eder. Güncellemede [Icons]
// eski kurulumun işareti yüzünden pythonw'yi seçmiş olabilir.
procedure ShortcutsBackToLauncher();
var
  App: String;
begin
  App := ExpandConstant('{app}');
  SetShortcutsTarget(App + '\WINDOWS_BASLAT.bat', '');
end;

// [Run] Check'leri: Bitir sayfasındaki "SesVer'i şimdi aç".
function OrtamHazirDogrudanAcilir(): Boolean;
begin
  Result := (OrtamSonuc = osTamam) and DirectLaunchReady();
end;

function OrtamHazirBaslaticiGerekli(): Boolean;
begin
  Result := (OrtamSonuc = osTamam) and not DirectLaunchReady();
end;

function KomutSatirindaVar(const Param: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Param) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

// Dosyanın ilk satırı (yazılırken de okunabilir); yoksa ya da okunamazsa ''.
function IlkSatiriOku(const Dosya: String): String;
var
  Ham: AnsiString;
  P: Integer;
begin
  Result := '';
  if not FileExists(Dosya) then
    Exit;
  if not LoadStringFromLockedFile(Dosya, Ham) then
    Exit;
  Result := String(Ham);
  P := Pos(#13, Result);
  if P > 0 then
    Result := Copy(Result, 1, P - 1);
  P := Pos(#10, Result);
  if P > 0 then
    Result := Copy(Result, 1, P - 1);
  Result := Trim(Result);
end;

// "<adım>/<toplam>|<metin>" satırını ayrıştırır (biçim: tools/kurulum_durum_bicimi.py,
// orada pascal_ayristir bu işlevin birebir karşılığıdır). Boş ya da yarım yazılmış
// satırda False döner; çağıran önceki durumu korur.
function DurumSatiriniAyristir(Satir: String; var Adim, Toplam: Integer; var Metin: String): Boolean;
var
  Cizgi, Bolu: Integer;
  Sol: String;
begin
  Result := False;
  Cizgi := Pos('|', Satir);
  if Cizgi < 4 then
    Exit;
  Sol := Copy(Satir, 1, Cizgi - 1);
  Bolu := Pos('/', Sol);
  if Bolu < 2 then
    Exit;
  Adim := StrToIntDef(Copy(Sol, 1, Bolu - 1), -1);
  Toplam := StrToIntDef(Copy(Sol, Bolu + 1, Length(Sol)), -1);
  Metin := Trim(Copy(Satir, Cizgi + 1, Length(Satir)));
  Result := (Adim >= 0) and (Toplam > 0) and (Adim <= Toplam) and (Metin <> '');
end;

// Metin "tamam" ya da "hata:<ADIM>" ise OrtamSonuc'u ayarlar ve True döner.
function OrtamBitisiniIsle(Metin: String): Boolean;
var
  Onek: String;
begin
  Result := True;
  Onek := OrtamDurumHataOneki;
  if Metin = OrtamDurumTamam then
    OrtamSonuc := osTamam
  else if Pos(Onek, Metin) = 1 then
  begin
    OrtamSonuc := osHata;
    OrtamHataAdimi := Copy(Metin, Length(Onek) + 1, Length(Metin));
  end
  else
    Result := False;
end;

// Çubukta adımın başladığı yer (binde). Ağırlık tipik süreye göredir: PyTorch
// (~3 GB) en uzun adımdır.
function AdimBaslangici(Adim: Integer): Integer;
begin
  case Adim of
    0: Result := 0;
    1: Result := 10;
    2: Result := 80;
    3: Result := 120;
    4: Result := 140;
    5: Result := 780;
    6: Result := 820;
  else
    Result := OrtamCubukMax;
  end;
end;

// Adımın tipik süresi (sn): çubuk adım içinde bu süreye göre ilerler ve adım
// aralığının %90'ında durur (gerçek bitiş durum dosyasından gelir).
function AdimTipikSuresi(Adim: Integer): Integer;
begin
  case Adim of
    1: Result := 90;
    2: Result := 45;
    3: Result := 20;
    4: Result := 900;
    5: Result := 45;
    6: Result := 600;
  else
    Result := 30;
  end;
end;

function AdimAdi(Adim: Integer): String;
begin
  if (Adim >= 0) and (Adim <= OrtamToplamAdim) then
    Result := CustomMessage('OrtamAdim' + IntToStr(Adim))
  else
    Result := CustomMessage('OrtamAdim0');
end;

function SureMetni(Saniye: Integer): String;
begin
  Result := Format('%d:%.2d', [Saniye div 60, Saniye mod 60]);
end;

procedure OrtamSayfasiniGuncelle(Adim: Integer; const Ayrinti: String; AdimSn, ToplamSn: Integer);
var
  Bas, Aralik, Ilerleme: Integer;
  Detay: String;
begin
  Bas := AdimBaslangici(Adim);
  Aralik := AdimBaslangici(Adim + 1) - Bas;
  Ilerleme := Aralik * AdimSn div AdimTipikSuresi(Adim);
  if Ilerleme > Aralik * 9 div 10 then
    Ilerleme := Aralik * 9 div 10;
  Detay := Ayrinti;
  if Detay = '' then
    Detay := AdimAdi(Adim);
  OrtamSayfasi.SetText(
    FmtMessage(CustomMessage('OrtamAdimMetni'), [IntToStr(Adim), IntToStr(OrtamToplamAdim), AdimAdi(Adim)]),
    FmtMessage(CustomMessage('OrtamAyrinti'), [Detay, SureMetni(ToplamSn)]));
  OrtamSayfasi.SetProgress(Bas + Ilerleme, OrtamCubukMax);
end;

procedure BaslaticiCiktisi(const S: String; const Error, FirstLine: Boolean);
begin
  if Trim(S) <> '' then
    Log('Başlatıcı çıktısı: ' + S);
end;

// kurulum_log.txt'nin sonuna sihirbazın notunu ekler (ASCII; destek için).
procedure OrtamGunlugeEkle(const Satir: String);
begin
  SaveStringToFile(ExpandConstant('{app}\') + OrtamGunlukDosyasi,
    #13#10 + '[SIHIRBAZ] ' + Satir + #13#10, True);
end;

// İlk kurulum süreç ağacını sonlandırır (cmd.exe + python/pip/curl alt süreçleri).
// Konsol programları ExecAndLogOutput ile çalıştırılır: pencere açılmaz.
procedure OrtamSureciniDurdur(Pid: Integer);
var
  RC: Integer;
  Komut: String;
begin
  try
    if Pid > 0 then
    begin
      Log('İlk kurulum süreç ağacı sonlandırılıyor: taskkill /T /F /PID ' + IntToStr(Pid));
      ExecAndLogOutput(ExpandConstant('{sys}\taskkill.exe'), '/T /F /PID ' + IntToStr(Pid), '',
        SW_HIDE, ewWaitUntilTerminated, RC, @BaslaticiCiktisi);
    end
    else
    begin
      // PID dosyası yazılamadıysa: süreç, komut satırındaki yalnız-kurulum argümanından bulunur.
      Komut := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' +
        'Get-CimInstance Win32_Process | Where-Object { $_.Name -eq ''cmd.exe'' -and ' +
        '$_.CommandLine -like ''*WINDOWS_BASLAT.bat*' + OrtamYalnizKurulumArg + '*'' } | ' +
        'ForEach-Object { taskkill.exe /T /F /PID $_.ProcessId }"';
      Log('İlk kurulum süreci PID''siz sonlandırılıyor (PowerShell).');
      ExecAndLogOutput(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Komut, '',
        SW_HIDE, ewWaitUntilTerminated, RC, @BaslaticiCiktisi);
    end;
    Log('Sonlandırma çıkış kodu: ' + IntToStr(RC));
  except
    Log('İlk kurulum süreci sonlandırılamadı: ' + GetExceptionMessage);
  end;
end;

procedure OrtamIptalDugmesiClick(Sender: TObject);
begin
  if OrtamIptalIstendi then
    Exit;
  if MsgBox(CustomMessage('OrtamIptalOnay'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    OrtamIptalIstendi := True;
    OrtamIptalDugmesi.Enabled := False;
  end;
end;

procedure GunlukDugmesiClick(Sender: TObject);
var
  Gunluk: String;
  Hata: Integer;
begin
  Gunluk := ExpandConstant('{app}\') + OrtamGunlukDosyasi;
  if ShellExec('open', Gunluk, '', '', SW_SHOWNORMAL, ewNoWait, Hata) then
    Exit;
  if Exec(ExpandConstant('{win}\notepad.exe'), '"' + Gunluk + '"', '', SW_SHOWNORMAL, ewNoWait, Hata) then
    Exit;
  MsgBox(FmtMessage(CustomMessage('GunlukAcilamadi'), [Gunluk, SysErrorMessage(Hata)]), mbError, MB_OK);
end;

// WINDOWS_BASLAT.bat'ı yalnız-kurulum kipinde gizli çalıştırır ve bitene kadar
// ilerleme sayfasını günceller. Sonuç OrtamSonuc / OrtamHataAdimi'na yazılır.
procedure OrtamKurulumunuCalistir();
var
  App, Cmd, DurumYolu, PidYolu, Komut, Satir, SonSatir, Metin, Ayrinti: String;
  Adim, Toplam, SonAdim, Pid, RC, Tur: Integer;
  Baslangic, AdimBaslangic, CikisKodu: DWORD;
  Surec: THandle;
  Basladi: Boolean;
begin
  OrtamSonuc := osHata;
  OrtamHataAdimi := '';
  OrtamIptalIstendi := False;
  App := ExpandConstant('{app}');
  Cmd := ExpandConstant('{cmd}');
  DurumYolu := App + '\' + OrtamDurumDosyasi;
  PidYolu := App + '\' + OrtamPidDosyasi;
  // Önceki bir denemenin "tamam"/"hata" satırı yeni koşu sanılmasın.
  DeleteFile(DurumYolu);
  DeleteFile(PidYolu);
  SonSatir := '';
  Ayrinti := '';
  SonAdim := 0;
  Pid := 0;
  Surec := 0;

  OrtamIptalDugmesi.Enabled := True;
  OrtamSayfasi.SetText(CustomMessage('OrtamBasliyor'), '');
  OrtamSayfasi.SetProgress(0, OrtamCubukMax);
  OrtamSayfasi.Show;
  try
    // Bu cmd.exe CREATE_NO_WINDOW ile (ExecAndLogOutput) açılır ve "start /b" ile
    // asıl cmd.exe'yi aynı penceresiz konsolda başlatıp hemen çıkar. Bekleme ve
    // iptal aşağıdaki döngüde yapılır. "call": yoldaki & gibi karakterler tırnak
    // içinde kalır (cmd /c tırnak soyma kuralına girilmez).
    Komut := '/d /c start "" /b "' + Cmd + '" /d /c call "' + App + '\WINDOWS_BASLAT.bat" ' +
      OrtamYalnizKurulumArg;
    Log('İlk kurulum başlatılıyor: ' + Cmd + ' ' + Komut);
    Basladi := False;
    try
      Basladi := ExecAndLogOutput(Cmd, Komut, App, SW_HIDE, ewWaitUntilTerminated, RC, @BaslaticiCiktisi);
      if not Basladi then
        OrtamHataAdimi := FmtMessage(CustomMessage('OrtamBaslatilamadi'), [SysErrorMessage(RC)])
      else if RC <> 0 then
      begin
        Basladi := False;
        OrtamHataAdimi := FmtMessage(CustomMessage('OrtamBaslatilamadi'), ['start ' + IntToStr(RC)]);
      end;
    except
      Basladi := False;
      OrtamHataAdimi := FmtMessage(CustomMessage('OrtamBaslatilamadi'), [GetExceptionMessage]);
    end;

    Baslangic := GetTickCount;
    AdimBaslangic := Baslangic;
    while Basladi do
    begin
      // ~0,5 sn bekle; SetProgress pencere mesajlarını işler (çizim + durdur düğmesi).
      for Tur := 1 to OrtamOkumaAraligiMs div 100 do
      begin
        Sleep(100);
        OrtamSayfasi.SetProgress(OrtamSayfasi.ProgressBar.Position, OrtamCubukMax);
      end;

      if OrtamIptalIstendi then
      begin
        OrtamSayfasi.SetText(CustomMessage('OrtamDurduruluyor'), '');
        OrtamSureciniDurdur(Pid);
        OrtamGunlugeEkle('Ilk kurulum kullanici tarafindan durduruldu; sonraki acilista kaldigi yerden devam eder.');
        OrtamSonuc := osIptal;
        Break;
      end;

      // Bat, yalnız-kurulum kipine girer girmez kendi cmd.exe PID'ini yazar.
      if Pid = 0 then
      begin
        Pid := StrToIntDef(IlkSatiriOku(PidYolu), 0);
        if Pid > 0 then
        begin
          Surec := OpenProcess(OrtamSurecSorguErisimi, False, Pid);
          if Surec <> 0 then
            Log('İlk kurulum süreci izleniyor: PID ' + IntToStr(Pid))
          else
            Log('İlk kurulum süreci açılamadı (PID ' + IntToStr(Pid) + '); yalnız durum dosyası izlenecek.');
        end;
      end;

      Satir := IlkSatiriOku(DurumYolu);
      if (Satir <> SonSatir) and DurumSatiriniAyristir(Satir, Adim, Toplam, Metin) then
      begin
        SonSatir := Satir;
        Log('İlk kurulum durumu: ' + Satir);
        if OrtamBitisiniIsle(Metin) then
          Break;
        if Adim <> SonAdim then
        begin
          SonAdim := Adim;
          AdimBaslangic := GetTickCount;
        end;
        Ayrinti := Metin;
      end;

      // Süreç son satırı yazmadan bittiyse (çöktü/kapatıldı) sonsuza dek beklenmez.
      if Surec <> 0 then
        if GetExitCodeProcess(Surec, CikisKodu) and (CikisKodu <> OrtamSurecCalisiyor) then
        begin
          Satir := IlkSatiriOku(DurumYolu);
          if DurumSatiriniAyristir(Satir, Adim, Toplam, Metin) and OrtamBitisiniIsle(Metin) then
            Log('İlk kurulum durumu: ' + Satir)
          else
          begin
            OrtamSonuc := osHata;
            OrtamHataAdimi := FmtMessage(CustomMessage('OrtamBeklenmedikCikis'), [IntToStr(CikisKodu)]);
            OrtamGunlugeEkle('Kurulum sureci son durum satirini yazmadan bitti; cikis kodu ' + IntToStr(CikisKodu));
          end;
          Break;
        end;

      OrtamSayfasiniGuncelle(SonAdim, Ayrinti, Integer((GetTickCount - AdimBaslangic) div 1000),
        Integer((GetTickCount - Baslangic) div 1000));
    end;
  finally
    if Surec <> 0 then
      CloseHandle(Surec);
    OrtamSayfasi.Hide;
  end;
end;

procedure InitializeWizard();
begin
  // "SesVer hazırlanıyor" ilerleme sayfası + durdur düğmesi + not.
  OrtamSayfasi := CreateOutputProgressPage(CustomMessage('OrtamSayfaBaslik'),
    CustomMessage('OrtamSayfaAciklama'));

  OrtamIptalDugmesi := TNewButton.Create(OrtamSayfasi);
  OrtamIptalDugmesi.Parent := OrtamSayfasi.Surface;
  OrtamIptalDugmesi.Caption := CustomMessage('OrtamIptalDugmesi');
  OrtamIptalDugmesi.Top := OrtamSayfasi.ProgressBar.Top + OrtamSayfasi.ProgressBar.Height + ScaleY(12);
  OrtamIptalDugmesi.Width := WizardForm.CalculateButtonWidth([OrtamIptalDugmesi.Caption]);
  OrtamIptalDugmesi.Height := WizardForm.CancelButton.Height;
  OrtamIptalDugmesi.OnClick := @OrtamIptalDugmesiClick;

  OrtamNotuEtiketi := TNewStaticText.Create(OrtamSayfasi);
  OrtamNotuEtiketi.Parent := OrtamSayfasi.Surface;
  OrtamNotuEtiketi.AutoSize := False;
  OrtamNotuEtiketi.WordWrap := True;
  OrtamNotuEtiketi.Width := OrtamSayfasi.SurfaceWidth;
  OrtamNotuEtiketi.Top := OrtamIptalDugmesi.Top + OrtamIptalDugmesi.Height + ScaleY(16);
  OrtamNotuEtiketi.Caption := CustomMessage('OrtamNotu');
  WizardForm.AdjustLabelHeight(OrtamNotuEtiketi);

  // Bitir sayfası: ilk kurulum tamamlanamadıysa "Günlüğü aç".
  GunlukDugmesi := TNewButton.Create(WizardForm);
  GunlukDugmesi.Parent := WizardForm.FinishedPage;
  GunlukDugmesi.Caption := CustomMessage('GunluguAc');
  GunlukDugmesi.Width := WizardForm.CalculateButtonWidth([GunlukDugmesi.Caption]);
  GunlukDugmesi.Height := WizardForm.CancelButton.Height;
  GunlukDugmesi.Visible := False;
  GunlukDugmesi.OnClick := @GunlukDugmesiClick;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then
    Exit;
  if WizardSilent() and not KomutSatirindaVar(OrtamKurParametresi) then
  begin
    Log('Sessiz kurulum: ilk kurulum atlandı (' + OrtamKurParametresi +
        ' verilmedi); kısayollar kurulumdaki kurala göre kaldı.');
    Exit;
  end;
  OrtamKurulumunuCalistir();
  case OrtamSonuc of
    osTamam:
      begin
        Log('İlk kurulum tamamlandı.');
        PostSetupShortcuts();
      end;
    osIptal:
      begin
        Log('İlk kurulum kullanıcı tarafından durduruldu.');
        ShortcutsBackToLauncher();
      end;
  else
    begin
      Log('İlk kurulum tamamlanamadı: ' + OrtamHataAdimi);
      ShortcutsBackToLauncher();
    end;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Metin, Gunluk: String;
  Fark: Integer;
begin
  if (CurPageID <> wpFinished) or ((OrtamSonuc <> osHata) and (OrtamSonuc <> osIptal)) then
    Exit;
  Gunluk := ExpandConstant('{app}\') + OrtamGunlukDosyasi;
  if OrtamSonuc = osHata then
    Metin := FmtMessage(CustomMessage('OrtamHataMetni'), [OrtamHataAdimi, Gunluk])
  else
    Metin := FmtMessage(CustomMessage('OrtamIptalMetni'), [Gunluk]);
  WizardForm.FinishedHeadingLabel.Caption := CustomMessage('OrtamBitirBaslikEksik');
  Fark := WizardForm.AdjustLabelHeight(WizardForm.FinishedHeadingLabel);
  WizardForm.FinishedLabel.Top := WizardForm.FinishedLabel.Top + Fark;
  WizardForm.FinishedLabel.Caption := Metin;
  WizardForm.AdjustLabelHeight(WizardForm.FinishedLabel);
  GunlukDugmesi.Left := WizardForm.FinishedLabel.Left;
  GunlukDugmesi.Top := WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height + ScaleY(12);
  GunlukDugmesi.Visible := True;
end;

// Sessiz /ORTAMKUR kurulumunda ilk kurulum tamamlanamadıysa (CI) 0 dışı çıkış kodu.
function GetCustomSetupExitCode(): Integer;
begin
  Result := 0;
  if WizardSilent() and ((OrtamSonuc = osHata) or (OrtamSonuc = osIptal)) then
    Result := OrtamHataCikisKodu;
end;
