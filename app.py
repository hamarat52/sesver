"""SesVer — yerel VoxCPM2 ses üretimi."""
import os

# Üçüncü taraf modüller yüklenmeden önce telemetriyi kapat.
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import logging
import random
from html import escape
from pathlib import Path
from threading import Event, Lock, Thread
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid4

import gradio as gr
import numpy as np
import soundfile as sf

import audio_prep
import effects as fx
import voice_designer as vdes
import voice_library as vlib

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
MODEL_ID = "openbmb/VoxCPM2"
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
        return text or "(metin boş)"
    return f"({instruction}){text}"


# --- Üretim -------------------------------------------------------------


def get_model():
    """Yalnız üretim kilidi içinden çağrılır; arayüz açılırken model yüklenmez."""
    global _model
    if _model is None:
        from voxcpm import VoxCPM
        _model = VoxCPM.from_pretrained(
            hf_model_id=MODEL_ID, load_denoiser=False, optimize=False,
        )
    return _model


_whisper_model = None
_whisper_lock = Lock()


def _get_whisper():
    """Whisper'ı yalnız "Otomatik yazıya dök" tıklanınca yükler (küçük/int8/CPU)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper_model


def auto_transcribe(reference_audio):
    if not reference_audio:
        raise gr.Error("Önce bir referans ses yükleyin.")
    try:
        with _whisper_lock:
            model = _get_whisper()
            segments, _info = model.transcribe(reference_audio, language="tr")
            text = " ".join(s.text.strip() for s in segments).strip()
    except Exception:
        import traceback
        traceback.print_exc()
        raise gr.Error("Otomatik yazıya dökme başarısız; metni elle yazabilirsiniz.")
    if not text:
        raise gr.Error("Ses anlaşılamadı; metni elle yazın.")
    return text


def transcribe_with_info(path):
    """auto_transcribe ile aynı model/kilit; VAD ile konuşma oranını da döndürür.

    VAD modeli faster-whisper'ın içinde gömülü gelir (yeni indirme yok).
    """
    with _whisper_lock:
        model = _get_whisper()
        segments, info = model.transcribe(path, language="tr", vad_filter=True)
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
    progress(0, desc="İstek kontrol ediliyor…")
    yield None, None, "İstek kontrol ediliyor…"
    text = (text or "").strip()
    prompt_text = (prompt_text or "").strip() or None
    if not text:
        raise gr.Error("Lütfen okunacak bir metin yazın.")
    if len(text) > 500:
        raise gr.Error("İlk sürümde en fazla 500 karakter kullanın; uzun metni bölün.")
    if prompt_text and not reference_audio:
        raise gr.Error("Referans metni yalnız bir referans ses yüklendiğinde kullanılabilir.")
    if reference_audio:
        try:
            info = sf.info(reference_audio)
            if not 1 <= info.duration <= 30:
                raise ValueError("Süre 1–30 saniye olmalı.")
        except (OSError, RuntimeError, ValueError) as exc:
            raise gr.Error("Referans ses okunamadı. 1–30 saniyelik geçerli bir WAV yükleyin.") from exc
    started = perf_counter()
    progress(0.05, desc="İlk kullanımda model indiriliyor/yükleniyor…")
    yield None, None, "İşleniyor… İlk kullanımda model indiriliyor/yükleniyor (internet ve birkaç dakika gerekebilir)."
    try:
        with _model_lock:
            model = get_model()
            # Kaba tahmin: karakter başına ~3-6 sn; uzun metin ve aynı anda
            # çalışan başka ağır uygulamalar süreyi belirgin artırabilir.
            est_min = max(1, round(len(text) * 3 / 60))
            est_max = max(est_min + 1, round(len(text) * 6 / 60))
            progress(0.2, desc="Ses üretiliyor…")
            yield None, None, (
                f"Ses üretiliyor… Metninizin uzunluğuna göre tahmini {est_min}-{est_max} dakika "
                "sürebilir (başka ağır uygulamalar açıksa daha uzun sürer). "
                "**Pencereyi kapatmayın, bu normal** — bittiğinde burada 'Tamamlandı' yazacak."
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

            def _tick():
                est_seconds = max(10.0, (est_min + est_max) / 2 * 60)
                t0 = perf_counter()
                while not stop_ticking.wait(0.4):
                    frac = 0.2 + 0.73 * min(1.0, (perf_counter() - t0) / est_seconds)
                    progress(frac, desc="Ses üretiliyor…")

            ticker = Thread(target=_tick, daemon=True)
            ticker.start()
            try:
                wav = model.generate(**generate_kwargs)
            finally:
                stop_ticking.set()
                ticker.join(timeout=2)
            progress(0.95, desc="Ses dosyası kaydediliyor…")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            output = str(OUTPUT_DIR / f"ai-ile-uretildi-{uuid4().hex}.wav")
            sf.write(output, wav, model.tts_model.sample_rate)
    except Exception:
        import traceback
        traceback.print_exc()  # Ayrıntı yalnız yerel terminalde; metin/ses loglanmaz.
        yield None, None, (
            "Üretim başarısız. İlk indirme için interneti, boş disk alanını ve RAM'i "
            "kontrol edin. Diğer ağır uygulamaları kapatıp kısa metinle tekrar deneyin. "
            "Ayrıntı terminalde; bellek hatasında uygulamayı yeniden başlatın."
        )
        return
    progress(1.0, desc="Tamamlandı")
    yield output, output, f"Tamamlandı: {perf_counter() - started:.1f} saniye. AI ile üretildi."


def _normal_generate(text, emotion_label, progress=gr.Progress(track_tqdm=True)):
    yield from generate_audio(text, None, EMOTIONS.get(emotion_label), progress=progress)


def _clone_generate(text, reference_audio, emotion_label, prompt_text, progress=gr.Progress(track_tqdm=True)):
    yield from generate_audio(text, reference_audio, EMOTIONS.get(emotion_label), prompt_text, progress=progress)


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


def _mode_info(voice_id, emotion_label, text=""):
    """Seçili sese ve duyguya göre kipi ve modele gidecek metni açıklar."""
    instruction = EMOTIONS.get(emotion_label)
    if not voice_id or voice_id == RANDOM_VOICE:
        return f"**Rastgele ses** · Üretilecek: _{_preview_text(text, emotion_label)}_"
    voice = vlib.get_voice(voice_id)
    if not voice:
        return "Seçili ses bulunamadı; kütüphaneden yeniden seçin."
    if instruction:
        return (f"**{escape(voice['ad'])}** · Kontrollü Klon kipi (`{instruction}`). "
                f"⚠️ {SIMILARITY_NOTE} En sadık sonuç için “Nötr” kalsın.")
    return (f"**{escape(voice['ad'])}** · Devam kipi: kayıtlı sesin kendi kaydı ve metniyle sürdürülür; "
            "tarif ya da duygu eklenmez (en yüksek benzerlik).")


def library_generate(text, emotion_label, quality="Dengeli", voice_id=RANDOM_VOICE,
                     progress=gr.Progress(track_tqdm=True)):
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
        raise gr.Error("Seçili ses bulunamadı; kütüphaneden yeniden seçin.")
    if instruction:
        yield from generate_audio(text, voice["ref_wav"], instruction, None, progress=progress,
                                  timesteps=steps, voice_id=voice_id)
    else:
        yield from generate_audio(text, voice["ref_wav"], None, voice["ref_text"], progress=progress,
                                  timesteps=steps, voice_id=voice_id)


def _voice_error(exc):
    return gr.Error(str(exc) or "İşlem yapılamadı.")


def copy_voice_ui(voice_id):
    try:
        voice = vlib.copy_voice(voice_id)
    except (vlib.VoiceError, PermissionError) as exc:
        raise _voice_error(exc)
    return _voice_list(), voice["id"], f"Kopyalandı: **{escape(voice['ad'])}** artık Seslerim'de."


def delete_voice_ui(voice_id, selected):
    try:
        vlib.delete_voice(voice_id)
    except vlib.VoiceError as exc:
        raise _voice_error(exc)
    new_selected = RANDOM_VOICE if selected == voice_id else selected
    return _voice_list(), new_selected, "Ses silindi.", None, gr.update(visible=False)


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
        return None, None, "Önce bir ses üretin; efektler üretilen sese uygulanır."
    if not settings:
        return None, None, "Efekt kapalı; ham ses olduğu gibi kullanılıyor."
    audio, sr = sf.read(str(raw_path), dtype="float32", always_2d=True)
    out = fx.apply(audio.mean(axis=1), sr, settings)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(raw_path).stem.split("-fx-")[0]
    for old in OUTPUT_DIR.glob(f"{stem}-fx-*.wav"):
        old.unlink(missing_ok=True)
    path = OUTPUT_DIR / f"{stem}-fx-{uuid4().hex[:6]}.wav"
    sf.write(str(path), out, sr, subtype="PCM_16")
    names = ", ".join(f"{fx.EFFECTS[e['ad']]} %{e['yogunluk']}" for e in settings)
    return str(path), str(path), (
        f"Efekt uygulandı: {names}. Seviye {fx.loudness_lufs(out, sr):.1f} LUFS, "
        f"tepe {fx.true_peak_dbtp(out):.1f} dBTP. Ham ses ayrıca korunuyor."
    )


def save_fx_preset_ui(voice_id, *vals):
    if not voice_id or voice_id == RANDOM_VOICE:
        raise gr.Error("Ön ayar yalnız kayıtlı bir sese kaydedilebilir.")
    try:
        voice = vlib.update_effects(voice_id, _fx_settings(*vals))
    except vlib.VoiceError as exc:
        raise _voice_error(exc)
    return f"Efekt ön ayarı **{escape(voice['ad'])}** sesine kaydedildi."


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
    if (doku or []) and len(doku) > 2:
        uyarilar.insert(0, "Ses dokusu için en fazla 2 seçim kullanılır; ilk ikisi alındı.")
    warn = "  \n".join(f"⚠️ {escape(u)}" for u in uyarilar)
    head = ('<p class="sv-fine"><b>Elle düzenlendi:</b> seçimler tarifin üzerine yazmıyor.</p>' if manual else "")
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
    return f"Örnek ses ≈ **{sec:.0f} sn** (tahmini; okunacak metnin uzunluğundan hesaplanır)."


def design_candidates(tarif, text, quality, batch, cands, cins, yas, kullanim, perde, ton, doku, hiz, enerji,
                      progress=gr.Progress(track_tqdm=True)):
    """4 aday: aynı tarif + aynı cümle, farklı seed. Her aday hazır olunca kartına düşer."""
    tarif = (tarif or "").strip().strip("()").strip()
    text = (text or "").strip()
    if not tarif:
        raise gr.Error("Önce seçim yapın ya da Gelişmiş alanına bir tarif yazın.")
    if not text:
        raise gr.Error("Örnek cümle boş olamaz.")
    seeds = vdes.candidate_seeds(batch)
    cands = dict(cands or {})
    meta = {"tarif": tarif, "text": text,
            "secimler": design_selections(cins, yas, kullanim, perde, ton, doku, hiz, enerji)}
    audios: list = [None] * 4
    labels = [f"Aday {i + 1} · seed {s} — sırada" for i, s in enumerate(seeds)]

    def pack(status):
        return (*audios, *labels, status, cands, meta, gr.update(visible=False), None)

    yield pack(f"4 aday sırayla üretilecek (seed {', '.join(map(str, seeds))}). İlk aday hazır olunca dinleyebilirsiniz.")
    for i, seed in enumerate(seeds):
        labels[i] = f"Aday {i + 1} · seed {seed} — üretiliyor…"
        last = None
        for last in generate_audio(text, None, tarif, progress=progress, seed=seed,
                                   timesteps=QUALITY.get(quality, 10), voice_id=f"aday-{seed}", log_mode="tasarim"):
            yield pack(f"Aday {i + 1}/4 · {last[2]}")
        if not last or not last[0]:
            labels[i] = f"Aday {i + 1} · seed {seed} — başarısız"
            yield pack(last[2] if last else "Üretim başarısız.")
            return
        audios[i] = last[0]
        cands[str(seed)] = last[0]
        labels[i] = f"Aday {i + 1} · seed {seed}"
        yield pack(f"Aday {i + 1}/4 hazır." + (" Sıradaki üretiliyor…" if i < 3 else " Birini seçip kaydedin."))


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


def pick_candidate_ui(index, batch, cands, meta=None):
    seed = vdes.candidate_seeds(batch)[index]
    if str(seed) not in (cands or {}):
        raise gr.Error("Bu aday henüz üretilmedi.")
    msg = f"Seçilen: **Aday {index + 1}** (seed {seed}). Ad verip kaydedin."
    warns = candidate_warnings(cands[str(seed)], meta)
    if warns:
        msg += "\n\n" + "  \n".join(f"⚠️ {escape(w)}" for w in warns)
    return seed, gr.update(visible=True), msg


def save_designed_ui(name, aciklama, kategori, picked, cands, meta):
    if picked is None:
        raise gr.Error("Önce bir aday seçin.")
    path = (cands or {}).get(str(picked))
    if not path or not Path(path).is_file() or not meta:
        raise gr.Error("Seçilen aday bulunamadı; adayları yeniden üretin.")
    try:
        voice = vlib.save_voice(
            ad=name, ref_wav=path, ref_text=meta["text"], kaynak=DESIGN_KAYNAK, aciklama=aciklama,
            kategori=(kategori or "").strip() or "Genel", tarif=meta["tarif"], seed=int(picked),
            secimler=meta.get("secimler"),
        )
    except (vlib.VoiceError, PermissionError) as exc:
        raise _voice_error(exc)
    return _voice_list(), voice["id"], gr.Tabs(selected="lib"), f"Kaydedildi: **{escape(voice['ad'])}**."


# --- Ses oluştur: dosya yükle -------------------------------------------------
def upload_analyze_ui(path):
    """Çöz → mono → sessizliği kırp → kontroller. Hazırlanan dosya outputs/ altına yazılır."""
    if not path:
        return (None, None, None, "", gr.update(visible=False), gr.update(), gr.update(), "")
    try:
        info = audio_prep.analyze(path)
    except audio_prep.PrepError as exc:
        raise gr.Error(str(exc))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    full = str(audio_prep.write_wav(info["audio"], info["sr"], OUTPUT_DIR / f"yukleme-{uuid4().hex}-tam.wav"))
    dur = info["duration"]
    long_ = dur > audio_prep.MAX_SECONDS
    if long_:
        prepared = str(audio_prep.write_wav(audio_prep.cut(info["audio"], info["sr"], 0, audio_prep.MAX_SECONDS),
                                            info["sr"], OUTPUT_DIR / f"yukleme-{uuid4().hex}.wav"))
    else:
        prepared = full
    lines = [f"Süre (sessizlik kırpıldı): **{dur:.1f} sn** · mono, 16-bit WAV'a çevrildi."]
    lines += [f"⚠️ {escape(w)}" for w in info["warnings"]]
    lines.append(audio_prep.CLEAN_NOTE)
    end = min(dur, audio_prep.MAX_SECONDS)
    return (full, prepared, prepared, "  \n".join(lines), gr.update(visible=long_),
            gr.update(maximum=round(dur, 1), value=0), gr.update(maximum=round(dur, 1), value=round(end, 1)), "")


def upload_cut_ui(full, start, end):
    if not full:
        raise gr.Error("Önce bir ses dosyası yükleyin.")
    audio, sr = sf.read(full, dtype="float32")
    try:
        clip = audio_prep.cut(audio, sr, start, end)
    except audio_prep.PrepError as exc:
        raise gr.Error(str(exc))
    out = str(audio_prep.write_wav(clip, sr, OUTPUT_DIR / f"yukleme-{uuid4().hex}.wav"))
    return out, out, f"Seçilen aralık: {float(start):.1f}–{float(end):.1f} sn ({float(end) - float(start):.1f} sn)."


def upload_transcribe_ui(prepared):
    if not prepared:
        raise gr.Error("Önce bir ses dosyası yükleyin.")
    try:
        text, ratio = transcribe_with_info(prepared)
    except Exception:
        import traceback
        traceback.print_exc()
        raise gr.Error("Otomatik yazıya dökme başarısız; metni elle yazabilirsiniz.")
    note = f"Konuşma oranı ≈ %{ratio * 100:.0f}."
    if ratio < 0.6:
        note += " ⚠️ Kaydın büyük kısmında konuşma algılanmadı; müzik veya sessizlik olabilir."
    if not text:
        note += " Ses anlaşılamadı; metni elle yazın."
    return text, note + " Metni kayıtla birebir aynı olacak şekilde düzeltin."


def save_uploaded_ui(prepared, text, name, aciklama, kategori, consent):
    if not consent:
        raise gr.Error("Kaydetmek için izin kutucuğunu işaretleyin.")
    if not prepared or not Path(prepared).is_file():
        raise gr.Error("Önce bir ses dosyası yükleyin.")
    if not (text or "").strip():
        raise gr.Error("Kaydın metni boş olamaz; devam kipi bu metinle çalışır.")
    dur = sf.info(prepared).duration
    if not audio_prep.MIN_SECONDS - 0.05 <= dur <= audio_prep.MAX_SECONDS + 0.05:
        raise gr.Error(f"Kayıt {dur:.1f} sn; 8–20 sn arası olmalı.")
    try:
        voice = vlib.save_voice(ad=name, ref_wav=prepared, ref_text=text, kaynak="yüklendi",
                                aciklama=aciklama, kategori=(kategori or "").strip() or "Genel")
    except (vlib.VoiceError, PermissionError) as exc:
        raise _voice_error(exc)
    return _voice_list(), voice["id"], gr.Tabs(selected="lib"), f"Kaydedildi: **{escape(voice['ad'])}**."




# --- Görünüm --------------------------------------------------------------
# Referanslar: "Voice Aura" (noktalı/halftone doku, yüzen beyaz kartlar, küçük
# rozetler, ince tipografi) ve Dribbble "Futuristic AI Voice Generator"
# (krem zemin, kalın başlık + tek mercan vurgu, girişi saran gradient çerçeve,
# siyah hap buton). Yazı tipleri sistemden gelir: arayüz dış sunucudan
# font/görsel çekmez, her şey yerelde kalır.

_SAMPLE_TEXT = "Merhaba! Bu ses, bilgisayarımda çalışan açık kaynak bir yapay zekâ ile üretildi."


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


def _html(value, **kwargs):
    return gr.HTML(value, apply_default_css=False, **kwargs)


def _head(icon, title, text, step=None):
    badge = f'<span class="sv-step">{step}</span>' if step else f'<span class="sv-head-ic">{_svg(icon)}</span>'
    return _html(
        f'<div class="sv-head">{badge}<div><h3>{title}</h3><p>{text}</p></div></div>'
    )


# --- Şemsiye marka imzası (HamaratLabs) -------------------------------
# İmza yalnız burada tanımlıdır; üst bilgi (_HERO) ve alt bilgi (_FOOTER) buradan okur.
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
BRAND_FOOTER_TEXT = f"{BRAND_NAME} tarafından geliştirildi"

_HERO = f"""
<div class="sv-hero">
  <div class="sv-aura" aria-hidden="true"><i></i><i></i><i></i></div>
  <nav class="sv-nav">
    <div class="sv-brand"><span class="sv-logo">{_svg(_IC_WAVE)}</span>
      <span class="sv-brand-text"><span>SesVer</span>{BRAND_SIGNATURE_HTML}</span></div>
    <div class="sv-nav-tags">
      <span class="sv-tag"><span class="sv-live"></span>Bilgisayarınızda çalışır</span>
      <span class="sv-tag sv-hide-sm">Açık kaynak · Ücretsiz</span>
    </div>
  </nav>
  <div class="sv-hero-body">
    <div class="sv-badges">
      <span class="sv-badge"><b>TR</b>Türkçe</span>
      <span class="sv-badge">{_svg(_IC_LOCK)}Hesap gerekmez</span>
      <span class="sv-badge">{_svg(_IC_MIC)}Ses klonlama</span>
    </div>
    <h1>Yazdığınız metne<br><span class="sv-accent">ses verin.</span></h1>
    <p>Türkçe metni doğal bir sese çevirin ya da kısa bir kayıtla bir sesi klonlayın.
    Kurulum bir kez yapılır, gerisi tek tık.</p>
  </div>
</div>
"""

_INFO = f"""
<div class="sv-info">
  <div class="sv-tile"><span class="sv-tile-ic">{_svg(_IC_CPU)}</span>
    <div><b>16 GB+ RAM önerilir</b><span>Daha az bellekte yavaşlayabilir veya durabilir.</span></div></div>
  <div class="sv-tile"><span class="sv-tile-ic">{_svg(_IC_CLOUD)}</span>
    <div><b>İlk üretimde ~5 GB indirilir</b><span>Bir kez internet gerekir; sonra model bilgisayarınızda kalır.</span></div></div>
  <div class="sv-tile"><span class="sv-tile-ic">{_svg(_IC_CLOCK)}</span>
    <div><b>Biraz sabır</b><span>Gerçek zamanlı değildir: 10 saniyelik ses, donanıma göre 1-2 dakika sürebilir.</span></div></div>
</div>
"""

_FOOTER = f"""
<footer class="sv-foot">
  <span class="sv-brand sv-brand-sm"><span class="sv-logo">{_svg(_IC_WAVE)}</span>SesVer</span>
  <span>VoxCPM2 ile yerel ses üretimi</span><i></i>
  <span>Paylaşırken “AI ile üretildi” yazın</span><i></i>
  <span class="sv-foot-sig">{BRAND_FOOTER_TEXT}</span>
</footer>
"""

_ETHICS = f"""
<div class="sv-ethics">
  <div class="sv-head"><span class="sv-head-ic">{_svg(_IC_SHIELD)}</span>
    <div><h3>Sorumlu kullanım</h3><p>Klonlama güçlü bir araçtır; lütfen dikkatli kullanın.</p></div></div>
  <ul>
    <li>Yalnız <b>kendi sesinizi</b> veya açık izin aldığınız sesleri kullanın.</li>
    <li>Paylaşırken <b>“AI ile üretildi”</b> etiketi ekleyin; otomatik filigran yoktur.</li>
    <li>Birini taklit ederek yanıltmak ve dolandırıcılık için kullanmayın.</li>
  </ul>
</div>
"""

_RESULT_HEAD = (_IC_PLAY, "Sonuç", "Ses hazır olunca burada dinleyip indirebilirsiniz.")
_RESULT_NOTE = ('<p class="sv-note">Üretim birkaç dakika sürebilir. '
                'Bu sırada pencereyi açık tutun; sayfa donmuş gibi görünse de çalışıyordur.</p>')

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

/* --- Üst bilgi ------------------------------------------------------- */
.sv-hero { position: relative; padding: 18px 0 34px; text-align: center; }
.sv-aura { position: absolute; left: 50%; top: 40px; width: min(980px, 100%); height: 330px;
  transform: translateX(-50%); pointer-events: none; z-index: -1; }
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
/* Açılış: nokta katmanları merkezden dışa doğru sırayla büyüyüp belirir (~1,9 sn),
   sonra durur. Yalnız transform + opacity (GPU dostu); döngü yok. Bitiş anahtar
   karesi yazılmadı ve fill-mode "backwards": animasyon bitince katman doğrudan
   yukarıdaki sabit stile döner (son görünüm birebir aynı, getAnimations() boşalır).
   Statik HTML bir kez bağlandığı için yalnız ilk açılışta oynar. */
@keyframes sv-aura-in { from { opacity: 0; transform: scale(var(--s0)); } }
.sv-aura i { transform-origin: 50% 58%;
  animation: sv-aura-in var(--d) var(--sv-ease) var(--dl) 1 backwards; }
.sv-aura i:nth-child(3) { --s0: .45; --d: 1.3s; --dl: 0s; }
.sv-aura i:nth-child(2) { --s0: .6;  --d: 1.5s; --dl: .12s; }
.sv-aura i:nth-child(1) { --s0: .75; --d: 1.7s; --dl: .24s; }
@media (prefers-reduced-motion: reduce) { .sv-aura i { animation: none !important; } }

.sv-nav { display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 6px 0 0; margin-bottom: 46px; }
.sv-brand { display: inline-flex; align-items: center; gap: 10px; font-weight: 700;
  font-size: 1.05rem; letter-spacing: 0.02em; color: var(--sv-ink); text-transform: uppercase; }
.sv-logo { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 11px;
  background: var(--sv-paper); border: 1px solid var(--sv-line); box-shadow: var(--sv-shadow-sm); }
.sv-logo .sv-ic { width: 17px; height: 17px; stroke-width: 2.2; }
/* Ürün adı + altında küçük "by HamaratLabs" imzası (ürün markasını bastırmaz). */
.sv-brand-text { display: inline-flex; flex-direction: column; align-items: flex-start; gap: 1px;
  line-height: 1.1; }
.sv-sig { font-size: .68rem; font-weight: 500; letter-spacing: .01em; text-transform: none;
  color: var(--sv-muted); white-space: nowrap; }
.sv-sig-mark { font-weight: 650; color: var(--sv-ink-2); }
.sv-foot-sig { color: var(--sv-ink-2); }
.sv-nav-tags { display: flex; gap: 8px; }
.sv-tag { display: inline-flex; align-items: center; gap: 8px; padding: 7px 13px; border-radius: 999px;
  font-size: .8rem; font-weight: 500; color: var(--sv-ink-2); background: rgba(255,255,255,.75);
  border: 1px solid var(--sv-line); box-shadow: var(--sv-shadow-sm); backdrop-filter: blur(6px); }
.sv-live { width: 7px; height: 7px; border-radius: 50%; background: #2DBE6C;
  box-shadow: 0 0 0 3px rgba(45, 190, 108, .18); }

.sv-hero-body { max-width: 720px; margin: 0 auto; }
.sv-badges { display: inline-flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-bottom: 22px; }
.sv-badge { display: inline-flex; align-items: center; gap: 7px; padding: 6px 12px 6px 8px;
  border-radius: 999px; background: var(--sv-paper); border: 1px solid var(--sv-line);
  box-shadow: var(--sv-shadow-sm); font-size: .8rem; font-weight: 500; color: var(--sv-ink-2); }
.sv-badge .sv-ic { width: 15px; height: 15px; color: var(--sv-coral); }
.sv-badge b { font-size: .64rem; font-weight: 700; letter-spacing: .04em; color: #fff;
  background: #E30A17; border-radius: 4px; padding: 2px 4px; line-height: 1; }
.sv-hero h1 { margin: 0; font-size: clamp(2.5rem, 5.4vw, 4.1rem); line-height: 1.02;
  font-weight: 700; letter-spacing: -0.032em; word-spacing: 0.04em; color: var(--sv-ink); }
.sv-accent { background: linear-gradient(92deg, #FF7A4D 0%, #F2476A 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent; padding-right: .04em; }
.sv-hero-body p { margin: 20px auto 0; max-width: 540px; font-size: 1.08rem; line-height: 1.6;
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
.sv-emotion label[data-testid="Sakin-radio-label"] { --dot: #4FA3E8; }
.sv-emotion label[data-testid="Enerjik-radio-label"] { --dot: #FF8A3D; }
.sv-emotion label[data-testid="Neşeli-radio-label"] { --dot: #F5C23A; }
.sv-emotion label[data-testid="Ciddi-radio-label"] { --dot: #6E7781; }
.sv-emotion label[data-testid="Heyecanlı-radio-label"] { --dot: #F2476A; }
.sv-emotion label[data-testid="Üzgün-radio-label"] { --dot: #7C6CF0; }

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
.sv-transcribe-row { align-items: flex-end !important; }

/* --- Sonuç kartı --------------------------------------------------- */
.sv-status { padding: 13px 15px 13px 40px !important; border-radius: 14px !important; position: relative;
  background: var(--sv-soft) !important; border: 1px solid var(--sv-line) !important; }
.sv-status::before { content: ""; position: absolute; left: 17px; top: 19px; width: 8px; height: 8px;
  border-radius: 50%; background: var(--sv-coral); box-shadow: 0 0 0 4px rgba(242,92,59,.16); }
.sv-status p { margin: 0 !important; font-size: .9rem !important; line-height: 1.5 !important; color: var(--sv-ink-2) !important; }
.sv-status strong { color: var(--sv-ink); }

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
.sv-cgrid { flex-wrap: wrap !important; gap: 10px !important; }
.sv-cand { flex: 1 1 calc(50% - 10px) !important; min-width: 170px !important; gap: 8px !important; padding: 10px !important;
  border-radius: 16px !important; background: var(--sv-soft) !important; border: 1px solid var(--sv-line) !important; }
.sv-cand-label p { margin: 0 !important; font-size: .8rem !important; font-weight: 600; color: var(--sv-ink-2) !important; }
.sv-card .block.sv-cand-audio { min-height: 90px; padding: 6px !important; background: #fff !important; }
.sv-cand .sv-btn.sv-mini { width: 100% !important; flex: 1 1 auto !important; }
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
  .sv-nav { margin-bottom: 30px; }
  .sv-hide-sm { display: none !important; }
  .sv-hero { padding-bottom: 26px; }
  .sv-panel { padding: 20px 18px 18px !important; }
  .sv-card { padding: 20px !important; }
  .sv-actionbar { flex-wrap: wrap !important; }
  .sv-actionbar > * { flex: 1 1 100% !important; }
  .sv-actionbar .sv-btn-primary { width: 100%; }
  .sv-transcribe-row { flex-wrap: wrap !important; }
  .sv-info { grid-template-columns: 1fr; }
  #sv-tabs [role="tab"] { padding: 9px 13px 9px 11px !important; font-size: .86rem !important; gap: 6px; }
  #sv-tabs [role="tab"]::before { width: 15px; height: 15px; }
  .sv-cand { flex: 1 1 100% !important; }
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
# Ayrıca VoxCPM/huggingface_hub'un dahili tqdm çıktısı bazen Gradio'nun genel
# ilerleme katmanına "Downloading bytes… / 0/N steps" gibi ham, teknik metin
# olarak sızabiliyor; bunu kendi temiz Türkçe durum metnimizle çakışmadan,
# hangi sınıfı kullanırsa kullansın sürekli tarayıp gizliyoruz.
_JS = """() => {
    document.querySelectorAll('.dark').forEach((el) => el.classList.remove('dark'));
    const raw = /Downloading bytes|Reconstructing|\\/\\s*\\d+\\s*steps/;
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
}"""


def _frame_bar(chips):
    inner = "".join(f'<span class="sv-chip">{c}</span>' for c in chips)
    return _html(f'<div class="sv-frame-bar"><div class="sv-chips">{inner}</div>'
                 f'<span class="sv-chip sv-chip-dark">{_svg(_IC_LOCK)}Yerel</span></div>')


def _card_html(voice):
    return (f'<div class="sv-vmeta"><span class="sv-cat">{escape(voice["kategori"] or "Genel")}</span>'
            f'<h4>{escape(voice["ad"])}</h4><p>{escape(voice["aciklama"] or "")}</p></div>')


def _library_tab(demo):
    """Ses Kütüphanesi: kartlar (Hazır sesler | Seslerim), üretim ve efektler."""
    with gr.Row(equal_height=False, elem_classes=["sv-grid"]):
        with gr.Column(scale=7, min_width=340, elem_classes=["sv-frame"]):
            _frame_bar([f"{_svg(_IC_LIB)}Ses kütüphanesi", "Türkçe"])
            with gr.Column(elem_classes=["sv-panel"]):
                voices = gr.State(_voice_list())
                selected = gr.State(RANDOM_VOICE)
                pending = gr.State(None)
                _head(None, "Bir ses seçin",
                      "Kayıtlı bir sesle her üretimde aynı kişi konuşur. ▶ ile 3 saniyelik örneği dinleyin.", step="1")
                cards_slot = gr.Column(elem_classes=["sv-cards"])
                lib_msg = gr.Markdown("", elem_classes=["sv-fine-md"])
                with gr.Row(visible=False, elem_classes=["sv-confirm"]) as confirm_row:
                    confirm_md = gr.Markdown()
                    confirm_yes = gr.Button("Evet, sil", size="sm", scale=0,
                                            elem_classes=["sv-btn", "sv-mini", "sv-mini-danger"])
                    confirm_no = gr.Button("Vazgeç", size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
                sample = gr.Audio(label="Örnek dinleme (3 sn)", type="filepath", interactive=False, autoplay=True,
                                  elem_classes=["sv-audio", "sv-sample"])
                _html('<div class="sv-divider"></div>')
                _head(None, "Metninizi yazın",
                      "Kayıtlı seste duygu seçmeyin: ses “Devam” kipinde en yüksek benzerlikle sürer.", step="2")
                text = gr.Textbox(label="Metin", lines=5, max_length=500, value=_SAMPLE_TEXT,
                                  placeholder="Seslendirilecek metni buraya yazın…")
                quality = gr.Radio(choices=list(QUALITY), value="Dengeli", label="Kalite",
                                   elem_classes=["sv-emotion", "sv-plain"])
                emotion = gr.Radio(choices=list(EMOTIONS.keys()), value="Nötr", label="Duygu / ton (isteğe bağlı)",
                                   elem_classes=["sv-emotion"])
                mode_md = gr.Markdown(elem_id="preview-box")
                with gr.Row(elem_classes=["sv-actionbar"]):
                    _html('<div class="sv-hint"><b>En fazla 500 karakter.</b><br>'
                          'Hızlı daha çabuk, En İyi daha temiz sonuç verir.</div>')
                    button = gr.Button("Üret", variant="primary", scale=0, min_width=170,
                                       elem_classes=["sv-btn", "sv-btn-primary"])
        with gr.Column(scale=5, min_width=300, elem_classes=["sv-side"]):
            with gr.Column(elem_classes=["sv-card"]):
                _head(*_RESULT_HEAD)
                status = gr.Markdown("Hazır. Bir ses seçip metninizi yazın ve Üret'e basın.",
                                     elem_classes=["sv-status"])
                audio = gr.Audio(label="Üretilen ses — AI ile üretildi", type="filepath", interactive=False,
                                 elem_classes=["sv-audio"])
                download = gr.DownloadButton("⬇ WAV indir", variant="secondary",
                                             elem_classes=["sv-btn", "sv-btn-ghost"])
                _html(_RESULT_NOTE)
            with gr.Column(elem_classes=["sv-card", "sv-fx"]):
                _head(_IC_FX, "Efektler",
                      "Üretimden sonra uygulanır; ham ses değişmez. Ayar değiştikçe önizleme yenilenir.")
                with gr.Accordion("Efekt ayarları", open=False, elem_classes=["sv-acc"]):
                    fx_controls = []
                    room = None
                    for key, label in fx.EFFECTS.items():
                        with gr.Row(elem_classes=["sv-fx-row"]):
                            on = gr.Checkbox(label=label, value=False, scale=2, min_width=150)
                            level = gr.Slider(0, 100, value=50, step=5, label="Yoğunluk", scale=3, min_width=160)
                        fx_controls += [on, level]
                        if key == "oda":
                            room = gr.Radio(choices=[(v[0], k) for k, v in fx.ROOM_PRESETS.items()], value="salon",
                                            label="Oda ön ayarı", elem_classes=["sv-emotion", "sv-plain"])
                    fx_controls.append(room)
                    fx_preset = gr.Button("Bu sese ön ayar olarak kaydet", size="sm",
                                          elem_classes=["sv-btn", "sv-mini"])
                fx_status = gr.Markdown("Efekt kapalı; ham ses olduğu gibi kullanılıyor.", elem_classes=["sv-status"])
                fx_audio = gr.Audio(label="Efektli ses — AI ile üretildi", type="filepath", interactive=False,
                                    elem_classes=["sv-audio"])
                fx_download = gr.DownloadButton("⬇ Efektli WAV indir", variant="secondary",
                                                elem_classes=["sv-btn", "sv-btn-ghost"])

    select_outputs = [selected, mode_md, *fx_controls]

    with cards_slot:
        @gr.render(inputs=[voices, selected])
        def _cards(items, current):
            hazir = [_RANDOM_CARD] + [v for v in items if v["hazir"]]
            mine = [v for v in items if not v["hazir"]]
            for title, group in (("Hazır sesler", hazir), ("Seslerim", mine)):
                _html(f'<div class="sv-group-title">{title}<span>{len(group)}</span></div>')
                if not group:
                    _html('<p class="sv-empty">Henüz kayıtlı sesiniz yok. “Ses Oluştur” sekmesinden seçimlerle '
                          'tarif edin ya da kendi kaydınızı yükleyin.</p>')
                    continue
                with gr.Row(elem_classes=["sv-vgrid"]):
                    for v in group:
                        is_sel = v["id"] == current
                        with gr.Column(min_width=180, elem_classes=["sv-vcard"] + (["is-selected"] if is_sel else [])):
                            _html(_card_html(v))
                            with gr.Row(elem_classes=["sv-vcard-actions"]):
                                pick = gr.Button("✓ Seçili" if is_sel else "Seç", size="sm", scale=0,
                                                 elem_classes=["sv-btn", "sv-mini"] + (["sv-mini-dark"] if is_sel else []))
                                pick.click(select_voice_ui, inputs=[gr.State(v["id"]), emotion, text],
                                           outputs=select_outputs, show_progress="hidden")
                                if v["ornek"]:
                                    play = gr.Button("▶ Örnek", size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
                                    play.click(lambda p=v["ornek"]: p, outputs=[sample], queue=False)
                                if v["id"] != RANDOM_VOICE:
                                    copy = gr.Button("Kopyala", size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
                                    copy.click(copy_voice_ui, inputs=[gr.State(v["id"])],
                                               outputs=[voices, selected, lib_msg]).then(
                                        select_voice_ui, inputs=[selected, emotion, text], outputs=select_outputs)
                                if not v["hazir"]:
                                    remove = gr.Button("Sil", size="sm", scale=0,
                                                       elem_classes=["sv-btn", "sv-mini", "sv-mini-danger"])
                                    remove.click(
                                        lambda vid=v["id"], ad=v["ad"]: (
                                            vid, gr.update(visible=True),
                                            f"**{escape(ad)}** silinsin mi? Bu işlem geri alınamaz."),
                                        outputs=[pending, confirm_row, confirm_md], queue=False)

    confirm_yes.click(delete_voice_ui, inputs=[pending, selected],
                      outputs=[voices, selected, lib_msg, pending, confirm_row]).then(
        select_voice_ui, inputs=[selected, emotion, text], outputs=select_outputs)
    confirm_no.click(lambda: (None, gr.update(visible=False)), outputs=[pending, confirm_row], queue=False)

    for trigger in (text.change, emotion.change):
        trigger(_mode_info, inputs=[selected, emotion, text], outputs=mode_md, queue=False)
    demo.load(_mode_info, inputs=[selected, emotion, text], outputs=mode_md)

    generation = button.click(
        library_generate, inputs=[text, emotion, quality, selected], outputs=[audio, download, status],
        concurrency_limit=1, api_name="generate_audio", show_progress="full",
    )
    fx_inputs = [audio, *fx_controls]
    fx_outputs = [fx_audio, fx_download, fx_status]
    generation.then(apply_effects_ui, inputs=fx_inputs, outputs=fx_outputs)
    for control in fx_controls:
        event = control.release if isinstance(control, gr.Slider) else control.change
        event(apply_effects_ui, inputs=fx_inputs, outputs=fx_outputs, show_progress="hidden")
    fx_preset.click(save_fx_preset_ui, inputs=[selected, *fx_controls], outputs=fx_status)
    return SimpleNamespace(voices=voices, selected=selected, emotion=emotion, text=text,
                           select_outputs=select_outputs)


def _design_subtab(lib, tabs):
    """Ses Oluştur → Seçimlerle tarif et (kurallı birleştirici, 4 aday)."""
    groups = _DMAP["gruplar"]

    def choice(group, **kw):
        return gr.Radio(choices=vdes.group_choices(_DMAP, group), value=_DMAP.get("bos_secenek"),
                        label=groups[group]["etiket"], elem_classes=["sv-emotion", "sv-plain"], **kw)

    def scale(group):
        labels = _slider_labels(group)
        return gr.Slider(1, len(labels), value=_slider_default(group), step=1, label=groups[group]["etiket"],
                         info=" · ".join(f"{i + 1} {lab}" for i, lab in enumerate(labels)), min_width=220)

    with gr.Row(equal_height=False, elem_classes=["sv-grid"]):
        with gr.Column(scale=7, min_width=340, elem_classes=["sv-frame"]):
            _frame_bar([f"{_svg(_IC_SPARK)}Ses tasarımı", "Seçimlerle, LLM'siz"])
            with gr.Column(elem_classes=["sv-panel"]):
                _head(None, "Şablonla başlayın", "İsteğe bağlı: bir şablon seçimleri doldurur, sonra değiştirebilirsiniz.",
                      step="1")
                with gr.Row(elem_classes=["sv-templates"]):
                    template_buttons = [(name, gr.Button(name, size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"]))
                                        for name in _DMAP["sablonlar"]]
                _html('<div class="sv-divider"></div>')
                _head(None, "Sesi tarif edin", "Her seçim İngilizce bir parçaya dönüşür; tarif otomatik kurulur.",
                      step="2")
                cins = choice("cinsiyet")
                yas = choice("yas")
                kullanim = choice("kullanim")
                ton = choice("ton")
                doku = gr.CheckboxGroup(choices=list(groups["doku"]["secenekler"]), value=[],
                                        label=groups["doku"]["etiket"], elem_classes=["sv-emotion", "sv-plain"])
                with gr.Row(elem_classes=["sv-sliders"]):
                    perde = scale("perde")
                    hiz = scale("hiz")
                    enerji = scale("enerji")
                warn_md = gr.Markdown("", elem_classes=["sv-warn"])
                manual = gr.State(False)
                with gr.Accordion("Gelişmiş: oluşan İngilizce tarif", open=False, elem_classes=["sv-acc"]):
                    parts = _html("")
                    tarif = gr.Textbox(label="Tarif (İngilizce, elle düzenlenebilir)", lines=2, value="a voice")
                    rebuild = gr.Button("Seçimlerden yeniden kur", size="sm", elem_classes=["sv-btn", "sv-mini"])
                _html('<div class="sv-divider"></div>')
                _head(None, "Örnek cümle",
                      "Adaylar bu cümleyi okur. Süreyi kaydırıcıyla seçin; metni dilediğiniz gibi değiştirin.",
                      step="3")
                with gr.Row(elem_classes=["sv-sliders"]):
                    category = gr.Radio(choices=_SAMPLE_CATEGORIES, value="masal", label="Örnek metin türü",
                                        elem_classes=["sv-emotion", "sv-plain"], min_width=220)
                    seconds = gr.Slider(_MIN_SAMPLE_SECONDS, _MAX_SAMPLE_SECONDS, value=_DEFAULT_SAMPLE_SECONDS, step=1,
                                        label="Örnek ses süresi (sn)", min_width=220)
                first_text = vdes.sample_text("masal", _DEFAULT_SAMPLE_SECONDS, _DMAP)
                sample = gr.Textbox(label="Örnek cümle", lines=3, max_length=500, value=first_text)
                estimate = gr.Markdown(sample_estimate_md(first_text), elem_classes=["sv-fine-md"])
                quality = gr.Radio(choices=list(QUALITY), value="Dengeli", label="Kalite",
                                   elem_classes=["sv-emotion", "sv-plain"])
                with gr.Row(elem_classes=["sv-actionbar"]):
                    _html('<div class="sv-hint"><b>4 aday sırayla üretilir.</b><br>'
                          'Her biri hazır olunca dinlenebilir; uzun cümle daha uzun sürer.</div>')
                    try_button = gr.Button("Sesleri Dene", variant="primary", scale=0, min_width=190,
                                           elem_classes=["sv-btn", "sv-btn-primary"])
        with gr.Column(scale=5, min_width=300, elem_classes=["sv-side"]):
            with gr.Column(elem_classes=["sv-card"]):
                _head(_IC_PLAY, "Adaylar", "Aynı tarif ve cümle, farklı seed. Dinleyin, birini seçin.")
                d_status = gr.Markdown("Henüz aday yok. Seçimleri yapıp “Sesleri Dene”ye basın.",
                                       elem_classes=["sv-status"])
                cand_audio, cand_label, cand_pick = [], [], []
                with gr.Row(elem_classes=["sv-cgrid"]):
                    for i in range(4):
                        with gr.Column(min_width=180, elem_classes=["sv-cand"]):
                            cand_label.append(gr.Markdown(f"Aday {i + 1} · seed {11 * (i + 1)}",
                                                          elem_classes=["sv-cand-label"]))
                            cand_audio.append(gr.Audio(label=f"Aday {i + 1}", show_label=False, type="filepath",
                                                       interactive=False, elem_classes=["sv-audio", "sv-cand-audio"]))
                            cand_pick.append(gr.Button("Bunu seç", size="sm", elem_classes=["sv-btn", "sv-mini"]))
                with gr.Row(elem_classes=["sv-cand-actions"]):
                    stop = gr.Button("Durdur", size="sm", scale=0, elem_classes=["sv-btn", "sv-mini", "sv-mini-danger"])
                    more = gr.Button("4 aday daha", size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
                    change = gr.Button("Seçimleri değiştir", size="sm", scale=0, elem_classes=["sv-btn", "sv-mini"])
                with gr.Column(visible=False, elem_classes=["sv-save"]) as save_group:
                    picked_md = gr.Markdown("")
                    name = gr.Textbox(label="Ses adı", placeholder="Örn. Gece Anlatıcısı", max_length=60)
                    aciklama = gr.Textbox(label="Kısa açıklama (isteğe bağlı)", max_length=160)
                    kategori = gr.Textbox(label="Kategori", value="Masal", max_length=40)
                    save = gr.Button("Kaydet", variant="primary", elem_classes=["sv-btn", "sv-btn-primary"])
                save_md = gr.Markdown("", elem_classes=["sv-fine-md"])

    batch = gr.State(0)
    cands = gr.State({})
    meta = gr.State(None)
    picked = gr.State(None)
    selections = [cins, yas, kullanim, perde, ton, doku, hiz, enerji]
    rebuild_args = dict(fn=rebuild_description_ui, inputs=[*selections, manual, tarif],
                        outputs=[tarif, parts, warn_md], queue=False)
    for control in selections:
        control.change(**rebuild_args)

    def limit_texture(values):
        if len(values or []) > 2:
            gr.Warning("Ses dokusu için en fazla 2 seçim yapılabilir.")
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

    run_args = dict(fn=design_candidates, inputs=[tarif, sample, quality, batch, cands, *selections],
                    outputs=[*cand_audio, *cand_label, d_status, cands, meta, save_group, picked],
                    concurrency_limit=1, show_progress="full", show_progress_on=[d_status])
    first_run = try_button.click(lambda: 0, outputs=batch, queue=False).then(**run_args)
    more_run = more.click(lambda b: int(b or 0) + 1, inputs=batch, outputs=batch, queue=False).then(**run_args)
    stop.click(lambda: "Durduruldu. Çalışmakta olan aday bitene kadar model meşgul kalabilir.",
               outputs=d_status, cancels=[first_run, more_run], queue=False)
    change.click(lambda: (gr.update(visible=False), None, "Seçimleri soldan değiştirip yeniden “Sesleri Dene”ye basın."),
                 outputs=[save_group, picked, d_status], queue=False)
    for i, pbutton in enumerate(cand_pick):
        pbutton.click(lambda b, c, m, i=i: pick_candidate_ui(i, b, c, m), inputs=[batch, cands, meta],
                      outputs=[picked, save_group, picked_md], queue=False)
    save.click(save_designed_ui, inputs=[name, aciklama, kategori, picked, cands, meta],
               outputs=[lib.voices, lib.selected, tabs, save_md]).then(
        select_voice_ui, inputs=[lib.selected, lib.emotion, lib.text], outputs=lib.select_outputs)
    return rebuild_args


def _upload_subtab(lib, tabs):
    """Ses Oluştur → Dosya yükle (çözme, kırpma, kontroller, Whisper, izin)."""
    with gr.Row(equal_height=False, elem_classes=["sv-grid"]):
        with gr.Column(scale=7, min_width=340, elem_classes=["sv-frame"]):
            _frame_bar([f"{_svg(_IC_MIC)}Kendi kaydınız", "WAV · MP3 · M4A"])
            with gr.Column(elem_classes=["sv-panel"]):
                _head(None, "Kaydı yükleyin",
                      "8–20 saniyelik, tek kişinin konuştuğu temiz bir kayıt. Dosya mono, 16-bit WAV'a çevrilir; "
                      "baştaki ve sondaki sessizlik kırpılır.", step="1")
                u_file = gr.File(label="Ses dosyası (WAV, MP3, M4A)", file_types=[".wav", ".mp3", ".m4a"],
                                 type="filepath", elem_classes=["sv-upload", "sv-file"])
                u_info = gr.Markdown(audio_prep.CLEAN_NOTE, elem_classes=["sv-fine-md"])
                with gr.Row(visible=False, elem_classes=["sv-sliders"]) as u_range:
                    u_start = gr.Slider(0, 20, value=0, step=0.1, label="Başlangıç (sn)", min_width=200)
                    u_end = gr.Slider(0, 20, value=20, step=0.1, label="Bitiş (sn)", min_width=200)
                u_range_md = gr.Markdown("", elem_classes=["sv-fine-md"])
                u_preview = gr.Audio(label="Hazırlanan kayıt (mono, 16-bit)", type="filepath", interactive=False,
                                     elem_classes=["sv-audio"])
                _html('<div class="sv-divider"></div>')
                _head(None, "Kaydın metni",
                      "Yerel Whisper ile çıkarılır; kayıtla birebir aynı olacak şekilde düzeltin. Boş bırakılamaz.",
                      step="2")
                with gr.Row(elem_classes=["sv-transcribe-row"]):
                    u_text = gr.Textbox(label="Kaydın metni (gerekli)", lines=3, scale=4,
                                        placeholder="Kayıtta tam olarak ne söylendiği…")
                    u_transcribe = gr.Button("Otomatik yazıya dök", scale=1, min_width=200,
                                             elem_classes=["sv-btn", "sv-btn-soft"])
                u_transcribe_md = gr.Markdown("", elem_classes=["sv-fine-md"])
                _html('<div class="sv-divider"></div>')
                _head(None, "Kaydedin", "Kaydedilen ses yalnız bu bilgisayarda, Seslerim'de durur.", step="3")
                u_name = gr.Textbox(label="Ses adı", max_length=60)
                u_desc = gr.Textbox(label="Kısa açıklama (isteğe bağlı)", max_length=160)
                u_cat = gr.Textbox(label="Kategori", value="Kişisel", max_length=40)
                u_consent = gr.Checkbox(label="Bu ses bana ait ya da sahibinden açık izin aldım.", value=False,
                                        elem_classes=["sv-consent"])
                with gr.Row(elem_classes=["sv-actionbar"]):
                    _html('<div class="sv-hint"><b>İzin kutucuğu zorunlu.</b><br>'
                          'İşaretlenmeden kaydedilemez.</div>')
                    u_save = gr.Button("Kaydet", variant="primary", interactive=False, scale=0, min_width=170,
                                       elem_classes=["sv-btn", "sv-btn-primary"])
                u_msg = gr.Markdown("", elem_classes=["sv-fine-md"])
        with gr.Column(scale=5, min_width=300, elem_classes=["sv-side"]):
            with gr.Column(elem_classes=["sv-card"]):
                _html(_ETHICS)

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


def build_app():
    with gr.Blocks(title="SesVer — Türkçe yerel ses üretimi", analytics_enabled=False) as demo:
        _html(_HERO)

        with gr.Tabs(elem_id="sv-tabs", selected="lib", overflow_behavior="wrap") as tabs:
            with gr.Tab("Ses Kütüphanesi", id="lib"):
                lib = _library_tab(demo)

            with gr.Tab("Ses Oluştur", id="olustur"):
                with gr.Tabs(elem_id="sv-subtabs", overflow_behavior="wrap"):
                    with gr.Tab("Seçimlerle tarif et", id="tarif"):
                        rebuild_args = _design_subtab(lib, tabs)
                    with gr.Tab("Dosya yükle", id="yukle"):
                        _upload_subtab(lib, tabs)
                demo.load(**rebuild_args)

            with gr.Tab("Ses Klonlama", id="klon"):
                with gr.Row(equal_height=False, elem_classes=["sv-grid"]):
                    with gr.Column(scale=7, min_width=340, elem_classes=["sv-frame"]):
                        _html(
                            f'<div class="sv-frame-bar"><div class="sv-chips">'
                            f'<span class="sv-chip">{_svg(_IC_MIC)}Ses klonlama</span>'
                            f'<span class="sv-chip">3 adım</span></div>'
                            f'<span class="sv-chip sv-chip-dark">{_svg(_IC_LOCK)}Yerel</span></div>'
                        )
                        with gr.Column(elem_classes=["sv-panel"]):
                            _head(None, "Örnek sesi yükleyin",
                                  "Tek kişinin konuştuğu, müziksiz ve temiz <b>3–15 saniyelik WAV</b> en iyi sonucu "
                                  "verir (1–30 saniye kabul edilir).", step="1")
                            c_reference = gr.Audio(
                                label="Referans ses (gerekli)", sources=["upload"], type="filepath",
                                elem_classes=["sv-audio", "sv-upload"],
                            )
                            _html('<div class="sv-divider"></div>')
                            _head(None, "Kayıtta ne söylendiğini yazın",
                                  "İsteğe bağlı ama önerilir: model kaydı anlayarak devam eder ve ses çok daha "
                                  "benzer çıkar. Boş bırakırsanız yalnız ses rengi kopyalanır.", step="2")
                            with gr.Row(elem_classes=["sv-transcribe-row"]):
                                c_prompt_text = gr.Textbox(
                                    label="Referans sesin metni (isteğe bağlı)",
                                    placeholder="Kayıtta tam olarak ne söylendiğini yazın ya da otomatik doldurun.",
                                    lines=2, scale=4,
                                )
                                c_transcribe_btn = gr.Button(
                                    "Otomatik yazıya dök", scale=1, min_width=200,
                                    elem_classes=["sv-btn", "sv-btn-soft"],
                                )
                            _html('<div class="sv-divider"></div>')
                            _head(None, "Yeni metni yazın",
                                  "Klonlanan ses bu metni okuyacak.", step="3")
                            c_text = gr.Textbox(
                                label="Metin", lines=4, max_length=500, value=_SAMPLE_TEXT,
                                placeholder="Klonlanan sesin okuyacağı metni yazın…",
                            )
                            c_emotion = gr.Radio(
                                choices=list(EMOTIONS.keys()), value="Nötr",
                                label="Duygu / ton (isteğe bağlı, varsayılan: nötr)",
                                elem_classes=["sv-emotion"],
                            )
                            _html('<p class="sv-fine"><b>İpucu:</b> Bir duygu seçmek, klonun orijinal sese '
                                  'benzerliğini biraz azaltabilir. En sadık sonuç için “Nötr” kalsın.</p>')
                            with gr.Row(elem_classes=["sv-actionbar"]):
                                _html('<div class="sv-hint"><b>En fazla 500 karakter.</b><br>'
                                      'Referans ses yüklemeden başlamaz.</div>')
                                c_button = gr.Button(
                                    "Klonla ve Üret", variant="primary", scale=0, min_width=190,
                                    elem_classes=["sv-btn", "sv-btn-primary"],
                                )
                    with gr.Column(scale=5, min_width=300, elem_classes=["sv-side"]):
                        with gr.Column(elem_classes=["sv-card"]):
                            _head(*_RESULT_HEAD)
                            c_status = gr.Markdown(
                                "Hazır. Metin ve referans ses yükleyip Klonla ve Üret'e basın.",
                                elem_classes=["sv-status"],
                            )
                            c_audio = gr.Audio(
                                label="Üretilen ses — AI ile üretildi", type="filepath", interactive=False,
                                elem_classes=["sv-audio"],
                            )
                            c_download = gr.DownloadButton(
                                "⬇ WAV indir", variant="secondary", elem_classes=["sv-btn", "sv-btn-ghost"],
                            )
                            _html(_RESULT_NOTE)
                        with gr.Column(elem_classes=["sv-card"]):
                            _html(_ETHICS)
                c_button.click(
                    _clone_generate, inputs=[c_text, c_reference, c_emotion, c_prompt_text],
                    outputs=[c_audio, c_download, c_status],
                    concurrency_limit=1, api_name="clone_audio", show_progress="full",
                )
                c_transcribe_btn.click(
                    auto_transcribe, inputs=[c_reference], outputs=[c_prompt_text],
                    concurrency_limit=1, show_progress="full",
                )

        _html(_INFO)
        _html(_FOOTER)
    return demo.queue(default_concurrency_limit=1, max_size=8)


def _setup_logging():
    """Yalnız SesVer'in tek satırlık istek loglarını terminale yazar."""
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [sesver] %(message)s", "%H:%M:%S"))
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


if __name__ == "__main__":
    _setup_logging()
    build_app().launch(
        server_name="127.0.0.1", server_port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")),
        share=False, inbrowser=False,
        css=_CSS, theme=_THEME, js=_JS, footer_links=[],
        allowed_paths=[str(vlib.VOICES_DIR / "hazir"), str(vlib.VOICES_DIR / "seslerim")],
    )
