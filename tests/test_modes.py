"""Kütüphane kipleri, seed, istek logu ve kayıt akışları (model taklit edilir)."""
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

import app
import voice_library as vl


def fake_model():
    return SimpleNamespace(tts_model=SimpleNamespace(sample_rate=16000),
                           generate=Mock(side_effect=lambda **kw: (0.1 * np.random.randn(16000 * 9)).astype(np.float32)))


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.model = fake_model()
        self.voices = self.tmp / "voices"
        wav = self.tmp / "ref.wav"
        sf.write(wav, (0.1 * np.random.randn(16000 * 10)).astype(np.float32), 16000)
        vl.save_voice(ad="Test Sesi", ref_wav=wav, ref_text="Kaydın metni.", root=self.voices,
                      kaynak="Tarifle tasarlandı (sentetik ses, gerçek kişi değil)", voice_id="test-sesi")
        self.patches = [patch.object(app, "OUTPUT_DIR", self.tmp / "out"),
                        patch.object(app, "get_model", return_value=self.model),
                        patch.object(vl, "VOICES_DIR", self.voices)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def kwargs(self):
        return self.model.generate.call_args.kwargs

    def test_saved_voice_neutral_uses_continuation_without_description(self):
        with self.assertLogs("sesver", level="INFO") as logs:
            last = list(app.library_generate("Yeni metin.", "Nötr", "Dengeli", "test-sesi"))[-1]
        kw = self.kwargs()
        ref = str(self.voices / "seslerim" / "test-sesi" / "ref.wav")
        self.assertEqual(kw["text"], "Yeni metin.")
        self.assertEqual((kw["prompt_wav_path"], kw["prompt_text"], kw["reference_wav_path"]),
                         (ref, "Kaydın metni.", ref))
        self.assertIsNotNone(last[0])
        line = logs.output[-1]
        self.assertIn("kip=devam", line)
        self.assertIn("ses=test-sesi", line)
        self.assertIn("tarif=yok", line)
        self.assertNotIn("Yeni metin", line)  # metin loglanmaz

    def test_saved_voice_with_emotion_switches_to_controlled_clone(self):
        with self.assertLogs("sesver", level="INFO") as logs:
            list(app.library_generate("Yeni metin.", "Heyecanlı", "Dengeli", "test-sesi"))
        kw = self.kwargs()
        self.assertEqual(kw["text"], "(excited)Yeni metin.")
        self.assertNotIn("prompt_text", kw)
        self.assertNotIn("prompt_wav_path", kw)
        self.assertIn("kip=kontrollu_klon", logs.output[-1])
        note = app._mode_info("test-sesi", "Heyecanlı")
        self.assertIn(app.SIMILARITY_NOTE, note)
        self.assertNotIn(app.SIMILARITY_NOTE, app._mode_info("test-sesi", "Nötr"))

    def test_random_card_keeps_old_reference_free_generation(self):
        list(app.library_generate("Merhaba.", "Üzgün", "Dengeli", app.RANDOM_VOICE))
        kw = self.kwargs()
        self.assertEqual(kw["text"], "(sad)Merhaba.")
        self.assertIsNone(kw["reference_wav_path"])
        self.assertEqual(kw["inference_timesteps"], 10)

    def test_quality_maps_to_timesteps(self):
        for quality, steps in app.QUALITY.items():
            list(app.library_generate("Merhaba.", "Nötr", quality, app.RANDOM_VOICE))
            self.assertEqual(self.kwargs()["inference_timesteps"], steps)
        self.assertEqual(app.QUALITY["Dengeli"], 10)

    def test_seed_is_applied_right_before_generation(self):
        with patch.object(app, "_seed_everything") as seeder:
            list(app.generate_audio("Merhaba.", None, "calm", seed=22))
        seeder.assert_called_once_with(22)
        with patch.object(app, "_seed_everything") as seeder:
            list(app.generate_audio("Merhaba.", None))
        seeder.assert_not_called()

    def test_seed_everything_makes_torch_repeatable(self):
        import torch
        app._seed_everything(33)
        a = torch.randn(5)
        app._seed_everything(33)
        self.assertTrue(torch.equal(a, torch.randn(5)))

    def test_four_candidates_then_save_then_continuation(self):
        sel = ["Erkek", "Yaşlı", "Masal", 2, "Sıcak", ["Boğuk"], 2, 2]
        tarif = "an elderly male storyteller, deep, warm, husky, slow"
        with self.assertLogs("sesver", level="INFO") as logs:
            outs = list(app.design_candidates(tarif, "Bir varmış bir yokmuş.", "Hızlı", 0, {}, *sel))
        final = outs[-1]
        audios, cands, meta = final[:4], final[9], final[10]
        self.assertTrue(all(audios))
        self.assertEqual(sorted(cands), ["11", "22", "33", "44"])
        texts = [c.kwargs["text"] for c in self.model.generate.call_args_list]
        self.assertEqual(texts, [f"({tarif})Bir varmış bir yokmuş."] * 4)
        self.assertTrue(all("kip=tasarim" in line and "tarif=var" in line for line in logs.output))
        # İlk aday, diğerleri bitmeden kendi kartına düşer.
        first_ready = next(o for o in outs if o[0])
        self.assertIsNone(first_ready[1])

        seed, _vis, _md = app.pick_candidate_ui(1, 0, cands)
        self.assertEqual(seed, 22)
        voices, new_id, _tabs, _msg = app.save_designed_ui("Gece Masalcısı", "", "Masal", seed, cands, meta)
        folder = self.voices / "seslerim" / new_id
        for name in ("ref.wav", "ref.txt", "ses.json"):
            self.assertTrue((folder / name).is_file())
        voice = vl.get_voice(new_id)
        self.assertEqual((voice["seed"], voice["tarif"], voice["ref_text"]), (22, tarif, "Bir varmış bir yokmuş."))
        self.assertEqual(voice["secimler"]["perde"], "Kalın")
        self.assertIn(new_id, [v["id"] for v in voices])

        with self.assertLogs("sesver", level="INFO") as logs:
            list(app.library_generate("Sonraki metin.", "Nötr", "Dengeli", new_id))
        self.assertEqual(self.kwargs()["text"], "Sonraki metin.")
        self.assertIn("kip=devam", logs.output[-1])
        self.assertIn("tarif=yok", logs.output[-1])

    def test_more_candidates_use_new_seeds(self):
        sel = [None] * 5 + [[]] + [3, 2]
        list(app.design_candidates("a calm voice", "Merhaba.", "Hızlı", 1, {}, *sel))
        self.assertEqual(self.model.generate.call_count, 4)

    def test_upload_save_requires_consent_and_text(self):
        wav = self.tmp / "up.wav"
        sf.write(wav, (0.1 * np.random.randn(16000 * 10)).astype(np.float32), 16000)
        with self.assertRaisesRegex(app.gr.Error, "izin"):
            app.save_uploaded_ui(str(wav), "Metin.", "Benim Sesim", "", "", False)
        with self.assertRaisesRegex(app.gr.Error, "boş"):
            app.save_uploaded_ui(str(wav), "  ", "Benim Sesim", "", "", True)
        _v, vid, _t, _m = app.save_uploaded_ui(str(wav), "Metin.", "Benim Sesim", "", "", True)
        voice = vl.get_voice(vid)
        self.assertEqual(voice["kaynak"], "yüklendi")
        self.assertFalse(voice["hazir"])

    def test_upload_transcribe_reports_speech_ratio(self):
        wav = self.tmp / "up.wav"
        sf.write(wav, np.zeros(16000 * 9, dtype=np.float32), 16000)
        with patch.object(app, "transcribe_with_info", return_value=("Merhaba", 0.3)):
            text, note = app.upload_transcribe_ui(str(wav))
        self.assertEqual(text, "Merhaba")
        self.assertIn("müzik veya sessizlik", note)

    def test_effects_ui_keeps_raw_file_and_writes_fx_copy(self):
        raw = list(app.library_generate("Merhaba.", "Nötr", "Dengeli", app.RANDOM_VOICE))[-1][0]
        before = Path(raw).read_bytes()
        vals = app._fx_values([{"ad": "telefon", "yogunluk": 60}])
        fx_path, _dl, msg = app.apply_effects_ui(raw, *vals)
        self.assertTrue(fx_path.endswith(".wav") and "-fx-" in fx_path)
        self.assertEqual(Path(raw).read_bytes(), before)
        self.assertIn("LUFS", msg)
        self.assertEqual(app._fx_settings(*vals), [{"ad": "telefon", "yogunluk": 60}])
        off = app._fx_values([])
        self.assertEqual(app.apply_effects_ui(raw, *off)[0], None)

    def test_ui_has_library_create_and_clone_tabs_only(self):
        demo = app.build_app()
        tabs = [c["props"].get("label") for c in demo.config["components"] if c.get("type") == "tabitem"]
        self.assertEqual(tabs[:1], ["Ses Kütüphanesi"])
        for label in ("Ses Oluştur", "Seçimlerle tarif et", "Dosya yükle", "Ses Klonlama"):
            self.assertIn(label, tabs)
        self.assertNotIn("Normal Ses Üretimi", tabs)
        apis = [d.get("api_name") for d in demo.config["dependencies"]]
        self.assertIn("generate_audio", apis)
        self.assertIn("clone_audio", apis)
        sliders = [c["props"] for c in demo.config["components"] if c["props"].get("label") == "Örnek ses süresi (sn)"]
        self.assertEqual((sliders[0]["minimum"], sliders[0]["maximum"], sliders[0]["value"]), (10, 20, 14))

    def test_default_sample_text_is_long_enough(self):
        # Varsayılan cümle ~14 sn; kısa referans eşiğinin (8 sn) belirgin üstünde.
        text = app.vdes.sample_text("masal", app._DEFAULT_SAMPLE_SECONDS, app._DMAP)
        self.assertGreaterEqual(app.vdes.estimate_seconds(text, app._DMAP), 10)
        self.assertGreaterEqual(app._MIN_SAMPLE_SECONDS, 10)

    def _cand(self, seconds, seed=11):
        path = self.tmp / f"aday-{seed}.wav"
        sf.write(path, np.zeros(int(16000 * seconds), dtype=np.float32), 16000)
        return {str(seed): str(path)}

    def test_short_candidate_warns_but_does_not_block_save(self):
        cands = self._cand(6)
        meta = {"tarif": "a voice", "text": "Kısa.", "secimler": {"doku": ["Berrak"]}}
        seed, _vis, md = app.pick_candidate_ui(0, 0, cands, meta)
        self.assertIn(app.SHORT_SAMPLE_WARNING, md)
        self.assertNotIn(app.TEXTURE_WARNING, md)
        _voices, new_id, _tabs, _msg = app.save_designed_ui("Kısa Ses", "", "Masal", seed, cands, meta)
        self.assertTrue((self.voices / "seslerim" / new_id / "ref.wav").is_file())

    def test_long_candidate_has_no_short_warning(self):
        seed, _vis, md = app.pick_candidate_ui(0, 0, self._cand(12), {"secimler": {"doku": []}})
        self.assertEqual(seed, 11)
        self.assertNotIn("⚠️", md)

    def test_fragile_texture_warns(self):
        for doku in (["Nefesli"], ["Tok", "Pürüzlü"]):
            _seed, _vis, md = app.pick_candidate_ui(0, 0, self._cand(12), {"secimler": {"doku": doku}})
            self.assertIn(app.TEXTURE_WARNING, md)
            self.assertNotIn(app.SHORT_SAMPLE_WARNING, md)


if __name__ == "__main__":
    unittest.main()
