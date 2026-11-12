"""1.4.1: ilk üretim iletisi modelin gerçek durumuna göre, ham ilerleme satırı yok, indirme ilerlemesi anlamlı.

Model yüklenmez: get_model ve önbellek denetimi taklit edilir.
"""
import contextlib
import io
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

import app
import i18n

ROOT = Path(__file__).resolve().parent.parent


def fake_model():
    return SimpleNamespace(tts_model=SimpleNamespace(sample_rate=16000),
                           generate=Mock(side_effect=lambda **kw: np.zeros(1600, dtype=np.float32)))


class FirstGenerationMessageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.model = fake_model()
        self.patches = [patch.object(app, "OUTPUT_DIR", Path(self.tmp.name)),
                        patch.object(app, "_model", None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def messages(self, diskte, run=None):
        with patch.object(app, "_model_diskte", return_value=diskte), \
                patch.object(app, "get_model", return_value=self.model):
            run = run or (lambda: app.generate_audio("Merhaba.", None))
            return [m[2] for m in run()]

    def test_model_on_disk_says_loading_not_downloading(self):
        msgs = self.messages(True)
        self.assertIn("belleğe yükleniyor", msgs[1])
        self.assertIn("indirme yapılmaz", msgs[1])
        for m in msgs:
            self.assertNotIn("indiriliyor", m)
            self.assertNotIn("indirilecek", m)
            self.assertNotIn("internet", m)
        self.assertRegex(msgs[-1], r"^Tamamlandı: \d+\.\d saniye\. AI ile üretildi\.$")

    def test_model_missing_says_one_time_download_with_size(self):
        msgs = self.messages(False)
        self.assertIn("bir kez indirilecek", msgs[1])
        self.assertIn("yaklaşık 5 GB", msgs[1])
        self.assertIn("internet gerekir", msgs[1])

    def test_unknown_cache_state_does_not_claim_a_download(self):
        msgs = self.messages(None)  # önbellek okunamadı
        self.assertIn("belleğe yükleniyor", msgs[1])

    def test_model_in_memory_shows_no_loading_message(self):
        with patch.object(app, "_model", self.model):
            msgs = self.messages(True)
        self.assertEqual(msgs[1], "İşleniyor…")
        self.assertFalse(any("yükleniyor" in m or "indiril" in m for m in msgs))

    def test_all_generation_paths_use_the_same_message(self):
        sel = ["Erkek", "Yaşlı", "Masal", 2, "Sıcak", [], 2, 2]
        ref = Path(self.tmp.name) / "ref.wav"
        import soundfile as sf
        sf.write(ref, np.zeros(16000 * 2, dtype=np.float32), 16000)
        yollar = {
            "normal": lambda: app.library_generate("Merhaba.", "Nötr", "Dengeli", app.RANDOM_VOICE),
            "klon": lambda: app._clone_generate("Merhaba.", str(ref), "Nötr", ""),
            "tarif/adaylar": lambda: (o[8:9] * 3 for o in app.design_candidates(
                "a calm voice", "Merhaba.", "Hızlı", "11", "22", "33", "44", {}, *sel)),
        }
        for ad, run in yollar.items():
            with self.subTest(yol=ad):
                yuklu = " ".join(self.messages(True, run))
                eksik = " ".join(self.messages(False, run))
                self.assertIn("belleğe yükleniyor", yuklu)
                self.assertNotIn("indirilecek", yuklu)
                self.assertIn("bir kez indirilecek", eksik)

    def test_queue_uses_the_same_cache_decision(self):
        for diskte, beklenen in ((True, True), (False, False), (None, True)):
            with patch.object(app, "_model_diskte", return_value=diskte):
                self.assertEqual(app._kuyruk_ortam()[1], beklenen, diskte)
        with patch.object(app, "_model", self.model), patch.object(app, "_model_diskte", return_value=False):
            self.assertTrue(app._kuyruk_ortam()[1])

    def test_cache_check_uses_the_pinned_revision(self):
        calls = []

        def fake(repo, name, revision=None):
            calls.append((repo, name, revision))
            return f"/cache/{name}"

        with patch("huggingface_hub.try_to_load_from_cache", side_effect=fake):
            self.assertTrue(app._model_diskte())
        self.assertEqual({c[2] for c in calls}, {app.MODEL_REVISION})
        self.assertEqual({c[1] for c in calls}, set(app._MODEL_DOSYALARI))
        with patch("huggingface_hub.try_to_load_from_cache", side_effect=lambda r, n, revision=None:
                   None if n == "model.safetensors" else "/x"):
            self.assertFalse(app._model_diskte())  # yarım önbellek = yok
        with patch("huggingface_hub.try_to_load_from_cache", side_effect=OSError("izin")):
            self.assertIsNone(app._model_diskte())


class DownloadProgressTests(unittest.TestCase):
    def test_real_download_shows_meaningful_progress(self):
        model = fake_model()

        def slow_download(ilerleme=None):
            ilerleme(1_000_000_000, 4_960_000_000)
            time.sleep(1.3)
            ilerleme(2_480_000_000, 4_960_000_000)
            time.sleep(1.3)
            return model

        with tempfile.TemporaryDirectory() as d, patch.object(app, "OUTPUT_DIR", Path(d)), \
                patch.object(app, "_model", None), patch.object(app, "_model_diskte", return_value=False), \
                patch.object(app, "get_model", side_effect=slow_download):
            msgs = [m[2] for m in app.generate_audio("Merhaba.", None)]
        indirme = [m for m in msgs if m.startswith("Ses modeli indiriliyor:")]
        self.assertTrue(indirme, msgs)
        self.assertRegex(indirme[-1], r"^Ses modeli indiriliyor: \d+\.\d\d / 4\.96 GB \(%\d+\)\. Bu yalnız bir kez olur\.$")
        raw = re.compile(app._HAM_ILERLEME)
        for m in msgs:
            self.assertIsNone(raw.search(m), m)  # kendi iletimiz ham satır süpürgesine takılmaz

    def test_tqdm_class_reports_bytes_and_prints_nothing(self):
        seen = []
        cls = app._indirme_izleyici(lambda n, toplam: seen.append((n, toplam)))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            # huggingface_hub snapshot_download'ın bayt çubuğunu kurduğu biçim (name= dahil).
            bar = cls(desc="Downloading bytes", total=0, initial=0, unit="B", unit_scale=True, name="x")
            bar.total = 1000
            bar.update(400)
            bar.update(600)
            files = cls(desc="Fetching 9 files", total=9)  # dosya sayacı (unit "it"): bildirilmez
            files.update(1)
            bar.close()
            files.close()
        self.assertEqual(seen, [(400, 1000), (1000, 1000)])
        self.assertEqual(out.getvalue() + err.getvalue(), "")

    def test_model_path_passes_tqdm_class_only_when_progress_is_wanted(self):
        with patch("huggingface_hub.snapshot_download", return_value="/m") as dl:
            app._model_yolu()
            self.assertEqual(dl.call_args.kwargs, {"repo_id": app.MODEL_ID, "revision": app.MODEL_REVISION})
            app._model_yolu(lambda n, t: None)
            self.assertTrue(issubclass(dl.call_args.kwargs["tqdm_class"], __import__("tqdm").tqdm))

    def test_generation_handlers_do_not_track_library_tqdm(self):
        import inspect
        for fn in (app.generate_audio, app._normal_generate, app._clone_generate, app.library_generate,
                   app.design_candidates, app.regenerate_candidate):
            fn = inspect.unwrap(fn)
            prog = inspect.signature(fn).parameters["progress"].default
            self.assertFalse(getattr(prog, "track_tqdm", False), fn.__name__)


class RawProgressFilterTests(unittest.TestCase):
    def test_raw_library_progress_is_matched(self):
        raw = re.compile(app._HAM_ILERLEME)
        for s in ("0/0 B | 0/0 B | 6.4s", "0/0 B |", "1.2G/4.96G B |", "523M/4.58G B", "Downloading bytes",
                  "Reconstructing (incomplete total...)", "Fetching 9 files", "3/10 steps", "0/10 it"):
            self.assertIsNotNone(raw.search(s), s)

    def test_our_own_messages_are_not_matched(self):
        raw = re.compile(app._HAM_ILERLEME)
        for lang in i18n.LANGUAGES:
            for key in ("Aday {n}/4 · {msg}", "Ses modeli indiriliyor: {done} / {total} GB (%{pct}). Bu yalnız bir kez olur.",
                        "Aday {n}/4 hazır: {sec} saniye.", "Tamamlandı: 4 aday, toplam {sec} saniye. Birini seçip kaydedin.",
                        "Aday {n} · seed {seed} · {sec} saniye"):
                s = i18n.t(key, lang, n=3, msg="x", done="1.20", total="4.96", pct=24, sec="12.5", seed=4294967295)
                self.assertIsNone(raw.search(s), f"{lang}: {s}")

    def test_sweep_script_uses_the_single_pattern(self):
        self.assertIn(f"new RegExp({json.dumps(app._HAM_ILERLEME)})", app._JS)

    def test_status_message_stays_readable_under_the_progress_indicator(self):
        # Gradio bekleyen çıktıyı %20 opaklığa düşürüp ilerleme yazısını üstüne bindiriyordu: ileti okunmuyordu.
        self.assertIn(".block.sv-status > .pending { opacity: 1 !important; }", app._CSS)
        self.assertIn(".block.sv-status > .wrap { position: relative !important;", app._CSS)
        self.assertNotIn(".block.sv-cand-status > .wrap {", app._CSS)  # genel kural adaylar kutusunu da kapsar


class NoEmDashTests(unittest.TestCase):
    """Bu işte dokunulan ve Adaylar panelinde görünen metinler: bütün dillerde em dash yok."""

    KEYS = [
        "İşleniyor…", "Ses modeli indiriliyor…", "Ses modeli yükleniyor…",
        "İşleniyor… İlk kullanım: ses modeli bir kez indirilecek (yaklaşık {gb} GB, internet gerekir). "
        "Sonraki açılışlarda yalnız yüklenir.",
        "İşleniyor… Ses modeli belleğe yükleniyor. Model bilgisayarınızda kayıtlı; indirme yapılmaz, "
        "birkaç dakika sürebilir.",
        "Ses modeli indiriliyor: {done} / {total} GB (%{pct}). Bu yalnız bir kez olur.",
        "Ses üretiliyor…",
        "Ses üretiliyor… Metninizin uzunluğuna göre tahmini {min}-{max} dakika sürebilir (başka ağır uygulamalar "
        "açıksa daha uzun sürer). **Pencereyi kapatmayın, bu normal**; bittiğinde burada 'Tamamlandı' yazacak.",
        "Ekran kartı bu sürümde kullanılamadı, işlemciyle devam ediliyor; daha yavaş. Ayrıntı: Ayarlar.",
        "Tamamlandı: {sec} saniye. AI ile üretildi.",
        "Adaylar", "Aynı tarif ve cümle, farklı seed. Dinleyin, birini seçin.",
        "Henüz aday yok. Seçimleri yapıp “Sesleri Dene”ye basın.",
        "Aynı tarif, aynı cümle ve aynı seed aynı sesi verir. Bir adayın seed'ini değiştirip “Yeniden üret”e "
        "basın; diğer adaylar değişmez.",
        "Aday {n}", "Aday {n} · seed {seed} · sırada", "Aday {n} · seed {seed} · üretiliyor…",
        "Aday {n} · seed {seed} · başarısız", "Aday {n} · seed {seed} · {sec} saniye", "Aday {n}/4 · {msg}",
        "Aday {n}/4 hazır: {sec} saniye.", "Sıradaki üretiliyor…",
        "Tamamlandı: 4 aday, toplam {sec} saniye. Birini seçip kaydedin.",
        "4 aday sırayla üretilecek (seed {seeds}). İlk aday hazır olunca dinleyebilirsiniz.",
        "Aday {n} yeniden üretiliyor (seed {seed}). Diğer adaylar değişmez.",
        "Tamamlandı: Aday {n}, seed {seed}, {sec} saniye. Diğer adaylar değişmedi.",
        "Aday {n}: seed sıfır ya da pozitif bir tam sayı olmalı (en fazla {en_fazla}).",
        "Seed", "Yeniden üret", "Bunu seç", "Durdur", "4 aday daha", "Seçimleri değiştir",
        "Seçimleri soldan değiştirip yeniden “Sesleri Dene”ye basın; kutulardaki seed'ler kullanılır.",
        "Durduruldu. Çalışmakta olan aday bitene kadar model meşgul kalabilir.",
        "Seçilen: **Aday {n}** (seed {seed}). Ad verip kaydedin.", "Bu aday henüz üretilmedi.",
    ]

    def test_no_em_dash_in_any_language(self):
        for key in self.KEYS:
            self.assertNotIn("—", key)
            for lang in i18n.LANGUAGES:
                value = i18n.catalog(lang).get(key, key)
                self.assertNotIn("—", value, f"{lang}: {key}")
                if lang != i18n.DEFAULT:
                    self.assertIn(key, i18n.catalog(lang), f"{lang} çevirisi yok: {key}")


if __name__ == "__main__":
    unittest.main()
