# SesVer

HamaratLabs tarafından geliştirilmiştir.

**Ücretsiz, yerel ve açık kaynak Türkçe ses üretimi + ses klonlama.**

Metninizi yazın, isterseniz bir referans ses yükleyin, **Üret** düğmesine basın. Sonucu dinleyin ve WAV olarak indirin. Hesap, API anahtarı veya ücretli servis gerekmez.

[OpenBMB VoxCPM2](https://huggingface.co/openbmb/VoxCPM2) kullanır: 2 milyar parametre, Türkçe dahil 30 dil, 48 kHz ses çıktısı. Arayüz yalnız Türkçedir. Gradio arayüzü basittir; **altındaki model küçük/hafif değildir.** GPU zorunlu değildir; donanımınıza göre beklemeniz gerekebilir.

## Kurulum

**Python 3.10–3.12 kullanın; 3.11 önerilir** ve sisteminizde kurulu olmalı ([python.org/downloads](https://www.python.org/downloads/)). Python 3.13+ bu kurulum için önerilmez. Başlamadan önce en az **20 GB boş disk alanı** ayırın.

```bash
git clone https://github.com/hamarat52/sesver.git
cd sesver
```

Git kullanmıyorsanız GitHub'da **Code → Download ZIP** ile indirin, arşivi açın.

### Kolay yol: tek dosyaya çift tıklayın

- **macOS:** `baslat.command` dosyasına çift tıklayın (ilk seferinde "Bilinmeyen geliştirici" uyarısı çıkarsa sağ tık → Aç).
- **Windows:** `baslat.bat` dosyasına çift tıklayın.

İlk çalıştırmada ortam otomatik kurulur (birkaç dakika sürebilir, bağımlılıklar indirilir); sonraki her çalıştırmada doğrudan açılır. Terminal/komut penceresi açık kalmalı; kapatmak için pencerede **Ctrl+C**.

### Elle kurulum (isteğe bağlı, terminale aşinaysanız)

#### macOS / Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install --no-deps voxcpm==2.0.3
pip install -r requirements.txt
python app.py
```

`--no-deps`: `voxcpm` paketi varsayılan kurulumda `funasr`, `matplotlib`, `modelscope`, `datasets`, `spaces`, `argbind` gibi bu arayüzün **hiç kullanmadığı** (kodda hiçbir yerde import edilmeyen, yalnız `voxcpm`'in kendi eğitim/demo betiklerine ait) ağır paketleri de kurar — bunları atlamak kurulumu ~400 MB küçültür. `requirements.txt` yalnız gerçekten çalışması için gereken paketleri listeler.

#### Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --no-deps voxcpm==2.0.3
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

`py` komutu çalışmazsa (bazı Python / Microsoft Store kurulumlarında `py` başlatıcısı yoktur) ilk satırda `python -m venv .venv` kullanın.

Tarayıcıda **http://127.0.0.1:7860** adresini açın. Terminal açık kalmalı; durdurmak için **Ctrl+C** kullanın. Yeniden başlatırken kurulum komutlarını tekrarlamanız gerekmez, ortamı etkinleştirip `python app.py` çalıştırın.

Arayüz hemen açılır. Model, ilk **Üret** tıklamasında Hugging Face'den indirilip belleğe yüklenir; ilk sefer internet gerekir ve süre bağlantınıza bağlıdır. Sonraki kullanımlarda ağırlıklar önbellekten kullanılır. Model hazırken internet olmadan çalıştırmak için macOS/Linux'ta `HF_HUB_OFFLINE=1 python app.py`; PowerShell'de önce `$env:HF_HUB_OFFLINE="1"` ayarlayın.

**NVIDIA GPU:** PyTorch'un CUDA destekli kurulumunu [resmî kurulum seçicisinden](https://pytorch.org/get-started/locally/) işletim sisteminize göre yapın. CUDA'sız PyTorch kuruluysa NVIDIA GPU otomatik kullanılamaz. Model uygun cihazı CUDA → Apple MPS → CPU sırasıyla seçer. CUDA şart değildir.

## Kullanım

1. Örnek metni değiştirin. İlk denemede kısa bir cümle kullanın; istek başına en fazla **500 karakter** kabul edilir.
2. **Ses Kütüphanesi (açılış sekmesi):** Bir ses kartı seçin. **Hazır sesler** (Yaşlı Masalcı, Belgesel Anlatıcı, Heyecanlı Sunucu; tarifle tasarlanmış sentetik sesler, gerçek kişi değil) repoyla gelir ve silinemez; **Kopyala** ile düzenlenebilir bir kopyası **Seslerim**'e eklenir. ▶ **Örnek** 3 saniyelik örneği çalar. Kayıtlı bir sesle üretim **Devam kipinde** yapılır (sesin `ref.wav` + `ref.txt` dosyası modele verilir, tarif/duygu eklenmez) ve her üretimde aynı kişi konuşur. Kayıtlı seste bir duygu seçerseniz kip **Kontrollü Klon**'a geçer ve “Duygu seçmek sesin benzerliğini biraz azaltır” notu görünür. **Kalite:** Hızlı / Dengeli / En İyi (`inference_timesteps` 6 / 10 / 16).
3. **🎲 Rastgele ses** kartı eski düz üretimdir: referans yoktur, duygu seçici serbestçe kullanılır (metnin başına `(energetic)` gibi parantezli talimat eklenir). Sabit bir konuşmacı garantisi yoktur.
4. **Ses Oluştur → Seçimlerle tarif et:** Yaş, cinsiyet, ton, doku, hız… seçimleri kurallı bir birleştiriciyle (LLM yok) İngilizce bir tarife çevrilir; kelimeler `voice_design_map.json` içindedir. **Gelişmiş** alanında tarif görünür ve elle düzenlenebilir; parçaların üstüne gelince Türkçe karşılığı çıkar. Örnek cümle süresi kaydırıcıyla 4–20 sn arasında seçilir. **Sesleri Dene** aynı tarif ve cümleyle seed 11/22/33/44 ile 4 aday üretir (sırayla; ilk aday hazır olunca dinlenebilir). Birini seçip ad verin ve **Kaydet**'e basın; ses Seslerim'e eklenir.
5. **Ses Oluştur → Dosya yükle:** WAV/MP3/M4A, 8–20 sn. Dosya mono 16-bit WAV'a çevrilir, baştaki/sondaki sessizlik kırpılır, kırpılma ve düşük seviye için uyarı verilir; uzunsa aralık seçilir. Metin yerel Whisper ile çıkarılır, düzeltilebilir ve boş bırakılamaz. **İzin kutucuğu** işaretlenmeden kaydedilemez.
6. **Efektler:** Cızırtı, Lo-fi, Telefon, Telsiz, Oda/yankı, Megafon üretimden **sonra** numpy/scipy ile uygulanır (modele yazılmaz); ham ses değişmez, efektli kopya `-fx-….wav` olarak yazılır ve -16 LUFS / ≤ -1 dBTP'ye eşitlenir. Ayarlar kayıtlı bir sese ön ayar olarak kaydedilebilir.
7. **Klonlama sekmesi** önceki gibi çalışır: Yalnız kendi sesinizi veya açık izin aldığınız bir sesi yükleyin. Tek kişinin konuştuğu, müziksiz ve temiz **3–15 saniyelik WAV** önerilir; kabul edilen süre **1–30 saniye**. **Referans sesin metnini de girerseniz** ("devam kipi") model referansı gerçekten anlayarak devam eder ve klon kalitesi belirgin artar — **🎙️ Otomatik yazıya dök** düğmesiyle bunu Whisper'a otomatik yazdırabilir, gerekirse düzeltebilirsiniz. Boş bırakılırsa eski davranış (yalnız ses rengi kopyalama) geçerli olur. Burada da bir duygu seçebilirsiniz, ancak **duygu seçmek klonlanan sesin orijinaline benzerliğini azaltabilir** (ses kimliği ile stil arasında bilinen bir ödünleşim) — en sadık klon için "Nötr" bırakın.
8. **Üret** düğmesine basıp durum mesajını bekleyin. İstekler sırayla işlenir; tekrar tekrar basmayın.
9. Sesi dinleyin, **⬇ WAV indir** düğmesiyle dosyayı kaydedin. Dosyalar ayrıca `outputs/` klasöründedir.

**Kişisel sesler git'e girmez:** `voices/seslerim/` `.gitignore`'dadır; ayrıca `voice_library.py` gerçek kişi klonu adlarını (`PROTECTED_NAMES`) ya da “yüklendi” kaynağını taşıyan hiçbir sesi `voices/hazir/` altına yazmaz.

Telaffuz, ses benzerliği ve kalite değişebilir. Uzun metni cümlelere bölün; kısaltmaları okunuşuyla yazmak yardımcı olabilir. Bu sürümde ek gürültü temizleme modeli yüklenmez; temiz referans kullanın.

## Donanım ve gerçekçi beklenti

**16 GB+ RAM önerilir. M1'de gerçek zamanlı değildir.** RTF, üretim süresinin ses uzunluğuna oranıdır: RTF 8, 10 saniyelik ses için yaklaşık 80 saniye beklemek demektir.

| Donanım / kaynak | Beklenti |
| --- | --- |
| Apple Silicon M1, 16 GB RAM | Yaklaşık 9 GB model belleği; önceki kullanıcı testinde RTF ~7–8, 10 saniye ses ~70–80 saniye. Yusuf'un M1 iMac 16 GB sisteminde çalıştırılmıştır. |
| 8 GB RAM | Bellek takasına düşebilir; RTF ~40–100 olabilir. Neredeyse kullanılamaz hale gelebilir; önerilmez. |
| NVIDIA RTX 4090 | Model kartında RTF ~0,3 raporlanır; bu depoda ölçülmüş bir sonuç değildir. Uyumlu CUDA kurulumu gerekir. |
| Yalnız CPU | Çalışabilir, fakat çok yavaştır. Süre işlemciye ve belleğe bağlıdır. |
| Model indirmesi | Yaklaşık 5 GB; ilk kullanımda internet gerekir. |
| Toplam disk bütçesi | Ortam, ağırlıklar ve paket önbellekleriyle ~17–19 GB'a çıkabilir; 20 GB+ boş alan ayırın. Ses çıktıları ayrıca yer kaplar. |

Bunlar garanti değil, planlama değerleridir. İlk model yüklemesi, referans işleme, diğer açık uygulamalar ve swap süreyi artırır. Tarayıcı sekmeleri, başka modeller ve ağır uygulamalarla aynı anda çalıştırmamak faydalıdır. İşlem bittikten sonra model, uygulamayı kapatana kadar RAM'de tutulur.

## Bu sürümün gerçek üretim testi

M1 iMac / 16 GB RAM / Python 3.11.1 üzerinde `python app.py` başlatılıp Gradio uç noktasından iki gerçek üretim yapıldı (VoxCPM 2.0.3, Gradio 6.30.0, PyTorch 2.14.1, MPS/float32):

| Test | Çıktı | Uçtan uca bekleme |
| --- | --- | --- |
| Referanssız | 48 kHz, 2,08 saniye | 205,9 saniye; ilk model yüklemesi dahil |
| Referanslı klonlama | 48 kHz, 2,72 saniye | 128,0 saniye; model bellekteyken |

Test metni: “Merhaba, bugün Türkçe ses üretimini deniyoruz.” Her iki WAV sessiz olmayan, sonlu örneklerden oluştu; kırpılma saptanmadı. Yerel Whisper small ile konuşma içeriği geri çözüldü (küçük yazım/bölütleme farklarıyla). Bu, insan dinlemesi veya ses benzerliği puanı değildir. Test sırasında sistemde yoğun swap kullanımı vardı; bu oturumun süreleri yukarıdaki önceki M1 ölçümünden belirgin şekilde kötüdür. **16 GB RAM tek başına hızlı çalışmayı garanti etmez.** Windows/Linux ve NVIDIA performansı bu sürümde ayrıca test edilmedi.

## Yerellik ve gizlilik

- Ses üretimi bilgisayarınızda yapılır; metin ve referans ses bulut servisine gönderilmez.
- Gradio analitiği ve Hugging Face telemetrisi kapalıdır. Sunucu yalnız `127.0.0.1` dinler, herkese açık paylaşım bağlantısı oluşturmaz.
- İlk model/paket indirmeleri için dış sunuculara bağlanılır. İlk kurulumdan sonra yukarıdaki çevrimdışı seçeneği kullanabilirsiniz.
- Üretilen dosyalar `outputs/` içinde, yüklemelerin/oynatmanın geçici kopyaları Gradio'nun yerel geçici klasöründe saklanabilir. Otomatik silinmez; hassas kayıtları işiniz bitince kendiniz temizleyin. Hugging Face model önbelleği genellikle `~/.cache/huggingface/hub` altındadır.
- Kişisel sesler ve model ağırlıkları Git'e dahil edilmez. Depo hiçbir hazır kişisel ses içermez.

## Lisans, atıf ve sorumlu kullanım

**SesVer'un kendi kodu (bu arayüz, `app.py`, testler) [PolyForm Noncommercial 1.0.0](LICENSE) lisanslıdır.** Kişisel kullanım, inceleme, eğitim, araştırma ve değiştirme serbesttir; **ticari kullanım ve yeniden satış izinli değildir** — SesVer'u indirip başka birine satamaz veya ticari bir ürüne/servise dahil edemezsiniz. Ticari kullanım için lisans sahibinden ayrıca izin gerekir.

Bu arayüz sıfırdan yazılmıştır ve yalnız bağımsız `voxcpm` paketini (pip) kullanır; VoiceStudio kodu veya bağımlılığı içermez. Sizin kendi bilgisayarınıza kurduğunuz **[VoxCPM2 modeli](https://huggingface.co/openbmb/VoxCPM2) ve [OpenBMB/VoxCPM](https://github.com/OpenBMB/VoxCPM) kodu ise ayrı bir bağımlılıktır ve kendi Apache-2.0 lisansı altındadır** (ticari kullanıma izin veren farklı bir lisans) — SesVer'un lisansı o bağımlılığı kısıtlamaz, sadece bu depodaki arayüz koduna uygulanır. OpenBMB ekibine teşekkürler.

### Sorumluluk reddi

Yazılım **"olduğu gibi", hiçbir garanti vermeden** sunulur. Lisans sahibi/katkıda bulunanlar, yazılımın kullanımından doğan hiçbir zarardan sorumlu değildir (LICENSE dosyasındaki "No Liability" maddesi). **Üretilen içerikten ve bu aracın nasıl kullanıldığından tamamen kullanıcı sorumludur.**

**Üretilen içeriği paylaşırken “AI ile üretildi” diye açıkça etiketlemek zorunludur.** Bu, model kartındaki kullanım uyarısıdır; uygulama sese otomatik bir filigran eklemez. Bu lisans başka kişilerin sesini izinsiz kullanma hakkı vermez. Sadece kendi sesinizi veya açık izin aldığınız bir sesi klonlayın; kimliğe bürünme, dolandırıcılık veya yanıltıcı/yasadışı içerik üretmek için kullanmayın. Bu araçla üretilen içerikle yapılan kimliğe bürünme, dolandırıcılık veya herhangi bir yasadışı eylemden tamamen kullanıcı sorumludur; proje sahibi/katkıda bulunanlar sorumlu tutulamaz.

## Sorun giderme ve katkı

- **İlk üretim uzun sürüyor:** Model indirme/yükleme aşamasını terminalden izleyin. M1'de üretim de zaman alır.
- **Bellek hatası / sistem yavaşladı:** Uygulamayı durdurun, diğer ağır uygulamaları kapatın ve daha kısa metinle yeniden başlatın. 8 GB cihazlarda kullanım önerilmez.
- **Referans okunmuyor:** 1–30 saniyelik geçerli bir WAV dosyası deneyin.
- **7860 portu kullanımda:** Daha önce açtığınız SesVer terminalini Ctrl+C ile kapatın.

Hata ve öneriler için [issue açabilirsiniz](https://github.com/hamarat52/sesver/issues). İşletim sistemi, Python sürümü, donanım ve kişisel bilgilerden arındırılmış hata mesajı yeterlidir; özel ses kayıtlarınızı paylaşmayın. Küçük, odaklı katkılar kabul edilir.

Model indirmeden birim testleri çalıştırmak için:

```bash
python -m unittest discover -s tests -v
```

Testler pahalı model çağrısını taklit eder; gerçek WAV yazımı, referans parametresi, giriş doğrulaması, hata durumu ve arayüz bağlantılarını sınar. Gerçek ses kalitesini birim testleri doğrulamaz.
