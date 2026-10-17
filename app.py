"""SesVer — yerel VoxCPM2 ses üretimi."""
import os

# Üçüncü taraf modüller yüklenmeden önce telemetriyi kapat.
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from pathlib import Path
from threading import Lock
from time import perf_counter
from uuid import uuid4

import gradio as gr
import soundfile as sf

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
MODEL_ID = "openbmb/VoxCPM2"
_model = None
_model_lock = Lock()

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


def generate_audio(text, reference_audio, instruction=None, prompt_text=None):
    """Durumu hemen göster; aynı modelde üretimleri sıraya koy.

    prompt_text verilmişse VoxCPM2'nin "devam kipi" kullanılır: model referans
    sesin gerçek içeriğini bilerek devam eder, yalnız izole klonlamadan (ses
    rengini kopyalama) çok daha sadık bir taklit üretir. prompt_text yoksa
    (varsayılan) eski izole klonlama davranışı değişmeden kalır.
    """
    # Eski çıktı, yeni istek başarısız olsa bile yeni ses sanılmasın.
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
    final_text = f"({instruction}){text}" if instruction else text
    started = perf_counter()
    yield None, None, "İşleniyor… İlk kullanımda model indiriliyor/yükleniyor (internet ve birkaç dakika gerekebilir)."
    try:
        with _model_lock:
            model = get_model()
            # Kaba tahmin: M1'de karakter başına ~3-6 sn; uzun metin ve aynı anda
            # çalışan başka ağır uygulamalar süreyi belirgin artırabilir.
            est_min = max(1, round(len(text) * 3 / 60))
            est_max = max(est_min + 1, round(len(text) * 6 / 60))
            yield None, None, (
                f"Ses üretiliyor… Metninizin uzunluğuna göre tahmini {est_min}-{est_max} dakika "
                "sürebilir (başka ağır uygulamalar açıksa daha uzun sürer). "
                "**Pencereyi kapatmayın, bu normal** — bittiğinde burada 'Tamamlandı' yazacak."
            )
            generate_kwargs = dict(text=final_text, cfg_value=2.0, inference_timesteps=10)
            if prompt_text:
                # Devam kipi: model referansın GERÇEK içeriğini bilerek devam eder.
                # reference_wav_path ile birlikte verilince sonuç daha da sağlam olur.
                generate_kwargs["prompt_wav_path"] = reference_audio
                generate_kwargs["prompt_text"] = prompt_text
                generate_kwargs["reference_wav_path"] = reference_audio
            else:
                generate_kwargs["reference_wav_path"] = reference_audio or None
            wav = model.generate(**generate_kwargs)
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
    yield output, output, f"Tamamlandı: {perf_counter() - started:.1f} saniye. AI ile üretildi."


def _normal_generate(text, emotion_label):
    yield from generate_audio(text, None, EMOTIONS.get(emotion_label))


def _clone_generate(text, reference_audio, emotion_label, prompt_text):
    yield from generate_audio(text, reference_audio, EMOTIONS.get(emotion_label), prompt_text)




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


def _html(value, **kwargs):
    return gr.HTML(value, apply_default_css=False, **kwargs)


def _head(icon, title, text, step=None):
    badge = f'<span class="sv-step">{step}</span>' if step else f'<span class="sv-head-ic">{_svg(icon)}</span>'
    return _html(
        f'<div class="sv-head">{badge}<div><h3>{title}</h3><p>{text}</p></div></div>'
    )


_HERO = f"""
<div class="sv-hero">
  <div class="sv-aura" aria-hidden="true"><i></i><i></i><i></i></div>
  <nav class="sv-nav">
    <div class="sv-brand"><span class="sv-logo">{_svg(_IC_WAVE)}</span>SesVer</div>
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
    <div><b>Biraz sabır</b><span>Gerçek zamanlı değildir: M1'de 10 sn ses ≈ 70–80 sn sürer.</span></div></div>
</div>
"""

_FOOTER = f"""
<footer class="sv-foot">
  <span class="sv-brand sv-brand-sm"><span class="sv-logo">{_svg(_IC_WAVE)}</span>SesVer</span>
  <span>VoxCPM2 ile yerel ses üretimi</span><i></i>
  <span>Paylaşırken “AI ile üretildi” yazın</span>
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

.sv-nav { display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 6px 0 0; margin-bottom: 46px; }
.sv-brand { display: inline-flex; align-items: center; gap: 10px; font-weight: 700;
  font-size: 1.05rem; letter-spacing: 0.02em; color: var(--sv-ink); text-transform: uppercase; }
.sv-logo { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 11px;
  background: var(--sv-paper); border: 1px solid var(--sv-line); box-shadow: var(--sv-shadow-sm); }
.sv-logo .sv-ic { width: 17px; height: 17px; stroke-width: 2.2; }
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
#sv-tabs [role="tab"]:nth-child(1) { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'><path d='M4 6.5V5h16v1.5M12 5v14M9 19h6'/></svg>"); }
#sv-tabs [role="tab"]:nth-child(2) { --ic: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'><rect x='9' y='3' width='6' height='11' rx='3'/><path d='M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21'/></svg>"); }
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
_JS = "() => { document.querySelectorAll('.dark').forEach((el) => el.classList.remove('dark')); }"


def build_app():
    with gr.Blocks(title="SesVer — Türkçe yerel ses üretimi", analytics_enabled=False) as demo:
        _html(_HERO)

        with gr.Tabs(elem_id="sv-tabs"):
            with gr.Tab("Normal Ses Üretimi"):
                with gr.Row(equal_height=False, elem_classes=["sv-grid"]):
                    with gr.Column(scale=7, min_width=340, elem_classes=["sv-frame"]):
                        _html(
                            f'<div class="sv-frame-bar"><div class="sv-chips">'
                            f'<span class="sv-chip">{_svg(_IC_TEXT)}Metinden sese</span>'
                            f'<span class="sv-chip">Türkçe</span></div>'
                            f'<span class="sv-chip sv-chip-dark">{_svg(_IC_LOCK)}Yerel</span></div>'
                        )
                        with gr.Column(elem_classes=["sv-panel"]):
                            _head(None, "Metninizi yazın",
                                  "Bir ton seçmek isteğe bağlıdır; seçmezseniz doğal, nötr bir ses üretilir.", step="1")
                            n_text = gr.Textbox(
                                label="Metin", lines=5, max_length=500, value=_SAMPLE_TEXT,
                                placeholder="Seslendirilecek metni buraya yazın…",
                            )
                            n_emotion = gr.Radio(
                                choices=list(EMOTIONS.keys()), value="Nötr", label="Duygu / ton (isteğe bağlı)",
                                elem_classes=["sv-emotion"],
                            )
                            n_preview = gr.Markdown(elem_id="preview-box")
                            with gr.Row(elem_classes=["sv-actionbar"]):
                                _html('<div class="sv-hint"><b>En fazla 500 karakter.</b><br>'
                                      'Uzun metinleri parçalara bölün.</div>')
                                n_button = gr.Button(
                                    "Üret", variant="primary", scale=0, min_width=170,
                                    elem_classes=["sv-btn", "sv-btn-primary"],
                                )
                    with gr.Column(scale=5, min_width=300, elem_classes=["sv-card"]):
                        _head(*_RESULT_HEAD)
                        n_status = gr.Markdown("Hazır. Metninizi yazıp Üret'e basın.", elem_classes=["sv-status"])
                        n_audio = gr.Audio(
                            label="Üretilen ses — AI ile üretildi", type="filepath", interactive=False,
                            elem_classes=["sv-audio"],
                        )
                        n_download = gr.DownloadButton(
                            "⬇ WAV indir", variant="secondary", elem_classes=["sv-btn", "sv-btn-ghost"],
                        )
                        _html(_RESULT_NOTE)
                for trigger in (n_text.change, n_emotion.change):
                    trigger(lambda t, e: f"Üretilecek: _{_preview_text(t, e)}_", inputs=[n_text, n_emotion], outputs=n_preview)
                n_button.click(
                    _normal_generate, inputs=[n_text, n_emotion], outputs=[n_audio, n_download, n_status],
                    concurrency_limit=1, api_name="generate_audio", show_progress="full",
                )
                demo.load(lambda t, e: f"Üretilecek: _{_preview_text(t, e)}_", inputs=[n_text, n_emotion], outputs=n_preview)

            with gr.Tab("Ses Klonlama"):
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


if __name__ == "__main__":
    build_app().launch(
        server_name="127.0.0.1", server_port=7860, share=False, inbrowser=False,
        css=_CSS, theme=_THEME, js=_JS, footer_links=[],
    )
