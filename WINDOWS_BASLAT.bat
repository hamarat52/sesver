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
REM Gunlugun geri kalani tek kodlamayla (UTF-8) yazilsin: cmd ciktisi konsol kod
REM sayfasini, Python ciktisi PYTHONIOENCODING degiskenini kullanir. Sihirbaz paylasilabilir
REM kopyayi uretirken gunlugu UTF-8 okur; ASCII disi kullanici adi da USERPROFILE ile
REM eslesip gizlenir (windows\SesVer.iss PaylasilabilirGunlukBaytlari). PID satiri bundan
REM once yazilir: PowerShell ciktisi kod sayfasi degisikliginden etkilenmesin. Yalniz bu
REM kipte; normal cift tik calismasinda kod sayfasina dokunulmaz.
chcp 65001 >nul 2>nul
set "PYTHONIOENCODING=utf-8"
REM Destek icin kurulum klasoru; paylasilabilir kopyada ev klasoru kismi gizlenir.
echo [BILGI] Kurulum klasoru: "%CD%"
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
REM voxcpm kilit\voxcpm.txt icinde (--no-deps ile ayri kurulur); surum isarete de yazilir.
REM macos_ortak.sh'teki VOXCPM_SURUM ile ayni tutun.
set "VOXCPM_SURUM=2.0.3"
REM Tedarik zinciri: tum paketler kilit\ klasorundeki dosyalardan sabit surum + SHA-256
REM ile kurulur (pip --require-hashes; uretici: tools\kilit_uret.py). Ozet tutmazsa
REM kurulum durur, isaret yazilmaz. --only-binary: kaynak derleme yok; tek istisna
REM proxy-tools (PyPI'de yalniz kaynak paketi var), o da hash'li kurulan setuptools ile
REM --no-build-isolation derlenir (izole derleme ortami pip'te hash denetimsiz inerdi).
set "KILIT_PIP=--require-hashes --only-binary=:all: --no-binary=proxy-tools --no-build-isolation --disable-pip-version-check --no-warn-script-location"
set "SV_HASH_HATASI=0"
set "TEMEL_KILIT="
set "TORCH_KILIT=kilit\torch-pypi.txt"
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
REM Ozet tutmadiysa sistem Python'una sessizce gecilmez: acik mesajla durulur.
if not "%SV_HASH_HATASI%"=="1" goto :embed_yedek
set "ADIM=Python indirme - SHA-256 uyusmazligi"
goto :hata
:embed_yedek
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
REM Kilit yalniz Python 3.10-3.12 icin var: baska surumde hash'siz kuruluma dusulmez.
%PY% -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)"
if not errorlevel 1 goto :py_surum_tamam
echo [HATA] Bu Python surumu desteklenmiyor; SesVer Python 3.10, 3.11 ya da 3.12 ile kurulur.
echo Internet baglantinizi kontrol edip tekrar deneyin ya da Python 3.11 kurun: https://www.python.org/downloads/
set "ADIM=Python surumu desteklenmiyor - 3.10-3.12 gerekir"
goto :hata
:py_surum_tamam
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
REM SesVer guncellenmis: ortam silinmez, kilitli paketler kurulur; surumu zaten
REM tutan pakete dokunulmaz. Basarisizsa isaret ESKI haliyle kalir (sonraki
REM acilista yeniden denenir) ve :hata ile ilk kurulumdaki hata yolu gosterilir.
echo SesVer guncellenmis: paketler esitleniyor - yalniz eksik/degisen paketler kurulur...
call :kilit_sec
if errorlevel 1 goto :esitle_kilit_yok
REM CUDA korumasi: NVIDIA kartta CUDA'li torch GERCEKTEN calisiyorsa (hizlandirma.py
REM --cuda-dogrula: kucuk bir gercek islemle sinar) torch katmani ayni CUDA etiketinin
REM kilidinden kurulur (kilit\torch-cuXXX.txt; ayni surumse hicbir sey inmez) ve kurulu
REM torch/torchaudio surumleri kisit dosyasina (-c) yazilir: temel kilit kurulurken pip
REM onlari PyPI'nin CPU derlemesiyle degistiremez. torch.cuda.is_available() TEK BASINA
REM yeterli degildir: Blackwell + cu126 gibi durumlarda is_available True doner, ilk
REM uretimde patlar. Boyle bozuk bir kurulumu "koru" diye kisitlamak hatayi kalicilastirirdi.
REM Etiketin kilidi yoksa (eski bir surumden kalma cu124 vb.) calisan torch'a dokunulmaz.
call :durum 3 "Ekran karti kontrol ediliyor"
set "SV_KISIT="
set "SV_CUDA_KORU=0"
set "TORCH_KILIT=kilit\torch-pypi.txt"
del "%MARK%.kisit" >nul 2>nul
where nvidia-smi >nul 2>nul
if errorlevel 1 goto :esitle_pip
"%PYEXE%" hizlandirma.py --cuda-dogrula >nul 2>nul
if errorlevel 1 goto :esitle_pip
set "SV_CUDA_KORU=1"
set "SV_TORCH_ETIKET="
REM Etiket gecici dosyaya yazdirilip okunur. "for /f" kullanilmaz: for /f komutu
REM "cmd /c" ile calistirir ve komut tirnakla baslayip ikiden fazla tirnak icerince
REM cmd ilk ve SON tirnagi soyar ("%PYEXE%" -c "..." bozulur, cikti bos kalir).
del /f /q "sesver_torch_etiket.tmp" >nul 2>nul
"%PYEXE%" -c "import torch;v=torch.__version__;print(v.split('+')[1] if '+' in v else '')" >"sesver_torch_etiket.tmp" 2>nul
if exist "sesver_torch_etiket.tmp" set /p SV_TORCH_ETIKET=<"sesver_torch_etiket.tmp"
del /f /q "sesver_torch_etiket.tmp" >nul 2>nul
set "TORCH_KILIT="
if not "%SV_TORCH_ETIKET%"=="" if exist "kilit\torch-%SV_TORCH_ETIKET%.txt" set "TORCH_KILIT=kilit\torch-%SV_TORCH_ETIKET%.txt"
echo CUDA destekli PyTorch korunuyor (gercek cekirdek testi basarili, etiket: %SV_TORCH_ETIKET%).
:esitle_pip
call :durum 5 "pip ve voxcpm esitleniyor"
set "ADIM=pip esitleme (kilit\pip.txt)"
set "SV_EK=--no-deps"
call :kilitli_kur "kilit\pip.txt"
if errorlevel 1 goto :esitle_hata
if "%TORCH_KILIT%"=="" goto :esitle_kisit
set "ADIM=PyTorch esitleme (%TORCH_KILIT%)"
call :kilitli_kur "%TORCH_KILIT%"
if errorlevel 1 goto :esitle_hata
:esitle_kisit
if not "%SV_CUDA_KORU%"=="1" goto :esitle_voxcpm
"%PYEXE%" -c "import sys,torch,torchaudio;open(sys.argv[1],'w').write('torch=='+torch.__version__+chr(10)+'torchaudio=='+torchaudio.__version__+chr(10))" "%MARK%.kisit" >nul 2>nul
if errorlevel 1 goto :esitle_voxcpm
set SV_KISIT=-c "%MARK%.kisit"
:esitle_voxcpm
set "ADIM=voxcpm esitleme (kilit\voxcpm.txt)"
set "SV_EK=--no-deps"
call :kilitli_kur "kilit\voxcpm.txt"
if errorlevel 1 goto :esitle_hata
call :durum 6 "Paketler esitleniyor (kilit)"
set "ADIM=paket esitleme (%TEMEL_KILIT%)"
set SV_EK=%SV_KISIT%
call :kilitli_kur "%TEMEL_KILIT%"
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
:esitle_kilit_yok
REM Bu Python surumu icin kilit yok: calisan eski kurulum bozulmasin diye hicbir sey
REM kurulmaz, isaret degismez, SesVer mevcut paketlerle acilir.
del "%MARK%.yeni" >nul 2>nul
echo [UYARI] Bu Python surumu icin paket kilidi yok; paket esitlemesi atlandi.
echo [UYARI] SesVer mevcut paketlerle aciliyor. Guncel paketler icin SesVer'i yeniden kurun.
goto :baslat

:ilk_kurulum
echo Ilk kurulum yapiliyor - bu sadece bir kere calisir...
call :durum 2 "pip hazirlaniyor"
set "ADIM=paket kilidi secimi"
call :kilit_sec
if errorlevel 1 goto :hata
set "ADIM=pip kontrolu"
"%PYEXE%" -m pip --version >nul 2>nul
if not errorlevel 1 goto :pip_var
"%PYEXE%" -m ensurepip --upgrade
if errorlevel 1 goto :hata
:pip_var
set "ADIM=pip kurulumu (kilit\pip.txt)"
set "SV_EK=--no-deps"
call :kilitli_kur "kilit\pip.txt"
if errorlevel 1 goto :hata
REM NVIDIA ekran karti varsa CUDA destekli PyTorch kilidi (kilit\torch-<etiket>.txt)
REM kurulur; yoksa PyPI derlemesi (kilit\torch-pypi.txt, Windows'ta yalniz CPU).
REM nvidia-smi.exe sadece NVIDIA suruculeri kuruluysa PATH'te olur.
call :durum 3 "Ekran karti algilaniyor"
set "ADIM=GPU tespiti"
set "SV_EK=--no-deps"
where nvidia-smi >nul 2>nul
if errorlevel 1 goto :gpu_yok_islemci
echo NVIDIA ekran karti bulundu, dogru PyTorch surumu seciliyor...
set "CUDA_ETIKET="
for /f "usebackq delims=" %%T in (`"%PYEXE%" hizlandirma.py --onerilen-etiket 2^>nul`) do set "CUDA_ETIKET=%%T"
if "%CUDA_ETIKET%"=="" goto :gpu_etiket_yok
if not exist "kilit\torch-%CUDA_ETIKET%.txt" goto :gpu_kilit_yok
call :durum 4 "PyTorch kuruluyor (%CUDA_ETIKET%)"
echo CUDA destekli PyTorch kuruluyor: %CUDA_ETIKET%
set "ADIM=CUDA destekli PyTorch kurulumu (kilit\torch-%CUDA_ETIKET%.txt)"
call :kilitli_kur "kilit\torch-%CUDA_ETIKET%.txt"
if not errorlevel 1 goto :gpu_bitti
REM Ozet tutmadiysa durulur; ag hatasi gibi diger durumlarda eskisi gibi CPU'ya gecilir.
if "%SV_HASH_HATASI%"=="1" goto :hata
echo CUDA PyTorch kurulumu basarisiz oldu, CPU surumune devam edilecek.
goto :torch_islemci
:gpu_kilit_yok
echo [UYARI] %CUDA_ETIKET% icin PyTorch kilidi yok, CPU surumune devam edilecek.
goto :torch_islemci
:gpu_etiket_yok
echo Ekran karti icin uygun CUDA surumu secilemedi, CPU surumune devam edilecek.
goto :torch_islemci
:gpu_yok_islemci
echo NVIDIA ekran karti bulunamadi, CPU modunda devam edilecek.
:torch_islemci
call :durum 4 "PyTorch (CPU) kuruluyor"
set "ADIM=PyTorch kurulumu (kilit\torch-pypi.txt)"
set "SV_EK=--no-deps"
call :kilitli_kur "kilit\torch-pypi.txt"
if errorlevel 1 goto :hata
:gpu_bitti
REM --no-deps: voxcpm'in gereksiz agir bagimliliklarini (funasr, matplotlib,
REM modelscope, datasets, spaces, argbind - hicbiri kodda kullanilmiyor) kurmaz.
call :durum 5 "voxcpm kuruluyor"
set "ADIM=voxcpm kurulumu (kilit\voxcpm.txt)"
set "SV_EK=--no-deps"
call :kilitli_kur "kilit\voxcpm.txt"
if errorlevel 1 goto :hata
call :durum 6 "Paketler kuruluyor (kilit)"
set "ADIM=paket kurulumu (%TEMEL_KILIT%)"
set "SV_EK="
call :kilitli_kur "%TEMEL_KILIT%"
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
if not exist "kilit\torch-%CUDA_ETIKET%.txt" goto :gpu_fix_isaretle
call :durum 6 "PyTorch ekran karti icin yeniden kuruluyor (%CUDA_ETIKET%)"
set "SV_EK=--no-deps"
call :kilitli_kur "kilit\torch-%CUDA_ETIKET%.txt"
if errorlevel 1 echo [UYARI] Ekran karti icin PyTorch kurulamadi; SesVer islemciyle (CPU) calisacak.
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
REM desktop.py sesver_log.txt'ye yazarken ev klasoru yollarini gizler (hata_raporu.sanitize).
echo Sorun surerse sesver_log.txt dosyasini hermes.agent.hamarat@gmail.com adresine gonderin.
echo Bu dosyada ev klasoru yollariniz gizlidir.
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
if not "%SV_HASH_HATASI%"=="1" goto :hata_genel
echo Indirilen bir dosyanin SHA-256 ozeti kilit dosyasindakiyle uyusmuyor - bozuk indirme
echo ya da degistirilmis paket. Guvenlik icin kurulum durduruldu; hicbir sey calistirilmadi.
echo Bir sure sonra WINDOWS_BASLAT.bat dosyasini tekrar calistirin; kurulum yeniden denenir.
:hata_genel
echo Yukaridaki hata mesajini okuyun. Internet baglantinizi kontrol edip
echo WINDOWS_BASLAT.bat dosyasini tekrar calistirin; kurulum kaldigi yerden devam eder.
REM Kurulum ciktisi yalniz bu pencerededir (dosyaya yazilmaz) ve ev klasoru yolunu
REM (C:\Users\kullanici_adi) icerebilir: kullanicidan dosya ya da kopyala-yapistir istenmez.
echo Sorun surerse hermes.agent.hamarat@gmail.com adresine yazin ve durdugu adimi bildirin: %ADIM%
echo Bu penceredeki yazilari paylasacaksaniz once icindeki C:\Users\... klasor adinizi silin.
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
REM Isaret: kilit\*.txt dosyalarinin (ad sirasiyla birlestirilmis) SHA-256 ozeti +
REM voxcpm surumu; herhangi bir kilit degisince esitleme calisir. Ozet Python
REM hashlib ile hesaplanir: certutil ciktisinin bicimi Windows surumune/diline gore
REM degisir (bosluklu hex, yerellestirilmis basliklar).
del "%MARK%.yeni" >nul 2>nul
set "SV_BEKLENEN="
"%PYEXE%" -c "import glob,hashlib,sys;h=hashlib.sha256();[h.update(open(f,'rb').read()) for f in sorted(glob.glob('kilit/*.txt'))];print('kilit_sha256='+h.hexdigest()+' voxcpm='+sys.argv[1])" "%VOXCPM_SURUM%" >"%MARK%.yeni" 2>nul
if errorlevel 1 goto :isaret_hesapla_hata
set /p SV_BEKLENEN=<"%MARK%.yeni"
if "%SV_BEKLENEN%"=="" goto :isaret_hesapla_hata
exit /b 0
:isaret_hesapla_hata
del "%MARK%.yeni" >nul 2>nul
exit /b 1

:kilit_sec
REM Bu Python surumu icin temel kilidi TEMEL_KILIT'e yazar (kilit\windows-x64-py3XX.txt).
REM Kilit yalniz 3.10-3.12 icin var; yoksa errorlevel 1 (hash'siz kuruluma dusulmez).
set "TEMEL_KILIT="
set "SV_PYV="
REM Surum gecici dosyaya yazdirilip "set /p" ile okunur (:isaret_hesapla ile ayni
REM desen). "for /f" + "%PYEXE%" -c "..." KULLANILMAZ: for /f komutu cmd /c ile
REM calistirir; komut tirnakla baslayip ikiden fazla tirnak icerince cmd ilk ve son
REM tirnagi soyar, komut bozulur ve SV_PYV bos kalir (1.3.1 CI'da boyle dustu).
del /f /q "sesver_pyv.tmp" >nul 2>nul
"%PYEXE%" -c "import sys;print(str(sys.version_info[0])+str(sys.version_info[1]))" >"sesver_pyv.tmp" 2>nul
if exist "sesver_pyv.tmp" set /p SV_PYV=<"sesver_pyv.tmp"
del /f /q "sesver_pyv.tmp" >nul 2>nul
if "%SV_PYV%"=="" goto :kilit_sec_okunamadi
if not exist "kilit\windows-x64-py%SV_PYV%.txt" goto :kilit_sec_yok
set "TEMEL_KILIT=kilit\windows-x64-py%SV_PYV%.txt"
exit /b 0
:kilit_sec_yok
echo [UYARI] Python %SV_PYV% icin paket kilidi yok (desteklenen: 3.10, 3.11, 3.12).
exit /b 1
:kilit_sec_okunamadi
echo [UYARI] Python surumu okunamadi: "%PYEXE%" -c calismadi.
exit /b 1

:kilitli_kur
REM %1 = kilit dosyasi; SV_EK = ek pip argumanlari (--no-deps ya da -c kisit).
REM pip --require-hashes ile kurar. Ozet tutmazsa SV_HASH_HATASI=1 olur ve ADIM'a
REM "SHA-256 uyusmazligi" eklenir (sihirbaz da bu adimi gosterir). pip --log ile
REM ayrintili gunluk gecici dosyaya da yazilir; cikti ekranda/kurulum_log'da kalir.
del /f /q "pip_kilit_gunluk.txt" >nul 2>nul
"%PYEXE%" -m pip install %KILIT_PIP% %SV_EK% -r "%~1" --log "pip_kilit_gunluk.txt"
if not errorlevel 1 goto :kilitli_kur_tamam
findstr /i /c:"DO NOT MATCH THE HASHES" /c:"Hashes are required" "pip_kilit_gunluk.txt" >nul 2>nul
if errorlevel 1 goto :kilitli_kur_hata
set "SV_HASH_HATASI=1"
set "ADIM=%ADIM% - SHA-256 uyusmazligi"
:kilitli_kur_hata
del /f /q "pip_kilit_gunluk.txt" >nul 2>nul
exit /b 1
:kilitli_kur_tamam
del /f /q "pip_kilit_gunluk.txt" >nul 2>nul
exit /b 0

:embed_kur
REM Tasinabilir Python'u indirir, SHA256 ile dogrular, python-embed\ olarak
REM yerlestirir. Basariliysa errorlevel 0, degilse 1 doner. Ozet tutmazsa
REM SV_HASH_HATASI=1 olur ve cagiran sistem Python'una gecmeden durur.
REM Ara dosyalar pbs_ onekiyle bu klasorde tutulur ve sonda silinir.
echo.
echo Python hazirlaniyor - bilgisayariniza ayrica Python kurmaniz gerekmez...
REM TEK yol: sabit surum + sabit SHA-256 (yayin sirasinda bilincli guncellenir).
REM "En yeni surum" sorgusu ve ayni kaynaktan gelen SHA256SUMS yok.
REM 3.11.18+20261026: ozet dosya indirilip shasum -a 256 ile dogrulandi (2026-11-08).
set "PBS_TAG=20261026"
set "PBS_DOSYA=cpython-3.11.18+20261026-x86_64-pc-windows-msvc-install_only.tar.gz"
set "PBS_SHA=75cb501dc11c7b55c6b447c58e4910bce5b1f609f1017328b4f3a858dfaf5428"
set "PBS_REPO=https://github.com/astral-sh/python-build-standalone/releases/download"
call :embed_temizle
if not exist "%SystemRoot%\System32\tar.exe" goto :embed_tar_yok
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
echo [HATA] Indirilen Python dosyasinin SHA-256 ozeti beklenenle ayni degil - bozuk ya da degistirilmis dosya.
echo   beklenen: %PBS_SHA%
set "SV_HASH_HATASI=1"
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
