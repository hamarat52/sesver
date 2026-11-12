"""SesVer — yerel VoxCPM2 ses üretimi."""
import os

# Üçüncü taraf modüller yüklenmeden önce telemetriyi kapat.
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import functools
import json
import logging
import random
from html import escape
from pathlib import Path
from queue import Queue
from threading import Event, Lock, Thread
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid4

import gradio as gr
import numpy as np
import soundfile as sf

import audio_prep
import effects as fx
import guncelleme
import hata_raporu
import hizlandirma as hiz
import i18n
import ice_aktarma
import kuyruk as kq
import kuyruk_arayuz as qa
import surum
import voice_designer as vdes
import voice_library as vlib
from engines import ema as ema_motor  # Hızlı Mod; içe aktarmak torch/ema_lightning yüklemez
from i18n import t, tr_message

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
MODEL_ID = "openbmb/VoxCPM2"
# Sabit model revizyonları (Hugging Face commit SHA'sı; 2026-11-08'de deponun main'i ile
# aynı olduğu doğrulandı). Depo sonradan güncellense de kullanıcılar aynı ağırlıkları alır;
# commit SHA'sı verildiğinde önbellekte o revizyon varsa dosyalar yeniden indirilmez.
# Değiştirmek bilinçli bir sürüm işidir (yeni SHA + gerçek üretim testi).
MODEL_REVISION = "32279effe8c19989596f05d353d1447f51d9e915"
WHISPER_MODEL = "small"  # faster-whisper bunu Systran/faster-whisper-small deposuna çevirir
WHISPER_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
_model = None
_model_lock = Lock()
log = logging.getLogger("sesver")

# --- Duygu/ton seçici -------------------------------------------------------
# VoxCPM2'nin stil talimatı ayrı bir API parametresi değildir; metnin başına
# "(energetic)" gibi parantezli bir talimat eklenerek verilir (resmi demo ile
# aynı sözleşme — İngilizce anahtar kelime, Türkçe buton etiketi).
EMOTIONS = {
    "Nötr": None,
    "Sakin": "calm",
    "Enerjik": "energetic",
    "Neşeli": "cheerful",
    "Ciddi": "serious",
    "Heyecanlı": "excited",
    "Üzgün": "sad",
}


def _preview_text(text, emotion_label):
    instruction = EMOTIONS.get(emotion_label)
    text = (text or "").strip()
    if not instruction or not text:
        return text or t("(metin boş)")
    return f"({instruction}){text}"


def _in_lang(fn, lang):
    """Olay işleyicisini sabit bir arayüz dilinde çalıştırır (sayfa açılışındaki yarışa karşı)."""
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        with i18n.use(lang):
            return fn(*args, **kwargs)
    return inner


def _choices(options):
    """Seçenek etiketi arayüz dilinde, değeri Türkçe anahtar (iş mantığı dilden bağımsız kalır)."""
    return [(t(k), k) for k in options]


# --- Üretim -------------------------------------------------------------


_gpu_disabled = False  # True: bu oturumda CUDA hatası yaşandı, bir daha denenmez (sonsuz döngü yok)


_model_yukleme_kilidi = Lock()  # iki istek (ör. durdurulan + yeni) modeli aynı anda iki kez yüklemesin
# Modelin bir kez indirilen boyutu (model.safetensors 4,58 GB + audiovae.pth 0,38 GB + küçük dosyalar).
MODEL_BOYUT_GB = 5
# Önbellekte bu dosyaların hepsi varsa model "diskte" sayılır (yalnız belleğe yüklenir, indirilmez).
_MODEL_DOSYALARI = ("config.json", "model.safetensors", "audiovae.pth")


def get_model(ilerleme=None):
    """Yalnız üretim kilidi içinden çağrılır; arayüz açılırken model yüklenmez.

    ``_gpu_disabled`` True ise (bu oturumda daha önce bir CUDA çalışma zamanı hatası:
    "no kernel image", CUDA OOM) model doğrudan CPU'da yüklenir: aynı oturumda
    ekran kartı bir daha denenmez (bkz. ``_reload_model_cpu``).
    ``ilerleme(bayt, toplam)``: model indirilirken bayt ilerlemesi (bkz. ``_model_yolu``).
    """
    global _model
    with _model_yukleme_kilidi:
        if _model is None:
            from voxcpm import VoxCPM
            _model = VoxCPM.from_pretrained(
                hf_model_id=_model_yolu(ilerleme), load_denoiser=False, optimize=False,
                device="cpu" if _gpu_disabled else None,
            )
    return _model


def _model_yolu(ilerleme=None):
    """VoxCPM2'nin sabit revizyonunun yerel klasörü (gerekirse bir kez indirilir).

    voxcpm 2.0.3 ``from_pretrained`` revizyon almaz; klasör yolu verilince indirmeyi
    atlayıp doğrudan onu yükler. ``HF_HUB_OFFLINE=1`` iken yalnız önbellek kullanılır.
    ``ilerleme`` verilirse indirme baytları ona bildirilir; kütüphanenin ham ilerleme
    satırı ("0/0 B | 0/0 B") hiçbir yere yazılmaz (bkz. ``_indirme_izleyici``).
    """
    from huggingface_hub import snapshot_download
    if ilerleme is None:
        return snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION)
    return snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION, tqdm_class=_indirme_izleyici(ilerleme))


def _indirme_izleyici(ilerleme):
    """snapshot_download'a verilen sessiz tqdm sınıfı: bayt çubuklarının (n, toplam) değerini
    ``ilerleme``ye iletir, ekrana/terminale hiçbir şey yazmaz. Hata ilerlemeyi bozar ama
    indirmeyi asla durdurmaz."""
    from tqdm.auto import tqdm

    class _Sessiz:
        def write(self, _metin):
            pass

        def flush(self):
            pass

    class _Izleyici(tqdm):
        def __init__(self, *args, **kwargs):
            kwargs.pop("name", None)  # huggingface_hub'ın kendi tqdm'ine özgü
            kwargs["disable"] = False
            kwargs["file"] = _Sessiz()
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            sonuc = super().update(n)
            if self.unit == "B":
                try:
                    ilerleme(int(self.n or 0), int(self.total or 0))
                except Exception:  # noqa: BLE001 — ilerleme gösterimi indirmeyi durdurmaz
                    pass
            return sonuc

    return _Izleyici


def _model_diskte():
    """Sabit revizyonun dosyaları Hugging Face önbelleğinde tam mı? Bilinemiyorsa None."""
    try:
        from huggingface_hub import try_to_load_from_cache
        return all(isinstance(try_to_load_from_cache(MODEL_ID, ad, revision=MODEL_REVISION), str)
                   for ad in _MODEL_DOSYALARI)
    except Exception:  # noqa: BLE001 — önbellek okunamıyorsa "bilinmiyor"
        return None


def _model_durumu():
    """Model durumu: "bellekte" (yüklü), "diskte" (önbellekte, yalnız yüklenecek) ya da "yok" (bir kez inecek).

    Önbellek okunamazsa "diskte" sayılır: kullanıcıya yanlışlıkla "indiriliyor" denmez; gerçekten
    indirme başlarsa ilerleme iletisi bunu ayrıca gösterir (bkz. ``_modeli_hazirla``)."""
    if _model is not None:
        return "bellekte"
    return "yok" if _model_diskte() is False else "diskte"


def _indirme_metni(bayt, toplam, lang=None):
    return t("Ses modeli indiriliyor: {done} / {total} GB (%{pct}). Bu yalnız bir kez olur.", lang,
             done=f"{bayt / 1e9:.2f}", total=f"{toplam / 1e9:.2f}", pct=int(bayt * 100 / toplam) if toplam else 0)


def _modeli_hazirla(progress):
    """Model kilidi içinden çağrılır (``yield from``): modeli yükler/indirir, indirme sürerken
    durum satırına anlamlı ilerleme verir ve modeli döndürür.

    Yükleme ayrı bir iş parçacığında yapılır; bu üreteç saniyede bir indirilen baytı yazar.
    Arayüz dili iş parçacığına geçmediği için metinler bu üreteçte ya da sabit dille kurulur."""
    if _model is not None:
        return get_model()
    lang = i18n.get_lang()
    son = {"bayt": 0, "toplam": 0}

    def ilerleme(bayt, toplam):
        if toplam != son["toplam"]:
            son.update(bayt=bayt, toplam=toplam)
        else:
            son["bayt"] = max(son["bayt"], bayt)
        if son["toplam"]:
            progress(0.05 + 0.13 * min(1.0, son["bayt"] / son["toplam"]),
                     desc=_indirme_metni(son["bayt"], son["toplam"], lang))

    kutu, bitti = {}, Event()

    def calis():
        try:
            kutu["model"] = get_model(ilerleme=ilerleme)
        except BaseException as exc:  # noqa: BLE001 — hata üretim akışına taşınır
            kutu["hata"] = exc
        finally:
            bitti.set()

    Thread(target=calis, name="sesver-model-yukleme", daemon=True).start()
    gosterilen = None
    while not bitti.wait(1.0):
        if son["toplam"] and son["bayt"] < son["toplam"]:
            metin = _indirme_metni(son["bayt"], son["toplam"], lang)
            if metin != gosterilen:
                gosterilen = metin
                yield None, None, metin
    if "hata" in kutu:
        raise kutu["hata"]
    return kutu["model"]


def _reload_model_cpu():
    """Ekran kartı çalışma anında patladığında (ör. Blackwell + cu126, CUDA OOM) tek seferlik
    CPU'ya düşüş: modeli boşaltır, ``_gpu_disabled``'ı işaretler ve CPU'da yeniden yükler.

    VoxCPM ``device=\"cpu\"`` parametresini doğrudan kabul eder (bkz. voxcpm/core.py
    ``resolve_runtime_device``); ``CUDA_VISIBLE_DEVICES`` gibi süreç çapında bir ortam
    değişkenine gerek yoktur ve zaten bu süreçte torch zaten CUDA ile başlatıldığı için
    işe yaramaz.
    """
    global _model, _gpu_disabled
    _gpu_disabled = True
    _model = None
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001 — bellek temizliği başarısız olsa da yeniden yükleme dener
        pass
    return get_model()


_whisper_model = None
_whisper_lock = Lock()


def _get_whisper():
    """Whisper'ı yalnız "Otomatik yazıya dök" tıklanınca yükler (küçük/int8/CPU)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8",
                                      revision=WHISPER_REVISION)
    return _whisper_model


def _whisper_language():
    """Türkçe arayüzde Türkçe zorlanır (eski davranış); diğer arayüz dillerinde
    Whisper kaydın dilini kendisi algılar (VoxCPM2 çok dilli olduğu için kayıt
    Türkçe olmak zorunda değildir)."""
    return "tr" if i18n.get_lang() == i18n.DEFAULT else None


def auto_transcribe(reference_audio):
    if not reference_audio:
        raise gr.Error(t("Önce bir referans ses yükleyin."))
    try:
        with _whisper_lock:
            model = _get_whisper()
            segments, _info = model.transcribe(reference_audio, language=_whisper_language())
            text = " ".join(s.text.strip() for s in segments).strip()
    except Exception:
        import traceback
        traceback.print_exc()
        raise gr.Error(t("Otomatik yazıya dökme başarısız; metni elle yazabilirsiniz."))
    if not text:
        raise gr.Error(t("Ses anlaşılamadı; metni elle yazın."))
    return text


def transcribe_with_info(path):
    """auto_transcribe ile aynı model/kilit; VAD ile konuşma oranını da döndürür.

    VAD modeli faster-whisper'ın içinde gömülü gelir (yeni indirme yok).
    """
    with _whisper_lock:
        model = _get_whisper()
        segments, info = model.transcribe(path, language=_whisper_language(), vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
    duration = float(getattr(info, "duration", 0) or 0)
    after = float(getattr(info, "duration_after_vad", duration) or 0)
    return text, (after / duration if duration else 0.0)


def _seed_everything(seed):
    """VoxCPM generate() seed almaz; rastgelelik torch.randn'den gelir."""
    import torch
    seed = int(seed)
    random.seed(seed)
    np.random.seed(seed % (2 ** 32))
    torch.manual_seed(seed)


def _build_kwargs(text, reference_audio, instruction, prompt_text, timesteps, voice_id=None, log_mode=None):
    """Üç kipin generate() parametrelerini tek yerde kurar ve tek satır loglar.

    Log yalnız kip/ses kimliği/parametre adlarını içerir; metin ve ses içeriği
    yazılmaz (gizlilik).
    """
    final_text = f"({instruction}){text}" if instruction else text
    kwargs = dict(text=final_text, cfg_value=2.0, inference_timesteps=int(timesteps))
    if prompt_text:
        # Devam kipi: model referansın GERÇEK içeriğini bilerek devam eder.
        # reference_wav_path ile birlikte verilince sonuç daha da sağlam olur.
        kwargs["prompt_wav_path"] = reference_audio
        kwargs["prompt_text"] = prompt_text
        kwargs["reference_wav_path"] = reference_audio
        mode = "devam+stil" if instruction else "devam"
    else:
        kwargs["reference_wav_path"] = reference_audio or None
        mode = ("kontrollu_klon" if instruction else "klon") if reference_audio else "referanssiz"
    mode = log_mode or mode
    names = ",".join(sorted(k for k, v in kwargs.items() if v is not None))
    log.info("istek kip=%s ses=%s parametreler=%s tarif=%s", mode, voice_id or "-", names,
             "var" if instruction else "yok")
    return mode, kwargs


def generate_audio(text, reference_audio, instruction=None, prompt_text=None, progress=gr.Progress(),
                   seed=None, timesteps=10, voice_id=None, log_mode=None):
    """Durumu hemen göster; aynı modelde üretimleri sıraya koy.

    prompt_text verilmişse VoxCPM2'nin "devam kipi" kullanılır: model referans
    sesin gerçek içeriğini bilerek devam eder, yalnız izole klonlamadan (ses
    rengini kopyalama) çok daha sadık bir taklit üretir. prompt_text yoksa
    (varsayılan) eski izole klonlama davranışı değişmeden kalır.

    progress: tahmini süreye göre 0.2→0.93 arası yumuşakça ilerleyen bir arka
    plan iş parçacığıyla beslenir (gerçek tqdm adımlarını değil, temiz Türkçe
    açıklamalı bir tahmini ilerleme gösterir — ham kütüphane çıktısı sızmaz).
    """
    # Eski çıktı, yeni istek başarısız olsa bile yeni ses sanılmasın.
    progress(0, desc=t("İstek kontrol ediliyor…"))
    yield None, None, t("İstek kontrol ediliyor…")
    blocked = _accel_block_reason()
    if blocked:
        # Ayarlar'dan PyTorch değişiyor/değişti: yarım ya da eski kurulumla model yüklenmesin.
        raise gr.Error(blocked)
    text = (text or "").strip()
    prompt_text = (prompt_text or "").strip() or None
    if not text:
        raise gr.Error(t("Lütfen okunacak bir metin yazın."))
    if len(text) > 500:
        raise gr.Error(t("İlk sürümde en fazla 500 karakter kullanın; uzun metni bölün."))
    if prompt_text and not reference_audio:
        raise gr.Error(t("Referans metni yalnız bir referans ses yüklendiğinde kullanılabilir."))
    if reference_audio:
        try:
            info = sf.info(reference_audio)
            if not 1 <= info.duration <= 30:
                raise ValueError("Süre 1–30 saniye olmalı.")
        except (OSError, RuntimeError, ValueError) as exc:
            raise gr.Error(t("Referans ses okunamadı. 1–30 saniyelik geçerli bir WAV yükleyin.")) from exc
    started = perf_counter()
    # Metin, tarif ve referans metni bundan sonra günlüğe (desktop._Tee) ve rapora hiç
    # yazılmaz: yalnız hata yolunda değil, kütüphane uyarısında da (bulgu 2).
    private = [text, prompt_text] + ([instruction] if instruction not in EMOTIONS.values() else [])
    hata_raporu.remember_private(*[v for v in private if v])
    # Model kilidinden ÖNCE ikinci ileti: kuyruk/elle üretim notu bu ilk iki iletiye eklenir
    # (_elle_oncelikli). İçerik modelin gerçek durumuna göre: önbellekte varsa "indiriliyor /
    # internet gerekir" denmez; yalnız gerçekten ilk kez inecekse boyutuyla söylenir.
    durum = _model_durumu()
    if durum == "yok":
        progress(0.05, desc=t("Ses modeli indiriliyor…"))
        yield None, None, t("İşleniyor… İlk kullanım: ses modeli bir kez indirilecek (yaklaşık {gb} GB, internet "
                            "gerekir). Sonraki açılışlarda yalnız yüklenir.", gb=MODEL_BOYUT_GB)
    elif durum == "diskte":
        progress(0.05, desc=t("Ses modeli yükleniyor…"))
        yield None, None, t("İşleniyor… Ses modeli belleğe yükleniyor. Model bilgisayarınızda kayıtlı; "
                            "indirme yapılmaz, birkaç dakika sürebilir.")
    else:
        progress(0.05, desc=t("İşleniyor…"))
        yield None, None, t("İşleniyor…")
    try:
        with _model_lock:
            model = yield from _modeli_hazirla(progress)
            # Kaba tahmin: karakter başına ~3-6 sn; uzun metin ve aynı anda
            # çalışan başka ağır uygulamalar süreyi belirgin artırabilir.
            est_min = max(1, round(len(text) * 3 / 60))
            est_max = max(est_min + 1, round(len(text) * 6 / 60))
            progress(0.2, desc=t("Ses üretiliyor…"))
            yield None, None, t(
                "Ses üretiliyor… Metninizin uzunluğuna göre tahmini {min}-{max} dakika "
                "sürebilir (başka ağır uygulamalar açıksa daha uzun sürer). "
                "**Pencereyi kapatmayın, bu normal**; bittiğinde burada 'Tamamlandı' yazacak.",
                min=est_min, max=est_max,
            )
            _mode, generate_kwargs = _build_kwargs(text, reference_audio, instruction, prompt_text, timesteps,
                                                   voice_id=voice_id, log_mode=log_mode)
            if seed is not None:
                # "Aynı tarif + aynı seed = aynı ses" için üretimden hemen önce.
                _seed_everything(seed)
            # Model.generate() tek bloklayıcı çağrı; gerçek adım bilgisi vermez.
            # Tahmini sürenin ortasına göre yumuşakça 0.2→0.93 arası ilerleyen
            # bir arka plan iş parçacığı, ilerlemeyi donuk göstermez.
            stop_ticking = Event()

            ticker_desc = t("Ses üretiliyor…")

            def _tick():
                est_seconds = max(10.0, (est_min + est_max) / 2 * 60)
                t0 = perf_counter()
                while not stop_ticking.wait(0.4):
                    frac = 0.2 + 0.73 * min(1.0, (perf_counter() - t0) / est_seconds)
                    progress(frac, desc=ticker_desc)

            ticker = Thread(target=_tick, daemon=True)
            ticker.start()
            try:
                try:
                    wav = model.generate(**generate_kwargs)
                except Exception as exc:
                    # "no kernel image"/CUDA OOM: torch.cuda.is_available() kuruluşta True
                    # dönmüş olabilir ama gerçek işlem burada patlar. Ekran kartı bu oturumda
                    # bir daha denenmez (_gpu_disabled); tek seferlik CPU'ya düşüş + tek bilgi.
                    code, _reason = hata_raporu.classify_error(exc)
                    if code not in ("cuda_kernel", "cuda_oom") or _gpu_disabled:
                        raise
                    log.warning("ekran kartı hatası (%s), bu oturumda CPU'ya tek seferlik geçiliyor: %s",
                                code, exc)
                    model = _reload_model_cpu()
                    fallback_msg = t("Ekran kartı bu sürümde kullanılamadı, işlemciyle devam ediliyor; "
                                    "daha yavaş. Ayrıntı: Ayarlar.")
                    progress(0.2, desc=fallback_msg)
                    yield None, None, fallback_msg
                    wav = model.generate(**generate_kwargs)
            finally:
                stop_ticking.set()
                ticker.join(timeout=2)
            progress(0.95, desc=t("Ses dosyası kaydediliyor…"))
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            output = str(OUTPUT_DIR / f"ai-ile-uretildi-{uuid4().hex}.wav")
            sf.write(output, wav, model.tts_model.sample_rate)
    except Exception as exc:
        # Ayrıntı (traceback) sesver_log.txt'ye yazılır; kullanıcının metni oradan ve hata
        # raporundan silinir (hata_raporu.record_error). Kullanıcıya hatanın türü söylenir.
        entry = hata_raporu.record_error(exc, redact=private, where=log_mode or "generate")
        yield None, None, t(
            "Üretim başarısız: **{neden}**. Diğer ağır uygulamaları kapatıp kısa bir metinle tekrar deneyin; "
            "bellek hatasında SesVer'i yeniden başlatın. Ayrıntı: sesver_log.txt. Sorun sürerse "
            "“Hata raporu gönder” düğmesiyle bize bildirin.", neden=escape(entry["reason"])
        )
        return
    progress(1.0, desc=t("Tamamlandı"))
    yield output, output, t("Tamamlandı: {sec} saniye. AI ile üretildi.", sec=f"{perf_counter() - started:.1f}")


def _normal_generate(text, emotion_label, progress=gr.Progress()):
    yield from generate_audio(text, None, EMOTIONS.get(emotion_label), progress=progress)


def _clone_generate(text, reference_audio, emotion_label, prompt_text, progress=gr.Progress()):
    yield from generate_audio(text, reference_audio, EMOTIONS.get(emotion_label), prompt_text, progress=progress)


def _elle_oncelikli(uretec):
    """Elle Üret'i kuyrukla paylaştırır (generate_audio'nun gövdesine dokunmadan sarar).

    - 500 karakter sınırı aynen geçerlidir; ileti uzun metin için “Kuyruğa ekle”yi gösterir.
    - Kuyruk çalışıyorsa elle üretim, kuyruğun şu anki PARÇASI bitince araya girer
      (Kuyruk.elle_uretim); bekleme sırasında durum satırı bunu söyler.
    """
    @functools.wraps(uretec)
    def inner(text, *args, **kwargs):
        if len((text or "").strip()) > kq.PARCA_EN_FAZLA:
            yield None, None, t("İstek kontrol ediliyor…")
            raise gr.Error(t("Üret en fazla 500 karakter alır. Daha uzun metni (10.000 karaktere kadar) "
                             "“Kuyruğa ekle” ile ekleyin; parçalara bölünüp tek ses dosyası olur."))
        kuyruk = _KUYRUK if _KUYRUK is not None and _KUYRUK.calisiyor else None
        if kuyruk is None:
            yield from uretec(text, *args, **kwargs)
            return
        not_ = t("Kuyruk çalışıyor: üretiminiz kuyruğun şu anki parçası bitince başlayacak, sonra kuyruk "
                 "kaldığı yerden sürecek.")
        with kuyruk.elle_uretim():
            # generate_audio'nun ilk iki iletisi model kilidinden ÖNCE gelir ("kontrol ediliyor",
            # "işleniyor"); bekleme bu ikincisinden sonra olur. Not yalnız bu ikisine eklenir.
            for i, out in enumerate(uretec(text, *args, **kwargs)):
                if i < 2 and isinstance(out, tuple) and len(out) == 3 and out[0] is None and out[2]:
                    out = (out[0], out[1], f"{out[2]}\n\n{not_}")
                yield out
    return inner


generate_audio = _elle_oncelikli(generate_audio)


# --- Ses kütüphanesi --------------------------------------------------------
RANDOM_VOICE = "rastgele"
QUALITY = {"Hızlı": 6, "Dengeli": 10, "En İyi": 16}  # inference_timesteps (Dengeli = eski varsayılan)
SIMILARITY_NOTE = "Duygu seçmek sesin benzerliğini biraz azaltır."
DESIGN_KAYNAK = "Tarifle tasarlandı (sentetik ses, gerçek kişi değil)"
_RANDOM_CARD = {
    "id": RANDOM_VOICE, "ad": "🎲 Rastgele ses", "kategori": "Referanssız", "hazir": True, "ornek": None,
    "aciklama": "Her üretimde yeni, kalıcı olmayan bir ses. Duygu seçici serbestçe kullanılır.",
}


def _voice_list():
    """Kartlar için hafif liste (gr.State içinde tutulur)."""
    return [{k: v[k] for k in ("id", "ad", "aciklama", "kategori", "hazir", "ornek")} for v in vlib.list_voices()]


def _voice_name(voice):
    """Hazır seslerin (ve Rastgele kartının) adı/açıklaması arayüz dilinde gösterilir;
    kullanıcının kendi seslerine dokunulmaz."""
    return t(voice["ad"]) if voice.get("hazir") or voice.get("id") == RANDOM_VOICE else voice["ad"]


def _mode_info(voice_id, emotion_label, text=""):
    """Seçili sese ve duyguya göre kipi ve modele gidecek metni açıklar."""
    instruction = EMOTIONS.get(emotion_label)
    if not voice_id or voice_id == RANDOM_VOICE:
        return t("**Rastgele ses** · Üretilecek: _{text}_", text=_preview_text(text, emotion_label))
    voice = vlib.get_voice(voice_id)
    if not voice:
        return t("Seçili ses bulunamadı; kütüphaneden yeniden seçin.")
    if instruction:
        return t("**{ad}** · Kontrollü Klon kipi (`{instruction}`). ⚠️ {note} En sadık sonuç için “Nötr” kalsın.",
                 ad=escape(_voice_name(voice)), instruction=instruction, note=t(SIMILARITY_NOTE))
    return t("**{ad}** · Devam kipi: kayıtlı sesin kendi kaydı ve metniyle sürdürülür; "
             "tarif ya da duygu eklenmez (en yüksek benzerlik).", ad=escape(_voice_name(voice)))


def library_generate(text, emotion_label, quality="Dengeli", voice_id=RANDOM_VOICE,
                     progress=gr.Progress()):
    """Kütüphanedeki seçili sesle üretim.

    Rastgele → referanssız (eski Normal Üretim); kayıtlı ses + Nötr → Devam;
    kayıtlı ses + duygu → Kontrollü Klon.
    """
    instruction = EMOTIONS.get(emotion_label)
    steps = QUALITY.get(quality, 10)
    voice_id = voice_id or RANDOM_VOICE
    if voice_id == RANDOM_VOICE:
        yield from generate_audio(text, None, instruction, progress=progress, timesteps=steps,
                                  voice_id=RANDOM_VOICE)
        return
    voice = vlib.get_voice(voice_id)
    if not voice:
        raise gr.Error(t("Seçili ses bulunamadı; kütüphaneden yeniden seçin."))
    if instruction:
        yield from generate_audio(text, voice["ref_wav"], instruction, None, progress=progress,
                                  timesteps=steps, voice_id=voice_id)
    else:
        yield from generate_audio(text, voice["ref_wav"], None, voice["ref_text"], progress=progress,
                                  timesteps=steps, voice_id=voice_id)


def _voice_error(exc):
    # voice_library/audio_prep iletileri Türkçe üretilir; burada arayüz diline çevrilir.
    return gr.Error(tr_message(str(exc)) or t("İşlem yapılamadı."))


def copy_voice_ui(voice_id):
    try:
        voice = vlib.copy_voice(voice_id)
    except (vlib.VoiceError, PermissionError) as exc:
        raise _voice_error(exc)
    return _voice_list(), voice["id"], t("Kopyalandı: **{ad}** artık Seslerim'de.", ad=escape(voice["ad"]))


def delete_voice_ui(voice_id, selected):
    try:
        vlib.delete_voice(voice_id)
    except vlib.VoiceError as exc:
        raise _voice_error(exc)
    new_selected = RANDOM_VOICE if selected == voice_id else selected
    return _voice_list(), new_selected, t("Ses silindi."), None, gr.update(visible=False)


# --- Efektler (üretim sonrası DSP) --------------------------------------------
_FX_KEYS = list(fx.EFFECTS)


def _fx_settings(*vals):
    """[açık, yoğunluk] * 6 + oda ön ayarı → ses.json biçimindeki liste."""
    room = vals[-1]
    out = []
    for i, key in enumerate(_FX_KEYS):
        if vals[2 * i]:
            entry = {"ad": key, "yogunluk": int(vals[2 * i + 1])}
            if key == "oda":
                entry["on_ayar"] = room
            out.append(entry)
    return fx.clean_settings(out)


def _fx_values(efektler):
    by_name = {e["ad"]: e for e in fx.clean_settings(efektler)}
    values = []
    for key in _FX_KEYS:
        values += [key in by_name, by_name.get(key, {}).get("yogunluk", 50)]
    values.append(by_name.get("oda", {}).get("on_ayar", "salon"))
    return values


def apply_effects_ui(raw_path, *vals):
    """Ham sesin kopyasına efekt zinciri; model yeniden çalışmaz."""
    settings = _fx_settings(*vals)
    if not raw_path:
        return None, None, t("Önce bir ses üretin; efektler üretilen sese uygulanır.")
    if not settings:
        return None, None, t("Efekt kapalı; ham ses olduğu gibi kullanılıyor.")
    audio, sr = sf.read(str(raw_path), dtype="float32", always_2d=True)
    out = fx.apply(audio.mean(axis=1), sr, settings)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(raw_path).stem.split("-fx-")[0]
    for old in OUTPUT_DIR.glob(f"{stem}-fx-*.wav"):
        old.unlink(missing_ok=True)
    path = OUTPUT_DIR / f"{stem}-fx-{uuid4().hex[:6]}.wav"
    sf.write(str(path), out, sr, subtype="PCM_16")
    names = ", ".join(f"{t(fx.EFFECTS[e['ad']])} %{e['yogunluk']}" for e in settings)
    return str(path), str(path), t(
        "Efekt uygulandı: {names}. Seviye {lufs} LUFS, tepe {peak} dBTP. Ham ses ayrıca korunuyor.",
        names=names, lufs=f"{fx.loudness_lufs(out, sr):.1f}", peak=f"{fx.true_peak_dbtp(out):.1f}",
    )


def save_fx_preset_ui(voice_id, *vals):
    if not voice_id or voice_id == RANDOM_VOICE:
        raise gr.Error(t("Ön ayar yalnız kayıtlı bir sese kaydedilebilir."))
    try:
        voice = vlib.update_effects(voice_id, _fx_settings(*vals))
    except vlib.VoiceError as exc:
        raise _voice_error(exc)
    return t("Efekt ön ayarı **{ad}** sesine kaydedildi.", ad=escape(voice["ad"]))


def select_voice_ui(voice_id, emotion_label, text):
    """Kart seçimi: kip açıklaması ve sesin efekt ön ayarı yüklenir."""
    voice = vlib.get_voice(voice_id) if voice_id != RANDOM_VOICE else None
    values = _fx_values(voice["varsayilan_efektler"] if voice else [])
    return [voice_id, _mode_info(voice_id, emotion_label, text)] + values


# --- Ses oluştur: seçimlerle tarif -------------------------------------------
_DMAP = vdes.load_map()
_SAMPLE_CATEGORIES = [(label, key) for key, label in _DMAP["kategori_etiketleri"].items()]
# Kısa referans (4-8 sn) devam kipinde kimlik kaymasına yol açıyor; varsayılan ve alt sınır buna göre.
_DEFAULT_SAMPLE_SECONDS = 14
_MIN_SAMPLE_SECONDS = 10
_MAX_SAMPLE_SECONDS = 20
_SHORT_SAMPLE_SECONDS = 8
_FRAGILE_TEXTURES = ("Nefesli", "Pürüzlü")
SHORT_SAMPLE_WARNING = ("Kısa örnek: bu sesle yapılan sonraki üretimlerde benzerlik düşebilir. "
                        "Daha uzun bir örnek cümleyle yeniden tasarlamanı öneririz.")
TEXTURE_WARNING = "Bu doku sonraki üretimlerde zayıflayabilir."


def _slider_labels(group):
    return list(_DMAP["gruplar"][group]["secenekler"])


def _slider_default(group):
    return _slider_labels(group).index(_DMAP["gruplar"][group]["varsayilan"]) + 1


def design_selections(cins, yas, kullanim, perde, ton, doku, hiz, enerji):
    """Arayüz değerlerini birleştiricinin beklediği sözlüğe çevirir (kaydırıcı 1'den başlar)."""
    def at(group, index):
        labels = _slider_labels(group)
        return labels[min(max(int(round(index or 1)) - 1, 0), len(labels) - 1)]

    return {"cinsiyet": cins, "yas": yas, "kullanim": kullanim, "perde": at("perde", perde), "ton": ton,
            "doku": list(doku or [])[:2], "hiz": at("hiz", hiz), "enerji": at("enerji", enerji)}


def rebuild_description_ui(cins, yas, kullanim, perde, ton, doku, hiz, enerji, manual, current):
    secimler = design_selections(cins, yas, kullanim, perde, ton, doku, hiz, enerji)
    tarif, parcalar, uyarilar = vdes.build_description(secimler, _DMAP)
    uyarilar = [tr_message(u) for u in uyarilar]
    if (doku or []) and len(doku) > 2:
        uyarilar.insert(0, t("Ses dokusu için en fazla 2 seçim kullanılır; ilk ikisi alındı."))
    warn = "  \n".join(f"⚠️ {escape(u)}" for u in uyarilar)
    head = (t('<p class="sv-fine"><b>Elle düzenlendi:</b> seçimler tarifin üzerine yazmıyor.</p>')
            if manual else "")
    # Rozet ipucu (fareyle üstüne gelince) seçimin arayüz dilindeki adını gösterir.
    parcalar = [(en, t(label)) for en, label in parcalar]
    return (current if manual else tarif), head + vdes.parts_html(parcalar), warn


def apply_template_ui(name, seconds):
    secimler, kategori = vdes.template(_DMAP, name)
    idx = {g: _slider_labels(g).index(secimler[g]) + 1 for g in ("perde", "hiz", "enerji")}
    kategori = kategori or "masal"
    return (secimler["cinsiyet"], secimler["yas"], secimler["kullanim"], idx["perde"], secimler["ton"],
            list(secimler["doku"]), idx["hiz"], idx["enerji"], kategori,
            vdes.sample_text(kategori, seconds, _DMAP), False)


def sample_estimate_md(text):
    sec = vdes.estimate_seconds(text, _DMAP)
    return t("Örnek ses ≈ **{sec} sn** (tahmini; okunacak metnin uzunluğundan hesaplanır).", sec=f"{sec:.0f}")


SEED_EN_FAZLA = 2 ** 32 - 1  # np.random.seed sınırı: aynı seed = aynı ses garantisi bu aralıkta geçerli


def seed_coz(deger):
    """Kullanıcının yazdığı seed → int (0..2^32-1); geçersizse None.

    Yalnız rakamlar kabul edilir (Arapça-Hint rakamları da): negatif, ondalıklı, boş ya da
    sınırı aşan değer reddedilir; sessizce yuvarlanmaz ya da mod alınmaz (aynı seed = aynı ses).
    """
    if isinstance(deger, bool):
        return None
    if isinstance(deger, int):
        sayi = deger
    else:
        metin = str(deger if deger is not None else "").strip()
        if not metin or not metin.isdecimal():
            return None
        sayi = int(metin)
    return sayi if 0 <= sayi <= SEED_EN_FAZLA else None


def _seed_hatasi(n):
    return gr.Error(t("Aday {n}: seed sıfır ya da pozitif bir tam sayı olmalı (en fazla {en_fazla}).",
                      n=n, en_fazla=SEED_EN_FAZLA))


def _aday_girdisi(tarif, text):
    tarif = (tarif or "").strip().strip("()").strip()
    text = (text or "").strip()
    if not tarif:
        raise gr.Error(t("Önce seçim yapın ya da Gelişmiş alanına bir tarif yazın."))
    if not text:
        raise gr.Error(t("Örnek cümle boş olamaz."))
    return tarif, text


def _aday_etiketi(n, seed, sec):
    return t("Aday {n} · seed {seed} · {sec} saniye", n=n, seed=seed, sec=f"{sec:.1f}")


def _aday_sesi(tarif, text, quality, seed, progress, sar):
    """Bir adayı üretir; generate_audio'nun ara iletilerini ``sar(ileti)`` ile verir.
    Döndürdüğü: (ses yolu ya da None, geçen saniye, son ileti)."""
    started = perf_counter()
    last = None
    for last in generate_audio(text, None, tarif, progress=progress, seed=seed,
                               timesteps=QUALITY.get(quality, 10), voice_id=f"aday-{seed}", log_mode="tasarim"):
        yield sar(last[2])
    return (last[0] if last else None), perf_counter() - started, (last[2] if last else None)


def design_candidates(tarif, text, quality, seed1, seed2, seed3, seed4, cands, cins, yas, kullanim, perde, ton,
                      doku, hiz, enerji, progress=gr.Progress()):
    """4 aday: aynı tarif + aynı cümle, kutulardaki seed'ler. Her aday hazır olunca kartına düşer.

    ``cands``: kart sırası ("0".."3") → {"seed", "yol", "sure", "tarif", "text", "secimler"}; seçme ve
    kaydetme adayın GERÇEKTEN üretildiği seed'i buradan alır (kutudaki sonradan değişmiş olabilir).
    """
    tarif, text = _aday_girdisi(tarif, text)
    seeds = []
    for i, deger in enumerate((seed1, seed2, seed3, seed4)):
        seed = seed_coz(deger)
        if seed is None:
            raise _seed_hatasi(i + 1)
        seeds.append(seed)
    secimler = design_selections(cins, yas, kullanim, perde, ton, doku, hiz, enerji)
    cands = {}
    audios: list = [None] * 4
    labels = [t("Aday {n} · seed {seed} · sırada", n=i + 1, seed=s) for i, s in enumerate(seeds)]

    def pack(status):
        return (*audios, *labels, status, cands, gr.update(visible=False), None)

    yield pack(t("4 aday sırayla üretilecek (seed {seeds}). İlk aday hazır olunca dinleyebilirsiniz.",
                 seeds=", ".join(map(str, seeds))))
    started = perf_counter()
    for i, seed in enumerate(seeds):
        labels[i] = t("Aday {n} · seed {seed} · üretiliyor…", n=i + 1, seed=seed)
        yol, sure, son = yield from _aday_sesi(tarif, text, quality, seed, progress,
                                               lambda msg, n=i + 1: pack(t("Aday {n}/4 · {msg}", n=n, msg=msg)))
        if not yol:
            labels[i] = t("Aday {n} · seed {seed} · başarısız", n=i + 1, seed=seed)
            yield pack(son or t("Üretim başarısız."))
            return
        audios[i] = yol
        cands[str(i)] = {"seed": seed, "yol": yol, "sure": round(sure, 1), "tarif": tarif, "text": text,
                         "secimler": secimler}
        labels[i] = _aday_etiketi(i + 1, seed, sure)
        if i < 3:
            yield pack(t("Aday {n}/4 hazır: {sec} saniye.", n=i + 1, sec=f"{sure:.1f}") + " " + t("Sıradaki üretiliyor…"))
        else:
            yield pack(t("Tamamlandı: 4 aday, toplam {sec} saniye. Birini seçip kaydedin.",
                         sec=f"{perf_counter() - started:.1f}"))


def regenerate_candidate(index, tarif, text, quality, seed_deger, cands, picked, cins, yas, kullanim, perde, ton,
                         doku, hiz, enerji, progress=gr.Progress()):
    """Tek adayı (kart ``index``) kutudaki seed'le yeniden üretir; diğer adaylara dokunulmaz.

    Çıktılar: o kartın sesi, etiketi, durum, cands, kaydet grubu, seçili aday. Seçili aday yeniden
    üretilirse seçim kalkar (kaydedilecek ses değişti); başka bir kart seçiliyse seçim korunur.
    """
    n = index + 1
    tarif, text = _aday_girdisi(tarif, text)
    seed = seed_coz(seed_deger)
    if seed is None:
        raise _seed_hatasi(n)
    secimler = design_selections(cins, yas, kullanim, perde, ton, doku, hiz, enerji)
    cands = dict(cands or {})
    eski = cands.get(str(index))
    keep = gr.update()
    label = t("Aday {n} · seed {seed} · üretiliyor…", n=n, seed=seed)
    yield keep, label, t("Aday {n} yeniden üretiliyor (seed {seed}). Diğer adaylar değişmez.", n=n, seed=seed), \
        cands, keep, keep
    yol, sure, son = yield from _aday_sesi(
        tarif, text, quality, seed, progress,
        lambda msg: (keep, label, t("Aday {n}/4 · {msg}", n=n, msg=msg), cands, keep, keep))
    if not yol:
        # Eski ses kartta kalır; etiketi de ona döner (ses ile etiket hep aynı seed'i gösterir).
        geri = _aday_etiketi(n, eski["seed"], eski["sure"]) if eski else \
            t("Aday {n} · seed {seed} · başarısız", n=n, seed=seed)
        yield keep, geri, son or t("Üretim başarısız."), cands, keep, keep
        return
    cands[str(index)] = {"seed": seed, "yol": yol, "sure": round(sure, 1), "tarif": tarif, "text": text,
                         "secimler": secimler}
    secim_kalkar = picked is not None and int(picked) == index
    yield (yol, _aday_etiketi(n, seed, sure),
           t("Tamamlandı: Aday {n}, seed {seed}, {sec} saniye. Diğer adaylar değişmedi.", n=n, seed=seed,
             sec=f"{sure:.1f}"),
           cands, gr.update(visible=False) if secim_kalkar else keep, None if secim_kalkar else keep)


def candidate_warnings(path, meta=None):
    """Kaydı engellemeyen uyarılar: kısa örnek ve sonradan zayıflayabilen doku."""
    out = []
    try:
        if sf.info(path).duration < _SHORT_SAMPLE_SECONDS:
            out.append(SHORT_SAMPLE_WARNING)
    except (RuntimeError, TypeError, OSError):
        pass
    doku = ((meta or {}).get("secimler") or {}).get("doku") or []
    if any(d in _FRAGILE_TEXTURES for d in doku):
        out.append(TEXTURE_WARNING)
    return out


def _secilen_aday(picked, cands):
    if picked is None:
        return None
    return (cands or {}).get(str(int(picked)))


def pick_candidate_ui(index, cands):
    """Kart ``index``'i seçer. Döner: (seçili kart sırası, kaydet grubu, ileti)."""
    aday = _secilen_aday(index, cands)
    if not aday or not aday.get("yol"):
        raise gr.Error(t("Bu aday henüz üretilmedi."))
    msg = t("Seçilen: **Aday {n}** (seed {seed}). Ad verip kaydedin.", n=index + 1, seed=aday["seed"])
    warns = candidate_warnings(aday["yol"], aday)
    if warns:
        msg += "\n\n" + "  \n".join(f"⚠️ {escape(t(w))}" for w in warns)
    return index, gr.update(visible=True), msg


def save_designed_ui(name, aciklama, kategori, picked, cands):
    """Seçili adayı kaydeder: referans o adayın sesi; seed/tarif/cümle o adayın gerçekten üretildiği değerler."""
    if picked is None:
        raise gr.Error(t("Önce bir aday seçin."))
    aday = _secilen_aday(picked, cands)
    if not aday or not aday.get("yol") or not Path(aday["yol"]).is_file():
        raise gr.Error(t("Seçilen aday bulunamadı; adayları yeniden üretin."))
    try:
        voice = vlib.save_voice(
            ad=name, ref_wav=aday["yol"], ref_text=aday["text"], kaynak=DESIGN_KAYNAK, aciklama=aciklama,
            kategori=(kategori or "").strip() or "Genel", tarif=aday["tarif"], seed=int(aday["seed"]),
            secimler=aday.get("secimler"),
        )
    except (vlib.VoiceError, PermissionError) as exc:
        raise _voice_error(exc)
    return _voice_list(), voice["id"], gr.Tabs(selected="lib"), t("Kaydedildi: **{ad}**.", ad=escape(voice["ad"]))


# --- Ses oluştur: dosya yükle -------------------------------------------------
def upload_analyze_ui(path):
    """Çöz → mono → sessizliği kırp → kontroller. Hazırlanan dosya outputs/ altına yazılır."""
    if not path:
        return (None, None, None, "", gr.update(visible=False), gr.update(), gr.update(), "")
    try:
        info = audio_prep.analyze(path)
    except audio_prep.PrepError as exc:
        raise gr.Error(tr_message(str(exc)))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    full = str(audio_prep.write_wav(info["audio"], info["sr"], OUTPUT_DIR / f"yukleme-{uuid4().hex}-tam.wav"))
    dur = info["duration"]
    long_ = dur > audio_prep.MAX_SECONDS
    if long_:
        prepared = str(audio_prep.write_wav(audio_prep.cut(info["audio"], info["sr"], 0, audio_prep.MAX_SECONDS),
                                            info["sr"], OUTPUT_DIR / f"yukleme-{uuid4().hex}.wav"))
    else:
        prepared = full
    lines = [t("Süre (sessizlik kırpıldı): **{sec} sn** · mono, 16-bit WAV'a çevrildi.", sec=f"{dur:.1f}")]
    lines += [f"⚠️ {escape(tr_message(w))}" for w in info["warnings"]]
    lines.append(t(audio_prep.CLEAN_NOTE))
    end = min(dur, audio_prep.MAX_SECONDS)
    return (full, prepared, prepared, "  \n".join(lines), gr.update(visible=long_),
            gr.update(maximum=round(dur, 1), value=0), gr.update(maximum=round(dur, 1), value=round(end, 1)), "")


def upload_cut_ui(full, start, end):
    if not full:
        raise gr.Error(t("Önce bir ses dosyası yükleyin."))
    audio, sr = sf.read(full, dtype="float32")
    try:
        clip = audio_prep.cut(audio, sr, start, end)
    except audio_prep.PrepError as exc:
        raise gr.Error(tr_message(str(exc)))
    out = str(audio_prep.write_wav(clip, sr, OUTPUT_DIR / f"yukleme-{uuid4().hex}.wav"))
    return out, out, t("Seçilen aralık: {start}–{end} sn ({length} sn).", start=f"{float(start):.1f}",
                       end=f"{float(end):.1f}", length=f"{float(end) - float(start):.1f}")


def upload_transcribe_ui(prepared):
    if not prepared:
        raise gr.Error(t("Önce bir ses dosyası yükleyin."))
    try:
        text, ratio = transcribe_with_info(prepared)
    except Exception:
        import traceback
        traceback.print_exc()
        raise gr.Error(t("Otomatik yazıya dökme başarısız; metni elle yazabilirsiniz."))
    note = t("Konuşma oranı ≈ %{pct}.", pct=f"{ratio * 100:.0f}")
    if ratio < 0.6:
        note += " " + t("⚠️ Kaydın büyük kısmında konuşma algılanmadı; müzik veya sessizlik olabilir.")
    if not text:
        note += " " + t("Ses anlaşılamadı; metni elle yazın.")
    return text, note + " " + t("Metni kayıtla birebir aynı olacak şekilde düzeltin.")


def save_uploaded_ui(prepared, text, name, aciklama, kategori, consent):
    if not consent:
        raise gr.Error(t("Kaydetmek için izin kutucuğunu işaretleyin."))
    if not prepared or not Path(prepared).is_file():
        raise gr.Error(t("Önce bir ses dosyası yükleyin."))
    if not (text or "").strip():
        raise gr.Error(t("Kaydın metni boş olamaz; devam kipi bu metinle çalışır."))
    dur = sf.info(prepared).duration
    if not audio_prep.MIN_SECONDS - 0.05 <= dur <= audio_prep.MAX_SECONDS + 0.05:
        raise gr.Error(t("Kayıt {sec} sn; 8–20 sn arası olmalı.", sec=f"{dur:.1f}"))
    try:
        voice = vlib.save_voice(ad=name, ref_wav=prepared, ref_text=text, kaynak="yüklendi",
                                aciklama=aciklama, kategori=(kategori or "").strip() or "Genel")
    except (vlib.VoiceError, PermissionError) as exc:
        raise _voice_error(exc)
    return _voice_list(), voice["id"], gr.Tabs(selected="lib"), t("Kaydedildi: **{ad}**.", ad=escape(voice["ad"]))




# --- Görünüm --------------------------------------------------------------
# Referanslar: "Voice Aura" (noktalı/halftone doku, yüzen beyaz kartlar, küçük
# rozetler, ince tipografi) ve Dribbble "Futuristic AI Voice Generator"
# (krem zemin, kalın başlık + tek mercan vurgu, girişi saran gradient çerçeve,
# siyah hap buton). Yazı tipleri sistemden gelir: arayüz dış sunucudan
# font/görsel çekmez, her şey yerelde kalır.

_SAMPLE_TEXT = "Merhaba! Bu ses, bilgisayarımda yerel olarak çalışan bir yapay zekâ ile üretildi."


def _svg(paths, cls="sv-ic"):
    return (
        f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{paths}</svg>'
    )


_IC_WAVE = '<path d="M3 10v4M7 7v10M11 4v16M15 8v8M19 10.5v3"/>'
_IC_LOCK = '<rect x="5" y="11" width="14" height="10" rx="2.5"/><path d="M8 11V7.5a4 4 0 0 1 8 0V11"/>'
_IC_TEXT = '<path d="M4 6.5V5h16v1.5M12 5v14M9 19h6"/>'
_IC_MIC = '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>'
_IC_PEN = '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>'
_IC_PLAY = '<circle cx="12" cy="12" r="9"/><path d="m10 8.5 5 3.5-5 3.5z"/>'
_IC_CPU = ('<rect x="5" y="5" width="14" height="14" rx="2.5"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/>'
           '<path d="M9.5 2v3M14.5 2v3M9.5 19v3M14.5 19v3M2 9.5h3M2 14.5h3M19 9.5h3M19 14.5h3"/>')
_IC_CLOUD = '<path d="M7 18a4.5 4.5 0 0 1-.5-9A6 6 0 0 1 18 8.5a4.5 4.5 0 0 1-1 9.5"/><path d="M12 11v9M9 17l3 3 3-3"/>'
_IC_CLOCK = '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>'
_IC_SHIELD = '<path d="M12 3 4.5 6v5.5c0 4.8 3.2 8.2 7.5 9.5 4.3-1.3 7.5-4.7 7.5-9.5V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>'
_IC_LIB = '<rect x="4" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.6"/><path d="M16.75 14v5.5M14 16.75h5.5"/>'
_IC_SPARK = '<path d="M12 3.5 13.8 9 19.5 10.8 13.8 12.6 12 18.5 10.2 12.6 4.5 10.8 10.2 9z"/><path d="M19 17v4M17 19h4"/>'
_IC_FX = '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>'
_IC_BOLT = '<path d="M13 2.5 5 13.5h6l-1 8 8-11h-6z"/>'


def _html(value, **kwargs):
    return gr.HTML(value, apply_default_css=False, **kwargs)


def _head(icon, title, text, step=None):
    badge = f'<span class="sv-step">{step}</span>' if step else f'<span class="sv-head-ic">{_svg(icon)}</span>'
    return _html(
        f'<div class="sv-head">{badge}<div><h3>{title}</h3><p>{text}</p></div></div>'
    )


# --- Şemsiye marka imzası (HamaratLabs) -------------------------------
# İmza yalnız burada tanımlıdır; kalıcı marka (_brand), açılış ekranı (_splash) ve alt bilgi
# (_footer) buradan okur.
# Logo seçilince yalnız BRAND_SIGNATURE_HTML içindeki <b class="sv-sig-mark"> öğesini
# satır içi SVG ile değiştirin, ör.:
#   <svg class="sv-sig-mark" role="img" aria-label="HamaratLabs" viewBox="…">…</svg>
# ("by" metni ve dış <span class="sv-sig"> kalabilir; .sv-sig-mark CSS'i yüksekliği
# metin boyuna (1em) göre ayarlanacak şekilde güncellenmeli.)
BRAND_NAME = "HamaratLabs"
BRAND_SIGNATURE_HTML = (
    f'<span class="sv-sig" title="{BRAND_NAME}">'
    f'by <b class="sv-sig-mark">{BRAND_NAME}</b></span>'
)
BRAND_FOOTER_TEXT = f"{BRAND_NAME} tarafından geliştirildi"  # Türkçe hâli; çevirisi _footer() içinde


def _brand():
    """Kalıcı marka: sol üstte küçük logo + SesVer + "by HamaratLabs" (dil çubuğunun solunda)."""
    return (f'<nav class="sv-nav"><div class="sv-brand"><span class="sv-logo">{_svg(_IC_WAVE)}</span>'
            f'<span class="sv-brand-text"><span>SesVer</span>{BRAND_SIGNATURE_HTML}</span></div></nav>')


# --- Açılış ekranı ---------------------------------------------------------
# Büyük karşılama (rozetler, başlık, açıklama) panelde kalıcı yer kaplamaz: uygulama her
# açıldığında bir kez ekranın ortasında belirir, kısa süre kalır ve kaybolur. Tıklama, tuş
# ya da kaydırma hemen geçer. "Bir kez" sunucu sürecine bağlıdır: her açılışta yeni bir
# kimlik üretilir; dil değiştirme (/en, /ar …), sayfa yenileme ve yeni sekme aynı kimliği
# görür ve tekrar oynatmaz. Hareket azaltma tercihinde hareketsiz ve kısa gösterilir.
SPLASH_BOOT_ID = uuid4().hex[:12]
SPLASH_KEY = "sesver-acilis"
SPLASH_HOLD_MS = 2000        # belirme dahil ekranda kalma süresi; ardından ~0,55 sn'de kaybolur
SPLASH_HOLD_STILL_MS = 1200  # hareket azaltma açıkken (animasyonsuz)


def _splash():
    rtl = ' dir="rtl"' if i18n.is_rtl(i18n.get_lang()) else ""
    return f"""
<div class="sv-splash" data-boot="{SPLASH_BOOT_ID}" aria-hidden="true"{rtl}>
  <div class="sv-aura"><i></i><i></i><i></i></div>
  <div class="sv-splash-in">
    <div class="sv-brand sv-brand-lg"><span class="sv-logo">{_svg(_IC_WAVE)}</span>
      <span class="sv-brand-text"><span>SesVer</span>{BRAND_SIGNATURE_HTML}</span></div>
    <div class="sv-badges">
      <span class="sv-badge"><b>TR</b>{t("Türkçe")}</span>
      <span class="sv-badge">{_svg(_IC_LOCK)}{t("Hesap gerekmez")}</span>
      <span class="sv-badge">{_svg(_IC_MIC)}{t("Ses klonlama")}</span>
    </div>
    <h1>{t('Yazdığınız metne<br><span class="sv-accent">ses verin.</span>')}</h1>
    <p>{t("Türkçe metni doğal bir sese çevirin ya da kısa bir kayıtla bir sesi klonlayın. "
          "Kurulum bir kez yapılır, gerisi tek tık.")}</p>
    <div class="sv-nav-tags">
      <span class="sv-tag"><span class="sv-live"></span>{t("Bilgisayarınızda çalışır")}</span>
      <span class="sv-tag">{t("Açık kaynak (MIT) · Ücretsiz")}</span>
    </div>
    <span class="sv-splash-bar"></span>
  </div>
</div>
"""


# gr.HTML js_on_load: bileşen DOM'a bağlanır bağlanmaz (ilk boyamadan önce) çalışır.
# Varsayılan CSS'te açılış ekranı gizlidir; yalnız oynayacaksa "is-on" eklenir, yoksa
# öğe hemen kaldırılır (yenilemede yanıp sönme olmaz). localStorage yoksa sessionStorage.
SPLASH_JS = f"""
const s = element.querySelector('.sv-splash');
if (!s) return;
const key = {SPLASH_KEY!r}, id = s.dataset.boot;
let seen = false;
for (const st of ['localStorage', 'sessionStorage']) {{
  try {{ seen = window[st].getItem(key) === id; window[st].setItem(key, id); break; }} catch (e) {{}}
}}
if (seen) {{ s.remove(); return; }}
const still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const hold = still ? {SPLASH_HOLD_STILL_MS} : {SPLASH_HOLD_MS};
const evs = ['pointerdown', 'keydown', 'wheel', 'touchstart'];
let done = false, timer = 0;
const end = (skip) => {{
  if (done) return;
  done = true;
  clearTimeout(timer);
  evs.forEach((ev) => window.removeEventListener(ev, onSkip, true));
  s.classList.add(skip ? 'is-skip' : 'is-out');
  setTimeout(() => s.remove(), skip || still ? 260 : 600);
}};
const onSkip = () => end(true);
s.style.setProperty('--sv-hold', hold + 'ms');
s.classList.add('is-on');
if (still) s.classList.add('is-still');
evs.forEach((ev) => window.addEventListener(ev, onSkip, {{ capture: true, passive: true }}));
timer = setTimeout(() => end(false), hold);
"""


def _info():
    return f"""
<div class="sv-info">
  <div class="sv-tile"><span class="sv-tile-ic">{_svg(_IC_CPU)}</span>
    <div><b>{t("16 GB+ RAM önerilir")}</b><span>{t("Daha az bellekte yavaşlayabilir veya durabilir.")}</span></div></div>
  <div class="sv-tile"><span class="sv-tile-ic">{_svg(_IC_CLOUD)}</span>
    <div>{_info_model()}</div></div>
  <div class="sv-tile"><span class="sv-tile-ic">{_svg(_IC_CLOCK)}</span>
    <div><b>{t("Biraz sabır")}</b><span>{t("Gerçek zamanlı değildir: 10 saniyelik ses, donanıma göre 1-2 dakika sürebilir.")}</span></div></div>
</div>
"""


def _info_model():
    """Model kutucuğu modelin gerçek durumuna göre (1.4.1): bilgisayardaysa "indirilir" demez.
    Önbellek okunamazsa (None) genel ve her durumda doğru olan eski metin kalır."""
    if _model is not None or _model_diskte():
        return (f'<b>{t("Ses modeli bilgisayarınızda")}</b>'
                f'<span>{t("Yeniden indirilmez; ilk üretimde yalnız belleğe yüklenir.")}</span>')
    return (f'<b>{t("İlk üretimde ~5 GB indirilir")}</b>'
            f'<span>{t("Bir kez internet gerekir; sonra model bilgisayarınızda kalır.")}</span>')


def _footer():
    return f"""
<footer class="sv-foot">
  <span class="sv-brand sv-brand-sm"><span class="sv-logo">{_svg(_IC_WAVE)}</span>SesVer</span>
  <span>{t("VoxCPM2 ile yerel ses üretimi")}</span><i></i>
  <span>{t("Paylaşırken “AI ile üretildi” yazın")}</span><i></i>
  <span class="sv-foot-sig">{t("{brand} tarafından geliştirildi", brand=BRAND_NAME)}</span>
</footer>
"""


def _ethics():
    return f"""
<div class="sv-ethics">
  <div class="sv-head"><span class="sv-head-ic">{_svg(_IC_SHIELD)}</span>
    <div><h3>{t("Sorumlu kullanım")}</h3><p>{t("Klonlama güçlü bir araçtır; lütfen dikkatli kullanın.")}</p></div></div>
  <ul>
    <li>{t("Yalnız <b>kendi sesinizi</b> veya açık izin aldığınız sesleri kullanın.")}</li>
    <li>{t("Paylaşırken <b>“AI ile üretildi”</b> etiketi ekleyin; otomatik filigran yoktur.")}</li>
    <li>{t("Birini taklit ederek yanıltmak ve dolandırıcılık için kullanmayın.")}</li>
  </ul>
</div>
"""


def _result_head():
    return (_IC_PLAY, t("Sonuç"), t("Ses hazır olunca burada dinleyip indirebilirsiniz."))


def _result_note():
    return ('<p class="sv-note">' + t("Üretim birkaç dakika sürebilir. Bu sırada pencereyi açık tutun; "
                                      "sayfa donmuş gibi görünse de çalışıyordur.") + "</p>")


# "Efekt ekle": efekt kartını görünür alana kaydırır (akordeonu sunucu tarafı açar).
_FX_JUMP_JS = """() => {
  const el = document.querySelector('.sv-fx');
  const still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (el) setTimeout(() => el.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'start' }), 80);
  return [];
}"""

# Butonlardaki ikonlar CSS maskesiyle çizilir (metin etiketi değişmeden kalır).
_CSS = """
:root, .gradio-container {
  --sv-ink: #17130F;
  --sv-ink-2: #3B342E;
  --sv-muted: #7A7069;
  --sv-line: rgba(23, 19, 15, 0.09);
  --sv-line-2: rgba(23, 19, 15, 0.16);
  --sv-cream: #F4F1EC;
  --sv-paper: #FFFFFF;
  --sv-soft: #FAF8F5;
  --sv-coral: #F25C3B;
  --sv-grad: linear-gradient(118deg, #C9B8FF 0%, #F2A9CB 36%, #FF9C6E 70%, #FF5A3A 100%);
  --sv-shadow-sm: 0 1px 2px rgba(23, 19, 15, 0.06), 0 1px 1px rgba(23, 19, 15, 0.03);
  --sv-shadow: 0 1px 2px rgba(23, 19, 15, 0.04), 0 18px 40px -22px rgba(23, 19, 15, 0.28);
  --sv-shadow-lg: 0 2px 6px rgba(23, 19, 15, 0.04), 0 40px 80px -36px rgba(170, 60, 30, 0.45);
  --sv-ease: cubic-bezier(.2, .7, .2, 1);
  color-scheme: light;
}

/* --- Sayfa ------------------------------------------------------------ */
html, body, gradio-app { background: var(--sv-cream) !important; }
.gradio-container {
  max-width: 1120px !important;
  margin: 0 auto !important;
  padding: 0 clamp(14px, 3vw, 28px) 28px !important;
  background: transparent !important;
  color: var(--sv-ink);
  -webkit-font-smoothing: antialiased;
}
/* Sayfanın üstüne yayılan çok hafif nokta dokusu. */
.gradio-container::before {
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background-image: radial-gradient(rgba(23, 19, 15, 0.10) 1px, transparent 1.3px);
  background-size: 14px 14px;
  -webkit-mask-image: radial-gradient(ellipse 75% 50% at 50% 0%, #000 0%, transparent 78%);
          mask-image: radial-gradient(ellipse 75% 50% at 50% 0%, #000 0%, transparent 78%);
}
.gradio-container > * { position: relative; z-index: 1; }
.gradio-container .main, .gradio-container .wrap.main { gap: 0 !important; }
.gradio-container .main.fillable { padding-left: 0 !important; padding-right: 0 !important; }
/* Not: Gradio @media içindeki seçicilere ".contain" ön eki ekler; kapsayıcı
   düzeyindeki boşluklar bu yüzden medya sorgusu yerine clamp() ile ayarlanır. */
.sv-ic { width: 18px; height: 18px; flex: none; }
.gradio-container .html-container { padding: 0 !important; }

/* --- Açılış ekranı (bkz. _splash / SPLASH_JS) --------------------------
   Varsayılan gizli; JS yalnız oynayacağı açılışta "is-on" ekler. Ekranı örten sabit
   katman: krem zemin, ortada marka + rozetler + başlık + açıklama, altta kalma süresini
   gösteren ince çizgi. Belirme ~0,9 sn (sırayla yükselerek), kalma SPLASH_HOLD_MS,
   kaybolma 0,55 sn (geçince 0,24 sn). Yalnız opacity + transform canlandırılır. */
.sv-splash { display: none; position: fixed; inset: 0; z-index: 1000; place-items: center;
  padding: 32px 20px; overflow: hidden; text-align: center; background: var(--sv-cream);
  color: var(--sv-ink); cursor: default; -webkit-user-select: none; user-select: none; }
.sv-splash.is-on { display: grid; }
/* Taşıyıcı blok akıştan çıkar: sütun aralığı (gap) eklemez, sayfa yukarıdan başlar. */
.block.sv-splash-host { position: absolute !important; width: 0 !important; height: 0 !important;
  margin: 0 !important; padding: 0 !important; border: 0 !important; }
.sv-splash-in { position: relative; z-index: 1; max-width: 760px; display: flex; flex-direction: column;
  align-items: center; }
.sv-aura { position: absolute; left: 50%; top: 50%; width: min(1100px, 100%); height: 520px;
  transform: translate(-50%, -52%); pointer-events: none; z-index: 0; }
.sv-aura i { position: absolute; inset: 0; display: block;
  background-image: radial-gradient(var(--sv-ink) var(--r), transparent calc(var(--r) + 0.6px));
  background-size: 9px 9px; background-position: center; }
.sv-aura i:nth-child(1) { --r: 0.7px; opacity: .22;
  -webkit-mask-image: radial-gradient(ellipse 50% 46% at 50% 55%, #000 25%, transparent 100%);
          mask-image: radial-gradient(ellipse 50% 46% at 50% 55%, #000 25%, transparent 100%); }
.sv-aura i:nth-child(2) { --r: 1.4px; opacity: .16;
  -webkit-mask-image: radial-gradient(ellipse 34% 24% at 50% 58%, #000 10%, transparent 100%);
          mask-image: radial-gradient(ellipse 34% 24% at 50% 58%, #000 10%, transparent 100%); }
.sv-aura i:nth-child(3) { --r: 2.2px; opacity: .10;
  -webkit-mask-image: radial-gradient(ellipse 20% 12% at 50% 60%, #000 0%, transparent 100%);
          mask-image: radial-gradient(ellipse 20% 12% at 50% 60%, #000 0%, transparent 100%); }
/* Nokta katmanları merkezden dışa doğru sırayla büyüyüp belirir (~1,9 sn), sonra durur.
   Bitiş anahtar karesi yok, fill-mode "backwards": bitince sabit stile döner. Katman
   display:none iken animasyon başlamaz; "is-on" ile görünür olunca bir kez oynar. */
@keyframes sv-aura-in { from { opacity: 0; transform: scale(var(--s0)); } }
.sv-aura i { transform-origin: 50% 58%;
  animation: sv-aura-in var(--d) var(--sv-ease) var(--dl) 1 backwards; }
.sv-aura i:nth-child(3) { --s0: .45; --d: 1.3s; --dl: 0s; }
.sv-aura i:nth-child(2) { --s0: .6;  --d: 1.5s; --dl: .12s; }
.sv-aura i:nth-child(1) { --s0: .75; --d: 1.7s; --dl: .24s; }
@media (prefers-reduced-motion: reduce) { .sv-aura i { animation: none !important; } }

@keyframes sv-rise { from { opacity: 0; transform: translateY(16px); } }
@keyframes sv-splash-out { to { opacity: 0; } }
@keyframes sv-lift { to { opacity: 0; transform: translateY(-14px) scale(.985); } }
@keyframes sv-fill { from { transform: scaleX(0); } }
.sv-splash-in > * { animation: sv-rise .75s var(--sv-ease) calc(80ms + var(--n) * 90ms) 1 backwards; }
.sv-splash-in > :nth-child(1) { --n: 0; }
.sv-splash-in > :nth-child(2) { --n: 1; }
.sv-splash-in > :nth-child(3) { --n: 2; }
.sv-splash-in > :nth-child(4) { --n: 3.4; }
.sv-splash-in > :nth-child(5) { --n: 4.4; }
.sv-splash-in > :nth-child(6) { --n: 5.4; }
.sv-splash.is-out { animation: sv-splash-out .55s var(--sv-ease) forwards; pointer-events: none; }
.sv-splash.is-out .sv-splash-in { animation: sv-lift .55s var(--sv-ease) forwards; }
.sv-splash.is-skip { animation: sv-splash-out .24s ease-out forwards; }
.sv-splash.is-skip .sv-splash-in { animation: sv-lift .24s ease-out forwards; }
.sv-splash-bar { position: relative; width: 112px; height: 2px; margin-top: 34px; border-radius: 2px;
  overflow: hidden; background: var(--sv-line); }
.sv-splash-bar::after { content: ""; position: absolute; inset: 0; background: var(--sv-grad);
  transform-origin: left center; animation: sv-fill var(--sv-hold, 2s) linear 1 backwards; }
.sv-splash[dir="rtl"] .sv-splash-bar::after { transform-origin: right center; }
/* Hareket azaltma: animasyon yok; kısa süre durağan görünür, 0,2 sn'de söner. */
.sv-splash.is-still, .sv-splash.is-still *, .sv-splash.is-still *::after { animation: none !important; }
.sv-splash.is-still { transition: opacity .2s linear; }
.sv-splash.is-still.is-out, .sv-splash.is-still.is-skip { opacity: 0; }
.sv-splash.is-still .sv-splash-bar { visibility: hidden; }
@media (prefers-reduced-motion: reduce) {
  .sv-splash, .sv-splash *, .sv-splash *::after { animation: none !important; } }

/* --- Marka (sol üst, kalıcı) ------------------------------------------ */
.sv-nav { display: flex; align-items: center; }
.sv-brand { display: inline-flex; align-items: center; gap: 10px; font-weight: 700;
  font-size: 1.05rem; letter-spacing: 0.02em; color: var(--sv-ink); text-transform: uppercase; }
.sv-logo { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 11px;
  background: var(--sv-paper); border: 1px solid var(--sv-line); box-shadow: var(--sv-shadow-sm); }
.sv-logo .sv-ic { width: 17px; height: 17px; stroke-width: 2.2; }
.sv-brand-lg { gap: 12px; margin-bottom: 30px; font-size: 1.2rem; text-align: start; }
.sv-brand-lg .sv-logo { width: 46px; height: 46px; border-radius: 15px; }
.sv-brand-lg .sv-logo .sv-ic { width: 22px; height: 22px; }
.sv-brand-lg .sv-sig { font-size: .74rem; }
/* Ürün adı + altında küçük "by HamaratLabs" imzası (ürün markasını bastırmaz). */
.sv-brand-text { display: inline-flex; flex-direction: column; align-items: flex-start; gap: 1px;
  line-height: 1.1; }
.sv-sig { font-size: .68rem; font-weight: 500; letter-spacing: .01em; text-transform: none;
  color: var(--sv-muted); white-space: nowrap; }
.sv-sig-mark { font-weight: 650; color: var(--sv-ink-2); }
.sv-foot-sig { color: var(--sv-ink-2); }
.sv-nav-tags { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 28px; }
.sv-tag { display: inline-flex; align-items: center; gap: 8px; padding: 7px 13px; border-radius: 999px;
  font-size: .8rem; font-weight: 500; color: var(--sv-ink-2); background: rgba(255,255,255,.75);
  border: 1px solid var(--sv-line); box-shadow: var(--sv-shadow-sm); }
.sv-live { width: 7px; height: 7px; border-radius: 50%; background: #2DBE6C;
  box-shadow: 0 0 0 3px rgba(45, 190, 108, .18); }

.sv-badges { display: inline-flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-bottom: 22px; }
.sv-badge { display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px 6px 8px;
  border-radius: 999px; background: var(--sv-paper); border: 1px solid var(--sv-line);
  box-shadow: var(--sv-shadow-sm); font-size: .8rem; font-weight: 500; color: var(--sv-ink-2); }
.sv-badge .sv-ic { width: 15px; height: 15px; color: var(--sv-coral); }
.sv-badge b { font-size: .64rem; font-weight: 700; letter-spacing: .04em; color: #fff;
  background: #E30A17; border-radius: 4px; padding: 2px 4px; line-height: 1; }
.sv-splash h1 { margin: 0; font-size: clamp(2.5rem, 5.4vw, 4.1rem); line-height: 1.02;
  font-weight: 700; letter-spacing: -0.032em; word-spacing: 0.04em; color: var(--sv-ink); }
.sv-accent { background: linear-gradient(92deg, #FF7A4D 0%, #F2476A 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent; padding-right: .04em; }
.sv-splash-in p { margin: 20px auto 0; max-width: 540px; font-size: 1.08rem; line-height: 1.6;
  color: var(--sv-muted); }

/* --- Sekmeler: ortalanmış hap anahtar ------------------------------ */
#sv-tabs { background: transparent !important; border: 0 !important; padding: 0 !important; gap: 0 !important; }
#sv-tabs > .tab-wrapper { display: flex; justify-content: center; height: auto !important;
  border: 0 !important; margin: 0 0 26px; padding: 0 !important; }
#sv-tabs > .tab-wrapper::before, #sv-tabs > .tab-wrapper::after { display: none !important; }
#sv-tabs .tab-container[role="tablist"] { display: inline-flex; flex: 0 0 auto !important; width: auto !important;
  gap: 4px; padding: 5px; height: auto !important;
  border-radius: 999px; background: rgba(255,255,255,.8); border: 1px solid var(--sv-line) !important;
  box-shadow: var(--sv-shadow-sm), 0 10px 30px -18px rgba(23,19,15,.35); backdrop-filter: blur(8px); }
#sv-tabs .tab-container[role="tablist"]::after { display: none !important; }
#sv-tabs [role="tab"] { display: inline-flex; align-items: center; gap: 8px; height: auto !important;
  padding: 10px 20px 10px 16px !important; margin: 0 !important; border: 0 !important; border-radius: 999px !important;
  font-size: .95rem !important; font-weight: 600 !important; color: var(--sv-muted) !important;
  background: transparent !important; transition: background .2s var(--sv-ease), color .2s var(--sv-ease); }
#sv-tabs [role="tab"]::after { display: none !important; }
#sv-tabs [role="tab"]::before { content: ""; width: 17px; height: 17px; background: currentColor;
  -webkit-mask: var(--ic) center / contain no-repeat; mask: var(--ic) center / contain no-repeat; }
#sv-tabs [role="tab"]:nth-child(1) { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'><rect x='4' y='4' width='6.5' height='6.5' rx='1.6'/><rect x='13.5' y='4' width='6.5' height='6.5' rx='1.6'/><rect x='4' y='13.5' width='6.5' height='6.5' rx='1.6'/><path d='M16.75 14v5.5M14 16.75h5.5'/></svg>"); }
#sv-tabs [role="tab"]:nth-child(2) { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 3.5 13.8 9 19.5 10.8 13.8 12.6 12 18.5 10.2 12.6 4.5 10.8 10.2 9z'/></svg>"); }
#sv-tabs [role="tab"]:nth-child(3) { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'><rect x='9' y='3' width='6' height='11' rx='3'/><path d='M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21'/></svg>"); }
#sv-tabs [role="tab"]:nth-child(4) { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M13 2.5 5 13.5h6l-1 8 8-11h-6z'/></svg>"); }
#sv-tabs [role="tab"]:nth-child(5) { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='3'/><path d='M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1'/></svg>"); }
/* İç sekmeler (Ses Oluştur): ikonsuz, sola dayalı, daha küçük hap. */
#sv-subtabs > .tab-wrapper { justify-content: flex-start; margin: 0 0 18px; }
#sv-subtabs [role="tab"]::before { display: none !important; }
#sv-subtabs [role="tab"] { padding: 8px 16px !important; font-size: .88rem !important; }
#sv-tabs [role="tab"]:hover { color: var(--sv-ink) !important; background: rgba(23,19,15,.04) !important; }
#sv-tabs [role="tab"].selected { color: #fff !important; background: var(--sv-ink) !important;
  box-shadow: 0 6px 16px -8px rgba(23,19,15,.7); }
#sv-tabs .tabitem { padding: 0 !important; border: 0 !important; background: transparent !important; }

/* --- Izgara ve kartlar --------------------------------------------- */
.sv-grid { gap: 22px !important; align-items: flex-start !important; flex-wrap: wrap !important; }
.sv-side { gap: 18px !important; }

/* Dribbble'daki gibi girişi saran gradient çerçeve, üstünde noktalı doku. */
.sv-frame { position: relative; background: var(--sv-grad) !important; border-radius: 30px !important;
  padding: 0 8px 8px !important; gap: 0 !important; border: 0 !important; box-shadow: var(--sv-shadow-lg); overflow: hidden; }
.sv-frame::before { content: ""; position: absolute; inset: 0; pointer-events: none;
  background-image: radial-gradient(rgba(255,255,255,.55) 1px, transparent 1.4px); background-size: 8px 8px;
  -webkit-mask-image: linear-gradient(180deg, #000 0, transparent 90px);
          mask-image: linear-gradient(180deg, #000 0, transparent 90px); }
.sv-frame-bar { position: relative; display: flex; align-items: center; justify-content: space-between;
  gap: 10px; padding: 12px 8px 12px; flex-wrap: wrap; }
.sv-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.sv-chip { display: inline-flex; align-items: center; gap: 7px; padding: 7px 13px; border-radius: 999px;
  background: rgba(255,255,255,.88); box-shadow: 0 1px 2px rgba(80,20,10,.10); font-size: .8rem;
  font-weight: 600; color: var(--sv-ink-2); }
.sv-chip .sv-ic { width: 15px; height: 15px; }
.sv-chip-dark { background: rgba(23,19,15,.82); color: #fff; }

.sv-panel { position: relative; z-index: 1; background: var(--sv-paper) !important; border-radius: 23px !important;
  padding: 26px 26px 22px !important; gap: 20px !important; border: 0 !important;
  box-shadow: 0 1px 2px rgba(80,20,10,.08), 0 0 0 1px rgba(255,255,255,.6) inset; }
.sv-card { background: var(--sv-paper) !important; border: 1px solid var(--sv-line) !important;
  border-radius: 24px !important; padding: 24px !important; gap: 16px !important; box-shadow: var(--sv-shadow); }

/* Kart içindeki Gradio blokları: kendi kutularını kaldır, düzeni kart versin. */
.sv-panel .block, .sv-card .block, .sv-panel .form, .sv-card .form {
  background: transparent !important; border: 0 !important; box-shadow: none !important;
  padding: 0 !important; border-radius: 0 !important; }
.sv-panel .form, .sv-card .form { gap: 20px !important; }
.sv-panel .row, .sv-card .row { gap: 12px !important; }

.sv-head { display: flex; align-items: flex-start; gap: 13px; }
.sv-head h3 { margin: 1px 0 3px; font-size: 1.08rem; font-weight: 650; letter-spacing: -0.015em; color: var(--sv-ink); }
.sv-head p { margin: 0; font-size: .9rem; line-height: 1.5; color: var(--sv-muted); }
.sv-head-ic, .sv-step { flex: none; display: grid; place-items: center; width: 36px; height: 36px;
  border-radius: 12px; background: var(--sv-soft); border: 1px solid var(--sv-line); color: var(--sv-ink); }
.sv-step { font-size: .85rem; font-weight: 700; background: var(--sv-ink); color: #fff; border: 0; border-radius: 50%;
  width: 30px; height: 30px; margin-top: 1px; }
.sv-divider { height: 1px; background: var(--sv-line); margin: 2px 0; }

/* Etiketler */
.sv-panel [data-testid="block-info"], .sv-card [data-testid="block-info"] {
  display: inline-block; margin-bottom: 9px !important; font-size: .8rem !important; font-weight: 600 !important;
  color: var(--sv-ink-2) !important; letter-spacing: .01em; }

/* Metin kutuları */
.sv-panel textarea {
  background: var(--sv-soft) !important; border: 1px solid var(--sv-line) !important; border-radius: 16px !important;
  padding: 15px 17px !important; font-size: 1.03rem !important; line-height: 1.6 !important; color: var(--sv-ink) !important;
  box-shadow: inset 0 1px 2px rgba(23,19,15,.03) !important;
  transition: border-color .18s var(--sv-ease), box-shadow .18s var(--sv-ease), background .18s var(--sv-ease); }
.sv-panel textarea::placeholder { color: #A89E96 !important; }
.sv-panel textarea:hover { border-color: var(--sv-line-2) !important; }
.sv-panel textarea:focus { outline: none !important; background: #fff !important;
  border-color: rgba(242,92,59,.55) !important; box-shadow: 0 0 0 4px rgba(242,92,59,.12) !important; }
.sv-panel .input-container { background: transparent !important; }
.sv-panel label.container { background: transparent !important; box-shadow: none !important; border: 0 !important; }

/* Duygu seçici: Voice Aura'daki küçük hap etiketler, her tona ait renk noktasıyla. */
.sv-emotion .wrap { display: flex !important; flex-wrap: wrap; gap: 8px !important; }
.sv-emotion .wrap label {
  position: relative; display: inline-flex !important; align-items: center; gap: 8px; margin: 0 !important;
  padding: 8px 15px 8px 12px !important; border-radius: 999px !important; cursor: pointer;
  background: #fff !important; border: 1px solid var(--sv-line-2) !important; box-shadow: var(--sv-shadow-sm) !important;
  font-size: .9rem !important; font-weight: 550; color: var(--sv-ink-2) !important;
  transition: transform .15s var(--sv-ease), box-shadow .2s var(--sv-ease), background .2s, border-color .2s, color .2s; }
.sv-emotion .wrap label input { position: absolute !important; opacity: 0 !important; width: 1px !important;
  height: 1px !important; margin: 0 !important; pointer-events: none; }
.sv-emotion .wrap label span { margin: 0 !important; }
.sv-emotion .wrap label::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--dot, #B9B0A8);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--dot, #B9B0A8) 20%, transparent); }
.sv-emotion .wrap label:hover { transform: translateY(-1px); border-color: rgba(23,19,15,.3) !important;
  box-shadow: 0 6px 14px -8px rgba(23,19,15,.35) !important; }
.sv-emotion .wrap label:has(input:focus-visible) { outline: 2px solid var(--sv-coral); outline-offset: 2px; }
.sv-emotion .wrap label.selected { background: var(--sv-ink) !important; border-color: var(--sv-ink) !important;
  color: #fff !important; box-shadow: 0 8px 18px -10px rgba(23,19,15,.8) !important; }
/* Renk noktaları sıraya göre (etiket metni arayüz diline göre değiştiği için):
   Nötr, Sakin, Enerjik, Neşeli, Ciddi, Heyecanlı, Üzgün. */
.sv-emotion:not(.sv-plain) .wrap label:nth-child(2) { --dot: #4FA3E8; }
.sv-emotion:not(.sv-plain) .wrap label:nth-child(3) { --dot: #FF8A3D; }
.sv-emotion:not(.sv-plain) .wrap label:nth-child(4) { --dot: #F5C23A; }
.sv-emotion:not(.sv-plain) .wrap label:nth-child(5) { --dot: #6E7781; }
.sv-emotion:not(.sv-plain) .wrap label:nth-child(6) { --dot: #F2476A; }
.sv-emotion:not(.sv-plain) .wrap label:nth-child(7) { --dot: #7C6CF0; }

/* --- Arayüz dili seçici (sağ üst) ---------------------------------- */
/* Gradio'nun çok sayfalı gezinme çubuğu ("Home") gizlenir; diller arası geçiş seçiciyle yapılır. */
.nav-holder { display: none !important; }
.sv-langbar { flex-direction: row-reverse !important; justify-content: flex-start !important;
  align-items: center !important; gap: 8px 14px !important; padding-top: 12px; margin-bottom: 22px;
  position: relative; z-index: 3; flex-wrap: wrap !important; }
.sv-langbar > * { flex: 0 1 auto !important; min-width: 0 !important; }
.sv-langbar > .form { flex: 0 0 200px !important; width: 200px !important; background: transparent !important;
  border: 0 !important; box-shadow: none !important; }
.sv-langbar .block { background: transparent !important; border: 0 !important; box-shadow: none !important;
  padding: 0 !important; }
.sv-langbar .sv-lang { width: 100% !important; }
.sv-langbar .sv-lang .container > .wrap { border-radius: 999px !important; background: rgba(255,255,255,.85) !important;
  border: 1px solid var(--sv-line) !important; box-shadow: var(--sv-shadow-sm) !important; }
.sv-langbar .sv-lang input { font-size: .85rem !important; cursor: pointer; }
/* Kalıcı marka: satırın en solunda, doğal genişliğinde; boşluk girişler ile marka arasında kalır. */
.sv-langbar > .block.sv-brandbar { flex: 0 0 auto !important; width: auto !important; margin-right: auto;
  align-self: center; }

/* --- Sağdan sola diller (Arapça) ----------------------------------
   Pragmatik orta yol: metin RTL okunur ve sağa hizalanır, sayfa düzeni (ızgara,
   kartların yeri, sekmeler) LTR kalır. Kullanıcının yazdığı metin kutuları
   içeriğin kendi yönünü izler (Türkçe/İngilizce metin yine soldan sağa). */
body.sv-rtl .sv-head > div, body.sv-rtl .sv-tile > div, body.sv-rtl .sv-ethics ul,
body.sv-rtl .sv-hint, body.sv-rtl .sv-note, body.sv-rtl .sv-fine, body.sv-rtl .prose, body.sv-rtl .sv-vmeta,
body.sv-rtl .sv-empty, body.sv-rtl .sv-group-title, body.sv-rtl [data-testid="block-info"],
body.sv-rtl .sv-foot span { direction: rtl; }
body.sv-rtl .sv-head > div, body.sv-rtl .sv-tile > div, body.sv-rtl .sv-hint, body.sv-rtl .sv-fine,
body.sv-rtl .prose, body.sv-rtl .sv-vmeta, body.sv-rtl .sv-empty { text-align: right; }
body.sv-rtl .sv-ethics li { padding-left: 0; padding-right: 22px; }
body.sv-rtl .sv-ethics li::before { left: auto; right: 4px; }
body.sv-rtl textarea, body.sv-rtl input[type="text"] { unicode-bidi: plaintext; text-align: start; }

/* Önizleme: modele gidecek metin */
#preview-box { padding: 11px 14px !important; border-radius: 12px !important; background: var(--sv-soft) !important;
  border: 1px dashed var(--sv-line-2) !important; }
#preview-box p { margin: 0 !important; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .8rem !important; line-height: 1.55 !important; color: var(--sv-muted) !important;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
#preview-box em { font-style: normal; color: var(--sv-ink-2); }

/* Alt eylem çubuğu */
.sv-actionbar { align-items: center !important; justify-content: space-between; flex-wrap: nowrap !important;
  padding-top: 18px; border-top: 1px solid var(--sv-line); gap: 16px !important; }
.sv-hint { font-size: .82rem; line-height: 1.45; color: var(--sv-muted); }
.sv-hint b { color: var(--sv-ink-2); font-weight: 600; }

/* --- Butonlar ------------------------------------------------------ */
.sv-btn { border-radius: 999px !important; font-weight: 600 !important; letter-spacing: -0.005em;
  display: inline-flex !important; flex-direction: row !important; flex-wrap: nowrap !important;
  white-space: nowrap; align-items: center; justify-content: center; gap: 9px;
  transition: transform .15s var(--sv-ease), box-shadow .22s var(--sv-ease), background .2s, color .2s, border-color .2s !important; }
.sv-btn::before { content: ""; width: 17px; height: 17px; flex: none; background: currentColor;
  -webkit-mask: var(--ic) center / contain no-repeat; mask: var(--ic) center / contain no-repeat; }
.sv-btn:active { transform: translateY(0) scale(.98) !important; }
.sv-btn:focus-visible { outline: 2px solid var(--sv-coral) !important; outline-offset: 3px; }

.sv-btn-primary { min-height: 52px; padding: 0 28px !important; font-size: 1rem !important; color: #fff !important;
  background: var(--sv-ink) !important; border: 0 !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.14), 0 10px 22px -10px rgba(23,19,15,.75) !important;
  --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M7 4.5v15l12.5-7.5z' fill='black'/></svg>"); }
.sv-btn-primary:hover { background: #000 !important; transform: translateY(-1px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.14), 0 16px 30px -12px rgba(242,92,59,.75) !important; }
.sv-btn-primary[disabled], .sv-btn-primary.disabled { opacity: .55; transform: none; }

.sv-btn-ghost { width: 100%; min-height: 48px; font-size: .95rem !important; color: var(--sv-ink) !important;
  background: #fff !important; border: 1px solid var(--sv-line-2) !important; box-shadow: var(--sv-shadow-sm) !important;
  --ic: none; }
.sv-btn-ghost::before { display: none; }
.sv-btn-ghost:hover { background: var(--sv-ink) !important; color: #fff !important; border-color: var(--sv-ink) !important;
  transform: translateY(-1px); box-shadow: 0 10px 22px -12px rgba(23,19,15,.7) !important; }

.sv-btn-soft { min-height: 46px; padding: 0 18px !important; font-size: .9rem !important; color: var(--sv-ink) !important;
  background: #FFF3EE !important; border: 1px solid rgba(242,92,59,.28) !important; box-shadow: none !important;
  --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z'/><path d='m13.5 6.5 4 4'/></svg>"); }
.sv-btn-soft:hover { background: #FFE6DC !important; border-color: rgba(242,92,59,.5) !important; transform: translateY(-1px); }
/* Ayarlar (hızlandırma) düğmelerinin ikonları */
.sv-ic-download { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 4v11m-5-5 5 5 5-5M5 20h14'/></svg>"); }
.sv-ic-undo { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M9 14 4 9l5-5'/><path d='M4 9h10.5a5.5 5.5 0 0 1 0 11H11'/></svg>"); }
.sv-ic-refresh { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M20 11a8 8 0 0 0-14.5-4.5L4 8m0-4v4h4M4 13a8 8 0 0 0 14.5 4.5L20 16m0 4v-4h-4'/></svg>"); }
.sv-transcribe-row { align-items: flex-end !important; }

/* --- Sonuç kartı --------------------------------------------------- */
.sv-status { padding: 13px 15px 13px 40px !important; border-radius: 14px !important; position: relative;
  background: var(--sv-soft) !important; border: 1px solid var(--sv-line) !important; }
.sv-status::before { content: ""; position: absolute; left: 17px; top: 19px; width: 8px; height: 8px;
  border-radius: 50%; background: var(--sv-coral); box-shadow: 0 0 0 4px rgba(242,92,59,.16); }
.sv-status p { margin: 0 !important; font-size: .9rem !important; line-height: 1.5 !important; color: var(--sv-ink-2) !important; }
.sv-status strong { color: var(--sv-ink); }
.sv-accel-status p + p { margin-top: 8px !important; }
.sv-accel-log textarea, .sv-report-text textarea { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
  font-size: .76rem !important; line-height: 1.45 !important; }
/* Hata raporu önizlemesi (kullanıcı onayı olmadan hiçbir şey gönderilmez) */
.sv-report { gap: 8px !important; padding: 12px; border-radius: 14px; background: #FFF9F6;
  border: 1px solid rgba(242,92,59,.3); }
.sv-report-actions { flex-wrap: wrap !important; gap: 6px !important; align-items: center !important; }
.sv-report-consent p { margin: 0 !important; font-size: .86rem !important; line-height: 1.5 !important; }
/* Durum kutuları (Sonuç, Adaylar, Klon, Hızlı Mod): Gradio ilerleme göstergesi kutunun içinde, üstte kendi
   satırında; ileti soluklaşmaz ve göstergenin altında kalmaz (1.4.1: "yükleniyor / indirme yapılmaz" okunabilsin). */
.block.sv-status > .pending { opacity: 1 !important; }
.block.sv-status > .wrap { position: relative !important; transform: none !important; inset: auto !important;
  width: auto !important; height: auto !important; min-height: 0 !important; padding: 0 0 6px !important;
  margin: 0 !important; background: transparent !important; border-radius: 0 !important;
  flex-direction: row !important; justify-content: flex-start !important; align-items: center !important; gap: 8px; }
.block.sv-status > .wrap.hide { display: none !important; }
/* elem_classes hem bloğa hem iç .prose'a gider; nokta yalnız içteki kutuda kalsın (ilerleme satırına binmesin). */
.block.sv-status::before { display: none !important; }
.block.sv-status > .wrap .progress-text, .block.sv-status > .wrap .meta-text-center {
  position: static !important; transform: none !important; padding: 0 !important; text-align: left !important;
  justify-content: flex-start !important; font-size: .78rem !important; color: var(--sv-ink-2) !important; }
.block.sv-status > .wrap svg { width: 16px !important; height: 16px !important; margin: 0 !important; }
.block.sv-status > .wrap > div:has(> svg) { margin: 0 !important; line-height: 0; order: -1; }
/* Üretim sürerken (generating) yalnızca nabız çerçevesi: kartın içine tam oturur, kenarı kesmez. */
.block.sv-status > .wrap.generating { position: absolute !important; inset: 0 !important; padding: 0 !important;
  border-radius: inherit !important; }

.sv-card .block.sv-audio, .sv-panel .block.sv-audio {
  min-height: 132px; padding: 10px !important; border-radius: 16px !important; overflow: hidden;
  background: var(--sv-soft) !important; border: 1px dashed var(--sv-line-2) !important;
  transition: border-color .2s, background .2s; }
.sv-panel .block.sv-upload:hover { border-color: rgba(242,92,59,.55) !important; background: #FFF9F6 !important; }
.sv-audio label[data-testid="block-label"] { position: static !important; background: transparent !important;
  border: 0 !important; box-shadow: none !important; padding: 2px 4px 6px !important; font-size: .78rem !important;
  font-weight: 600 !important; color: var(--sv-muted) !important; }
.sv-audio .empty { min-height: 80px; color: #B5ABA3; }
.sv-note { margin: 0; font-size: .8rem; line-height: 1.5; color: var(--sv-muted); text-align: center; }
.sv-fine { margin: -6px 0 0; font-size: .8rem; line-height: 1.5; color: var(--sv-muted); }
.sv-fine b { color: var(--sv-ink-2); font-weight: 600; }

/* --- Sorumlu kullanım --------------------------------------------- */
.sv-ethics ul { margin: 14px 0 0; padding: 0; list-style: none; display: grid; gap: 10px; }
.sv-ethics li { position: relative; padding-left: 22px; font-size: .88rem; line-height: 1.5; color: var(--sv-ink-2); }
.sv-ethics li::before { content: ""; position: absolute; left: 4px; top: .55em; width: 6px; height: 6px;
  border-radius: 50%; background: var(--sv-coral); }

/* --- Bilgi kutucukları ve alt bilgi ------------------------------- */
.sv-info { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 34px; }
.sv-tile { display: flex; gap: 13px; align-items: flex-start; padding: 16px 18px; border-radius: 18px;
  background: rgba(255,255,255,.62); border: 1px solid var(--sv-line); transition: background .2s, transform .2s var(--sv-ease); }
.sv-tile:hover { background: #fff; transform: translateY(-2px); }
.sv-tile b { display: block; font-size: .9rem; font-weight: 650; color: var(--sv-ink); margin-bottom: 3px; }
.sv-tile span { font-size: .82rem; line-height: 1.45; color: var(--sv-muted); }
.sv-tile-ic { flex: none; display: grid; place-items: center; width: 34px; height: 34px; border-radius: 11px;
  background: var(--sv-grad); color: #fff; }
.sv-tile-ic .sv-ic { width: 17px; height: 17px; }
.sv-foot { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 10px 14px;
  margin-top: 34px; padding-top: 22px; border-top: 1px solid var(--sv-line); font-size: .8rem; color: var(--sv-muted); }
.sv-foot i { width: 3px; height: 3px; border-radius: 50%; background: currentColor; opacity: .6; }
.sv-brand-sm { font-size: .8rem; gap: 8px; }
.sv-brand-sm .sv-logo { width: 26px; height: 26px; border-radius: 8px; }
.sv-brand-sm .sv-logo .sv-ic { width: 14px; height: 14px; }

/* İlerleme göstergesi rengi */
.gradio-container .progress-bar { background: var(--sv-grad) !important; }

/* --- Ses kütüphanesi kartları ------------------------------------- */
.sv-cards { gap: 12px !important; }
.sv-group-title { display: flex; align-items: center; gap: 8px; margin: 2px 2px -4px; font-size: .74rem;
  font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--sv-muted); }
.sv-group-title span { display: inline-grid; place-items: center; min-width: 20px; height: 20px; padding: 0 6px;
  border-radius: 999px; background: var(--sv-soft); border: 1px solid var(--sv-line); font-size: .7rem;
  letter-spacing: 0; color: var(--sv-ink-2); }
.sv-empty { margin: 0; padding: 14px 16px; border-radius: 16px; border: 1px dashed var(--sv-line-2);
  font-size: .85rem; line-height: 1.5; color: var(--sv-muted); background: var(--sv-soft); }
.sv-vgrid { flex-wrap: wrap !important; gap: 10px !important; }
.sv-panel .sv-vcard, .sv-vcard { flex: 1 1 200px !important; min-width: 180px !important; gap: 10px !important;
  padding: 14px !important; border-radius: 18px !important; background: var(--sv-soft) !important;
  border: 1px solid var(--sv-line) !important; transition: background .2s, border-color .2s, box-shadow .2s, transform .2s var(--sv-ease); }
.sv-vcard:hover { background: #fff !important; transform: translateY(-1px); box-shadow: var(--sv-shadow-sm); }
.sv-vcard.is-selected { background: #fff !important; border-color: var(--sv-ink) !important;
  box-shadow: 0 0 0 1px var(--sv-ink), 0 14px 30px -20px rgba(23,19,15,.6) !important; }
.sv-vmeta h4 { margin: 6px 0 2px; font-size: .98rem; font-weight: 650; letter-spacing: -0.01em; color: var(--sv-ink); }
.sv-vmeta p { margin: 0; font-size: .8rem; line-height: 1.45; color: var(--sv-muted); }
.sv-cat { display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: .68rem; font-weight: 650;
  letter-spacing: .02em; color: #B4432A; background: #FFF3EE; border: 1px solid rgba(242,92,59,.25); }
.sv-vcard-actions, .sv-cand-actions, .sv-templates, .sv-confirm { flex-wrap: wrap !important; gap: 6px !important;
  align-items: center !important; }
.sv-btn.sv-mini { min-height: 34px; min-width: 0 !important; width: auto !important; flex: 0 0 auto !important;
  padding: 0 13px !important; font-size: .82rem !important; color: var(--sv-ink) !important; background: #fff !important;
  border: 1px solid var(--sv-line-2) !important; box-shadow: none !important; --ic: none; }
.sv-btn.sv-mini::before { display: none; }
.sv-btn.sv-mini:hover { border-color: var(--sv-ink) !important; transform: translateY(-1px); }
.sv-btn.sv-mini-dark { background: var(--sv-ink) !important; color: #fff !important; border-color: var(--sv-ink) !important; }
.sv-btn.sv-mini-danger:hover { border-color: #D8452A !important; color: #C23A20 !important; }
.sv-confirm { padding: 10px 12px; border-radius: 14px; background: #FFF3EE; border: 1px solid rgba(242,92,59,.3); }
.sv-confirm p { margin: 0 !important; font-size: .88rem !important; }
.sv-fine-md p { margin: 0 !important; font-size: .82rem !important; line-height: 1.5 !important; color: var(--sv-muted) !important; }
.sv-fine-md strong { color: var(--sv-ink-2); }
.sv-card .block.sv-sample, .sv-panel .block.sv-sample { min-height: 0; }
/* Duygu hapları dışındaki seçim grupları: renk noktası yok. */
.sv-emotion.sv-plain .wrap label::before { display: none; }
.sv-emotion.sv-plain .wrap label { padding: 7px 14px !important; font-size: .86rem !important; }

/* --- Ses tasarımı -------------------------------------------------- */
.sv-sliders { flex-wrap: wrap !important; gap: 14px !important; }
.sv-sliders > * { flex: 1 1 200px !important; }
.sv-panel .sv-sliders [data-testid="block-info"] + span, .sv-panel .sv-sliders .info,
.sv-panel [data-testid="block-info"] ~ div[class*="info"] { font-size: .74rem !important; color: var(--sv-muted) !important; }
.sv-warn p { margin: 0 !important; padding: 9px 13px; border-radius: 12px; background: #FFF8E6;
  border: 1px solid rgba(214,158,20,.35); font-size: .84rem !important; line-height: 1.5 !important; color: #6B4E06 !important; }
.sv-warn:empty, .sv-warn p:empty { display: none; }
.sv-part { display: inline-block; margin: 0 6px 6px 0; padding: 4px 10px; border-radius: 999px; cursor: help;
  background: #fff; border: 1px solid var(--sv-line-2); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .78rem; color: var(--sv-ink-2); }
.sv-part:hover { border-color: var(--sv-coral); color: var(--sv-ink); }
.sv-acc { border: 1px solid var(--sv-line) !important; border-radius: 16px !important; background: var(--sv-soft) !important;
  padding: 10px 14px !important; }
.sv-acc > button, .sv-acc .label-wrap { font-size: .86rem !important; font-weight: 600 !important; color: var(--sv-ink-2) !important; }
/* Adaylar: tek sütun liste. Her kart: başlık (aday · seed · süre), sade oynatıcı (oynat/duraklat +
   dalga + süre; ses, hız, atla düğmeleri yok) ve altta seed kutusu + Yeniden üret + Bunu seç.
   ~400-550 px panelde ve dar pencerede taşma/kaydırma çubuğu olmasın diye her şey min-width: 0. */
.sv-cgrid { flex-direction: column !important; flex-wrap: nowrap !important; gap: 8px !important; }
.sv-cand { flex: 0 0 auto !important; width: 100% !important; min-width: 0 !important; gap: 6px !important;
  padding: 10px 12px !important; border-radius: 16px !important; background: var(--sv-soft) !important;
  border: 1px solid var(--sv-line) !important; }
.sv-cand > * { min-width: 0 !important; }
.sv-cand-label p { margin: 0 !important; font-size: .8rem !important; font-weight: 600; color: var(--sv-ink-2) !important;
  overflow-wrap: anywhere; }
.sv-card .block.sv-cand-audio { min-height: 0 !important; padding: 4px 10px !important; background: #fff !important;
  border-style: solid !important; overflow: hidden; }
.sv-cand-audio .empty { min-height: 40px !important; }
.sv-cand-audio .component-wrapper { display: grid !important; grid-template-columns: 32px minmax(0, 1fr) auto;
  align-items: center; column-gap: 10px; padding: 0 !important; min-height: 44px; direction: ltr; }
.sv-cand-audio .controls, .sv-cand-audio .play-pause-wrapper { display: contents !important; }
.sv-cand-audio .control-wrapper, .sv-cand-audio .settings-wrapper, .sv-cand-audio .rewind,
.sv-cand-audio .skip, .sv-cand-audio .subtitle-display { display: none !important; }
.sv-cand-audio .play-pause-button { grid-column: 1; grid-row: 1; width: 32px !important; height: 32px !important;
  margin: 0 !important; }
.sv-cand-audio .waveform-container { grid-column: 2; grid-row: 1; min-width: 0 !important; width: 100% !important;
  height: 40px !important; margin: 0 !important; }
.sv-cand-audio #waveform, .sv-cand-audio #waveform > div { min-width: 0 !important; width: 100% !important; }
.sv-cand-audio .timestamps { grid-column: 3; grid-row: 1; display: flex !important; gap: 4px; margin: 0 !important;
  padding: 0 !important; font-size: .74rem !important; color: var(--sv-muted) !important; white-space: nowrap; }
.sv-cand-audio .timestamps time { font-variant-numeric: tabular-nums; }
.sv-cand-audio #duration::before { content: "/ "; }
.sv-card .row.sv-cand-row { flex-wrap: wrap !important; gap: 6px !important; align-items: center !important; }
.sv-cand-row > * { min-width: 0 !important; }
.sv-seed { flex: 0 1 auto !important; width: auto !important; }
.sv-seed label { display: flex !important; align-items: center !important; gap: 6px !important; margin: 0 !important; }
/* container=False Gradio'da etiketi yalnız ekran okuyucuya bırakır (sr-only); "Seed" görünür kalsın. */
.sv-seed [data-testid="block-info"], .sv-seed [data-testid="block-info"].sr-only, .sv-seed [data-testid="block-info"].hide {
  display: inline !important; position: static !important; width: auto !important; height: auto !important;
  clip: auto !important; clip-path: none !important; overflow: visible !important; margin: 0 !important;
  font-size: .74rem !important; font-weight: 600 !important; color: var(--sv-muted) !important; white-space: nowrap; }
.sv-seed .input-container { flex: 0 1 auto !important; min-width: 0; }
.sv-seed input { width: 13ch !important; min-width: 9ch !important; flex: 0 1 auto !important; height: 34px !important; padding: 4px 8px !important; border-radius: 10px !important;
  background: #fff !important; border: 1px solid var(--sv-line-2) !important; box-shadow: none !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important; font-size: .82rem !important;
  direction: ltr; }
.sv-seed input:focus { border-color: var(--sv-coral) !important; box-shadow: inset 0 0 0 1px var(--sv-coral) !important; }
.sv-seed.block { background: transparent !important; border: 0 !important; padding: 0 !important; }
.sv-cand-row .sv-btn.sv-mini { flex: 0 1 auto !important; white-space: nowrap; }
.sv-cand-row .sv-cand-pick { margin-inline-start: auto; }
.sv-seed-note { margin: -4px 0 0 !important; }
.sv-save { gap: 12px !important; padding: 16px !important; border-radius: 18px !important; background: #fff !important;
  border: 1px solid var(--sv-ink) !important; }
.sv-fx-row { flex-wrap: nowrap !important; align-items: center !important; gap: 10px !important; }
.sv-fx .sv-acc { margin-bottom: 4px; }

/* --- Dosya yükleme -------------------------------------------------- */
.sv-panel .block.sv-file { min-height: 120px; padding: 10px !important; border-radius: 16px !important;
  background: var(--sv-soft) !important; border: 1px dashed var(--sv-line-2) !important; }
.sv-panel .block.sv-file:hover { border-color: rgba(242,92,59,.55) !important; background: #FFF9F6 !important; }
.sv-consent label { font-size: .9rem !important; font-weight: 600 !important; color: var(--sv-ink) !important; }

/* --- Mobil --------------------------------------------------------- */
@media (max-width: 860px) {
  .sv-panel { padding: 20px 18px 18px !important; }
  .sv-card { padding: 20px !important; }
  .sv-actionbar { flex-wrap: wrap !important; }
  .sv-actionbar > * { flex: 1 1 100% !important; }
  .sv-actionbar .sv-btn-primary { width: 100%; }
  .sv-transcribe-row { flex-wrap: wrap !important; }
  .sv-info { grid-template-columns: 1fr; }
  #sv-tabs [role="tab"] { padding: 9px 13px 9px 11px !important; font-size: .86rem !important; gap: 6px; }
  #sv-tabs [role="tab"]::before { width: 15px; height: 15px; }
  .sv-fx-row { flex-wrap: wrap !important; }
  .sv-vcard { flex: 1 1 100% !important; }
}
@media (max-width: 480px) {
  #sv-tabs > .tab-wrapper { max-width: 100%; min-width: 0; }
  #sv-tabs .tab-container[role="tablist"] { max-width: 100%; min-width: 0; flex-wrap: wrap; justify-content: center;
    gap: 2px; padding: 4px; }
  #sv-tabs > .tab-wrapper [role="tab"] { padding: 8px 10px !important; font-size: .78rem !important; flex: none; }
  /* Üç sekme 390 px'te tek satıra sığsın: dar ekranda ikonlar gizlenir (sığmazsa alt satıra geçer). */
  #sv-tabs > .tab-wrapper [role="tab"]::before { display: none !important; }
}
/* Güncelleme bildirimi: göze batmayan tek satırlık bilgi şeridi (guncelleme.py). */
.sv-update { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: center; gap: 4px 10px;
  margin: 0 auto 14px; padding: 8px 14px; max-width: 720px; border-radius: 12px; font-size: .84rem;
  line-height: 1.45; color: var(--sv-ink-2); background: var(--sv-paper); border: 1px solid var(--sv-line);
  box-shadow: var(--sv-shadow-sm); }
.sv-update b { font-weight: 650; color: var(--sv-ink); }
.sv-update a { color: var(--sv-coral); font-weight: 600; text-decoration: underline; text-underline-offset: 2px; }
.sv-update-note { flex-basis: 100%; text-align: center; color: var(--sv-muted); font-size: .8rem; }
/* Ayarlar → "Güncellemeleri şimdi denetle" sonucu: kartın içinde, sola (RTL'de sağa) hizalı. */
.sv-update-now { align-self: flex-start; }
.sv-update-result .sv-update { margin: 2px 0 0; max-width: none; justify-content: flex-start; box-shadow: none;
  background: var(--sv-soft); }
.sv-update-result .sv-update-note { text-align: start; }
.sv-update-result .sv-update-ok b { color: #1F7A4D; }
.sv-update-result .sv-update-err b { color: #B3361C; }
/* Sonuç kartında ses hazır olunca çıkan "Efekt ekle" girişi (ikon: Efektler kartınınki). */
.sv-fx-jump { align-self: flex-start; }
.sv-ic-fx { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M4 7h10M18 7h2M4 17h2M10 17h10'/><circle cx='16' cy='7' r='2'/><circle cx='8' cy='17' r='2'/></svg>"); }

/* --- Sağ üst: Kuyruk ve Ayarlar girişleri (dil seçicinin solunda) ---------------------
   Kuyruk ve Ayarlar birer gizli sekmedir: sekme düğmeleri CSS ile gizlenir, sağ üstteki
   girişler sekmeyi seçer. Açık olan görünümün girişi seçili sekme gibi koyu görünür. */
#sv-tab-kuyruk-button, #sv-tab-ayarlar-button { display: none !important; }
.sv-langbar > .sv-topnav { flex: 0 0 auto !important; width: auto !important; gap: 8px !important;
  align-self: flex-end; flex-wrap: nowrap !important; background: transparent !important; border: 0 !important; }
.sv-btn.sv-topbtn { min-height: 40px; min-width: 0 !important; padding: 0 15px 0 13px !important; font-size: .86rem !important;
  color: var(--sv-ink-2) !important; background: rgba(255,255,255,.85) !important; border: 1px solid var(--sv-line) !important;
  box-shadow: var(--sv-shadow-sm) !important; gap: 7px; font-variant-numeric: tabular-nums; }
.sv-btn.sv-topbtn::before { width: 16px; height: 16px; }
.sv-topnav > .sv-topbtn { flex: 0 0 auto !important; width: auto !important; }
.sv-btn.sv-topbtn:hover { color: var(--sv-ink) !important; border-color: var(--sv-line-2) !important; transform: translateY(-1px); }
.sv-top-kuyruk { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M4 6.5h11M4 12h11M4 17.5h6'/><path d='m15.5 14.5 5 3-5 3z'/></svg>"); }
.sv-top-ayarlar { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='3'/><path d='M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1'/></svg>"); }
.sv-top-kuyruk:not(.is-empty)::after { content: ""; width: 7px; height: 7px; border-radius: 50%; flex: none;
  background: #B9B0A8; }
.sv-top-kuyruk.is-running { color: var(--sv-ink) !important; border-color: rgba(242,92,59,.45) !important; }
.sv-top-kuyruk.is-running::after { background: var(--sv-coral); box-shadow: 0 0 0 3px rgba(242,92,59,.18);
  animation: sv-pulse 1.6s ease-in-out infinite; }
.sv-top-kuyruk.is-done::after { background: #2DBE6C; }
.sv-top-kuyruk.is-error::after { background: #D8452A; }
@keyframes sv-pulse { 50% { opacity: .35; } }
@media (prefers-reduced-motion: reduce) { .sv-top-kuyruk.is-running::after { animation: none; } }
body:has(#sv-tab-kuyruk-button[aria-selected="true"]) .sv-btn.sv-top-kuyruk,
body:has(#sv-tab-ayarlar-button[aria-selected="true"]) .sv-btn.sv-top-ayarlar {
  color: #fff !important; background: var(--sv-ink) !important; border-color: var(--sv-ink) !important;
  box-shadow: 0 6px 16px -8px rgba(23,19,15,.7) !important; }

/* --- Kuyruk görünümü (taslak A) ---------------------------------------------------- */
.sv-btn-queue { min-height: 52px; padding: 0 20px !important; font-size: .95rem !important; color: var(--sv-ink) !important;
  background: #fff !important; border: 1px solid var(--sv-line-2) !important; box-shadow: var(--sv-shadow-sm) !important;
  --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.2' stroke-linecap='round'><path d='M12 5v14M5 12h14'/></svg>"); }
.sv-btn-queue:hover { border-color: var(--sv-ink) !important; transform: translateY(-1px); }
.sv-btn-queue[disabled] { opacity: .5; transform: none; }
.sv-btn.sv-no-ic::before { display: none; }
.sv-ic-plus { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.2' stroke-linecap='round'><path d='M12 5v14M5 12h14'/></svg>"); }
.sv-ic-pause { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><rect x='6.5' y='5' width='4' height='14' rx='1' fill='black'/><rect x='13.5' y='5' width='4' height='14' rx='1' fill='black'/></svg>"); }
.sv-ic-upload { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M12 16V4m-5 5 5-5 5 5M5 20h14'/></svg>"); }
.sv-btn-soft.sv-ic-upload { width: 100%; }
.sv-btn.sv-template { align-self: flex-start; color: var(--sv-coral) !important; }
.sv-qview { display: flex; flex-direction: column; gap: 14px; }
/* Kuyruk eylem çubuğu: "Kuyruğu boşalt" görününce açıklama daralmasın, düğmeler alt satıra geçsin. */
.sv-actionbar.sv-qactions { flex-wrap: wrap !important; justify-content: flex-end; row-gap: 12px !important; }
.sv-actionbar.sv-qactions > :first-child { flex: 1 1 240px !important; min-width: 240px !important; }
.sv-qview .sv-qwarnbox { margin-top: 0; }
.sv-qsummary { display: flex; flex-wrap: wrap; gap: 8px; }
.sv-qstat { display: inline-flex; align-items: baseline; gap: 6px; padding: 7px 12px; border-radius: 999px;
  background: var(--sv-soft); border: 1px solid var(--sv-line); font-size: .82rem; color: var(--sv-muted); }
.sv-qstat b { font-size: 1rem; font-weight: 700; color: var(--sv-ink); font-variant-numeric: tabular-nums; }
.sv-qnote, .sv-qwarnbox { padding: 10px 13px; border-radius: 12px; background: #FFF8E6;
  border: 1px solid rgba(214,158,20,.35); font-size: .84rem; line-height: 1.5; color: #6B4E06; }
.sv-qwarnbox { margin-top: 10px; }
.sv-qlist { border: 1px solid var(--sv-line); border-radius: 16px; overflow: hidden; background: #fff; }
.sv-qrow { display: grid; grid-template-columns: 28px minmax(0, 1fr) 118px auto; align-items: center; gap: 12px;
  padding: 12px 14px; border-top: 1px solid var(--sv-line); }
.sv-qrow:first-child { border-top: 0; }
.sv-qrow.is-run { background: #FFF9F6; box-shadow: inset 3px 0 0 var(--sv-coral); }
.sv-qrow.is-err { background: #FFFBFA; }
.sv-qno { font-size: .8rem; font-weight: 700; color: var(--sv-muted); font-variant-numeric: tabular-nums; }
.sv-qmain { min-width: 0; }
.sv-qtext { font-size: .92rem; font-weight: 600; line-height: 1.4; color: var(--sv-ink); overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow-wrap: anywhere; }
.sv-qmeta { margin-top: 3px; font-size: .76rem; line-height: 1.5; color: var(--sv-muted); overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow-wrap: anywhere; }
.sv-qfile { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .72rem; color: var(--sv-ink-2); }
.sv-qerr { color: #B3261E; font-weight: 600; }
.sv-qwarn { color: #8A5A00; font-weight: 600; }
.sv-qparts { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 7px; }
.sv-qparts i { width: 14px; height: 4px; border-radius: 2px; background: rgba(23,19,15,.12); }
.sv-qparts i.d { background: #F4A58E; }
.sv-qparts i.a { background: var(--sv-coral); }
.sv-qstate { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; min-width: 0; }
.sv-qtime { font-size: .74rem; color: var(--sv-muted); font-variant-numeric: tabular-nums; }
.sv-qbadge { display: inline-flex; align-items: center; gap: 5px; padding: 2px 9px; border-radius: 999px;
  font-size: .72rem; font-weight: 650; white-space: nowrap; border: 1px solid var(--sv-line-2); }
.sv-qbadge::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.sv-qbadge.b-ok { color: #17824A; background: #EFFAF3; border-color: rgba(23,130,74,.25); }
.sv-qbadge.b-err { color: #B3261E; background: #FFF1EF; border-color: rgba(179,38,30,.25); }
.sv-qbadge.b-run { color: #B4432A; background: #FFF3EE; border-color: rgba(242,92,59,.35); }
.sv-qbadge.b-wait { color: var(--sv-muted); background: var(--sv-soft); }
.sv-qbadge.b-long { color: #5B4BC4; background: #F3F0FF; border-color: rgba(91,75,196,.25); margin-right: 2px; }
.sv-qbadge.b-long::before { display: none; }
.sv-qact { display: flex; gap: 6px; justify-content: flex-end; }
.sv-qicon { display: grid; place-items: center; width: 32px; height: 32px; padding: 0; border-radius: 10px;
  border: 1px solid var(--sv-line-2); background: #fff; color: var(--sv-ink); cursor: pointer;
  transition: border-color .15s, transform .15s var(--sv-ease); }
.sv-qicon svg { width: 15px; height: 15px; }
.sv-qicon:hover:not([disabled]), .sv-qmini:hover { border-color: var(--sv-ink); transform: translateY(-1px); }
.sv-qicon:focus-visible, .sv-qmini:focus-visible { outline: 2px solid var(--sv-coral); outline-offset: 2px; }
.sv-qicon[disabled] { opacity: .35; cursor: default; }
.sv-qmini { min-height: 32px; padding: 0 12px; border-radius: 999px; border: 1px solid var(--sv-line-2); background: #fff;
  font-size: .8rem; font-weight: 600; color: var(--sv-ink); cursor: pointer; white-space: nowrap; }
.sv-qempty { padding: 18px; border-radius: 16px; border: 1px dashed var(--sv-line-2); background: var(--sv-soft);
  font-size: .88rem; line-height: 1.55; color: var(--sv-muted); }
.sv-qempty b { color: var(--sv-ink-2); }
.sv-qnow { margin-top: 14px; padding: 12px 14px; border-radius: 14px; background: var(--sv-soft);
  border: 1px solid var(--sv-line); font-size: .86rem; line-height: 1.55; color: var(--sv-ink-2); }
.sv-qbar { height: 6px; margin-top: 14px; border-radius: 999px; background: rgba(23,19,15,.08); overflow: hidden; }
.sv-qbar i { display: block; height: 100%; border-radius: inherit; background: var(--sv-grad); }
.sv-qfine { margin: 8px 0 0; font-size: .78rem; line-height: 1.5; color: var(--sv-muted); }
.sv-qfine b { color: var(--sv-ink-2); }
.sv-qok { margin-top: 14px; padding: 11px 13px; border-radius: 12px; background: #EFFAF3;
  border: 1px solid rgba(23,130,74,.25); font-size: .84rem; line-height: 1.5; color: #17502F; }
.sv-card .sv-head + .sv-qfine { margin-top: 12px; }
.sv-qbanner { max-width: 760px; margin: 0 auto 14px !important; padding: 8px 10px 8px 16px !important;
  border-radius: 14px; background: #FFF3EE !important; border: 1px solid rgba(242,92,59,.3) !important;
  align-items: center !important; gap: 8px !important; flex-wrap: wrap !important; }
.sv-qbanner > :first-child { flex: 1 1 260px !important; font-size: .86rem; line-height: 1.45; color: var(--sv-ink-2); }
/* İçe aktarma önizlemesi (taslak D) */
.sv-import { margin-bottom: 22px; }
.sv-import-top { justify-content: space-between !important; align-items: flex-start !important; flex-wrap: nowrap !important; }
.sv-import-cols { flex-wrap: wrap !important; gap: 12px !important; align-items: flex-start !important; }
.sv-import-cols > * { flex: 1 1 180px !important; }
.sv-ifile { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 16px;
  background: var(--sv-soft); border: 1px dashed var(--sv-line-2); font-size: .92rem; }
.sv-ifile .sv-qfine { margin: 2px 0 0; }
.sv-ifi { flex: none; display: grid; place-items: center; width: 38px; height: 38px; border-radius: 12px;
  background: var(--sv-grad); color: #fff; font-weight: 700; font-size: .72rem; }
.sv-itable { border: 1px solid var(--sv-line); border-radius: 16px; overflow: auto; max-height: 460px; }
.sv-itable table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: .84rem; }
.sv-itable th { position: sticky; top: 0; text-align: start; font-size: .7rem; letter-spacing: .06em;
  text-transform: uppercase; color: var(--sv-muted); font-weight: 700; padding: 9px 10px; background: var(--sv-soft);
  border-bottom: 1px solid var(--sv-line); }
.sv-itable td { padding: 9px 10px; border-bottom: 1px solid var(--sv-line); vertical-align: middle; color: var(--sv-ink-2); }
.sv-itable tr:last-child td { border-bottom: 0; }
.sv-itable td.t { max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--sv-ink);
  font-weight: 550; }
.sv-itable tr.rej td { background: #FFFBFA; }
.sv-itable tr.over td { color: var(--sv-muted); background: #FAFAF8; }
.sv-ireason { color: #B3261E; font-weight: 600; }
body.sv-rtl .sv-qmeta, body.sv-rtl .sv-qempty, body.sv-rtl .sv-qnow, body.sv-rtl .sv-qfine, body.sv-rtl .sv-qok,
body.sv-rtl .sv-qwarnbox, body.sv-rtl .sv-qnote, body.sv-rtl .sv-qbanner span, body.sv-rtl .sv-qtime,
body.sv-rtl .sv-itable { direction: rtl; text-align: right; }
@media (max-width: 860px) {
  .sv-qrow { grid-template-columns: 26px minmax(0, 1fr) auto; row-gap: 6px; }
  .sv-qstate { grid-column: 2; grid-row: 2; flex-direction: row; align-items: center; gap: 8px; }
  .sv-qact { grid-column: 3; grid-row: 1 / span 2; }
  .sv-import-top { flex-wrap: wrap !important; }
}
@media (max-width: 480px) {
  .sv-qrow { grid-template-columns: 22px minmax(0, 1fr); }
  .sv-qact { grid-column: 2; grid-row: 3; justify-content: flex-start; }
  .sv-langbar > .form { flex: 1 1 130px !important; width: auto !important; }
  .sv-btn.sv-topbtn { padding: 0 11px !important; font-size: .8rem !important; }
  .sv-btn.sv-topbtn::before { display: none; }
}
"""

_THEME = gr.themes.Base(
    primary_hue="orange",
    neutral_hue="stone",
    font=["Inter", "-apple-system", "BlinkMacSystemFont", "SF Pro Text", "Segoe UI", "Roboto",
          "Helvetica Neue", "Arial", "sans-serif"],
    font_mono=["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
).set(
    body_background_fill="#F4F1EC",
    body_text_color="#17130F",
    color_accent="#F25C3B",
    color_accent_soft="#FFE6DC",
    loader_color="#F25C3B",
    slider_color="#F25C3B",
)

# Tasarım açık renk için kurgulandı; sistem karanlık modda olsa da açık kalsın.
# Üretim olayları gr.Progress(track_tqdm=True) KULLANMAZ: Gradio kütüphanelerin tqdm çubuklarını
# (huggingface_hub'ın "Downloading bytes"/"Reconstructing" baytları, VoxCPM'in adımları) durum
# satırına ham "0/0 B | 0/0 B | 6.4s" olarak basıyordu (1.4.0, model önbellekteyken bile). İlerleme
# yalnız kendi temiz metnimizle verilir (bkz. _modeli_hazirla). Aşağıdaki süpürge ikinci savunmadır:
# yine de sızan ham, teknik ilerleme metnini hangi sınıfı kullanırsa kullansın tarayıp gizler.
# Desen tek kaynaktır (_HAM_ILERLEME); tests/test_app.py örneklerle (ve kendi iletilerimizin
# eşleşmediğini) sınar.
_HAM_ILERLEME = (r"Downloading bytes|Reconstructing|Fetching \d+ files|/\s*\d+\s*steps"
                 r"|\d[\d.]*[kMGT]?/\d[\d.]*[kMGT]?\s*(?:B|it)\b")
_JS = """() => {
    document.querySelectorAll('.dark').forEach((el) => el.classList.remove('dark'));
    const raw = new RegExp(%s);
    function sweep() {
        document.querySelectorAll('body *').forEach((el) => {
            const t = el.textContent || '';
            if (t.length < 300 && raw.test(t)) {
                const childMatch = [...el.children].some((c) => raw.test(c.textContent || ''));
                if (!childMatch) el.style.display = 'none';
            }
        });
    }
    new MutationObserver(sweep).observe(document.body, { childList: true, subtree: true, characterData: true });
    setInterval(sweep, 150);
}""" % json.dumps(_HAM_ILERLEME)


def _frame_bar(chips):
    inner = "".join(f'<span class="sv-chip">{c}</span>' for c in chips)
    return _html(f'<div class="sv-frame-bar"><div class="sv-chips">{inner}</div>'
                 f'<span class="sv-chip sv-chip-dark">{_svg(_IC_LOCK)}{t("Yerel")}</span></div>')


def _card_html(voice):
    # Hazır seslerin meta verisi Türkçe yazılmıştır; arayüz diline çevrilir (kendi sesleriniz olduğu gibi kalır).
    tr_ = t if voice.get("hazir") or voice.get("id") == RANDOM_VOICE else (lambda s: s)
    return (f'<div class="sv-vmeta"><span class="sv-cat">{escape(tr_(voice["kategori"] or "Genel"))}</span>'
            f'<h4>{escape(_voice_name(voice))}</h4><p>{escape(tr_(voice["aciklama"] or ""))}</p></div>')


def _library_tab(demo):
    """Ses Kütüphanesi: kartlar (Hazır sesler | Seslerim), üretim ve efektler."""
    lang = i18n.get_lang()  # bu sayfanın arayüz dili (gr.render sonradan da bu dilde çizer)
    with gr.Row(equal_height=False, elem_classes=["sv-grid"]):
        with gr.Column(scale=7, min_width=340, elem_classes=["sv-frame"]):
            _frame_bar([f"{_svg(_IC_LIB)}{t('Ses kütüphanesi')}", t("Türkçe")])
            with gr.Column(elem_classes=["sv-panel"]):
                voices = gr.State(_voice_list())
                selected = gr.State(RANDOM_VOICE)
                pending = gr.State(None)
                _head(None, t("Bir ses seçin"),
                      t("Kayıtlı bir sesle her üretimde aynı kişi konuşur. ▶ ile 3 saniyelik örneği dinleyin."),
                      step="1")
                cards_slot = gr.Column(elem_classes=["sv-cards"])
                lib_msg = gr.Markdown("", elem_classes=["sv-fine-md"])
                with gr.Row(visible=False, elem_classes=["sv-confirm"]) as confirm_row:
                    confirm_md = gr.Markdown()
                    confirm_yes = gr.Button(t("Evet, sil"), size="sm", scale=0,
                                            elem_classes=["sv-btn", "sv-mini", "sv-mini-danger"])
                    confirm_no = gr.Button(t("Vazgeç"), size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
                # Gradio 6 gr.Audio varsayılanı buttons=["download", "share"]; "share" sesi herkese açık
                # Hugging Face Discussions'a yüklemeye çalışır (yerellik vaadiyle çelişir, Spaces dışında
                # "Error" verir). Bu yüzden her gr.Audio'da yalnız "download" açık bırakılır.
                sample = gr.Audio(label=t("Örnek dinleme (3 sn)"), type="filepath", interactive=False,
                                  autoplay=True, buttons=["download"], elem_classes=["sv-audio", "sv-sample"])
                _html('<div class="sv-divider"></div>')
                _head(None, t("Metninizi yazın"),
                      t("Kayıtlı seste duygu seçmeyin: ses “Devam” kipinde en yüksek benzerlikle sürer."), step="2")
                text = gr.Textbox(label=t("Metin"), lines=5, max_length=kq.OGE_METIN_EN_FAZLA, value=t(_SAMPLE_TEXT),
                                  placeholder=t("Seslendirilecek metni buraya yazın…"),
                                  info=t("Hangi dilde yazarsanız o dilde okur."), elem_classes=["sv-lang-hint"])
                quality = gr.Radio(choices=_choices(QUALITY), value="Dengeli", label=t("Kalite"),
                                   elem_classes=["sv-emotion", "sv-plain"])
                emotion = gr.Radio(choices=_choices(EMOTIONS), value="Nötr", label=t("Duygu / ton (isteğe bağlı)"),
                                   elem_classes=["sv-emotion"])
                mode_md = gr.Markdown(elem_id="preview-box")
                with gr.Row(elem_classes=["sv-actionbar"]):
                    _html('<div class="sv-hint">' + t("<b>Üret: en fazla 500 karakter.</b><br>"
                                                      "Kuyruğa ekle: 10.000 karaktere kadar.") + "</div>")
                    queue_add = gr.Button(t("Kuyruğa ekle"), scale=0, min_width=150,
                                          elem_classes=["sv-btn", "sv-btn-queue"])
                    button = gr.Button(t("Üret"), variant="primary", scale=0, min_width=170,
                                       elem_classes=["sv-btn", "sv-btn-primary"])
        with gr.Column(scale=5, min_width=300, elem_classes=["sv-side"]):
            with gr.Column(elem_classes=["sv-card"]):
                _head(*_result_head())
                status = gr.Markdown(t("Hazır. Bir ses seçip metninizi yazın ve Üret'e basın."),
                                     elem_classes=["sv-status"])
                report_button = _report_panel(lang)
                audio = gr.Audio(label=t("Üretilen ses (AI ile üretildi)"), type="filepath", interactive=False,
                                 buttons=["download"], elem_classes=["sv-audio"])
                download = gr.DownloadButton(t("⬇ WAV indir"), variant="secondary",
                                             elem_classes=["sv-btn", "sv-btn-ghost"])
                # Efektler sağ sütunun altında, kapalı başlıyordu; kullanıcı fark etmiyordu (1.4.1).
                # Ses hazır olunca burada bir giriş çıkar: efekt ayarlarını açar ve oraya kaydırır.
                fx_jump = gr.Button(t("Efekt ekle"), visible=False, size="sm",
                                    elem_classes=["sv-btn", "sv-btn-soft", "sv-ic-fx", "sv-fx-jump"])
                _html(_result_note())
            with gr.Column(elem_classes=["sv-card", "sv-fx"]):
                _head(_IC_FX, t("Efektler"),
                      t("Cızırtı, eski radyo, telefon, telsiz, oda yankısı ve megafon. Üretimden sonra uygulanır; "
                        "ham ses değişmez. Ayar değiştikçe önizleme yenilenir."))
                with gr.Accordion(t("Efekt ayarları"), open=False, elem_classes=["sv-acc"]) as fx_acc:
                    fx_controls = []
                    room = None
                    for key, label in fx.EFFECTS.items():
                        with gr.Row(elem_classes=["sv-fx-row"]):
                            on = gr.Checkbox(label=t(label), value=False, scale=2, min_width=150)
                            level = gr.Slider(0, 100, value=50, step=5, label=t("Yoğunluk"), scale=3, min_width=160)
                        fx_controls += [on, level]
                        if key == "oda":
                            room = gr.Radio(choices=[(t(v[0]), k) for k, v in fx.ROOM_PRESETS.items()],
                                            value="salon", label=t("Oda ön ayarı"),
                                            elem_classes=["sv-emotion", "sv-plain"])
                    fx_controls.append(room)
                    fx_preset = gr.Button(t("Bu sese ön ayar olarak kaydet"), size="sm",
                                          elem_classes=["sv-btn", "sv-mini"])
                fx_status = gr.Markdown(t("Efekt kapalı; ham ses olduğu gibi kullanılıyor."),
                                        elem_classes=["sv-status"])
                fx_audio = gr.Audio(label=t("Efektli ses (AI ile üretildi)"), type="filepath", interactive=False,
                                    buttons=["download"], elem_classes=["sv-audio"])
                fx_download = gr.DownloadButton(t("⬇ Efektli WAV indir"), variant="secondary",
                                                elem_classes=["sv-btn", "sv-btn-ghost"])

    select_outputs = [selected, mode_md, *fx_controls]

    with cards_slot:
        @gr.render(inputs=[voices, selected])
        def _cards(items, current):
            with i18n.use(lang):
                _render_cards(items, current)

        def _render_cards(items, current):
            hazir = [_RANDOM_CARD] + [v for v in items if v["hazir"]]
            mine = [v for v in items if not v["hazir"]]
            for title, group in ((t("Hazır sesler"), hazir), (t("Seslerim"), mine)):
                _html(f'<div class="sv-group-title">{title}<span>{len(group)}</span></div>')
                if not group:
                    _html('<p class="sv-empty">' + t("Henüz kayıtlı sesiniz yok. “Ses Oluştur” sekmesinden "
                                                     "seçimlerle tarif edin ya da kendi kaydınızı yükleyin.") + "</p>")
                    continue
                with gr.Row(elem_classes=["sv-vgrid"]):
                    for v in group:
                        is_sel = v["id"] == current
                        with gr.Column(min_width=180, elem_classes=["sv-vcard"] + (["is-selected"] if is_sel else [])):
                            _html(_card_html(v))
                            with gr.Row(elem_classes=["sv-vcard-actions"]):
                                pick = gr.Button(t("✓ Seçili") if is_sel else t("Seç"), size="sm", scale=0,
                                                 elem_classes=["sv-btn", "sv-mini"] + (["sv-mini-dark"] if is_sel else []))
                                pick.click(select_voice_ui, inputs=[gr.State(v["id"]), emotion, text],
                                           outputs=select_outputs, show_progress="hidden")
                                if v["ornek"]:
                                    play = gr.Button(t("▶ Örnek"), size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
                                    play.click(lambda p=v["ornek"]: p, outputs=[sample], queue=False)
                                if v["id"] != RANDOM_VOICE:
                                    copy = gr.Button(t("Kopyala"), size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
                                    copy.click(copy_voice_ui, inputs=[gr.State(v["id"])],
                                               outputs=[voices, selected, lib_msg]).then(
                                        select_voice_ui, inputs=[selected, emotion, text], outputs=select_outputs)
                                if not v["hazir"]:
                                    remove = gr.Button(t("Sil"), size="sm", scale=0,
                                                       elem_classes=["sv-btn", "sv-mini", "sv-mini-danger"])
                                    ask = t("**{ad}** silinsin mi? Bu işlem geri alınamaz.", ad=escape(v["ad"]))
                                    remove.click(
                                        lambda vid=v["id"], msg=ask: (vid, gr.update(visible=True), msg),
                                        outputs=[pending, confirm_row, confirm_md], queue=False)

    confirm_yes.click(delete_voice_ui, inputs=[pending, selected],
                      outputs=[voices, selected, lib_msg, pending, confirm_row]).then(
        select_voice_ui, inputs=[selected, emotion, text], outputs=select_outputs)
    confirm_no.click(lambda: (None, gr.update(visible=False)), outputs=[pending, confirm_row], queue=False)

    for trigger in (text.change, emotion.change):
        trigger(_mode_info, inputs=[selected, emotion, text], outputs=mode_md, queue=False)
    demo.load(_in_lang(_mode_info, lang), inputs=[selected, emotion, text], outputs=mode_md)

    generation = _watch_failures(
        button.click, report_button,
        fn=library_generate, inputs=[text, emotion, quality, selected], outputs=[audio, download, status],
        concurrency_limit=1, api_name="generate_audio", show_progress="full",
    )
    fx_inputs = [audio, *fx_controls]
    fx_outputs = [fx_audio, fx_download, fx_status]
    generation.then(apply_effects_ui, inputs=fx_inputs, outputs=fx_outputs)
    generation.then(lambda a: gr.update(visible=bool(a)), inputs=audio, outputs=fx_jump, queue=False,
                    show_progress="hidden")
    fx_jump.click(lambda: gr.Accordion(open=True), outputs=fx_acc, queue=False, show_progress="hidden",
                  js=_FX_JUMP_JS)
    for control in fx_controls:
        event = control.release if isinstance(control, gr.Slider) else control.change
        event(apply_effects_ui, inputs=fx_inputs, outputs=fx_outputs, show_progress="hidden")
    fx_preset.click(save_fx_preset_ui, inputs=[selected, *fx_controls], outputs=fx_status)
    queue_add.click(_in_lang(kuyruga_ekle_kutuphane_ui, lang), inputs=[text, emotion, quality, selected, *fx_controls],
                    outputs=status, show_progress="hidden", concurrency_limit=None, concurrency_id="sv-kuyruk-islem")
    return SimpleNamespace(voices=voices, selected=selected, emotion=emotion, text=text,
                           select_outputs=select_outputs)


def _design_subtab(lib, tabs):
    """Ses Oluştur → Seçimlerle tarif et (kurallı birleştirici, 4 aday)."""
    groups = _DMAP["gruplar"]

    def choice(group, **kw):
        return gr.Radio(choices=_choices(vdes.group_choices(_DMAP, group)), value=_DMAP.get("bos_secenek"),
                        label=t(groups[group]["etiket"]), elem_classes=["sv-emotion", "sv-plain"], **kw)

    def scale(group):
        labels = _slider_labels(group)
        return gr.Slider(1, len(labels), value=_slider_default(group), step=1, label=t(groups[group]["etiket"]),
                         info=" · ".join(f"{i + 1} {t(lab)}" for i, lab in enumerate(labels)), min_width=220)

    with gr.Row(equal_height=False, elem_classes=["sv-grid"]):
        with gr.Column(scale=7, min_width=340, elem_classes=["sv-frame"]):
            _frame_bar([f"{_svg(_IC_SPARK)}{t('Ses tasarımı')}", t("Seçimlerle, LLM'siz")])
            with gr.Column(elem_classes=["sv-panel"]):
                _head(None, t("Şablonla başlayın"),
                      t("İsteğe bağlı: bir şablon seçimleri doldurur, sonra değiştirebilirsiniz."), step="1")
                with gr.Row(elem_classes=["sv-templates"]):
                    template_buttons = [(name, gr.Button(t(name), size="sm", scale=0,
                                                         elem_classes=["sv-btn", "sv-mini"]))
                                        for name in _DMAP["sablonlar"]]
                _html('<div class="sv-divider"></div>')
                _head(None, t("Sesi tarif edin"),
                      t("Her seçim İngilizce bir parçaya dönüşür; tarif otomatik kurulur."), step="2")
                cins = choice("cinsiyet")
                yas = choice("yas")
                kullanim = choice("kullanim")
                ton = choice("ton")
                doku = gr.CheckboxGroup(choices=_choices(groups["doku"]["secenekler"]), value=[],
                                        label=t(groups["doku"]["etiket"]), elem_classes=["sv-emotion", "sv-plain"])
                with gr.Row(elem_classes=["sv-sliders"]):
                    perde = scale("perde")
                    hiz = scale("hiz")
                    enerji = scale("enerji")
                warn_md = gr.Markdown("", elem_classes=["sv-warn"])
                manual = gr.State(False)
                with gr.Accordion(t("Gelişmiş: oluşan İngilizce tarif"), open=False, elem_classes=["sv-acc"]):
                    parts = _html("")
                    tarif = gr.Textbox(label=t("Tarif (İngilizce, elle düzenlenebilir)"), lines=2, value="a voice")
                    rebuild = gr.Button(t("Seçimlerden yeniden kur"), size="sm", elem_classes=["sv-btn", "sv-mini"])
                _html('<div class="sv-divider"></div>')
                _head(None, t("Örnek cümle"),
                      t("Adaylar bu cümleyi okur. Süreyi kaydırıcıyla seçin; metni dilediğiniz gibi değiştirin."),
                      step="3")
                with gr.Row(elem_classes=["sv-sliders"]):
                    category = gr.Radio(choices=[(t(label), key) for label, key in _SAMPLE_CATEGORIES],
                                        value="masal", label=t("Örnek metin türü"),
                                        elem_classes=["sv-emotion", "sv-plain"], min_width=220)
                    seconds = gr.Slider(_MIN_SAMPLE_SECONDS, _MAX_SAMPLE_SECONDS, value=_DEFAULT_SAMPLE_SECONDS, step=1,
                                        label=t("Örnek ses süresi (sn)"), min_width=220)
                first_text = vdes.sample_text("masal", _DEFAULT_SAMPLE_SECONDS, _DMAP)
                sample = gr.Textbox(label=t("Örnek cümle"), lines=3, max_length=500, value=first_text)
                estimate = gr.Markdown(sample_estimate_md(first_text), elem_classes=["sv-fine-md"])
                quality = gr.Radio(choices=_choices(QUALITY), value="Dengeli", label=t("Kalite"),
                                   elem_classes=["sv-emotion", "sv-plain"])
                with gr.Row(elem_classes=["sv-actionbar"]):
                    _html('<div class="sv-hint">' + t("<b>4 aday sırayla üretilir.</b><br>Her biri hazır olunca "
                                                      "dinlenebilir; uzun cümle daha uzun sürer.") + "</div>")
                    try_button = gr.Button(t("Sesleri Dene"), variant="primary", scale=0, min_width=190,
                                           elem_classes=["sv-btn", "sv-btn-primary"])
        with gr.Column(scale=5, min_width=300, elem_classes=["sv-side"]):
            with gr.Column(elem_classes=["sv-card"]):
                _head(_IC_PLAY, t("Adaylar"), t("Aynı tarif ve cümle, farklı seed. Dinleyin, birini seçin."))
                _html('<p class="sv-fine sv-seed-note">' + escape(t(
                    "Aynı tarif, aynı cümle ve aynı seed aynı sesi verir. Bir adayın seed'ini değiştirip "
                    "“Yeniden üret”e basın; diğer adaylar değişmez.")) + "</p>")
                d_status = gr.Markdown(t("Henüz aday yok. Seçimleri yapıp “Sesleri Dene”ye basın."),
                                       elem_classes=["sv-status", "sv-cand-status"])
                d_report_button = _report_panel(i18n.get_lang())
                cand_audio, cand_label, cand_pick, cand_seed, cand_regen = [], [], [], [], []
                # Aday kartları: tek sütun liste (dar panelde taşmaz). Oynatıcıda yalnız oynat/duraklat,
                # dalga ve süre kalır (CSS: .sv-cand-audio); altta seed kutusu + Yeniden üret + Bunu seç.
                with gr.Column(elem_classes=["sv-cgrid"]):
                    for i, varsayilan in enumerate(vdes.candidate_seeds(0)):
                        with gr.Column(min_width=0, elem_classes=["sv-cand"]):
                            cand_label.append(gr.Markdown(t("Aday {n}", n=i + 1), elem_classes=["sv-cand-label"]))
                            cand_audio.append(gr.Audio(label=t("Aday {n}", n=i + 1), show_label=False,
                                                       type="filepath", interactive=False, buttons=[],
                                                       elem_classes=["sv-audio", "sv-cand-audio"]))
                            with gr.Row(elem_classes=["sv-cand-row"]):
                                cand_seed.append(gr.Textbox(value=str(varsayilan), label=t("Seed"), max_lines=1,
                                                            max_length=10, container=False, scale=0, min_width=0,
                                                            elem_classes=["sv-seed"]))
                                cand_regen.append(gr.Button(t("Yeniden üret"), size="sm", scale=0, min_width=0,
                                                            elem_classes=["sv-btn", "sv-mini", "sv-cand-regen"]))
                                cand_pick.append(gr.Button(t("Bunu seç"), size="sm", scale=0, min_width=0,
                                                           elem_classes=["sv-btn", "sv-mini", "sv-cand-pick"]))
                with gr.Row(elem_classes=["sv-cand-actions"]):
                    stop = gr.Button(t("Durdur"), size="sm", scale=0,
                                     elem_classes=["sv-btn", "sv-mini", "sv-mini-danger"])
                    more = gr.Button(t("4 aday daha"), size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
                    change = gr.Button(t("Seçimleri değiştir"), size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
                with gr.Column(visible=False, elem_classes=["sv-save"]) as save_group:
                    picked_md = gr.Markdown("")
                    name = gr.Textbox(label=t("Ses adı"), placeholder=t("Örn. Gece Anlatıcısı"), max_length=60)
                    aciklama = gr.Textbox(label=t("Kısa açıklama (isteğe bağlı)"), max_length=160)
                    kategori = gr.Textbox(label=t("Kategori"), value=t("Masal"), max_length=40)
                    save = gr.Button(t("Kaydet"), variant="primary", elem_classes=["sv-btn", "sv-btn-primary"])
                save_md = gr.Markdown("", elem_classes=["sv-fine-md"])

    batch = gr.State(0)
    cands = gr.State({})
    picked = gr.State(None)
    selections = [cins, yas, kullanim, perde, ton, doku, hiz, enerji]
    rebuild_args = dict(fn=_in_lang(rebuild_description_ui, i18n.get_lang()), inputs=[*selections, manual, tarif],
                        outputs=[tarif, parts, warn_md], queue=False)
    for control in selections:
        control.change(**rebuild_args)

    texture_warning = t("Ses dokusu için en fazla 2 seçim yapılabilir.")

    def limit_texture(values):
        if len(values or []) > 2:
            gr.Warning(texture_warning)
            return values[:2]
        return gr.update()

    def tarif_changed(*values):
        # Kutu seçimlerden kurulandan farklıysa kullanıcı elle yazmıştır.
        sel, current = values[:8], values[8]
        built = vdes.build_description(design_selections(*sel), _DMAP)[0]
        is_manual = (current or "").strip() != built
        _tarif, parts_html, warn = rebuild_description_ui(*sel, is_manual, current)
        return is_manual, parts_html, warn

    doku.input(limit_texture, inputs=doku, outputs=doku, queue=False)
    tarif.change(tarif_changed, inputs=[*selections, tarif], outputs=[manual, parts, warn_md], queue=False)
    rebuild.click(lambda *v: (False, *rebuild_description_ui(*v[:-1], False, v[-1])),
                  inputs=[*selections, tarif], outputs=[manual, tarif, parts, warn_md], queue=False)
    def template_click(name, secs):
        values = apply_template_ui(name, secs)
        return (*values, *rebuild_description_ui(*values[:8], False, ""))

    for tname, tbutton in template_buttons:
        tbutton.click(lambda s, n=tname: template_click(n, s), inputs=[seconds],
                      outputs=[*selections, category, sample, manual, tarif, parts, warn_md], queue=False)
    for trigger in (category.change, seconds.change):
        trigger(lambda k, s: vdes.sample_text(k, s, _DMAP), inputs=[category, seconds], outputs=sample, queue=False)
    sample.change(sample_estimate_md, inputs=sample, outputs=estimate, queue=False)

    # Tüm aday üretimleri (4 aday, 4 aday daha, tek aday yeniden üret) aynı sırayı paylaşır: biri
    # sürerken diğeri beklemeye girer, model aynı anda iki iş görmez.
    ortak = dict(concurrency_limit=1, concurrency_id="sv-adaylar", show_progress="full", show_progress_on=[d_status])
    run_args = dict(fn=design_candidates, inputs=[tarif, sample, quality, *cand_seed, cands, *selections],
                    outputs=[*cand_audio, *cand_label, d_status, cands, save_group, picked], **ortak)
    # "Sesleri Dene": kutulardaki seed'lerle (ilk açılışta 11/22/33/44; kullanıcı değiştirdiyse onlar).
    first_run = _watch_failures(try_button.click, d_report_button, **run_args)

    def next_seeds(b):
        b = int(b or 0) + 1
        return (b, *map(str, vdes.candidate_seeds(b)))

    # "4 aday daha": kutulara sıradaki varsayılan seed'ler yazılır (55/66/77/88 …), sonra 4 aday üretilir.
    more_run = _watch_failures(more.click(next_seeds, inputs=batch, outputs=[batch, *cand_seed], queue=False).then,
                               d_report_button, **run_args)

    def regen_fn(i):
        # Açık parametreler (*args değil): Gradio gr.Progress'i parametre sırasına göre yerleştirir.
        def regen(tarif_, text_, quality_, seed_, cands_, picked_, cins_, yas_, kullanim_, perde_, ton_, doku_,
                  hiz_, enerji_, progress=gr.Progress()):
            yield from regenerate_candidate(i, tarif_, text_, quality_, seed_, cands_, picked_, cins_, yas_,
                                            kullanim_, perde_, ton_, doku_, hiz_, enerji_, progress=progress)
        return regen

    regen_runs = []
    for i, rbutton in enumerate(cand_regen):
        regen_runs.append(_watch_failures(
            rbutton.click, d_report_button, fn=regen_fn(i),
            inputs=[tarif, sample, quality, cand_seed[i], cands, picked, *selections],
            outputs=[cand_audio[i], cand_label[i], d_status, cands, save_group, picked], **ortak))
    stopped_msg = t("Durduruldu. Çalışmakta olan aday bitene kadar model meşgul kalabilir.")
    change_msg = t("Seçimleri soldan değiştirip yeniden “Sesleri Dene”ye basın; kutulardaki seed'ler kullanılır.")
    stop.click(lambda: stopped_msg, outputs=d_status, cancels=[first_run, more_run, *regen_runs], queue=False)
    change.click(lambda: (gr.update(visible=False), None, change_msg),
                 outputs=[save_group, picked, d_status], queue=False)
    for i, pbutton in enumerate(cand_pick):
        pbutton.click(lambda c, i=i: pick_candidate_ui(i, c), inputs=[cands],
                      outputs=[picked, save_group, picked_md], queue=False)
    save.click(save_designed_ui, inputs=[name, aciklama, kategori, picked, cands],
               outputs=[lib.voices, lib.selected, tabs, save_md]).then(
        select_voice_ui, inputs=[lib.selected, lib.emotion, lib.text], outputs=lib.select_outputs)
    return rebuild_args


def _upload_subtab(lib, tabs):
    """Ses Oluştur → Dosya yükle (çözme, kırpma, kontroller, Whisper, izin)."""
    with gr.Row(equal_height=False, elem_classes=["sv-grid"]):
        with gr.Column(scale=7, min_width=340, elem_classes=["sv-frame"]):
            _frame_bar([f"{_svg(_IC_MIC)}{t('Kendi kaydınız')}", "WAV · MP3 · M4A"])
            with gr.Column(elem_classes=["sv-panel"]):
                _head(None, t("Kaydı yükleyin"),
                      t("8–20 saniyelik, tek kişinin konuştuğu temiz bir kayıt. Dosya mono, 16-bit WAV'a çevrilir; "
                        "baştaki ve sondaki sessizlik kırpılır."), step="1")
                u_file = gr.File(label=t("Ses dosyası (WAV, MP3, M4A)"), file_types=[".wav", ".mp3", ".m4a"],
                                 type="filepath", elem_classes=["sv-upload", "sv-file"])
                u_info = gr.Markdown(t(audio_prep.CLEAN_NOTE), elem_classes=["sv-fine-md"])
                with gr.Row(visible=False, elem_classes=["sv-sliders"]) as u_range:
                    u_start = gr.Slider(0, 20, value=0, step=0.1, label=t("Başlangıç (sn)"), min_width=200)
                    u_end = gr.Slider(0, 20, value=20, step=0.1, label=t("Bitiş (sn)"), min_width=200)
                u_range_md = gr.Markdown("", elem_classes=["sv-fine-md"])
                u_preview = gr.Audio(label=t("Hazırlanan kayıt (mono, 16-bit)"), type="filepath", interactive=False,
                                     buttons=["download"], elem_classes=["sv-audio"])
                _html('<div class="sv-divider"></div>')
                _head(None, t("Kaydın metni"),
                      t("Yerel Whisper ile çıkarılır; kayıtla birebir aynı olacak şekilde düzeltin. Boş bırakılamaz."),
                      step="2")
                with gr.Row(elem_classes=["sv-transcribe-row"]):
                    u_text = gr.Textbox(label=t("Kaydın metni (gerekli)"), lines=3, scale=4,
                                        placeholder=t("Kayıtta tam olarak ne söylendiği…"))
                    u_transcribe = gr.Button(t("Otomatik yazıya dök"), scale=1, min_width=200,
                                             elem_classes=["sv-btn", "sv-btn-soft"])
                u_transcribe_md = gr.Markdown("", elem_classes=["sv-fine-md"])
                _html('<div class="sv-divider"></div>')
                _head(None, t("Kaydedin"), t("Kaydedilen ses yalnız bu bilgisayarda, Seslerim'de durur."), step="3")
                u_name = gr.Textbox(label=t("Ses adı"), max_length=60)
                u_desc = gr.Textbox(label=t("Kısa açıklama (isteğe bağlı)"), max_length=160)
                u_cat = gr.Textbox(label=t("Kategori"), value=t("Kişisel"), max_length=40)
                u_consent = gr.Checkbox(label=t("Bu ses bana ait ya da sahibinden açık izin aldım."), value=False,
                                        elem_classes=["sv-consent"])
                with gr.Row(elem_classes=["sv-actionbar"]):
                    _html('<div class="sv-hint">' + t("<b>İzin kutucuğu zorunlu.</b><br>"
                                                      "İşaretlenmeden kaydedilemez.") + "</div>")
                    u_save = gr.Button(t("Kaydet"), variant="primary", interactive=False, scale=0, min_width=170,
                                       elem_classes=["sv-btn", "sv-btn-primary"])
                u_msg = gr.Markdown("", elem_classes=["sv-fine-md"])
        with gr.Column(scale=5, min_width=300, elem_classes=["sv-side"]):
            with gr.Column(elem_classes=["sv-card"]):
                _html(_ethics())

    u_full = gr.State(None)
    u_prepared = gr.State(None)
    analyze_outputs = [u_full, u_prepared, u_preview, u_info, u_range, u_start, u_end, u_text]
    u_file.upload(upload_analyze_ui, inputs=u_file, outputs=analyze_outputs)
    u_file.clear(lambda: upload_analyze_ui(None), outputs=analyze_outputs, queue=False)
    for slider in (u_start, u_end):
        slider.release(upload_cut_ui, inputs=[u_full, u_start, u_end], outputs=[u_prepared, u_preview, u_range_md])
    u_transcribe.click(upload_transcribe_ui, inputs=u_prepared, outputs=[u_text, u_transcribe_md],
                       concurrency_limit=1, show_progress="full")
    u_consent.change(lambda v: gr.update(interactive=bool(v)), inputs=u_consent, outputs=u_save, queue=False)
    u_save.click(save_uploaded_ui, inputs=[u_prepared, u_text, u_name, u_desc, u_cat, u_consent],
                 outputs=[lib.voices, lib.selected, tabs, u_msg]).then(
        select_voice_ui, inputs=[lib.selected, lib.emotion, lib.text], outputs=lib.select_outputs)


_GRADIO_LOCALES = {"zh": "zh-CN"}  # Gradio'nun kendi (yerleşik) metinleri için yerel ad


def _page_js(lang):
    """Sayfa açılışında: <html lang>, RTL sınıfı, sekme başlığı ve Gradio'nun kendi
    yerleşik metinlerinin (ör. ses bileşenindeki "Drop Audio Here") dili."""
    import json
    return f"""() => {{
    const lang = {json.dumps(lang)}, glang = {json.dumps(_GRADIO_LOCALES.get(lang, lang))};
    document.documentElement.lang = lang;
    document.body.classList.toggle('sv-rtl', {json.dumps(i18n.is_rtl(lang))});
    document.title = {json.dumps(t("SesVer · Türkçe yerel ses üretimi"), ensure_ascii=False)};
    const urls = performance.getEntriesByType('resource').map((r) => r.name)
        .concat([...document.querySelectorAll('script[src],link[href]')].map((e) => e.src || e.href));
    const core = urls.find((u) => /\\/assets\\/core-[^/]*\\.js/.test(u));
    if (core) import(core).then((m) => m.changeLocale && m.changeLocale(glang)).catch(() => {{}});
}}"""


def _switch_js():
    """Dil seçiciden: aynı sunucuda seçilen dilin sayfasına geçer (Türkçe = kök adres)."""
    import json
    codes = json.dumps([c for c in i18n.LANGUAGES if c != i18n.DEFAULT])
    return f"""(v) => {{
    const codes = {codes};
    const parts = window.location.pathname.replace(/\\/+$/, '').split('/');
    if (codes.includes(parts[parts.length - 1])) parts.pop();
    const target = parts.join('/') + '/' + (codes.includes(v) ? v : '');
    if (target !== window.location.pathname) window.location.assign(target + window.location.search);
    return v;
}}"""


def _remember_language(lang):
    def remember():
        # Sunucu tarafı iletiler (hata/durum) bu dilde üretilir; seçim ayarlar.json'da saklanır.
        i18n.set_lang(lang)
    return remember


def _language_bar(lang):
    # DOM sırası: seçici, sonra Kuyruk/Ayarlar girişleri, sonra marka (CSS row-reverse ile seçici sağ
    # üstte, girişler hemen solunda durur). Girişler gizli sekmeleri açar (bkz. _build_page).
    with gr.Row(elem_classes=["sv-langbar"]):
        # Görünür etiket yok (Yusuf: "arayüz dili yazmasına gerek yok"); etiket metni ekran okuyucu
        # için erişilebilir ad olarak kalır (show_label=False → Gradio gizli etiket, bkz. _CSS .sv-lang).
        picker = gr.Dropdown(
            choices=[(name, code) for code, name in i18n.LANGUAGES.items()], value=lang,
            label=t("Arayüz dili"), show_label=False, interactive=True, filterable=False, scale=0, min_width=170,
            elem_classes=["sv-lang"],
        )
        with gr.Row(elem_classes=["sv-topnav"]):
            queue_btn = gr.Button(t("Kuyruk"), scale=0, min_width=0,
                                  elem_classes=["sv-btn", "sv-topbtn", "sv-top-kuyruk", "is-empty"])
            settings_btn = gr.Button(t("Ayarlar"), scale=0, min_width=0,
                                     elem_classes=["sv-btn", "sv-topbtn", "sv-top-ayarlar"])
        _html(_brand(), elem_classes=["sv-brandbar"])  # DOM'da en sonda = görünümde en solda
    picker.change(None, inputs=picker, js=_switch_js())
    return queue_btn, settings_btn


def _guncelleme_bildirimi(lang):
    """Sayfa yüklenince: açılışta başlatılan arka plan kontrolünün sonucunu gösterir.

    Kontrol başlatılmadıysa (testler, ayar kapalı, SESVER_GUNCELLEME_KONTROLU=0) ya da
    yeni sürüm yok/hata varsa bildirim gizli kalır. Bekleme en fazla kontrolün toplam
    süre sınırına kadardır ve kendi eşzamanlılık havuzunda çalışır; ses üretim
    kuyruğunu bekletmez.
    """
    def goster():
        metin = guncelleme.bildirim_html(guncelleme.sonuc(), lang=lang)
        return gr.update(value=metin, visible=bool(metin))
    return goster


def _build_page(demo, lang):
    """Bir dilin tam sayfası; tüm metinler kurulurken o dilde üretilir."""
    with i18n.use(lang):
        # Açılış ekranı: sabit katman (akışta yer kaplamaz); uygulama açılışı başına bir kez oynar.
        _html(_splash(), js_on_load=SPLASH_JS, elem_classes=["sv-splash-host"])
        queue_btn, settings_btn = _language_bar(lang)
        update_note = _html("", visible=False, elem_id="sv-update-note")
        demo.load(_guncelleme_bildirimi(lang), outputs=update_note, show_progress="hidden",
                  concurrency_limit=None, concurrency_id="sv-guncelleme", api_visibility="private")
        # Önceki oturumdan bekleyen öğe varsa (kuyruk kendiliğinden başlamaz): her sekmede görünen bant.
        with gr.Row(visible=False, elem_classes=["sv-qbanner"]) as banner:
            banner_html = _html("")
            banner_go = gr.Button(t("Kaldığı yerden devam et"), size="sm", scale=0,
                                  elem_classes=["sv-btn", "sv-mini", "sv-mini-dark"])
            banner_show = gr.Button(t("Kuyruğu göster"), size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])

        with gr.Tabs(elem_id="sv-tabs", selected="lib", overflow_behavior="wrap") as tabs:
            with gr.Tab(t("Ses Kütüphanesi"), id="lib"):
                lib = _library_tab(demo)

            with gr.Tab(t("Ses Oluştur"), id="olustur"):
                with gr.Tabs(elem_id="sv-subtabs", overflow_behavior="wrap"):
                    with gr.Tab(t("Seçimlerle tarif et"), id="tarif"):
                        rebuild_args = _design_subtab(lib, tabs)
                    with gr.Tab(t("Dosya yükle"), id="yukle"):
                        _upload_subtab(lib, tabs)
                demo.load(**rebuild_args)

            with gr.Tab(t("Ses Klonlama"), id="klon"):
                _clone_tab()

            with gr.Tab(t("Hızlı Mod"), id="hizli") as fast:
                fast_refresh = _fast_tab()
            # Kurulu mu? (hızlı: dosya boyutları + paket sürümü; ağa çıkmaz, torch yüklemez)
            fast.select(**fast_refresh)
            demo.load(**fast_refresh)

            # Kuyruk ve Ayarlar sekme çubuğunda görünmez (CSS); sağ üstteki girişlerle açılır.
            with gr.Tab(t("Kuyruk"), id="kuyruk", elem_id="sv-tab-kuyruk"):
                queue = _queue_tab(lang, lib)

            with gr.Tab(t("Ayarlar"), id="ayarlar", elem_id="sv-tab-ayarlar"):
                accel_refresh, accel_out, update_check = _settings_tab()

        # Sağ üst girişler: görünüm değişir (sekme), Ayarlar açılınca donanım taraması (~3 sn) yapılır.
        queue_btn.click(lambda: gr.Tabs(selected="kuyruk"), outputs=tabs, queue=False, show_progress="hidden")
        settings_btn.click(lambda: gr.Tabs(selected="ayarlar"), outputs=tabs, queue=False,
                           show_progress="hidden").then(accel_refresh, outputs=accel_out, show_progress="minimal")
        settings_btn.click(guncelleme.ayar_acik_mi, outputs=update_check, queue=False, show_progress="hidden")
        _queue_wiring(demo, lang, queue, queue_btn, banner, banner_html, banner_go, banner_show, tabs)

        info = _html(_info())
        # Model bu oturumda inmiş olabilir: sayfa her açılışta kutucuğu yeniden hesaplar (dosya denetimi, ağ yok).
        demo.load(_in_lang(_info, lang), outputs=info, queue=False, show_progress="hidden",
                  api_visibility="private")
        _html(_footer())
        demo.load(None, js=_page_js(lang))
        demo.load(_remember_language(lang), queue=False, show_progress="hidden")


def build_app():
    """Her arayüz dili ayrı bir sayfadır (Türkçe kökte, diğerleri /en, /es …).

    Gradio bileşen metinleri sunucuda kurulur ve sonradan topluca değiştirilemez
    (gr.I18n yalnız statik etiketleri çevirir; HTML blokları ve sunucu iletileri
    kapsam dışıdır). Bu yüzden dil seçici ilgili sayfaya geçer; tüm sayfalar
    açılışta bir kez kurulur (~0,1 sn/dil).
    """
    with gr.Blocks(title=t("SesVer · Türkçe yerel ses üretimi", i18n.DEFAULT), analytics_enabled=False) as demo:
        _build_page(demo, i18n.DEFAULT)
    for code, name in i18n.LANGUAGES.items():
        if code == i18n.DEFAULT:
            continue
        with demo.route(name, f"/{code}", show_in_navbar=False):
            _build_page(demo, code)
    return demo.queue(default_concurrency_limit=1, max_size=8)


def _clone_tab():
    """Ses Klonlama sekmesi (referans ses + isteğe bağlı metni + yeni metin)."""
    with gr.Row(equal_height=False, elem_classes=["sv-grid"]):
        with gr.Column(scale=7, min_width=340, elem_classes=["sv-frame"]):
            _html(
                f'<div class="sv-frame-bar"><div class="sv-chips">'
                f'<span class="sv-chip">{_svg(_IC_MIC)}{t("Ses klonlama")}</span>'
                f'<span class="sv-chip">{t("3 adım")}</span></div>'
                f'<span class="sv-chip sv-chip-dark">{_svg(_IC_LOCK)}{t("Yerel")}</span></div>'
            )
            with gr.Column(elem_classes=["sv-panel"]):
                _head(None, t("Örnek sesi yükleyin"),
                      t("Tek kişinin konuştuğu, müziksiz ve temiz <b>3–15 saniyelik WAV</b> en iyi sonucu "
                        "verir (1–30 saniye kabul edilir)."), step="1")
                c_reference = gr.Audio(
                    label=t("Referans ses (gerekli)"), sources=["upload"], type="filepath",
                    buttons=["download"], elem_classes=["sv-audio", "sv-upload"],
                )
                _html('<div class="sv-divider"></div>')
                _head(None, t("Kayıtta ne söylendiğini yazın"),
                      t("İsteğe bağlı ama önerilir: model kaydı anlayarak devam eder ve ses çok daha "
                        "benzer çıkar. Boş bırakırsanız yalnız ses rengi kopyalanır."), step="2")
                with gr.Row(elem_classes=["sv-transcribe-row"]):
                    c_prompt_text = gr.Textbox(
                        label=t("Referans sesin metni (isteğe bağlı)"),
                        placeholder=t("Kayıtta tam olarak ne söylendiğini yazın ya da otomatik doldurun."),
                        lines=2, scale=4,
                    )
                    c_transcribe_btn = gr.Button(
                        t("Otomatik yazıya dök"), scale=1, min_width=200,
                        elem_classes=["sv-btn", "sv-btn-soft"],
                    )
                _html('<div class="sv-divider"></div>')
                _head(None, t("Yeni metni yazın"),
                      t("Klonlanan ses bu metni okuyacak."), step="3")
                c_text = gr.Textbox(
                    label=t("Metin"), lines=4, max_length=kq.OGE_METIN_EN_FAZLA, value=t(_SAMPLE_TEXT),
                    placeholder=t("Klonlanan sesin okuyacağı metni yazın…"),
                    info=t("Hangi dilde yazarsanız o dilde okur."), elem_classes=["sv-lang-hint"],
                )
                c_emotion = gr.Radio(
                    choices=_choices(EMOTIONS), value="Nötr",
                    label=t("Duygu / ton (isteğe bağlı, varsayılan: nötr)"),
                    elem_classes=["sv-emotion"],
                )
                _html('<p class="sv-fine">' + t("<b>İpucu:</b> Bir duygu seçmek, klonun orijinal sese "
                                                "benzerliğini biraz azaltabilir. En sadık sonuç için "
                                                "“Nötr” kalsın.") + "</p>")
                with gr.Row(elem_classes=["sv-actionbar"]):
                    _html('<div class="sv-hint">' + t("<b>Üret: en fazla 500 karakter.</b><br>"
                                                      "Kuyruğa ekle: 10.000 karaktere kadar.") + "</div>")
                    c_queue_add = gr.Button(t("Kuyruğa ekle"), scale=0, min_width=150,
                                            elem_classes=["sv-btn", "sv-btn-queue"])
                    c_button = gr.Button(
                        t("Klonla ve Üret"), variant="primary", scale=0, min_width=190,
                        elem_classes=["sv-btn", "sv-btn-primary"],
                    )
        with gr.Column(scale=5, min_width=300, elem_classes=["sv-side"]):
            with gr.Column(elem_classes=["sv-card"]):
                _head(*_result_head())
                c_status = gr.Markdown(
                    t("Hazır. Metin ve referans ses yükleyip Klonla ve Üret'e basın."),
                    elem_classes=["sv-status"],
                )
                c_report_button = _report_panel(i18n.get_lang())
                c_audio = gr.Audio(
                    label=t("Üretilen ses (AI ile üretildi)"), type="filepath", interactive=False,
                    buttons=["download"], elem_classes=["sv-audio"],
                )
                c_download = gr.DownloadButton(
                    t("⬇ WAV indir"), variant="secondary", elem_classes=["sv-btn", "sv-btn-ghost"],
                )
                _html(_result_note())
            with gr.Column(elem_classes=["sv-card"]):
                _html(_ethics())
    _watch_failures(
        c_button.click, c_report_button,
        fn=_clone_generate, inputs=[c_text, c_reference, c_emotion, c_prompt_text],
        outputs=[c_audio, c_download, c_status],
        concurrency_limit=1, api_name="clone_audio", show_progress="full",
    )
    c_transcribe_btn.click(
        auto_transcribe, inputs=[c_reference], outputs=[c_prompt_text],
        concurrency_limit=1, show_progress="full",
    )
    c_queue_add.click(_in_lang(kuyruga_ekle_klon_ui, i18n.get_lang()),
                      inputs=[c_text, c_reference, c_emotion, c_prompt_text], outputs=c_status, show_progress="hidden",
                      concurrency_limit=None, concurrency_id="sv-kuyruk-islem")


# --- ⚡ Hızlı Mod (EMA Lightning) -----------------------------------------------
# Kurulum/motor mantığı engines/ema.py'de (SHA-256 doğrulamalı indirme, iptal, geri alma).
# Burada yalnız arayüz ve iletiler var. Paketler SesVer'in kendi Python ortamına
# (python-embed / .venv) pip ile kurulur; ağırlıklar models/ema-lightning'e iner.
# İletiler sabit sayfa diliyle (t(..., lang)) üretilir: üreteç olaylarında i18n.use()
# bağlamı iş parçacıkları arasında taşınmaz.

_fast = {"engine": None, "cancel": Event()}
_fast_lock = Lock()  # kurulum / kaldırma aynı anda tek


def _fast_engine():
    if _fast["engine"] is None:
        _fast["engine"] = ema_motor.EmaEngine(output_dir=OUTPUT_DIR, write_srt=False)
    return _fast["engine"]


def _fast_views(ready, lang, note=None):
    """(kurulu değil sütunu, kurulu sütunu, kurulum durumu) güncellemeleri."""
    return (gr.update(visible=not ready), gr.update(visible=ready),
            note if note is not None else gr.update())


def _fast_refresh_ui(lang):
    """Sekme açılınca/sayfa yüklenince: kurulu mu? (hızlı; ağa çıkmaz, torch yüklemez)."""
    st = ema_motor.ema_status()
    install = gr.update(interactive=st.dependencies_ok and not _fast_lock.locked())
    note = gr.update()
    if not st.dependencies_ok:
        note = t("Hızlı Mod için gereken temel paketler eksik ya da eski: {liste}. "
                 "SesVer'i kapatıp başlatıcıyla yeniden açın.", lang,
                 liste=escape(", ".join(st.missing_dependencies)))
    return (*_fast_views(st.ready, lang, note), install)


def _fast_progress_text(p, lang):
    if p.stage == "paket":
        return t("Paketler kuruluyor (ema-lightning, normalizer-tr)…", lang)
    if p.stage == "indirme" and p.total_bytes:
        return t("Model indiriliyor: {done} / {total} MB ({pct}%)", lang,
                 done=f"{p.done_bytes / 1e6:.1f}", total=f"{p.total_bytes / 1e6:.1f}",
                 pct=int(p.done_bytes * 100 / p.total_bytes))
    if p.stage == "dogrulama":
        return t("İndirilen dosyalar doğrulanıyor (SHA-256)…", lang)
    if p.stage == "geri_alma":
        return t("Yarım kurulum geri alınıyor…", lang)
    return t("Kurulum denetleniyor…", lang)


def _fast_install_ui(lang):
    """"Hızlı Mod'u indir": arka planda ema_install; ilerleme durum satırına yazılır.

    Çıktılar: durum, indir düğmesi, iptal düğmesi, kurulu değil sütunu, kurulu sütunu.
    """
    keep = gr.update()
    blocked = _accel_block_reason()
    if blocked:
        raise gr.Error(blocked)
    if not _fast_lock.acquire(blocking=False):
        raise gr.Error(t("Hızlı Mod kurulumu zaten sürüyor.", lang))
    try:
        _fast["cancel"].clear()
        events, box = Queue(), {}
        started = perf_counter()

        def work():
            try:
                box["status"] = ema_motor.ema_install(events.put, cancel=_fast["cancel"])
            except BaseException as exc:  # noqa: BLE001 — hata ana akışa taşınır
                box["error"] = exc
            finally:
                events.put(None)

        Thread(target=work, name="sesver-hizli-kurulum", daemon=True).start()
        off, on = gr.update(interactive=False), gr.update(visible=True, interactive=True)
        yield "⏳ " + t("Kurulum denetleniyor…", lang), off, on, keep, keep
        while True:
            item = events.get()
            if item is None:
                break
            yield "⏳ " + _fast_progress_text(item, lang), off, keep, keep, keep
        hide_cancel, enable = gr.update(visible=False), gr.update(interactive=True)
        exc = box.get("error")
        if exc is None:
            sec = f"{perf_counter() - started:.1f}"
            log.info("Hızlı Mod kuruldu (%s sn).", sec)
            yield (t("Hızlı Mod hazır (kurulum {sec} sn). Metninizi yazıp Üret'e basın.", lang, sec=sec),
                   enable, hide_cancel, *_fast_views(True, lang)[:2])
            return
        if isinstance(exc, ema_motor.InstallCancelledError):
            log.info("Hızlı Mod kurulumu iptal edildi.")
            yield t("İndirme iptal edildi; yarım dosya kalmadı.", lang), enable, hide_cancel, keep, keep
            return
        with i18n.use(lang):
            entry = hata_raporu.record_error(exc, where="hizli_mod_kurulum")
        if isinstance(exc, ema_motor.EmaNetworkError):
            msg = t("İndirme başarısız: internet bağlantınızı kontrol edip yeniden deneyin. "
                    "Yarım dosya kalmadı; tam inen dosyalar tekrar inmez.", lang)
        else:
            msg = t("Hızlı Mod kurulamadı: **{neden}**. Ayrıntı: sesver_log.txt. Sorun sürerse "
                    "“Hata raporu gönder” düğmesiyle bize bildirin.", lang, neden=escape(entry["reason"]))
        yield msg, enable, hide_cancel, keep, keep
    finally:
        _fast_lock.release()


def _fast_cancel_ui(lang):
    _fast["cancel"].set()
    return "⏳ " + t("İptal ediliyor…", lang)


def _fast_generate_ui(text, speed, seed, want_srt, lang):
    """Hızlı Mod üretimi. Çıktılar: ses, WAV indirme, SRT dosyası, durum."""
    hide = gr.update(value=None, visible=False)
    yield None, None, hide, t("Ses üretiliyor…", lang)
    blocked = _accel_block_reason()
    if blocked:
        raise gr.Error(blocked)
    text = (text or "").strip()
    if not text:
        raise gr.Error(t("Lütfen okunacak bir metin yazın.", lang))
    if len(text) > ema_motor.MAX_TEXT_CHARS:
        raise gr.Error(t("Hızlı Mod'da en fazla {n} karakter kullanın; uzun metni bölün.", lang,
                         n=ema_motor.MAX_TEXT_CHARS))
    seed = "" if seed is None else str(seed).strip()
    if not seed:
        seed = None
    else:
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = -1
        if seed < 0:
            raise gr.Error(t("Seed sıfır ya da pozitif bir tam sayı olmalı.", lang))
    if not ema_motor.ema_status().ready:
        raise gr.Error(t("Hızlı Mod kurulu değil. Önce “Hızlı Mod'u indir” düğmesine basın.", lang))
    started = perf_counter()
    hata_raporu.remember_private(text)  # metin günlüğe/rapora hiç yazılmaz (bulgu 2)
    log.info("istek kip=hizli hiz=%.2f seed=%s srt=%s karakter=%d", float(speed), "var" if seed is not None
             else "rastgele", "evet" if want_srt else "hayir", len(text))
    try:
        res = _fast_engine().synthesize(text, speed=float(speed), seed=seed, srt=bool(want_srt))
    except Exception as exc:  # noqa: BLE001 — kullanıcıya tür, ayrıntı günlüğe/rapora
        with i18n.use(lang):
            entry = hata_raporu.record_error(exc, redact=[text], where="hizli_mod")
        yield None, None, hide, t(
            "Üretim başarısız: **{neden}**. Ayrıntı: sesver_log.txt. Sorun sürerse "
            "“Hata raporu gönder” düğmesiyle bize bildirin.", lang, neden=escape(entry["reason"]))
        return
    meta = res.meta
    srt_file = gr.update(value=meta["srt_path"], visible=True) if meta.get("srt_path") else hide
    yield res.path, res.path, srt_file, t(
        "Tamamlandı: {sec} saniye, ses {dur} saniye (seed {seed}). AI ile üretildi.", lang,
        sec=f"{perf_counter() - started:.1f}", dur=f"{meta['duration']:.1f}", seed=meta.get("seed"))


def _fast_remove_ui(lang):
    """"Hızlı Mod'u kaldır" (onaylandıktan sonra): ağırlıklar + iki paket silinir."""
    if not _fast_lock.acquire(blocking=False):
        raise gr.Error(t("Hızlı Mod kurulumu zaten sürüyor.", lang))
    try:
        result = ema_motor.ema_uninstall(packages=True)
    except Exception as exc:  # noqa: BLE001
        with i18n.use(lang):
            entry = hata_raporu.record_error(exc, where="hizli_mod_kaldir")
        return (t("Hızlı Mod kaldırılamadı: **{neden}**. SesVer'i kapatıp yeniden açın, sonra tekrar "
                  "deneyin.", lang, neden=escape(entry["reason"])), gr.update(), gr.update())
    finally:
        _fast_lock.release()
    _fast["engine"] = None
    log.info("Hızlı Mod kaldırıldı: %s, paketler: %s", ema_motor.format_size(result["freed_bytes"]),
             ", ".join(result["packages_removed"]) or "-")
    return (t("Hızlı Mod kaldırıldı ({size} boşaldı). İsterseniz yeniden indirebilirsiniz.", lang,
              size=ema_motor.format_size(result["freed_bytes"])), *_fast_views(False, lang)[:2])


def _fast_tab():
    """⚡ Hızlı Mod sekmesi. Sayfa yüklenince/sekme seçilince çağrılacak (fn, outputs) döndürür."""
    lang = i18n.get_lang()
    st = ema_motor.ema_status()
    with gr.Row(equal_height=False, elem_classes=["sv-grid"]):
        with gr.Column(scale=7, min_width=340, elem_classes=["sv-frame"]):
            _html(
                f'<div class="sv-frame-bar"><div class="sv-chips">'
                f'<span class="sv-chip">{_svg(_IC_BOLT)}{t("Hızlı Mod")}</span>'
                f'<span class="sv-chip">EMA Lightning</span></div>'
                f'<span class="sv-chip sv-chip-dark">{_svg(_IC_LOCK)}{t("Yerel")}</span></div>'
            )
            with gr.Column(elem_classes=["sv-panel"]):
                with gr.Column(visible=not st.ready) as setup_col:
                    _head(_IC_BOLT, t("Hızlı Mod'u indirin"),
                          t("Saniyeler içinde Türkçe seslendirme. <b>Yalnız Türkçe</b> ve <b>tek bir ses</b> "
                            "vardır; ses klonu, ses tarifi ve duygu seçimi yoktur (bunlar için diğer "
                            "sekmeleri kullanın). Bir kez yaklaşık <b>35 MB</b> indirilir, sonra internetsiz "
                            "çalışır. “Kalite: Hızlı” ayarından farklı, ayrı bir ses motorudur (EMA Lightning)."))
                    with gr.Row():
                        install = gr.Button(t("Hızlı Mod'u indir"), variant="primary",
                                            interactive=st.dependencies_ok,
                                            elem_classes=["sv-btn", "sv-btn-primary", "sv-ic-download"])
                        cancel = gr.Button(t("İptal"), visible=False, elem_classes=["sv-btn", "sv-btn-soft"])
                    _html('<p class="sv-fine">' + t(
                        "İndirilen dosyalar SHA-256 ile doğrulanır. Model: EMA Lightning (Apache-2.0).") + "</p>")
                with gr.Column(visible=st.ready) as ready_col:
                    _head(_IC_TEXT, t("Metni yazın"),
                          t("Tek Türkçe ses okur. Hızı ayarlayabilir, beğendiğiniz okumayı seed ile sabitleyebilirsiniz."))
                    # Örnek metin bilerek Türkçe kalır: Hızlı Mod yalnız Türkçe okur.
                    f_text = gr.Textbox(label=t("Metin"), lines=5, max_length=ema_motor.MAX_TEXT_CHARS,
                                        value="Merhaba, bu SesVer Hızlı Mod denemesidir.",
                                        placeholder=t("Okunacak Türkçe metni yazın…"))
                    with gr.Row():
                        f_speed = gr.Slider(0.5, 2.0, value=1.0, step=0.05, label=t("Konuşma hızı"))
                        # gr.Number boşken 0 gösterip 0 gönderiyor; "boş = rastgele" için metin kutusu.
                        f_seed = gr.Textbox(value="", max_lines=1, label=t("Seed (isteğe bağlı)"),
                                            info=t("Boş bırakılırsa her seferinde farklı bir okuma."))
                    f_srt = gr.Checkbox(value=False, label=t("Altyazı (SRT) dosyası da oluştur"))
                    with gr.Row(elem_classes=["sv-actionbar"]):
                        _html('<div class="sv-hint">' + t("<b>Yalnız Türkçe.</b><br>"
                                                          "En fazla 5000 karakter.") + "</div>")
                        f_button = gr.Button(t("Üret"), variant="primary", scale=0, min_width=190,
                                             elem_classes=["sv-btn", "sv-btn-primary"])
                    _html('<div class="sv-divider"></div>')
                    with gr.Row():
                        remove = gr.Button(t("Hızlı Mod'u kaldır"), size="sm", scale=0,
                                           elem_classes=["sv-btn", "sv-mini"])
                    with gr.Row(visible=False) as confirm_row:
                        _html('<p class="sv-fine">' + t(
                            "Model dosyaları (~34 MB) ve Hızlı Mod paketleri silinecek. Ürettiğiniz sesler "
                            "kalır.") + "</p>")
                        confirm_yes = gr.Button(t("Evet, kaldır"), size="sm", scale=0,
                                                elem_classes=["sv-btn", "sv-mini", "sv-mini-danger"])
                        confirm_no = gr.Button(t("Vazgeç"), size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
                setup_status = gr.Markdown("", elem_classes=["sv-fine-md"])
        with gr.Column(scale=5, min_width=300, elem_classes=["sv-side"]):
            with gr.Column(elem_classes=["sv-card"]):
                _head(*_result_head())
                f_status = gr.Markdown(t("Hazır. Metni yazıp Üret'e basın."), elem_classes=["sv-status"])
                f_report = _report_panel(lang)
                f_audio = gr.Audio(label=t("Üretilen ses (AI ile üretildi)"), type="filepath", interactive=False,
                                   buttons=["download"], elem_classes=["sv-audio"])
                f_download = gr.DownloadButton(t("⬇ WAV indir"), variant="secondary",
                                               elem_classes=["sv-btn", "sv-btn-ghost"])
                f_srt_file = gr.File(label=t("Altyazı (SRT)"), visible=False, interactive=False)
                _html(_result_note())

    views = [setup_col, ready_col]

    def do_install():
        yield from _fast_install_ui(lang)

    def do_generate(text, speed, seed, want_srt):
        yield from _fast_generate_ui(text, speed, seed, want_srt, lang)

    _watch_failures(
        install.click, f_report,
        fn=do_install, outputs=[setup_status, install, cancel, *views],
        concurrency_limit=1, concurrency_id="sv-hizli-kurulum", show_progress="hidden",
    )
    cancel.click(lambda: _fast_cancel_ui(lang), outputs=setup_status, queue=False, show_progress="hidden")
    _watch_failures(
        f_button.click, f_report,
        fn=do_generate, inputs=[f_text, f_speed, f_seed, f_srt],
        outputs=[f_audio, f_download, f_srt_file, f_status],
        concurrency_limit=1, concurrency_id="sv-hizli", api_name="fast_audio", show_progress="full",
    )
    remove.click(lambda: gr.update(visible=True), outputs=confirm_row, queue=False, show_progress="hidden")
    confirm_no.click(lambda: gr.update(visible=False), outputs=confirm_row, queue=False, show_progress="hidden")
    _watch_failures(
        confirm_yes.click(lambda: gr.update(visible=False), outputs=confirm_row, queue=False,
                          show_progress="hidden").then, f_report,
        fn=lambda: _fast_remove_ui(lang), outputs=[setup_status, *views], show_progress="minimal",
    )
    return dict(fn=lambda: _fast_refresh_ui(lang), outputs=[*views, setup_status, install],
                queue=False, show_progress="hidden")


# --- Ayarlar: ekran kartı (GPU) hızlandırma ---------------------------------
# Algılama/kurulum mantığı hizlandirma.py'de; burada yalnız arayüz ve iletiler var.
# PyTorch'un CPU/CUDA/ROCm derlemeleri ayrı paketlerdir: kurulumdan sonra değişiklik
# ancak SesVer yeniden başlatılınca devreye girer (bu sınır arayüzde açıkça söylenir).

_accel = {"busy": False, "restart": False, "scan": None}
_accel_lock = Lock()


def _accel_block_reason():
    if _accel["busy"]:
        return t("Ekran kartı kurulumu sürüyor; bitene kadar ses üretilemez.")
    if _accel["restart"]:
        return t("Ekran kartı ayarı değişti. Ses üretmeden önce SesVer'i kapatıp yeniden açın.")
    return None


def _accel_scan(force=False):
    """(donanım, kurulu torch bilgisi, plan); torch okuması ~3 sn sürdüğü için önbelleklenir."""
    if force or _accel["scan"] is None:
        hw = hiz.detect()
        info = hiz.probe_torch()
        _accel["scan"] = (hw, info, hiz.plan(hw, info))
    return _accel["scan"]


def _backend_label(backend):
    return {"cuda": "NVIDIA CUDA", "rocm": "AMD ROCm", "mps": "Apple MPS",
            "cpu": t("İşlemci (CPU)")}.get(backend, t("okunamadı"))


def _accel_plan_md(p):
    gpu = f"**{escape(p['gpu'] or '')}**"
    durum = p["durum"]
    if durum == hiz.MAC:
        if p["gpu"]:
            return t("Apple Silicon Mac'te SesVer ekran kartını (MPS) zaten otomatik kullanır; "
                     "ek kurulum gerekmez.")
        return t("Bu Mac'te ekran kartı hızlandırması yok; SesVer işlemciyle (CPU) çalışır.")
    if durum == hiz.ACTIVE:
        return t("✅ Ekran kartı hızlandırması etkin: ses üretimi {gpu} üzerinde çalışır.", gpu=gpu)
    if durum == hiz.INSTALL:
        return t("{gpu} algılandı: {backend} hızlandırması kullanılabilir. Şu an işlemci (CPU) "
                 "kullanılıyor; aşağıdaki düğmeyle etkinleştirebilirsiniz.",
                 gpu=gpu, backend=_backend_label(p["hedef"]))
    if durum == hiz.BROKEN:
        return t("⚠️ {backend} destekli PyTorch kurulu ama ekran kartı kullanılamıyor (sürücü eksik "
                 "veya uyumsuz olabilir). Ekran kartı sürücüsünü güncelleyip yeniden tarayın ya da "
                 "işlemci (CPU) sürümüne geri dönün.", backend=_backend_label(p["hedef"]))
    if durum == hiz.DRIVER_OLD:
        return t("{gpu} algılandı ama NVIDIA sürücüsü çok eski (sürüm {driver}; en az 525 gerekir). "
                 "Sürücüyü nvidia.com/drivers adresinden güncelleyip bu sayfayı yeniden tarayın.",
                 gpu=gpu, driver=escape(p["surucu"] or "?"))
    if durum == hiz.NO_DRIVER:
        return t("{gpu} algılandı ama NVIDIA sürücüsü (nvidia-smi) bulunamadı. Sürücüyü "
                 "nvidia.com/drivers adresinden kurup bu sayfayı yeniden tarayın.", gpu=gpu)
    if durum == hiz.AMD_WINDOWS:
        return t("{gpu} algılandı. Windows'ta AMD hızlandırması SesVer'de henüz kullanılamıyor: "
                 "DirectML eklentisi (torch-directml) yalnız eski PyTorch 2.4 ile çalışıyor, ses "
                 "modeli ise PyTorch 2.5 veya üstünü istiyor; AMD'nin Windows için PyTorch sürümü de "
                 "yalnız Python 3.12 ve belirli kartları destekliyor. SesVer işlemciyle (CPU) "
                 "çalışmaya devam eder.", gpu=gpu)
    if durum == hiz.PLATFORM:
        return t("{gpu} algılandı ama bu işletim sistemi/işlemci için hazır bir PyTorch hızlandırma "
                 "paketi yok; SesVer işlemciyle (CPU) çalışır.", gpu=gpu)
    return t("Ekran kartı algılanmadı; SesVer işlemciyle (CPU) çalışmaya devam eder.")


def _accel_status_md(scan):
    hw, info, p = scan
    names = ", ".join(escape(g["name"]) for g in hw["gpus"])
    detected = (t("**Algılanan ekran kartı:** {gpu}", gpu=names) if names
                else t("**Algılanan ekran kartı:** bulunamadı"))
    if _accel["restart"]:
        # Yeni PyTorch diskte, eskisi bellekte: "kullanılacak cihaz" yeniden başlatana dek anlamsız.
        return detected + "\n\n" + t("🔄 **SesVer'i kapatıp yeniden açın.** Yeni PyTorch kuruldu; değişiklik "
                                     "ancak yeniden başlatınca devreye girer. O zamana kadar ses üretimi kapalı.")
    lines = [detected,
             t("**Ses modelinin kullanacağı cihaz:** {backend}",
               backend=_backend_label(hiz.active_backend(info))),
             t("**Kurulu PyTorch:** {version}", version=escape(info["version"]))
             if info and info.get("version") else t("**Kurulu PyTorch:** okunamadı")]
    return "  \n".join(lines) + "\n\n" + _accel_plan_md(p)


def _accel_can_install(scan):
    return scan[2]["durum"] == hiz.INSTALL and not _accel["restart"]


def _accel_can_rollback(scan):
    hw, info, _p = scan
    return hw["system"] != "Darwin" and hiz.build_of(info) in ("cuda", "rocm") and not _accel["restart"]


def _accel_need_md(scan):
    target = scan[2]["hedef"] if _accel_can_install(scan) else ("cpu" if _accel_can_rollback(scan) else None)
    if not target:
        return gr.update(value="", visible=False)
    download, disk = hiz.SIZES[target]
    return gr.update(visible=True, value=t(
        "**Gereksinimler:** internet bağlantısı, yaklaşık {download} GB indirme ve en az {disk} GB boş "
        "disk alanı. Bağlantınıza göre 5–30 dakika sürebilir; bu sırada ses üretilemez.",
        download=download, disk=disk))


def _accel_refresh(force=False):
    """Sekme açılınca/“Yeniden tara”: durum, düğmeler ve gereksinim notu."""
    if _accel["busy"]:
        return (gr.update(), gr.update(), gr.update(), gr.update())
    scan = _accel_scan(force)
    return (_accel_status_md(scan), gr.update(visible=_accel_can_install(scan), interactive=True),
            gr.update(visible=_accel_can_rollback(scan), interactive=True), _accel_need_md(scan))


def _accel_install_ui(target):
    """target "gpu": algılanan karta uygun derleme; "cpu": hızlandırmayı kaldırıp CPU derlemesi.

    Çıktılar: sonuç iletisi, kurulum günlüğü, etkinleştir/geri dön düğmeleri, durum, gereksinim
    notu. İlerleme sonuç iletisine yazılır (Gradio'nun bekleme katmanı metni soluklaştırıyor).
    """
    if not _accel_lock.acquire(blocking=False):
        raise gr.Error(t("Kurulum zaten sürüyor."))
    try:
        if not _model_lock.acquire(blocking=False):
            raise gr.Error(t("Şu an ses üretiliyor; bitmesini bekleyip tekrar deneyin."))
        _model_lock.release()
        if hiz.windows_files_locked():
            raise gr.Error(t("Ses modeli bu oturumda yüklendiği için PyTorch dosyaları kilitli. SesVer'i "
                             "kapatıp yeniden açın ve ses üretmeden önce kurulumu buradan başlatın."))
        scan = _accel_scan()
        tag = hiz.CPU if target == "cpu" else scan[2]["etiket"]
        allowed = _accel_can_rollback(scan) if target == "cpu" else _accel_can_install(scan)
        if not tag or not allowed:
            raise gr.Error(t("Bu sistem için uygun PyTorch paketi bulunamadı."))
        size_key = "cpu" if target == "cpu" else scan[2]["hedef"]
        need, free = hiz.SIZES[size_key][1], hiz.free_gb()
        if free is not None and free < need:
            raise gr.Error(t("Yeterli disk alanı yok: {free} GB boş, en az {need} GB gerekir.",
                             free=f"{free:.1f}", need=need))
        _accel["busy"] = True
        off, keep = gr.update(interactive=False), gr.update()

        def ui(msg, log_value=keep, buttons=off, status=keep, need_md=keep):
            return msg, log_value, buttons, buttons, status, need_md

        def done_ui(msg, log_value=keep):
            """Bitiş: durum, düğmeler ve not taze taramayla yeniden çizilir."""
            _accel["busy"] = False
            status, install, rollback, need_md = _accel_refresh(force=not _accel["restart"])
            return msg, log_value, install, rollback, status, need_md

        yield ui(t("PyTorch sürümleri kontrol ediliyor…"), gr.update(value="", visible=True))
        installed = hiz.installed_versions()
        try:
            versions = hiz.resolve(tag, installed)
        except OSError:
            yield done_ui(t("PyTorch indirme sunucusuna bağlanılamadı. İnternet bağlantınızı kontrol edin."),
                          gr.update(visible=False))
            return
        if not versions:
            yield done_ui(t("Bu sistem için uygun PyTorch paketi bulunamadı."), gr.update(visible=False))
            return
        cmd = hiz.install_command(tag, *versions, pip_version=installed.get("pip"))
        log.info("Hızlandırma kurulumu: %s", " ".join(cmd[1:]))
        lines = ["$ pip " + " ".join(cmd[4:])]
        working = "⏳ " + t("İndiriliyor ve kuruluyor… Pencereyi kapatmayın.")
        yield ui(working, "\n".join(lines))
        proc = hiz.start_install(cmd)
        last = perf_counter()
        for raw in proc.stdout:
            got = hiz.parse_progress(raw)
            if got:
                working = "⏳ " + t("İndiriliyor… {done} / {total} MB", done=got[0] // 2 ** 20,
                                    total=got[1] // 2 ** 20) + f" ({got[0] * 100 // got[1]}%)"
            elif raw.strip():
                lines = (lines + [raw.rstrip()])[-60:]
                if lines[-1].startswith("Installing collected packages"):
                    working = "⏳ " + t("İndiriliyor ve kuruluyor… Pencereyi kapatmayın.")
            if perf_counter() - last > 0.5:
                last = perf_counter()
                yield ui(working, "\n".join(lines))
        code = proc.wait()
        log_text = "\n".join(lines)
        if code != 0:
            log.warning("Hızlandırma kurulumu başarısız (çıkış kodu %s)", code)
            if hiz.build_of(hiz.probe_torch()) is None:
                # pip normalde geri alır; alamadıysa (ör. disk doldu) bunu saklamıyoruz.
                msg = t("❌ Kurulum başarısız oldu (çıkış kodu {code}) ve PyTorch şu an okunamıyor. İnternet "
                        "bağlantısını ve disk alanını kontrol edip kurulumu tekrarlayın; ayrıntılar günlükte.",
                        code=code)
            else:
                msg = t("❌ Kurulum başarısız oldu (çıkış kodu {code}). Mevcut PyTorch korunur ve SesVer "
                        "eskisi gibi çalışır; ayrıntılar günlükte.", code=code)
            yield done_ui(msg, log_text)
            return
        _accel["restart"] = True  # bu süreçteki eski torch'la artık üretim yapılmasın
        yield ui("⏳ " + t("Kurulum doğrulanıyor…"), log_text)
        info = hiz.probe_torch()
        log_text += f"\n\ntorch {info.get('version') if info else '?'}"
        if target == "cpu":
            msg = t("✅ İşlemci (CPU) sürümü kuruldu.")
        elif info and info.get("cuda_ok"):
            msg = t("✅ Kurulum tamamlandı; {gpu} PyTorch tarafından görüldü.",
                    gpu=escape(info.get("device_name") or scan[2]["gpu"] or ""))
        else:
            msg = t("⚠️ Kurulum tamamlandı ama test sırasında ekran kartı görülemedi. Yeniden "
                    "başlattıktan sonra bu sayfadan durumu kontrol edin.")
        yield done_ui(msg, log_text)
    finally:
        _accel["busy"] = False
        _accel_lock.release()


# --- Hata raporu (kullanıcı onaylı; mailto + dosya, hiçbir şey kendiliğinden gönderilmez) ---------
# Rapor içeriği ve maskeleme hata_raporu.py'de; burada yalnız önizleme/onay arayüzü var.


def report_open_ui(include_prev=None):
    """“Hata raporu gönder”: raporu kurar ve önizleme kutusunu açar (henüz hiçbir şey açılmaz/gönderilmez)."""
    prev_exists = hata_raporu.PREV_LOG_PATH.is_file()
    if include_prev is None:  # varsayılan: önceki oturumun günlüğü hata içeriyorsa eklenir
        include_prev = prev_exists and hata_raporu.log_has_error()
    include_prev = bool(include_prev) and prev_exists
    report = hata_raporu.build_report(include_previous=include_prev)
    return (gr.update(visible=True), gr.update(visible=prev_exists, value=include_prev),
            report["text"], report, "")


def report_rebuild_ui(include_prev):
    report = hata_raporu.build_report(include_previous=bool(include_prev))
    return report["text"], report


def report_send_ui(report):
    """Onaydan sonra: dosyayı kaydet + klasörde göster + e-posta TASLAĞI aç (gönderen kullanıcıdır)."""
    if not report:
        raise gr.Error(t("Önce “Hata raporu gönder” ile raporu hazırlayın."))
    try:
        path, opened = hata_raporu.send(report)
    except OSError as exc:
        raise gr.Error(t("Rapor dosyası yazılamadı: {hata}", hata=f"{type(exc).__name__}: {exc}")) from exc
    return hata_raporu.send_message(path, opened, fmt_path=lambda p: f"`{p}`", fmt_addr=lambda a: f"**{a}**")


def report_copy_ui(report):
    if not report:
        raise gr.Error(t("Önce “Hata raporu gönder” ile raporu hazırlayın."))
    ok = hata_raporu.copy_to_clipboard(hata_raporu.clipboard_text(report))
    return hata_raporu.copy_message(ok, fmt_addr=lambda a: f"**{a}**")


def _report_panel(lang, visible=False):
    """“Hata raporu gönder” düğmesi + önizleme/onay kutusu. Düğmeyi döndürür (görünürlüğü dışarıdan yönetilir)."""
    button = gr.Button(t("Hata raporu gönder"), size="sm", visible=visible,
                       elem_classes=["sv-btn", "sv-mini", "sv-report-btn"])
    report = gr.State(None)
    with gr.Column(visible=False, elem_classes=["sv-report"]) as box:
        consent, details = hata_raporu.consent_text()
        gr.Markdown(f"**{consent}** {details}", elem_classes=["sv-report-consent"])
        prev = gr.Checkbox(label=t("Önceki oturumun günlüğünü de ekle"), value=False, visible=False)
        text = gr.Textbox(label=t("Rapor önizlemesi"), lines=12, max_lines=12, interactive=False,
                          elem_classes=["sv-report-text"])
        with gr.Row(elem_classes=["sv-report-actions"]):
            mail = gr.Button(t("E-posta uygulamasında aç"), size="sm", scale=0,
                             elem_classes=["sv-btn", "sv-mini", "sv-mini-dark"])
            copy = gr.Button(t("Panoya kopyala"), size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
            cancel = gr.Button(t("Vazgeç"), size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
        gr.Markdown(hata_raporu.recipient_text(f"**{hata_raporu.DESTEK_EPOSTA}**"), elem_classes=["sv-fine-md"])
        msg = gr.Markdown("", elem_classes=["sv-fine-md"])
    button.click(_in_lang(lambda: report_open_ui(), lang), outputs=[box, prev, text, report, msg],
                 show_progress="minimal")
    prev.input(_in_lang(report_rebuild_ui, lang), inputs=prev, outputs=[text, report], show_progress="minimal")
    mail.click(_in_lang(report_send_ui, lang), inputs=report, outputs=msg, show_progress="minimal")
    copy.click(_in_lang(report_copy_ui, lang), inputs=report, outputs=msg, show_progress="hidden")
    cancel.click(lambda: (gr.update(visible=False), None, ""), outputs=[box, report, msg], queue=False)
    return button


def _watch_failures(trigger, button, **run):
    """``trigger`` (ör. ``button.click``) → rapor düğmesini gizle → üretim (``run``) → üretim sırasında
    yeni bir hata kaydedildiyse düğmeyi göster. Üretim olayını döndürür (``.then``/``cancels`` için).

    Adımlar zincirlenir: gizleme + hata sayacı anlık görüntüsü üretimden ÖNCE kesinleşir (paralel
    olaylarda hızlı düşen bir üretim sayacı anlık görüntüden önce artırabiliyordu). Üretim
    işlevlerinin çıktıları ve API'leri değişmez.
    """
    seen = gr.State(0)
    event = trigger(lambda: (gr.update(visible=False), _ui_hata_sayisi()), outputs=[button, seen],
                    queue=False, show_progress="hidden").then(**run)
    event.then(lambda n: gr.update(visible=_ui_hata_sayisi() > int(n or 0)), inputs=seen,
               outputs=button, queue=False, show_progress="hidden")
    return event


def _ui_hata_sayisi():
    """Arayüzdeki üretimlerin hata sayısı: arka planda çalışan kuyruğun hataları sayılmaz (onlar
    kuyruk listesinde görünür); yoksa elle üretim beklerken düşen bir kuyruk öğesi bu sekmedeki
    “Hata raporu gönder” düğmesini yanlışlıkla gösterirdi."""
    return hata_raporu.error_count() - _kuyruk_hata_sayisi


def _update_toggle_ui(acik):
    """Ayarlar → "Açılışta güncellemeleri denetle" değişince ayarlar.json'a yazar."""
    acik = guncelleme.ayar_degistir(acik)
    return t("Kaydedildi: açılışta güncellemeler denetlenecek.") if acik else \
        t("Kaydedildi: açılışta güncelleme denetimi yapılmayacak.")


def _update_check_now_ui(lang):
    """Ayarlar → "Güncellemeleri şimdi denetle": o an GitHub'a bakar, sonucu hemen gösterir.

    Kullanıcı bastığı için açılış ayarı kapalıyken de çalışır. İstek sürerken düğme pasif ve
    "Denetleniyor…" yazar; art arda basma ya da ikinci sekme yeni istek atmaz
    (guncelleme.elle_denetle tek uçuş)."""
    def denetle():
        yield (gr.update(value=t("Denetleniyor…", lang), interactive=False),
               gr.update(value="", visible=False))
        sonuc = guncelleme.elle_denetle()
        yield (gr.update(value=t("Güncellemeleri şimdi denetle", lang), interactive=True),
               gr.update(value=guncelleme.denetim_html(sonuc, lang=lang), visible=True))
    return denetle


def _settings_tab():
    """Ayarlar sekmesi: ekran kartı algılama ve hızlandırmalı PyTorch kurulumu + sorun bildirme."""
    lang = i18n.get_lang()
    with gr.Row(equal_height=False, elem_classes=["sv-grid"]):
        with gr.Column(scale=7, min_width=340, elem_classes=["sv-frame"]):
            _html(
                f'<div class="sv-frame-bar"><div class="sv-chips">'
                f'<span class="sv-chip">{_svg(_IC_CPU)}{t("Donanım")}</span></div>'
                f'<span class="sv-chip sv-chip-dark">{_svg(_IC_LOCK)}{t("Yerel")}</span></div>'
            )
            with gr.Column(elem_classes=["sv-panel"]):
                _head(_IC_CPU, t("Ekran kartı hızlandırma"),
                      t("SesVer ekran kartınızı otomatik algılar; uygunsa doğru PyTorch sürümünü buradan "
                        "kurar. Hiçbir şeye dokunmazsanız SesVer bugünkü gibi çalışmaya devam eder."))
                status = gr.Markdown(t("Donanım taranıyor…"), elem_classes=["sv-status", "sv-accel-status"])
                need = gr.Markdown("", visible=False, elem_classes=["sv-fine-md"])
                with gr.Row():
                    install = gr.Button(t("Hızlandırmayı etkinleştir"), variant="primary", visible=False,
                                        elem_classes=["sv-btn", "sv-btn-primary", "sv-ic-download"])
                    rollback = gr.Button(t("İşlemci (CPU) sürümüne geri dön"), visible=False,
                                         elem_classes=["sv-btn", "sv-btn-soft", "sv-ic-undo"])
                    rescan = gr.Button(t("Yeniden tara"), elem_classes=["sv-btn", "sv-btn-soft", "sv-ic-refresh"])
                result = gr.Markdown("", elem_classes=["sv-fine-md"])
                log_box = gr.Textbox(label=t("Kurulum günlüğü"), lines=10, max_lines=16, interactive=False,
                                     visible=False, autoscroll=True, elem_classes=["sv-accel-log"])
                _html('<p class="sv-fine">' + t(
                    "<b>Neden yeniden başlatma?</b> PyTorch'un işlemci (CPU), NVIDIA (CUDA) ve AMD (ROCm) "
                    "sürümleri ayrı paketlerdir; çalışan uygulama kullandığı sürümü değiştiremez. "
                    "Apple Silicon Mac'te ekran kartı zaten kullanılır.") + "</p>")
        with gr.Column(scale=5, min_width=300, elem_classes=["sv-side"]):
            with gr.Column(elem_classes=["sv-card"]):
                _head(_IC_SHIELD, t("Sorun bildir / Hata raporu gönder"),
                      t("Bir sorun yaşarsanız teknik raporu (sistem bilgisi ve günlüğün son satırları) "
                        "e-postayla geliştiriciye gönderebilirsiniz. Önce raporu görürsünüz; hiçbir şey "
                        "kendiliğinden gönderilmez."))
                _report_panel(lang, visible=True)
            with gr.Column(elem_classes=["sv-card"]):
                _head(_IC_CLOUD, t("Güncellemeler"),
                      t("Bu sürüm: <b>v{surum}</b>. Açılışta yalnız GitHub'daki son sürüm numarasına "
                        "bakılır (tek bir istek, en fazla 3 sn); hiçbir kişisel veri gönderilmez.",
                        surum=escape(surum.__version__)))
                # Değer sabit verilir; Ayarlar açılınca yenilenir (_build_page). Çağrılabilir değer
                # (value=fonksiyon) Gradio'da her sayfa için önceki sayfaların yükleme olaylarını da
                # biriktiriyordu: /ar'da 21, /ja'da 66 kuyruk isteği → "currently busy" (max_size=8).
                update_check = gr.Checkbox(
                    label=t("Açılışta güncellemeleri denetle"), value=guncelleme.ayar_acik_mi(),
                    elem_classes=["sv-update-toggle"])
                update_msg = gr.Markdown("", elem_classes=["sv-fine-md"])
                update_now = gr.Button(t("Güncellemeleri şimdi denetle"), size="sm",
                                       elem_classes=["sv-btn", "sv-btn-soft", "sv-ic-refresh", "sv-update-now"])
                update_result = _html("", visible=False, elem_classes=["sv-update-result"])
    update_check.input(_in_lang(_update_toggle_ui, lang), inputs=update_check, outputs=update_msg,
                       queue=False, show_progress="hidden")
    # trigger_mode="once": istek sürerken yeni tıklama yok sayılır; ayrıca sunucuda tek uçuş.
    update_now.click(_update_check_now_ui(lang), outputs=[update_now, update_result], trigger_mode="once",
                     concurrency_limit=1, concurrency_id="sv-guncelleme-elle", show_progress="hidden",
                     api_visibility="private")
    refresh_out = [status, install, rollback, need]

    def enable_gpu():
        yield from _accel_install_ui("gpu")

    def back_to_cpu():
        yield from _accel_install_ui("cpu")

    install_out = [result, log_box, install, rollback, status, need]
    install.click(enable_gpu, outputs=install_out, concurrency_limit=1, show_progress="hidden")
    rollback.click(back_to_cpu, outputs=install_out, concurrency_limit=1, show_progress="hidden")
    rescan.click(lambda: _accel_refresh(force=True), outputs=refresh_out, show_progress="minimal")
    return lambda: _accel_refresh(), refresh_out, update_check


# --- Üretim kuyruğu: akşam sıraya koy, sabah sonuçları gör ------------------------------
# Çekirdek kuyruk.py'de (kalıcı kayıt, tek işçi, uzun metin parçaları, uyku engeli, ozet.txt);
# metin/HTML parçaları kuyruk_arayuz.py'de. Burada: model çağrısı (uret_fn), efekt, hata
# sınıflandırma ve arayüz bağlantısı. Kuyruk ilk kullanımda kurulur (arayüz kurulurken diske
# yazılmaz). Kuyruk işçisi model kilidini elle üretimle paylaşır; elle Üret parça arasında
# araya girer (_elle_oncelikli).

_KUYRUK = None
_KUYRUK_KURULUM = Lock()
_kuyruk_hata_sayisi = 0  # kuyruk işçisinin kaydettiği hatalar (_ui_hata_sayisi bunları düşer)
_kuyruk_ortam_onbellek = {"zaman": -1e9, "pilde": None}
_IC_QUEUE = '<path d="M4 6.5h11M4 12h11M4 17.5h6"/><path d="m15.5 14.5 5 3-5 3z"/>'
_IC_UPLOAD = '<path d="M12 16V4m-5 5 5-5 5 5M5 20h14"/>'
_IC_PLUS = '<path d="M12 5v14M5 12h14"/>'


class KuyrukUretimHatasi(Exception):
    """Kuyruk öğesine özgü, kodu bilinen üretim hatası (ör. referans kopyası silinmiş)."""

    def __init__(self, kod):
        super().__init__(kod)
        self.kod = kod


def _kuyruk():
    """Süreç genelindeki tek kuyruk (ilk çağrıda kurulur; açılışta yarıda kalanı beklemeye alır)."""
    global _KUYRUK
    with _KUYRUK_KURULUM:
        if _KUYRUK is None:
            _KUYRUK = kq.Kuyruk(
                cikti_dir=OUTPUT_DIR, uret_fn=_kuyruk_parca_uret, efekt_fn=_kuyruk_efekt,
                siniflandir=_kuyruk_siniflandir, blok_fn=_accel_block_reason, temizlik_fn=_kuyruk_temizlik,
                ceviri=lambda s, **kw: t(s, **kw), hata_metni=qa.hata_metni)
        return _KUYRUK


def _kuyruk_istek_ayarlari(istek):
    """Kuyruk isteği → (referans, talimat, referans metni, adım sayısı, günlük kipi).

    Kip kuralları elle üretimle aynıdır: rastgele → referanssız; kayıtlı ses + Nötr → devam;
    kayıtlı ses + duygu → kontrollü klon; klon → referans (+ varsa metni) ve duygu.
    """
    instruction = EMOTIONS.get(istek.get("duygu"))
    steps = QUALITY.get(istek.get("kalite"), 10)
    ref = istek.get("ref_yol")
    if istek.get("tur") == "klon":
        return ref, instruction, istek.get("ref_metin") or None, steps, "kuyruk-klon"
    if (istek.get("ses_id") or RANDOM_VOICE) == RANDOM_VOICE:
        return None, instruction, None, steps, "kuyruk-rastgele"
    if instruction:
        return ref, instruction, None, steps, "kuyruk-kontrollu-klon"
    return ref, None, istek.get("ref_metin") or None, steps, "kuyruk-devam"


def _kuyruk_parca_uret(istek, hedef):
    """Kuyruk işçisinin uret_fn'i: tek parçayı `hedef` WAV'ına yazar, hatada istisna fırlatır.

    generate_audio ile aynı model, kilit ve tek seferlik GPU→CPU geçişi; ama ileti üretmez
    (işçi iş parçacığında arayüz dili yoktur) ve 500 karakter sınırını parça zaten sağlar.
    """
    # Elle üretimdeki gibi: parça metni ve referans metni modele gitmeden maskeye girer; kütüphane
    # uyarısı, ilerleme çıktısı ya da traceback sesver_log.txt'ye metni yazamaz. Önceki oturumdan
    # kalan (kuyruk.json'dan yüklenen) öğeler de bu yoldan geçer (siberguvenlik 1.3.0 bulgu A).
    hata_raporu.remember_private(istek.get("metin"), istek.get("ref_metin"))
    reference, instruction, prompt_text, steps, kip = _kuyruk_istek_ayarlari(istek)
    if reference:
        try:
            if not 1 <= sf.info(reference).duration <= 30:
                raise ValueError("referans süresi")
        except (OSError, RuntimeError, ValueError) as exc:
            raise KuyrukUretimHatasi("ref_okunamadi") from exc
    with _model_lock:
        model = get_model()
        _mode, kwargs = _build_kwargs(istek["metin"], reference, instruction, prompt_text, steps,
                                      voice_id=istek.get("ses_id") or "klon", log_mode=kip)
        try:
            wav = model.generate(**kwargs)
        except Exception as exc:
            code, _reason = hata_raporu.classify_error(exc)
            if code not in ("cuda_kernel", "cuda_oom") or _gpu_disabled:
                raise
            log.warning("kuyruk: ekran kartı hatası (%s), bu oturumda CPU'ya tek seferlik geçiliyor", code)
            model = _reload_model_cpu()
            wav = model.generate(**kwargs)
        sf.write(str(hedef), wav, model.tts_model.sample_rate)


def _kuyruk_efekt(ham, hedef, efektler):
    """Birleşmiş ham sesin efektli kopyası (ham dosya korunur; apply_effects_ui eski kopyaları sildiği
    için kullanılmaz)."""
    audio, sr = sf.read(str(ham), dtype="float32", always_2d=True)
    out = fx.apply(audio.mean(axis=1), sr, fx.clean_settings(efektler))
    sf.write(str(hedef), out, sr, subtype="PCM_16")


def _kuyruk_siniflandir(exc, oge):
    """Hata kaydı (metin günlükten/rapordan maskelenir) + kuyruğun saklayacağı hata kodu."""
    global _kuyruk_hata_sayisi
    entry = hata_raporu.record_error(exc, redact=[oge.get("metin"), oge.get("ref_metin")], where="kuyruk")
    _kuyruk_hata_sayisi += 1
    return getattr(exc, "kod", None) or entry["code"]


def _kuyruk_temizlik():
    """Her parçadan sonra: çöp toplama, MPS/CUDA önbelleği; günlüğe yalnız boş bellek yazılır."""
    import gc
    import sys
    gc.collect()
    torch = sys.modules.get("torch")
    try:
        if torch is not None:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
                torch.mps.empty_cache()
    except Exception:  # noqa: BLE001 — önbellek boşaltılamasa da kuyruk sürer
        pass
    mem = hata_raporu.memory_info()
    if mem and mem[1]:
        log.info("kuyruk: boş bellek %.1f GB", mem[1] / 1024 ** 3)


def _kuyruk_ortam():
    """(pilde mi, model diskte mi, çıktı diskinde boş GB). Pil okuması 60 sn önbelleklenir."""
    import shutil
    import time
    import uyku_engeli
    now = time.monotonic()
    if now - _kuyruk_ortam_onbellek["zaman"] > 60:
        _kuyruk_ortam_onbellek.update(zaman=now, pilde=uyku_engeli.pilde_mi())
    # Model bellekte ya da önbellekte mi (generate_audio'daki ilk üretim iletisiyle aynı karar).
    model_var = _model_durumu() != "yok"
    try:
        hedef = OUTPUT_DIR if OUTPUT_DIR.exists() else OUTPUT_DIR.parent
        bos_gb = shutil.disk_usage(hedef).free / 1024 ** 3
    except OSError:
        bos_gb = None
    return _kuyruk_ortam_onbellek["pilde"], model_var, bos_gb


def _kuyruk_ses_ayarlari(voice_id):
    """Kütüphanedeki seçim → kuyruk öğesinin ses alanları (referans kuyruk/ref'e kopyalanır)."""
    voice_id = voice_id or RANDOM_VOICE
    if voice_id == RANDOM_VOICE:
        return {"ses_id": kq.RASTGELE, "ses_adi": "Rastgele ses", "ref_kaynak": None, "ref_metin": None}
    voice = vlib.get_voice(voice_id)
    if not voice:
        raise gr.Error(t("Seçili ses bulunamadı; kütüphaneden yeniden seçin."))
    return {"ses_id": voice_id, "ses_adi": voice["ad"], "ref_kaynak": voice["ref_wav"],
            "ref_metin": voice["ref_text"]}


def _kuyruga_ekle(tur, text, **ayarlar):
    k = _kuyruk()
    try:
        oge = k.ekle(tur, text, **ayarlar)
    except kq.KuyrukHatasi as exc:
        raise gr.Error(qa.red_metni(exc.kod, exc.bilgi)) from None
    ogeler = k.durum()["ogeler"]
    sira = next((i for i, o in enumerate(ogeler, 1) if o["id"] == oge["id"]), len(ogeler))
    if oge["parca_sayisi"] > 1:
        msg = t("**Kuyruğa eklendi:** listede {sira}. sırada; {n} parçaya bölündü, sonunda tek dosya olur.",
                sira=sira, n=oge["parca_sayisi"])
    else:
        msg = t("**Kuyruğa eklendi:** listede {sira}. sırada.", sira=sira)
    if k.calisiyor:
        return msg + " " + t("Kuyruk çalışıyor; sırası gelince üretilecek.")
    return msg + " " + t("Başlatmak için sağ üstteki **Kuyruk** düğmesine basın.")


def kuyruga_ekle_kutuphane_ui(text, emotion, quality, voice_id, *fx_vals):
    """Ses Kütüphanesi → “Kuyruğa ekle”: o anki ses, duygu, kalite ve efektlerin anlık görüntüsü."""
    ayarlar = _kuyruk_ses_ayarlari(voice_id)
    efektler = _fx_settings(*fx_vals) if fx_vals else []
    return _kuyruga_ekle("kutuphane", text, duygu=emotion or "Nötr", kalite=quality or "Dengeli",
                         efektler=efektler, **ayarlar)


def kuyruga_ekle_klon_ui(text, reference_audio, emotion, prompt_text):
    """Ses Klonlama → “Kuyruğa ekle”: referans ses kuyruk klasörüne kopyalanır (geçici dosya silinse de
    gece üretilebilsin). Klonda kalite/efekt yok (bugünkü davranış)."""
    if not reference_audio:
        raise gr.Error(t("Önce bir referans ses yükleyin."))
    try:
        if not 1 <= sf.info(reference_audio).duration <= 30:
            raise ValueError("referans süresi")
    except (OSError, RuntimeError, ValueError) as exc:
        raise gr.Error(t("Referans ses okunamadı. 1–30 saniyelik geçerli bir WAV yükleyin.")) from exc
    return _kuyruga_ekle("klon", text, ses_adi=f"Klon ({Path(reference_audio).stem[:40]})",
                         ref_kaynak=reference_audio, ref_metin=(prompt_text or "").strip() or None,
                         duygu=emotion or "Nötr", kalite="Dengeli")


def _kuyruk_gorunum():
    """Kuyruk görünümünün tüm parçaları (sıra _queue_wiring'deki `view` listesiyle aynı) ve sürüm."""
    k = _kuyruk()
    d = k.durum()
    etiket, sinif = qa.ust_dugme(d)
    ana_etiket, ana_etkin, durdur_mu = qa.ana_dugme(d)
    neden = qa.duraklatma_metni(d)
    calisiyor = d["durum"] in (kq.CALISIYOR, kq.DURUYOR)
    klasor = d.get("oturum_klasoru")
    pilde, model_var, bos_gb = _kuyruk_ortam()
    return (
        gr.update(value=etiket, elem_classes=["sv-btn", "sv-topbtn", "sv-top-kuyruk", sinif]),
        gr.update(visible=qa.banner_gorunur_mu(d)),
        qa.banner_html(d),
        # Özet, duraklatma nedeni ve liste tek blokta (boş bloklar araya boşluk koymasın).
        '<div class="sv-qview">' + qa.ozet_html(d)
        + (f'<div class="sv-qnote">{escape(neden)}</div>' if neden else "") + qa.liste_html(d) + "</div>",
        qa.simdi_html(d),
        qa.gece_html(d, pilde, model_var, bos_gb),
        gr.update(value=ana_etiket, interactive=ana_etkin,
                  elem_classes=["sv-btn", "sv-btn-primary"] + (["sv-ic-pause"] if durdur_mu else [])),
        gr.update(interactive=d["sayilar"][kq.BITTI] > 0 and not d["salt_okunur"]),
        gr.update(visible=bool(d["ogeler"]) and not calisiyor and not d["salt_okunur"]),
        gr.update(visible=bool(klasor and Path(klasor).is_dir())),
    ), d["surum"]


def kuyruk_komut_ui(act, oid):
    """Listedeki düğmeler: yukari, asagi, cikar, yeniden, dinle, klasor. (oynatıcı güncellemesi) döner."""
    k = _kuyruk()
    try:
        if act == "yukari":
            k.yukari(oid)
        elif act == "asagi":
            k.asagi(oid)
        elif act == "cikar":
            k.cikar(oid)
        elif act == "yeniden":
            k.yeniden_dene(oid)
        elif act in ("dinle", "klasor"):
            oge = next((o for o in k.durum()["ogeler"] if o["id"] == oid), None)
            yol = oge and (oge.get("efektli") or oge.get("cikti"))
            if not yol or not Path(yol).is_file():
                raise kq.KuyrukHatasi("oge_yok")
            if act == "dinle":
                return yol
            hata_raporu.reveal(yol)
    except kq.KuyrukHatasi as exc:
        gr.Warning(qa.red_metni(exc.kod, exc.bilgi))
    return None


def kuyruk_baslat_durdur_ui():
    k = _kuyruk()
    if k.calisiyor:
        k.durdur()
        gr.Info(t("Şu anki parça bitince kuyruk duracak. Kalan öğeler kaybolmaz."))
        return
    blocked = _accel_block_reason()
    if blocked:
        gr.Warning(blocked)
        return
    try:
        k.baslat()
    except kq.KuyrukHatasi as exc:
        gr.Warning(qa.red_metni(exc.kod, exc.bilgi))
        return
    import uyku_engeli
    if uyku_engeli.pilde_mi():
        gr.Warning(t("Bilgisayar pilde çalışıyor. Gece boyu sürmesi için prize takın ve kapağı açık bırakın."))


def _ses_bulucu():
    """İçe aktarma: hücredeki ses adı → kayıtlı ses (Türkçe/İngilizce yazım ve hazır seslerin tüm
    çevirileri kabul edilir; büyük/küçük harf ve Türkçe harf farkı gözetilmez)."""
    tablo = {}
    for v in vlib.list_voices():
        adlar = {v["ad"]} | (i18n.all_translations(v["ad"]) if v["hazir"] else set())
        for ad in adlar:
            tablo.setdefault(ice_aktarma.katla(ad), {"id": v["id"], "ad": v["ad"], "ref_wav": v["ref_wav"],
                                                    "ref_text": v["ref_text"]})
    return lambda ad: tablo.get(ice_aktarma.katla(ad))


def _ice_ayarlar(ses_id, duygu, kalite):
    try:
        ses = _kuyruk_ses_ayarlari(ses_id)
    except gr.Error:
        ses = _kuyruk_ses_ayarlari(RANDOM_VOICE)
    return dict(ses, tur="kutuphane", duygu=duygu or "Nötr", kalite=kalite or "Dengeli", efektler=[])


def _ice_hesapla(yol, ses_id, duygu, kalite, kip, kalan_yer):
    csv_mi = Path(yol).suffix.lower() == ".csv"
    # Boyut okumadan önce denetlenir; okuma da sınırla kesilir (dosya bu arada büyüse bile).
    sinir = ice_aktarma.DOSYA_EN_FAZLA_BAYT
    if Path(yol).stat().st_size > sinir:
        return ice_aktarma.Onizleme(hata="dosya_buyuk"), csv_mi
    with Path(yol).open("rb") as f:
        veri = f.read(sinir + 1)
    ayar = _ice_ayarlar(ses_id, duygu, kalite)
    if csv_mi:
        return ice_aktarma.onizle_csv(veri, ayar, ses_bul=_ses_bulucu(), kalan_yer=kalan_yer), csv_mi
    return ice_aktarma.onizle_txt(veri, kip or "paragraf", ayar, kalan_yer=kalan_yer), csv_mi


def ice_onizle_ui(yol, ses_id, duygu, kalite, kip):
    """İçe aktarma önizlemesi: (dosya bilgisi + özet + uyarı + tablo HTML'i, ekle düğmesi). Kuyruğa EKLEMEZ."""
    if not yol:
        return "", gr.update(value=t("Kuyruğa ekle"), interactive=False)
    kuyrukta = len(_kuyruk().durum()["ogeler"])
    try:
        tum, csv_mi = _ice_hesapla(yol, ses_id, duygu, kalite, kip, 10 ** 6)
        sinirli, _ = _ice_hesapla(yol, ses_id, duygu, kalite, kip, kq.KUYRUK_EN_FAZLA - kuyrukta)
    except OSError:
        return ('<div class="sv-qwarnbox">' + escape(t("Dosya okunamadı.")) + "</div>",
                gr.update(value=t("Kuyruğa ekle"), interactive=False))
    ozet, uyari, tablo, n = qa.ice_onizleme(tum, sinirli, kuyrukta)
    dosya = "" if tum.hata else qa.ice_dosya_html(Path(yol).name, tum, csv_mi)
    etiket = t("{n} öğeyi kuyruğa ekle", n=n) if n else t("Eklenecek öğe yok")
    return ('<div class="sv-qview">' + dosya + ozet + uyari + tablo + "</div>",
            gr.update(value=etiket, interactive=n > 0))


def ice_ekle_ui(yol, ses_id, duygu, kalite, kip):
    """Onaydan sonra: önizlemedeki öğeler kuyruğa eklenir (hepsi ya da hiçbiri). Eklenen sayısı döner."""
    if not yol:
        raise gr.Error(t("Önce bir TXT ya da CSV dosyası seçin."))
    k = _kuyruk()
    sinirli, _ = _ice_hesapla(yol, ses_id, duygu, kalite, kip,
                              kq.KUYRUK_EN_FAZLA - len(k.durum()["ogeler"]))
    if sinirli.hata or not sinirli.ogeler:
        raise gr.Error(t("Eklenecek öğe yok."))
    try:
        eklenen = k.ekle_toplu(sinirli.istekler())
    except kq.KuyrukHatasi as exc:
        raise gr.Error(qa.red_metni(exc.kod, exc.bilgi)) from None
    log.info("kuyruk: içe aktarma %d öğe ekledi (%d satır reddedildi)", len(eklenen), len(sinirli.reddedilen))
    return len(eklenen)


def _sablon_yolu(lang):
    """İndirilebilir örnek CSV (UTF-8 BOM, `;`): Türkçe sayfada Türkçe, diğerlerinde İngilizce başlıklar."""
    import tempfile
    dil = "tr" if lang == i18n.DEFAULT else "en"
    yol = Path(tempfile.gettempdir()) / "sesver-sablon" / ("kuyruk-ornegi.csv" if dil == "tr" else "queue-template.csv")
    try:
        yol.parent.mkdir(parents=True, exist_ok=True)
        veri = ice_aktarma.sablon_csv(dil)
        if not yol.is_file() or yol.read_bytes() != veri:
            yol.write_bytes(veri)
    except OSError:
        return None
    return str(yol)


def _voice_choices():
    return [("🎲 " + t("Rastgele ses"), RANDOM_VOICE)] + [(_voice_name(v), v["id"]) for v in vlib.list_voices()]


def _queue_tab(lang, lib):
    """Kuyruk görünümü (taslak A): solda geniş liste, sağda şu an / kuyruğa ekle / gece boyunca.
    İçe aktarma önizlemesi (taslak D) aynı görünümde açılan kart. Olaylar _queue_wiring'de."""
    with gr.Column(visible=False, elem_classes=["sv-card", "sv-import"]) as ice_col:
        with gr.Row(elem_classes=["sv-import-top"]):
            _head(_IC_UPLOAD, t("Dosyadan içe aktar"),
                  t("Önizleme: onaylamadan kuyruğa hiçbir şey eklenmez. Dosya yalnız bu bilgisayarda okunur."))
            ice_close = gr.Button(t("✕ Kapat"), size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
        ice_file = gr.File(label=t("TXT ya da CSV dosyası"), file_types=[".txt", ".csv"], type="filepath",
                           elem_classes=["sv-file"])
        with gr.Row(elem_classes=["sv-import-cols"]):
            ice_voice = gr.Dropdown(choices=_voice_choices(), value=RANDOM_VOICE, filterable=False,
                                    label=t("Varsayılan ses (sütunu boş satırlar)"), min_width=200)
            ice_emotion = gr.Dropdown(choices=_choices(EMOTIONS), value="Nötr", label=t("Duygu"),
                                      filterable=False, min_width=150)
            ice_quality = gr.Dropdown(choices=_choices(QUALITY), value="Dengeli", label=t("Kalite"),
                                      filterable=False, min_width=150)
            ice_mode = gr.Radio(choices=[(t("Tamamı tek öğe"), "tek"), (t("Her paragraf ayrı öğe"), "paragraf")],
                                value="paragraf", label=t("TXT dosyasında"), min_width=220,
                                elem_classes=["sv-emotion", "sv-plain"])
        ice_view = _html("")
        _html('<p class="sv-fine">' + t("<b>Reddedilen satırlar</b> eklenmez; dosyayı düzeltip yeniden "
                                        "yükleyebilirsiniz. Sütun adları Türkçe ya da İngilizce olabilir "
                                        "(metin/text, ses/voice, duygu/emotion, kalite/quality).") + "</p>")
        with gr.Row(elem_classes=["sv-actionbar"]):
            _html('<div class="sv-hint">' + t("Uzun öğeler cümle sonlarından en fazla 500 karakterlik "
                                              "parçalara bölünür, sonunda tek WAV olur.") + "</div>")
            ice_cancel = gr.Button(t("Vazgeç"), scale=0, min_width=120, elem_classes=["sv-btn", "sv-btn-queue",
                                                                                      "sv-no-ic"])
            ice_add = gr.Button(t("Kuyruğa ekle"), variant="primary", interactive=False, scale=0, min_width=200,
                                elem_classes=["sv-btn", "sv-btn-primary", "sv-ic-plus"])

    with gr.Row(equal_height=False, elem_classes=["sv-grid"]) as main_grid:
        with gr.Column(scale=7, min_width=340, elem_classes=["sv-frame"]):
            _frame_bar([f"{_svg(_IC_QUEUE)}{t('Üretim kuyruğu')}", t("Sırayla, tek tek")])
            with gr.Column(elem_classes=["sv-panel"]):
                _head(_IC_QUEUE, t("Kuyruk"),
                      t("Öğeler sırayla üretilir. Biri hata verirse kuyruk durmaz, sonrakine geçer."))
                listing = gr.HTML("", js_on_load=qa.LISTE_JS, apply_default_css=False,
                                  elem_classes=["sv-qlist-wrap"])
                with gr.Row(visible=False, elem_classes=["sv-confirm"]) as confirm_row:
                    _html('<p class="sv-fine">' + t("Kuyruk boşaltılsın mı? Liste ve referans kopyaları silinir; "
                                                    "üretilmiş ses dosyaları klasörde kalır.") + "</p>")
                    confirm_yes = gr.Button(t("Evet, boşalt"), size="sm", scale=0,
                                            elem_classes=["sv-btn", "sv-mini", "sv-mini-danger"])
                    confirm_no = gr.Button(t("Vazgeç"), size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
                with gr.Row(elem_classes=["sv-actionbar", "sv-qactions"]):
                    _html('<div class="sv-hint">' + t("<b>Durdur:</b> şu anki parça bitince durur.<br>"
                                                      "Kalan öğeler kaybolmaz; “Devam et” ile sürer.") + "</div>")
                    clear_all = gr.Button(t("Kuyruğu boşalt"), size="sm", scale=0, visible=False,
                                          elem_classes=["sv-btn", "sv-mini", "sv-mini-danger"])
                    clear_done = gr.Button(t("Bitenleri temizle"), scale=0, min_width=150, interactive=False,
                                           elem_classes=["sv-btn", "sv-btn-queue", "sv-no-ic"])
                    main = gr.Button(t("Başlat"), variant="primary", scale=0, min_width=170, interactive=False,
                                     elem_classes=["sv-btn", "sv-btn-primary"])
        with gr.Column(scale=5, min_width=300, elem_classes=["sv-side"]):
            with gr.Column(elem_classes=["sv-card"]):
                now = _html("")
            with gr.Column(visible=False, elem_classes=["sv-card"]) as player_col:
                _head(_IC_PLAY, t("Dinle"), t("Kuyrukta biten öğe. AI ile üretildi."))
                player = gr.Audio(label=t("Üretilen ses (AI ile üretildi)"), type="filepath", interactive=False,
                                  autoplay=True, buttons=["download"], elem_classes=["sv-audio"])
            with gr.Column(elem_classes=["sv-card"]):
                _head(_IC_PLUS, t("Kuyruğa ekle"), t("En fazla 50 öğe; tek öğe 10.000 karaktere kadar."))
                import_btn = gr.Button(t("Dosyadan içe aktar (TXT / CSV)"),
                                       elem_classes=["sv-btn", "sv-btn-soft", "sv-ic-upload"])
                _html('<p class="sv-fine">' + t("<b>Ses Kütüphanesi</b> ve <b>Ses Klonlama</b> sekmelerinde "
                                                "“Üret”in yanındaki <b>Kuyruğa ekle</b> düğmesiyle de eklenir.")
                      + "</p>")
                gr.DownloadButton(t("Örnek CSV şablonu"), value=_sablon_yolu(lang), size="sm",
                                  elem_classes=["sv-btn", "sv-mini", "sv-template"])
            with gr.Column(elem_classes=["sv-card"]):
                night = _html("")
                folder_btn = gr.Button(t("Klasörü aç · ozet.txt"), visible=False,
                                       elem_classes=["sv-btn", "sv-btn-ghost"])
    return SimpleNamespace(
        ice_col=ice_col, ice_close=ice_close, ice_file=ice_file, ice_voice=ice_voice,
        ice_emotion=ice_emotion, ice_quality=ice_quality, ice_mode=ice_mode, ice_view=ice_view,
        ice_cancel=ice_cancel, ice_add=ice_add, main_grid=main_grid,
        listing=listing, confirm_row=confirm_row, confirm_yes=confirm_yes,
        confirm_no=confirm_no, clear_all=clear_all, clear_done=clear_done, main=main, now=now,
        player_col=player_col, player=player, import_btn=import_btn, night=night, folder_btn=folder_btn,
        lib=lib)


def _queue_wiring(demo, lang, q, queue_btn, banner, banner_html, banner_go, banner_show, tabs):
    """Kuyruk görünümünün olayları: 2 sn'lik yoklama (yalnız değişince yeniden çizer), liste
    düğmeleri, başlat/durdur, temizleme, içe aktarma ve sağ üstteki durum (\"Kuyruk 3/10\")."""
    view = [queue_btn, banner, banner_html, q.listing, q.now, q.night, q.main, q.clear_done, q.clear_all,
            q.folder_btn]
    seen = gr.State(-1)
    keep = tuple(gr.update() for _ in view)

    def full():
        with i18n.use(lang):
            parts, surum_ = _kuyruk_gorunum()
            return (*parts, surum_)

    def poll(last):
        if _KUYRUK is not None and last == _KUYRUK.surum:
            return (*keep, last)
        return full()

    quiet = dict(queue=False, show_progress="hidden")
    # gr.Info/gr.Warning yalnız kuyruktaki olaylarda görünür; işlemler kendi sınırsız havuzunda
    # çalışır (uzun bir elle üretim sürerken beklemezler).
    act = dict(show_progress="hidden", concurrency_limit=None, concurrency_id="sv-kuyruk-islem")
    gr.Timer(2.0).tick(poll, inputs=seen, outputs=[*view, seen], **quiet)
    demo.load(full, outputs=[*view, seen], **quiet)

    def command(evt: gr.EventData):
        data = getattr(evt, "_data", None) or {}
        with i18n.use(lang):
            path = kuyruk_komut_ui(str(data.get("act") or ""), str(data.get("id") or ""))
        player = (gr.update(visible=True), gr.update(value=path)) if path else (gr.update(), gr.update())
        return (*full(), *player)

    q.listing.click(command, outputs=[*view, seen, q.player_col, q.player], **act)

    def start_stop():
        with i18n.use(lang):
            kuyruk_baslat_durdur_ui()
        return full()

    q.main.click(start_stop, outputs=[*view, seen], **act)
    banner_go.click(start_stop, outputs=[*view, seen], **act)
    banner_show.click(lambda: gr.Tabs(selected="kuyruk"), outputs=tabs, **quiet)

    def clear_done():
        with i18n.use(lang):
            try:
                n = _kuyruk().bitenleri_temizle()
                gr.Info(t("{n} biten öğe listeden kaldırıldı; ses dosyaları klasörde duruyor.", n=n))
            except kq.KuyrukHatasi as exc:
                gr.Warning(qa.red_metni(exc.kod, exc.bilgi))
        return full()

    q.clear_done.click(clear_done, outputs=[*view, seen], **act)
    q.clear_all.click(lambda: gr.update(visible=True), outputs=q.confirm_row, **quiet)
    q.confirm_no.click(lambda: gr.update(visible=False), outputs=q.confirm_row, **quiet)

    def clear_all():
        with i18n.use(lang):
            try:
                _kuyruk().temizle()
            except kq.KuyrukHatasi as exc:
                gr.Warning(qa.red_metni(exc.kod, exc.bilgi))
        return (gr.update(visible=False), *full())

    q.confirm_yes.click(clear_all, outputs=[q.confirm_row, *view, seen], **act)

    def open_folder():
        klasor = _kuyruk().durum().get("oturum_klasoru")
        if klasor and Path(klasor).is_dir():
            ozet = Path(klasor) / "ozet.txt"
            hata_raporu.reveal(ozet if ozet.is_file() else klasor)

    q.folder_btn.click(open_folder, **quiet)

    # İçe aktarma (taslak D): kart açılır, liste gizlenir; onaylamadan hiçbir şey eklenmez.
    ice_inputs = [q.ice_file, q.ice_voice, q.ice_emotion, q.ice_quality, q.ice_mode]
    ice_outputs = [q.ice_view, q.ice_add]

    def ice_open(selected):
        with i18n.use(lang):
            choices = _voice_choices()
        value = selected if any(v == selected for _, v in choices) else RANDOM_VOICE
        return gr.update(visible=True), gr.update(visible=False), gr.update(choices=choices, value=value)

    def ice_close():
        return (gr.update(visible=False), gr.update(visible=True), None, "",
                gr.update(value=t("Kuyruğa ekle", lang), interactive=False))

    close_outputs = [q.ice_col, q.main_grid, q.ice_file, q.ice_view, q.ice_add]
    q.import_btn.click(ice_open, inputs=q.lib.selected, outputs=[q.ice_col, q.main_grid, q.ice_voice], **quiet)
    q.ice_close.click(ice_close, outputs=close_outputs, **quiet)
    q.ice_cancel.click(ice_close, outputs=close_outputs, **quiet)
    preview = _in_lang(ice_onizle_ui, lang)
    for control in (q.ice_file, q.ice_voice, q.ice_emotion, q.ice_quality, q.ice_mode):
        control.change(preview, inputs=ice_inputs, outputs=ice_outputs, **quiet)

    def ice_add(*values):
        with i18n.use(lang):
            n = ice_ekle_ui(*values)
            gr.Info(t("{n} öğe kuyruğa eklendi.", n=n))
        return (*ice_close(), *full())

    q.ice_add.click(ice_add, inputs=ice_inputs, outputs=[*close_outputs, *view, seen], **act)


def _setup_logging():
    """Yalnız SesVer'in tek satırlık istek loglarını terminale yazar."""
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [sesver] %(message)s", "%H:%M:%S"))
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


PORT_TRIES = 5  # 7860, 7861, … 7864


def launch_with_port_retry(demo, port, tries=PORT_TRIES, **launch_kwargs):
    """demo.launch()'u `port`'ta dener; port doluysa (OSError) port += 1 ile toplam `tries`
    kez dener ve sunucunun açıldığı portu döndürür. Portu önce soketle yoklayıp sonra
    launch etmek yarış doğurur (port arada kapılabilir); bu yüzden doğrudan launch denenir.
    Hepsi doluysa anlaşılır bir OSError fırlatır."""
    first, last_exc = port, None
    for attempt in range(tries):
        try:
            demo.launch(server_port=port, **launch_kwargs)
            if port != first:
                print(f"SesVer {port} portunda açıldı.", flush=True)
            return port
        except OSError as exc:
            last_exc = exc
            if attempt + 1 < tries:
                print(f"Port {port} kullanımda, {port + 1} portu deneniyor.", flush=True)
                port += 1
    raise OSError(
        f"{first}-{port} arasındaki portların hepsi kullanımda; SesVer başlatılamadı. "
        "Açık kalmış başka bir SesVer penceresini kapatıp yeniden deneyin ya da "
        f"GRADIO_SERVER_PORT ile başka bir port belirtin. (Son hata: {last_exc})"
    )


if __name__ == "__main__":
    _setup_logging()
    _port = int(os.environ.get("GRADIO_SERVER_PORT", "7860"))
    _lang = i18n.saved_language()  # kayıtlı tercih; yoksa sistem dili (desteklenmiyorsa en)
    _page = i18n.page_path(_lang)
    print(f"Arayüz dili: {_lang} ({'ayarlar.json' if i18n.stored_language() else 'sistem dili'}) -> "
          f"http://127.0.0.1:{_port}/{_page}", flush=True)
    # Port doluysa (OSError) 7860..7864 sırayla denenir — yokla-sonra-kullan yarışı yok.
    guncelleme.baslat()  # "Yeni sürüm var" kontrolü arka planda; arayüz beklemez
    launch_with_port_retry(
        build_app(), _port,
        server_name="127.0.0.1",
        share=False, inbrowser=False,
        css=_CSS, theme=_THEME, js=_JS, footer_links=[],
        allowed_paths=[str(vlib.VOICES_DIR / "hazir"), str(vlib.VOICES_DIR / "seslerim")],
    )
