@echo off
echo [SesVer baslatici calisiyor]
REM SesVer başlatıcı — Windows. Çift tıklayın.
REM İlk çalıştırmada ortamı kurar; sonrakilerde doğrudan açar.
REM Not: parantezli if bloklari bilerek kullanilmiyor; blok icindeki ")" ve
REM blok icinde errorlevel acilimi klasik batch tuzaklaridir. Duz satir + goto kullanilir.
setlocal
cd /d "%~dp0"

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
echo [HATA] Python bulunamadi. "py" ve "python" komutlari calismiyor.
echo Lutfen Python 3.10-3.12 kurun: https://www.python.org/downloads/
echo Kurulumda "Add python.exe to PATH" kutusunu isaretleyin.
echo Microsoft Store kisayolu sorun cikariyorsa: Ayarlar - Uygulamalar -
echo Uygulama yurutme diger adlari - python.exe/python3.exe kapatin.
pause
exit /b 1
:py_bulundu
echo Kullanilan Python komutu: %PY%
%PY% --version
%PY% -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" || echo [UYARI] Onerilen surum Python 3.10-3.12; kurulum basarisiz olabilir.

if exist ".venv\Scripts\python.exe" if exist ".venv\sesver_kurulum_tamam.txt" goto :baslat
echo Ilk kurulum yapiliyor - bu sadece bir kere calisir...
set "ADIM=sanal ortam olusturma: %PY% -m venv .venv"
if exist ".venv\Scripts\python.exe" goto :venv_var
%PY% -m venv .venv
if errorlevel 1 goto :hata
if not exist ".venv\Scripts\python.exe" goto :hata
:venv_var
set "ADIM=pip guncelleme"
.\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
if errorlevel 1 goto :hata
REM --no-deps: voxcpm'in gereksiz agir bagimliliklarini (funasr, matplotlib,
REM modelscope, datasets, spaces, argbind - hicbiri kodda kullanilmiyor)
REM atlayip yalniz requirements.txt'teki gercekten gerekli paketleri kurar.
set "ADIM=voxcpm kurulumu"
.\.venv\Scripts\python.exe -m pip install --no-deps voxcpm==2.0.3
if errorlevel 1 goto :hata
set "ADIM=requirements.txt kurulumu"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :hata
echo tamam>".venv\sesver_kurulum_tamam.txt"
echo Kurulum tamamlandi.

:baslat
echo SesVer baslatiliyor... Tarayicinizda http://127.0.0.1:7860 acilacak.
echo Durdurmak icin bu pencerede Ctrl+C kullanin.
.\.venv\Scripts\python.exe app.py
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
