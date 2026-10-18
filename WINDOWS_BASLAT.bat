@echo off
echo [SesVer baslatici calisiyor]
REM SesVer başlatıcı — Windows. Çift tıklayın.
REM İlk çalıştırmada ortamı kurar; sonrakilerde doğrudan açar.
REM Not: parantezli if bloklari bilerek kullanilmiyor; blok icindeki ")" ve
REM blok icinde errorlevel acilimi klasik batch tuzaklaridir. Duz satir + goto kullanilir.
setlocal
cd /d "%~dp0"

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
set "PYEXE="
set "MARK="

if not exist "%EMBED_PY%" goto :embed_yok
"%EMBED_PY%" --version >nul 2>nul
if not errorlevel 1 goto :embed_kullan
echo [UYARI] python-embed klasorundeki Python calismiyor; silinip yeniden indirilecek.
rd /s /q "python-embed" >nul 2>nul
:embed_yok
if exist ".venv\Scripts\python.exe" if exist ".venv\sesver_kurulum_tamam.txt" goto :venv_kullan
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
if exist "%MARK%" goto :baslat
echo Ilk kurulum yapiliyor - bu sadece bir kere calisir...
set "ADIM=pip kontrolu"
"%PYEXE%" -m pip --version >nul 2>nul
if not errorlevel 1 goto :pip_var
"%PYEXE%" -m ensurepip --upgrade
if errorlevel 1 goto :hata
:pip_var
set "ADIM=pip guncelleme"
"%PYEXE%" -m pip install --upgrade pip --quiet --no-warn-script-location
if errorlevel 1 goto :hata
REM --no-deps: voxcpm'in gereksiz agir bagimliliklarini (funasr, matplotlib,
REM modelscope, datasets, spaces, argbind - hicbiri kodda kullanilmiyor)
REM atlayip yalniz requirements.txt'teki gercekten gerekli paketleri kurar.
set "ADIM=voxcpm kurulumu"
"%PYEXE%" -m pip install --no-deps voxcpm==2.0.3 --no-warn-script-location
if errorlevel 1 goto :hata
set "ADIM=requirements.txt kurulumu"
"%PYEXE%" -m pip install -r requirements.txt --no-warn-script-location
if errorlevel 1 goto :hata
echo tamam>"%MARK%"
echo Kurulum tamamlandi.

:baslat
echo SesVer baslatiliyor... Tarayicinizda http://127.0.0.1:7860 acilacak.
echo Durdurmak icin bu pencerede Ctrl+C kullanin.
"%PYEXE%" desktop.py
set "CIKIS=%errorlevel%"
if not "%CIKIS%"=="0" echo [BILGI] SesVer durdu, cikis kodu %CIKIS%. Ctrl+C ile kapatmadiysaniz yukaridaki hata mesajini okuyun.
pause
exit /b 0

:hata
echo.
echo [HATA] Kurulum adimi basarisiz oldu: %ADIM%
echo Yukaridaki hata mesajini okuyun. Internet baglantinizi kontrol edip
echo WINDOWS_BASLAT.bat dosyasini tekrar calistirin; kurulum kaldigi yerden devam eder.
pause
exit /b 1

REM ================= Alt yordamlar =================

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
