# SesVer × ElevenLabs — Altyapı ve Entegrasyon Planı

Durum: **Faz 1 (altyapı) tamam ✔**. Arayüz yok.
Branch: `feature/elevenlabs-backend` (worktree: `~/Desktop/Projeler/sesver-elevenlabs`). Merge yapılmadı, push yapılmadı.
Tarih: 2026-10-18. Hazırlayan: WebDev. Olgular aynı gün resmî dokümandan okundu.

> Üç motorun (VoxCPM2 · ElevenLabs · EMA Lightning) karşılaştırması ve "⚡ Hızlı Mod"
> planı: **`PLAN-MOTORLAR.md`**. Bu dosya yalnız ElevenLabs ayrıntılarını içerir.

---

## 1. Özet

### Eklenenler (yalnız arka uç, arayüzden bağımsız)

| Dosya | Ne yapar |
|---|---|
| `engines/base.py` | Ortak motor sözleşmesi: `synthesize`, `list_voices`, `design_voice`, `clone_voice`, `usage`, `estimate`. Ayrıca yetenek bayrakları (`Capabilities`), veri tipleri ve Türkçe hata sınıfları. |
| `engines/voxcpm.py` | VoxCPM2 için ince sarmalayıcı. `app.generate_audio`'yu olduğu gibi çağırır ve son çıktıyı okur; yeniden yazmaz. |
| `engines/elevenlabs.py` | ElevenLabs adaptörü:<br>• stdlib `urllib`, yeni paket yok<br>• WAV 48 kHz mono PCM_16 dönüşümü<br>• Türkçe normalizasyon<br>• tarif eşleme<br>• kota koruyucu<br>• 401/402/403/404/429/5xx hata eşleme ve backoff<br>• izin kontrolü ve kişisel ses koruması<br>• disk önbelleği<br>• anahtar maskeleme |
| `engines/text_tr.py` | Türkçe sayı, yüzde, saat, birim ve kısaltma okuma (stdlib). Gerekçesi aşağıda. |
| `engines/__init__.py` | `SESVER_ENGINE=voxcpm\|elevenlabs` ile motor seçimi. Varsayılan `voxcpm`. |
| `scripts/elevenlabs_smoke.py` | Faz 2 duman testi. Yalnız Yusuf, kendi anahtarıyla çalıştırır. |
| `tests/test_engines.py` | 42 test. HTTP katmanı taklit edilir; model yüklenmez, ağa çıkılmaz. |

### Eklenmeyenler (bilerek)

- **Arayüz:** Gradio bileşeni, CSS, sekme yok. `_library_tab`, `_design_subtab`, `_upload_subtab` ve `build_app` değişmedi. `app.py` hiç değişmedi; diff boş.
- `app.py` motor katmanını içe aktarmıyor (bunu bir test doğruluyor). Uygulama bugünkü gibi VoxCPM2 ile açılır.
- Yeni bağımlılık yok. `requirements.txt` değişmedi.
- Gerçek ElevenLabs isteği atılmadı. Anahtar istenmedi, okunmadı, kaydedilmedi.
- ElevenLabs'e ses yükleme (IVC) kodu var ama hiçbir yerden çağrılmıyor. Faz 3'e kadar kullanıcıya açık değil.

### Normalizer hakkında düzeltme

Görev, "mevcut normalizer'ı yeniden kullan" diyordu. İnceledim:
- SesVer'de bugüne kadar Türkçe normalizer yokmuş.
- VoxCPM paketindeki `voxcpm/utils/text_normalize.py` Çince ve İngilizce içindir. Sayıları `inflect` ile İngilizce okur.
- SesVer bu normalizer'ı zaten kapalı kullanıyor (`generate(normalize=False)`).

Bu yüzden ElevenLabs'e özel, küçük ve kurallı bir `engines/text_tr.py` yazıldı. VoxCPM2 hattına dokunulmadı, davranışı aynı kaldı. Ayrıca ElevenLabs'in kendi `apply_text_normalization="auto"` ayarı da açık.

---

## 2. Doğrulanmış ElevenLabs olguları

Her satırın kaynağı yanında. "Doğrulanamadı" yazanlar resmî kaynakta bulunamadı ve Faz 2'de ölçülecek.

### 2.1 Text-to-Speech

| Olgu | Değer | Kaynak |
|---|---|---|
| Uç nokta | `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}` | https://elevenlabs.io/docs/api-reference/text-to-speech/convert |
| Kimlik doğrulama | `xi-api-key` başlığı | aynı sayfa (örnekler); https://elevenlabs.io/docs/help-center/technical/api-error-code-400-or-401 (`invalid_api_key`) |
| Gövde | `text`, `model_id` (varsayılan `eleven_multilingual_v2`), `language_code`, `voice_settings`, `seed`, `previous_text`/`next_text`, `previous_request_ids`/`next_request_ids` (en fazla 3), `apply_text_normalization` (`auto`/`on`/`off`), `pronunciation_dictionary_locators` | convert sayfası |
| `voice_settings` varsayılanları | `stability` 0.5, `similarity_boost` 0.75, `style` 0, `use_speaker_boost` true, `speed` 1.0 | convert sayfası |
| `language_code` | ISO 639-1. **`multilingual_v2` modellerinde desteklenmez.** | convert sayfası |
| `seed` | 0–4294967295 arası. "En iyi çaba" ile çalışır; **belirlenimcilik garanti değil.** | convert sayfası |
| Çıktı biçimleri | `mp3_*`, `pcm_8000…48000`, `wav_8000…48000`, `opus_48000_*`, `ulaw_8000`, `alaw_8000`. Varsayılan `mp3_44100_128`. | convert sayfası |
| Plan kısıtları (biçim) | 44,1 kHz PCM/WAV için **Pro ve üstü**; 192 kbps MP3 için Creator ve üstü | convert sayfası; https://help.elevenlabs.io/hc/en-us/articles/15754340124305 (PCM 8–24 kHz: Free/Starter/Creator) |
| `wav_48000`/`pcm_48000` hangi planda? | **Doğrulanamadı.** Yardım sayfası 48 kHz PCM'i plansız listeliyor, kesin değil. SesVer bu yüzden `wav_24000` ister ve 48 kHz'e kendisi çevirir. | — |

### 2.2 Modeller ve Türkçe

| Model | Türkçe | Tek istek sınırı | TTS API'de | Kaynak |
|---|---|---|---|---|
| `eleven_multilingual_v2` | ✔ (`tr`) | 10.000 karakter | ✔ (varsayılan) | https://elevenlabs.io/docs/overview/models |
| `eleven_flash_v2_5` | ✔ (v2 dilleri + hu/no/vi) | 40.000 karakter | ✔ | aynı |
| `eleven_v3` | ✔ (Turkish, 70+ dil) | 5.000 karakter | ✔ ("Text to Speech API ile de kullanılabilir") | aynı |
| `eleven_v4` | ✔ (Turkish, 90+ dil) | 10.000 karakter (karakter sınırı tablosu) | **Belirsiz.** Model sayfası "Text to Dialogue API üzerinden" diyor; hata sayfasındaki SDK örneği TTS ile `eleven_v4` kullanıyor. **Doğrulanamadı → Faz 2.** | aynı; https://elevenlabs.io/docs/eleven-api/resources/errors |
| `eleven_v4_turbo` | ✔ | — | Yalnız "Text to Dialogue websocket" | models sayfası |
| `eleven_turbo_v2_5` | ✔ | 40.000 | Kullanımdan kalkıyor ("Flash'ı kullanın") | models sayfası |

### 2.3 Sesleri listeleme

| Olgu | Değer | Kaynak |
|---|---|---|
| Uç nokta | `GET /v2/voices`. `page_size` en fazla 100; `next_page_token` ve `has_more` ile sayfalama. `search`, `category` (`premade`/`cloned`/`generated`/`professional`), `language` filtreleri var. | https://elevenlabs.io/docs/api-reference/voices/search |

### 2.4 Voice Design (tariften ses)

| Olgu | Değer | Kaynak |
|---|---|---|
| Önizleme | `POST /v1/text-to-voice/design`. Gövde: `voice_description` (zorunlu), `model_id` (`eleven_multilingual_ttv_v2` varsayılan veya `eleven_ttv_v3`), `text` (**100–1000 karakter**), `auto_generate_text`, `seed` ("aynı seed + aynı girdi = aynı ses"), `guidance_scale` (varsayılan 5), `loudness`, `should_enhance`. | https://elevenlabs.io/docs/api-reference/text-to-voice/design |
| Yanıt | `previews[]`: `audio_base_64`, `generated_voice_id`, `media_type`, `duration_secs`, `language` | aynı |
| Kalıcı kaydetme | `POST /v1/text-to-voice`. Gövde: `voice_name`, `voice_description`, `generated_voice_id`, `labels`. | https://elevenlabs.io/docs/api-reference/text-to-voice/create |
| Önizleme sayısı ve maliyet | Her "Generate" **üç seçenek** üretir. Ücret yalnız önizleme metninin karakteri kadardır ve **bir kez** alınır. | https://elevenlabs.io/docs/eleven-creative/voices/voice-design |
| İstem yazımı | İlk cümlede dili açıkça yaz ("Native <Language>."). "Accent" kelimesini tonlama anlamında kullanma; lehçe kayması yapar. | aynı |
| `ttv_v2` dilleri | `tr` dahil | models sayfası |
| API'de dönen önizleme sayısının 3 olması | Rehber "üç" diyor; API referansında sayı yok. **API için doğrulanamadı.** Adaptör kaç tane dönerse onu kullanır. | — |

### 2.5 Instant Voice Cloning (IVC)

| Olgu | Değer | Kaynak |
|---|---|---|
| Uç nokta | `POST /v1/voices/add` (multipart). Alanlar: `name`, `files[]`, `remove_background_noise`, `description`, `labels`. Yanıt: `voice_id`, `requires_verification`. | https://elevenlabs.io/docs/api-reference/voices/ivc/create |
| Plan | Ücretsiz planda **yok**. **Starter ve üstü** ("Everything in free, plus … Instant Voice Cloning"). | https://elevenlabs.io/pricing |
| Plan sorgusu | `GET /v1/user/subscription` → `can_use_instant_voice_cloning` | https://elevenlabs.io/docs/api-reference/user/subscription/get |
| Önerilen kayıt | 1–2 dakika temiz ses. 3 dakikadan fazlası faydasız, bazen zararlı. Kayıt, "klonlama hakkı ve izni olduğunu onayla" adımıyla kaydedilir. | https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning/instant-voice-cloning |
| Transkript | API transkript almıyor (alan yok). | ivc/create sayfası |

### 2.6 Kota, hata kodları, eşzamanlılık

| Olgu | Değer | Kaynak |
|---|---|---|
| Kota sorgusu | `GET /v1/user/subscription` → `tier`, `character_count`, `character_limit`, `next_character_count_reset_unix`, `voice_slots_used`, `voice_limit`, `can_use_instant_voice_cloning`, `max_credit_limit_extension`… | subscription/get sayfası |
| Kredi = karakter | TTS'te 1 karakter = 1 kredi (Multilingual v2). Flash/Turbo için self-serve planlarda 0,5 kredi/karakter; pricing SSS'de "0,5–1". Bazı kütüphane seslerinde çarpan olabilir. | https://help.elevenlabs.io/hc/en-us/articles/27562020846481-What-are-credits ; https://elevenlabs.io/pricing |
| v3 / v4 kredi oranı | API fiyat sayfasında v3 ve v4 için $0,08 / 1K karakter (Multilingual v2 ile aynı). Kredi/karakter oranı açıkça yazmıyor. **Doğrulanamadı** (≈1 varsayıldı). | https://elevenlabs.io/pricing/api |
| Hata biçimi | `{"detail": {"type","code","message","status"(eski),"request_id","param"}}` | https://elevenlabs.io/docs/eleven-api/resources/errors |
| Tipler ve HTTP kodları | `authentication_error` 401, `payment_required` 402, `authorization_error` 403, `not_found` 404, `rate_limit_error` 429, `internal_error` 500, `service_unavailable` 503 | aynı |
| Kodlar | `invalid_api_key`, `missing_api_key`, `insufficient_credits`, `feature_not_available`, `subscription_required`, `rate_limit_exceeded`, `concurrent_limit_exceeded`, `system_busy`, `voice_not_found`, `text_too_long`… | aynı |
| `quota_exceeded` | Eski biçim; "Error Code 400 or 401" sayfasında. | https://elevenlabs.io/docs/help-center/technical/api-error-code-400-or-401 |
| `too_many_concurrent_requests` | 429 ile döner. | https://help.elevenlabs.io/hc/en-us/articles/19571824571921-API-Error-Code-429 |
| 429 önerisi | Hız sınırında üstel backoff uygula. Eşzamanlılık sınırında mevcut isteklerin bitmesini bekle. | errors sayfası |
| Eşzamanlılık (Multilingual v2 / Flash) | Free 2/4 · Starter 3/6 · Creator 5/10 · Pro 10/20 · Scale ve Business 15/30 | https://elevenlabs.io/docs/overview/models (Concurrency and priority) |
| Rate-limit başlıkları | `current-concurrent-requests`, `maximum-concurrent-requests` | models sayfası |
| `Retry-After` başlığı | **Doğrulanamadı.** Adaptör varsa uyar, yoksa üstel bekler. | — |
| `request-id` / `character-cost` yanıt başlıkları | **Doğrulanamadı.** Adaptör varsa yalnız meta'ya yazar; mantık bunlara bağlı değil. | — |

### 2.7 Planlar, ücretsiz plan, ticari kullanım

| Olgu | Değer | Kaynak |
|---|---|---|
| Ücretsiz planda API | Var: "API tüm planlarda, ücretsiz dahil". | https://help.elevenlabs.io/hc/en-us/sections/14163158308369-API |
| Free | Ayda 10k kredi. TTS, Voice Design, STT, SFX dahil. **IVC yok, ticari lisans yok.** | https://elevenlabs.io/pricing |
| Starter | Ayda 30k kredi. Ticari lisans + IVC. | aynı |
| Creator | Ayda 121k kredi. PVC. | aynı |
| Pro | Ayda 600k kredi. 44,1 kHz PCM. | aynı |
| Fiyatlar | Sayfadaki fiyatlar o günkü kampanyaları içeriyor (ör. "Until Oct 18" indirimi). Fiyatı plana yazmıyorum; karar anında yeniden bakılmalı. | aynı |
| Kredi devri | Kullanılmayan krediler en fazla 2 ay devreder. | https://elevenlabs.io/docs/overview/intro |
| Ücretsiz plan ticari kullanım | **Ticari amaçla kullanılamaz.** Yayınlanan içerikte başlığa **"elevenlabs.io" ya da "11.ai" atfı zorunlu.** | https://help.elevenlabs.io/hc/en-us/articles/13313564601361-Can-I-publish-the-content-I-generate-on-the-platform |
| Ücretli plan | Ücretli abonelik süresince üretilen içerik ticari olarak süresiz kullanılabilir. Abonelik dışında üretilen içerik her zaman atıf ister. | aynı; https://help.elevenlabs.io/hc/en-us/articles/15993008593297 |
| Beta servisler | Beta servislerle üretilen içerik ticari kullanılamaz. | aynı (Beta Services Addendum) |
| Ücretsiz planda ses slotu sayısı | **Doğrulanamadı.** `usage().voice_limit` ile Faz 2'de okunacak. | — |

---

## 3. Mimari

```
                 (Faz 3'e kadar bağlı DEĞİL)
app.py (Gradio) ─────────────X──────────────┐
   │ bugün: generate_audio → WAV → effects   │
   ▼                                         ▼
engines.get_engine()  ◄── SESVER_ENGINE (varsayılan voxcpm)
   ├─ VoxCPMEngine   → app.generate_audio (aynen) → outputs/<uuid>.wav (48 kHz)
   └─ ElevenLabsEngine
        text_tr.normalize → estimate() → _guard() → önbellek? ──evet──► kopya WAV (0 kredi)
                                                    │hayır
                     _request(urllib, xi-api-key, backoff) → decode_audio → to_app_wav
                                                    ▼
                             outputs/ai-ile-uretildi-<uuid>.wav (48 kHz, mono, PCM_16)
                                                    ▼
                         effects.apply → (gelecekte) birleştirme / SRT
```

### 3.1 Motor arayüzü (`engines/base.py`)

```
synthesize(text, voice, instruction, seed=None, quality="Dengeli", **opts) -> SynthesisResult(path, sample_rate, meta)
list_voices() -> [VoiceInfo]
design_voice(description, preview_text, candidates=…) -> [DesignPreview]
clone_voice(audio, transcript, consent, name=…) -> VoiceInfo        # consent is not True → ConsentError
usage() -> UsageInfo           estimate(text, quality) -> QuotaEstimate
capabilities -> Capabilities
```

Hatalar `EngineError` altında toplanır ve hepsi Türkçe, kullanıcıya gösterilebilir mesaj taşır:
`AuthError` (401), `QuotaError` (402 / quota_exceeded / yerel koruyucu), `RateLimitError` (429, denemeler bitti), `PlanFeatureError` (403 / plan), `VoiceNotFoundError`, `TextTooLongError`, `ServiceError` (5xx / ağ), `ConsentError`, `EngineConfigError`.

### 3.2 Yetenek bayrakları

| Bayrak | VoxCPM2 | ElevenLabs |
|---|---|---|
| `local` | ✔ | ✘ (bulut) |
| `seed` / `seed_deterministic` | ✔ / ✔ | ✔ / ✘ (TTS'te "en iyi çaba") |
| `continuation` (devam kipi) | ✔ | ✘ (`previous_text` yalnız metin sürekliliği) |
| `instruction` (duygu talimatı) | ✔ | ✘ (bu sürümde; v3/v4 ses etiketleri Faz 2/3) |
| `description_design` | ✔ | ✔ (Voice Design) |
| `clone` | ✔ (yerel) | ✔ (IVC, Starter+) |
| `multi_candidate` / `default_candidates` | ✔ / 4 | ✔ / **1** (kota koruması) |
| `candidates_per_design_call` | 1 | 3 (rehber) |
| `max_text_chars` | 500 (bugünkü uygulama sınırı) | 5.000 (en dar model v3) |
| `requires_api_key` / `metered` | ✘ / ✘ | ✔ / ✔ |

### 3.3 Çoklu aday ve seed

- **VoxCPM2:** 4 aday = aynı tarif + aynı cümle, 4 farklı seed. Aynı seed aynı sesi verir.
- **ElevenLabs Voice Design:** Bir çağrı yaklaşık 3 önizleme döndürür ve yalnız önizleme metni kadar kredi harcar.
  - `candidates=1` (varsayılan) → 1 çağrı, 1 önizleme gösterilir.
  - `candidates=4` → 2 çağrı; seed artarak gönderilir (s, s+1).
  - Her çağrı ayrı ayrı kota koruyucudan geçer.
- **ElevenLabs TTS'te çoklu aday:** Seed belirlenimci olmadığından "4 aday" = 4 ayrı TTS isteği = 4 kat kredi. Bu yüzden TTS'te varsayılan 1. Kalıcı ses kimliği (voice_id) zaten sesin kendisini sabitler; adaylar yalnız okuma farkı üretir.

### 3.4 Kota koruyucu ve önbellek

- `estimate()` istekten **önce** şunları hesaplar: normalize edilmiş karakter sayısı × kredi/karakter (muhafazakâr, 1,0) = tahmini kredi. Ardından `usage()` ile kalan kotayı alır (30 sn önbellekli).
- Kota yetmezse **istek atılmaz**, açık bir `QuotaError` döner: "…yaklaşık N kredi istiyor, kalan M…".
- Başarılı istekten sonra kalan kota yerelde düşülür; ek bir istek atılmaz.
- Önbellek anahtarı: `sha256` hash'i. İçine metin (normalize), ses, model, `voice_settings`, seed, `language_code`, `previous_text`/`next_text`, çıktı biçimi ve hedef örnekleme hızı girer.
  - Dosya: `outputs/.cache/elevenlabs/<hash>.wav` (`.gitignore` kapsamında).
  - İsabette 0 kredi harcanır. Kopya yeni bir `uuid` dosyası olarak döner; böylece efektler önbelleği bozmaz.

### 3.5 Mevcut hatta bağlantı

- `effects.apply` dosyayı `sf.read(..., always_2d=True)` ile okuyor (bkz. `apply_effects_ui`). ElevenLabs çıktısı VoxCPM2 ile aynı biçimde: **48 kHz, mono, PCM_16 WAV**. Efekt zinciri değişmeden çalışıyor; bunu bir test doğruluyor.
- **SRT ve birleştirme:** Repo taramasında (`srt|altyazı|birleştir|concat`) SesVer'de bugün SRT ya da çoklu klip birleştirme hattı **yok**; yalnız efekt zinciri var.
  - Motor çıktısı tek biçimde WAV olduğu için ileride eklenecek birleştirme veya SRT, motordan bağımsız çalışacak.
  - Süre için `sf.info(path).duration` kullanılabilir.
  - Bkz. Açık Sorular.

### 3.6 Anahtar güvenliği

- Anahtar yalnız `ELEVENLABS_API_KEY` ortam değişkeninden, **istek anında** okunur. Nesne alanında tutulmaz.
- `__repr__` anahtar yerine "var/yok" gösterir.
- Hata mesajlarında anahtar yok. Ağ istisnaları yalnız tür adıyla zincirlenir.
- Modül logger'ına takılı filtre, logda geçen anahtarı `***abcd` biçiminde maskeler.
- Testler kontrol eder:
  - repr, hata ve logda anahtarın görünmemesi
  - kaynak kodda `sk_…` deseninin olmaması

---

## 4. Özellik eşleme

| SesVer özelliği | VoxCPM2 | ElevenLabs | Not |
|---|---|---|---|
| Hazır sesler (`voices/hazir`) | ✔ | **Kısmen** | ElevenLabs'in kendi hazır sesleri `list_voices()` ile gelir; SesVer'in sentetik hazır sesleri ElevenLabs'te yok. Taşımak IVC demek: Starter+ gerekir ve ses slotu harcar. Önerilmez. |
| Seçimlerle tarif (`voice_designer`) | ✔ (her üretimde tarif) | ✔ | `map_description()` İngilizce tarifi "Native Turkish speaker. … Excellent audio quality." biçimine çevirir. Akış: önizleme → beğenilen `save_designed_voice()` ile kalıcı `voice_id` olur → TTS. Fark: ElevenLabs'te kalıcı ses bir **slot** harcar. |
| Dosya yükleme ve klon | ✔ (1–30 sn + transkript, devam kipi) | **Kısmen** | IVC Starter+ ister. 1–2 dk önerilir; SesVer'in 1–30 sn referansları kısa kalır. Transkript gönderilmez. `consent=True` zorunlu. Korumalı isimler asla yüklenmez; kütüphane sesleri yalnız `allow_library_upload=True` ile yüklenir. |
| 4 aday | ✔ (4 seed) | **Kısmen** | Tasarımda ~3 önizleme/çağrı. TTS'te seed belirlenimci değil. Varsayılan 1. |
| Kalite: Hızlı / Dengeli / En İyi | ✔ (timesteps 6/10/16) | **Kısmen** | Model seçimine eşlenir: `eleven_flash_v2_5` / `eleven_multilingual_v2` / `eleven_v3`. Anlam farklı: hız, maliyet ve ifade. `SESVER_ELEVENLABS_MODEL` ile tek modele sabitlenebilir (ör. Faz 2'de doğrulanırsa `eleven_v4`). |
| Duygu (Nötr/Sakin/Neşeli…) | ✔ | **Yok (bu sürümde)** | Talimat sessizce düşmez; `meta["uyarilar"]` alanına yazılır. v3/v4 ses etiketleri (`[calm]` vb.) Faz 3 adayı. |
| Efektler | ✔ | ✔ | Aynı WAV biçimi; test var. |
| SRT | — (bugün yok) | — | Bkz. 3.5. |
| Uzun metin | 500 karakter (uygulama sınırı) | Model sınırı 5k–40k | Uygulamadaki 500 sınırı arayüz kararı; Faz 3'te ele alınacak. Adaptör bölme için `previous_text`/`next_text` kabul ediyor. |

---

## 5. Kota ve maliyet (örnek: 60 sn video metni ≈ 800 karakter)

Kaynaklar: kredi/karakter oranları için https://help.elevenlabs.io/hc/en-us/articles/27562020846481-What-are-credits, plan kredileri için https://elevenlabs.io/pricing.

| Kalite modu → model | Kredi/karakter | 1 video (800 kr.) | **Free (10k)** | Starter (30k) | Creator (121k) |
|---|---|---|---|---|---|
| Hızlı → `eleven_flash_v2_5` | 0,5 (self-serve) | 400 | **25 video** | 75 | 302 |
| Hızlı (muhafazakâr hesap, 1,0) | 1,0 | 800 | 12 | 37 | 151 |
| Dengeli → `eleven_multilingual_v2` | 1,0 | 800 | **12 video** | 37 | 151 |
| En İyi → `eleven_v3` | ≈1,0 (doğrulanamadı) | ≈800 | **≈12 video** | ≈37 | ≈151 |

Tabloyu okurken şunlara dikkat:
- **Aday sayısı maliyeti çarpar.** TTS'te 4 aday = 4 kat. Free planda Dengeli ile ayda ≈3 video eder. Varsayılanın 1 olmasının sebebi bu.
- **Ses tasarımı:** Önizleme metni 100–1000 karakter. Örnek: 180 karakterlik metinle 1 tasarım ≈ 180 kredi, ~3 önizleme. 4 aday için 2 çağrı ≈ 360 kredi.
- **Kota koruyucunun tahmini** Flash için bilerek 1,0 kullanır; gerçek harcama genelde daha azdır. Faz 2'deki duman testi bunu `usage()` farkıyla ölçer ve oran gerekirse güncellenir.
- **Önbellek:** Aynı metin + ses + ayar tekrarında 0 kredi harcanır.
- **Kritik uyarı:** Free planda üretilen ses **ticari amaçla kullanılamaz** ve yayında başlıkta "elevenlabs.io" atfı ister. Sosyal medya, marka veya gelir amaçlı kullanım için en az Starter gerekir.

---

## 6. Gelecekteki arayüz planı (YALNIZ METİN — UYGULANMAYACAK)

> **Bu bölüm Yusuf açıkça onaylamadan uygulanmayacak.** Faz 1'de hiçbir arayüz değişikliği yapılmadı.

1. **Motor seçici:** Üst başlığa küçük bir "Yerel (VoxCPM2) / Bulut (ElevenLabs)" seçimi; varsayılan Yerel.
   - Seçim, `capabilities` bayraklarına göre denetimleri açar ya da gizler.
   - ElevenLabs'te gizlenenler: duygu, devam kipi; aday sayısı 1'e iner.
2. **API anahtarı girişi:** Saklama seçenekleri:

   | Seçenek | Artı | Eksi |
   |---|---|---|
   | **macOS Keychain** (`security add-generic-password`, ya da `keyring` paketi) | Şifreli, OS kilidine bağlı, repo/dosyada iz yok | `keyring` yeni bağımlılık (veya `security` CLI çağrısı); macOS'e özgü |
   | Yalnız ortam değişkeni (bugünkü) | Sıfır kod, sıfır kalıcılık | Her oturumda yeniden girilir; `baslat.command` ile kullanıcı dostu değil |
   | Yerel dosya (`~/.config/sesver/…`, 0600) | Basit | Düz metin; yedeklere ve Spotlight'a sızabilir; repoya yanlışlıkla girme riski |

   **Öneri:** Keychain (`security` CLI ile, yeni paket gerektirmez). Arayüzde maskeli alan ve "Kaydet / Sil" düğmesi olur. Anahtar asla `outputs/`, log ya da Gradio state'e yazılmaz.
3. **Kota göstergesi:** "Kalan: 9.200 / 10.000 kredi · yenilenme: <tarih>". Üretim düğmesinin yanında "Bu metin ≈ 800 kredi" tahmini. Kota yetmezse düğme kilitlenir ve neden yazılır.
4. **Bulut uyarısı:** ElevenLabs seçiliyken kalıcı bir şerit: "Bulut kullanılıyor: metin ve ses ElevenLabs sunucularına gider, %100 yerel değil." Free plandaysa ek uyarı: "Ticari kullanım yok; yayında 'elevenlabs.io' atfı zorunlu."
5. **Klon izin kutusu:** İki ayrı onay:
   - (a) "Bu sesin sahibiyim ya da sahibinin açık izni var."
   - (b) "Bu kaydın ElevenLabs'e yükleneceğini anlıyorum."

   Kişisel kütüphane seslerinde üçüncü bir açık onay istenir. Korumalı isimlerde düğme hiç görünmez.
6. **Tarif akışı:** "Önizleme üret (≈N kredi)" → önizleme kartları → "Bu sesi kaydet (1 ses slotu)". Slot sayısı (`voice_slots_used/voice_limit`) görünür.

---

## 7. Güvenlik ve gizlilik

- ElevenLabs seçiliyken **metin ve ses buluta gider.** Varsayılan motor yerel kalır; bulut yalnız `SESVER_ENGINE=elevenlabs` ile ya da Faz 3'te açık seçimle devreye girer.
- **Kişisel klon sesleri ElevenLabs'e yüklenmez:**
  - `voice_library.PROTECTED_NAMES` (yusuf, yusuf2, akif) adda, kimlikte ya da dosya yolunda geçiyorsa yükleme **koşulsuz** reddedilir.
  - `voices/` altındaki her ses (Seslerim) yalnız `allow_library_upload=True` açık izniyle yüklenebilir.
  - Her durumda `consent=True` zorunlu (`"evet"`, `1` gibi değerler kabul edilmez).
- IVC'ye transkript gönderilmez (API zaten istemiyor).
- Anahtar: yalnız ortam değişkeni, maskeli log; repoda ve testlerde gerçek anahtar yok (desen testi var).
- Ücretsiz planda ticari kullanım yasak ve atıf zorunlu. Bu bir hukuki risk; bkz. Bölüm 6, madde 4.
- Önbellek (`outputs/.cache/elevenlabs`) yereldir ve `.gitignore` kapsamındadır. Üretilen sesi ve metnin hash'ini tutar, metnin kendisini tutmaz.

---

## 8. Riskler

| Risk | Etki | Önlem |
|---|---|---|
| `eleven_v4` TTS uç noktasında çalışmayabilir | "En İyi" modu hata verir | Varsayılan `eleven_v3`; v4 yalnız Faz 2'de doğrulanırsa ortam değişkeniyle açılır |
| Kredi oranı tahmini sapması | Kota göstergesi yanıltır | Muhafazakâr 1,0; Faz 2'de ölçüm |
| Kota tükenmesi ya da 429 | Üretim durur | Ön kontrol, üstel backoff (en fazla 3 deneme, en fazla 30 sn), Türkçe hata, yerel motora dönüş önerisi |
| Seed belirlenimci değil | "Aynı seed aynı ses" kabul testi ElevenLabs TTS'te geçmez | Bayrak `seed_deterministic=False`; ses kimliği (voice_id) sesi sabitler |
| Türkçe telaffuz ve normalizasyon hataları | Sayı ve kısaltma yanlış okunur | `text_tr` dar ve kurallı (sıra sayıları ve tarihler bilerek çevrilmez); ElevenLabs `auto` normalizasyonu da açık; Faz 2'de dinleme testi |
| Ticari kullanım (Free) | Hukuki | Arayüz uyarısı; ticari iş için Starter+ |
| Ses slotu dolması | Tasarım kaydı başarısız | `usage().voice_limit` ile ön kontrol (Faz 3) |
| Bulut gizliliği | Metin ve ses dışarı çıkar | Varsayılan yerel; açık uyarı; kişisel sesler engelli |

---

## 9. Yol haritası

1. **Faz 1 — Altyapı ✔:** Motor soyutlaması, iki adaptör, motor seçimi, 42 mock test, bu plan, duman testi betiği. Arayüz yok.
2. **Faz 2 — Gerçek anahtarla duman testi (Yusuf):** Bölüm 10'daki adımlar. Ölçülecekler:
   - gerçek kredi harcaması
   - `wav_24000` çıktısı
   - Türkçe telaffuz
   - önbellek isabeti
   - `eleven_v4` TTS uyumluluğu (opsiyonel)
   - Free plandaki ses slotu sayısı

   Sonuçlar bu plana işlenir.
3. **Faz 3 — Arayüz (yalnız Yusuf onaylarsa):** Bölüm 6. Ayrı branch, ayrı onay, 390×844 görsel kontrol.

---

## 10. Gerçek anahtarla duman testi (Faz 2) — adım adım

> Anahtarı **Yusuf kendi terminaline girer.** Ajan anahtarı görmez, istemez, yazmaz. Anahtar dosyaya ya da repoya kaydedilmez.

```bash
cd ~/Desktop/Projeler/sesver-elevenlabs

# 1) Anahtarı yalnız bu terminal oturumuna gir (ekrana ve shell geçmişine düşmez)
read -s ELEVENLABS_API_KEY && export ELEVENLABS_API_KEY

# 2) 0 kredi: kota + ses listesi (plan, kalan kredi, klon izni, ses slotu)
~/Desktop/Projeler/sesver/.venv/bin/python scripts/elevenlabs_smoke.py

# 3) ~50–100 kredi: 97 karakterlik Türkçe TTS (Hızlı) + önbellek kontrolü + gerçek harcama
~/Desktop/Projeler/sesver/.venv/bin/python scripts/elevenlabs_smoke.py --harca

# 4) (isteğe bağlı) Dengeli ve En İyi modelleri dene
~/Desktop/Projeler/sesver/.venv/bin/python scripts/elevenlabs_smoke.py --harca --kalite Dengeli
~/Desktop/Projeler/sesver/.venv/bin/python scripts/elevenlabs_smoke.py --harca --kalite "En İyi"

# 5) (isteğe bağlı) + ~180 kredi: 1 Voice Design çağrısı (kalıcı kaydetmez, slot harcamaz)
~/Desktop/Projeler/sesver/.venv/bin/python scripts/elevenlabs_smoke.py --harca --tasarim

# 6) (isteğe bağlı) v4'ün TTS uç noktasında çalışıp çalışmadığı
SESVER_ELEVENLABS_MODEL=eleven_v4 ~/Desktop/Projeler/sesver/.venv/bin/python scripts/elevenlabs_smoke.py --harca

# 7) Bitince anahtarı oturumdan sil
unset ELEVENLABS_API_KEY
```

**Beklenen çıktı:**
- "4) TTS: … 48000 Hz, 1 kanal …"
- "5) Önbellek: … cached=True (kredi 0.0)"
- "7) Gerçek harcama: N kredi"

**Hata durumunda** betik Türkçe hata sınıfını yazar ve `exit 2` ile çıkar:
- `AuthError` → anahtar yanlış
- `QuotaError` → kota yetmiyor
- `RateLimitError` → yoğunluk

Çıktıdaki sayılar (anahtar hariç) bu plana işlenmek üzere Haberci'ye iletilir. Üretilen WAV'lar `outputs/` altındadır; dinleyip Türkçe telaffuzu not edin.

**Not:** Betik klon (IVC) denemesi **yapmaz**. Kişisel ses yüklenmez.

---

## 11. Test sonucu (Faz 1)

```
~/Desktop/Projeler/sesver/.venv/bin/python -m unittest discover -s tests -v
Ran 118 tests … OK          (76 mevcut + 42 yeni; ağ yok, model yok, anahtar yok)
```

- `pytest` venv'de kurulu değil. Görev gereği paket kurulmadı; testler `unittest` biçiminde.
- `pytest` kurulursa aynı testler değişmeden koşar: `python -m pytest tests`.

---

## Açık Sorular

1. **"En İyi" modu `eleven_v3` mü kalsın, v4 mü olsun?** v4'ün TTS uç noktasında çalışıp çalışmadığı Faz 2'de görülecek.
2. **Kullanım ticari mi?** Sosyal medya, marka ya da gelir amaçlıysa ücretsiz plan uygun değil; Starter gerekir.
3. **SRT ve birleştirme:** Görevde geçiyor ama bugünkü SesVer'de böyle bir hat yok. Ayrı bir özellik olarak mı planlansın?
4. **Anahtar saklama:** Faz 3'te Keychain önerisi onaylanıyor mu?
5. **ElevenLabs'te duygu:** v3/v4 ses etiketleriyle duygu desteği Faz 3 kapsamına girsin mi?
6. **Hazır sesler:** SesVer'in sentetik hazır seslerini ElevenLabs'e taşımak (IVC, slot harcar) isteniyor mu? Öneri: hayır; ElevenLabs'in kendi sesleri ve Voice Design yeterli.
