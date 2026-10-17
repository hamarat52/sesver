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
        self.assertIn("Referans ses (isteğe bağlı)", labels)
        self.assertIn("WAV indir", labels)


if __name__ == "__main__":
    unittest.main()
