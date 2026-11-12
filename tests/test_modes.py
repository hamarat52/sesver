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
            outs = list(app.design_candidates(tarif, "Bir varmış bir yokmuş.", "Hızlı", *SEEDS0, {}, *sel))
        final = outs[-1]
        audios, labels, cands = final[:4], final[4:8], final[9]
        self.assertTrue(all(audios))
        self.assertEqual([cands[str(i)]["seed"] for i in range(4)], [11, 22, 33, 44])
        texts = [c.kwargs["text"] for c in self.model.generate.call_args_list]
        self.assertEqual(texts, [f"({tarif})Bir varmış bir yokmuş."] * 4)
        self.assertTrue(all("kip=tasarim" in line and "tarif=var" in line for line in logs.output))
        # İlk aday, diğerleri bitmeden kendi kartına düşer.
        first_ready = next(o for o in outs if o[0])
        self.assertIsNone(first_ready[1])
        # Her kartta seed ve üretim süresi; durumda toplam süre (normal üretimdeki "Tamamlandı: X saniye" dili).
        for i, label in enumerate(labels):
            self.assertRegex(label, rf"^Aday {i + 1} · seed {11 * (i + 1)} · \d+\.\d saniye$")
        self.assertRegex(final[8], r"^Tamamlandı: 4 aday, toplam \d+\.\d saniye\.")

        index, _vis, _md = app.pick_candidate_ui(1, cands)
        self.assertEqual(index, 1)
        voices, new_id, _tabs, _msg = app.save_designed_ui("Gece Masalcısı", "", "Masal", index, cands)
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
        with patch.object(app, "_seed_everything") as seeder:
            list(app.design_candidates("a calm voice", "Merhaba.", "Hızlı", *map(str, app.vdes.candidate_seeds(1)),
                                       {}, *sel))
        self.assertEqual(self.model.generate.call_count, 4)
        self.assertEqual([c.args[0] for c in seeder.call_args_list], [55, 66, 77, 88])

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

    def _cand(self, seconds, seed=11, doku=()):
        path = self.tmp / f"aday-{seed}.wav"
        sf.write(path, np.zeros(int(16000 * seconds), dtype=np.float32), 16000)
        return {"0": {"seed": seed, "yol": str(path), "sure": 1.0, "tarif": "a voice", "text": "Kısa.",
                      "secimler": {"doku": list(doku)}}}

    def test_short_candidate_warns_but_does_not_block_save(self):
        cands = self._cand(6, doku=["Berrak"])
        index, _vis, md = app.pick_candidate_ui(0, cands)
        self.assertIn(app.SHORT_SAMPLE_WARNING, md)
        self.assertNotIn(app.TEXTURE_WARNING, md)
        _voices, new_id, _tabs, _msg = app.save_designed_ui("Kısa Ses", "", "Masal", index, cands)
        self.assertTrue((self.voices / "seslerim" / new_id / "ref.wav").is_file())

    def test_long_candidate_has_no_short_warning(self):
        index, _vis, md = app.pick_candidate_ui(0, self._cand(12))
        self.assertEqual(index, 0)
        self.assertIn("seed 11", md)
        self.assertNotIn("⚠️", md)

    def test_fragile_texture_warns(self):
        for doku in (["Nefesli"], ["Tok", "Pürüzlü"]):
            _index, _vis, md = app.pick_candidate_ui(0, self._cand(12, doku=doku))
            self.assertIn(app.TEXTURE_WARNING, md)
            self.assertNotIn(app.SHORT_SAMPLE_WARNING, md)

    def test_pick_and_save_require_a_generated_candidate(self):
        with self.assertRaisesRegex(app.gr.Error, "henüz üretilmedi"):
            app.pick_candidate_ui(2, self._cand(12))
        with self.assertRaisesRegex(app.gr.Error, "Önce bir aday"):
            app.save_designed_ui("Ad", "", "Masal", None, self._cand(12))


SEEDS0 = ("11", "22", "33", "44")  # seed kutularının ilk değerleri (metin kutusu → str)
SEL = ["Erkek", "Yaşlı", "Masal", 2, "Sıcak", [], 2, 2]


def seeded_model():
    """Çıktısı yalnız np.random durumuna bağlı sahte model: aynı seed → aynı ses (gerçek _seed_everything)."""
    return SimpleNamespace(tts_model=SimpleNamespace(sample_rate=16000),
                           generate=Mock(side_effect=lambda **kw: (0.1 * np.random.randn(16000 * 9)).astype(np.float32)))


class CandidateSeedTests(unittest.TestCase):
    """1.4.1: aday seed'i görünür, değiştirilebilir; tek aday yeniden üretilebilir."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.model = seeded_model()
        self.patches = [patch.object(app, "OUTPUT_DIR", self.tmp / "out"),
                        patch.object(app, "get_model", return_value=self.model),
                        patch.object(vl, "VOICES_DIR", self.tmp / "voices")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def four(self, seeds=SEEDS0, tarif="a calm voice", text="Merhaba."):
        return list(app.design_candidates(tarif, text, "Hızlı", *seeds, {}, *SEL))[-1]

    def test_seed_parser_accepts_only_whole_numbers_in_range(self):
        for ok, beklenen in (("0", 0), ("42", 42), (" 7 ", 7), ("007", 7), ("4294967295", 2 ** 32 - 1),
                             ("١٢", 12), (5, 5)):
            self.assertEqual(app.seed_coz(ok), beklenen, ok)
        for bad in ("-1", "1.5", "1,5", "4294967296", "99999999999", "abc", "1e3", "+5", "", "  ", None, True,
                    -3, 2 ** 32, 1.0):
            self.assertIsNone(app.seed_coz(bad), repr(bad))
        self.assertEqual(app.SEED_EN_FAZLA, 2 ** 32 - 1)

    def test_invalid_seed_is_rejected_before_the_model_runs(self):
        for bad in ("-1", "2.5", "4294967296", "abc", ""):
            with self.subTest(bad=bad), patch.object(app, "get_model") as load:
                with self.assertRaises(app.gr.Error) as ctx:
                    list(app.design_candidates("a calm voice", "Merhaba.", "Hızlı", "11", bad, "33", "44", {}, *SEL))
                msg = str(ctx.exception)
                self.assertIn("Aday 2", msg)
                self.assertIn("4294967295", msg)
                self.assertIn("sıfır ya da pozitif bir tam sayı", msg)  # Hızlı Mod'daki kuralla aynı dil
                load.assert_not_called()
            with self.subTest(tek=bad), patch.object(app, "get_model") as load:
                with self.assertRaises(app.gr.Error):
                    list(app.regenerate_candidate(2, "a calm voice", "Merhaba.", "Hızlı", bad, {}, None, *SEL))
                load.assert_not_called()

    def test_user_seeds_are_used_in_order(self):
        with patch.object(app, "_seed_everything") as seeder:
            final = self.four(("11", "123", "0", "4294967295"))
        self.assertEqual([c.args[0] for c in seeder.call_args_list], [11, 123, 0, 4294967295])
        self.assertEqual([final[9][str(i)]["seed"] for i in range(4)], [11, 123, 0, 4294967295])
        self.assertIn("seed 123", final[5])

    def test_same_description_sentence_and_seed_give_the_same_voice(self):
        a = self.four(("5", "6", "7", "8"))
        b = self.four(("5", "6", "7", "8"))
        for i in range(4):
            self.assertTrue(np.array_equal(sf.read(a[i])[0], sf.read(b[i])[0]), f"aday {i + 1}")
        self.assertFalse(np.array_equal(sf.read(a[0])[0], sf.read(a[1])[0]))  # farklı seed → farklı ses

    def test_regenerate_one_candidate_keeps_the_others(self):
        final = self.four()
        cands = final[9]
        eski = {k: dict(v) for k, v in cands.items()}
        self.model.generate.reset_mock()
        with patch.object(app, "_seed_everything", wraps=app._seed_everything) as seeder:
            outs = list(app.regenerate_candidate(1, "a calm voice", "Merhaba.", "Hızlı", " 999 ", cands, None, *SEL))
        seeder.assert_called_once_with(999)
        self.assertEqual(self.model.generate.call_count, 1)  # yalnız bu aday
        self.assertIn("üretiliyor", outs[0][1])
        self.assertIn("Diğer adaylar değişmez", outs[0][2])
        audio, label, status, yeni, save_vis, picked = outs[-1]
        self.assertTrue(Path(audio).is_file())
        self.assertRegex(label, r"^Aday 2 · seed 999 · \d+\.\d saniye$")
        self.assertRegex(status, r"^Tamamlandı: Aday 2, seed 999, \d+\.\d saniye\.")
        self.assertEqual(yeni["1"]["seed"], 999)
        self.assertEqual(yeni["1"]["yol"], audio)
        for k in ("0", "2", "3"):
            self.assertEqual(yeni[k], eski[k])
        # Seçili değildi: kaydet grubu ve seçim olduğu gibi kalır (gr.update()).
        self.assertEqual(save_vis, app.gr.update())
        self.assertEqual(picked, app.gr.update())
        # Aynı seed ile yeniden üretmek aynı sesi verir (tekrarlanabilirlik).
        tekrar = list(app.regenerate_candidate(1, "a calm voice", "Merhaba.", "Hızlı", "999", yeni, None, *SEL))[-1]
        self.assertTrue(np.array_equal(sf.read(audio)[0], sf.read(tekrar[0])[0]))

    def test_regenerating_the_picked_candidate_clears_the_pick(self):
        cands = self.four()[9]
        _a, _l, _s, _c, save_vis, picked = list(
            app.regenerate_candidate(0, "a calm voice", "Merhaba.", "Hızlı", "77", cands, 0, *SEL))[-1]
        self.assertEqual(save_vis, app.gr.update(visible=False))
        self.assertIsNone(picked)
        _a, _l, _s, _c, save_vis, picked = list(
            app.regenerate_candidate(1, "a calm voice", "Merhaba.", "Hızlı", "78", cands, 0, *SEL))[-1]
        self.assertEqual((save_vis, picked), (app.gr.update(), app.gr.update()))

    def test_failed_regeneration_keeps_old_audio_and_label(self):
        cands = self.four()[9]
        self.model.generate.side_effect = RuntimeError("bozuk")
        with patch.object(app.hata_raporu, "record_error", return_value={"reason": "x", "code": "diger"}):
            audio, label, status, yeni, _v, _p = list(
                app.regenerate_candidate(2, "a calm voice", "Merhaba.", "Hızlı", "5", cands, None, *SEL))[-1]
        self.assertEqual(audio, app.gr.update())  # eski ses kartta kalır
        self.assertRegex(label, r"^Aday 3 · seed 33 · ")  # etiket eski sesin seed'ini gösterir
        self.assertIn("Üretim başarısız", status)
        self.assertEqual(yeni["2"], cands["2"])

    def test_pick_and_save_use_the_real_seed_of_the_candidate(self):
        cands = self.four()[9]
        yeni = list(app.regenerate_candidate(1, "a calm voice", "Merhaba.", "Hızlı", "4294967295", cands, None,
                                             *SEL))[-1][3]
        index, _vis, md = app.pick_candidate_ui(1, yeni)
        self.assertIn("seed 4294967295", md)
        _v, new_id, _t, _m = app.save_designed_ui("Büyük Seed", "", "Masal", index, yeni)
        voice = vl.get_voice(new_id)
        self.assertEqual(voice["seed"], 4294967295)
        self.assertEqual(Path(voice["ref_wav"]).read_bytes(), Path(yeni["1"]["yol"]).read_bytes())
        # Kutudaki seed sonradan değişse de (yeniden üretilmeden) kaydedilen, üretilen adayın seed'idir.
        index, _vis, md = app.pick_candidate_ui(2, yeni)
        self.assertIn("seed 33", md)
        _v, other_id, _t, _m = app.save_designed_ui("Üçüncü", "", "Masal", index, yeni)
        self.assertEqual(vl.get_voice(other_id)["seed"], 33)

    def test_candidate_panel_has_seed_boxes_and_regenerate_buttons(self):
        demo = app.build_app()
        comps = demo.config["components"]
        seeds = [c["props"] for c in comps if "sv-seed" in (c["props"].get("elem_classes") or [])]
        self.assertEqual([s["value"] for s in seeds[:4]], ["11", "22", "33", "44"])  # TR sayfası
        self.assertTrue(all(s["label"] == "Seed" and s["max_length"] == 10 for s in seeds[:4]))
        regen = [c for c in comps if "sv-cand-regen" in (c["props"].get("elem_classes") or [])]
        self.assertEqual(len(regen) % 4, 0)
        self.assertEqual(regen[0]["props"]["value"], "Yeniden üret")
        # Aday oynatıcıları sade: indirme/paylaş düğmesi yok.
        audios = [c["props"] for c in comps if c.get("type") == "audio"
                  and "sv-cand-audio" in (c["props"].get("elem_classes") or [])]
        self.assertTrue(audios and all(not a.get("buttons") for a in audios))


if __name__ == "__main__":
    unittest.main()
