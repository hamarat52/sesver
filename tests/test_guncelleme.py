"""Sürüm okuma ve "yeni sürüm var" kontrolü — ağ tamamen taklit edilir."""
import io
import json
import socket
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import guncelleme as g
import surum

_AYAR_DIZINI = tempfile.TemporaryDirectory()
_ayar_yamasi = patch.dict("os.environ", {"SESVER_AYARLAR": str(Path(_AYAR_DIZINI.name) / "ayarlar.json")})


def setUpModule():
    # Testler gerçek ayarlar.json'a bağlı olmasın (kullanıcı kontrolü kapatmış olabilir).
    _ayar_yamasi.start()


def tearDownModule():
    _ayar_yamasi.stop()
    _AYAR_DIZINI.cleanup()


def _yanit(**alanlar):
    veri = {"tag_name": "v1.2.0", "draft": False, "prerelease": False,
            "html_url": "https://github.com/hamarat52/sesver/releases/tag/v1.2.0"}
    veri.update(alanlar)
    return lambda url, zaman_asimi: veri


class SurumOkumaTests(unittest.TestCase):
    def test_kokteki_version_dosyasi_okunur(self):
        beklenen = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(surum.__version__, beklenen)
        self.assertIsNotNone(g.surum_parcala(surum.__version__))

    def test_bosluk_bom_ve_bozuk_icerik(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "VERSION"
            p.write_bytes(b"\xef\xbb\xbf 2.3.4 \r\n")
            self.assertEqual(surum.oku(p), "2.3.4")
            p.write_text("v2.3", encoding="utf-8")
            self.assertEqual(surum.oku(p), surum.BILINMEYEN)
            self.assertEqual(surum.oku(Path(d) / "yok"), surum.BILINMEYEN)


class SurumKarsilastirmaTests(unittest.TestCase):
    def test_sayisal_karsilastirma(self):
        self.assertTrue(g.daha_yeni_mi("1.10.0", "1.9.0"))
        self.assertTrue(g.daha_yeni_mi("v2.0.0", "1.99.99"))
        self.assertTrue(g.daha_yeni_mi("1.0.10", "1.0.9"))
        self.assertFalse(g.daha_yeni_mi("1.9.0", "1.10.0"))
        self.assertFalse(g.daha_yeni_mi("v1.0.0", "1.0.0"))
        self.assertFalse(g.daha_yeni_mi("1.0.0-beta", "0.9.0"))
        self.assertFalse(g.daha_yeni_mi(None, "1.0.0"))

    def test_v_oneki_temizlenir(self):
        self.assertEqual(g.surum_parcala("v1.10.3"), (1, 10, 3))
        self.assertEqual(g.surum_parcala(" 1.2.3 "), (1, 2, 3))
        self.assertIsNone(g.surum_parcala("1.2"))


class KontrolTests(unittest.TestCase):
    def test_yeni_surum_bildirimi(self):
        bilgi = g.kontrol_et(yerel="1.0.0", istek=_yanit(tag_name="v1.10.0"))
        self.assertEqual(bilgi, g.YeniSurum("1.10.0", "https://github.com/hamarat52/sesver/releases/tag/v1.2.0"))
        win = g.bildirim_html(bilgi, platform="win32", lang="tr")
        self.assertIn("Yeni sürüm var: v1.10.0", win)
        self.assertIn('href="https://github.com/hamarat52/sesver/releases/tag/v1.2.0"', win)
        self.assertIn("kurulum programını", win)
        self.assertIn("sesleriniz korunur", win)
        mac = g.bildirim_html(bilgi, platform="darwin", lang="tr")
        self.assertIn("Yeni sürüm var: v1.10.0", mac)
        self.assertIn("release sayfasından", mac)
        self.assertNotIn("Kurulum-Windows", mac)

    def test_bildirim_arayuz_dilinde(self):
        bilgi = g.YeniSurum("9.9.9", g.RELEASES_URL)
        en = g.bildirim_html(bilgi, platform="win32", lang="en")
        self.assertIn("New version available: v9.9.9", en)
        self.assertIn("Release page", en)
        self.assertIn("SesVer-Kurulum-Windows.exe", en)
        self.assertNotIn("Yeni sürüm", en)
        ja = g.bildirim_html(bilgi, platform="darwin", lang="ja")
        self.assertIn("v9.9.9", ja)
        self.assertNotIn("Yeni sürüm", ja)

    def test_github_son_surumu_eskiyse_bildirim_cikmaz(self):
        # Kabul kriteri: GitHub'daki son sürüm v1.1.0, yerel VERSION 1.2.0 -> bildirim yok.
        self.assertEqual(surum.__version__, "1.2.0")
        self.assertIsNone(g.kontrol_et(istek=_yanit(tag_name="v1.1.0")))
        # Sahte daha yeni sürümle (v1.3.0) bildirim çıkar.
        bilgi = g.kontrol_et(istek=_yanit(tag_name="v1.3.0"))
        self.assertEqual(bilgi.surum, "1.3.0")
        self.assertIn("v1.3.0", g.bildirim_html(bilgi, lang="tr"))

    def test_guncelse_veya_eskiyse_bildirim_yok(self):
        self.assertIsNone(g.kontrol_et(yerel="1.2.0", istek=_yanit(tag_name="v1.2.0")))
        self.assertIsNone(g.kontrol_et(yerel="1.10.0", istek=_yanit(tag_name="v1.9.0")))
        self.assertEqual(g.bildirim_html(None), "")

    def test_taslak_on_surum_ve_bozuk_etiket_sessiz(self):
        for alanlar in ({"draft": True}, {"prerelease": True}, {"tag_name": "nightly"}, {"tag_name": None}):
            with self.subTest(alanlar=alanlar):
                self.assertIsNone(g.kontrol_et(yerel="1.0.0", istek=_yanit(**alanlar)))

    def test_yabanci_sayfa_adresi_kullanilmaz(self):
        bilgi = g.kontrol_et(yerel="1.0.0", istek=_yanit(html_url="https://kotu.example/x"))
        self.assertEqual(bilgi.sayfa, g.RELEASES_URL)
        self.assertNotIn("kotu.example", g.bildirim_html(bilgi, platform="win32"))

    def test_ag_hatalarinda_sessiz_ve_tek_satir_log(self):
        def hata(exc):
            def istek(url, zaman_asimi):
                raise exc
            return istek
        hatalar = [
            urllib.error.URLError("internet yok"),
            socket.timeout("timed out"),
            TimeoutError("timed out"),
            urllib.error.HTTPError(g.API_URL, 403, "rate limit exceeded", {}, io.BytesIO(b"")),
            urllib.error.HTTPError(g.API_URL, 404, "Not Found", {}, io.BytesIO(b"")),
            json.JSONDecodeError("bozuk", "x", 0),
        ]
        for exc in hatalar:
            with self.subTest(exc=type(exc).__name__), self.assertLogs("sesver", "INFO") as kayit:
                self.assertIsNone(g.kontrol_et(yerel="1.0.0", istek=hata(exc)))
            self.assertEqual(len(kayit.output), 1)
            self.assertIn("yapılamadı", kayit.output[0])

    def test_gercek_istek_yalniz_get_ve_kisisel_veri_yok(self):
        yakalanan = {}

        class Sahte(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(istek, timeout):
            yakalanan.update(istek=istek, timeout=timeout)
            return Sahte(json.dumps({"tag_name": "v9.0.0"}).encode())

        with patch.object(g.urllib.request, "urlopen", urlopen):
            bilgi = g.kontrol_et(yerel="1.0.0")
        istek = yakalanan["istek"]
        self.assertEqual(bilgi.surum, "9.0.0")
        self.assertEqual(istek.get_method(), "GET")
        self.assertIsNone(istek.data)
        self.assertEqual(istek.full_url, "https://api.github.com/repos/hamarat52/sesver/releases/latest")
        self.assertEqual(set(k.lower() for k in istek.headers), {"accept", "user-agent"})
        self.assertLessEqual(yakalanan["timeout"], 3)

    def test_ortam_degiskeniyle_kapatma(self):
        self.assertTrue(g.kontrol_acik_mi({}))
        self.assertTrue(g.kontrol_acik_mi({g.ORTAM_DEGISKENI: "1"}))
        for deger in ("0", "false", "OFF", " hayir "):
            self.assertFalse(g.kontrol_acik_mi({g.ORTAM_DEGISKENI: deger}))
        cagri = []
        k = g.ArkaPlanKontrol(kontrol=lambda **kw: cagri.append(kw))
        k.baslat(ortam={g.ORTAM_DEGISKENI: "0"})
        self.assertIsNone(k.sonuc())
        self.assertEqual(cagri, [])

    def test_ayarlar_sekmesiyle_kapatma(self):
        self.assertTrue(g.ayar_acik_mi())  # ayarlar.json yok -> varsayılan açık
        try:
            g.ayar_degistir(False)
            self.assertFalse(g.ayar_acik_mi())
            self.assertFalse(g.kontrol_acik_mi({}))
            cagri = []
            k = g.ArkaPlanKontrol(kontrol=lambda **kw: cagri.append(kw))
            k.baslat(ortam={})
            self.assertIsNone(k.sonuc())
            self.assertEqual(cagri, [])  # ağ isteği yapılmadı
            # Diğer ayarlar (arayüz dili) korunur.
            import i18n
            i18n.set_setting("arayuz_dili", "en")
            self.assertFalse(g.ayar_acik_mi())
            g.ayar_degistir(True)
            self.assertTrue(g.kontrol_acik_mi({}))
            self.assertEqual(i18n.get_setting("arayuz_dili"), "en")
            # Ortam değişkeni ayardan önce gelir.
            self.assertFalse(g.kontrol_acik_mi({g.ORTAM_DEGISKENI: "0"}))
        finally:
            Path(g.i18n.settings_path()).unlink(missing_ok=True)

class ArkaPlanTests(unittest.TestCase):
    def test_baslatilmadiysa_beklemeden_none(self):
        t0 = time.monotonic()
        self.assertIsNone(g.ArkaPlanKontrol().sonuc())
        self.assertLess(time.monotonic() - t0, 0.05)

    def test_baslat_bloklamaz_sonuc_gelir(self):
        def yavas(zaman_asimi, kayit):
            time.sleep(0.2)
            return g.YeniSurum("2.0.0", g.RELEASES_URL)
        k = g.ArkaPlanKontrol(kontrol=yavas, zaman_asimi=2)
        t0 = time.monotonic()
        k.baslat(ortam={})
        self.assertLess(time.monotonic() - t0, 0.05)  # açılışa gecikme eklemez
        self.assertEqual(k.sonuc().surum, "2.0.0")

    def test_toplam_sure_siniri_asilmaz(self):
        def asili(zaman_asimi, kayit):
            time.sleep(0.8)
            kayit("Güncelleme kontrolü yapılamadı (TimeoutError: geç)")
        k = g.ArkaPlanKontrol(kontrol=asili, zaman_asimi=0.3)
        k.baslat(ortam={})
        t0 = time.monotonic()
        with self.assertLogs("sesver", "INFO") as kayit:
            self.assertIsNone(k.sonuc())
            gecen = time.monotonic() - t0
            self.assertIsNone(k.sonuc())
            time.sleep(0.8)  # geç biten thread'in log denemesi
        self.assertLess(gecen, 0.6)
        # Bekleyen tarafın tek satırı; ikinci sonuc() ve geç gelen thread yeni satır eklemez.
        self.assertEqual(len(kayit.output), 1, kayit.output)
        self.assertIn("bitmedi", kayit.output[0])

    def test_thread_hatasi_tek_satir(self):
        def hata(url, zaman_asimi):
            raise urllib.error.URLError("internet yok")
        k = g.ArkaPlanKontrol(kontrol=lambda zaman_asimi, kayit: g.kontrol_et(
            yerel="1.0.0", zaman_asimi=zaman_asimi, istek=hata, kayit=kayit), zaman_asimi=2)
        with self.assertLogs("sesver", "INFO") as kayit:
            k.baslat(ortam={})
            self.assertIsNone(k.sonuc())
        self.assertEqual(len(kayit.output), 1)
        self.assertIn("URLError", kayit.output[0])


class ArayuzTests(unittest.TestCase):
    def test_load_bildirimi_gizli_ve_gorunur(self):
        import app
        with patch.object(app.guncelleme, "sonuc", return_value=None):
            self.assertEqual(app._guncelleme_bildirimi("tr")()["visible"], False)
        with patch.object(app.guncelleme, "sonuc", return_value=g.YeniSurum("1.5.0", g.RELEASES_URL)):
            cikti = app._guncelleme_bildirimi("tr")()
        self.assertTrue(cikti["visible"])
        self.assertIn("Yeni sürüm var: v1.5.0", cikti["value"])

    def test_build_app_ag_istegi_baslatmaz(self):
        import app
        with patch.object(g.urllib.request, "urlopen", side_effect=AssertionError("ağ çağrıldı")) as istek, \
                patch.object(g, "baslat") as baslat:
            demo = app.build_app()
        istek.assert_not_called()
        baslat.assert_not_called()
        ids = [c["props"].get("elem_id") for c in demo.config["components"]]
        self.assertIn("sv-update-note", ids)
        # Ayarlar sekmesinde "Açılışta güncellemeleri denetle" (11 dilin her sayfasında bir tane).
        etiketler = [c["props"].get("label") for c in demo.config["components"]
                     if "sv-update-toggle" in (c["props"].get("elem_classes") or [])]
        self.assertEqual(len(etiketler), 11)
        self.assertIn("Açılışta güncellemeleri denetle", etiketler)
        self.assertIn("Check for updates at startup", etiketler)

    def test_ayar_dugmesi_kaydeder(self):
        import app
        try:
            self.assertIn("yapılmayacak", app._update_toggle_ui(False))
            self.assertFalse(g.ayar_acik_mi())
            self.assertIn("denetlenecek", app._update_toggle_ui(True))
            self.assertTrue(g.ayar_acik_mi())
        finally:
            Path(g.i18n.settings_path()).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
