# Kabul Testi Sonuçları — Ses Kütüphanesi + Seçimli Ses Tasarımcısı

Tarih: 2026-10-17 · Model: VoxCPM2 (yerel, MPS, float32) · Birim testler: 73/73 OK

Kanıt kök dizini: `outputs/acceptance/` (`outputs/` git'te yok sayılır; kanıtlar commit'e girmez).
Ham sonuç dosyası: `outputs/acceptance/results2.json`. Bu dosyadaki yollar ilk çalıştırma yerini
(`~/.hermes/profiles/webdev/cache/scratch/acc/...`) gösterir; aynı dosyaların kopyaları aşağıdaki
`outputs/acceptance/...` yollarındadır.

Testler gerçek modelle, uygulamanın kendi fonksiyonları üzerinden yürütüldü:
`app.design_candidates`, `save_designed_ui`, `library_generate`, `generate_audio`, `_mode_info`.
Kütüphane klasörü test için geçici bir dizine yönlendirildi; kullanıcının `voices/seslerim/`
klasörüne yazılmadı.

| # | Test | Sonuç | Kanıt |
|---|------|-------|-------|
| 1 | 3 hazır ses, örnek dinleme, aynı metinle 2 üretimde kimlik aynı | GEÇTİ (vekil ölçüyle) — kulak onayı bekliyor | `kabul1_mfcc.txt`, `out/ai-ile-uretildi-f93cf406….wav`, `out/ai-ile-uretildi-0bf5e876….wav`, `screens/lib-desktop.png`, `screens/lib-mobile.png` |
| 2 | Birleştirici: iki örnek birebir, a/an, his/her, fazla virgül yok | GEÇTİ | `tests/test_designer.py` (4 test), `unittest.txt` |
| 3 | 4 aday → kaydet → ref.wav/ref.txt/ses.json → sonraki üretim Devam kipinde, logda tarif/duygu yok | GEÇTİ (gerçek model) | `results2.json` → `kabul3`, `qa-tasarim-sesi/`, `out/` (aşağıda), `acceptance2.log` |
| 4 | Kayıtlı ses + duygu → uyarı + Kontrollü Klon | GEÇTİ (gerçek model) | `results2.json` → `kabul4`, `out/ai-ile-uretildi-4973a230….wav`, `acceptance2.log` |
| 5 | Dosya yükleme: Whisper metni çıkarıyor; izin yoksa kayıt yok | GEÇTİ | `tests/test_modes.py::test_upload_save_requires_consent_and_text`, `test_upload_transcribe_reports_speech_ratio`, `screens/m-upload.png`, `results2.json` → `whisper` |
| 6 | Efektler aç/kapa, yoğunluk duyulur fark, ham ses bozulmuyor | GEÇTİ | `results2.json` → `kabul6`, `fx/fx-*-90.wav`, `out/…-fx-5d2810.wav` |
| 7 | Yeniden başlatınca "Seslerim" korunuyor | GEÇTİ | `kabul7_check.txt`, `tests/test_library.py::test_voices_persist_across_restart` |
| + | Seed tekrarlanabilirliği (plan §9.1) | GEÇTİ — bit düzeyinde aynı | `results2.json` → `seed`, `out/ai-ile-uretildi-e5605960….wav` ile `out/ai-ile-uretildi-2e2fa7dd….wav` |

## Ayrıntılar

### 1 — Ses kimliği (önceki oturum, 22:41–22:44)
- Yaşlı Masalcı ile aynı metin iki kez Devam kipinde üretildi. Her çıktı 4,0 sn, 48 kHz. İki çıktı bit düzeyinde aynı değil, yani gerçekten iki ayrı üretim yapıldı.
- MFCC ortalama kosinüs benzerlikleri:
  - üretim 1 ↔ üretim 2: 0,979
  - üretim 1 ↔ Masalcı referansı: 0,955; üretim 2 ↔ Masalcı referansı: 0,969
  - Karşılaştırma için: üretim 1 ↔ Belgesel referansı 0,736; ↔ Heyecanlı referansı −0,05
- **Sınır:** Bu ölçü ECAPA değil. `speechbrain` kurulu değil, yeni model indirmek de yasak. Kulak testi yapılmadı. Spesifikasyondaki "kulakla aynı kişi" koşulu için iki dosyanın dinlenmesi gerekiyor.
- Hazır seslerin listelenmesi ve ▶ örnek dinleme tarayıcıda doğrulandı (ekran görüntüleri `screens/`).

### 3 — Aday üretimi → kaydetme → Devam kipi (bu oturum, 23:44–23:49)
- Masalcı şablonundan kurulan tarif: `an elderly male storyteller, deep, warm, husky, slow`.
- 4 aday üretildi (seed 11/22/33/44, kalite "Hızlı"). Adaylar sırayla geldi: ilki 143 sn'de, dördü birden 233 sn'de hazırdı. Bu süreye modelin ilk yüklenmesi (~80 sn) dahil.
  - Dosyalar: 11 → `e5605960…`, 22 → `0dbc4fa4…`, 33 → `014473ad…`, 44 → `401379d9…` (hepsi `out/` altında)
  - Süreler: 5,44 / 8,32 / 6,88 / 4,96 sn
  - Aday 11 ile aday 22 arasındaki MFCC benzerliği 0,63. Farklı seed'ler gerçekten farklı sesler üretiyor.
- Seed 22 seçilip "QA Tasarım Sesi" adıyla kaydedildi. Oluşan dosyalar: `ref.wav`, `ref.txt`, `ses.json`, `ornek.wav` (`qa-tasarim-sesi/`).
  - `ses.json` içinde tarif, `seed: 22`, `secimler` ve kaynak alanları doğru.
  - `ref.txt` örnek cümleyle birebir aynı.
- Tasarım isteklerinin logu, adayların her biri için: `kip=tasarim … parametreler=cfg_value,inference_timesteps,text tarif=var`
- Kaydedilen sesle yapılan sonraki üretimin logu: `kip=devam ses=qa-tasarim-sesi parametreler=cfg_value,inference_timesteps,prompt_text,prompt_wav_path,reference_wav_path,text tarif=yok`
  - Tarif ve duygu yok. Çıktı: `out/ai-ile-uretildi-4ebd3485….wav` (82 sn sürdü).
  - Çıktının ref.wav ile MFCC benzerliği 0,797.
  - Whisper metni doğru çıkardı: "Bugün size çok eski bir hikâye anlatacağım. Hazırsanız başlayalım."
- **Not:** Örnek cümle olarak 4 sn'lik kısa masal metni kullanıldı (`sample_text("masal", 4)`). Spesifikasyonda bu 10–15 sn, uygulamanın varsayılanında 8 sn. Bellek riski yüzünden bilerek kısa tutuldu; ölçülen davranış metin uzunluğundan bağımsız.

### 4 — Duygu → Kontrollü Klon (bu oturum, 23:50–23:52)
- Yaşlı Masalcı + "Heyecanlı" ile üretim yapıldı. Ekrandaki not: "**Yaşlı Masalcı** · Kontrollü Klon kipi (`excited`). ⚠️ Duygu seçmek sesin benzerliğini biraz azaltır. En sadık sonuç için “Nötr” kalsın."
- İstek logu: `kip=kontrollu_klon ses=masalci parametreler=cfg_value,inference_timesteps,reference_wav_path,text tarif=var`. `prompt_wav_path` ve `prompt_text` yok, yani istek Devam kipinden çıktı.
- Çıktının Masalcı referansıyla MFCC benzerliği 0,938. Kimlik büyük ölçüde korunuyor.

### Seed tekrarlanabilirliği (bu oturum, 23:49)
- Aynı tarif, aynı örnek cümle, seed 11 ve 6 adımla yeniden üretim yapıldı (aday 11'in yeniden üretimi).
- İki çıktı da 261 120 örnek uzunluğunda. `np.array_equal` sonucu True, en büyük fark 0,0, korelasyon 1,0. Bu makinede MPS'te sonuç **bit düzeyinde aynı**.
- Plan §9.1'deki "MPS'te garanti değil" riski bu ölçümde ortaya çıkmadı. Farklı donanımda ya da farklı torch sürümünde yine sapma olabilir. Kayıtlı sesler `ref.wav` ile çalıştığı için bundan etkilenmez.

### 5 — Dosya yükleme
- Önceki oturumda tarayıcıda denendi: M4A yüklendi, Whisper metni doğru çıkardı, izin kutucuğu işaretlendi, ses kaydedildi ve Kütüphane'ye geçildi (`screens/m-upload.png`).
- İzin işaretlenmeden Kaydet pasif kalıyor. Sunucu tarafındaki kontrol `test_upload_save_requires_consent_and_text` ile doğrulandı.
- Bu oturumda yerel faster-whisper üç üretim çıktısının metnini doğru çıkardı (`results2.json` → `whisper`).

### 6 — Efektler
- Ham sesin md5'i değişmedi.
- Altı efektin hepsinde %20 ve %90 çıkışları −16 LUFS civarında; %90'da tepe ≤ −1 dBTP.
- %20 ile %90 arasındaki RMS farkı efekte göre 0,030–0,128.
- Arayüzdeki "Telsiz %70" ayarı ayrı bir `-fx-` dosyası üretti: "Efekt uygulandı: Telsiz %70. Seviye -16.0 LUFS, tepe -1.6 dBTP. Ham ses ayrıca korunuyor."

### 7 — Kalıcılık
- 3. testte kaydedilen ses, o süreç kapandıktan sonra yeni bir Python sürecinde `voice_library.list_voices()` ile listelendi (`kabul7_check.txt`: `qa-tasarim-sesi | hazir= False`).
- Önceki oturumda ayrıca sunucu yeniden başlatılarak tarayıcıda da doğrulandı.

## Kaynak durumu ve koşullar
- Bu oturumda ayrı bir VoxCPM2 süreci açıktı: VideoGen / voicestudio-test, port 3900, PID 26235/26835. Bu sürece dokunulmadı; test, onun üretimi bittikten sonra başladı.
- Swap kullanımı yüksekti (20 GB'ın ~19,8 GB'ı), ama sistemde boş bellek %30–34 düzeyindeydi. Üretim hızı ~1,7–1,9 adım/sn ile normal seyretti. Önceki oturumdaki gibi adım başına 80 sn'lik yavaşlama olmadı, bekleme ya da yeniden deneme gerekmedi.

## Açık kalan
- Test 1 için kulak onayı: `out/ai-ile-uretildi-f93cf406….wav` ve `out/ai-ile-uretildi-0bf5e876….wav` dinlenip aynı kişi olduğu onaylanmalı. ECAPA ölçümü yapılmadı (model indirme izni yok).

## Betikler
`outputs/acceptance/scripts/`: `acceptance.py` (test 1 ve 6, ilk tur), `acceptance2.py` (3, seed, 4, whisper), `acc_mfcc.py`, `kabul7_check.py`, `wait_and_run.sh`.
