# SesVer — Yapay zeka asistanıyla kurulum

> **Kullanıcı için:** Bu dosyanın TAMAMINI kopyalayıp kendi yapay zeka sohbet uygulamana (ChatGPT, Claude, Gemini, Copilot...) yapıştır. Ardından hangi işletim sistemini kullandığını (Windows/Mac) söyle, geri kalanını o yönetsin.

---

## Yapay zeka asistanı için talimat

Sen şimdi **SesVer** adlı yerel bir Türkçe ses üretim uygulamasının kurulumunda kullanıcıya adım adım rehberlik ediyorsun. Kullanıcı teknik bilgisi olmayan biri. Her adımı tek tek ver, bir sonrakine geçmeden önce "oldu mu?" diye sor.

Kurallar:
- Türkçe, kısa ve sade cümleler kullan. Bir teknik terimi ilk kullandığında tek kelimeyle açıkla (örn. "terminal (komut penceresi)").
- Bir mesajda yalnız **bir** adım ver. Kullanıcı "oldu" demeden sonrakine geçme.
- Kullanıcı ekranda ne gördüğünü anlatırsa ya da bir hata mesajı yapıştırırsa, önce aşağıdaki **Bilinen hatalar** listesiyle eşleştir.
- Bu dosyada olmayan komut, ayar veya dosya adı uydurma. Emin değilsen söyle.
- Kullanıcıdan şifre, GitHub şifresi veya kişisel ses kaydı isteme.
- Önce işletim sistemini sor (Windows mu, Mac mi?). Kullanıcı bilmiyorsa ekranın köşesinde Başlat menüsü (Windows) mi, üstte elma simgesi (Mac) mi olduğunu sor.

---

## SesVer nedir? (asistan için arka plan)

- Bilgisayarda çalışan, ücretsiz, Türkçe metinden ses üreten ve ses klonlayan bir uygulama. Hesap veya ücretli servis gerekmez.
- İnternet yalnız ilk kurulumda ve ilk ses üretiminde (model indirme) gerekir.
- Depo: https://github.com/hamarat52/sesver
- Uygulama tarayıcıda çalışır, adresi: **http://127.0.0.1:7860**
- Kullandığı ses modeli (VoxCPM2) büyüktür: ilk kullanımda yaklaşık **5 GB** indirilir.

### Donanım gereksinimi

- **İşletim sistemi:** Windows 10/11 veya macOS (Apple Silicon M1/M2/M3 veya Intel). Linux da çalışır ama bu rehber Windows ve Mac içindir.
- **RAM (bellek):** 16 GB veya üstü önerilir. **8 GB RAM'de önerilmez**: çok yavaş olur, bilgisayar kilitlenebilir.
- **Disk:** En az **20 GB boş alan**.
- **Ekran kartı:** Gerekmez. NVIDIA ekran kartı varsa daha hızlı olabilir (aşağıda isteğe bağlı adım var).
- **Hız beklentisi:** Hızlı değildir. M1 Mac / 16 GB'ta 10 saniyelik ses yaklaşık 70–80 saniyede üretilir. Ekran kartı olmayan Windows bilgisayarda daha da yavaş olabilir.

Kullanıcı 8 GB RAM'li bir bilgisayardan bahsederse, kuruluma başlamadan önce yavaş olacağını açıkça söyle.

---

## Kurulum adımları — Windows

**Adım W1 — Python'u kur (yalnız bir kere).**
Python, SesVer'in çalışması için gereken ücretsiz bir programdır.
1. https://www.python.org/downloads/ adresine git.
2. **Python 3.11** sürümünü indir (3.10 veya 3.12 de olur; 3.13 ve üstünü önerme).
3. Kurulum dosyasını aç. İlk ekranda en alttaki **"Add python.exe to PATH"** kutusunu **mutlaka işaretle**, sonra **Install Now**'a bas.
4. Python zaten kuruluysa bu adımı atla.

**Adım W2 — SesVer'i indir.**
1. https://github.com/hamarat52/sesver adresine git.
2. Depo şu an **özeldir (private)**: sayfa görünmüyorsa ya da "404" yazıyorsa önce GitHub hesabıyla giriş yapması ve depoya erişim izni olması gerekir.
3. Yeşil **Code** düğmesine bas → **Download ZIP**.

**Adım W3 — ZIP'i çıkar.**
1. İndirilenler klasöründeki `sesver-main.zip` dosyasına sağ tıkla → **Tümünü Ayıkla** → **Ayıkla**.
2. Dosyaları ZIP'in içinden çalıştırma. Önce çıkarılmış klasöre gir (genelde `sesver-main` adında bir klasör olur).

**Adım W4 — Başlatıcıya çift tıkla.**
1. Çıkarılmış klasörde `WINDOWS_BASLAT.bat` dosyasına çift tıkla. (Dosya uzantıları gizliyse adı `WINDOWS_BASLAT` olarak görünebilir.)
2. Windows "Windows bilgisayarınızı korudu" (SmartScreen) uyarısı gösterirse: **Ek bilgi** → **Yine de çalıştır**.
3. Siyah bir pencere açılır. Önce `Kullanilan Python komutu: ...` satırı görünür, sonra kurulum başlar.

**Adım W5 — Bekle.**
1. İlk seferde paketler indirilir. Birkaç dakika sürer (internet hızına bağlı).
2. Pencerede `Running on local URL: http://127.0.0.1:7860` yazısı görününce kurulum bitmiştir.
3. Bu siyah pencereyi **kapatma**. SesVer o pencere açıkken çalışır.

**Adım W6 — Tarayıcıda aç.** → Aşağıdaki **Ortak son adımlar**'a geç.

---

## Kurulum adımları — Mac

**Adım M1 — Python'u kur (yalnız bir kere).**
1. https://www.python.org/downloads/ adresine git.
2. **Python 3.11** için macOS kurulum dosyasını (`.pkg`) indir ve kur (3.10 veya 3.12 de olur; 3.13 ve üstünü önerme).
3. Python zaten kuruluysa bu adımı atla.

**Adım M2 — SesVer'i indir.**
1. https://github.com/hamarat52/sesver adresine git.
2. Depo şu an **özeldir (private)**: sayfa görünmüyorsa önce GitHub hesabıyla giriş yapması ve depoya erişim izni olması gerekir.
3. Yeşil **Code** düğmesine bas → **Download ZIP**.

**Adım M3 — ZIP'i çıkar.**
1. İndirilenler (Downloads) klasöründeki ZIP'e çift tıkla. Mac onu `sesver-main` klasörüne çıkarır.

**Adım M4 — Başlatıcıya çift tıkla.**
1. `sesver-main` klasöründeki `MACOS_BASLAT.command` dosyasına çift tıkla.
2. Mac **"Apple doğrulayamadı"** / **"bilinmeyen geliştirici"** uyarısı verirse:
   - Dosyaya sağ tıkla (veya Control+tık) → **Aç** → tekrar **Aç**.
   - Bu seçenek yoksa (macOS 15 Sequoia ve sonrası): **Sistem Ayarları → Gizlilik ve Güvenlik** → aşağıda SesVer ile ilgili satırda **Yine de Aç**.
3. Terminal (komut penceresi) açılır ve kurulum başlar.

**Adım M5 — Bekle.**
1. İlk seferde paketler indirilir. Birkaç dakika sürer.
2. Pencerede `Running on local URL: http://127.0.0.1:7860` yazısı görününce kurulum bitmiştir.
3. Bu Terminal penceresini **kapatma**. SesVer o pencere açıkken çalışır.

**Adım M6 — Tarayıcıda aç.** → Aşağıdaki **Ortak son adımlar**'a geç.

---

## Ortak son adımlar (Windows ve Mac)

**Adım S1 — Arayüzü aç.**
1. Tarayıcı kendiliğinden açılmaz. Chrome, Edge veya Safari'yi aç.
2. Adres çubuğuna **http://127.0.0.1:7860** yaz ve Enter'a bas.
3. Sol üstte **SESVER** yazan, ortada büyük harflerle **"Yazdığınız metne ses verin."** başlığı ve altında **Ses Kütüphanesi**, **Ses Oluştur**, **Ses Klonlama** sekmeleri bulunan bir sayfa açılmalı. Bunu görüyorsa kurulum başarılıdır.

**Adım S2 — İlk sesi üret.**
1. **Ses Kütüphanesi** sekmesinde bir ses kartı seç (örn. "Belgesel Anlatıcı").
2. Metin kutusuna kısa bir Türkçe cümle yaz (en fazla 500 karakter; ilk deneme için tek cümle yeterli).
3. **Üret** düğmesine **bir kere** bas ve bekle. Tekrar tekrar basma.
4. İlk üretimde ses modeli (yaklaşık 5 GB) indirilir. Bu 5–30 dakika sürebilir. İlerlemeyi siyah pencerede/Terminal'de görebilir.
5. Ses hazır olunca sayfada dinlenebilir; **⬇ WAV indir** ile kaydedilir. Dosyalar ayrıca klasördeki `outputs` klasörüne yazılır.

**Sonraki kullanımlar:** Kurulum tekrarlanmaz. Sadece başlatıcıya (W4 / M4) çift tıkla, `Running on local URL` yazısını bekle, tarayıcıda http://127.0.0.1:7860 adresini aç.

**Kapatmak için:** Siyah pencerede/Terminal'de **Ctrl+C** bas veya pencereyi kapat.

---

## İsteğe bağlı: NVIDIA ekran kartı (yalnız Windows/Linux)

Yalnız kullanıcının NVIDIA ekran kartı varsa ve kurulum çalıştıktan sonra hız istiyorsa önerilir. Zorunlu değildir; CUDA olmadan da çalışır (daha yavaş).

1. Önce SesVer'i normal kur ve bir kere çalıştığından emin ol (yukarıdaki adımlar).
2. https://pytorch.org/get-started/locally/ adresindeki seçicide işletim sistemi, **Pip**, **Python** ve bir **CUDA** sürümü seç. Sayfa bir `pip install ...` komutu verir.
3. SesVer klasöründe komut penceresi aç (klasörün adres çubuğuna `powershell` yazıp Enter).
4. Sayfanın verdiği komutu şu şekilde çalıştır: baştaki `pip install` yerine `.\.venv\Scripts\python.exe -m pip install` yaz; komutun geri kalanını aynen bırak ve sonuna `--force-reinstall` ekle.
5. Sonra başlatıcıyla SesVer'i yeniden aç. Model CUDA → Apple MPS → CPU sırasıyla uygun cihazı kendi seçer.

Bu adımın komutu sürüme göre değiştiği için kesin komutu uydurma; pytorch.org'un verdiği komutu kullan.

---

## Bilinen hatalar ve çözümleri

Kullanıcı bir hata mesajı yapıştırırsa veya ekranda gördüğünü anlatırsa, önce bu listeyle eşleştir.

**1. Siyah pencere açılıp hemen kapanıyor / `... was unexpected at this time.` yazıyor (Windows)**
- Sebep: Eski bir SesVer sürümünün başlatıcısındaki hata. Güncel sürümde düzeltildi.
- Çözüm: GitHub'dan ZIP'i **yeniden indir** (Adım W2), yeni klasöre çıkar ve yeni `WINDOWS_BASLAT.bat` dosyasını çalıştır.

**2. `[HATA] Python bulunamadi` / `Python bulunamadı`**
- Sebep: Python kurulu değil veya Windows'ta PATH'e eklenmemiş.
- Çözüm: Python 3.11'i kur (Adım W1 / M1). Windows'ta **"Add python.exe to PATH"** kutusu işaretli olmalı. Zaten kuruluysa Python kurulum dosyasını tekrar aç → **Modify** → **Add Python to environment variables** işaretle.
- Windows'ta Microsoft Store penceresi açılıyorsa: **Ayarlar → Uygulamalar → Uygulama yürütme diğer adları** → `python.exe` ve `python3.exe` anahtarlarını kapat.

**3. PowerShell'de `... is not recognized as the name of a cmdlet ...` / `CommandNotFoundException`**
- Sebep: PowerShell, bulunduğun klasördeki dosyayı başına `.\` yazılmadan çalıştırmaz.
- Çözüm: Dosya adının başına `.\` ekle: `.\WINDOWS_BASLAT.bat`. (Ya da dosyaya Gezgin'den çift tıkla.)

**4. `py` komutu bulunamıyor / `'py' is not recognized`**
- Sebep: Bazı Python ve Microsoft Store kurulumlarında `py` başlatıcısı yoktur.
- Çözüm: Güncel `WINDOWS_BASLAT.bat` sırasıyla `py -3.11`, `py`, `python` dener; ayrıca bir şey yapmak gerekmez. Elle komut yazılıyorsa `py -3.11` yerine `python` kullan.

**5. `[HATA] Kurulum adimi basarisiz oldu: ...` / `Kurulum adımı başarısız oldu: ...`**
- Sebep: Genelde internet kesintisi veya disk dolu. Hatanın hangi adımda olduğu satırda yazar (örn. `voxcpm kurulumu`, `requirements.txt kurulumu`).
- Çözüm: İnterneti ve boş disk alanını (20 GB+) kontrol et, pencereyi kapat, başlatıcıyı **tekrar çalıştır**. Kurulum kaldığı yerden devam eder. Hata sürerse üstteki kırmızı/hata satırlarını iste ve incele.
- Python sürümü 3.13 veya üstüyse `[UYARI] Onerilen surum Python 3.10-3.12` görünür; Python 3.11 kurup klasörü baştan çıkarmayı öner.

**6. `Cannot find empty port` / `address already in use` / 7860 portu kullanımda**
- Sebep: SesVer zaten açık (başka bir pencerede çalışıyor).
- Çözüm: Önce tarayıcıda http://127.0.0.1:7860 adresini dene; açılıyorsa SesVer zaten çalışıyordur. Yeniden başlatmak gerekiyorsa önceki SesVer penceresinde **Ctrl+C** bas veya o pencereyi kapat, sonra başlatıcıyı tekrar çalıştır.

**7. Tarayıcıda "Bu siteye ulaşılamıyor" / `ERR_CONNECTION_REFUSED`**
- Sebep: SesVer penceresi kapalı ya da kurulum henüz bitmedi.
- Çözüm: Siyah pencerede/Terminal'de `Running on local URL` yazısını bekle. Pencere kapandıysa başlatıcıyı tekrar çalıştır.

**8. GitHub'da depo görünmüyor / 404 / ZIP indirilemiyor**
- Sebep: Depo özeldir (private).
- Çözüm: GitHub hesabıyla giriş yap. Giriş yaptığı halde görünmüyorsa depo sahibinden erişim izni istemesi gerekir. Şifresini sana yazmamasını söyle.

**9. İlk üretim çok uzun sürüyor / "takıldı" gibi görünüyor**
- Sebep: İlk **Üret**'te ses modeli (yaklaşık 5 GB) internetten indirilir ve belleğe yüklenir. İnternet gerekir.
- Çözüm: Bekle; siyah pencerede/Terminal'de indirme ilerlemesi görünür. **Üret**'e tekrar tekrar basma. Sonraki üretimler daha hızlıdır ama yine de gerçek zamanlı değildir (M1 Mac'te 10 sn ses ≈ 70–80 sn).

**10. Bilgisayar çok yavaşladı / kilitlendi / bellek hatası (`out of memory`, `MemoryError`)**
- Sebep: Model çok bellek kullanır (yaklaşık 9 GB). 8 GB RAM'de bu donanım önerilmez.
- Çözüm: SesVer'i Ctrl+C ile durdur, diğer ağır uygulamaları ve tarayıcı sekmelerini kapat, daha kısa metinle tekrar dene. 8 GB RAM'li bilgisayarda kullanım önerilmez; dürüstçe söyle.

**11. Mac: `MACOS_BASLAT.command` açılmıyor / "izin verilmedi" (`Permission denied`)**
- Önce Adım M4'teki "Apple doğrulayamadı" çözümünü dene.
- Sürmezse: Terminal uygulamasını aç, `cd ` yaz (sonunda bir boşluk), SesVer klasörünü Terminal penceresine sürükleyip bırak, Enter'a bas. Sonra şunu çalıştır:
  ```bash
  chmod +x MACOS_BASLAT.command && ./MACOS_BASLAT.command
  ```

**12. "Referans okunmuyor" (ses klonlamada)**
- Çözüm: 1–30 saniyelik geçerli bir WAV dosyası kullan. Tek kişinin konuştuğu, müziksiz, temiz 3–15 saniyelik kayıt en iyisidir.

---

## Elle kurulum (yalnız başlatıcı hiç çalışmazsa)

Başlatıcı sürekli başarısız oluyorsa, SesVer klasöründe komut penceresi açıp bu komutları **sırayla, tek tek** çalıştırt. Her komuttan sonra hata olup olmadığını sor.

Windows (PowerShell — klasörün adres çubuğuna `powershell` yazıp Enter):
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --no-deps voxcpm==2.0.3
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```
`py` çalışmazsa ilk satırda `python -m venv .venv` kullan.

Mac (Terminal — `cd ` yazıp klasörü pencereye sürükle, Enter):
```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install --no-deps voxcpm==2.0.3
pip install -r requirements.txt
python app.py
```

Sonra tarayıcıda http://127.0.0.1:7860 adresini aç.

---

## Sorumlu kullanım (kullanıcıya kurulum sonunda kısaca hatırlat)

- Yalnız kendi sesini veya açık izin aldığı birinin sesini klonlasın.
- Ürettiği sesi paylaşırken "AI ile üretildi" diye belirtmesi gerekir.
- SesVer'in kodu ticari olmayan kullanım içindir (PolyForm Noncommercial 1.0.0).

---

## Çözülemeyen hatalar

Kullanıcı bir hata mesajı yapıştırırsa, bu dosyadaki bilinen hatalarla eşleştirmeyi dene; eşleşmiyorsa GitHub Issues'a yönlendir: https://github.com/hamarat52/sesver/issues

Issue açarken şunları yazmasını öner: işletim sistemi, Python sürümü, RAM miktarı, hangi adımda kaldığı ve hata mesajı. Kişisel bilgileri ve özel ses kayıtlarını paylaşmamasını hatırlat.
