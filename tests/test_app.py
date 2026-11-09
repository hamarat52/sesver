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

    def test_cuda_kernel_error_falls_back_to_cpu_once_with_notice(self):
        """Blackwell + eski cu126 gibi durumlar: is_available() True ama ilk işlemde patlar."""
        import app
        from unittest.mock import Mock
        cpu_model = SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),
                                    generate=Mock(return_value=np.zeros(4800, dtype=np.float32)))
        gpu_model = SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),
                                    generate=Mock(side_effect=RuntimeError(
                                        "CUDA error: no kernel image is available for execution on the device")))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(app, "OUTPUT_DIR", Path(directory)), \
                patch.object(app, "_gpu_disabled", False), \
                patch.object(app, "get_model", side_effect=[gpu_model, cpu_model]) as load:
            events = list(app.generate_audio("Merhaba.", None))
            self.assertEqual(load.call_count, 2)  # GPU denemesi + CPU'ya tek seferlik yeniden yükleme
            self.assertTrue(app._gpu_disabled)  # bu oturumda bir daha GPU denenmez
        gpu_model.generate.assert_called_once()
        cpu_model.generate.assert_called_once()
        messages = [e[2] for e in events]
        self.assertTrue(any("işlemciyle devam ediliyor" in m for m in messages))  # tek seferlik bilgi
        self.assertIn("saniye", events[-1][2])  # yeniden denemeden sonra üretim normal tamamlanır
        self.assertIsNotNone(events[-1][0])  # CPU'da üretilen ses de kullanıcıya ulaşır

    def test_gpu_fallback_does_not_retry_in_same_session(self):
        """_gpu_disabled zaten True ise ikinci bir GPU/yeniden-yükleme denemesi yapılmaz."""
        import app
        from unittest.mock import Mock
        model = SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),
                                generate=Mock(side_effect=RuntimeError("CUDA error: out of memory")))
        with patch.object(app, "_gpu_disabled", True), \
                patch.object(app, "get_model", return_value=model) as load:
            last = list(app.generate_audio("Merhaba.", None))[-1]
            load.assert_called_once()  # ikinci bir deneme/yeniden yükleme yok
        self.assertIn("Üretim başarısız", last[2])  # döngüye girmeden normal hata olarak raporlanır

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
        self.assertIn(app.BRAND_SIGNATURE_HTML, app._splash())
        # İmza, kaydırmadan görünen kalıcı üst marka satırında olmalı (açılış ekranı kaybolur).
        nav = app._brand().split('<nav class="sv-nav">', 1)[1].split("</nav>", 1)[0]
        self.assertIn(app.BRAND_SIGNATURE_HTML, nav)
        self.assertIn("HamaratLabs tarafından geliştirildi", app._footer())
        # .sv-brand büyük harfe çevirir; imza yazımı korunmalı (HAMARATLABS olmamalı).
        import re
        sig_rule = re.search(r"(?m)^\.sv-sig \{([^}]*)\}", app._CSS)  # temel kural (satır başı)
        assert sig_rule is not None
        sig_css = sig_rule.group(1)
        self.assertIn("text-transform: none", sig_css)

    def test_brand_spelling_is_consistent(self):
        import re
        import app
        readme = (Path(app.__file__).parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("HamaratLabs tarafından geliştirilmiştir.", readme.splitlines()[:4])
        for source in (app._brand(), app._splash(), app._footer(), readme):
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


# SPLASH_JS'i (gr.HTML js_on_load gövdesi) Node'da sahte DOM ile çalıştırır: depolama, zamanlayıcı
# ve olay dinleyicileri taklit edilir; her senaryonun sonucu JSON olarak döner.
_SPLASH_HARNESS = r"""
const SPLASH_JS = process.env.SV_SPLASH_JS;
const scenarios = JSON.parse(process.env.SV_SCENARIOS);
const out = [];
const shared = {};
for (const sc of scenarios) {
  const store = sc.fresh ? {} : shared;
  const mkStorage = (broken) => ({
    getItem(k) { if (broken) throw new Error('denied'); return k in store ? store[k] : null; },
    setItem(k, v) { if (broken) throw new Error('denied'); store[k] = String(v); },
  });
  const listeners = {};
  const timers = [];
  const win = {
    localStorage: mkStorage(sc.noLocal), sessionStorage: mkStorage(false),
    matchMedia: () => ({ matches: !!sc.reduced }),
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener(ev, fn) { listeners[ev] = (listeners[ev] || []).filter((f) => f !== fn); },
  };
  const cls = new Set();
  let removed = false;
  const s = { dataset: { boot: sc.boot }, classList: { add: (c) => cls.add(c) },
              style: { setProperty() {} }, remove() { removed = true; } };
  const element = { querySelector: (q) => (q === '.sv-splash' ? s : null) };
  const setT = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };
  new Function('element', 'window', 'setTimeout', 'clearTimeout', SPLASH_JS)(element, win, setT, () => {});
  const r = { removedAtOnce: removed, classes: [...cls], listeners: Object.keys(listeners).filter((k) => listeners[k].length),
              hold: timers.length ? timers[0].ms : null };
  if (sc.action === 'skip' && listeners.keydown) listeners.keydown[0]();
  if (sc.action === 'wait' && timers.length) timers[0].fn();
  if (sc.action) {
    r.afterClasses = [...cls];
    r.removeDelay = timers.length > 1 ? timers[timers.length - 1].ms : null;
    timers.slice(1).forEach((t) => t.fn());
    r.removedAtEnd = removed;
    r.listenersLeft = Object.keys(listeners).filter((k) => listeners[k].length);
  }
  r.stored = store['sesver-acilis'] || null;
  out.push(r);
}
console.log(JSON.stringify(out));
"""


class SplashTests(unittest.TestCase):
    """Açılış ekranı: büyük karşılama panelde kalıcı değil; uygulama açılışı başına bir kez oynar."""

    def _run_js(self, scenarios):
        import json
        import os
        import shutil
        import subprocess
        import app
        node = shutil.which("node")
        if not node:
            self.skipTest("node yok; açılış betiği davranış testi atlandı")
        env = dict(os.environ, SV_SPLASH_JS=app.SPLASH_JS, SV_SCENARIOS=json.dumps(scenarios))
        proc = subprocess.run([node, "-"], input=_SPLASH_HARNESS, env=env,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_plays_once_per_app_start_and_not_on_reload_or_language_change(self):
        first, reload_, other_lang, new_start = self._run_js([
            {"boot": "aaa"},  # ilk açılış (ortak depo başta boş)
            {"boot": "aaa"},  # aynı sunucu: sayfa yenileme
            {"boot": "aaa"},  # aynı sunucu: başka dil sayfası (/en, /ar …) aynı kimliği taşır
            {"boot": "bbb"},  # uygulama yeniden açıldı: yeni kimlik
        ])
        self.assertFalse(first["removedAtOnce"])
        self.assertIn("is-on", first["classes"])
        self.assertEqual(first["stored"], "aaa")
        for again in (reload_, other_lang):
            self.assertTrue(again["removedAtOnce"])
            self.assertNotIn("is-on", again["classes"])
            self.assertEqual(again["listeners"], [])
        self.assertIn("is-on", new_start["classes"])
        self.assertEqual(new_start["stored"], "bbb")

    def test_ends_by_itself_or_on_skip_and_cleans_up(self):
        import app
        waited, skipped = self._run_js([
            {"boot": "x", "fresh": True, "action": "wait"},
            {"boot": "y", "fresh": True, "action": "skip"},
        ])
        self.assertEqual(waited["hold"], app.SPLASH_HOLD_MS)
        self.assertLessEqual(app.SPLASH_HOLD_MS, 2500)  # kullanıcıyı bekletmez
        self.assertEqual(set(waited["listeners"]), {"pointerdown", "keydown", "wheel", "touchstart"})
        self.assertIn("is-out", waited["afterClasses"])
        self.assertIn("is-skip", skipped["afterClasses"])
        self.assertLess(skipped["removeDelay"], waited["removeDelay"])  # geçince daha çabuk kaybolur
        for r in (waited, skipped):
            self.assertTrue(r["removedAtEnd"])
            self.assertEqual(r["listenersLeft"], [])

    def test_reduced_motion_and_storage_fallback(self):
        import app
        reduced, no_local = self._run_js([
            {"boot": "r", "fresh": True, "reduced": True},
            {"boot": "s", "fresh": True, "noLocal": True},
        ])
        self.assertIn("is-still", reduced["classes"])
        self.assertEqual(reduced["hold"], app.SPLASH_HOLD_STILL_MS)
        self.assertLess(app.SPLASH_HOLD_STILL_MS, app.SPLASH_HOLD_MS)
        # localStorage kapalıysa sessionStorage'a yazılır (sekme içinde yine bir kez).
        self.assertEqual(no_local["stored"], "s")
        css = app._CSS
        self.assertRegex(css, r"\.sv-splash \{ display: none;")  # betik çalışmazsa hiç görünmez
        self.assertIn(".sv-splash.is-on { display: grid; }", css)
        self.assertRegex(css, r"@media \(prefers-reduced-motion: reduce\) \{\s*\.sv-splash, \.sv-splash \*")

    def test_splash_markup_is_decorative_and_rtl_aware(self):
        import app
        html = app._splash()
        self.assertIn(f'data-boot="{app.SPLASH_BOOT_ID}"', html)
        self.assertIn('aria-hidden="true"', html)
        self.assertIn("<h1>", html)
        self.assertNotIn('dir="rtl"', html)
        with app.i18n.use("ar"):
            self.assertIn('dir="rtl"', app._splash())

    def test_pages_have_no_permanent_hero(self):
        import asyncio
        import app

        async def construct():
            return app.build_app()

        with patch.object(app, "get_model"):
            demo = asyncio.run(construct())
        htmls = [c for c in demo.config["components"] if c.get("type") == "html"]
        hosts = [c for c in htmls if "sv-splash-host" in (c["props"].get("elem_classes") or [])]
        self.assertGreaterEqual(len(hosts), 1)
        for host in hosts:
            self.assertEqual(host["props"].get("js_on_load"), app.SPLASH_JS)
        # Büyük başlık yalnız açılış ekranında; panelde kalıcı karşılama bölümü yok.
        for c in htmls:
            if c in hosts:
                continue
            value = str(c["props"].get("value") or "")
            self.assertNotIn("sv-hero", value)
            self.assertNotIn("<h1>", value)
        brands = [c for c in htmls if "sv-brandbar" in (c["props"].get("elem_classes") or [])]
        self.assertEqual(len(brands), len(hosts))  # her sayfada küçük kalıcı marka


if __name__ == "__main__":
    unittest.main()
