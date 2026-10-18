# FAZ 2 — EMA Lightning: gerçek kurulum ve ölçüm raporu (WebDev)

Tarih: 2026-10-18 · Branch: `feature/elevenlabs-backend` · Makine: macOS, CPU (torch 4 iş parçacığı)
ARAYÜZ YOK: app.py'ye, arayüze ve main'e dokunulmadı. VoxCPM2 ve SesVer uygulaması başlatılmadı.

> **Kulakla dinlenmedi.** Bütün kalite yargıları otomatik ölçümlere dayanıyor: Whisper geri okuma, ebur128 ve ECAPA.
> Doğallık, tonlama ve "robotiklik" ölçülmedi. Bunlar için Yusuf'un mp3'leri dinlemesi gerekiyor.

## 1. Kurulum (M1-1)

Kurulum, adaptördeki `ema_install()` ile yapıldı (`_olcum/m1_kurulum.py`, ham kayıt `m1_kurulum.json`).

| Ölçüm | Değer |
|---|---|
| Toplam kurulum süresi (paket + ağırlık + doğrulama) | **5,12 sn** |
| Paket aşaması (`--only-binary`, ema-lightning 1.0.3 + normalizer-tr 0.4.0) | 1,17 sn · 1.298.611 B (~1,3 MB) |
| Ağırlık indirme (config.json + ema.pt + decoder.pt) | ~3,6 sn · **34.389.489 B (34,4 MB)** |
| Kurulum öncesi `ema_status().total_download_bytes` | 35.688.100 B ("~35,7 MB") |
| SHA-256 doğrulama (`ema_status(verify=True)`) | 0,02 sn → `verified: true` |
| İkinci `ema_install()` çağrısı (idempotent, ağa çıkmaz) | 0,04 sn |
| Revizyon | `7a6ba1ad216bb2f1da9863f80ac8770a6a807632` (Apache-2.0) |

`ema_status()` kurulumdan sonra:
`package_installed: true`, `package_version: 1.0.3`, `normalizer_version: 0.4.0`, `dependencies_ok: true`,
`weights_present: true`, `weights_bytes: 34389489`, `download_bytes: 0`, `verified: true` (verify ile), `ready: true`, `weights_label: "34,4 MB"`.

İlerleme olayları sırayla geliyor: kontrol → paket → indirme (dosya başına ~1 MB'lık adımlar) → dogrulama → tamam ("EMA hazır (34,4 MB).").

> Ölçüm betiği hatası (düzeltildi): `m1_kurulum.json` içindeki `weights_downloaded_bytes = 56676051` yanlış.
> `done_bytes` dosyalar boyunca birikimli ilerliyor; betik ise dosya başına maksimumları toplamış.
> Gerçek değer son indirme olayındaki `done_bytes = 34389489`. Formül betikte düzeltildi. Kurulum tekrar edilmedi.

## 2. Soğuk başlatma (M1-2)

Ayrı süreçte, `/usr/bin/time -l` ile ölçüldü (`m2_soguk.json`).

| Adım | Süre | RSS |
|---|---|---|
| Süreç başı | – | 14 MB |
| `import torch` | 1,0 sn | 190 MB |
| Model yükleme (SHA doğrulama dahil, `default_loader`) | **0,8 sn** | 265 MB |
| İlk kısa üretim | 0,08 sn | **291 MB (tepe, ru_maxrss)** |
| **Soğuk başlangıçtan ilk sese** | **1,91 sn** | – |

## 3. Üretim, hız ve geri okuma (M1-3/4)

Seed 1, hız 1,0, 48 kHz (`m3_uretim.json`). RTF burada ses süresi / üretim süresi, yani büyük değer daha hızlı demek.

| Metin | Karakter | Ses | Üretim | RTF (×gerçek zaman) | WER | CER | I (LUFS) | LRA | TP (dBFS) |
|---|---|---|---|---|---|---|---|---|---|
| a) Merhaba… | 76 | 4,00 sn | 0,347 sn | **11,5×** | 0,0 | 0,0 | −24,9 | 1,2 | −7,4 |
| b) Sayılar/kısaltma | 95 | 8,76 sn | 1,113 sn | **7,9×** | 0,0 | 0,0 | −25,1 | 2,1 | −7,2 |
| c) Belgesel (Titanik 1–14) | 1112 | **65,79 sn** | 7,486 sn | **8,8×** | 0,084 (ham) | 0,042 | −24,4 | 3,0 | −3,5 |

Geri okuma yöntemi:
- faster-whisper medium, int8, CPU, `language=tr`, beam 5. Mevcut voicestudio-test venv'inde koştu; SesVer `.venv`'ine ölçüm paketi kurulmadı.
- Referans ve Whisper çıktısı aynı söyleyiş biçimine çevrildi (normalizer-tr), sonra karşılaştırıldı. Böylece "29 Mayıs" ile "yirmi dokuz mayıs" eşit sayılıyor.

**b) sayılar:** Whisper çıktısı girdiyle karakter karakter aynı:
"1453'te İstanbul'un fethi, 29 Mayıs günü sabah saat 6'da başladı. TBMM 23 Nisan 1920'de açıldı."
1453'te ✓ · 29 Mayıs ✓ · saat 6'da ✓ · TBMM ✓ · 23 Nisan ✓ · 1920'de ✓. Ekler doğru. Sayılar doğru okunmuş. TBMM'nin nasıl seslendirildiği ayrıca doğrulanmadı; yalnız Whisper'ın onu "TBMM" olarak geri yazdığı biliniyor.

**c) ham WER 0,084 (14 hata / 167 kelime), dökümü:**
- Ad yazımı, 6 adet. Fonetik yazılan metni Whisper İngilizce yazıyor: tamıs endruz→Thomas Andrews, karpeyşa→Carpeyse/Karpeyş'e, titanik→Titanic, kaliforniyın→Kaliforniya'ın.
- Saat biçimi, 6 adet. Bunlar Whisper'ın yazım tarzından kaynaklanan değerlendirme yapaylığı, okuma hatası değil:
  - "00.15/00.25" → fazladan "nokta"
  - "218/220/410" → "iki yüz on sekiz" (metinde "iki on sekiz")
  - "0045" → "kırk" yerine "dört"
- Olası gerçek telaffuz/ASR hatası, 1 adet: "işaret fişeği" → "fişeye". Kulakla doğrulanmalı.
- Benim yorumum: içerik düzeyinde gerçek hata ≤1/167 (~%0,6). Bu sınıflandırma otomatik değil, elle yapıldı.

## 4. Seed belirlenimciliği (M1-5)

| Karşılaştırma | Sonuç |
|---|---|
| seed 1, aynı süreçte 2 kez (+ ilk a üretimi) | SHA-256 aynı → **örnek bazında birebir aynı** |
| seed 1, ayrı süreçte (`--tekrar`, yeni Python süreci) | SHA-256 aynı (`9e6e016b…`) → **süreçler arası da aynı** |
| seed 2 ve 3 | SHA farklı; süre üçünde de 4,00 sn (seed zamanlamayı değil ses dokusunu oynatıyor) |

ECAPA kosinüs benzerliği (speechbrain spkrec-ecapa-voxceleb, crow-voices yerel önbelleği):

| Çift | Benzerlik |
|---|---|
| seed1 ~ seed1 tekrar | 1,000 |
| seed1 ~ seed2 | 0,908 |
| seed1 ~ seed3 | 0,906 |
| seed2 ~ seed3 | 0,914 |
| EMA seed1 ~ VoxCPM2 l01_c11 (çapraz kontrol) | 0,097 |

Yorum: Seed'ler aynı konuşmacının küçük varyasyonları (≥0,90). Farklı bir sese karşı değer 0,07–0,10. Yani "tek ses" iddiası ölçümle tutarlı, seed sesi değiştirmiyor.

## 5. Hız parametresi (M1-6)

c) metninin ilk 2 cümlesi: "Titanik'in batması iki saat kırk dakika sürdü. İşte o gece, saat saat."

| speed | Ses | 1,0'a oran | Beklenen | Üretim | WER |
|---|---|---|---|---|---|
| 0,9 | 4,96 sn | 1,138× uzun | 1,111× | 0,782 sn | 0,083 (Titanic) |
| 1,0 | 4,36 sn | 1,000 | 1,000 | 0,784 sn | 0,083 (Titanic) |
| 1,15 | 3,80 sn | 1,147× kısa | 1,150× | 0,335 sn | 0,0 |

- Hız parametresi beklendiği gibi çalışıyor; sapma ≤%2,5.
- Üç hızda da metin eksiksiz okunmuş. Tek fark Whisper'ın "Titanik" kelimesini "Titanic" yazması.

## 6. SRT (M1-7) — `ema_c.srt`

SRT, motorun kelime zamanlarından adaptörün `write_srt` yoluyla üretildi. Whisper kelime zamanlarıyla hizası şöyle:

| Ölçüm | Değer |
|---|---|
| Kip (cue) sayısı | 42; 167 kelimenin tamamı kiplerde |
| Motor ↔ Whisper eşleşen kelime | 156/167 (%93,4; eşleşmeyenler ad yazımı ve saat biçimi) |
| Kelime başlangıç sapması | medyan **0,04 sn** · p95 0,19 sn · maks 0,57 sn |
| Kip başlangıç sapması | medyan **0,07 sn** · p95 0,23 sn · maks 0,57 sn |
| Kip başlangıcı ±200 ms içinde | **%92,3** |
| 1 sn'den kısa kip | 9/42 (en kısa 0,56 sn, "sürdü.") |

- 0,57 sn'lik en büyük sapma "sıfır sıfır kırk beş" kipinde. Whisper bu bölümü tek kelime ("0045") olarak veriyor ve ölçüm betiği o kelimenin süresini jetonlara eşit bölüyor; sapma bundan geliyor, bir yapaylık.
- Genel değerlendirme: hiza altyazı için yeterli.

## 7. VoxCPM2 referansı (M1-8) — üretilmedi, meta.jsonl'den

Kaynak: `titanik-saat-saat/audio/cand/meta.jsonl` (64 aday, 14 satır), kalite verisi aynı klasördeki `asr.jsonl`'den.

| Ölçüm | VoxCPM2 (meta.jsonl) | EMA Lightning |
|---|---|---|
| Aday başına `gen_s` | ort. 41,6 sn · medyan 46,4 · min 16,9 · maks 82,1 | a) 0,35 sn · c) 7,49 sn |
| Ortalama ses süresi | 5,58 sn/aday | – |
| 1 sn ses için üretim | **7,46 sn** (RTF 0,134×) | **0,114 sn** (c, RTF 8,8×) |
| Eşdeğer satır: l01 "Titanik'in batması…" (4,96 sn) | 35,1–39,5 sn | 0,78 sn (hiz_1.0, 4,36 sn) |
| Geri okuma | ort. WER 0,0385; adayların %78'i WER 0 | a/b WER 0; c ham 0,084 (içerik ≤%0,6, yorum) |

- Hız farkı: 1 sn ses başına yaklaşık **65 kat** EMA lehine.
- Uyarı: VoxCPM2 ses klonlama (continuation) modunda ve başka yük koşullarında çalışmıştı. WER boru hatları da aynı değil.
- Bu yüzden yalnız büyüklük mertebesi karşılaştırılabilir. Ses benzerliği, tını ve doğallık karşılaştırması yapılmadı.

## 8. Ortam bütünlüğü

- `pip freeze --all` farkı (öncesi→sonrası), yalnız iki ekleme var:
  - `+ ema-lightning==1.0.3`
  - `+ normalizer-tr==0.4.0`
- Kaldırılan ya da yükseltilen paket yok.
- torch 2.14.1, numpy 2.4.6 ve gradio 6.30.0 değişmedi. Ölçümlerden sonra da `pip freeze --all` "sonrası" dosyasıyla aynı.
- `~/.hermes/tts/ema-venv`'e ve ana repo klasöründeki diğer görev dosyalarına dokunulmadı.
- Ağırlıklar `models/ema-lightning/` altında ve `.gitignore`'daki `models/` ile `*.pt` kurallarıyla dışarıda.
- `.gitignore` `*.wav` ve `*.mp3` dosyalarını da dışlıyor; dinleme dosyaları yerelde duruyor, commit'e girmedi.
- unittest: `python -m unittest discover -s tests` → **168 test OK, 0 skip.**

## 9. Sorunlar

1. **SRT metni modelin alfabesinde.** Kipler küçük harf ve sayılar yazıyla: "titanik'in batması iki saat kırk dakika". Kullanıcının yazdığı metin (büyük harf, "23.40", "TBMM") geri gelmiyor. Belgesel altyazısı için çoğu zaman istenmez. Faz 3 öncesi karar gerekiyor: söyleyiş kelimeleri orijinal metne geri eşlenmeli mi?
2. **Kısa kipler:** 9/42 kip 1 sn'nin altında. Tek kelimelik kipler var ("sürdü.", "çeviriyor."). Okunabilirlik için en az süre veya birleştirme kuralı önerilir.
3. **Loudness düşük:** I ≈ −24,4…−25,6 LUFS, TP −3…−8 dBFS. Tipik yayın hedefi −16/−14 LUFS. Çıkışta normalizasyon gerekiyor. SesVer'in mevcut efekt/loudness zincirinin EMA çıktısına uygulanıp uygulanmadığı bu fazda test edilmedi.
4. **config.json SHA'sız:** Manifestte `sha256: null`; yalnız boyut (342 B) denetleniyor. İki .pt dosyası SHA-256 ile doğrulanıyor. Küçük risk.
5. **Isınma:** Yeni süreçte ilk üretim yavaş, aynı cümle 1,05 sn sürdü (sıcakken 0,35 sn). Tek tük 0,78 sn'lik dalgalanma da görüldü. Kullanıcı açısından önemsiz.
6. **Olası telaffuz:** "fişeği" → Whisper'da "fişeye". Ayrıca hız 0,9/1,0'da "Titanik" kelimesinin "Titanic" yazılması bir ASR eğilimi olabilir. Kulakla kontrol edilmeli.
7. Ölçüm betiğindeki indirme baytı hatası düzeltildi (bkz. §1).

## 10. SesVer'e uygunluk kararı

**Koşullu UYGUN: "⚡ Hızlı Mod" (yalnız Türkçe, tek ses) için arka uç hazır.**

Gerekçe:
- Kurulum 5 sn ve 35,7 MB, idempotent ve SHA doğrulamalı.
- İlk sese 1,9 sn, RAM ~291 MB.
- ~9× gerçek zaman; VoxCPM2'den ~65× hızlı.
- Sayı, tarih ve kısaltma okuması kusursuz; seed tam belirlenimci.
- SRT hizası medyan 70 ms.

Faz 3'e (arayüz) geçmeden önce:
- (1) Yusuf mp3'leri kulakla dinleyip onaylamalı.
- (2) Loudness normalizasyonu eklenmeli.
- (3) SRT için orijinal metin eşlemesi ve en az kip süresi kararı verilmeli.

Faz 3 ayrı onay gerektirir.

## Dosyalar

- Dinleme (yerel, gitignore): `ema_a.mp3`, `ema_b_sayilar.mp3`, `ema_c_belgesel.mp3`, `ema_seed_1-2-3.mp3` (seed 1→2→3, arada 0,5 sn), `ema_hiz_karsilastirma.mp3` (0,9→1,0→1,15, arada 0,5 sn)
- Altyazı: `ema_c.srt`
- Ölçüm betikleri ve ham veri: `_olcum/m1_kurulum.*`, `m2_soguk.*`, `m3_uretim.*`, `m3_tekrar.json`, `m4_asr_ecapa.*`, `m5_loud_ref.*`, `m6_analiz.*`, `pip_freeze_once.txt`, `pip_freeze_sonra.txt`
- WAV'lar (yerel, gitignore): `_olcum/wav/`
