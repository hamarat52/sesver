# SesVer — Yapay zekâ asistanıyla kurulum (KURULUM.md)

> **Kullanıcı için:** Bu dosyanın tamamını kopyalayın ve kendi yapay zekâ sohbetinize (ChatGPT, Claude, Gemini…) yapıştırın. Altına "Bunu kurmama yardım et" yazın. Asistan sizi adım adım yönlendirecek.
>
> Dosyayı GitHub'da açıp sağ üstteki kopyala simgesine (üst üste iki kare) basarsanız tüm metin kopyalanır: https://github.com/hamarat52/sesver/blob/main/KURULUM.md

---

## 1. Asistana talimat (önce bunu oku)

Sen, **SesVer** adlı ücretsiz ve yerel bir Türkçe ses üretme uygulamasının kurulumunda kullanıcıya yardım ediyorsun. Bu dosya senin için yazıldı.

Kurallar:

1. **Kullanıcının teknik bilgisi az.** Türkçe ve kısa cümleler kullan. Bir teknik terimi ilk kullandığında parantez içinde açıkla. Örnek: "terminal (komut yazılan pencere)".
2. **Her mesajda yalnız bir adım ver.** Adımın sonunda kullanıcıdan ekranda ne gördüğünü ya da komutun çıktısını iste. Cevap gelmeden sonraki adıma geçme.
3. **Hata çıkarsa** önce aşağıdaki **"7. Sorun giderme"** bölümüne bak. Hatayı oradaki bir maddeyle eşleştir ve oradaki çözümü uygula. Eşleşmiyorsa tahminde bulunduğunu açıkça söyle.
4. **Kullanıcıdan şifre, token, API anahtarı, GitHub şifresi ya da doğrulama kodu isteme.** Kullanıcı bunları sohbete yazmaya kalkarsa durdur. Şifre yalnız kendi bilgisayarının ya da GitHub'ın penceresine yazılır.
5. **Yönetici izni isteyen adımları önceden açıkla.** `sudo` (Mac/Linux), "Yönetici olarak çalıştır" ya da Windows'un "Bu uygulamanın değişiklik yapmasına izin verilsin mi?" sorusu çıkacaksa önce şunları söyle: bu adım ne yapıyor, neden gerekiyor, şifre sorulursa bilgisayarın kendi şifresi olduğu ve ekranda görünmeyeceği. SesVer'in kendisi yönetici izni istemez. Yönetici izni yalnız Python kurulumunda, Linux paketlerinde ve isteğe bağlı Windows uzun yol ayarında gerekebilir.
6. **Bu dosyada olmayan komut ya da dosya adı uydurma.** Başlatıcıların adı `WINDOWS_BASLAT.bat` ve `MACOS_BASLAT.command`. Uygulamanın adresi `http://127.0.0.1:7860`.
7. **Güvenliği toptan kapatan komutlar önerme.** Örnekler: `sudo spctl --master-disable`, antivirüsü kapatmak, SmartScreen'i kapatmak. Bunların yerine bu dosyadaki tek dosyalık izin yöntemlerini kullan.
8. Kullanıcıdan kişisel ses kaydı ya da özel dosya isteme.

---

## 2. SesVer hakkında (arka plan bilgisi)

- Bilgisayarda çalışır. Türkçe metni sese çevirir ve ses klonlar. Hesap ya da ücretli servis gerekmez.
- Depo: https://github.com/hamarat52/sesver. Şu an **özel (private)**: sayfayı açmak ve indirmek için GitHub hesabıyla giriş yapılmış olmalı ve depoya erişim izni olmalı.
- Arayüz tarayıcıda açılır: **http://127.0.0.1:7860**. Tarayıcı **kendiliğinden açılmaz**; adresi kullanıcı yazar.
- Ses modeli (OpenBMB VoxCPM2) büyüktür. **İlk "Üret" tıklamasında yaklaşık 5 GB** indirilir. Bu yalnız ilk seferde internet gerektirir.
- Çalışırken model belleğin yaklaşık 9 GB'ını kullanır (M1 / 16 GB üzerinde ölçüldü).
- Hızlı değildir. M1 / 16 GB'ta 10 saniyelik ses yaklaşık 70–80 saniyede üretilir. Ekran kartı olmayan bilgisayarlarda bu daha da uzun sürebilir.

---

## 3. Önce sorulacaklar

Kuruluma başlamadan önce kullanıcıya şunları **tek tek** sor:

**S1 — İşletim sistemi ne?**

- **Mac:** Sol üstteki elma simgesi → **Bu Mac Hakkında**.
  - "Çip: Apple M1/M2/M3/M4…" yazıyorsa → **Apple Silicon**.
  - "İşlemci: Intel…" yazıyorsa → **Intel Mac**. (Aşağıdaki Intel uyarısını oku.)
  - macOS sürümünü de not et.
- **Windows:** **Ayarlar → Sistem → Hakkında** ekranında "Windows 10" ya da "Windows 11" yazar.
- **Linux:** Dağıtımın adını ve sürümünü sor (örneğin Ubuntu 24.04).

**S2 — Boş disk alanı en az 20 GB mı?** Ortam, model ve paket önbellekleri toplam ~17–19 GB tutabilir.

- Mac: elma → **Sistem Ayarları → Genel → Depolama**.
- Windows: **Dosya Gezgini → Bu bilgisayar**. C: sürücüsünün altında boş alan yazar.
- 20 GB'tan azsa önce yer açmasını söyle. Yer açılmadan kuruluma başlama.

**S3 — RAM (bellek) kaç GB?**

- Mac: **Bu Mac Hakkında** ekranında "Bellek" satırı.
- Windows: **Ayarlar → Sistem → Hakkında** ekranında "Yüklü RAM" satırı.
- **16 GB ve üstü önerilir.** 8 GB'ta neredeyse kullanılamayacak kadar yavaş olabilir ve bilgisayar kilitlenebilir. Bunu kullanıcıya kuruluma başlamadan açıkça söyle; devam edip etmeyeceğine o karar versin.

**S4 — NVIDIA ekran kartı var mı?** (Yalnız Windows ve Linux için.)

- Windows: **Görev Yöneticisi** (Ctrl+Shift+Esc) → **Performans** sekmesi. GPU satırında "NVIDIA" yazıyor mu?
- Ekran kartı zorunlu değil. Varsa kurulum çalıştıktan sonra **6. bölümdeki** isteğe bağlı adım hızı artırabilir.

**S5 — Python kurulu mu?** Bunu platform adımlarının ilk adımında kontrol edeceksin.

### Uygun olmayan durumlar (kullanıcıya dürüstçe söyle)

- **Intel Mac:** `requirements.txt` dosyası `torch>=2.5.0` istiyor. PyPI'da (Python paket deposu) PyTorch 2.5.0 için Intel Mac paketi yok; Intel Mac için son paket 2.2.2. Bu yüzden kurulum büyük olasılıkla `requirements.txt kurulumu` adımında durur. Bu durum test edilmedi. Kullanıcıya bunu söyle ve başka bir bilgisayar önermeyi düşün.
- **Linux:** Başlatıcı (`MACOS_BASLAT.command`) Linux'ta da çalışacak şekilde yazıldı, ama Linux'ta test edilmedi.
- **Python 3.13 veya üstü:** Önerilmez. Başlatıcı yalnız uyarı verir, kurulum başarısız olabilir. Python 3.11 kurdur.

---

## 4. Kurulum adımları

Kullanıcının platformuna uyan bölümü uygula. Kurulumun özeti: Python 3.11 kurulur → SesVer indirilir → başlatıcıya çift tıklanır → `Running on local URL` yazısı beklenir → tarayıcıda adres açılır.

### 4A. Windows 10 / 11

**W1 — Python'u kontrol et.**
Başlat menüsünü aç, `cmd` yaz ve **Komut İstemi**'ni aç. Şu iki komutu sırayla yazdır ve çıktıları iste:

```bat
py --version
python --version
```

- Biri `Python 3.10.x`, `3.11.x` ya da `3.12.x` yazıyorsa Python hazır. **W3**'e geç.
- `... is not recognized` yazıyorsa, Microsoft Store açılıyorsa ya da sürüm 3.13 veya üstüyse **W2**'ye geç.

**W2 — Python 3.11'i kur.**

1. https://www.python.org/downloads/ adresine git. **Python 3.11** sürümünü bul ve Windows installer (64-bit) dosyasını indir. 3.13 veya üstünü seçme.
2. Kurulum dosyasını aç. İlk ekranın en altındaki **"Add python.exe to PATH"** kutusunu **mutlaka işaretle**. Sonra **Install Now**'a bas.
3. Windows "değişiklik yapmasına izin verilsin mi?" diye sorabilir. Bu Python kurulumu içindir, **Evet** de.
4. Son ekranda **"Disable path length limit"** seçeneği çıkarsa ona basmak önerilir. Bu, Windows'un uzun klasör yolu sınırını kaldırır. Yönetici izni ister.
5. Komut İstemi'ni kapat, yeniden aç ve **W1**'deki komutları tekrar çalıştır.

**W3 — SesVer'i indir.** İki yol var. Teknik olmayan kullanıcı için **ZIP yolu** önerilir.

- **ZIP yolu:**
  1. https://github.com/hamarat52/sesver adresine git. Depo özel olduğu için GitHub hesabıyla giriş yapmış olmalı.
  2. Yeşil **Code** düğmesine bas → **Download ZIP**.
  3. İndirilenler klasöründeki `sesver-main.zip` dosyasına sağ tıkla → **Tümünü Ayıkla** → **Ayıkla**.
  4. Dosyaları ZIP'in içinden çalıştırma. Çıkarılmış `sesver-main` klasörüne gir.
  5. Öneri: Klasörü `C:\SesVer` gibi kısa bir yola taşı. Uzun yol hatalarını önler (bkz. 7. bölüm).
- **Git yolu** (Git kuruluysa):

  ```bat
  git clone https://github.com/hamarat52/sesver.git
  cd sesver
  ```

  Depo özel olduğu için Git, GitHub girişi isteyebilir. Giriş tarayıcıda ya da Git'in kendi penceresinde yapılır. Şifreyi ya da token'ı sohbete yazmamasını söyle. Bu yolda klasörün adı `sesver` olur.

**W4 — Başlatıcıyı çalıştır.**

1. Klasördeki `WINDOWS_BASLAT.bat` dosyasına çift tıkla. Dosya uzantıları gizliyse yalnız `WINDOWS_BASLAT` görünebilir.
2. "Windows bilgisayarınızı korudu" (SmartScreen) uyarısı çıkarsa **Ek bilgi** → **Yine de çalıştır**.
3. Siyah bir pencere açılır ve sırayla şunlar görünür:
   - `[SesVer baslatici calisiyor]`
   - `Kullanilan Python komutu: ...`
   - `Ilk kurulum yapiliyor - bu sadece bir kere calisir...`
4. Başlatıcı Python'u şu sırayla arar: `py -3.11` → `py` → `python`. Bunun için elle bir şey yapmak gerekmez.

**W5 — Bekle.** Kurulum paketleri indirir. Bu, internet hızına bağlı olarak birkaç dakika sürer. Kurulum bitince sırayla şunlar görünür:

- `Kurulum tamamlandi.`
- `SesVer baslatiliyor... Tarayicinizda http://127.0.0.1:7860 acilacak.`
- `Running on local URL: http://127.0.0.1:7860`

Not: Mesajda "acilacak" yazsa da tarayıcı kendiliğinden açılmaz. **Siyah pencereyi kapatma.** SesVer o pencere açıkken çalışır. Ardından **5. bölüme** geç.

### 4B. macOS (Apple Silicon)

**M1 — Python'u kontrol et.**
**Terminal** uygulamasını aç: Spotlight (Cmd+Boşluk) → `Terminal`. Şu komutları yazdır ve çıktıları iste:

```bash
python3.11 --version
python3 --version
```

- `Python 3.10.x`, `3.11.x` ya da `3.12.x` görünüyorsa Python hazır. **M3**'e geç.
- Başlatıcı Python'u şu sırayla arar: `python3.11` → `python3.12` → `python3.10` → `python3`.
- `python3` yazınca "komut satırı geliştirici araçlarını yükle" penceresi açılabilir. Bu Apple'ın penceresidir. Onun yerine **M2** ile python.org kurulumunu yapmak daha kısadır.

**M2 — Python 3.11'i kur.**

1. https://www.python.org/downloads/ adresine git. **Python 3.11** için **macOS 64-bit universal2 installer** (`.pkg`) dosyasını indir. 3.13 veya üstünü seçme.
2. `.pkg` dosyasını aç ve adımları izle. Mac bilgisayar şifresini sorar. Bu Mac'in kendi şifresidir; sohbete yazılmaz.
3. Terminal'i kapatıp yeniden aç ve `python3.11 --version` komutunu tekrar çalıştır.

**M3 — SesVer'i indir.**

- **ZIP yolu:** https://github.com/hamarat52/sesver adresine git (GitHub girişi gerekli). **Code → Download ZIP**. İndirilenler klasöründeki ZIP'e çift tıkla; `sesver-main` klasörü oluşur.
- **Git yolu:** Terminal'de:

  ```bash
  git clone https://github.com/hamarat52/sesver.git
  cd sesver
  ```

  Git kurulu değilse macOS geliştirici araçlarını kurmayı önerir. Teknik olmayan kullanıcı için ZIP yolu daha basittir.

**M4 — Başlatıcıyı çalıştır (Gatekeeper izni dahil).**

1. Klasördeki `MACOS_BASLAT.command` dosyasına çift tıkla.
2. "Apple doğrulayamadı" ya da "bilinmeyen geliştirici" uyarısı çıkarsa:
   - Dosyaya **sağ tık** (ya da Control + tık) → **Aç** → tekrar **Aç**.
   - Bu seçenek yoksa (macOS 15 Sequoia ve sonrası): **Sistem Ayarları → Gizlilik ve Güvenlik**. Aşağıda bu dosyayla ilgili satırda **Yine de Aç**'a bas. Mac şifresini ya da Touch ID'yi isteyebilir.
3. Terminal penceresi açılır ve şunları gösterir:
   - `[SesVer başlatıcı çalışıyor]`
   - `Kullanılan Python komutu: ...`
   - `İlk kurulum yapılıyor (bu sadece bir kere çalışır)...`
4. Dosya hiç açılmıyorsa ya da "izin verilmedi" (`Permission denied`) yazıyorsa 7. bölümdeki **Mac: başlatıcı açılmıyor** maddesine bak.

**M5 — Bekle.** Kurulum bitince sırayla şunlar görünür:

- `Kurulum tamamlandı.`
- `SesVer başlatılıyor... Tarayıcınızda http://127.0.0.1:7860 adresini açın.`
- `Running on local URL: http://127.0.0.1:7860`

Terminal penceresini **kapatma**. Ardından **5. bölüme** geç.

### 4C. Linux (test edilmedi)

1. Python sürümünü kontrol et: `python3 --version`. 3.10–3.12 olmalı. Değilse dağıtımın paket yöneticisiyle kurulmalı. Bu adım `sudo` ve bilgisayar şifresi ister; önce kullanıcıya açıkla. Paket adı dağıtıma göre değişir. Emin değilsen söyle.
2. Debian/Ubuntu'da `venv` modülü ayrı bir pakettedir (`python3-venv` ya da sürümlü adı, örneğin `python3.11-venv`). Bu paket yoksa sanal ortam adımı hata verir.
3. Git ya da ZIP ile indir (4B/M3 ile aynı), klasöre gir ve terminalde şu komutu çalıştır:

   ```bash
   bash MACOS_BASLAT.command
   ```

4. `Running on local URL: http://127.0.0.1:7860` yazısını bekle ve **5. bölüme** geç.

---

## 5. İlk çalıştırma

**İ1 — Arayüzü aç.** Chrome, Edge, Safari ya da Firefox'u aç ve adres çubuğuna **http://127.0.0.1:7860** yaz.

Kurulumun başarılı olduğunu şunlardan anlarsın: Sol üstte **SESVER** yazar. Ortada **"Yazdığınız metne ses verin."** başlığı vardır. Altında **Ses Kütüphanesi**, **Ses Oluştur** ve **Ses Klonlama** sekmeleri görünür.

**İ2 — İlk sesi üret (model indirmesi burada olur).**

1. **Ses Kütüphanesi** sekmesinde bir hazır ses seç, örneğin "Belgesel Anlatıcı".
2. Metin kutusuna tek ve kısa bir Türkçe cümle yaz. En fazla 500 karakter yazılabilir.
3. **Üret** düğmesine **bir kez** bas. Tekrar tekrar basma; istekler sırayla işlenir.
4. Ekranda `İşleniyor… İlk kullanımda model indiriliyor/yükleniyor` yazar. Bu sırada ses modeli (**yaklaşık 5 GB**) Hugging Face'ten (model indirme sitesi) bir kez indirilir. İndirme ilerlemesi siyah pencerede ya da Terminal'de görünür.
   - README'de indirme için kesin bir süre yok; süre internet hızına bağlı. Kabaca: 50 Mbit/sn hızla 5 GB yaklaşık 15 dakika sürer. Daha yavaş bağlantıda daha uzun sürer.
   - İndirmeden sonra model belleğe yüklenir. Bu da birkaç dakika sürebilir. README'deki M1 testinde ilk üretim, model yüklemesi dahil 205,9 saniye sürdü.
5. Ses hazır olunca sayfada dinlenebilir. **⬇ WAV indir** ile kaydedilir. Ayrıca SesVer klasöründeki `outputs` klasörüne yazılır.

**Sonraki açılışlar:** Kurulum tekrarlanmaz. Başlatıcıya çift tıkla, `Running on local URL` yazısını bekle ve tarayıcıda http://127.0.0.1:7860 adresini aç. Model önbellekte durduğu için tekrar indirilmez.

**Kapatmak için:** Siyah pencerede ya da Terminal'de **Ctrl+C** bas veya pencereyi kapat.

**Kullanıcıya hatırlat:** Ürettiği sesi paylaşırken "AI ile üretildi" diye belirtmesi gerekir. Uygulama sese filigran eklemez.

---

## 6. İsteğe bağlı: NVIDIA ekran kartıyla hızlandırma (Windows/Linux)

Bu adımı yalnız kurulum çalıştıktan sonra ve kullanıcı isterse uygula. Zorunlu değildir. Model uygun cihazı kendisi şu sırayla seçer: CUDA (NVIDIA) → Apple MPS → CPU.

1. https://pytorch.org/get-started/locally/ adresindeki seçicide şunları seç: işletim sistemi, **Pip**, **Python** ve bir **CUDA** sürümü. Sayfa bir `pip install ...` komutu verir.
2. SesVer klasöründe PowerShell aç: klasörün adres çubuğuna `powershell` yazıp Enter'a bas.
3. Sayfanın verdiği komutta baştaki `pip install` yerine `.\.venv\Scripts\python.exe -m pip install` yaz. Komutun geri kalanını aynen bırak ve sonuna `--force-reinstall` ekle.
4. SesVer'i başlatıcıyla yeniden aç.

Bu komut PyTorch sürümüne göre değişir. Kesin komutu uydurma; pytorch.org'un verdiği komutu kullan.

---

## 7. Sorun giderme

Kullanıcı bir hata yapıştırınca önce bu listeye bak. Satır başlarındaki `[HATA]`, `[UYARI]` ve `[BILGI]` mesajları başlatıcılardan, Türkçe arayüz mesajları `app.py` dosyasından gelir.

**Python sürümü ya da Python bulunamadı**

- Windows'ta `[HATA] Python bulunamadi. "py" ve "python" komutlari calismiyor.`, Mac'te `Python bulunamadı. Lütfen Python 3.10–3.12 kurun`:
  - Python 3.11'i kur (W2 / M2). Windows'ta **"Add python.exe to PATH"** kutusu işaretli olmalı.
  - Python zaten kuruluysa kurulum dosyasını tekrar aç → **Modify** → **Add Python to environment variables** seçeneğini işaretle.
  - Windows'ta Microsoft Store açılıyorsa: **Ayarlar → Uygulamalar → Uygulama yürütme diğer adları** → `python.exe` ve `python3.exe` anahtarlarını kapat.
- `[UYARI] Onerilen surum Python 3.10-3.12; kurulum basarisiz olabilir.` (Mac'te aynı uyarı Türkçe karakterlerle görünür): Python 3.13 veya üstü kullanılıyor.
  - Python 3.11'i kur.
  - SesVer klasöründeki `.venv` klasörünü sil. Bu klasör gizli olabilir; Mac'te Finder'da Cmd+Shift+. ile gizli dosyalar görünür.
  - Başlatıcıyı tekrar çalıştır. Başlatıcı önce 3.11'i dener.
- `py` komutu bulunamıyor: Başlatıcı `python` komutunu kendisi dener. Elle komut yazılıyorsa `py -3.11` yerine `python` kullan.

**Kurulum adımı başarısız / indirme yarıda kaldı**

- `[HATA] Kurulum adimi basarisiz oldu: ...` (Mac: `Kurulum adımı başarısız oldu: ...`): Satırın sonunda hangi adımda durduğu yazar. Olası adımlar: `sanal ortam oluşturma`, `pip güncelleme`, `voxcpm kurulumu`, `requirements.txt kurulumu`.
  - En sık sebepler: internet kesintisi ya da disk dolu.
  - İnterneti ve boş alanı kontrol et, sonra başlatıcıyı **tekrar çalıştır**. Kurulum kaldığı yerden devam eder; tamamlanmış kurulum `.venv/sesver_kurulum_tamam.txt` dosyasıyla işaretlenir.
  - Hata sürerse kullanıcıdan `[HATA]` satırının hemen üstündeki kırmızı ya da İngilizce satırları iste.
- Intel Mac'te `requirements.txt kurulumu` adımında `No matching distribution found for torch>=2.5.0`: Intel Mac için uygun PyTorch paketi yok (bkz. 3. bölüm). Bu, kurulumla çözülebilecek bir sorun değil.
- Model indirmesi yarıda kaldı (ilk Üret sırasında internet kesildi, pencere kapandı): Başlatıcıyı yeniden aç ve **Üret**'e tekrar bas. Hugging Face indirmesi kaldığı yerden devam eder. Hata sürerse 9. bölümde yolu yazılı `models--openbmb--VoxCPM2` klasörünü sil ve tekrar dene. Bu durumda model baştan indirilir.

**Disk dolu**

- `No space left on device`, `Errno 28` ya da `There is not enough space on the disk` gibi mesajlar görünür.
- En az 20 GB boş alan aç. Yarım kalan kurulumu temizlemek için `.venv` klasörünü sil ve başlatıcıyı tekrar çalıştır.

**Port dolu (7860 kullanımda)**

- `Cannot find empty port in range: 7860-7860` ya da `address already in use` mesajı görünür.
- Sebep: SesVer zaten başka bir pencerede açık.
- Önce tarayıcıda http://127.0.0.1:7860 adresini dene; açılıyorsa SesVer zaten çalışıyordur.
- Kapatıp yeniden açmak için eski penceredeki SesVer'i **Ctrl+C** ile durdur ya da o pencereyi kapat.
- Port başka bir program tarafından kullanılıyorsa farklı port seçilebilir (`app.py` bu portu `GRADIO_SERVER_PORT` değişkeninden okur):
  - Mac/Linux, Terminal'de SesVer klasöründeyken: `GRADIO_SERVER_PORT=7861 ./MACOS_BASLAT.command`
  - Windows, Komut İstemi'nde SesVer klasöründeyken önce `set GRADIO_SERVER_PORT=7861`, sonra `WINDOWS_BASLAT.bat`. Windows başlatıcısının mesajı yine 7860 yazar, ama doğru adres http://127.0.0.1:7861 olur.

**Tarayıcıda "Bu siteye ulaşılamıyor" / `ERR_CONNECTION_REFUSED`**

- SesVer penceresi kapalı ya da kurulum henüz bitmedi. `Running on local URL` yazısını bekle. Pencere kapandıysa başlatıcıyı tekrar çalıştır.

**Apple Silicon (MPS) ve bellek**

- Apple Silicon'da model ekran kartını (MPS) otomatik kullanır ve float32 hassasiyetle çalışır. Elle ayar gerekmez. `VOXCPM_MPS_DTYPE` değişkenini kurdurma.
- PyTorch belgelerine göre MPS için macOS 12.3 veya üstü gerekir. Daha eski macOS'ta model CPU'da çalışır ve çok yavaş olur.
- `MPS backend out of memory`, `out of memory` ya da `MemoryError` hatası çıkarsa ya da bilgisayar donarsa:
  - SesVer'i Ctrl+C ile durdur.
  - Diğer ağır uygulamaları ve tarayıcı sekmelerini kapat.
  - Daha kısa metinle tekrar dene.
  - Bellek sınırını kaldıran ortam değişkenleri önerme; sistemi kilitleyebilir.
- Arayüzde `Üretim başarısız. İlk indirme için interneti, boş disk alanını ve RAM'i kontrol edin...` yazıyorsa ayrıntı siyah pencerede ya da Terminal'dedir. Kullanıcıdan oradaki son satırları iste.

**Windows: uzun yol ve izin sorunları**

- `OSError`, `No such file or directory` ya da `Windows Long Path support` geçen pip hatası çıkarsa:
  - SesVer klasörünü kısa bir yola taşı (örneğin `C:\SesVer`).
  - `.venv` klasörünü sil ve başlatıcıyı tekrar çalıştır.
  - Alternatif: Python kurulum dosyasının son ekranındaki **"Disable path length limit"** seçeneği. Yönetici izni ister; önce açıkla.
- `Access is denied` / `Erişim engellendi` hatası çıkarsa:
  - Klasör `C:\Program Files` gibi korumalı bir yerde ya da OneDrive ile eşitlenen bir klasörde olabilir. Klasörü `C:\SesVer` ya da kullanıcı klasörüne taşı.
  - Başlatıcıyı yönetici olarak çalıştırmak gerekmez.
- Siyah pencere açılıp hemen kapanıyor ya da `... was unexpected at this time.` yazıyor: Eski bir başlatıcı sürümü kullanılıyor. ZIP'i yeniden indir ve yeni klasördeki `WINDOWS_BASLAT.bat` dosyasını çalıştır.
- PowerShell'de `is not recognized` / `CommandNotFoundException` hatası: Dosya adının başına `.\` ekle: `.\WINDOWS_BASLAT.bat`. Ya da dosyaya Dosya Gezgini'nden çift tıkla.

**Mac: başlatıcı açılmıyor / `Permission denied`**

- Önce M4'teki Gatekeeper adımlarını dene.
- Sürerse Terminal'i aç, `cd ` yaz (sonunda bir boşluk bırak), SesVer klasörünü Terminal penceresine sürükle ve Enter'a bas. Sonra şunu çalıştır:

  ```bash
  chmod +x MACOS_BASLAT.command && ./MACOS_BASLAT.command
  ```

**GitHub'da depo görünmüyor / 404 / ZIP inmiyor**

- Depo özel. Kullanıcı GitHub'a giriş yapmalı. Giriş yaptığı halde depo görünmüyorsa depo sahibinden erişim izni istemeli. Şifresini sohbete yazmamasını söyle.

**Uygulama içi mesajlar**

- `Referans ses okunamadı. 1–30 saniyelik geçerli bir WAV yükleyin.`: Ses Klonlama'da 1–30 saniyelik, tercihen 3–15 saniyelik temiz bir WAV kullan.
- `Kayıt ... sn; 8–20 sn arası olmalı.`: Ses Oluştur → Dosya yükle bölümünde kayıt 8–20 saniye olmalı. Başlangıç ve Bitiş kaydırıcılarıyla aralık seç.
- `İlk sürümde en fazla 500 karakter kullanın; uzun metni bölün.`: Metni parçalara böl.
- `Kaydetmek için izin kutucuğunu işaretleyin.`: Bkz. 8. bölüm, ses klonlama uyarısı.
- İlk üretim "takıldı" gibi görünüyor: Model indiriliyor ya da yükleniyor. Bekle ve Üret'e tekrar basma.

**Çözülemezse:** Kullanıcıyı https://github.com/hamarat52/sesver/issues adresine yönlendir. Issue'ya şunları yazmasını öner: işletim sistemi, Python sürümü, RAM, hangi adımda kaldığı ve hata mesajı. Kişisel bilgilerini ve ses kayıtlarını paylaşmamasını hatırlat.

---

## 8. Kullanım özeti

Kurulum bitince kullanıcıya kısaca şunları anlat:

- **Ses Kütüphanesi → Hazır sesler:** Yaşlı Masalcı, Belgesel Anlatıcı ve Heyecanlı Sunucu repoyla gelir. Bunlar tarifle tasarlanmış sentetik seslerdir, gerçek kişi değildir.
  - Bir kartı **Seç**, metni yaz ve **Üret**'e bas.
  - **▶ Örnek** düğmesi 3 saniyelik örneği çalar.
  - **Kalite** seçenekleri: Hızlı / Dengeli / En İyi. **Duygu / ton** isteğe bağlıdır.
  - **🎲 Rastgele ses** kartı referanssız üretir; her seferinde farklı biri konuşabilir.
- **Ses Oluştur → Seçimlerle tarif et:**
  - Yaş, cinsiyet, ton, doku, hız gibi seçimleri yap. Bu seçimlerden İngilizce bir tarif kurulur; **Gelişmiş** alanında görünür.
  - Örnek cümleyi ve süresini (10–20 sn) seç, sonra **Sesleri Dene**'ye bas.
  - **4 aday** sırayla üretilir. Dinle, beğendiğinde **Bunu seç**'e bas.
  - **Ses adı** ver ve **Kaydet**'e bas. Ses **Seslerim**'e eklenir.
  - **4 aday daha** ile yeni adaylar üretilebilir.
- **Seslerim:** Kaydettiğin sesler Ses Kütüphanesi'nde **Seslerim** başlığı altında durur. Hazır bir sesi **Kopyala** ile buraya alıp düzenleyebilirsin. Seslerim yalnız bu bilgisayarda (`voices/seslerim/`) durur, GitHub'a gitmez.
- **Ses Klonlama:**
  - Referans ses yükle: tek kişi, müziksiz, 3–15 sn önerilir.
  - İstersen referansın metnini yaz ya da **Otomatik yazıya dök**'e bas.
  - Yeni metni yaz ve **Klonla ve Üret**'e bas.
  - Kaydı kalıcı bir sese çevirmek için **Ses Oluştur → Dosya yükle** kullanılır. Bu bölümde **"Bu ses bana ait ya da sahibinden açık izin aldım."** kutusu işaretlenmeden kaydedilemez.
  - **Otomatik yazıya dök** ilk kullanımda küçük bir Whisper modelini indirir.

> ⚠️ **Ses klonlama uyarısı — kullanıcıya açıkça söyle:**
> - **Yalnız kendi sesini ya da sahibinden açık izin aldığın sesleri klonla.**
> - Başkasının sesini izinsiz kullanmak, kimliğe bürünmek, dolandırıcılık ya da yanıltıcı içerik üretmek yasaktır. Sorumluluk tamamen kullanıcıdadır.
> - Üretilen sesi paylaşırken **"AI ile üretildi"** diye etiketle. Uygulama otomatik filigran eklemez.
> - SesVer'in kodu ticari olmayan kullanım içindir (PolyForm Noncommercial 1.0.0).

---

## 9. Kaldırma

1. SesVer'i kapat: pencerede **Ctrl+C** bas ya da pencereyi kapat.
2. **Kişisel sesleri yedekle** (istersen): `voices/seslerim/` ve `outputs/` klasörleri SesVer klasörünün içindedir. Silinince geri gelmez.
3. **SesVer klasörünü sil:** `sesver-main` (ZIP) ya da `sesver` (Git). Sanal ortam `.venv`, çıktılar `outputs` ve kişisel sesler `voices/seslerim` de bu klasörün içinde olduğu için onlar da silinir.
4. **Model önbelleğini sil** (yer açmanın asıl kısmı, yaklaşık 5 GB). Hugging Face önbellek klasörü:
   - Mac/Linux: `~/.cache/huggingface/hub/`
   - Windows: `C:\Users\<kullanıcı adı>\.cache\huggingface\hub\`

   Bu klasörde **yalnız** şu iki alt klasörü sil:
   - `models--openbmb--VoxCPM2` (ses modeli)
   - `models--Systran--faster-whisper-small` (yalnız "Otomatik yazıya dök" kullanıldıysa vardır)

   Tüm `huggingface` klasörünü silme; başka yapay zekâ uygulamaları da kullanıyor olabilir. Kullanıcı `HF_HOME` değişkenini kendisi ayarladıysa önbellek o klasördedir.
5. İsteğe bağlı:
   - **pip önbelleğini sil:** Mac'te `~/Library/Caches/pip`, Windows'ta `%LOCALAPPDATA%\pip\Cache`, Linux'ta `~/.cache/pip`. Başka Python projeleri de kullanır; silinmesi zararsızdır, yalnız sonraki kurulumlar yeniden indirir.
   - **Gradio geçici dosyalarını sil:** Sistemin geçici klasöründeki `gradio` klasörü. Yüklenen seslerin geçici kopyaları burada kalabilir.
6. Python'u başka bir şey için kullanmıyorsa kaldırabilir. Windows'ta **Ayarlar → Uygulamalar**. Mac'te python.org kurulumu `/Applications/Python 3.11` klasörünü ekler; kaldırmak yönetici izni ister, önce açıkla.
