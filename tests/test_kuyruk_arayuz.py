"""Üretim kuyruğunun arayüz bağlantısı (app.py + kuyruk_arayuz.py), model indirmeden.

Kuyruk geçici klasörde, sahte üretimle kurulur ve app._KUYRUK yerine konur; arayüz işlevleri
(Kuyruğa ekle, listedeki düğmeler, Başlat/Durdur, içe aktarma) gerçek kod yolundan çağrılır.
"""
import contextlib
import shutil
import sys
import tempfile
import threading
import unittest
import warnings
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import i18n  # noqa: E402
import kuyruk as kq  # noqa: E402
import kuyruk_arayuz as qa  # noqa: E402

VERI = ROOT / "tests" / "veri" / "ice_aktarma"
SR = 48000


def wav_yaz(yol, sn=0.05):
    t = np.arange(int(sn * SR), dtype=np.float32) / SR
    sf.write(str(yol), (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), SR)


class SahteUretim:
    """uret_fn yerine: metinde HATA geçerse hata verir; istenen çağrıda bekletir."""

    def __init__(self):
        self.metinler = []
        self.basladi = threading.Event()
        self.devam = threading.Event()
        self.devam.set()

    def __call__(self, istek, hedef):
        self.metinler.append(istek["metin"])
        self.basladi.set()
        assert self.devam.wait(10), "test bekletmesi zaman aşımı"
        if "HATA" in istek["metin"]:
            raise RuntimeError("sahte üretim hatası")
        wav_yaz(hedef)


class KuyrukArayuzTestleri(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app = app

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sv-kuyruk-ui-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.uret = SahteUretim()
        self.kuyruk = kq.Kuyruk(
            dizin=self.tmp / "kuyruk", cikti_dir=self.tmp / "outputs", uret_fn=self.uret,
            siniflandir=lambda exc, oge: "beklenmeyen", engel=lambda gerekce: contextlib.nullcontext(),
            temizlik_fn=lambda: None, hata_metni=qa.hata_metni)
        self.addCleanup(self._kapat)
        for yama in (mock.patch.object(self.app, "_KUYRUK", self.kuyruk),
                     mock.patch.object(self.app, "_accel_block_reason", return_value=None),
                     mock.patch("uyku_engeli.pilde_mi", return_value=False)):
            yama.start()
            self.addCleanup(yama.stop)
        warnings.simplefilter("ignore", UserWarning)  # gr.Info/Warning istek bağlamı dışında uyarı verir

    def _kapat(self):
        self.uret.devam.set()
        self.kuyruk.durdur()
        self.kuyruk.bekle(10)

    def _ogeler(self):
        return self.kuyruk.durum()["ogeler"]

    def _kutuphane_ekle(self, metin, ses="masalci", duygu="Nötr"):
        return self.app.kuyruga_ekle_kutuphane_ui(metin, duygu, "Hızlı", ses)

    # --- ekleme ------------------------------------------------------------------------------
    def test_kutuphaneden_ekle_ayarlarin_anlik_goruntusunu_alir(self):
        msg = self._kutuphane_ekle("Bir varmış bir yokmuş.", duygu="Sakin")
        self.assertIn("Kuyruğa eklendi", msg)
        self.assertIn("sağ üstteki **Kuyruk**", msg)
        (oge,) = self._ogeler()
        self.assertEqual((oge["tur"], oge["ses_id"], oge["duygu"], oge["kalite"]),
                         ("kutuphane", "masalci", "Sakin", "Hızlı"))
        # Referans kuyruk klasörüne kopyalanır; kütüphanedeki ses silinse de gece üretilebilir.
        self.assertTrue(list((self.tmp / "kuyruk" / "ref").glob("*.wav")))
        self.assertFalse(self.kuyruk.calisiyor, "Kuyruğa ekle kuyruğu kendiliğinden başlatmamalı")

    def test_uzun_metin_parcalanir_ve_rastgele_seste_reddedilir(self):
        uzun = ("Karıncalar doğanın en sabırlı yapı ustalarıdır. " * 40).strip()
        self.assertGreater(len(uzun), 1500)
        with self.assertRaisesRegex(self.app.gr.Error, "rastgele sesle"):
            self._kutuphane_ekle(uzun, ses=self.app.RANDOM_VOICE)
        self.assertEqual(self._ogeler(), [], "reddedilen öğe kuyruğa girmemeli")
        msg = self._kutuphane_ekle(uzun)
        (oge,) = self._ogeler()
        self.assertGreaterEqual(oge["parca_sayisi"], 3)
        self.assertIn(f"{oge['parca_sayisi']} parçaya", msg)
        # Kısa metin rastgele sesle eklenebilir.
        self._kutuphane_ekle("Kısa bir cümle.", ses=self.app.RANDOM_VOICE)
        self.assertEqual(len(self._ogeler()), 2)

    def test_on_bin_karakter_siniri(self):
        with self.assertRaisesRegex(self.app.gr.Error, "10000|10.000"):
            self._kutuphane_ekle("a" * (kq.OGE_METIN_EN_FAZLA + 1))
        self.assertEqual(self._ogeler(), [])

    def test_klondan_ekle_referansi_kopyalar(self):
        ref = self.tmp / "gecici_ref.wav"
        wav_yaz(ref, sn=2)
        self.app.kuyruga_ekle_klon_ui("Merhaba dünya.", str(ref), "Nötr", "referans metni")
        ref.unlink()  # Gradio'nun geçici dosyası silinse de kopya kalır
        (oge,) = self._ogeler()
        self.assertEqual(oge["tur"], "klon")
        self.assertTrue((self.tmp / "kuyruk" / oge["ref"]).is_file())
        with self.assertRaisesRegex(self.app.gr.Error, "referans"):
            self.app.kuyruga_ekle_klon_ui("Merhaba.", None, "Nötr", "")

    # --- listedeki düğmeler ---------------------------------------------------------------------
    def test_sirala_ve_cikar(self):
        for metin in ("Bir.", "İki.", "Üç."):
            self._kutuphane_ekle(metin)
        ids = [o["id"] for o in self._ogeler()]
        self.app.kuyruk_komut_ui("yukari", ids[2])
        self.assertEqual([o["metin"] for o in self._ogeler()], ["Bir.", "Üç.", "İki."])
        self.app.kuyruk_komut_ui("asagi", ids[0])
        self.assertEqual([o["metin"] for o in self._ogeler()], ["Üç.", "Bir.", "İki."])
        self.app.kuyruk_komut_ui("cikar", ids[1])
        self.assertEqual([o["metin"] for o in self._ogeler()], ["Üç.", "Bir."])
        # Olmayan öğe: istisna yerine uyarı (arayüz çökmez).
        self.assertIsNone(self.app.kuyruk_komut_ui("cikar", "yok"))

    def test_liste_dugmeleri_ve_kullanici_metni_kacislanir(self):
        self._kutuphane_ekle('<img src=x onerror="alert(1)"> Merhaba.')
        html = qa.liste_html(self.kuyruk.durum())
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)
        oid = self._ogeler()[0]["id"]
        for act in ("yukari", "asagi", "cikar"):
            self.assertIn(f'data-act="{act}" data-id="{oid}"', html)

    # --- çalıştırma ------------------------------------------------------------------------------
    def test_durdur_devam_ve_ust_dugme(self):
        for metin in ("Bir.", "İki.", "Üç."):
            self._kutuphane_ekle(metin)
        self.assertEqual(qa.ust_dugme(self.kuyruk.durum()), ("Kuyruk · 3 bekliyor", "is-waiting"))
        self.assertEqual(qa.ana_dugme(self.kuyruk.durum())[:2], ("Başlat", True))
        self.uret.devam.clear()
        self.uret.basladi.clear()
        self.app.kuyruk_baslat_durdur_ui()
        self.assertTrue(self.uret.basladi.wait(5))
        d = self.kuyruk.durum()
        self.assertEqual(qa.ust_dugme(d), ("Kuyruk 1/3", "is-running"))
        self.assertEqual(qa.ana_dugme(d), ("Durdur", True, True))
        self.app.kuyruk_baslat_durdur_ui()  # Durdur: şu anki parça bitince
        self.uret.devam.set()
        self.assertTrue(self.kuyruk.bekle(10))
        d = self.kuyruk.durum()
        self.assertEqual([o["durum"] for o in d["ogeler"]], [kq.BITTI, kq.BEKLIYOR, kq.BEKLIYOR])
        self.assertEqual(qa.ana_dugme(d)[:2], ("Devam et", True))
        self.app.kuyruk_baslat_durdur_ui()  # Devam et
        self.assertTrue(self.kuyruk.bekle(10))
        d = self.kuyruk.durum()
        self.assertEqual(d["sayilar"][kq.BITTI], 3)
        self.assertEqual(qa.ust_dugme(d), ("Kuyruk · 3 bitti", "is-done"))
        self.assertEqual(self.uret.metinler, ["Bir.", "İki.", "Üç."])

    def test_hatali_oge_kuyrugu_durdurmaz_yeniden_dene_sona_alir(self):
        for metin in ("Bir.", "HATA ver.", "Üç."):
            self._kutuphane_ekle(metin)
        self.app.kuyruk_baslat_durdur_ui()
        self.assertTrue(self.kuyruk.bekle(10))
        d = self.kuyruk.durum()
        self.assertEqual([o["durum"] for o in d["ogeler"]], [kq.BITTI, kq.HATA, kq.BITTI])
        self.assertEqual(qa.ust_dugme(d)[1], "is-error")
        html = qa.liste_html(d)
        hatali = d["ogeler"][1]["id"]
        self.assertIn(f'data-act="yeniden" data-id="{hatali}"', html)
        self.app.kuyruk_komut_ui("yeniden", hatali)
        d = self.kuyruk.durum()
        self.assertEqual(d["ogeler"][-1]["id"], hatali)
        self.assertEqual(d["ogeler"][-1]["durum"], kq.BEKLIYOR)
        # Biten öğe dinlenebilir (yol döner); hatalı öğe yeniden denenemez değil artık bekliyor.
        biten = d["ogeler"][0]
        self.assertEqual(self.app.kuyruk_komut_ui("dinle", biten["id"]), biten["cikti"])
        ozet = (Path(d["oturum_klasoru"]) / "ozet.txt").read_text(encoding="utf-8")
        self.assertIn("hata: ", ozet)

    def test_kuyruk_gorunumu_tek_blok_ve_surum(self):
        self._kutuphane_ekle("Bir.")
        cikti, surum = self.app._kuyruk_gorunum()
        self.assertEqual(cikti[0]["value"], "Kuyruk · 1 bekliyor")
        self.assertIn('class="sv-qview"', cikti[3])
        self.assertEqual(surum, self.kuyruk.durum()["surum"])

    # --- içe aktarma ------------------------------------------------------------------------------
    def test_ice_aktarma_onizleme_eklemez_onay_ekler(self):
        yol = str(VERI / "tr_noktalivirgul_utf8.csv")
        html, dugme = self.app.ice_onizle_ui(yol, "masalci", "Nötr", "Dengeli", "paragraf")
        self.assertEqual(self._ogeler(), [], "önizleme kuyruğa eklememeli")
        self.assertIn("Olmayan Ses", html)  # reddedilen satır nedeniyle gösterilir
        self.assertTrue(dugme["interactive"])
        self.assertEqual(dugme["value"], "3 öğeyi kuyruğa ekle")
        self.assertEqual(self.app.ice_ekle_ui(yol, "masalci", "Nötr", "Dengeli", "paragraf"), 3)
        ogeler = self._ogeler()
        self.assertEqual([o["ses_id"] for o in ogeler], ["masalci", "belgesel", kq.RASTGELE])
        self.assertEqual(ogeler[1]["kalite"], "En İyi")

    def test_ice_aktarma_txt_paragraf_ve_bos_dosya(self):
        yol = str(VERI / "paragraflar_utf8.txt")
        _html, dugme = self.app.ice_onizle_ui(yol, "masalci", "Nötr", "Dengeli", "paragraf")
        n = int(dugme["value"].split()[0])
        self.assertGreaterEqual(n, 2)
        _html, tek = self.app.ice_onizle_ui(yol, "masalci", "Nötr", "Dengeli", "tek")
        self.assertEqual(tek["value"], "1 öğeyi kuyruğa ekle")
        bos = self.tmp / "bos.txt"
        bos.write_text("  \n", encoding="utf-8")
        html, dugme = self.app.ice_onizle_ui(str(bos), "masalci", "Nötr", "Dengeli", "paragraf")
        self.assertFalse(dugme["interactive"])
        with self.assertRaisesRegex(self.app.gr.Error, "Eklenecek öğe yok"):
            self.app.ice_ekle_ui(str(bos), "masalci", "Nötr", "Dengeli", "paragraf")

    def test_ice_aktarma_kuyruk_sinirini_asmaz(self):
        satirlar = "\n\n".join(f"Paragraf {i}." for i in range(60))
        yol = self.tmp / "cok.txt"
        yol.write_text(satirlar, encoding="utf-8")
        _html, dugme = self.app.ice_onizle_ui(str(yol), "masalci", "Nötr", "Dengeli", "paragraf")
        self.assertEqual(dugme["value"], f"{kq.KUYRUK_EN_FAZLA} öğeyi kuyruğa ekle")
        self.assertEqual(self.app.ice_ekle_ui(str(yol), "masalci", "Nötr", "Dengeli", "paragraf"),
                         kq.KUYRUK_EN_FAZLA)

    # --- elle Üret ile paylaşım ------------------------------------------------------------------
    def test_elle_uret_500_siniri_kuyruga_yonlendirir(self):
        with mock.patch.object(self.app, "get_model") as yukle:
            with self.assertRaisesRegex(self.app.gr.Error, "Kuyruğa ekle"):
                list(self.app.generate_audio("a" * 501, None))
            yukle.assert_not_called()

    def test_kuyruk_calisirken_elle_uret_parca_arasina_girer(self):
        self._kutuphane_ekle("Bir.")
        self._kutuphane_ekle("İki.")
        self.uret.devam.clear()
        self.app.kuyruk_baslat_durdur_ui()
        self.assertTrue(self.uret.basladi.wait(5))
        sira = []

        def elle(text, *args, **kwargs):
            sira.append("elle-basladi:" + ",".join(self.uret.metinler))
            yield None, None, "İstek kontrol ediliyor…"
            yield "x.wav", "x.wav", "bitti"

        sarili = self.app._elle_oncelikli(elle)
        sonuc = []
        th = threading.Thread(target=lambda: sonuc.extend(sarili("Merhaba.")))
        th.start()
        self.uret.devam.set()
        th.join(10)
        self.assertTrue(self.kuyruk.bekle(10))
        self.assertIn("Kuyruk çalışıyor", sonuc[0][2])
        self.assertEqual(sonuc[-1], ("x.wav", "x.wav", "bitti"))
        self.assertEqual(self.uret.metinler, ["Bir.", "İki."])

    def test_kuyruk_hatalari_arayuz_hata_sayisina_karismaz(self):
        with mock.patch.object(self.app.hata_raporu, "error_count", return_value=5), \
                mock.patch.object(self.app, "_kuyruk_hata_sayisi", 3):
            self.assertEqual(self.app._ui_hata_sayisi(), 2)

    def test_ingilizce_metinler(self):
        self._kutuphane_ekle("Bir.")
        with i18n.use("en"):
            self.assertEqual(qa.ust_dugme(self.kuyruk.durum())[0], "Queue · 1 waiting")
            self.assertEqual(qa.ana_dugme(self.kuyruk.durum())[0], "Start")
            with self.assertRaisesRegex(self.app.gr.Error, "random voice"):
                self.app._in_lang(self.app.kuyruga_ekle_kutuphane_ui, "en")(
                    "Uzun cümle. " * 60, "Nötr", "Hızlı", self.app.RANDOM_VOICE)


class KuyrukSayfaTestleri(unittest.TestCase):
    def test_arayuz_kurulurken_kuyruk_diske_yazilmaz_girisler_sag_ustte(self):
        import app
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(kq, "KUYRUK_DIR", Path(tmp) / "kuyruk"), \
                mock.patch.object(app, "_KUYRUK", None):
            demo = app.build_app()
            self.assertFalse((Path(tmp) / "kuyruk").exists())
            self.assertIsNone(app._KUYRUK)
        comps = demo.config["components"]
        sinif = [" ".join(c["props"].get("elem_classes") or []) for c in comps]
        self.assertEqual(sum("sv-top-kuyruk" in s for s in sinif), len(i18n.LANGUAGES))
        self.assertEqual(sum("sv-top-ayarlar" in s for s in sinif), len(i18n.LANGUAGES))
        etiketler = {c["props"].get("value") for c in comps if "sv-btn-queue" in " ".join(
            c["props"].get("elem_classes") or [])}
        self.assertTrue({"Kuyruğa ekle", "Add to queue", "أضف إلى الطابور"} <= etiketler)
        ids = {c["props"].get("elem_id") for c in comps}
        self.assertTrue({"sv-tab-kuyruk", "sv-tab-ayarlar"} <= ids)
        # Sayfa açılışında kuyruğa giden olaylar sayfa başına sınırlı kalır (Gradio max_size=8):
        # aynı yükleme olayı birden çok kez bağlanmaz.
        for dep in demo.config["dependencies"]:
            yukleme = [tuple(t) for t in dep["targets"] if t[1] == "load"]
            self.assertEqual(len(yukleme), len(set(yukleme)), dep["id"])


if __name__ == "__main__":
    unittest.main()
