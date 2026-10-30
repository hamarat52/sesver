"""⚡ Hızlı Mod sekmesi (app.py arayüz katmanı) — EMA motoru ve kurulum taklit edilir."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf

import app
import hata_raporu
from engines import ema


def _status(ready=True, deps=True):
    return SimpleNamespace(ready=ready, dependencies_ok=deps, missing_dependencies=() if deps else ("torch>=2.1",))


class FakeEngine:
    def __init__(self, out, fail=None):
        self.out, self.fail, self.calls = Path(out), fail, []

    def synthesize(self, text, speed=1.0, seed=None, srt=None):
        self.calls.append(dict(text=text, speed=speed, seed=seed, srt=srt))
        if self.fail:
            raise self.fail
        path = self.out / f"{ema.OUTPUT_PREFIX}test.wav"
        sf.write(str(path), np.full(24000, 0.1, dtype=np.float32), 48000, subtype="PCM_16")
        srt_path = None
        if srt:
            srt_path = str(path.with_suffix(".srt"))
            Path(srt_path).write_text("1\n00:00:00,000 --> 00:00:00,500\nmerhaba\n", encoding="utf-8")
        return SimpleNamespace(path=str(path), sample_rate=48000,
                               meta={"duration": 0.5, "seed": 7 if seed is None else seed, "srt_path": srt_path})


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(app.ema_motor, "ema_status", return_value=_status())
        p.start()
        self.addCleanup(p.stop)

    def run_gen(self, engine, *args, lang="tr"):
        with patch.object(app, "_fast_engine", return_value=engine):
            return list(app._fast_generate_ui(*args, lang))

    def test_success_writes_ai_labelled_wav_and_optional_srt(self):
        eng = FakeEngine(self.tmp.name)
        steps = self.run_gen(eng, "Merhaba dünya.", 1.25, None, True)
        audio, download, srt_file, status = steps[-1]
        self.assertTrue(Path(audio).name.startswith("ai-ile-uretildi-"))
        self.assertEqual(download, audio)
        self.assertGreater(sf.info(audio).duration, 0)
        self.assertTrue(srt_file["visible"])
        self.assertTrue(srt_file["value"].endswith(".srt"))
        self.assertIn("AI ile üretildi", status)
        self.assertIn("seed 7", status)
        self.assertEqual(eng.calls[-1], dict(text="Merhaba dünya.", speed=1.25, seed=None, srt=True))
        steps = self.run_gen(eng, "Merhaba.", 1.0, 42, False)
        self.assertFalse(steps[-1][2]["visible"])            # SRT istenmedi -> gizli
        self.assertEqual(eng.calls[-1]["seed"], 42)

    def test_validation(self):
        eng = FakeEngine(self.tmp.name)
        for args in (("  ", 1.0, None, False), ("Merhaba", 1.0, -3, False)):
            with self.subTest(args=args), self.assertRaises(app.gr.Error):
                self.run_gen(eng, *args)
        with self.assertRaises(app.gr.Error):
            self.run_gen(eng, "x" * (ema.MAX_TEXT_CHARS + 1), 1.0, None, False)
        with patch.object(app.ema_motor, "ema_status", return_value=_status(ready=False)), \
                self.assertRaises(app.gr.Error):
            self.run_gen(eng, "Merhaba", 1.0, None, False)
        self.assertEqual(eng.calls, [])

    def test_failure_goes_to_error_report_without_user_text(self):
        before = hata_raporu.error_count()
        eng = FakeEngine(self.tmp.name, fail=MemoryError("bellek bitti"))
        status = self.run_gen(eng, "Gizli kullanıcı metni", 1.0, None, False)[-1][3]
        self.assertEqual(hata_raporu.error_count(), before + 1)   # "Hata raporu gönder" düğmesi açılır
        self.assertIn("Hata raporu gönder", status)
        last = hata_raporu.last_error()
        self.assertEqual(last["where"], "hizli_mod")
        self.assertNotIn("Gizli kullanıcı metni", last["traceback"] + last["message"])

    def test_messages_follow_page_language(self):
        status = self.run_gen(FakeEngine(self.tmp.name), "Merhaba.", 1.0, 3, False, lang="en")[-1][3]
        self.assertIn("AI-generated", status)


class InstallRemoveTests(unittest.TestCase):
    def test_install_success_shows_ready_view(self):
        def fake_install(progress_cb, cancel):
            progress_cb(ema.InstallProgress("paket", 0.02, ""))
            progress_cb(ema.InstallProgress("indirme", 0.5, "", file="ema.pt", done_bytes=17_000_000,
                                            total_bytes=34_000_000))
            progress_cb(ema.InstallProgress("dogrulama", 0.99, ""))
            return _status()
        with patch.object(app.ema_motor, "ema_install", fake_install):
            steps = list(app._fast_install_ui("tr"))
        texts = [s[0] for s in steps]
        self.assertTrue(any("17.0 / 34.0 MB (50%)" in x for x in texts), texts)
        self.assertTrue(any("SHA-256" in x for x in texts))
        last = steps[-1]
        self.assertIn("Hızlı Mod hazır", last[0])
        self.assertFalse(last[2]["visible"])                 # iptal düğmesi gizlenir
        self.assertFalse(last[3]["visible"])                 # kurulum sütunu gizli
        self.assertTrue(last[4]["visible"])                  # üretim sütunu görünür
        self.assertFalse(app._fast_lock.locked())

    def test_install_cancel_and_network_error(self):
        def cancelled(progress_cb, cancel):
            raise ema.InstallCancelledError("iptal")
        before = hata_raporu.error_count()
        with patch.object(app.ema_motor, "ema_install", cancelled):
            last = list(app._fast_install_ui("tr"))[-1]
        self.assertIn("iptal edildi", last[0])
        self.assertEqual(hata_raporu.error_count(), before)  # iptal hata sayılmaz

        def offline(progress_cb, cancel):
            raise ema.EmaNetworkError("ağ yok")
        with patch.object(app.ema_motor, "ema_install", offline):
            last = list(app._fast_install_ui("tr"))[-1]
        self.assertIn("internet bağlantınızı", last[0])
        self.assertEqual(hata_raporu.error_count(), before + 1)
        self.assertFalse(app._fast_lock.locked())

    def test_cancel_sets_event(self):
        app._fast["cancel"].clear()
        app._fast_cancel_ui("tr")
        self.assertTrue(app._fast["cancel"].is_set())
        app._fast["cancel"].clear()

    def test_remove_uninstalls_weights_and_packages(self):
        calls = []

        def fake_uninstall(**kw):
            calls.append(kw)
            return {"removed": ["ema.pt"], "freed_bytes": 34_389_489, "weights_dir": "x",
                    "packages_removed": ["ema-lightning", "normalizer-tr"]}
        with patch.object(app.ema_motor, "ema_uninstall", fake_uninstall):
            msg, setup, ready = app._fast_remove_ui("tr")
        self.assertEqual(calls, [{"packages": True}])
        self.assertIn("34,4 MB", msg)
        self.assertTrue(setup["visible"])
        self.assertFalse(ready["visible"])

    def test_refresh_reports_missing_dependencies(self):
        with patch.object(app.ema_motor, "ema_status", return_value=_status(ready=False, deps=False)):
            setup, ready, note, install = app._fast_refresh_ui("tr")
        self.assertTrue(setup["visible"])
        self.assertFalse(install["interactive"])
        self.assertIn("torch&gt;=2.1", note)   # Markdown'a kaçışlı yazılır


class LayoutTests(unittest.TestCase):
    def test_tab_on_every_language_page(self):
        demo = app.build_app()
        labels = [c["props"].get("label") for c in demo.config["components"] if c.get("type") == "tabitem"]
        self.assertEqual(labels.count("Hızlı Mod"), 1)
        self.assertIn("Fast Mode", labels)
        self.assertIn("高速モード", labels)
        api = {d.get("api_name") for d in demo.config["dependencies"]}
        self.assertIn("fast_audio", api)


if __name__ == "__main__":
    unittest.main()
