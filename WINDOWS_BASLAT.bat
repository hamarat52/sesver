@echo off
echo [SesVer baslatici calisiyor]
REM SesVer başlatıcı — Windows. Çift tıklayın.
REM İlk çalıştırmada ortamı kurar; sonrakilerde doğrudan açar.
REM Not: parantezli if bloklari bilerek kullanilmiyor; blok icindeki ")" ve
REM blok icinde errorlevel acilimi klasik batch tuzaklaridir. Duz satir + goto kullanilir.
setlocal
cd /d "%~dp0"

REM ---- Yalniz kurulum kipi (Windows kurulum sihirbazi kullanir) ----
REM SESVER_YALNIZ_KURULUM=1 ortam degiskeni ya da /yalniz-kurulum argumani ile:
REM ilk kurulum/esitleme yapilir, SesVer BASLATILMAZ, hicbir pause beklenmez;
REM basarida 0, hatada 1 ile cikilir. Her adimda kurulum_durum.txt dosyasina tek
REM satir yazilir: "<adim>/<toplam>|<ASCII kisa metin>", son satir "tamam" ya da
REM "hata:<ADIM>" (bicim tek yerde: tools/kurulum_durum_bicimi.py; sihirbaz
REM windows\SesVer.iss ayni bicimi okur). Tum cikti kurulum_log.txt dosyasina gider;
REM sihirbazin iptal edebilmesi icin bu cmd.exe surecinin PID'i kurulum_pid.txt'ye
REM yazilir. Normal (cift tik) calismada bu bolum atlanir ve :durum hicbir sey yazmaz.
set "SV_TOPLAM_ADIM=6"
set "SV_ADIM_NO=0"
set "SV_YK=0"
if /i "%~1"=="/yalniz-kurulum" set "SESVER_YALNIZ_KURULUM=1"
if "%SESVER_YALNIZ_KURULUM%"=="1" set "SV_YK=1"
if not "%SV_YK%"=="1" goto :yk_hazir
REM 32 bit bir cagiran (32 bit kurulum programi) 32 bit cmd.exe acmis olabilir; o
REM zaman System32 (nvidia-smi, tar, curl) SysWOW64'e yonlenir ve ekran karti
REM gorulmez. Bu durumda betik 64 bit cmd.exe ile yeniden calistirilir.
if not defined PROCESSOR_ARCHITEW6432 goto :yk_mimari_tamam
if not exist "%SystemRoot%\Sysnative\cmd.exe" goto :yk_mimari_tamam
"%SystemRoot%\Sysnative\cmd.exe" /d /c call "%~f0" /yalniz-kurulum
exit /b %errorlevel%
:yk_mimari_tamam
REM Betik kendini bir kez daha cagirir; tum ciktisi kurulum_log.txt'ye yazilir.
if "%SESVER_YK_GUNLUK%"=="1" goto :yk_gunluk_acik
set "SESVER_YK_GUNLUK=1"
call "%~f0" /yalniz-kurulum >"kurulum_log.txt" 2>&1
exit /b %errorlevel%
:yk_gunluk_acik
echo [BILGI] Yalniz kurulum kipi: SesVer kurulumdan sonra baslatilmaz.
del /f /q "kurulum_pid.txt" >nul 2>nul
REM PowerShell'in ust sureci bu betigi calistiran cmd.exe'dir (dogrudan cagri).
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "(Get-CimInstance Win32_Process -Filter ('ProcessId=' + $PID)).ParentProcessId" >"kurulum_pid.txt" 2>nul
if errorlevel 1 echo [UYARI] Surec numarasi yazilamadi; sihirbaz iptal dugmesi yedek yontemi kullanir.
call :durum 0 "Basliyor"
:yk_hazir

REM Python ortami secim sirasi:
REM  1. python-embed\python.exe: bu klasore indirilmis tasinabilir Python
REM     - astral-sh/python-build-standalone. Kurulum ve venv gerekmez; paketler
REM     dogrudan onun site-packages klasorune kurulur.
REM  2. Kurulumu tamamlanmis eski .venv: onceki surumle kurmus kullanicilar
REM     her seyi yeniden indirmesin diye aynen kullanilir.
REM  3. Ikisi de yoksa python-embed indirilir - ilk calistirma.
REM  4. Indirme veya cikarma basarisizsa eski yontem: sistemdeki py/python + .venv.
REM Sistemde kurulu baska bir Python'un ayarlari bu ortami bozmasin:
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"

set "EMBED_PY=.\python-embed\python.exe"
REM voxcpm requirements.txt'te degil (--no-deps ile ayri kurulur); pini burada.
REM macos_ortak.sh'teki VOXCPM_SURUM ile ayni tutun.
set "VOXCPM_SURUM=2.0.3"
set "PYEXE="
set "MARK="

if not exist "%EMBED_PY%" goto :embed_yok
"%EMBED_PY%" --version >nul 2>nul
if not errorlevel 1 goto :embed_kullan
echo [UYARI] python-embed klasorundeki Python calismiyor; silinip yeniden indirilecek.
rd /s /q "python-embed" >nul 2>nul
:embed_yok
if exist ".venv\Scripts\python.exe" if exist ".venv\sesver_kurulum_tamam.txt" goto :venv_kullan
call :durum 1 "Python indiriliyor"
call :embed_kur
if not errorlevel 1 goto :embed_kullan
echo.
echo [UYARI] Gomulu Python hazirlanamadi; bilgisayarda kurulu Python araniyor...
goto :sistem_python

:embed_kullan
set "PYEXE=%EMBED_PY%"
set "MARK=python-embed\sesver_kurulum_tamam.txt"
echo Kullanilan Python: python-embed - SesVer'e ozel tasinabilir Python
"%PYEXE%" --version
goto :kurulum

:venv_kullan
set "PYEXE=.\.venv\Scripts\python.exe"
set "MARK=.venv\sesver_kurulum_tamam.txt"
goto :kurulum

:sistem_python
REM ---- Yedek yontem: sistem Python + .venv ----
call :durum 1 "Bilgisayardaki Python araniyor"
REM Python secimi: once "py -3.11", sonra "py", sonra "python".
REM where ile varlik, --version ile gercekten calistigi kontrol edilir
REM (Microsoft Store'un sahte python.exe kisayolu where'de gorunur ama calismaz).
set "PY="
where py >nul 2>nul || goto :py_yok
py -3.11 --version >nul 2>nul && set "PY=py -3.11" && goto :py_bulundu
py --version >nul 2>nul && set "PY=py" && goto :py_bulundu
:py_yok
where python >nul 2>nul || goto :python_yok
python --version >nul 2>nul && set "PY=python" && goto :py_bulundu
:python_yok
set "ADIM=Python hazirlama"
if "%SV_YK%"=="1" goto :yk_hata
echo.
echo [HATA] Python hazirlanamadi.
echo Otomatik Python indirmesi basarisiz oldu ve bilgisayarda calisan Python bulunamadi.
echo Once internet baglantinizi kontrol edip WINDOWS_BASLAT.bat dosyasini tekrar calistirin.
echo Sorun devam ederse Python 3.10-3.12 kurun: https://www.python.org/downloads/
echo Kurulumda "Add python.exe to PATH" kutusunu isaretleyin.
echo Microsoft Store kisayolu sorun cikariyorsa: Ayarlar - Uygulamalar -
echo Uygulama yurutme diger adlari - python.exe/python3.exe kapatin.
pause
exit /b 1
:py_bulundu
echo Kullanilan Python komutu: %PY%
%PY% --version
%PY% -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" || echo [UYARI] Onerilen surum Python 3.10-3.12; kurulum basarisiz olabilir.
set "PYEXE=.\.venv\Scripts\python.exe"
set "MARK=.venv\sesver_kurulum_tamam.txt"
set "ADIM=sanal ortam olusturma: %PY% -m venv .venv"
if exist "%PYEXE%" goto :kurulum
%PY% -m venv .venv
if errorlevel 1 goto :hata
if not exist "%PYEXE%" goto :hata

:kurulum
REM Isaret dosyasi yalniz tum adimlar bitince yazilir; yarida kalan kurulum
REM bir sonraki calistirmada kaldigi yerden devam eder.
REM Isaret tek satirdir: "req_sha256=<requirements.txt SHA-256> voxcpm=<surum>".
REM   isaret yok                       -> asagidaki tam ilk kurulum
REM   isaret ayni                      -> kurulum atlanir
REM   farkli ya da eski bicim "tamam"  -> :esitle (yalniz pip install -r ...)
if not exist "%MARK%" goto :ilk_kurulum
call :isaret_hesapla
REM Ozet hesaplanamadiysa (Python bozuk vb.) eskisi gibi dogrudan baslatilir;
REM yalniz kurulum kipinde bu bir hatadir (Python calismiyor, SesVer de acilmaz).
if errorlevel 1 if "%SV_YK%"=="1" goto :yk_isaret_hata
if errorlevel 1 goto :baslat
set "SV_ISARET="
set /p SV_ISARET=<"%MARK%"
if not "%SV_ISARET%"=="%SV_BEKLENEN%" goto :esitle
del "%MARK%.yeni" >nul 2>nul
goto :baslat

:esitle
REM SesVer guncellenmis: ortam silinmez, yalniz eksik/degisen paketler kurulur.
REM Basarisizsa isaret ESKI haliyle kalir (sonraki acilista yeniden denenir)
REM ve :hata ile ilk kurulumdaki hata yolu gosterilir.
echo SesVer guncellenmis: paketler esitleniyor - yalniz eksik/degisen paketler kurulur...
REM CUDA korumasi: NVIDIA kartta CUDA'li torch GERCEKTEN calisiyorsa (hizlandirma.py
REM --cuda-dogrula: kucuk bir gercek islemle sinar) kurulu torch/torchaudio surumleri
REM kisit dosyasina (-c) yazilir; pip onlari PyPI'nin CPU derlemesiyle degistiremez.
REM torch.cuda.is_available() TEK BASINA yeterli degildir: Blackwell + cu126 gibi
REM durumlarda surucu/baglam calisir gorunur ama bu mimari icin derlenmis cekirdek
REM yoktur ("no kernel image is available") - is_available True doner, ilk uretimde
REM patlar. Boyle bozuk bir kurulumu "koru" diye kisitlamak hatayi kalicilastirirdi.
REM Yeni requirements daha yeni torch isterse esitleme hata verir (sessizce CPU'ya
REM dusmek yerine). --upgrade kullanilmaz: gereksinimi zaten karsilayan paketlere
REM dokunulmaz.
call :durum 3 "Ekran karti kontrol ediliyor"
set "SV_KISIT="
del "%MARK%.kisit" >nul 2>nul
where nvidia-smi >nul 2>nul
if errorlevel 1 goto :esitle_voxcpm
"%PYEXE%" hizlandirma.py --cuda-dogrula >nul 2>nul
if errorlevel 1 goto :esitle_voxcpm
"%PYEXE%" -c "import sys,torch,torchaudio;open(sys.argv[1],'w').write('torch=='+torch.__version__+chr(10)+'torchaudio=='+torchaudio.__version__+chr(10))" "%MARK%.kisit" >nul 2>nul
if errorlevel 1 goto :esitle_voxcpm
set SV_KISIT=-c "%MARK%.kisit"
echo CUDA destekli PyTorch korunuyor (gercek cekirdek testi basarili).
:esitle_voxcpm
REM voxcpm yalniz pini degistiyse ya da eski "tamam" isaretinde (pin bilinmiyor) kurulur.
set "SV_ESKI_VOX="
for /f "tokens=2 delims= " %%v in ("%SV_ISARET%") do set "SV_ESKI_VOX=%%v"
if "%SV_ESKI_VOX%"=="voxcpm=%VOXCPM_SURUM%" goto :esitle_req
call :durum 5 "voxcpm esitleniyor"
set "ADIM=voxcpm esitleme"
"%PYEXE%" -m pip install --no-deps voxcpm==%VOXCPM_SURUM% --no-warn-script-location
if errorlevel 1 goto :esitle_hata
:esitle_req
call :durum 6 "Paketler esitleniyor (requirements.txt)"
set "ADIM=requirements.txt esitleme"
"%PYEXE%" -m pip install -r requirements.txt %SV_KISIT% --no-warn-script-location
if errorlevel 1 goto :esitle_hata
del "%MARK%.kisit" >nul 2>nul
move /y "%MARK%.yeni" "%MARK%" >nul
if errorlevel 1 goto :hata
echo Paket esitleme tamamlandi.
goto :baslat
:esitle_hata
del "%MARK%.kisit" >nul 2>nul
del "%MARK%.yeni" >nul 2>nul
goto :hata

:ilk_kurulum
echo Ilk kurulum yapiliyor - bu sadece bir kere calisir...
call :durum 2 "pip hazirlaniyor"
set "ADIM=pip kontrolu"
"%PYEXE%" -m pip --version >nul 2>nul
if not errorlevel 1 goto :pip_var
"%PYEXE%" -m ensurepip --upgrade
if errorlevel 1 goto :hata
:pip_var
set "ADIM=pip guncelleme"
"%PYEXE%" -m pip install --upgrade pip --quiet --no-warn-script-location
if errorlevel 1 goto :hata
REM NVIDIA ekran karti varsa CUDA destekli PyTorch kurulur; yoksa normal
REM "pip install torch" (PyPI varsayilani) sessizce SADECE CPU derlemesini
REM kurar ve uretim CPU'da calisir (GPU bos durur). nvidia-smi.exe sadece
REM NVIDIA suruculeri kuruluysa PATH'te olur, bu yuzden guvenilir bir tespit.
call :durum 3 "Ekran karti algilaniyor"
set "ADIM=GPU tespiti"
where nvidia-smi >nul 2>nul
if errorlevel 1 goto :gpu_yok_islemci
echo NVIDIA ekran karti bulundu, dogru PyTorch surumu seciliyor...
set "ADIM=CUDA destekli PyTorch kurulumu"
set "CUDA_ETIKET="
for /f "usebackq delims=" %%T in (`"%PYEXE%" hizlandirma.py --onerilen-etiket 2^>nul`) do set "CUDA_ETIKET=%%T"
if "%CUDA_ETIKET%"=="" goto :gpu_etiket_yok
call :durum 4 "PyTorch kuruluyor (%CUDA_ETIKET%)"
echo CUDA destekli PyTorch kuruluyor: %CUDA_ETIKET%
"%PYEXE%" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/%CUDA_ETIKET% --no-warn-script-location
if errorlevel 1 echo CUDA PyTorch kurulumu basarisiz oldu, CPU surumune devam edilecek.
goto :gpu_bitti
:gpu_etiket_yok
call :durum 4 "PyTorch (CPU) paketlerle kurulacak"
echo Ekran karti icin uygun CUDA surumu secilemedi, CPU surumune devam edilecek.
goto :gpu_bitti
:gpu_yok_islemci
call :durum 4 "PyTorch (CPU) paketlerle kurulacak"
echo NVIDIA ekran karti bulunamadi, CPU modunda devam edilecek.
:gpu_bitti
REM --no-deps: voxcpm'in gereksiz agir bagimliliklarini (funasr, matplotlib,
REM modelscope, datasets, spaces, argbind - hicbiri kodda kullanilmiyor)
REM atlayip yalniz requirements.txt'teki gercekten gerekli paketleri kurar.
call :durum 5 "voxcpm kuruluyor"
set "ADIM=voxcpm kurulumu"
"%PYEXE%" -m pip install --no-deps voxcpm==%VOXCPM_SURUM% --no-warn-script-location
if errorlevel 1 goto :hata
call :durum 6 "Paketler kuruluyor (requirements.txt)"
set "ADIM=requirements.txt kurulumu"
"%PYEXE%" -m pip install -r requirements.txt --no-warn-script-location
if errorlevel 1 goto :hata
call :isaret_hesapla
if errorlevel 1 goto :isaret_eski_bicim
move /y "%MARK%.yeni" "%MARK%" >nul
if not errorlevel 1 goto :kurulum_bitti
:isaret_eski_bicim
REM Ozet yazilamadiysa eski bicim: sonraki acilis bir kez esitleme dener.
echo tamam>"%MARK%"
:kurulum_bitti
echo Kurulum tamamlandi.

:baslat
REM Kurulum atlanmis olsa bile (MARK zaten vardi) her acilista ucuz bir kontrol:
REM NVIDIA karti var ama PyTorch CUDA'yi kullanamiyorsa (ör. eski kurulumdan
REM kalma CPU-only torch, ya da Blackwell + cu126 gibi "cuda_ok=True ama cekirdek
REM yok" durumu), bir kerelik duzeltme dener ve ikinci markla isaretler.
REM Isaret MARK ile AYNI klasorde tutulur (python-embed\ ya da .venv\): .venv
REM sabitlenirse python-embed kurulumunda klasor hic olusmayabilir ve "echo >"
REM sessizce basarisiz olur - bir sonraki acilista kontrol gereksiz yere tekrar
REM calisir (zararsiz ama MARK ile tutarsiz). Isaret ayrica v2 ile adlandirilir:
REM v1.1.0'dan kalma eski ".venv\sesver_gpu_duzeltme_denendi.txt" isareti varsa
REM bile yeni kontrolu ENGELLEMEZ (dosya adi farkli).
set "GPU_FIX_MARK="
for %%I in ("%MARK%") do set "GPU_FIX_MARK=%%~dpIsesver_gpu_duzeltme_v2.txt"
where nvidia-smi >nul 2>nul
if errorlevel 1 goto :gpu_fix_bitti
if exist "%GPU_FIX_MARK%" goto :gpu_fix_bitti
call :durum 6 "Ekran karti dogrulaniyor"
set "CUDA_ETIKET="
"%PYEXE%" hizlandirma.py --cuda-dogrula >nul 2>nul
if not errorlevel 1 goto :gpu_fix_isaretle
echo NVIDIA ekran karti var ama PyTorch ekran kartini kullanamiyor, duzeltiliyor...
set "CUDA_ETIKET="
for /f "usebackq delims=" %%T in (`"%PYEXE%" hizlandirma.py --onerilen-etiket 2^>nul`) do set "CUDA_ETIKET=%%T"
if "%CUDA_ETIKET%"=="" goto :gpu_fix_isaretle
call :durum 6 "PyTorch ekran karti icin yeniden kuruluyor (%CUDA_ETIKET%)"
"%PYEXE%" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/%CUDA_ETIKET% --no-warn-script-location
:gpu_fix_isaretle
echo %CUDA_ETIKET%>"%GPU_FIX_MARK%"
:gpu_fix_bitti
REM Yalniz kurulum kipi: SesVer baslatilmaz (sihirbaz kisayollari ayarlar).
if "%SV_YK%"=="1" goto :yk_tamam
set "SV_PORT=%GRADIO_SERVER_PORT%"
if "%SV_PORT%"=="" set "SV_PORT=7860"
REM Normal yol: konsolsuz pythonw.exe ile baslat; SesVer penceresi acilinca bu
REM pencere kendiliginden kapanir. Ciktilar sesver_log.txt dosyasina yazilir.
REM desktop.py acilis sonucunu SESVER_DURUM_DOSYASI'na yazar:
REM   acildi      = pencere ekranda, bu konsol kapanir
REM   pencere_yok = pywebview/WebView2 yok, asagidaki konsollu yonteme donulur
REM   hata        = SesVer acilamadi, log gosterilir ve pencere acik kalir
REM pythonw.exe, python.exe ile ayni klasordedir (python-embed ve .venv\Scripts).
set "PYW=%PYEXE:python.exe=pythonw.exe%"
if not exist "%PYW%" goto :baslat_konsollu
set "SESVER_DURUM_DOSYASI=%CD%\sesver_durum.tmp"
del /q "%SESVER_DURUM_DOSYASI%" >nul 2>nul
echo SesVer aciliyor, birkac saniye surebilir. Pencere acilinca bu pencere kendiliginden kapanir.
REM ver: errorlevel 0 yapar; basarili start errorlevel'i degistirmeyebilir.
ver >nul
start "" "%PYW%" desktop.py
if errorlevel 1 goto :baslat_konsollu_temiz
set /a SV_BEKLE=0
:baslat_bekle
if exist "%SESVER_DURUM_DOSYASI%" goto :baslat_durum
if %SV_BEKLE% GEQ 180 goto :baslat_zaman_asimi
ping -n 2 127.0.0.1 >nul
set /a SV_BEKLE+=1
goto :baslat_bekle

:baslat_durum
set "SV_DURUM="
set /p SV_DURUM=<"%SESVER_DURUM_DOSYASI%"
del /q "%SESVER_DURUM_DOSYASI%" >nul 2>nul
if /i "%SV_DURUM%"=="acildi" exit /b 0
if /i "%SV_DURUM%"=="pencere_yok" goto :baslat_konsollu_temiz
echo.
echo [HATA] SesVer acilamadi. sesver_log.txt dosyasinin son satirlari:
echo ----------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -LiteralPath 'sesver_log.txt' -Tail 40 -Encoding UTF8" 2>nul || type "sesver_log.txt"
echo ----------------------------------------------------------------
echo Tum ayrinti: SesVer klasorundeki sesver_log.txt dosyasi.
echo Sorun surerse sesver_log.txt dosyasini hermes.agent.hamarat@gmail.com adresine gonderin.
pause
exit /b 1

:baslat_zaman_asimi
del /q "%SESVER_DURUM_DOSYASI%" >nul 2>nul
echo.
echo [UYARI] SesVer penceresi 3 dakika icinde acilmadi.
echo Pencere biraz sonra acilabilir. Acilmazsa SesVer klasorundeki sesver_log.txt dosyasina bakin.
pause
exit /b 1

:baslat_konsollu_temiz
del /q "%SESVER_DURUM_DOSYASI%" >nul 2>nul
set "SESVER_DURUM_DOSYASI="
echo [BILGI] Konsolsuz baslatma kullanilamadi; SesVer bu pencereden calistiriliyor.
:baslat_konsollu
REM Yedek yol: eski davranis - python.exe ile bu konsolda calisir, konsol acik kalir.
echo SesVer aciliyor, birkac saniye surebilir. Bir pencere acilmazsa tarayicinizda http://127.0.0.1:%SV_PORT% adresini deneyin (port doluysa asagida yazilan adresi).
echo Durdurmak icin bu pencerede Ctrl+C kullanin.
"%PYEXE%" desktop.py
set "CIKIS=%errorlevel%"
if not "%CIKIS%"=="0" echo [BILGI] SesVer durdu, cikis kodu %CIKIS%. Ctrl+C ile kapatmadiysaniz yukaridaki hata mesajini okuyun. Ayrinti: sesver_log.txt
pause
exit /b 0

:hata
if "%SV_YK%"=="1" goto :yk_hata
echo.
echo [HATA] Kurulum adimi basarisiz oldu: %ADIM%
echo Yukaridaki hata mesajini okuyun. Internet baglantinizi kontrol edip
echo WINDOWS_BASLAT.bat dosyasini tekrar calistirin; kurulum kaldigi yerden devam eder.
echo Sorun surerse sesver_log.txt dosyasini hermes.agent.hamarat@gmail.com adresine gonderin.
pause
exit /b 1

REM ---- Yalniz kurulum kipinin sonlari: pause YOK, cikis kodu dondurulur ----
:yk_tamam
echo Kurulum tamamlandi. Yalniz kurulum kipi: SesVer baslatilmadi.
call :durum %SV_TOPLAM_ADIM% "tamam"
exit /b 0
:yk_isaret_hata
set "ADIM=kurulum isareti hesaplama - Python calismiyor"
:yk_hata
echo [HATA] Kurulum adimi basarisiz oldu: %ADIM%
echo Kurulum kaldigi yerden devam eder: SesVer simgesine ya da WINDOWS_BASLAT.bat dosyasina tekrar cift tiklayin.
call :durum %SV_ADIM_NO% "hata:%ADIM%"
exit /b 1

REM ================= Alt yordamlar =================

:durum
REM %1 = adim no, %2 = ASCII kisa metin. Yalniz kurulum kipinde kurulum_durum.txt
REM dosyasini tek satirla degistirir: "<adim>/<toplam>|<metin>". Sihirbaz bos ya da
REM yarim okunan satiri yok sayar. Normal kipte hicbir sey yapmaz.
if not "%SV_YK%"=="1" exit /b 0
set "SV_ADIM_NO=%~1"
>"kurulum_durum.txt" echo %~1/%SV_TOPLAM_ADIM%^|%~2
echo [DURUM] %~1/%SV_TOPLAM_ADIM%^|%~2
exit /b 0

:isaret_hesapla
REM Beklenen kurulum isaretini "%MARK%.yeni" dosyasina yazar, SV_BEKLENEN'e okur.
REM SHA-256 Python hashlib ile hesaplanir: certutil ciktisinin bicimi Windows
REM surumune/diline gore degisir (bosluklu hex, yerellestirilmis basliklar).
del "%MARK%.yeni" >nul 2>nul
set "SV_BEKLENEN="
"%PYEXE%" -c "import hashlib,sys;print('req_sha256='+hashlib.sha256(open('requirements.txt','rb').read()).hexdigest()+' voxcpm='+sys.argv[1])" "%VOXCPM_SURUM%" >"%MARK%.yeni" 2>nul
if errorlevel 1 goto :isaret_hesapla_hata
set /p SV_BEKLENEN=<"%MARK%.yeni"
if "%SV_BEKLENEN%"=="" goto :isaret_hesapla_hata
exit /b 0
:isaret_hesapla_hata
del "%MARK%.yeni" >nul 2>nul
exit /b 1

:embed_kur
REM Tasinabilir Python'u indirir, SHA256 ile dogrular, python-embed\ olarak
REM yerlestirir. Basariliysa errorlevel 0, degilse 1 doner.
REM Ara dosyalar pbs_ onekiyle bu klasorde tutulur ve sonda silinir.
echo.
echo Python hazirlaniyor - bilgisayariniza ayrica Python kurmaniz gerekmez...
REM Guncel surum bilgisi alinamazsa kullanilacak, dogrulanmis son iyi surum:
set "PBS_TAG_YEDEK=20261013"
set "PBS_DOSYA_YEDEK=cpython-3.11.17+20261013-x86_64-pc-windows-msvc-install_only.tar.gz"
set "PBS_SHA_YEDEK=7616ab1f74aab975bd91eb0a657a74a092a63a46cac38c5f3f9415c79fd781f5"
set "PBS_REPO=https://github.com/astral-sh/python-build-standalone/releases/download"
set "PBS_TAG="
set "PBS_DOSYA="
set "PBS_SHA="
call :embed_temizle
if not exist "%SystemRoot%\System32\tar.exe" goto :embed_tar_yok
REM Guncel surum etiketi: latest-release.json icindeki "tag" alani.
call :indir "https://raw.githubusercontent.com/astral-sh/python-build-standalone/latest-release/latest-release.json" "pbs_latest.json" sessiz
if errorlevel 1 goto :embed_yedek_surum
for /f "usebackq tokens=1,2 delims=:, " %%A in ("pbs_latest.json") do if "%%~A"=="tag" set "PBS_TAG=%%~B"
if "%PBS_TAG%"=="" goto :embed_yedek_surum
REM Bu etiketteki 3.11 Windows x64 install_only dosyasinin adi ve SHA256'si.
call :indir "%PBS_REPO%/%PBS_TAG%/SHA256SUMS" "pbs_sums.txt" sessiz
if errorlevel 1 goto :embed_yedek_surum
findstr /l /c:" cpython-3.11." "pbs_sums.txt" >"pbs_sums_311.txt" 2>nul
findstr /l /c:"-x86_64-pc-windows-msvc-install_only.tar.gz" "pbs_sums_311.txt" >"pbs_satir.txt" 2>nul
for /f "usebackq tokens=1" %%A in ("pbs_satir.txt") do set "PBS_SHA=%%A"
for /f "usebackq tokens=2" %%A in ("pbs_satir.txt") do set "PBS_DOSYA=%%A"
if "%PBS_SHA%"=="" goto :embed_yedek_surum
if "%PBS_DOSYA%"=="" goto :embed_yedek_surum
goto :embed_indir
:embed_yedek_surum
echo [BILGI] Guncel surum bilgisi alinamadi; bilinen surum kullaniliyor.
set "PBS_TAG=%PBS_TAG_YEDEK%"
set "PBS_DOSYA=%PBS_DOSYA_YEDEK%"
set "PBS_SHA=%PBS_SHA_YEDEK%"
:embed_indir
echo Indiriliyor: %PBS_DOSYA%
call :indir "%PBS_REPO%/%PBS_TAG%/%PBS_DOSYA%" "pbs_python.tar.gz"
if errorlevel 1 goto :embed_hata_indir
REM Butunluk kontrolu: once certutil, olmazsa PowerShell Get-FileHash.
certutil -hashfile "pbs_python.tar.gz" SHA256 2>nul | findstr /i /c:"%PBS_SHA%" >nul
if not errorlevel 1 goto :embed_sha_tamam
powershell -NoProfile -ExecutionPolicy Bypass -Command "if ((Get-FileHash -Algorithm SHA256 -LiteralPath 'pbs_python.tar.gz').Hash -ieq '%PBS_SHA%') { exit 0 } else { exit 1 }"
if errorlevel 1 goto :embed_hata_sha
:embed_sha_tamam
echo Python cikariliyor...
mkdir "pbs_tmp"
if errorlevel 1 goto :embed_hata_cikar
REM Yerlesik bsdtar acikca secilir; PATH'teki Git tar'i farkli davranabilir.
"%SystemRoot%\System32\tar.exe" -xzf "pbs_python.tar.gz" -C "pbs_tmp"
if errorlevel 1 goto :embed_hata_cikar
if not exist "pbs_tmp\python\python.exe" goto :embed_hata_cikar
if exist "python-embed" rd /s /q "python-embed" >nul 2>nul
if exist "python-embed" goto :embed_hata_tasi
REM Antivirus yeni cikan dosyalari kisa sure kilitleyebilir; 5 kez dene.
set /a "PBS_DENEME=0"
:embed_tasi
set /a "PBS_DENEME+=1"
move "pbs_tmp\python" "python-embed" >nul 2>nul
if not errorlevel 1 goto :embed_tasindi
if %PBS_DENEME% GEQ 5 goto :embed_hata_tasi
ping -n 3 127.0.0.1 >nul
goto :embed_tasi
:embed_tasindi
REM python-embed git'e girmesin: klasor kendi kendini yok saydirir.
>"python-embed\.gitignore" echo *
"%EMBED_PY%" --version >nul 2>nul
if errorlevel 1 goto :embed_hata_calismiyor
call :embed_temizle
echo Python hazir.
exit /b 0
:embed_tar_yok
echo [UYARI] Windows'ta yerlesik tar araci yok - Windows surumunuz cok eski.
echo Python'u elle kurmaniz gerekebilir: https://www.python.org/downloads/
goto :embed_basarisiz
:embed_hata_indir
echo [UYARI] Python indirilemedi. Internet baglantinizi kontrol edin.
goto :embed_basarisiz
:embed_hata_sha
echo [UYARI] Indirilen Python dosyasi bozuk - SHA256 dogrulamasi tutmadi.
goto :embed_basarisiz
:embed_hata_cikar
echo [UYARI] Python arsivi cikarilamadi.
goto :embed_basarisiz
:embed_hata_tasi
echo [UYARI] python-embed klasoru olusturulamadi; antivirus dosyalari kilitliyor olabilir.
goto :embed_basarisiz
:embed_hata_calismiyor
echo [UYARI] Indirilen Python bu bilgisayarda calismadi; 64 bit Windows 10/11 gerekir.
rd /s /q "python-embed" >nul 2>nul
goto :embed_basarisiz
:embed_basarisiz
call :embed_temizle
exit /b 1

:embed_temizle
if exist "pbs_tmp" rd /s /q "pbs_tmp" >nul 2>nul
del /f /q "pbs_python.tar.gz" "pbs_latest.json" "pbs_sums.txt" "pbs_sums_311.txt" "pbs_satir.txt" >nul 2>nul
exit /b 0

:indir
REM %1 = URL, %2 = hedef dosya, %3 = sessiz ise ilerleme gosterilmez.
REM Once Windows 10+ yerlesik curl, olmazsa PowerShell Invoke-WebRequest.
del /f /q "%~2" >nul 2>nul
set "CURL_SES=-#"
if "%~3"=="sessiz" set "CURL_SES=-sS"
if not exist "%SystemRoot%\System32\curl.exe" goto :indir_ps
"%SystemRoot%\System32\curl.exe" %CURL_SES% -fL --retry 3 --connect-timeout 20 -o "%~2" "%~1"
if not errorlevel 1 if exist "%~2" exit /b 0
echo [BILGI] curl ile indirilemedi, PowerShell deneniyor...
:indir_ps
del /f /q "%~2" >nul 2>nul
where powershell >nul 2>nul || exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -UseBasicParsing -Uri '%~1' -OutFile '%~2'; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 exit /b 1
if not exist "%~2" exit /b 1
exit /b 0
