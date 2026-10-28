"""Arayüz dili (i18n): çeviri sözlükleri, kalıp eşleme, dil sayfaları ve dil tercihi."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import i18n  # noqa: E402


class CatalogTests(unittest.TestCase):
    def test_eleven_languages_turkish_default(self):
        self.assertEqual(list(i18n.LANGUAGES)[0], "tr")
        self.assertEqual(i18n.DEFAULT, "tr")
        self.assertEqual(set(i18n.LANGUAGES),
                         {"tr", "en", "es", "zh", "hi", "ar", "fr", "pt", "ru", "de", "ja"})
        self.assertEqual(i18n.RTL, frozenset({"ar"}))

    def test_every_locale_covers_every_source_text(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import i18n_anahtarlar
        keys = i18n_anahtarlar.collect()
        self.assertGreater(len(keys), 250)
        stored = json.loads((ROOT / "locales" / "_kaynak.json").read_text(encoding="utf-8"))
        self.assertEqual(set(stored), set(keys), "locales/_kaynak.json eski: python tools/i18n_anahtarlar.py çalıştırın")
        self.assertTrue(i18n_anahtarlar.check(keys), "eksik/uyumsuz çeviri var (--check çıktısına bakın)")

    def test_t_falls_back_and_formats(self):
        self.assertEqual(i18n.t("Üret", "tr"), "Üret")
        self.assertEqual(i18n.t("Üret", "en"), "Generate")
        self.assertEqual(i18n.t("bilinmeyen kaynak metin", "ja"), "bilinmeyen kaynak metin")
        self.assertEqual(i18n.t("Kaydedildi: **{ad}**.", "de", ad="X"), "Gespeichert: **X**.")
        # text/lang konumsal: {text} yer tutucusu kwargs olarak verilebilir.
        self.assertIn("_hi_", i18n.t("**Rastgele ses** · Üretilecek: _{text}_", "en", text="hi"))

    def test_tr_message_translates_helper_templates(self):
        # audio_prep'in f-string uyarısı ({duration:.1f}) kalıpla eşlenir.
        msg = "Kayıt 5.2 sn; en az 8 sn olmalı."
        self.assertEqual(i18n.tr_message(msg, "en"), "The recording is 5.2 s; it must be at least 8 s.")
        self.assertEqual(i18n.tr_message(msg, "tr"), msg)
        # voice_designer: yer tutucuya düşen grup adı da çevrilir.
        out = i18n.tr_message("Ses dokusu için en fazla 2 seçim kullanıldı.", "en")
        self.assertEqual(out, "At most 2 choices were used for Voice texture.")
        self.assertEqual(i18n.tr_message("Bu adla bir ses zaten var.", "fr"), "Une voix porte déjà ce nom.")

    def test_language_preference_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ayarlar.json"
            old = os.environ.get("SESVER_AYARLAR")
            os.environ["SESVER_AYARLAR"] = str(path)
            old_sys = os.environ.get(i18n.SYSTEM_LANG_ENV)
            os.environ[i18n.SYSTEM_LANG_ENV] = "tr-TR"  # dosya yokken sistem dili belirler
            try:
                self.assertIsNone(i18n.stored_language())
                self.assertEqual(i18n.saved_language(), "tr")
                i18n.set_lang("ar")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["arayuz_dili"], "ar")
                self.assertEqual(i18n.saved_language(), "ar")
                self.assertTrue(i18n.is_rtl())
                self.assertEqual(i18n.page_path("ar"), "ar")
                self.assertEqual(i18n.page_path("tr"), "")
                self.assertEqual(i18n.normalize("pt-BR"), "pt")
                self.assertEqual(i18n.normalize("xx"), "tr")
            finally:
                i18n.set_lang("tr", persist=False)
                if old_sys is None:
                    os.environ.pop(i18n.SYSTEM_LANG_ENV, None)
                else:
                    os.environ[i18n.SYSTEM_LANG_ENV] = old_sys
                if old is None:
                    os.environ.pop("SESVER_AYARLAR", None)
                else:
                    os.environ["SESVER_AYARLAR"] = old


class SystemLanguageTests(unittest.TestCase):
    """İlk açılış dili: kayıtlı tercih yoksa işletim sisteminin dili (desteklenmiyorsa en)."""

    @staticmethod
    def _mac(first):
        out = f'(\n    "{first}",\n    "tr-TR"\n)\n'
        return lambda cmd: out if cmd[-1] == "AppleLanguages" else ""

    def test_macos_apple_languages_first_item(self):
        cases = {"tr-TR": "tr", "en-GB": "en", "de-DE": "de", "pt-BR": "pt",
                 "zh-Hans-CN": "zh", "ja-JP": "ja", "ar-SA": "ar", "xx": "en", "ko-KR": "en"}
        for given, want in cases.items():
            with self.subTest(given=given):
                got = i18n.system_language(env={}, runner=self._mac(given), platform="darwin")
                self.assertEqual(got, want)
        # Tırnaksız öğe biçimi de okunur (defaults basit dizgeleri tırnaksız yazar).
        self.assertEqual(i18n.system_language(env={}, runner=lambda c: "(\n    fr,\n    en\n)", platform="darwin"), "fr")

    def test_windows_ui_language(self):
        for given, want in {"tr_TR": "tr", "en_GB": "en", "de_DE": "de", "pt_BR": "pt",
                            "zh_CN": "zh", "xx_XX": "en"}.items():
            with self.subTest(given=given):
                self.assertEqual(i18n.system_language(env={}, platform="win32", windows_ui=lambda: given), want)

    def test_env_fallbacks_and_defaults(self):
        empty = lambda cmd: ""  # noqa: E731 — AppleLanguages okunamadı
        self.assertEqual(i18n.system_language(env={"LANG": "tr_TR.UTF-8"}, runner=empty, platform="darwin"), "tr")
        self.assertEqual(i18n.system_language(env={"LC_ALL": "es_ES.UTF-8", "LANG": "tr_TR.UTF-8"},
                                              platform="linux"), "es")
        self.assertEqual(i18n.system_language(env={"LANG": "C.UTF-8"}, platform="linux"), "en")
        self.assertEqual(i18n.system_language(env={}, runner=empty, platform="darwin"), "en")
        # Test ortam değişkeni her şeyden önce gelir.
        self.assertEqual(i18n.system_language(env={i18n.SYSTEM_LANG_ENV: "ru-RU"}, runner=self._mac("en-US"),
                                              platform="darwin"), "ru")
        self.assertEqual(i18n.match("zh-Hans-CN"), "zh")
        self.assertIsNone(i18n.match("xx"))

    def _with_settings(self, content, system):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "ayarlar.json"
        if content is not None:
            path.write_text(content, encoding="utf-8")
        from unittest import mock
        patcher = mock.patch.dict(os.environ, {"SESVER_AYARLAR": str(path), i18n.SYSTEM_LANG_ENV: system})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_first_run_uses_system_language(self):
        for system, want in {"en-US": "en", "tr-TR": "tr", "de-DE": "de", "xx": "en"}.items():
            with self.subTest(system=system):
                self._with_settings(None, system)
                self.assertIsNone(i18n.stored_language())
                self.assertEqual(i18n.saved_language(), want)
        # Dosya var ama dil kaydı yok (ör. başka ayarlar) → yine sistem dili.
        self._with_settings('{"baska": 1}', "pt-BR")
        self.assertEqual(i18n.saved_language(), "pt")

    def test_saved_preference_wins_over_system_language(self):
        self._with_settings('{"arayuz_dili": "tr"}', "en-US")
        self.assertEqual(i18n.stored_language(), "tr")
        self.assertEqual(i18n.saved_language(), "tr")
        self._with_settings('{"arayuz_dili": "ja"}', "de-DE")
        self.assertEqual(i18n.saved_language(), "ja")


class AppPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app = app
        cls.demo = app.build_app()

    def test_one_page_per_language(self):
        paths = {p[0] for p in self.demo.pages}
        self.assertEqual(paths, {""} | {c for c in i18n.LANGUAGES if c != "tr"})

    def test_pages_have_translated_labels(self):
        labels = {c["props"].get("label") for c in self.demo.config["components"]}
        for label in ("Ses Kütüphanesi", "Voice Library", "Biblioteca de voces", "音色库", "مكتبة الأصوات",
                      "ボイスライブラリ", "Библиотека голосов", "Stimmbibliothek", "आवाज़ लाइब्रेरी"):
            self.assertIn(label, labels)
        # API adları Türkçe (kök) sayfada değişmeden kalır.
        apis = [d.get("api_name") for d in self.demo.config["dependencies"]]
        self.assertIn("generate_audio", apis)
        self.assertIn("clone_audio", apis)

    def test_choice_values_stay_turkish(self):
        with i18n.use("en"):
            self.assertIn(("Calm", "Sakin"), self.app._choices(self.app.EMOTIONS))
            self.assertEqual(self.app._whisper_language(), None)
        self.assertEqual(self.app._whisper_language(), "tr")

    def test_server_messages_follow_page_language(self):
        with i18n.use("es"):
            with self.assertRaises(Exception) as ctx:
                self.app.save_fx_preset_ui(self.app.RANDOM_VOICE)
            self.assertIn("preajuste", str(ctx.exception))
        md = self.app._in_lang(self.app._mode_info, "ja")(self.app.RANDOM_VOICE, "Nötr", "")
        self.assertIn("ランダムな声", md)

    def test_desktop_opens_saved_language_and_guide_is_translated(self):
        from unittest import mock
        import desktop
        import hata_rehberi
        with mock.patch.object(i18n, "saved_language", return_value="ja"):
            self.assertEqual(desktop._ui_url("http://127.0.0.1:7860"), "http://127.0.0.1:7860/ja")
        with mock.patch.object(i18n, "saved_language", return_value="tr"):
            self.assertEqual(desktop._ui_url("http://127.0.0.1:7860"), "http://127.0.0.1:7860")
        # İlk açılış (ayarlar.json yok): masaüstü penceresi sistem dilinin sayfasını açar.
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
                os.environ, {"SESVER_AYARLAR": str(Path(tmp) / "ayarlar.json"), i18n.SYSTEM_LANG_ENV: "en-US"}):
            self.assertEqual(desktop._ui_url("http://127.0.0.1:7860"), "http://127.0.0.1:7860/en")
            self.assertIn("(sistem dili)", desktop._language_note("http://127.0.0.1:7860"))
        with i18n.use("en"):
            self.assertTrue(hata_rehberi.smart_app_control_rehberi("Application Control").startswith("This error"))
        self.assertTrue(hata_rehberi.smart_app_control_rehberi("uygulama denetimi").startswith("Bu hata"))


if __name__ == "__main__":
    unittest.main()
