"""Parça birleştirme: birleşim yerinde süreksizlik (tık) yok, doğal duraklama var (sentetik sesle)."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ses_birlestirme as sb  # noqa: E402

SR = 48000


def sinus(sn, frek=220.0, genlik=0.5, faz=0.0):
    t = np.arange(int(sn * SR), dtype=np.float32) / SR
    return (genlik * np.sin(2 * np.pi * frek * t + faz)).astype(np.float32)


def en_buyuk_sicrama(a):
    return float(np.max(np.abs(np.diff(a))))


class BirlestirmeTests(unittest.TestCase):
    def setUp(self):
        # Kenarları sıfırda OLMAYAN parçalar: ham birleştirmede tık olur.
        self.parcalar = [sinus(0.5, 220, 0.5, faz=1.3), sinus(0.4, 330, 0.6, faz=2.1), sinus(0.6, 180, 0.4, faz=0.7)]
        self.aralar = [0.45, 0.3]
        self.dogal_sicrama = max(en_buyuk_sicrama(p) for p in self.parcalar)

    def test_ham_birlestirme_tik_uretir_test_duyarli(self):
        ham = np.concatenate(self.parcalar)
        self.assertGreater(en_buyuk_sicrama(ham), 10 * self.dogal_sicrama,
                           "test sinyali birleşim yerinde gerçekten süreksiz olmalı")

    def test_birlesim_yerinde_sureksizlik_yok(self):
        out = sb.birlestir(self.parcalar, SR, self.aralar, kirp=False)
        # Örnekten örneğe en büyük sıçrama, sinüsün kendi doğal eğiminden belirgin büyük olamaz.
        self.assertLessEqual(en_buyuk_sicrama(out), 1.2 * self.dogal_sicrama)
        self.assertEqual(out.dtype, np.float32)

    def test_duraklama_sessiz_ve_dogru_uzunlukta(self):
        out = sb.birlestir(self.parcalar, SR, self.aralar, kirp=False)
        beklenen = sum(p.size for p in self.parcalar) + sum(int(round(a * SR)) for a in self.aralar)
        self.assertEqual(out.size, beklenen)
        bas = self.parcalar[0].size
        ara = out[bas: bas + int(round(self.aralar[0] * SR))]
        self.assertTrue(np.all(ara == 0.0))
        # Parça kenarları sıfıra iner (ilk ve son örnek tam 0).
        self.assertEqual(out[0], 0.0)
        self.assertEqual(out[bas - 1], 0.0)
        self.assertEqual(out[-1], 0.0)

    def test_gurultulu_parcada_kenarlar_yumusak(self):
        rng = np.random.default_rng(7)
        gurultu = [(rng.standard_normal(SR // 2) * 0.3).astype(np.float32) for _ in range(3)]
        out = sb.birlestir(gurultu, SR, [0.3, 0.3], kirp=False)
        n = int(SR * sb.SOLMA_MS / 1000)
        # Birleşimden hemen önceki/sonraki 1 ms'lik bölümün enerjisi parçanın ortasından çok düşük olmalı.
        bas = gurultu[0].size
        kenar = out[bas - SR // 1000: bas]
        orta = out[bas // 2 - n: bas // 2 + n]
        self.assertLess(np.sqrt(np.mean(kenar ** 2)), 0.1 * np.sqrt(np.mean(orta ** 2)))

    def test_bas_ve_sondaki_sessizlik_kirpilir_pay_kalir(self):
        sessiz = np.zeros(SR, dtype=np.float32)  # 1 sn sessizlik
        parca = np.concatenate([sessiz, sinus(0.5), sessiz])
        kirpik = sb.sessizlik_kirp(parca, SR)
        pay = int(SR * sb.PAY_MS / 1000)
        self.assertAlmostEqual(kirpik.size, int(0.5 * SR) + 2 * pay, delta=4)
        out = sb.birlestir([parca, parca], SR, [0.45])
        self.assertAlmostEqual(out.size / SR, 2 * (0.5 + 2 * sb.PAY_MS / 1000) + 0.45, delta=0.01)

    def test_tamamen_sessiz_ve_tek_parca(self):
        self.assertEqual(sb.sessizlik_kirp(np.zeros(100, dtype=np.float32), SR).size, 0)
        tek = sb.birlestir([sinus(0.2)], SR, [], kirp=False)
        self.assertEqual(tek.size, int(0.2 * SR))
        with self.assertRaises(ValueError):
            sb.birlestir([sinus(0.2), sinus(0.2)], SR, [])

    def test_stereo_mono_indirgenir(self):
        stereo = np.stack([sinus(0.2), sinus(0.2)], axis=1)
        self.assertEqual(sb.birlestir([stereo, stereo], SR, [0.1], kirp=False).ndim, 1)

    def test_dosyalardan_birlestir_pcm16(self):
        with tempfile.TemporaryDirectory() as d:
            yollar = []
            for i, p in enumerate(self.parcalar):
                yol = Path(d) / f"{i:03d}.wav"
                sf.write(str(yol), p, SR)
                yollar.append(yol)
            hedef = Path(d) / "tum.yaziliyor.wav"
            sure = sb.birlestir_dosyalar(yollar, hedef, self.aralar)
            bilgi = sf.info(str(hedef))
            self.assertEqual(bilgi.samplerate, SR)
            self.assertEqual(bilgi.subtype, "PCM_16")
            self.assertAlmostEqual(bilgi.duration, sure, places=3)
            veri, _ = sf.read(str(hedef), dtype="float32")
            # 16-bit nicemlemesi payıyla yine süreksizlik yok.
            self.assertLessEqual(en_buyuk_sicrama(veri), 1.2 * self.dogal_sicrama + 2 / 32768)
            farkli = Path(d) / "farkli.wav"
            sf.write(str(farkli), sinus(0.1), 24000)
            with self.assertRaises(ValueError):
                sb.birlestir_dosyalar([yollar[0], farkli], Path(d) / "x.wav", [0.1])


if __name__ == "__main__":
    unittest.main()
