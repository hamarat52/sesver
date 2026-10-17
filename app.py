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
# Referanslar: Dribbble "Futuristic AI Voice Generator Website" (Fahema Yesmin)
# — krem zemin, kalın başlık + mercan vurgu, metni saran gradient kart, siyah
# hap buton — ve "Voice Aura" tarzı sade/profesyonel SaaS görünümü.
_CSS = """
.gradio-container { background: #F9F8F8 !important; }
#hero-title h1 { font-weight: 800; font-size: 2.1rem; margin-bottom: 0.25rem; }
#hero-title .accent { color: #ED271E; }
#hero-sub { color: #685E59; margin-bottom: 1rem; }
.gradient-card {
    background: linear-gradient(135deg, #D5AFB3 0%, #CA8978 55%, #ED271E 100%);
    border-radius: 28px !important;
    padding: 24px !important;
    border: none !important;
}
.gradient-card .gr-box, .gradient-card textarea, .gradient-card input {
    border-radius: 18px !important;
    border: none !important;
}
.pill-btn button, button.pill-btn, .pill-btn.secondary button {
    border-radius: 999px !important;
    font-weight: 600;
    border: none !important;
}
button.primary.pill-btn, button.pill-btn.primary {
    background: #0B0C0B !important;
    background-color: #0B0C0B !important;
    color: #F9F8F8 !important;
}
button.primary.pill-btn:hover, button.pill-btn.primary:hover {
    background: #2a2a2a !important;
    background-color: #2a2a2a !important;
}
button.secondary.pill-btn, button.pill-btn.secondary {
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    color: #0B0C0B !important;
    border: 1.5px solid #0B0C0B !important;
}
.emotion-row .wrap label {
    border-radius: 999px !important;
    border: 1.5px solid #0B0C0B !important;
    padding: 4px 14px !important;
    margin: 2px !important;
}
.emotion-row .wrap label.selected {
    background: #0B0C0B !important;
    color: #F9F8F8 !important;
}
#preview-box { font-family: monospace; font-size: 0.85rem; color: #562E24; }
"""


def build_app():
    with gr.Blocks(title="SesVer", analytics_enabled=False) as demo:
        gr.HTML(
            '<div id="hero-title"><h1>Sesinizi <span class="accent">Keşfedin</span>.</h1></div>'
            '<div id="hero-sub">Ücretsiz, yerel ve açık kaynak Türkçe ses üretimi + klonlama. '
            '16 GB+ RAM önerilir; M1\'de gerçek zamanlı değildir (10 sn ses ≈ 70–80 sn). '
            'İlk üretimde ~5 GB model indirilir.</div>'
        )

        with gr.Tabs():
            with gr.Tab("Normal Ses Üretimi"):
                with gr.Group(elem_classes=["gradient-card"]):
                    gr.Markdown("Metni yazın, isterseniz bir **duygu** seçin, **Üret**'e basın.")
                    n_text = gr.Textbox(
                        label="Metin", lines=4, max_length=500,
                        value="Merhaba! Bu ses, bilgisayarımda çalışan açık kaynak bir yapay zekâ ile üretildi.",
                    )
                    n_emotion = gr.Radio(
                        choices=list(EMOTIONS.keys()), value="Nötr", label="Duygu/Ton (isteğe bağlı)",
                        elem_classes=["emotion-row"],
                    )
                    n_preview = gr.Markdown(elem_id="preview-box")
                    n_button = gr.Button("Üret", variant="primary", elem_classes=["pill-btn"])
                n_status = gr.Markdown("Hazır. Metninizi yazıp Üret'e basın.")
                n_audio = gr.Audio(label="Üretilen ses — AI ile üretildi", type="filepath", interactive=False)
                n_download = gr.DownloadButton("⬇ WAV indir", variant="secondary", elem_classes=["pill-btn"])
                for trigger in (n_text.change, n_emotion.change):
                    trigger(lambda t, e: f"Üretilecek: _{_preview_text(t, e)}_", inputs=[n_text, n_emotion], outputs=n_preview)
                n_button.click(
                    _normal_generate, inputs=[n_text, n_emotion], outputs=[n_audio, n_download, n_status],
                    concurrency_limit=1, api_name="generate_audio", show_progress="full",
                )
                demo.load(lambda t, e: f"Üretilecek: _{_preview_text(t, e)}_", inputs=[n_text, n_emotion], outputs=n_preview)

            with gr.Tab("Ses Klonlama"):
                with gr.Group(elem_classes=["gradient-card"]):
                    gr.Markdown(
                        "Tek kişinin konuştuğu, müziksiz ve temiz **3–15 saniyelik WAV** önerilir "
                        "(kabul: 1–30 saniye). Referansın metnini yazmanız gerekmez.\n\n"
                        "Yalnız kendi sesinizi veya açık izin aldığınız sesleri kullanın. "
                        "Paylaşırken **'AI ile üretildi'** etiketi ekleyin; otomatik filigran yoktur. "
                        "Taklit yoluyla yanıltma ve dolandırıcılık için kullanmayın.\n\n"
                        "**Not:** Bir duygu seçmek klonlanan sesin orijinaline benzerliğini azaltabilir "
                        "(ses kimliği ile stil arasında bilinen bir ödünleşim)."
                    )
                    c_text = gr.Textbox(
                        label="Metin", lines=4, max_length=500,
                        value="Merhaba! Bu ses, bilgisayarımda çalışan açık kaynak bir yapay zekâ ile üretildi.",
                    )
                    c_reference = gr.Audio(
                        label="Referans ses (gerekli)", sources=["upload"], type="filepath",
                    )
                    with gr.Row():
                        c_prompt_text = gr.Textbox(
                            label="Referans sesin metni (isteğe bağlı ama önerilir — \"devam kipi\")",
                            placeholder="Referans kayıtta tam olarak ne söylendiğini yazın; boş bırakılırsa yalnız ses rengi taklit edilir.",
                            lines=2, scale=4,
                        )
                        c_transcribe_btn = gr.Button("🎙️ Otomatik yazıya dök", scale=1, elem_classes=["pill-btn"])
                    gr.Markdown(
                        "Bu metni doldurmak, modelin referansı **gerçekten anlayarak devam etmesini** sağlar "
                        "ve klon kalitesini belirgin artırır (boş bırakılırsa eski davranış: yalnız ses rengi kopyalanır)."
                    )
                    c_emotion = gr.Radio(
                        choices=list(EMOTIONS.keys()), value="Nötr", label="Duygu/Ton (isteğe bağlı, varsayılan: nötr)",
                        elem_classes=["emotion-row"],
                    )
                    c_button = gr.Button("Klonla ve Üret", variant="primary", elem_classes=["pill-btn"])
                c_status = gr.Markdown("Hazır. Metin ve referans ses yükleyip Klonla ve Üret'e basın.")
                c_audio = gr.Audio(label="Üretilen ses — AI ile üretildi", type="filepath", interactive=False)
                c_download = gr.DownloadButton("⬇ WAV indir", variant="secondary", elem_classes=["pill-btn"])
                c_button.click(
                    _clone_generate, inputs=[c_text, c_reference, c_emotion, c_prompt_text],
                    outputs=[c_audio, c_download, c_status],
                    concurrency_limit=1, api_name="clone_audio", show_progress="full",
                )
                c_transcribe_btn.click(
                    auto_transcribe, inputs=[c_reference], outputs=[c_prompt_text],
                    concurrency_limit=1, show_progress="full",
                )
    return demo.queue(default_concurrency_limit=1, max_size=8)


if __name__ == "__main__":
    build_app().launch(server_name="127.0.0.1", server_port=7860, share=False, inbrowser=False, css=_CSS)
