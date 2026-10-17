@echo off
REM SesVer başlatıcı — Windows. Çift tıklayın.
REM İlk çalıştırmada ortamı kurar; sonrakilerde doğrudan açar.
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel% neq 0 (
    echo Python bulunamadı. Lütfen Python 3.10-3.12 kurun: https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Ilk kurulum yapiliyor (bu sadece bir kere calisir)...
    py -3.11 -m venv .venv || py -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    REM --no-deps: voxcpm'in gereksiz agir bagimliliklarini (funasr, matplotlib,
    REM modelscope, datasets, spaces, argbind - hicbiri kodda kullanilmiyor)
    REM atlayip yalniz requirements.txt'teki gercekten gerekli paketleri kurar.
    .\.venv\Scripts\python.exe -m pip install --no-deps voxcpm==2.0.3
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    echo Kurulum tamamlandi.
)

echo SesVer baslatiliyor... Tarayicinizda http://127.0.0.1:7860 acilacak.
echo Durdurmak icin bu pencerede Ctrl+C kullanin.
.\.venv\Scripts\python.exe app.py
pause
