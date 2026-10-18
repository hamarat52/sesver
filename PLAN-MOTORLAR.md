# SesVer — Motorlar Planı (VoxCPM2 · ElevenLabs · EMA Lightning)

Durum: **Faz 1 tamam (yalnız arka uç + mock test).** Arayüz yok; `app.py` değişmedi.
ElevenLabs ayrıntıları `PLAN-ELEVENLABS.md`'de kalır. Bu dosya üç motoru birlikte
ele alır ve EMA Lightning'i ("Hızlı Mod" isteği) planlar.

Yusuf'un isteği: *"ema lightning de ekleyebilir miyiz sence? hızlı mod diye ayrı bi
sekme koyarız oraya giderse ema'yı indirir tek tuşla ardından sadece emanın verdiği
imkanlarla türkçe ses üretir?"*

**Kısa cevap: evet.** Altyapı hazır ve mock testlerle doğrulandı. Sekme için Yusuf'un
onayı gerekiyor (§6). Kurulum bu makinede **çalıştırılmadı**: paket kurulmadı, model
indirilmedi, model başlatılmadı.

---

## 1. Eklenenler (Faz 1)

| Dosya | Ne yapar |
|---|---|
| `engines/ema.py` | `EmaEngine` adaptörü ve tek tuşla kurulum altyapısı: `ema_status()`, `ema_install(progress_cb, cancel=…)`, `ema_uninstall()` |
| `engines/srt.py` | Kelime zamanlarından SRT üretir (stdlib). EMA, altyazıyı Whisper'sız, doğrudan buradan alır |
| `engines/base.py` | Yeni bayraklar: `speed`, `word_timestamps`, `streaming`, `languages`. Varsayılanları `False`/boş olduğu için eski motorların davranışı değişmez. Yeni hatalar: `EngineNotInstalledError`, `InstallError`, `InstallCancelledError` |
| `engines/__init__.py` | `SESVER_ENGINE=ema` seçeneği. **Varsayılan `voxcpm` kalır** |
| `tests/test_ema.py` | 50 mock test. pip, HTTP, paket sürümleri ve model taklit edilir |

Seçim (yalnız ortam değişkeni):

```bash
SESVER_ENGINE=voxcpm      # varsayılan, %100 yerel
SESVER_ENGINE=elevenlabs  # bulut, ELEVENLABS_API_KEY
SESVER_ENGINE=ema         # yerel, yalnız Türkçe; önce engines.ema.ema_install()
```

Bugünkü `app.py` `engines`'i içe aktarmıyor (bunu bir test kontrol ediyor). Uygulama
aynen VoxCPM2 ile açılır.

---

## 2. Doğrulanmış EMA olguları (2026-10-18)

Kaynaklar: ilk ikisi `~/.hermes/tts/ema-venv` içindeki paket kaynağıdır (salt okundu,
SesVer'e bağlanmadı). Diğerleri PyPI JSON ve Hugging Face API'sinden gelir.

| Konu | Değer | Kaynak |
|---|---|---|
| Paket | `ema-lightning` 1.0.3, Apache-2.0, saf Python tekerlek (32.095 B) | PyPI `ema_lightning-1.0.3-py3-none-any.whl`; `METADATA` |
| Bağımlılıklar | `torch>=2.1`, `numpy>=1.24`, `huggingface-hub>=0.20`, `normalizer-tr>=0.4,<0.5`; Python `>=3.11` | `ema_lightning-1.0.3.dist-info/METADATA` |
| `normalizer-tr` 0.4.0 | Rust eklentisi. cp311–cp314 tekerlekleri macOS arm64/x86_64, Linux x86_64 ve Windows amd64 için var. **Linux arm64 tekerleği yok** (sdist Rust derlemesi ister). Python `<3.15` | PyPI dosya listesi; `METADATA` |
| Ağırlıklar | `config.json` 342 B · `ema.pt` 22.285.878 B · `decoder.pt` 12.103.269 B = **34.389.489 B ≈ 34,4 MB** | HF API `?blobs=true`, revizyon `7a6ba1ad…7632` |
| Bütünlük | `ema.pt` ve `decoder.pt` LFS sha256'ları koda sabitlendi; `config.json` git blob kimliği `a4f3b575…` | HF API |
| Yükleme | `load_acoustic`/`load_decoder` → `torch.load(..., weights_only=False)` (pickle) | `model.py:242`, `decoder.py:57` |
| API | `EMA(device="auto")` ağırlıkları `hf_hub_download` ile HF önbelleğinden çeker. `EMA._from_parts(model, decoder, frontend, device)` hazır parçalardan kurar. `say(text, speed=1.0, seed=None, sample_rate=48000, path=None)` → `Speech(audio float32 [-1,1], sample_rate, duration, seed, words)`. `stream(...)` float32 parçalar üretir | `api.py:61-75, 138-175` |
| Hız / seed | Hız 0,25–4. Seed negatif olmayan tam sayı; *"the same seed gives the same audio"*. Verilmezse rastgele seçilip `speech.seed` içinde döner | `METADATA` (parametre tablosu) |
| Sınırlar | *"One voice. No voice cloning and no emotion control. Turkish only."* | `METADATA` → Limitations |
| Yayımcının ölçümleri | 8,6M parametre. Freya-TR-Eval WER %0,92, UTMOS ≈ 3,30 (*"level with ElevenLabs v4"*). RTX 4090'da tek istek 440× gerçek zaman. **CPU'da ≈ 6× gerçek zaman** | `METADATA` (yayımcı beyanı; bu makinede ölçülmedi) |

---

## 3. Üç motorun karşılaştırması

### 3.1 Genel

| | **VoxCPM2** (varsayılan) | **ElevenLabs** | **EMA Lightning** (Hızlı Mod) |
|---|---|---|---|
| Çalıştığı yer | Yerel | Bulut (metin ve ses yurt dışı sunucuya gider) | Yerel (yalnız kurulumda ~34,4 MB iner) |
| Hız (M1 16 GB) | **Yavaş**: RTF ~7–8, yani 10 sn ses ≈ 70–80 sn (README ölçümü; swap varken daha kötü) | Ağa bağlı. **Ölçülmedi** (Faz 2 duman testi) | Yayımcıya göre CPU'da ≈ 6× gerçek zaman (10 sn ses ≈ 1,7 sn). **M1'de ölçülmedi** |
| Bellek | ≈ 9 GB model belleği | Yerelde ihmal edilebilir | Model ≈ 34 MB. Tepe RAM **ölçülmedi** (torch zaten yüklü) |
| Kalite | Yüksek doğallık, duygu ve tarif desteği. Türkçe telaffuz normalizer'a bağlı | Yüksek. Model kalite moduna göre değişir | Doğruluk çok yüksek (WER %0,92). Doğallık "iyi, en iyi değil" (UTMOS ≈ 3,30, yayımcı) |
| Ses çeşitliliği | **Sınırsız**: tarif, klon, hazır sesler, duygu | Geniş: hazır kütüphane, Voice Design, IVC (Starter+) | **Tek ses.** Seed yalnız aynı sesin farklı okumasını verir |
| Dil | Çok dilli (SesVer Türkçe odaklı) | Çok dilli | **Yalnız Türkçe** (yabancı kelimeler Türkçe kurallarla okunur) |
| Maliyet | 0 ₺ (elektrik/donanım) | Kredi/karakter. Free ayda 10k kredi, **ticari kullanım yok**; ticari için Starter+ (`PLAN-ELEVENLABS.md` §5) | 0 ₺. Apache-2.0, ticari kullanım serbest |
| Gizlilik | Hiçbir şey dışarı çıkmaz | Metin ve klon kaydı sağlayıcıya gider | Hiçbir şey dışarı çıkmaz |
| İnternet | Yalnız ilk model indirmesi | Her üretimde | Yalnız ilk kurulumda |
| En uygun iş | Karakterli ses, klon, duygu, son kalite | Bulutta hızlı ve kaliteli üretim, hazır ses kütüphanesi | Hızlı Türkçe taslak, uzun metin, seslendirme + altyazı, RAM'i dar makine |

### 3.2 Özellik tablosu (`Capabilities` bayrakları)

| Bayrak | VoxCPM2 | ElevenLabs | EMA |
|---|:-:|:-:|:-:|
| `local` | ✔ | ✘ | ✔ |
| `description_design` (ses tarifi) | ✔ | ✔ (Voice Design) | **✘ → `NotSupportedError`** |
| `clone` (referans kayıt) | ✔ | ✔ (IVC, Starter+) | **✘ → `NotSupportedError`** |
| `instruction` (duygu/stil) | ✔ | ✘ (adaptörde yok) | **✘ → `NotSupportedError`** |
| `seed` | ✔ (belirlenimci, kabul testi) | ✔ (belirlenimci değil) | ✔ (belgeye göre belirlenimci) |
| `speed` | ✘ | ✘ (adaptörde yok) | **✔ 0,25–4** |
| `word_timestamps` → SRT | ✘ (Whisper gerekir) | ✘ (adaptörde yok) | **✔ doğrudan** |
| `streaming` | ✘ | ✘ (adaptörde yok) | **✔ `stream()`** |
| `quality_modes` | Hızlı / Dengeli / En İyi | Hızlı / Dengeli / En İyi → model | **yok** (`quality` yok sayılır) |
| `metered` / `requires_api_key` | ✘ / ✘ | ✔ / ✔ | ✘ / ✘ |
| Çıkış | 48 kHz WAV | WAV (plana göre hız) | 48 kHz mono 16-bit WAV + aynı adla `.srt` |

"Bu motorda yok" mesajları açıktır ve gidilecek motoru söyler. Örnek: *"EMA Lightning
(Hızlı Mod) motorunda ses klonu yok: referans kayıt kabul etmez. Kayıttan ses için
VoxCPM2 motorunu seçin."* Tarif, klon veya talimat içeren bir istek model
**yüklenmeden** reddedilir. Ayrıca `voice="yusuf"` gibi tek ses dışındaki bir ses
adı da klon isteği sayılır ve reddedilir.

---

## 4. Kurulum yeri: ayrı venv mi, aynı ortam mı?

**Karar: SesVer'in kendi `.venv`'i.** Paket sabit sürümle ve `--no-deps --only-binary=:all:`
ile kurulur. Ağırlıklar SesVer'in kendi klasörüne iner: `models/ema-lightning/`
(`.gitignore`'da zaten `models/` var). `ema-venv`'e bağlanılmaz.

### 4.1 Uyum (gerçek sürümler, 2026-10-18)

| Gereksinim (EMA 1.0.3) | SesVer `.venv` | `~/.hermes/tts/ema-venv` | Uyum |
|---|---|---|---|
| Python ≥ 3.11 (`normalizer-tr` < 3.15) | 3.11 | 3.11 | ✔ |
| `torch>=2.1` | 2.14.1 (requirements: `>=2.5.0`) | 2.14.1 | ✔ aynı sürüm |
| `numpy>=1.24` | 2.4.6 | 2.4.6 | ✔ aynı sürüm |
| `huggingface-hub>=0.20` | 2.2.0 | 2.1.1 | ✔ |
| `normalizer-tr>=0.4,<0.5` | yok, kurulur (0.4.0, cp311 macOS arm64 tekerleği 1,27 MB) | 0.4.0 | ✔ |

İki ortamda torch ve numpy aynı sürüm. EMA bunlardan başka bir şey istemiyor ve
SesVer'in requirements'ındaki hiçbir sınırla çakışmıyor.

### 4.2 Gerekçe

| Ölçüt | Aynı `.venv` (seçilen) | Ayrı venv |
|---|---|---|
| İndirme | ≈ 1,3 MB paket + 34,4 MB ağırlık | Ek olarak torch'un ikinci kopyası (yüzlerce MB; tam boyut ölçülmedi) |
| RAM | torch tek kez yüklenir. Model ≈ 34 MB | İkinci Python süreci + ikinci torch |
| Bağlantı | Doğrudan çağrı; `Speech` nesnesi, kelime zamanları ve `stream()` parçaları süreç içinde | Alt süreç + IPC; akış ve iptal daha karmaşık |
| "Tek tuş" | `pip install` + indirme | Venv oluşturma + torch kurulumu: dakikalar sürer, daha çok hata yolu |
| Yalıtım | `--no-deps` sayesinde pip torch/numpy/hub'a **dokunmaz** | Tam yalıtım |
| Risk | İleride SesVer torch'u <2.1'e düşürürse kırılır (olası değil). `ema_status()` bunu `missing_dependencies` olarak bildirir | Yok |

**Neden `ema-venv` kullanılmıyor:** O ortam Hermes'in seslendirme aracına aittir.
SesVer'e bağlanırsa iki proje birbirine kilitlenir ve Yusuf dışında kimsenin
makinesinde çalışmaz. Görev de bunu yasaklıyor.

**Neden HF önbelleği (`~/.cache/huggingface`) kullanılmıyor:** `ema_uninstall()`
"yalnız EMA ağırlıklarını kaldırır" demek. Paylaşılan önbellekten silmek Hermes
araçlarının kopyasını da silerdi. Bedeli, bu makinede 34 MB'ın ikinci bir kopyasıdır.
Bu yüzden `default_loader`, `EMA()` (`hf_hub_download`) yerine paketin kendi parçalarını
kullanır: `load_acoustic`, `load_decoder`, `Frontend` ve `EMA._from_parts`. Böylece
üretim sırasında ağa çıkılmaz.

**`requirements.txt` değişmedi.** EMA isteğe bağlıdır ve yalnız kullanıcı "indir"e
basınca kurulur.

### 4.3 `ema_install()` akışı

```
kontrol ─► (paket eksikse) pip install --no-deps --only-binary=:all: ema-lightning==1.0.3 normalizer-tr==0.4.0
        ─► disk alanı (≥ ağırlık + 50 MB)
        ─► models/ema-lightning/.tmp-<uuid>/ içine sabit revizyondan indir (1 MB parçalar)
            · her parçada iptal kontrolü + ilerleme (fraction 0..1, bayt)
            · beklenenden büyükse dur; eksikse hata; sha256 / git-sha1 doğrula
        ─► hepsi doğrulandıysa os.replace ile yerine taşı + sesver-ema.json
        ─► son doğrulama (hash) ─► "tamam" (fraction 1.0)
```

- **İlerleme:** `progress_cb(InstallProgress)` → `stage` (kontrol / paket / indirme /
  dogrulama / tamam / geri_alma), `fraction`, `message`, `file`, `done_bytes`,
  `total_bytes`. Oran hiç geri gitmez (test edildi).
- **İptal:** `cancel=threading.Event()` ile başka iş parçacığından ya da `progress_cb`
  `False` döndürerek. pip sürerken iptal edilirse süreç `terminate`/`kill` ile kapatılır.
- **Yarım dosya kalmaz:** Hata veya iptalde `.tmp-*` silinir. Klasörü bu çağrı açtıysa
  o da silinir. Önceden tam olan dosyalar korunur. **Bu çağrının kurduğu paketler geri
  alınır**: yeni kurulduysa `pip uninstall`, sürüm yükseltildiyse eski sürüme dönülür.
- **Hata türleri:** Ağ/HTTP/kesik indirme → `EmaNetworkError`. Hash, disk, pip veya
  eksik torch → `InstallError`. İptal → `InstallCancelledError`. Hepsi Türkçe ve ne
  yapılacağını söyler. Eksik torch'u EMA kendisi **kurmaz**; mesaj `baslat.command`'ı
  önerir.
- **Tekrar çağrı:** Her şey yerindeyse ağa çıkmadan döner (hash ile doğrulanır).
  Yalnız eksik dosyalar iner.
- **Güvenlik:** Ağırlıklar pickle olduğu için hash'leri kodda sabittir. Model her
  yüklemeden önce `verify=True` ile doğrulanır. `ema_uninstall()` symlink klasörü
  silmeyi reddeder, yalnız bilinen dosya adlarını ve `.tmp-*` klasörlerini siler,
  klasördeki başka dosyalara dokunmaz, yüklü modeli bellekten bırakır ve paketleri
  kaldırmaz.
- **Kilit:** Aynı anda iki kurulum ya da kurulumla kaldırma çakışmaz
  (`threading.Lock`).

### 4.4 `ema_status()`

Torch'u veya `ema_lightning`'i içe aktarmaz ve ağa çıkmaz. Döndürdüğü alanlar:
`ready`, `package_installed` (+sürüm), `dependencies_ok` / `missing_dependencies`,
`weights_present`, dosya bazında `files`, diskte kapladığı `weights_bytes`,
indirilecek `download_bytes` + `package_download_bytes` ve düğme metni için
`download_label` (sıfırdan kurulumda `~35,7 MB`: 34,4 MB ağırlık + 1,3 MB paket).
`verify=True` sha256 hesaplar; boyutu aynı ama bozuk dosyayı yakalar (test edildi).

---

## 5. SRT (kelime zamanları)

`synthesize()` WAV'ın yanına aynı adla `.srt` yazar ve metnini `meta["srt"]`
alanında döndürür. Kelimeler `meta["words"]` içindedir (`text/start/end`, sn).
Altyazılar şu koşullarla bölünür: en çok 42 karakter, en çok 5 sn, 0,6 sn'den uzun
sessizlik ya da cümle sonu (`. ! ? …`). VoxCPM2'deki Whisper adımı EMA'da gerekmez.

---

## 6. Gelecekteki "⚡ Hızlı Mod" sekmesi — YALNIZ METİN TASARIM (UYGULANMAYACAK)

> **Yusuf onaylamadan UI uygulanmaz.** Aşağıdakiler öneridir. `app.py`'ye tek satır
> eklenmedi.

### 6.1 Ad çakışması ve öneri

Sorun: Kütüphane ve Klonlama sekmelerinde zaten **Kalite: Hızlı / Dengeli / En İyi**
(`inference_timesteps` 6/10/16) var. "Hızlı Mod" adlı bir sekme açılırsa iki ayrı
"Hızlı" olur. Biri VoxCPM2'nin hızlı ayarı, diğeri bambaşka bir motor. Kullanıcı
"Kalite: Hızlı" ile EMA'yı karıştırır.

| Seçenek | Sekme adı | Kalite etiketleri | Artı | Eksi |
|---|---|---|---|---|
| **A (önerilen)** | **⚡ Şimşek** (alt yazı: "Anında Türkçe ses · EMA Lightning") | Değişmez | Mevcut ekranlara dokunmaz. "Lightning"in Türkçesi, akılda kalır. Kalite modlarıyla kelime paylaşmaz | Yeni bir kelime öğrenilir |
| B | ⚡ Hızlı Mod | "Hızlı" → **"Taslak"** (Taslak / Dengeli / En İyi) | Yusuf'un kullandığı ad korunur | Mevcut iki sekmede etiket değişir. README ve alışkanlık güncellenmeli |
| C | ⚡ Anında Ses | Değişmez | Ne yaptığını söyler | "Anında" iddiası M1'de ölçülmeden verilmiş olur |

Öneri **A**. Kod tarafında hiçbir şey bu ada bağlı değil: motor adı `ema`, dosya öneki
`ema-`, `meta["mode"] = "ema"`. Karar sonradan değişebilir.

### 6.2 Kurulu değilken (`ema_status().ready == False`)

```
┌─ ⚡ Şimşek ─────────────────────────────────────────────┐
│  Anında Türkçe ses · bilgisayarında çalışır, internet    │
│  yalnız indirmede gerekir.                               │
│                                                          │
│  [ ⬇ EMA'yı indir (~35,7 MB) ]     ← status.download_label│
│                                                          │
│  ▓▓▓▓▓▓▓▓▓░░░░░░░░░  48 %  ema.pt indiriliyor… 16,4/34,4 MB│
│  [ İptal ]                     ← cancel Event.set()      │
│                                                          │
│  Tek ses, yalnız Türkçe. Tarif, klon ve duygu yok; bunlar │
│  için Ses Kütüphanesi / Ses Oluştur sekmeleri.           │
└──────────────────────────────────────────────────────────┘
```

- İlerleme çubuğu: `InstallProgress.fraction`. Metin: `message` + `done_bytes/total_bytes`.
- Hata olursa çubuk kaybolur. Türkçe hata ve **[Yeniden dene]** gösterilir. Yarım dosya
  kalmadığı için yeniden deneme temiz başlar; tam inmiş dosyalar tekrar inmez.
- İptal: "İndirme iptal edildi, hiçbir dosya kalmadı." Düğme eski haline döner.
- Eksik torch gibi bir durumda (`dependencies_ok=False`) düğme kilitlenir ve
  `missing_dependencies` gösterilir.

### 6.3 Kuruluyken

```
┌─ ⚡ Şimşek ─────────────────────────────────────────────┐
│  Metin   [ çok satırlı, Türkçe ………………………… ]  1.240/5.000 │
│  Hız     ──────●────────  1,0×   (0,25 – 4)              │
│  Ses varyasyonu (seed)  [ 1234 ] [🎲]  ← boşsa rastgele   │
│                                                          │
│  [ ⚡ Üret ]                                              │
│                                                          │
│  ▶ ses oynatıcı (48 kHz WAV)   seed: 987654 [📌 sabitle]  │
│  ⬇ WAV   ⬇ SRT (kelime zamanlı)                          │
│  Altyazı önizleme: 1  00:00:00,040 → 00:00:01,100 …       │
│                                                          │
│  ⚙ EMA: 34,4 MB · [Kaldır]      ← ema_uninstall()        │
└──────────────────────────────────────────────────────────┘
```

- **Yalnız** metin, hız ve seed alanları var. **Tarif, klon, referans kayıt, duygu ve
  Kalite alanları gizli** (gri değil, hiç yok). Bu, `Capabilities` bayraklarından
  türetilir: `description_design/clone/instruction=False`, `quality_modes=()`.
- "Ses varyasyonu" yanında not: "Aynı ses, farklı okuma. Beğendiğin okumayı seed ile
  sabitle." Rastgele üretimde dönen seed gösterilir; 📌 ile kutuya yazılır.
- SRT varsayılan olarak yazılır. Önizleme ilk 3 altyazıyı gösterir.
- Akış (`stream()`): v1'de yok. Gradio akışlı ses oynatıcı M1'de denendikten sonra
  "Üretirken çal" seçeneği olarak gelebilir (Faz 3+).
- Kaldır: onay sorar ("34,4 MB silinecek; paketler kalır"). Bittiğinde sekme 6.2'ye
  döner.

### 6.4 Diğer sekmelere etkisi

Yok. Ses Kütüphanesi'nde EMA'nın "tek sesi" listelenmez. Şimşek'te üretilen ses
kütüphaneye "ses" olarak kaydedilmez, yalnız çıktı olarak kalır. Klon/tarif
istendiğinde ilgili sekmeye yönlendiren tek satırlık not yeter.

---

## 7. Test sonucu (Faz 1)

```bash
~/Desktop/Projeler/sesver/.venv/bin/python -m unittest discover -s tests
# Ran 168 tests … OK   (118 önceki + 50 yeni EMA testi)
```

`pytest` SesVer `.venv`'inde yok ve görev gereği kurulmadı. Testler `unittest`
biçiminde yazıldı; `pytest` kurulursa değişmeden koşar.

`tests/test_ema.py` şunları kapsar:
- **Durum:** kurulu değil, kısmi dosya, aynı boyutta bozuk dosya (hash), yanlış
  paket/normalizer sürümü, eksik torch/numpy/Python, boyut etiketi ve gerçek HF
  boyutları.
- **Kurulum:** sıfırdan başarı (pip argümanları, sabit revizyon URL'leri, sıralı
  ilerleme, 1.0'da bitiş). Zaten kuruluyken ağa çıkmama. Yalnız eksik dosyayı indirme.
- **Ağ hatası** (URLError, HTTP 503, Timeout, ConnectionError, kesik indirme) → yarım
  dosya yok, klasör yok, paket geri alındı. Önceden tam olan dosya korunur.
- **Hash uyuşmazlığı, disk dolu, pip hatası, eksik torch.**
- **İptal:** `progress_cb` ile indirme ortasında, `threading.Event` ile, pip sırasında
  (gerçek `default_pip_runner` süreci sonlandırır; `Popen` taklit).
- **Kaldırma:** yalnız EMA dosyaları + `.tmp-*`; kullanıcı dosyası korunur; symlink
  reddedilir; tekrar çağrı güvenli; yüklü model bellekten bırakılır.
- **Motor:** `say` → 48 kHz mono PCM_16 WAV (süre, genlik, geçici dosya yok). Seed
  iletimi ve rastgele seed'in geri bildirimi. Model tek kez yüklenir; yüklemeden önce
  hash doğrulanır. Kelime zamanlarından SRT (dosya + meta). Tarif/klon/talimat → açık
  "bu motorda yok" (model yüklenmeden). Hız/seed/örnekleme hızı/metin doğrulaması.
  Kurulu değilken `EngineNotInstalledError` (boyutla). `stream`.
- **Seçim:** `SESVER_ENGINE=ema`, varsayılan `voxcpm`, seçimin `ema_lightning`'i
  içe aktarmaması. `app.py`'nin `engines`'e bağlı olmaması. `models/`'in gitignore'da
  olması. Kodun `ema-venv`'e ve `hf_hub_download(`'a başvurmaması.

---

## 8. Riskler

| Risk | Etki | Önlem |
|---|---|---|
| M1'de hız/RAM yayımcı beyanından farklı | "Anında" vaadi tutmaz | Faz 2'de ölçülecek; sekme adı bu yüzden "Anında" değil (§6.1) |
| Ağırlık deposu güncellenir/silinir | İndirme 404 olur ya da hash tutmaz | Sabit revizyon + hash; hata açık mesaj verir. Güncelleme bilinçli yapılır |
| `torch.load(weights_only=False)` (pickle) | Bozuk/kötü dosya kod çalıştırabilir | sha256 sabit; her yüklemede `verify=True` |
| `_from_parts` özel API | EMA sürüm değişikliğinde kırılabilir | Sürüm `==1.0.3` sabit; `ema_status` farklı sürümü "kurulu değil" sayar |
| Linux arm64 (tekerlek yok) | Kurulum başarısız | `--only-binary=:all:` → derleme denemesi yerine açık pip hatası, paket geri alınır |
| Tek ses | Kullanıcı tarif/klon bekler | Alanlar gizli; açık "bu motorda yok" mesajı ve yönlendirme |
| Yabancı kelimeler Türkçe okunur | Marka/İngilizce adlar tuhaf okunur | Arayüz notu; gerekirse yazım önerisi (Faz 3+) |

---

## 9. Yol haritası

1. **Faz 1 (bitti):** arka uç + mock testler + bu plan.
2. **Faz 2 (Yusuf onayıyla, gerçek kurulum):** `ema_install()` gerçek çalıştırma
   (~35,7 MB). M1'de ölçülecekler: ilk yükleme süresi, RTF, tepe RAM, aynı seed = aynı
   ses ve 3–4 Türkçe metinle VoxCPM2 "Hızlı" ile karşılaştırma.
   `ema_uninstall()` ile temizlik.
3. **Faz 3 (Yusuf onayıyla, arayüz):** §6'daki sekme. Ad kararı (§6.1) önce verilir.

---

## Açık Sorular

1. **Sekme adı:** A "⚡ Şimşek" (önerilen), B "⚡ Hızlı Mod" + kalite "Hızlı"→"Taslak",
   ya da C "⚡ Anında Ses"?
2. **Faz 2 gerçek kurulum** yapılsın mı (SesVer `.venv`'ine ~1,3 MB paket +
   `models/` altına 34,4 MB ağırlık)?
3. Bu makinede EMA ağırlıkları zaten HF önbelleğinde var. İleride "önbellekte hash'i
   tutan kopya varsa indirmeden kopyala" kısayolu istenir mi? (Şu an bilerek yok:
   kurulum makineden bağımsız ve kaldırma yalıtılmış kalsın diye.)
