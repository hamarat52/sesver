# Windows kurulum programı kullanıcıya ulaşmıyor — düzeltme raporu (WebDev)

Branch: `ci/windows-installer-release` (origin/main d57042f üzerinden)
Tarih: 2026-10-20

## 1. Kök neden

`windows/SesVer.iss` eksiksiz bir İleri/İleri/Kur sihirbazıydı (Başlat Menüsü + isteğe bağlı masaüstü kısayolu, SesVer.ico, Kaldır/Ekle kaydı). Ama ürettiği `.exe` hiçbir zaman son kullanıcıya ulaşmıyordu:

- `.github/workflows/windows-installer.yml` yalnız `workflow_dispatch` ve `ci/windows-installer*` push'unda çalışıyor, `.exe`'yi 14 günlük CI artifact'ı olarak yüklüyordu (artifact indirmek GitHub girişi ister).
- Release/tag akışı yoktu (`gh release list` boş, uzakta tag yok).
- README Windows bölümü kullanıcıyı "Code → Download ZIP → WINDOWS_BASLAT.bat" yoluna yönlendiriyordu. Bu yol kısayol, simge veya sihirbaz üretmez. Kullanıcının "ikon yok, İleri-İleri yok, tekrar nasıl açacağımı bilmiyorum" şikâyeti tam olarak bu.

## 2. Yapılan değişiklikler

### `.github/workflows/windows-installer.yml` (mevcut dosya genişletildi)

- Satır 14–18: `workflow_dispatch` girdisi `full_launch_test` (boolean, varsayılan false). `version` girdisi ve 1.0.0 varsayılanı korundu.
- Satır 23–24: `push: tags: ['v*']` eklendi; `ci/windows-installer*` branch tetikleyicisi korundu. (GitHub, tag push'larında `paths` filtresini uygulamaz; her v* tag'i derlenir.)
- Satır 33–34 ve 37–41: iş akışı düzeyinde ve `build` job'unda `permissions: contents: read`.
- Satır 48–76 (`Sürümü belirle`): öncelik sırası tag → dispatch girdisi → 1.0.0. Tag `^v(\d+\.\d+\.\d+)$` biçiminde değilse (ör. `v1.2`, `v1.2.3-beta`) `::error::Geçersiz tag biçimi …` mesajıyla `exit 1` (satır 59). Her parça 0–65535 aralığında olmalı (Windows VERSIONINFO sınırı). Sonuç, job çıktısı `version` olarak dışarı verilir.
- Derleme adımı ve mevcut duman testi korundu. Teste eklenenler:
  - Satır 122–130: Kaldır/Ekle kaydı `HKCU\…\Uninstall\{12D750B7-D7C7-400A-A81A-2A083B04A266}_is1` var mı. DisplayName=`SesVer`, DisplayVersion=sürüm, InstallLocation=kurulum klasörü, UninstallString dolu mu kontrol edilir. Kaldırmadan sonra kaydın silindiği de doğrulanır.
  - Satır 133–148: mevcut `$baslat`/`$masa` kontrolleri tamamlandı. Başlat Menüsü yolunun `$env:APPDATA\Microsoft\Windows\Start Menu\Programs\SesVer.lnk` olduğu doğrulanır. Her kısayolun TargetPath, WorkingDirectory ve IconLocation değerleri tam eşitlikle kontrol edilir (`<app>\WINDOWS_BASLAT.bat`, `<app>`, `<app>\SesVer.ico,0`). `.ico` dosyasının varlığına da bakılır.
  - Satır 150–198 (kısayoldan açılış): Başlat Menüsü kısayolunun TargetPath+Arguments değeri WorkingDirectory içinde `Start-Process` ile gerçekten çalıştırılır. Ölçüt aşağıda, bölüm 4'te.
- Satır 256–289: release dosyaları hazırlanır. Sabit adlı kopya `SesVer-Kurulum-Windows.exe` oluşturulur, iki dosyanın SHA256 değerinin eşitliği doğrulanır ve SHA256'ları içeren `RELEASE_NOTES.md` yazılır. Artifact'a `.exe`'ler ve notlar girer.
- Satır 291–307 (`Release dry-run`): yalnız `github.ref_type != 'tag'` olduğunda çalışır. "dry-run:" önekiyle şunları basar: hangi tag, hangi `gh release create` komutu, hangi asset'ler (boyut + sha256) ve notların tamamı.
- Satır 319–358 (`release` job'u): `needs: build`. Koşulu `push` + `ref_type == 'tag'` + `v` önekidir. Yetki yalnız bu job'da `contents: write`. Artifact'ı indirir; asset'lerin varlığını ve notlardaki SHA256'nın dosyayla eşleştiğini kontrol eder. Ardından `gh release create <tag> SesVer-Kurulum-<ver>.exe SesVer-Kurulum-Windows.exe --notes-file RELEASE_NOTES.md --verify-tag --latest` çalıştırır. Release zaten varsa `gh release upload --clobber` + `gh release edit` kullanır, böylece job yeniden çalıştırılabilir. 3. parti action kullanılmaz; yalnız `GITHUB_TOKEN` (`github.token`).
- Satır 360–474 (`full-launch` job'u, isteğe bağlı): yalnız `workflow_dispatch` + `full_launch_test=true` ile çalışır. Timeout 120 dk, `contents: read`. Kurar, Başlat Menüsü kısayolundan ilk açılışı yapar (gerçek pip/torch kurulumu dahil), `sesver_log.txt` içindeki `http://127.0.0.1:<port>` adresinden HTTP 200 bekler ve ekran görüntüsü alır. Ardından kurulum programını yeniden çalıştırır ve aynı kısayoldan ikinci açılışta tekrar HTTP 200 bekler. Günlükler ve PNG'ler artifact olarak yüklenir. Tag akışında çalışmaz, varsayılan akışı yavaşlatmaz.

Gerekçe: neden ayrı `release` job'u? Brief'in (d) maddesi gereği yazma yetkisi yalnız yayın adımında olmalı. GitHub Actions'ta `permissions` job düzeyinde verilir, adım düzeyinde verilemez. Aynı job'da son adım olarak yayınlasaydık derleme ve test adımları da (3. parti betikler, choco, indirilen Python) `contents: write` token'ıyla çalışırdı. Ayrı job ve `needs: build` ile release yalnız derleme + duman testi başarılıysa koşar ve yetki yalnız artifact'ı yükleyen küçük ubuntu job'unda kalır.

### `README.md` (yalnız Windows bölümü ve ortak Sorun giderme satırları; Mac bölümü, satır 29–39, değişmedi)

- Satır 9–27 "🪟 Windows Kurulum" yeniden yazıldı. Birincil yol: doğrudan link `releases/latest/download/SesVer-Kurulum-Windows.exe` + `releases/latest` → çift tık → SmartScreen'de "Ek bilgi → Yine de çalıştır" (kod imzasız) → İleri/İleri/Kur → son sayfada "İlk kurulumu şimdi başlat" işaretli kalsın (metin `windows/SesVer.iss:82` ile aynı) → Bitir.
- Satır 19–23 "Sonra nasıl açarım?": Başlat menüsünde "SesVer" yaz / masaüstü simgesi. Kaldırma: Ayarlar → Uygulamalar → SesVer (`voices\seslerim` ve `outputs` korunur; duman testi bunu doğruluyor).
- Satır 25–27 "Alternatif (ileri kullanıcı): ZIP ile": kısaltıldı, kısayol/simge oluşturmadığı açıkça yazıldı.
- Satır 57: "Sonraki kullanımlarda" cümlesi Windows'ta simgeye yönlendiriyor.
- Satır 78–80, 84 (Sorun giderme): SmartScreen'de "Yine de çalıştır" yoksa ne yapılacağı ("Engellemeyi kaldır"), kayıp simge için kurulumu yeniden çalıştırma, eski sürüm ve yarım kalan kurulum maddeleri bu akışa uyarlandı.

### Dokunulmayanlar

`windows/SesVer.iss` (AppId dahil), `WINDOWS_BASLAT.bat`, macOS dosyaları ve Python kaynakları değiştirilmedi.

## 3. Doğrulama

### Yerel
- `python3 -c 'import yaml; …'` → `YAML OK jobs= ['build', 'release', 'full-launch'] push= ['v*'] ['ci/windows-installer*']`
- `actionlint 1.7.12 .github/workflows/windows-installer.yml` → çıktı yok, `exit=0` (shellcheck kurulu; release job'unun bash betiği de denetlendi).
- Tag regex'i (Python'da eşdeğeri): `v1.2.3→1.2.3`, `v10.20.30→10.20.30`, `v1.2→HATA`, `v1.2.3-beta→HATA`, `1.2.3→HATA`.

### CI
- Run **39422295245**: https://github.com/hamarat52/sesver/actions/runs/39422295245
  - commit 780c9cc (bu rapor eklenmeden önceki iş akışı/README hâli; teslim commit'i aynı iş akışı ve README'ye ek olarak yalnız bu raporu içerir)
  - olay: `push` → `ci/windows-installer-release`, sonuç: **success**
  - `build`: success, https://github.com/hamarat52/sesver/actions/runs/39422295245/job/118626011091
  - `release`: **skipped** (tag değil; beklenen)
  - `full-launch`: **skipped** (dispatch değil; beklenen)

Log alıntıları (run 39422295245, `build` job'u):

```
Sürüm: 1.0.0 (kaynak: varsayılan)
Üretildi: D:\a\sesver\sesver\windows\Output\SesVer-Kurulum-1.0.0.exe (5,562,998 bayt)
Kaldır/Ekle: DisplayName=SesVer DisplayVersion=1.0.0 Publisher=HamaratLabs InstallLocation=C:\Users\runneradmin\AppData\Local\Programs\SesVer\ DisplayIcon=
C:\Users\runneradmin\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\SesVer.lnk -> C:\Users\runneradmin\AppData\Local\Programs\SesVer\WINDOWS_BASLAT.bat  [C:\Users\runneradmin\AppData\Local\Programs\SesVer] ikon=C:\Users\runneradmin\AppData\Local\Programs\SesVer\SesVer.ico,0
C:\Users\runneradmin\Desktop\SesVer.lnk -> C:\Users\runneradmin\AppData\Local\Programs\SesVer\WINDOWS_BASLAT.bat  [C:\Users\runneradmin\AppData\Local\Programs\SesVer] ikon=C:\Users\runneradmin\AppData\Local\Programs\SesVer\SesVer.ico,0
Çalıştırılıyor: C:\Users\runneradmin\AppData\Local\Programs\SesVer\WINDOWS_BASLAT.bat  (çalışma klasörü: C:\Users\runneradmin\AppData\Local\Programs\SesVer)
[SesVer baslatici calisiyor]
Python hazirlaniyor - bilgisayariniza ayrica Python kurmaniz gerekmez...
Indiriliyor: cpython-3.11.17+…-x86_64-pc-windows-msvc-install_only.tar.gz
Python hazir.
Ilk kurulum yapiliyor - bu sadece bir kere calisir...
Kurulum klasöründeki python-embed: Python 3.11.17
Kısayoldan açılış KANITLANDI: kısayol hedefi çalıştı, Python indirildi+doğrulandı+çalıştı, pip ilk kurulum adımı başladı. (torch kurulumu ve pencere açılışı bu job'da test edilmez.)
WebView2 Runtime: 154.0.4258.62
…\Start Menu\Programs\SesVer.lnk -> …\SesVer\python-embed\pythonw.exe -E -s "…\SesVer\desktop.py" […\SesVer] ikon=…\SesVer\SesVer.ico,0
Duman testi BAŞARILI: kurulum, Kaldır/Ekle kaydı, kısayollar (hedef/çalışma klasörü/ikon), kısayoldan açılış (başlatıcı + Python + pip başlangıcı), kısayol seçimi, kaldırma ve kullanıcı verisinin korunması doğrulandı.
```

Release dry-run kanıtı (aynı run):

```
dry-run: bu koşu (push, ref 'ci/windows-installer-release') bir tag değil; GitHub Release OLUŞTURULMADI.
dry-run: tag v1.0.0 push edilseydi release job'u şu komutla yayınlardı:
dry-run:   gh release create v1.0.0 SesVer-Kurulum-1.0.0.exe SesVer-Kurulum-Windows.exe --title 'SesVer 1.0.0' --notes-file RELEASE_NOTES.md --verify-tag --latest
dry-run: asset SesVer-Kurulum-1.0.0.exe (5,562,998 bayt) sha256=f6a123e831cbc9ddf3f2c223c8c55cb8958819b40964cc9ec5baf0ab031b78ef
dry-run: asset SesVer-Kurulum-Windows.exe (5,562,998 bayt) sha256=f6a123e831cbc9ddf3f2c223c8c55cb8958819b40964cc9ec5baf0ab031b78ef
dry-run: | f6a123e8…78ef  SesVer-Kurulum-1.0.0.exe
dry-run: | f6a123e8…78ef  SesVer-Kurulum-Windows.exe
dry-run: | Her zaman en son sürüm: https://github.com/hamarat52/sesver/releases/latest/download/SesVer-Kurulum-Windows.exe
```

## 4. Kısayoldan açılış: kanıtlanan / kanıtlanamayan

Kanıtlanan (CI, windows-latest, run 39422295245):
- Sessiz kurulumdan sonra Başlat Menüsü ve masaüstü `.lnk` dosyaları gerçek dosya sisteminde mevcut. Hedef, çalışma klasörü ve `SesVer.ico,0` ikonu WScript.Shell ile okunup doğrulandı.
- Kaldır/Ekle kaydı mevcut (DisplayName=SesVer, DisplayVersion=1.0.0) ve kaldırmadan sonra siliniyor.
- Başlat Menüsü kısayolunun hedefi `Start-Process` ile çalıştırıldı. Başlatıcı açıldı, taşınabilir Python 3.11'i indirdi ve SHA256 ile doğrulayıp çıkardı (`python-embed\python.exe --version` → `Python 3.11.17`). Ardından pip ile ilk kurulum adımı başladı. Ölçüt "ilk kurulum adımına 12 dk içinde ulaşıldı"; sonra süreç kasıtlı olarak sonlandırıldı.
- Ortam hazır sayıldığında ve WebView2 mevcutken, yeniden kurulumla kısayollar `pythonw.exe -E -s desktop.py` hedefine çevriliyor ve ikon korunuyor. Bu adımda `pythonw.exe` bir taklit (cmd.exe kopyası); yalnız kısayol seçimi test edilir.
- Kaldırmada program dosyaları, kısayollar ve kayıt siliniyor; `voices\seslerim` ve `outputs` korunuyor.

**CI'da doğrulanamadı, gerçek Windows makinede test edilmeli:**
- Paket kurulumunun (torch vb.) tamamlanması ve ilk açılışta SesVer penceresinin (desktop.py "acildi" / `127.0.0.1:<port>` HTTP 200) gelmesi. Bunun için `full-launch` job'u yazıldı (`gh workflow run windows-installer.yml --ref ci/windows-installer-release -f full_launch_test=true`), ama bu oturumda **çalıştırılmadı**. Brief yalnız push'a izin verdiği için sonucu bilinmiyor. GitHub runner'ı GPU'suz olduğu ve 14 GB disk sınırı bulunduğu için orada da başarısız olabilir.
- İkinci açılışın gerçek `pythonw.exe desktop.py` kısayoluyla pencere açması.
- Sihirbazın etkileşimli akışı: lisans sayfası, İleri/İleri/Kur, son sayfadaki "İlk kurulumu şimdi başlat" kutusu. CI sessiz kurulum (`/VERYSILENT`) kullanır; `postinstall skipifsilent` adımı sessiz kurulumda çalışmaz.
- SmartScreen uyarısı ve "Ek bilgi → Yine de çalıştır" davranışı (yalnız internetten indirilen, Mark-of-the-Web taşıyan dosyada görülür).
- Ayarlar → Uygulamalar listesinde görünüm (kayıt doğrulandı, UI görülmedi).
- `release` job'unun gerçek yayını: tag push edilmedi. Yalnız dry-run ve actionlint kanıtı var. Geçersiz tag hata yolu da CI'da çalıştırılmadı; yalnız regex'i yerelde doğrulandı.

## 5. Yayınlama için ana oturumun yapacağı adım (WebDev YAPMADI)

1. Bu branch'i main'e alın (PR/merge onaylı iş).
2. main üzerinde tag oluşturup push edin:
   `git tag v1.0.0 && git push origin v1.0.0`
3. Actions'ta `build` → `release` job'larının yeşil olduğunu kontrol edin. Ardından https://github.com/hamarat52/sesver/releases/latest sayfasında iki asset ve SHA256 notunu görün.
4. Sonraki sürümlerde aynı biçimde (`vMAJOR.MINOR.PATCH`) tag atın; sabit link otomatik olarak yeni sürümü gösterir.

## 6. hamaratlabs-web `data.js` için önerilen link (yalnız bilgi; değiştirilmedi)

- Windows indirme düğmesi: `https://github.com/hamarat52/sesver/releases/latest/download/SesVer-Kurulum-Windows.exe`
- "Tüm sürümler" bağlantısı: `https://github.com/hamarat52/sesver/releases/latest`

Not: Bu linkler ilk `v*` tag'i yayınlanana kadar 404 döner.

## 7. Açık riskler

- Kod imzası yok: SmartScreen uyarısı her yeni sürümde çıkabilir (README'de anlatıldı).
- Kaldır/Ekle kaydında `DisplayIcon` boş (log'da `DisplayIcon=`). Ayarlar → Uygulamalar'da SesVer genel bir simgeyle görünebilir. Bunun için `.iss`'e `UninstallDisplayIcon={app}\SesVer.ico` eklenmesi gerekir; kapsam dışı olduğu için dokunulmadı.
- İlk kurulumun tamamlanması ve pencere açılışı CI'da kanıtlanmadı (bkz. bölüm 4).
- Release job'u gerçek tag ile hiç çalışmadı; ilk tag push'u dikkatle izlenmeli.
