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
;   * Hata/iptal: Bitir sayfasında açık metin + e-posta adresi + "Günlüğü aç".
;     Kullanıcıya gönderilmesi söylenen dosya kurulum_log.txt değil, sihirbazın
;     ondan ürettiği kurulum_log_paylas.txt'dir: ev klasörü yolları (USERPROFILE ve
;     X:\Users\<ad>) <ev> olarak gizlenir (PaylasilabilirGunlukYaz; kurallar
;     tools/kurulum_durum_bicimi.py pascal_gunluk_maskele ile aynı). Kopya yazılamazsa
;     ham günlük gösterilmez; metin yalnız durduğu adımı bildirmeyi ister. Kısayollar
;     WINDOWS_BASLAT.bat'ı gösterir.
;   * Sessiz kurulum (/SILENT, /VERYSILENT): ortam kurulumu varsayılan olarak
;     ATLANIR (eski davranış); /ORTAMKUR verilirse sessizce yapılır ve başarısız
;     olursa Setup 30 çıkış koduyla biter (CI tam testi bunu kullanır).
; - Gizlilik ve güncelleme denetimi sayfası (ek görevlerden sonra): ağ erişiminin kısa özeti,
;   README'deki gizlilik politikasının adresi ve "Açılışta güncellemeleri denetle" kutusu.
;   Kutu {app}\ayarlar.json'daki mevcut seçimle açılır; seçim değiştiyse yazılır (Ayarlar
;   sekmesindeki aynı ayar). Sessiz kurulumda /GUNCELLEMEDENETIMI=0|1 ile verilir.
; - Kaldırma: kopyalanan dosyalar ve geçici/günlük dosyaları silinir. KULLANICI VERİSİ
;   SİLİNMEZ: voices\seslerim\ (kişisel ses klonları) ve outputs\ (üretilen sesler)
;   klasörde kalır. İndirilen bileşenler (python-embed\ ve varsa .venv\, ~3 GB) için
;   kaldırma sırasında sorulur (CurUninstallStepChanged): "Sakla" (varsayılan) seçilirse
;   klasörde kalır ve aynı yere yeniden kurulumda WINDOWS_BASLAT.bat'ın kurulum işareti
;   (python-embed\sesver_kurulum_tamam.txt) aynı olduğu için hiçbir şey yeniden inmez;
;   "Sil" seçilirse silinir. Sessiz kaldırmada (/SILENT, /VERYSILENT) soru sorulmaz ve
;   eski davranış korunur: silinir. /BILESENLERISAKLA verilirse sessiz kaldırmada da kalır.

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
; Kurulum programının dosya özellikleri (Özellikler → Ayrıntılar). SignPath Foundation imzası
; ürün adı ve ürün sürümü özniteliklerinin her derlemede proje adı ve VERSION ile aynı olmasını
; şart koşar (file metadata restrictions). Inno varsayılanı VersionInfoVersion için 0.0.0.0
; olduğundan hepsi açıkça verilir; CI derlemeden sonra .exe'de ProductName/ProductVersion'ı denetler.
; Inno dizgileri sabit uzunluklu boşluk yer tutucularının üstüne yazar (ProductName/Company/
; Description 60, ProductVersion 50, FileVersion 20, Copyright 100 karakter; uzunu kesilir) ve
; kalan boşluğu bırakır. CI imzadan önce tools/pe_surum_bilgisi.py --kirp ile kaynakta kırpar.
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} kurulum programı
VersionInfoCopyright=Muhammed Yusuf Hamarat - Founder of HamaratLabs
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
turkish.ShortcutComment=SesVer: yerel Türkçe ses üretimi
english.ShortcutComment=SesVer: local Turkish voice generation
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
turkish.OrtamYanitYok=kurulum başlatıcısı %1 sn içinde yanıt vermedi
english.OrtamYanitYok=the setup launcher did not respond within %1 s
turkish.OrtamBitirBaslikEksik=SesVer kuruldu, ilk hazırlık tamamlanamadı
english.OrtamBitirBaslikEksik=SesVer is installed, but first-time setup did not finish
turkish.OrtamHataMetni=İlk hazırlık şu adımda durdu: %1%n%nİnternet bağlantınızı kontrol edip masaüstündeki ya da Başlat menüsündeki SesVer simgesine çift tıklayın; kurulum kaldığı yerden devam eder.%n%nSorun sürerse kurulum_log_paylas.txt dosyasını hermes.agent.hamarat@gmail.com adresine gönderin. Bu kopyada ev klasörü yollarınız gizlidir; Günlüğü aç ile içine bakabilirsiniz.%n%nDosya: %2
english.OrtamHataMetni=First-time setup stopped at this step: %1%n%nCheck your internet connection, then double-click the SesVer icon on the desktop or in the Start menu; setup resumes where it left off.%n%nIf the problem persists, send the kurulum_log_paylas.txt file to hermes.agent.hamarat@gmail.com. Your home folder paths are hidden in this copy; use Open log to look inside.%n%nFile: %2
turkish.OrtamIptalMetni=İlk hazırlık durduruldu.%n%nMasaüstündeki ya da Başlat menüsündeki SesVer simgesine çift tıkladığınızda kurulum kaldığı yerden devam eder.%n%nAyrıntılar: %1
english.OrtamIptalMetni=First-time setup was stopped.%n%nDouble-click the SesVer icon on the desktop or in the Start menu and setup resumes where it left off.%n%nDetails: %1
; Ev klasörü yolları gizlenmiş kopya yazılamadıysa: dosya gösterilmez ve istenmez (ham günlük asla).
turkish.OrtamHataMetniGunluksuz=İlk hazırlık şu adımda durdu: %1%n%nİnternet bağlantınızı kontrol edip masaüstündeki ya da Başlat menüsündeki SesVer simgesine çift tıklayın; kurulum kaldığı yerden devam eder.%n%nSorun sürerse hermes.agent.hamarat@gmail.com adresine yazın ve durduğu adımı bildirin: %1
english.OrtamHataMetniGunluksuz=First-time setup stopped at this step: %1%n%nCheck your internet connection, then double-click the SesVer icon on the desktop or in the Start menu; setup resumes where it left off.%n%nIf the problem persists, write to hermes.agent.hamarat@gmail.com and mention the step where it stopped: %1
turkish.OrtamIptalMetniGunluksuz=İlk hazırlık durduruldu.%n%nMasaüstündeki ya da Başlat menüsündeki SesVer simgesine çift tıkladığınızda kurulum kaldığı yerden devam eder.
english.OrtamIptalMetniGunluksuz=First-time setup was stopped.%n%nDouble-click the SesVer icon on the desktop or in the Start menu and setup resumes where it left off.
; --- Gizlilik ve güncelleme denetimi sayfası (SignPath: kurulumda gizlilik özeti + kapatma seçeneği) ---
turkish.GizlilikSayfaBaslik=Gizlilik ve güncelleme denetimi
english.GizlilikSayfaBaslik=Privacy and update check
turkish.GizlilikSayfaAciklama=SesVer internete ne zaman bağlanır?
english.GizlilikSayfaAciklama=When does SesVer connect to the internet?
turkish.GizlilikOzeti=SesVer bilgisayarınızda çalışır; metinleriniz, kayıtlarınız ve sesleriniz hiçbir yere gönderilmez. Hesap, telemetri ve analitik yoktur.%n%nAşağıdaki güncelleme denetimi dışında internete yalnız şunlar için bağlanır: kurulum ve paketleri değiştiren güncellemeler (Python, paketler; NVIDIA kartta PyTorch, gerekirse açılışta da), Hugging Face'ten ses modeli (ilk üretimde indirme; sabit model sürümü, sonra önbellekten), yazıya dökme modeli ve sizin başlattığınız indirmeler. Hata raporu otomatik gönderilmez.
english.GizlilikOzeti=SesVer runs on your computer; your texts, recordings and audio are never sent anywhere. No account, telemetry or analytics.%n%nApart from the update check below, it connects to the internet only for: setup and updates that change its packages (Python, packages; PyTorch on NVIDIA cards, at startup too if needed), the voice model from Hugging Face (downloaded on the first generation; fixed model revision, then used from the cache), the transcription model and downloads you start yourself. Error reports are never sent automatically.
turkish.GuncellemeSecenegi=Açılışta güncellemeleri denetle
english.GuncellemeSecenegi=Check for updates at startup
turkish.GuncellemeAciklama=İşaretliyse SesVer her açılışta GitHub'a yeni sürüm olup olmadığını sorar. Yalnız sürüm bilgisi alınır; GitHub IP adresinizi görür. Bu seçimi sonra Ayarlar sekmesinden de değiştirebilirsiniz.
english.GuncellemeAciklama=If checked, SesVer asks GitHub at every start whether a new version exists. Only version information is fetched; GitHub sees your IP address. You can change this later in the Settings tab.
turkish.GizlilikBaglantisi=Gizlilik politikasının tamamı: github.com/hamarat52/sesver#privacy-policy
english.GizlilikBaglantisi=Full privacy policy: github.com/hamarat52/sesver#privacy-policy
turkish.GunluguAc=Günlüğü aç
english.GunluguAc=Open log
turkish.GunlukAcilamadi=Günlük açılamadı: %1%n%n%2
english.GunlukAcilamadi=Could not open the log: %1%n%n%2
; --- Kaldırma: indirilen bileşenleri (python-embed, .venv) saklama sorusu ---
turkish.KaldirSaklaBaslik=İndirilen bileşenler saklansın mı?
english.KaldirSaklaBaslik=Keep the downloaded components?
turkish.KaldirSaklaMetni=SesVer'in indirdiği Python ortamı ve paketler (yaklaşık %1 GB) şu klasörde duruyor:%n%2%n%nSaklarsanız SesVer'i aynı klasöre yeniden kurduğunuzda bunlar yeniden indirilmez. Seslerim ve outputs klasörleri her iki durumda da korunur.
english.KaldirSaklaMetni=The Python environment and packages SesVer downloaded (about %1 GB) are in this folder:%n%2%n%nIf you keep them, reinstalling SesVer to the same folder will not download them again. Your voices (Seslerim) and the outputs folder are kept either way.
turkish.KaldirSaklaDugmesi=Sakla
english.KaldirSaklaDugmesi=Keep
turkish.KaldirSaklaNotu=Yeniden kurulumda indirme olmaz. Sonra silmek için klasörü elle silebilirsiniz.
english.KaldirSaklaNotu=No download when you reinstall. To remove them later, delete the folder yourself.
turkish.KaldirSilDugmesi=Sil
english.KaldirSilDugmesi=Delete
turkish.KaldirSilNotu=%1 GB yer açılır; yeniden kurulumda yaklaşık 3 GB yeniden iner.
english.KaldirSilNotu=Frees %1 GB; about 3 GB is downloaded again when you reinstall.

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
; Kurulum kilitleri: WINDOWS_BASLAT.bat paketleri yalnız bunlardan, pip --require-hashes ile kurar.
Source: "{#SrcRoot}\kilit\*.txt"; DestDir: "{app}\kilit"; Flags: ignoreversion
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
; (voices\seslerim\, outputs\) bilerek listede YOK. İndirilen bileşenler (python-embed\,
; .venv\) da burada değil: kullanıcının seçimine göre [Code] IndirilenBilesenleriSil siler
; (bkz. CurUninstallStepChanged); [UninstallDelete] koşula bağlanamaz.
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
; Sihirbazın hata/iptalde yazdığı, ev klasörü yolları gizli kopya (destek için gönderilir).
Type: files; Name: "{app}\kurulum_log_paylas.txt"
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
  // Kullanıcıya gönderilmesi söylenen, ev klasörü yolları gizlenmiş kopya ve maske.
  OrtamPaylasGunlukDosyasi = 'kurulum_log_paylas.txt';
  OrtamEvMaskesi = '<ev>';
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
  // Bat saniyeler içinde PID'ini ve "0/6|..." satırını yazar. Bu sürede ikisi de
  // yoksa başlatma ölü/askıda sayılır (sihirbaz sonsuza dek beklemez).
  OrtamIlkSinyalSn = 180;
  // kernel32: PROCESS_QUERY_LIMITED_INFORMATION ve STILL_ACTIVE.
  OrtamSurecSorguErisimi = $1000;
  OrtamSurecCalisiyor = 259;

  // --- Açılışta güncelleme denetimi (uygulamanın Ayarlar'daki aynı seçeneği) ---
  // Uygulama bu ayarı {app}\ayarlar.json'daki "guncelleme_kontrolu" anahtarından okur
  // (guncelleme.py AYAR_ANAHTARI; yalnız JSON false kapalıdır). Sihirbaz yalnız kullanıcı
  // seçimi değiştirdiyse yazar: yeniden kurulum/güncelleme önceki seçimi ezmez. Sessiz
  // kurulumda yalnız /GUNCELLEMEDENETIMI=0|1 verilirse yazılır. Kurallar ve Python karşılığı:
  // tools/kurulum_durum_bicimi.py (pascal_guncelleme_*).
  AyarDosyasi = 'ayarlar.json';
  GuncellemeAyarAnahtari = 'guncelleme_kontrolu';
  GizlilikPolitikasiAdresi = '{#AppURL}#privacy-policy';
  // ayarlar.json'un biçimi (GuncellemeYazimBicimi). Uygulamanın yazdığı biçim dışındaki bir
  // dosya yerinde düzenlenmez: bozuksa önce olduğu gibi yedeklenir (uygulama da aynı adla
  // yedekler: i18n._keep_unreadable), anahtarın değeri boolean değilse dosyaya dokunulmaz.
  AyarYok = 0;
  AyarTanidik = 1;
  AyarBozuk = 2;
  AyarDegerBeklenmedik = 3;
  AyarYedekEki = '.bozuk';
  AyarYedekSiniri = 20;

  // --- Kaldırma: indirilen bileşenler (python-embed, .venv) ---
  // Sessiz kaldırmada varsayılan silmedir (CI/otomasyon için eski davranış); bu parametre
  // verilirse sessiz kaldırmada da saklanır. Etkileşimli kaldırmada kullanıcıya sorulur.
  BilesenSaklaParametresi = '/BILESENLERISAKLA';
  // Bayt → GB (onda bir hassasiyet; 1024^3).
  BirGB = 1073741824;

type
  TOrtamSonuc = (osDenenmedi, osTamam, osHata, osIptal);

var
  OrtamSonuc: TOrtamSonuc;
  // Kaldırma: indirilen bileşenler klasörde kalsın mı (InitializeUninstall / CurUninstallStepChanged).
  BilesenleriSakla: Boolean;
  OrtamHataAdimi: String;
  OrtamIptalIstendi: Boolean;
  OrtamSayfasi: TOutputProgressWizardPage;
  OrtamIptalDugmesi: TNewButton;
  OrtamNotuEtiketi: TNewStaticText;
  GunlukDugmesi: TNewButton;
  // Bu kurulumda kurulum_log_paylas.txt yazıldı mı (eski bir denemeden kalan kopya sayılmaz).
  PaylasGunlukHazir: Boolean;
  GuncellemeSayfasi: TWizardPage;
  GuncellemeKutusu: TNewCheckBox;
  // Kutunun ilk değeri hangi kurulum klasörünün ayarlar.json'undan okundu ('' = henüz okunmadı).
  GuncellemeKutusuKlasoru: String;

// BOOL dönüşleri Boolean: Pascal Script'te BOOL (LongBool) 'and' ile Boolean'a karışınca 'Type mismatch' verir.
function OpenProcess(dwDesiredAccess: DWORD; bInheritHandle: BOOL; dwProcessId: DWORD): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function GetExitCodeProcess(hProcess: THandle; var lpExitCode: DWORD): Boolean;
  external 'GetExitCodeProcess@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): Boolean;
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
  // Satır '#' ile başlamamalı: ISPP onu önişlemci yönergesi sanıyor.
  SaveStringToFile(ExpandConstant('{app}\') + OrtamGunlukDosyasi,
    '' + #13#10 + '[SIHIRBAZ] ' + Satir + #13#10, True);
end;

// --- Paylaşılabilir günlük (destek e-postası için) ---
// kurulum_log.txt pip/cmd çıktısıdır ve C:\Users\<ad>\... yolları içerir. Kullanıcıya
// gönderilmesi söylenen dosya, buradan üretilen kurulum_log_paylas.txt'dir. Kurallar
// tools/kurulum_durum_bicimi.py'deki pascal_gunluk_maskele ile birebir aynıdır;
// tests/test_windows_kurulum.py ikisinin aynı parçaları taşıdığını sınar.

// Metindeki Bul'un tüm geçişlerini (büyük/küçük harf duyarsız) Yeni ile değiştirir.
function HarfDuyarsizDegistir(const Metin, Bul, Yeni: String): String;
var
  Kalan, Kucuk, KucukBul: String;
  P: Integer;
begin
  Result := '';
  Kalan := Metin;
  if Bul = '' then
  begin
    Result := Kalan;
    Exit;
  end;
  // AnsiLowercase (CharLowerBuff) ASCII dışı harfleri de küçültür ve her UTF-16 birimini
  // tek birime çevirir: uzunluk ve konumlar korunur. pip Windows yollarını küçük harfle
  // yazar (c:\users\şükrü...); USERPROFILE (C:\Users\Şükrü) yine eşleşir (bulgu B).
  KucukBul := AnsiLowercase(Bul);
  Kucuk := AnsiLowercase(Kalan);
  P := Pos(KucukBul, Kucuk);
  while P > 0 do
  begin
    Result := Result + Copy(Kalan, 1, P - 1) + Yeni;
    Delete(Kalan, 1, P - 1 + Length(Bul));
    Delete(Kucuk, 1, P - 1 + Length(Bul));
    P := Pos(KucukBul, Kucuk);
  end;
  Result := Result + Kalan;
end;

// Küçük harfli metinde ilk ':\users\', ':\\users\\' ya da ':/users/' geçişinin
// konumu (yoksa 0); Uzunluk o işaretin uzunluğu.
function IlkEvIsareti(const Kucuk: String; var Uzunluk: Integer): Integer;
var
  Isaretler: TArrayOfString;
  I, P: Integer;
begin
  SetArrayLength(Isaretler, 3);
  Isaretler[0] := ':\users\';
  Isaretler[1] := ':\\users\\';
  Isaretler[2] := ':/users/';
  Result := 0;
  Uzunluk := 0;
  for I := 0 to GetArrayLength(Isaretler) - 1 do
  begin
    P := Pos(Isaretler[I], Kucuk);
    if (P > 0) and ((Result = 0) or (P < Result)) then
    begin
      Result := P;
      Uzunluk := Length(Isaretler[I]);
    end;
  end;
end;

// Her "X:\Users\<ad>" (ayırıcı \, \\ ya da /) <ev> olur. Ad; bir sonraki ayırıcıya,
// tırnağa, < > | karakterine, sekmeye ya da satır sonuna kadardır (boşluklu adlar dahil).
function EvYollariniMaskele(const Metin: String): String;
var
  Kalan, Kucuk, Bitis: String;
  P, Uzunluk, Bas, Son: Integer;
begin
  Result := '';
  Kalan := Metin;
  Kucuk := Lowercase(Kalan);
  Bitis := '\/"''<>|' + #9 + #10 + #13;
  P := IlkEvIsareti(Kucuk, Uzunluk);
  while P > 0 do
  begin
    Bas := P;
    if P > 1 then
      if (Kucuk[P - 1] >= 'a') and (Kucuk[P - 1] <= 'z') then
        Bas := P - 1;
    Son := P + Uzunluk;
    while (Son <= Length(Kalan)) and (Pos(Copy(Kalan, Son, 1), Bitis) = 0) do
      Son := Son + 1;
    Result := Result + Copy(Kalan, 1, Bas - 1) + OrtamEvMaskesi;
    Delete(Kalan, 1, Son - 1);
    Delete(Kucuk, 1, Son - 1);
    P := IlkEvIsareti(Kucuk, Uzunluk);
  end;
  Result := Result + Kalan;
end;

// Önce ev klasörünün kendisi (USERPROFILE, / ayırıcılı biçimi ve kısa 8.3 adı; profil
// X:\Users dışında olsa da), sonra genel "X:\Users\<ad>" kalıbı <ev> olur.
function GunlukMaskele(const Metin, Ev: String): String;
var
  Egik, Kisa: String;
begin
  Result := Metin;
  if Length(Ev) > 3 then
  begin
    Egik := Ev;
    StringChangeEx(Egik, '\', '/', True);
    Kisa := GetShortName(Ev);
    Result := HarfDuyarsizDegistir(Result, Ev, OrtamEvMaskesi);
    Result := HarfDuyarsizDegistir(Result, Egik, OrtamEvMaskesi);
    if (Kisa <> '') and (Kisa <> Ev) then
      Result := HarfDuyarsizDegistir(Result, Kisa, OrtamEvMaskesi);
  end;
  Result := EvYollariniMaskele(Result);
end;

// Baytlar katı UTF-8 mi? Python'un utf-8 çözücüsüyle aynı kurallar: C0/C1 ve F5-FF öncü
// bayt, fazla uzun biçim (E0 + <A0, F0 + <90), vekil (ED + >9F) ve U+10FFFF üstü (F4 + >8F)
// geçersizdir. Python karşılığı: tools/kurulum_durum_bicimi.py pascal_gecerli_utf8.
function GecerliUtf8(const B: AnsiString): Boolean;
var
  I, J, N, Ek, C, Alt, Ust: Integer;
begin
  Result := False;
  N := Length(B);
  I := 1;
  while I <= N do
  begin
    C := Ord(B[I]);
    Alt := $80;
    Ust := $BF;
    if C < $80 then
      Ek := 0
    else if (C >= $C2) and (C <= $DF) then
      Ek := 1
    else if (C >= $E0) and (C <= $EF) then
    begin
      Ek := 2;
      if C = $E0 then
        Alt := $A0;
      if C = $ED then
        Ust := $9F;
    end
    else if (C >= $F0) and (C <= $F4) then
    begin
      Ek := 3;
      if C = $F0 then
        Alt := $90;
      if C = $F4 then
        Ust := $8F;
    end
    else
      Exit;
    if I + Ek > N then
      Exit;
    if Ek > 0 then
    begin
      C := Ord(B[I + 1]);
      if (C < Alt) or (C > Ust) then
        Exit;
      for J := I + 2 to I + Ek do
        if (Ord(B[J]) < $80) or (Ord(B[J]) > $BF) then
          Exit;
    end;
    I := I + Ek + 1;
  end;
  Result := True;
end;

// Ham günlüğün ev klasörü yolları gizlenmiş hâli (dosyaya yazılacak baytlar). Bat günlüğü
// yalnız-kurulum kipinde UTF-8 yazar (chcp 65001 + PYTHONIOENCODING=utf-8). Günlük geçerli
// UTF-8 ise UTF-8 olarak çözülür, maskelenir ve UTF-8 yazılır: ASCII dışı kullanıcı adı da
// USERPROFILE ile aynı metin üzerinde karşılaştırılır (bulgu B). Değilse (araya ANSI çıktı
// karışmış) sistemin ANSI kod sayfasıyla çözülür ve ev klasörü hem kendi hâliyle hem UTF-8
// baytlarının ANSI okunuşuyla aranır; çıktı yine ANSI'dir (baytlar korunur).
function PaylasilabilirGunlukBaytlari(const Ham: AnsiString; const Ev: String): AnsiString;
var
  Metin, EvUtf8Okunusu, KucukEvUtf8Okunusu: String;
  EvUtf8, KucukEvUtf8: AnsiString;
begin
  if GecerliUtf8(Ham) then
    Result := Utf8Encode(GunlukMaskele(Utf8Decode(Ham), Ev))
  else
  begin
    // pip yolu küçük harfle yazar; UTF-8 baytlarının ANSI okunuşunda büyük/küçük harf
    // ilişkisi kaybolduğu için küçük harfli biçim ayrıca aranır.
    EvUtf8 := Utf8Encode(Ev);
    EvUtf8Okunusu := String(EvUtf8);
    KucukEvUtf8 := Utf8Encode(AnsiLowercase(Ev));
    KucukEvUtf8Okunusu := String(KucukEvUtf8);
    Metin := GunlukMaskele(String(Ham), EvUtf8Okunusu);
    Metin := GunlukMaskele(Metin, KucukEvUtf8Okunusu);
    Metin := GunlukMaskele(Metin, Ev);
    Result := Metin;
  end;
end;

// kurulum_log.txt'nin ev klasörü yolları gizlenmiş kopyasını kurulum_log_paylas.txt
// olarak yazar (ilk kurulum hata ya da iptalle bitince). Başarıda True; sonuç
// PaylasGunlukHazir'a da yazılır (yalnız bu kurulumda yazılan kopya gösterilir).
function PaylasilabilirGunlukYaz(): Boolean;
var
  Kaynak, Hedef: String;
  Ham: AnsiString;
begin
  Result := False;
  PaylasGunlukHazir := False;
  Kaynak := ExpandConstant('{app}\') + OrtamGunlukDosyasi;
  Hedef := ExpandConstant('{app}\') + OrtamPaylasGunlukDosyasi;
  DeleteFile(Hedef);
  if not FileExists(Kaynak) then
  begin
    Log('Paylaşılabilir günlük yazılmadı: ' + OrtamGunlukDosyasi + ' yok.');
    Exit;
  end;
  if not LoadStringFromLockedFile(Kaynak, Ham) then
  begin
    Log('Paylaşılabilir günlük yazılamadı: ' + OrtamGunlukDosyasi + ' okunamadı.');
    Exit;
  end;
  Result := SaveStringToFile(Hedef, PaylasilabilirGunlukBaytlari(Ham, GetEnv('USERPROFILE')), False);
  PaylasGunlukHazir := Result;
  if Result then
    Log('Paylaşılabilir günlük yazıldı (ev klasörü yolları gizli): ' + OrtamPaylasGunlukDosyasi)
  else
    Log('Paylaşılabilir günlük yazılamadı: ' + OrtamPaylasGunlukDosyasi);
end;

// Bitir sayfasında gösterilen ve "Günlüğü aç"ın açtığı dosya: yalnız bu kurulumda yazılan
// paylaşılabilir (maskeli) kopya. Yazılamadıysa '' döner; ham kurulum_log.txt hiçbir durumda
// gösterilmez ve Bitir metni dosya istemez (bulgu A).
function GosterilecekGunluk(): String;
begin
  Result := '';
  if PaylasGunlukHazir and FileExists(ExpandConstant('{app}\') + OrtamPaylasGunlukDosyasi) then
    Result := ExpandConstant('{app}\') + OrtamPaylasGunlukDosyasi;
end;

// --- Açılışta güncelleme denetimi: ayarlar.json okuma/yazma ---
// JSON ayrıştırıcı yok; yalnız uygulamanın yazdığı düz nesnede tek bir boolean anahtar
// okunur/değiştirilir. Python karşılıkları tools/kurulum_durum_bicimi.py'dedir.

// ayarlar.json'un ham baytları. Dosya yoksa True ve Ham = ''; var ama okunamadıysa False
// (o durumda dosyaya hiç dokunulmaz).
function AyarDosyasiniOku(const Yol: String; var Ham: AnsiString): Boolean;
begin
  Ham := '';
  Result := True;
  if FileExists(Yol) then
    Result := LoadStringFromFile(Yol, Ham);
end;

// Ham baytların metni (UTF-8; değilse ANSI).
function AyarMetni(const Ham: AnsiString): String;
begin
  if GecerliUtf8(Ham) then
    Result := Utf8Decode(Ham)
  else
    Result := String(Ham);
end;

// ayarlar.json metni. Dosya yoksa ya da okunamazsa ''.
function AyarMetniniOku(const Yol: String): String;
var
  Ham: AnsiString;
begin
  Result := '';
  if AyarDosyasiniOku(Yol, Ham) then
    Result := AyarMetni(Ham);
end;

// Metin bir JSON nesnesi gibi görünüyor mu ({ ile başlayıp } ile bitiyor). Değilse uygulama
// da dosyayı yok sayar (i18n._read_settings: bozuk dosya = boş ayar).
function AyarGovdesiGecerli(const Metin: String): Boolean;
var
  G: String;
begin
  G := Trim(Metin);
  Result := (Length(G) >= 2) and (Copy(G, 1, 1) = '{') and (Copy(G, Length(G), 1) = '}');
end;

// "guncelleme_kontrolu" anahtarının değerinin başladığı konum (1 tabanlı); yoksa 0.
function GuncellemeDegerKonumu(const Metin: String): Integer;
var
  P, I: Integer;
begin
  Result := 0;
  P := Pos('"' + GuncellemeAyarAnahtari + '"', Metin);
  if P = 0 then
    Exit;
  I := P + Length(GuncellemeAyarAnahtari) + 2;
  while (I <= Length(Metin)) and (Copy(Metin, I, 1) <= ' ') do
    I := I + 1;
  if Copy(Metin, I, 1) <> ':' then
    Exit;
  I := I + 1;
  while (I <= Length(Metin)) and (Copy(Metin, I, 1) <= ' ') do
    I := I + 1;
  Result := I;
end;

// Uygulamanın gördüğü değer (guncelleme.ayar_acik_mi): yalnız JSON false kapalıdır; dosya,
// anahtar ya da geçerli gövde yoksa açık.
function GuncellemeAyariAcikMi(const Metin: String): Boolean;
var
  P: Integer;
begin
  Result := True;
  if not AyarGovdesiGecerli(Metin) then
    Exit;
  P := GuncellemeDegerKonumu(Metin);
  if P > 0 then
    Result := Copy(Metin, P, 5) <> 'false';
end;

// I. karakter bir değerin bitişi mi (sınırlayıcı ya da metnin sonu).
function DegerSinirindaMi(const Metin: String; I: Integer): Boolean;
begin
  if I > Length(Metin) then
    Result := True
  else
    Result := Pos(Copy(Metin, I, 1), ',}] ' + #9 + #10 + #13) > 0;
end;

// Dosya yerinde düzenlenebilir mi? AyarYok: boş/yok (yeni nesne yazılır); AyarTanidik:
// uygulamanın yazdığı gibi bir nesne, anahtar yok ya da değeri true/false; AyarBozuk: nesne
// değil (uygulama da yok sayar; önce yedeklenir); AyarDegerBeklenmedik: anahtarın değeri
// true/false değil (dokunulmaz). Python karşılığı: pascal_guncelleme_yazim_bicimi.
function GuncellemeYazimBicimi(const Metin: String): Integer;
var
  P: Integer;
begin
  if Trim(Metin) = '' then
    Result := AyarYok
  else if not AyarGovdesiGecerli(Metin) then
    Result := AyarBozuk
  else
  begin
    Result := AyarTanidik;
    P := GuncellemeDegerKonumu(Metin);
    if P = 0 then
      Exit;
    if (Copy(Metin, P, 4) = 'true') and DegerSinirindaMi(Metin, P + 4) then
      Exit;
    if (Copy(Metin, P, 5) = 'false') and DegerSinirindaMi(Metin, P + 5) then
      Exit;
    Result := AyarDegerBeklenmedik;
  end;
end;

// Bozuk dosyanın yedeği için boş bir ad: ayarlar.json.bozuk, sonra .bozuk-2 ... .bozuk-20.
// Hepsi doluysa ''. Uygulamadaki karşılığı: i18n._backup_path.
function AyarYedekAdi(const Yol: String): String;
var
  N: Integer;
begin
  Result := Yol + AyarYedekEki;
  N := 2;
  while FileExists(Result) do
  begin
    if N > AyarYedekSiniri then
    begin
      Result := '';
      Exit;
    end;
    Result := Yol + AyarYedekEki + '-' + IntToStr(N);
    N := N + 1;
  end;
end;

// Metne "guncelleme_kontrolu": true|false yazar; diğer anahtarlar ve biçim korunur.
function GuncellemeAyariniYerlestir(const Metin: String; Acik: Boolean): String;
var
  Deger, Kalan: String;
  P, Son: Integer;
begin
  if Acik then
    Deger := 'true'
  else
    Deger := 'false';
  if not AyarGovdesiGecerli(Metin) then
  begin
    Result := '{' + #10 + '  "' + GuncellemeAyarAnahtari + '": ' + Deger + #10 + '}' + #10;
    Exit;
  end;
  P := GuncellemeDegerKonumu(Metin);
  if P > 0 then
  begin
    Son := P;
    while (Son <= Length(Metin)) and (Pos(Copy(Metin, Son, 1), ',}] ' + #9 + #10 + #13) = 0) do
      Son := Son + 1;
    Result := Copy(Metin, 1, P - 1) + Deger + Copy(Metin, Son, Length(Metin));
    Exit;
  end;
  P := Pos('{', Metin);
  Kalan := Copy(Metin, P + 1, Length(Metin));
  if Copy(TrimLeft(Kalan), 1, 1) = '}' then
    Result := Copy(Metin, 1, P) + #10 + '  "' + GuncellemeAyarAnahtari + '": ' + Deger + #10 + TrimLeft(Kalan)
  else
    Result := Copy(Metin, 1, P) + #10 + '  "' + GuncellemeAyarAnahtari + '": ' + Deger + ',' + Kalan;
end;

// /GUNCELLEMEDENETIMI=0|1 komut satırı parametresi: 0 ya da 1; verilmediyse/tanınmadıysa -1.
function GuncellemeParametresi(): Integer;
var
  Deger: String;
begin
  Deger := Trim(ExpandConstant('{param:GUNCELLEMEDENETIMI|}'));
  if Deger = '0' then
    Result := 0
  else if Deger = '1' then
    Result := 1
  else
    Result := -1;
end;

// Yazılacak mı? Sessiz kurulumda yalnız parametre verildiyse, etkileşimli kurulumda kutunun
// değeri. Seçim mevcut ayarla aynıysa yazılmaz: önceki seçim (Ayarlar'da değiştirilmiş olsa
// da) ezilmez. Python karşılığı: pascal_guncelleme_karari.
function GuncellemeKarari(Sessiz: Boolean; Parametre: Integer; Kutu, Mevcut: Boolean; var Yeni: Boolean): Boolean;
begin
  Result := False;
  if Sessiz then
  begin
    if Parametre < 0 then
      Exit;
    Yeni := Parametre = 1;
  end
  else
    Yeni := Kutu;
  Result := Yeni <> Mevcut;
end;

// ssPostInstall: seçimi {app}\ayarlar.json'a yansıtır (gerekirse). Dosya okunamıyorsa ya da
// anahtarın değeri beklenmedikse dokunulmaz; bozuksa önce olduğu gibi yedeklenir.
procedure GuncellemeTercihiniUygula();
var
  Yol, Yedek, Metin: String;
  Ham: AnsiString;
  Sessiz, Mevcut, Yeni: Boolean;
  Bicim: Integer;
begin
  Yol := ExpandConstant('{app}\') + AyarDosyasi;
  if not AyarDosyasiniOku(Yol, Ham) then
  begin
    Log('Açılışta güncelleme denetimi: ' + AyarDosyasi + ' okunamadı, dosyaya dokunulmadı.');
    Exit;
  end;
  Metin := AyarMetni(Ham);
  Mevcut := GuncellemeAyariAcikMi(Metin);
  // Sayfa hiç gösterilmediyse (sessiz kurulum) kutu değil, yalnız parametre geçerlidir.
  Sessiz := WizardSilent() or (GuncellemeKutusuKlasoru = '');
  if not GuncellemeKarari(Sessiz, GuncellemeParametresi(), GuncellemeKutusu.Checked, Mevcut, Yeni) then
  begin
    Log('Açılışta güncelleme denetimi ayarı değişmedi (' + IntToStr(Ord(Mevcut)) + ').');
    Exit;
  end;
  Bicim := GuncellemeYazimBicimi(Metin);
  if Bicim = AyarDegerBeklenmedik then
  begin
    Log('Açılışta güncelleme denetimi: ' + GuncellemeAyarAnahtari + ' değeri true/false değil, dosyaya dokunulmadı.');
    Exit;
  end;
  if Bicim = AyarBozuk then
  begin
    Yedek := AyarYedekAdi(Yol);
    if (Yedek = '') or not SaveStringToFile(Yedek, Ham, False) then
    begin
      Log('Açılışta güncelleme denetimi: bozuk ' + AyarDosyasi + ' yedeklenemedi, dosyaya dokunulmadı.');
      Exit;
    end;
    Log('Bozuk ' + AyarDosyasi + ' olduğu gibi yedeklendi: ' + ExtractFileName(Yedek));
  end;
  if SaveStringToFile(Yol, Utf8Encode(GuncellemeAyariniYerlestir(Metin, Yeni)), False) then
    Log('Açılışta güncelleme denetimi ayarı yazıldı: ' + AyarDosyasi + ' ' + GuncellemeAyarAnahtari + '=' + IntToStr(Ord(Yeni)))
  else
    Log('Açılışta güncelleme denetimi ayarı yazılamadı: ' + Yol);
end;

// Gizlilik sayfası açılınca kutunun ilk değeri: parametre, yoksa kurulum klasöründeki mevcut ayar.
procedure GuncellemeKutusunuHazirla();
var
  Klasor: String;
  Parametre: Integer;
begin
  Klasor := WizardDirValue;
  if Klasor = GuncellemeKutusuKlasoru then
    Exit;  // geri/ileri gezinmede kullanıcının seçimi korunur
  GuncellemeKutusuKlasoru := Klasor;
  Parametre := GuncellemeParametresi();
  if Parametre >= 0 then
    GuncellemeKutusu.Checked := Parametre = 1
  else
    GuncellemeKutusu.Checked := GuncellemeAyariAcikMi(AyarMetniniOku(AddBackslash(Klasor) + AyarDosyasi));
end;

procedure GizlilikBaglantisiClick(Sender: TObject);
var
  Hata: Integer;
begin
  ShellExecAsOriginalUser('open', GizlilikPolitikasiAdresi, '', '', SW_SHOWNORMAL, ewNoWait, Hata);
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
  Gunluk := GosterilecekGunluk();
  if Gunluk = '' then
    Exit;  // maskeli kopya yoksa düğme zaten gizlidir; ham günlük açılmaz
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
    // ">nul 2>&1" dıştaki cmd'nin "start" komutuna uygulanır; başlatılan cmd.exe bu
    // tutamaçları devralır. Olmazsa ExecAndLogOutput'un çıktı borusunu devralır: dış
    // cmd ~20 ms'de çıkar, Inno borunun okuma ucunu kapatır ve bat ilk "echo"yu geçemeden, hiçbir
    // dosya (günlük/PID/durum) yazmadan biter; sihirbaz durum satırını sonsuza dek bekler.
    // Kanıt: CI 41073828284 (askı) ve 41075564237 deneyi (boru kapalı: bat ölür; boru
    // açık ya da >nul: bat sonuna dek çalışır).
    Komut := '/d /c start "" /b "' + Cmd + '" /d /c call "' + App + '\WINDOWS_BASLAT.bat" ' +
      OrtamYalnizKurulumArg + ' >nul 2>&1';
    Log('İlk kurulum başlatılıyor: ' + Cmd + ' ' + Komut);
    Basladi := False;
    try
      Basladi := ExecAndLogOutput(Cmd, Komut, App, SW_HIDE, ewWaitUntilTerminated, RC, @BaslaticiCiktisi);
      Log('İlk kurulum başlatıcısı döndü: çıkış kodu ' + IntToStr(RC));
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

      // Başlatma ölü doğduysa (ne PID ne durum satırı) sonsuza dek beklenmez.
      if (Pid = 0) and (SonSatir = '') and (Integer((GetTickCount - Baslangic) div 1000) >= OrtamIlkSinyalSn) then
      begin
        OrtamSureciniDurdur(0);
        OrtamSonuc := osHata;
        OrtamHataAdimi := FmtMessage(CustomMessage('OrtamYanitYok'), [IntToStr(OrtamIlkSinyalSn)]);
        OrtamGunlugeEkle('Kurulum baslaticisi ' + IntToStr(OrtamIlkSinyalSn) +
          ' sn icinde ne PID ne durum satiri yazdi; ilk kurulum baslatilamadi.');
        Break;
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
var
  GizlilikOzetiEtiketi, GuncellemeNotu, GizlilikBaglantisi: TNewStaticText;
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

  // Gizlilik ve güncelleme denetimi sayfası (ek görevlerden sonra). SignPath koşulu: kullanıcı
  // verisi aktarılmasa da ağ erişimi kurulumda anlatılır ve kapatma seçeneği sunulur.
  GuncellemeSayfasi := CreateCustomPage(wpSelectTasks, CustomMessage('GizlilikSayfaBaslik'),
    CustomMessage('GizlilikSayfaAciklama'));

  GizlilikOzetiEtiketi := TNewStaticText.Create(GuncellemeSayfasi);
  GizlilikOzetiEtiketi.Parent := GuncellemeSayfasi.Surface;
  GizlilikOzetiEtiketi.AutoSize := False;
  GizlilikOzetiEtiketi.WordWrap := True;
  GizlilikOzetiEtiketi.Width := GuncellemeSayfasi.SurfaceWidth;
  GizlilikOzetiEtiketi.Caption := CustomMessage('GizlilikOzeti');
  WizardForm.AdjustLabelHeight(GizlilikOzetiEtiketi);

  GuncellemeKutusu := TNewCheckBox.Create(GuncellemeSayfasi);
  GuncellemeKutusu.Parent := GuncellemeSayfasi.Surface;
  GuncellemeKutusu.Top := GizlilikOzetiEtiketi.Top + GizlilikOzetiEtiketi.Height + ScaleY(14);
  GuncellemeKutusu.Width := GuncellemeSayfasi.SurfaceWidth;
  GuncellemeKutusu.Height := ScaleY(17);
  GuncellemeKutusu.Caption := CustomMessage('GuncellemeSecenegi');
  // Varsayılan açık; sayfa açılınca mevcut ayar ya da parametreyle güncellenir.
  GuncellemeKutusu.Checked := True;

  GuncellemeNotu := TNewStaticText.Create(GuncellemeSayfasi);
  GuncellemeNotu.Parent := GuncellemeSayfasi.Surface;
  GuncellemeNotu.AutoSize := False;
  GuncellemeNotu.WordWrap := True;
  GuncellemeNotu.Left := ScaleX(18);
  GuncellemeNotu.Top := GuncellemeKutusu.Top + GuncellemeKutusu.Height + ScaleY(4);
  GuncellemeNotu.Width := GuncellemeSayfasi.SurfaceWidth - ScaleX(18);
  GuncellemeNotu.Caption := CustomMessage('GuncellemeAciklama');
  WizardForm.AdjustLabelHeight(GuncellemeNotu);

  GizlilikBaglantisi := TNewStaticText.Create(GuncellemeSayfasi);
  GizlilikBaglantisi.Parent := GuncellemeSayfasi.Surface;
  GizlilikBaglantisi.Top := GuncellemeNotu.Top + GuncellemeNotu.Height + ScaleY(14);
  GizlilikBaglantisi.Caption := CustomMessage('GizlilikBaglantisi');
  GizlilikBaglantisi.Cursor := crHand;
  GizlilikBaglantisi.OnClick := @GizlilikBaglantisiClick;
  // Yazı tipi Parent'tan sonra değiştirilir (varsayılanlar önce devralınsın).
  GizlilikBaglantisi.Font.Style := GizlilikBaglantisi.Font.Style + [fsUnderline];
  GizlilikBaglantisi.Font.Color := clBlue;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then
    Exit;
  // Açılışta güncelleme denetimi seçimi ilk kurulumdan (ve onun atlanmasından) bağımsızdır.
  GuncellemeTercihiniUygula();
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
        PaylasilabilirGunlukYaz();
      end;
  else
    begin
      Log('İlk kurulum tamamlanamadı: ' + OrtamHataAdimi);
      ShortcutsBackToLauncher();
      PaylasilabilirGunlukYaz();
    end;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Metin, Gunluk: String;
  Fark: Integer;
begin
  if CurPageID = GuncellemeSayfasi.ID then
  begin
    GuncellemeKutusunuHazirla();
    Exit;
  end;
  if (CurPageID <> wpFinished) or ((OrtamSonuc <> osHata) and (OrtamSonuc <> osIptal)) then
    Exit;
  Gunluk := GosterilecekGunluk();
  // Maskeli kopya yazılamadıysa metin dosya göstermez/istemez ve "Günlüğü aç" gizli kalır.
  if OrtamSonuc = osHata then
  begin
    if Gunluk <> '' then
      Metin := FmtMessage(CustomMessage('OrtamHataMetni'), [OrtamHataAdimi, Gunluk])
    else
      Metin := FmtMessage(CustomMessage('OrtamHataMetniGunluksuz'), [OrtamHataAdimi]);
  end
  else if Gunluk <> '' then
    Metin := FmtMessage(CustomMessage('OrtamIptalMetni'), [Gunluk])
  else
    Metin := CustomMessage('OrtamIptalMetniGunluksuz');
  WizardForm.FinishedHeadingLabel.Caption := CustomMessage('OrtamBitirBaslikEksik');
  Fark := WizardForm.AdjustLabelHeight(WizardForm.FinishedHeadingLabel);
  WizardForm.FinishedLabel.Top := WizardForm.FinishedLabel.Top + Fark;
  WizardForm.FinishedLabel.Caption := Metin;
  WizardForm.AdjustLabelHeight(WizardForm.FinishedLabel);
  GunlukDugmesi.Left := WizardForm.FinishedLabel.Left;
  GunlukDugmesi.Top := WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height + ScaleY(12);
  GunlukDugmesi.Visible := Gunluk <> '';
end;

// Sessiz /ORTAMKUR kurulumunda ilk kurulum tamamlanamadıysa (CI) 0 dışı çıkış kodu.
function GetCustomSetupExitCode(): Integer;
begin
  Result := 0;
  if WizardSilent() and ((OrtamSonuc = osHata) or (OrtamSonuc = osIptal)) then
    Result := OrtamHataCikisKodu;
end;

// ---------------------------------------------------------------- kaldırma
// İndirilen bileşenler: WINDOWS_BASLAT.bat'ın python-embed\ (taşınabilir Python + ~3 GB paket)
// ve python-embed indirilemezse kullandığı yedek .venv\. Aynı klasöre yeniden kurulumda bat
// kurulum işaretini (sesver_kurulum_tamam.txt) aynı bulursa hiçbir şey indirmez.

// Klasörün toplam boyutu (bayt). Bağlantı noktalarına (reparse point) girilmez: döngü olmasın,
// başka diske taşılmış klasör sayılmasın.
function KlasorBoyutu(const Klasor: String): Int64;
var
  K: TFindRec;
begin
  Result := 0;
  if FindFirst(Klasor + '\*', K) then
  begin
    try
      repeat
        if (K.Name <> '.') and (K.Name <> '..') then
        begin
          if K.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
          begin
            if K.Attributes and FILE_ATTRIBUTE_REPARSE_POINT = 0 then
              Result := Result + KlasorBoyutu(Klasor + '\' + K.Name);
          end
          else
          begin
            Result := Result + K.SizeLow;
            if K.SizeHigh > 0 then
              Result := Result + Int64(K.SizeHigh) * 65536 * 65536;
          end;
        end;
      until not FindNext(K);
    finally
      FindClose(K);
    end;
  end;
end;

// "3,1" (Türkçe) / "3.1" (İngilizce): onda bir hassasiyetli GB.
function GBMetni(Bayt: Int64): String;
var
  Onda: Int64;
  Ayirici: String;
begin
  Onda := (Bayt * 10 + BirGB div 2) div BirGB;
  if ActiveLanguage = 'english' then
    Ayirici := '.'
  else
    Ayirici := ',';
  Result := IntToStr(Onda div 10) + Ayirici + IntToStr(Onda mod 10);
end;

function IndirilenBilesenBoyutu(const App: String): Int64;
begin
  Result := 0;
  if DirExists(App + '\python-embed') then
    Result := Result + KlasorBoyutu(App + '\python-embed');
  if DirExists(App + '\.venv') then
    Result := Result + KlasorBoyutu(App + '\.venv');
end;

// Etkileşimli kaldırmada soru. True = sakla. İletişim kutusu açılamazsa (0) saklanır: veri kaybı yok.
function BilesenSaklamaSorusu(const App: String): Boolean;
var
  Boyut: String;
  Cevap: Integer;
begin
  Boyut := GBMetni(IndirilenBilesenBoyutu(App));
  Cevap := TaskDialogMsgBox(CustomMessage('KaldirSaklaBaslik'),
    FmtMessage(CustomMessage('KaldirSaklaMetni'), [Boyut, App]), mbConfirmation, MB_YESNO,
    [CustomMessage('KaldirSaklaDugmesi') + #13#10 + CustomMessage('KaldirSaklaNotu'),
     CustomMessage('KaldirSilDugmesi') + #13#10 + FmtMessage(CustomMessage('KaldirSilNotu'), [Boyut])], 0);
  Result := Cevap <> IDNO;
end;

procedure IndirilenBilesenleriSil(const App: String);
begin
  if DirExists(App + '\python-embed') and not DelTree(App + '\python-embed', True, True, True) then
    Log('Kaldirma: python-embed silinemedi (kullanimda olabilir)');
  if DirExists(App + '\.venv') and not DelTree(App + '\.venv', True, True, True) then
    Log('Kaldirma: .venv silinemedi (kullanimda olabilir)');
  // Kalan bir şey yoksa kurulum klasörü de kalkar (kullanıcı verisi varsa klasör durur).
  RemoveDir(App);
end;

function InitializeUninstall(): Boolean;
begin
  // Sessiz kaldırma: varsayılan sil (eski davranış); /BILESENLERISAKLA ile sakla.
  BilesenleriSakla := UninstallSilent() and KomutSatirindaVar(BilesenSaklaParametresi);
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  App: String;
begin
  App := ExpandConstant('{app}');
  // usUninstall: kullanıcı kaldırmayı onayladı, dosyalar henüz silinmedi. Soru yalnız burada.
  if (CurUninstallStep = usUninstall) and not UninstallSilent() and
     (DirExists(App + '\python-embed') or DirExists(App + '\.venv')) then
    BilesenleriSakla := BilesenSaklamaSorusu(App);
  // usPostUninstall: SesVer dosyaları silindi; şimdi seçime göre bileşenler.
  if CurUninstallStep = usPostUninstall then
  begin
    if BilesenleriSakla then
      Log('Kaldirma: indirilen bilesenler saklandi (python-embed, .venv): ' + App)
    else
    begin
      Log('Kaldirma: indirilen bilesenler siliniyor (python-embed, .venv)');
      IndirilenBilesenleriSil(App);
    end;
  end;
end;
