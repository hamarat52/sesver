"""Uzun metin bölme: 500 sınırı, Türkçe kısaltmalar, sayılar, aşırı uzun cümle davranışı."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import metin_bolme as mb  # noqa: E402

DOLGU = "Bu küçük köyde herkes birbirini tanırdı. "  # 41 karakter, büyük harfle başlar


def _sade(metin):
    return re.sub(r"\s+", " ", metin).strip()


class BolmeTests(unittest.TestCase):
    def assert_gecerli(self, metin, parcalar, en_fazla=500, birlesim=True):
        self.assertTrue(parcalar, "boş olmayan metin en az bir parça vermeli")
        for p in parcalar:
            self.assertLessEqual(len(p.metin), en_fazla, p.metin[:60])
            self.assertEqual(p.metin, p.metin.strip())
            self.assertTrue(p.metin)
        self.assertIsNone(parcalar[-1].sinir)
        for p in parcalar[:-1]:
            self.assertIn(p.sinir, mb.ARALAR)
        if birlesim:  # içerik kaybolmaz, sıra bozulmaz
            self.assertEqual(" ".join(p.metin for p in parcalar), _sade(metin))

    def test_kisa_metin_tek_parca(self):
        self.assertEqual(mb.bol("Merhaba dünya."), [mb.Parca("Merhaba dünya.", None)])
        self.assertEqual(mb.bol("   \n  "), [])
        self.assertEqual(len(mb.bol("a" * 500)), 1)

    def test_uzun_masal_500u_asmaz_ve_cumle_sonundan_boler(self):
        metin = (DOLGU * 30).strip()  # ~1230 karakter
        parcalar = mb.bol(metin)
        self.assert_gecerli(metin, parcalar)
        self.assertGreaterEqual(len(parcalar), 3)
        for p in parcalar[:-1]:
            self.assertTrue(p.metin.endswith("."), p.metin[-30:])
            self.assertEqual(p.sinir, "cumle")

    def test_kisaltmalardan_bolunmez(self):
        # Kısaltmayı 500 sınırının çevresinde her konuma kaydırarak dener.
        for kisaltma, devam in (("Dr.", "Ahmet geldi."), ("Prof.", "Ayşe Hanım anlattı."),
                                ("vb.", "şeyler alındı."), ("ör.", "elma gibi meyveler."),
                                ("Doç.", "Mehmet Bey okudu."), ("bkz.", "Ek 3."), ("T.C.", "Devleti kuruldu.")):
            for kayma in range(0, 45):
                metin = DOLGU * 11 + "x" * kayma + f" Sonra {kisaltma} {devam} " + DOLGU * 3
                parcalar = mb.bol(metin)
                self.assert_gecerli(metin, parcalar)
                for p in parcalar[:-1]:
                    self.assertFalse(p.metin.endswith(kisaltma),
                                     f"'{kisaltma}' sonrasından bölündü (kayma={kayma})")
                self.assertTrue(any(f"{kisaltma} {devam}" in p.metin for p in parcalar), f"kayma={kayma}")

    def test_sayilardan_ve_sira_sayilarindan_bolunmez(self):
        for ifade in ("3.5 kilo un aldı.", "1.000 kişi geldi.", "2. Dünya Savaşı bitti.", "III. Selim tahta çıktı.",
                      "12.03.2024 tarihinde imzalandı.", "Saat 14.30 oldu."):
            for kayma in range(0, 45):
                metin = DOLGU * 11 + "y" * kayma + " Sonra " + ifade + " " + DOLGU * 3
                parcalar = mb.bol(metin)
                self.assert_gecerli(metin, parcalar)
                # İfade tek parçanın içinde kalmalı: içindeki noktadan bölünmemiş olmalı.
                self.assertTrue(any(ifade in p.metin for p in parcalar), f"sayıdan bölündü: {ifade!r} kayma={kayma}")

    def test_kucuk_harfle_devam_eden_soru_bolunmez(self):
        metin = DOLGU * 11 + '"Geliyor musun?" dedi annesi. ' + DOLGU * 2
        for p in mb.bol(metin)[:-1]:
            self.assertFalse(p.metin.endswith('musun?"'))

    def test_paragraf_siniri_isaretlenir(self):
        p1 = (DOLGU * 8).strip()
        p2 = (DOLGU * 8).strip()
        parcalar = mb.bol(p1 + "\n\n" + p2)
        self.assert_gecerli(p1 + " " + p2, parcalar)
        self.assertIn("paragraf", [p.sinir for p in parcalar])
        self.assertEqual(mb.ara_suresi("paragraf"), mb.ARALAR["paragraf"])
        self.assertGreater(mb.ARALAR["paragraf"], mb.ARALAR["cumle"])
        self.assertEqual(mb.ara_suresi(None), 0.0)

    def test_500u_asan_tek_cumle_virgulden_bolunur(self):
        cumle = ", ".join(["uzun bir yan cümle daha geliyor"] * 40) + "."  # ~1300 karakter, tek cümle
        parcalar = mb.bol(cumle)
        self.assert_gecerli(cumle, parcalar)
        self.assertGreater(len(parcalar), 2)
        for p in parcalar[:-1]:
            self.assertTrue(p.metin.endswith(","), p.metin[-20:])
            self.assertEqual(p.sinir, "yan_cumle")

    def test_noktalamasiz_uzun_cumle_kelime_arasindan_bolunur(self):
        cumle = " ".join(["kelime"] * 200)  # 1399 karakter, hiç noktalama yok
        parcalar = mb.bol(cumle)
        self.assert_gecerli(cumle, parcalar)
        for p in parcalar:
            self.assertTrue(all(w == "kelime" for w in p.metin.split(" ")), "kelime ortadan bölünmemeli")
        self.assertEqual(parcalar[0].sinir, "kelime")

    def test_kelime_arasi_bolmede_kisaltma_parcayi_bitirmez(self):
        for kayma in range(0, 12):
            cumle = " ".join(["sozcuk"] * (70 + kayma)) + " Dr. Ahmet " + " ".join(["sozcuk"] * 40)
            parcalar = mb.bol(cumle)
            self.assert_gecerli(cumle, parcalar)
            for p in parcalar[:-1]:
                self.assertFalse(p.metin.endswith("Dr."), f"kayma={kayma}")

    def test_bosluksuz_asiri_uzun_dizi_zorla_kesilir(self):
        dizi = "a" * 1203
        parcalar = mb.bol(dizi)
        self.assertEqual([len(p.metin) for p in parcalar], [500, 500, 203])
        self.assertEqual([p.sinir for p in parcalar], ["kesme", "kesme", None])
        self.assertEqual(mb.ara_suresi("kesme"), 0.0)
        self.assertEqual("".join(p.metin for p in parcalar), dizi)

    def test_on_bin_karakterlik_masal(self):
        cumleler = [f"Masalın {i}. bölümünde kahramanımız Dr. Kaya ile {i}.5 km yürüdü, sonra dinlendi." for i in range(140)]
        metin = " ".join(cumleler)[:10000]
        parcalar = mb.bol(metin)
        self.assert_gecerli(metin, parcalar)
        self.assertGreaterEqual(len(parcalar), 20)

    def test_farkli_sinir_degeri(self):
        metin = DOLGU * 10
        parcalar = mb.bol(metin, en_fazla=120)
        self.assert_gecerli(metin, parcalar, en_fazla=120)


if __name__ == "__main__":
    unittest.main()
