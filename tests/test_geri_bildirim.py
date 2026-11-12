"""1.4.1 (Yusuf'un 2026-11-12 geri bildirimleri): dil seçici etiketi, üretim dili ipucu, efektlerin
bulunabilirliği, model kutucuğu ve kullanıcıya görünen metinlerde em dash olmaması.

Model yüklenmez; ağ çağrılmaz.
"""
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import i18n

ROOT = Path(__file__).resolve().parent.parent
IPUCU = "Hangi dilde yazarsanız o dilde okur."


def _demo():
    with patch.object(app.guncelleme.urllib.request, "urlopen", side_effect=AssertionError("ağ çağrıldı")):
        return app.build_app()


class GeriBildirimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = _demo()
        cls.comps = cls.demo.config["components"]

    def _sinifli(self, sinif):
        return [c for c in self.comps if sinif in (c["props"].get("elem_classes") or [])]

    def test_dil_secicide_gorunur_etiket_yok_erisilebilir_ad_var(self):
        seciciler = self._sinifli("sv-lang")
        self.assertEqual(len(seciciler), 11)
        etiketler = {c["props"]["label"] for c in seciciler}
        self.assertIn("Arayüz dili", etiketler)  # ekran okuyucu için ad (TR sayfası)
        self.assertIn("Interface language", etiketler)
        for c in seciciler:
            self.assertIs(c["props"]["show_label"], False)
            self.assertNotIn("🌐", c["props"]["label"])
        self.assertNotIn('.sv-lang [data-testid="block-info"] { font-size', app._CSS)

    def test_uretim_dili_ipucu_yalniz_voxcpm_metin_alanlarinda(self):
        ipucu = self._sinifli("sv-lang-hint")
        # Ses Kütüphanesi + Ses Klonlama metin alanı, 11 dil sayfası.
        self.assertEqual(len(ipucu), 22)
        self.assertTrue(all(c["type"] == "textbox" for c in ipucu))
        infolar = {c["props"]["info"] for c in ipucu}
        self.assertIn(IPUCU, infolar)
        self.assertIn("It reads in whatever language you write.", infolar)
        # Hızlı Mod (yalnız Türkçe okur) metin alanında ipucu yok.
        hizli = [c for c in self.comps if c["type"] == "textbox"
                 and c["props"].get("max_length") == app.ema_motor.MAX_TEXT_CHARS
                 and c["props"].get("info")]
        self.assertEqual(hizli, [])
        # Tek kısa satır, bütün dillerde çevrili.
        self.assertLessEqual(len(IPUCU), 45)
        for lang in i18n.LANGUAGES:
            if lang != i18n.DEFAULT:
                self.assertIn(IPUCU, i18n.catalog(lang))

    def test_efekt_girisi_ses_hazir_olunca_gorunur_ve_ayarlari_acar(self):
        girisler = self._sinifli("sv-fx-jump")
        self.assertEqual(len(girisler), 11)
        for c in girisler:
            self.assertIs(c["props"]["visible"], False)  # üretimden önce gizli
        tr = next(c for c in girisler if c["props"]["value"] == "Efekt ekle")
        tiklama = [f for f in self.demo.fns.values() if (tr["id"], "click") in [tuple(x) for x in f.targets]]
        self.assertEqual(len(tiklama), 1)
        acilan = tiklama[0].fn()
        self.assertIsInstance(acilan, app.gr.Accordion)
        self.assertIs(acilan.open, True)
        self.assertIn("scrollIntoView", tiklama[0].js)
        self.assertIn(".sv-fx", tiklama[0].js)
        # Üretimden sonra görünürlük ses dosyasına bağlı.
        gorunur = [f for f in self.demo.fns.values() if tr["id"] in [o._id for o in f.outputs]
                   and f.fn is not None and f is not tiklama[0]]
        self.assertTrue(gorunur)
        self.assertEqual(gorunur[0].fn("/x/ses.wav"), app.gr.update(visible=True))
        self.assertEqual(gorunur[0].fn(None), app.gr.update(visible=False))
        # Efekt kartı başlığı efektleri adıyla sayar (kapalı akordeonda da görünür).
        self.assertIn("Cızırtı, eski radyo, telefon, telsiz, oda yankısı ve megafon.",
                      " ".join(str(c["props"].get("value")) for c in self.comps if c["type"] == "html"))

    def test_model_kutucugu_model_durumuna_gore(self):
        with patch.object(app, "_model", None), patch.object(app, "_model_diskte", return_value=True):
            diskte = app._info()
        self.assertIn("Ses modeli bilgisayarınızda", diskte)
        self.assertNotIn("indirilir", diskte.replace("indirilmez", ""))
        with patch.object(app, "_model", None), patch.object(app, "_model_diskte", return_value=False):
            yok = app._info()
        self.assertIn("İlk üretimde ~5 GB indirilir", yok)
        with patch.object(app, "_model", None), patch.object(app, "_model_diskte", return_value=None):
            self.assertIn("İlk üretimde ~5 GB indirilir", app._info())  # bilinmiyorsa genel metin
        with patch.object(app, "_model", object()), patch.object(app, "_model_diskte", return_value=False):
            self.assertIn("Ses modeli bilgisayarınızda", app._info())
        with i18n.use("en"), patch.object(app, "_model", None), patch.object(app, "_model_diskte", return_value=True):
            self.assertIn("The voice model is on your computer", app._info())

    def test_model_kutucugu_sayfa_acilisinda_yenilenir(self):
        bilgi = [c for c in self.comps if c["type"] == "html" and "sv-info" in str(c["props"].get("value"))]
        self.assertEqual(len(bilgi), 11)
        ids = {c["id"] for c in bilgi}
        yukleme = [f for f in self.demo.fns.values() if ("load" in [x[1] for x in f.targets])
                   and any(o._id in ids for o in f.outputs)]
        self.assertEqual(len(yukleme), 11)
        self.assertTrue(all(f.queue is False for f in yukleme))


class EmDashTests(unittest.TestCase):
    """Kullanıcıya görünen bütün metinler (kaynak anahtarlar ve 10 dilin çevirileri) em dash içermez."""

    def test_sifir_em_dash(self):
        kaynak = json.loads((ROOT / "locales" / "_kaynak.json").read_text(encoding="utf-8"))
        self.assertEqual([k for k in kaynak if "\u2014" in k], [])
        for f in sorted((ROOT / "locales").glob("*.json")):
            if f.name.startswith("_"):
                continue
            d = json.loads(f.read_text(encoding="utf-8"))
            with self.subTest(dil=f.stem):
                self.assertEqual([k for k, v in d.items() if "\u2014" in k + str(v)], [])

    def test_kurulum_kisayol_aciklamasi(self):
        iss = (ROOT / "windows" / "SesVer.iss").read_text(encoding="utf-8-sig")
        mesajlar = re.findall(r"^(?:turkish|english)\.[A-Za-z0-9]+=(.*)$", iss, re.M)
        self.assertGreater(len(mesajlar), 50)
        self.assertEqual([m for m in mesajlar if "\u2014" in m], [])


if __name__ == "__main__":
    unittest.main()
