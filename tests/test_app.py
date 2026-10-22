"""Model indirmeden arayüz sözleşmesini sınayan birim testleri."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf


class AppTests(unittest.TestCase):
    def test_plain_generation_writes_playable_unique_wav(self):
        self.assertIsNotNone(importlib.util.find_spec("app"), "app.py henüz yok")
        import app
        # Yalnız pahalı sinir ağı taklit edilir; gerçek WAV yazımı sınanır.
        model = SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),
                                generate=lambda **kw: np.zeros(4800, dtype=np.float32))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(app, "OUTPUT_DIR", Path(directory)), \
                patch.object(app, "get_model", return_value=model):
            first = list(app.generate_audio(" Merhaba. ", None))[-1]
            second = list(app.generate_audio("Merhaba.", None))[-1]
            self.assertEqual(first[0], first[1])
            self.assertNotEqual(first[0], second[0])
            self.assertEqual(sf.info(first[0]).samplerate, 48000)
            self.assertIn("saniye", first[2])
    def test_clone_passes_reference_without_transcript(self):
        import app
        from unittest.mock import Mock
        model = SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),
                                generate=Mock(return_value=np.zeros(4800)))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(app, "OUTPUT_DIR", Path(directory)), \
                patch.object(app, "get_model", return_value=model):
            reference = str(Path(directory) / "reference.wav")
            sf.write(reference, np.zeros(48000), 16000)
            list(app.generate_audio("Merhaba.", reference))
            self.assertEqual(model.generate.call_args.kwargs.get("reference_wav_path"), reference)
            self.assertNotIn("prompt_text", model.generate.call_args.kwargs)

    def test_invalid_inputs_fail_before_loading_model(self):
        import app
        for text, reference, message in [(" ", None, "metin"), ("a" * 501, None, "500"),
                                         ("Merhaba", "missing.wav", "Referans")]:
            with self.subTest(text=text[:10]), patch.object(app, "get_model") as load:
                with self.assertRaisesRegex(app.gr.Error, message):
                    list(app.generate_audio(text, reference))
                load.assert_not_called()

    def test_model_failure_is_turkish_and_clears_outputs(self):
        import app
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()), \
                patch.object(app, "get_model", side_effect=RuntimeError("private details")):
            events = app.generate_audio("Merhaba", None)
            self.assertEqual(next(events)[:2], (None, None))
            last = list(events)[-1]
            self.assertEqual(last[:2], (None, None))
            self.assertIn("Üretim başarısız", last[2])
            self.assertNotIn("private details", last[2])

    def test_invalid_request_clears_previous_audio_first(self):
        import app
        events = app.generate_audio("", None)
        try:
            event = next(events)
        except app.gr.Error:
            self.fail("Geçersiz giriş, önceki ses temizlenmeden hata verdi")
        self.assertEqual(event[:2], (None, None))
        with self.assertRaises(app.gr.Error):
            list(events)

    def test_ui_is_lazy_local_and_serialized(self):
        import app
        self.assertTrue(hasattr(app, "build_app"), "Arayüz eksik")
        import asyncio

        async def construct():
            return app.build_app()

        with patch.object(app, "get_model") as load:
            demo = asyncio.run(construct())
            load.assert_not_called()
        self.assertFalse(demo.analytics_enabled)
        self.assertEqual(demo._queue.default_concurrency_limit, 1)
        labels = [c.get("props", {}).get("label") for c in demo.config["components"]]
        self.assertIn("Metin", labels)
        self.assertIn("Referans ses (gerekli)", labels)
        self.assertIn("⬇ WAV indir", labels)
        # Gradio'nun "share" düğmesi sesi herkese açık HF Discussions'a yükler: hiçbir gr.Audio'da olmamalı.
        audios = [c["props"] for c in demo.config["components"] if c.get("type") == "audio"]
        self.assertGreaterEqual(len(audios), 7)
        for props in audios:
            self.assertNotIn("share", props.get("buttons") or [], props.get("label"))

    def test_instruction_is_prepended_to_text(self):
        import app
        from unittest.mock import Mock
        model = SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),
                                generate=Mock(return_value=np.zeros(4800)))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(app, "OUTPUT_DIR", Path(directory)), \
                patch.object(app, "get_model", return_value=model):
            list(app.generate_audio("Merhaba.", None, instruction="energetic, playful"))
            self.assertEqual(model.generate.call_args.kwargs.get("text"), "(energetic, playful)Merhaba.")

    def test_pad_quadrants_map_to_expected_instruction(self):
        import app
        self.assertIsNone(app.EMOTIONS["Nötr"])
        self.assertEqual(app.EMOTIONS["Enerjik"], "energetic")
        self.assertEqual(app.EMOTIONS["Sakin"], "calm")
        self.assertEqual(app.EMOTIONS["Neşeli"], "cheerful")
        self.assertEqual(app.EMOTIONS["Ciddi"], "serious")

    def test_emotion_preview_shows_bracketed_instruction(self):
        import app
        self.assertEqual(app._preview_text("Merhaba.", "Enerjik"), "(energetic)Merhaba.")
        self.assertEqual(app._preview_text("Merhaba.", "Nötr"), "Merhaba.")
        self.assertEqual(app._preview_text("", "Enerjik"), "(metin boş)")

    def test_normal_generate_applies_selected_emotion(self):
        import app
        from unittest.mock import Mock
        model = SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),
                                generate=Mock(return_value=np.zeros(4800)))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(app, "OUTPUT_DIR", Path(directory)), \
                patch.object(app, "get_model", return_value=model):
            list(app._normal_generate("Merhaba.", "Üzgün"))
            self.assertEqual(model.generate.call_args.kwargs.get("text"), "(sad)Merhaba.")
            self.assertIsNone(model.generate.call_args.kwargs.get("reference_wav_path"))

    def test_clone_generate_applies_selected_emotion_and_reference(self):
        import app
        from unittest.mock import Mock
        model = SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),
                                generate=Mock(return_value=np.zeros(4800)))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(app, "OUTPUT_DIR", Path(directory)), \
                patch.object(app, "get_model", return_value=model):
            reference = str(Path(directory) / "reference.wav")
            sf.write(reference, np.zeros(48000), 16000)
            list(app._clone_generate("Merhaba.", reference, "Neşeli", None))
            self.assertEqual(model.generate.call_args.kwargs.get("text"), "(cheerful)Merhaba.")
            self.assertEqual(model.generate.call_args.kwargs.get("reference_wav_path"), reference)

    def test_prompt_text_enables_continuation_mode(self):
        import app
        from unittest.mock import Mock
        model = SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),
                                generate=Mock(return_value=np.zeros(4800)))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(app, "OUTPUT_DIR", Path(directory)), \
                patch.object(app, "get_model", return_value=model):
            reference = str(Path(directory) / "reference.wav")
            sf.write(reference, np.zeros(48000), 16000)
            list(app.generate_audio("Merhaba.", reference, prompt_text="Referansta söylenen tam metin."))
            kwargs = model.generate.call_args.kwargs
            self.assertEqual(kwargs.get("prompt_wav_path"), reference)
            self.assertEqual(kwargs.get("prompt_text"), "Referansta söylenen tam metin.")
            self.assertEqual(kwargs.get("reference_wav_path"), reference)

    def test_prompt_text_without_reference_is_rejected(self):
        import app
        with patch.object(app, "get_model") as load:
            with self.assertRaisesRegex(app.gr.Error, "Referans"):
                list(app.generate_audio("Merhaba.", None, prompt_text="metin"))
            load.assert_not_called()

    def test_auto_transcribe_requires_reference(self):
        import app
        with self.assertRaisesRegex(app.gr.Error, "referans"):
            app.auto_transcribe(None)

    def test_auto_transcribe_returns_whisper_text(self):
        import app
        from unittest.mock import Mock
        segment = SimpleNamespace(text=" Merhaba dünya. ")
        whisper = Mock(transcribe=Mock(return_value=([segment], None)))
        with patch.object(app, "_get_whisper", return_value=whisper):
            result = app.auto_transcribe("/tmp/herhangi.wav")
        self.assertEqual(result, "Merhaba dünya.")

    def test_brand_signature_visible_in_hero_and_footer(self):
        import app
        # İmza tek yerde tanımlı; üst bilgi (ilk ekran) ve alt bilgi oradan okur.
        self.assertEqual(app.BRAND_NAME, "HamaratLabs")
        self.assertIn("by <b", app.BRAND_SIGNATURE_HTML)
        self.assertIn("HamaratLabs", app.BRAND_SIGNATURE_HTML)
        self.assertIn(app.BRAND_SIGNATURE_HTML, app._hero())
        # İmza, kaydırmadan görünen üst gezinme çubuğunda olmalı.
        nav = app._hero().split('<nav class="sv-nav">', 1)[1].split("</nav>", 1)[0]
        self.assertIn(app.BRAND_SIGNATURE_HTML, nav)
        self.assertIn("HamaratLabs tarafından geliştirildi", app._footer())
        # .sv-brand büyük harfe çevirir; imza yazımı korunmalı (HAMARATLABS olmamalı).
        sig_css = app._CSS.split(".sv-sig {", 1)[1].split("}", 1)[0]
        self.assertIn("text-transform: none", sig_css)

    def test_brand_spelling_is_consistent(self):
        import re
        import app
        readme = (Path(app.__file__).parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("HamaratLabs tarafından geliştirilmiştir.", readme.splitlines()[:4])
        for source in (app._hero(), app._footer(), readme):
            for match in re.findall(r"hamarat\s*-?\s*labs", source, flags=re.IGNORECASE):
                self.assertEqual(match, "HamaratLabs")

    def test_hero_intro_animation_runs_once_and_respects_reduced_motion(self):
        import re
        import app
        css = app._CSS
        self.assertIn("@keyframes sv-aura-in", css)
        rule = re.search(r"\.sv-aura i \{[^}]*animation:\s*sv-aura-in[^;}]*", css)
        self.assertIsNotNone(rule)
        assert rule is not None
        # Tek seferlik: sonsuz döngü yok; bitince sabit stile döner (forwards/both yok).
        self.assertNotIn("infinite", rule.group(0))
        self.assertRegex(rule.group(0), r"\b1 backwards\b")
        # Yalnız GPU dostu özellikler canlandırılır.
        frames = css.split("@keyframes sv-aura-in", 1)[1].split("}", 2)[:2]
        self.assertNotIn("filter", "".join(frames))
        # Hareket azaltma tercihi olanlarda animasyon kapalı.
        self.assertRegex(css, r"@media \(prefers-reduced-motion: reduce\) \{\s*\.sv-aura i \{ animation: none")


if __name__ == "__main__":
    unittest.main()
