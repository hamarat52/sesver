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


def get_model():
    """Yalnız üretim kilidi içinden çağrılır; arayüz açılırken model yüklenmez."""
    global _model
    if _model is None:
        from voxcpm import VoxCPM
        _model = VoxCPM.from_pretrained(
            hf_model_id=MODEL_ID, load_denoiser=False, optimize=False,
        )
    return _model


def generate_audio(text, reference_audio):
    """Durumu hemen göster; aynı modelde üretimleri sıraya koy."""
    # Eski çıktı, yeni istek başarısız olsa bile yeni ses sanılmasın.
    yield None, None, "İstek kontrol ediliyor…"
    text = (text or "").strip()
    if not text:
        raise gr.Error("Lütfen okunacak bir metin yazın.")
    if len(text) > 500:
        raise gr.Error("İlk sürümde en fazla 500 karakter kullanın; uzun metni bölün.")
    if reference_audio:
        try:
            info = sf.info(reference_audio)
            if not 1 <= info.duration <= 30:
                raise ValueError("Süre 1–30 saniye olmalı.")
        except (OSError, RuntimeError, ValueError) as exc:
            raise gr.Error("Referans ses okunamadı. 1–30 saniyelik geçerli bir WAV yükleyin.") from exc
    started = perf_counter()
    yield None, None, "İşleniyor… İlk kullanımda model indiriliyor/yükleniyor."
    try:
        with _model_lock:
            model = get_model()
            yield None, None, "Ses üretiliyor… M1'de 10 saniyelik ses yaklaşık 70–80 saniye sürebilir."
            wav = model.generate(
                text=text, reference_wav_path=reference_audio or None,
                cfg_value=2.0, inference_timesteps=10,
            )
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


def build_app():
    with gr.Blocks(title="SesVer", analytics_enabled=False) as demo:
        gr.Markdown(
            "# SesVer\nÜcretsiz, yerel ve açık kaynak Türkçe ses üretimi + klonlama.\n\n"
            "**16 GB+ RAM önerilir.** M1'de gerçek zamanlı değildir: 10 saniyelik ses "
            "yaklaşık 70–80 saniye sürebilir. İlk üretimde ~5 GB model indirilir; "
            "indirme ve yükleme ayrıca zaman alır."
        )
        text = gr.Textbox(
            label="Metin", lines=4, max_length=500,
            value="Merhaba! Bu ses, bilgisayarımda çalışan açık kaynak bir yapay zekâ ile üretildi.",
        )
        reference = gr.Audio(
            label="Referans ses (isteğe bağlı)", sources=["upload"], type="filepath",
        )
        gr.Markdown(
            "Referans olmadan yeni bir ses üretilir. Klonlama için tek kişinin konuştuğu, "
            "müziksiz ve temiz **3–15 saniyelik WAV** önerilir (kabul: 1–30 saniye). "
            "Referansın metnini yazmanız gerekmez.\n\n"
            "Yalnız kendi sesinizi veya açık izin aldığınız sesleri kullanın. "
            "Paylaşırken **‘AI ile üretildi’** etiketi ekleyin; otomatik filigran yoktur. "
            "Taklit yoluyla yanıltma ve dolandırıcılık için kullanmayın."
        )
        button = gr.Button("Üret", variant="primary")
        status = gr.Markdown("Hazır. Metninizi yazıp Üret'e basın.")
        audio = gr.Audio(label="Üretilen ses — AI ile üretildi", type="filepath", interactive=False)
        download = gr.File(label="WAV indir", interactive=False)
        button.click(
            generate_audio, inputs=[text, reference], outputs=[audio, download, status],
            concurrency_limit=1, api_name="generate_audio", show_progress="full",
        )
    return demo.queue(default_concurrency_limit=1, max_size=8)


if __name__ == "__main__":
    build_app().launch(server_name="127.0.0.1", server_port=7860, share=False, inbrowser=False)
