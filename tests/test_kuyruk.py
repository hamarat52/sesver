"""Üretim kuyruğu çekirdeği: durumlar, sıra, kalıcılık (kapat/aç), sistemik duraklatma,
kendiliğinden başlamama, uzun öğe parçaları ve kesintiden devam (sahte üretimle)."""
import contextlib
import datetime
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import kuyruk as kq  # noqa: E402

SR = 48000
PARCA_SN = 0.05
SABIT_ZAMAN = datetime.datetime(2026, 11, 3, 22, 15, tzinfo=datetime.timezone(datetime.timedelta(hours=3)))


class KodluHata(Exception):
    def __init__(self, kod):
        super().__init__(f"sahte hata {kod}")
        self.kod = kod


def wav_yaz(yol, sn=PARCA_SN):
    t = np.arange(int(sn * SR), dtype=np.float32) / SR
    sf.write(str(yol), (0.4 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), SR)


class SahteUretim:
    """uret_fn yerine: çağrıları kaydeder, eşzamanlılığı ölçer; istenen çağrıda hata/bekleme."""

    def __init__(self, hatalar=None, engel=None):
        self.cagrilar = []
        self.hatalar = hatalar or {}
        self.bekletmeler = {}
        self.engel = engel
        self.engel_acikti = []
        self.esz = self.en_fazla_esz = 0
        self._kilit = threading.Lock()
        self.ozel = {}  # çağrı no -> callable(istek, hedef) (ör. anlık görüntü al)

    def beklet(self, n):
        basladi, devam = threading.Event(), threading.Event()
        self.bekletmeler[n] = (basladi, devam)
        return basladi, devam

    def __call__(self, istek, hedef):
        with self._kilit:
            self.esz += 1
            self.en_fazla_esz = max(self.en_fazla_esz, self.esz)
            self.cagrilar.append(dict(istek))
            n = len(self.cagrilar)
        try:
            if self.engel is not None:
                self.engel_acikti.append(self.engel.acik)
            if n in self.ozel:
                self.ozel[n](istek, hedef)
            if n in self.bekletmeler:
                basladi, devam = self.bekletmeler[n]
                basladi.set()
                assert devam.wait(10), "test bekletmesi zaman aşımı"
            hata = self.hatalar(istek, n) if callable(self.hatalar) else self.hatalar.get(n)
            if hata:
                raise hata
            wav_yaz(hedef)
        finally:
            with self._kilit:
                self.esz -= 1

    def parca_nolari(self):
        return [c["parca_no"] for c in self.cagrilar]


class SahteEngel:
    def __init__(self):
        self.acik = False
        self.giris = self.cikis = 0
        self.thread = None
        self.gerekce = None

    def __call__(self, gerekce):
        @contextlib.contextmanager
        def cm():
            self.acik, self.gerekce, self.thread = True, gerekce, threading.get_ident()
            self.giris += 1
            try:
                yield
            finally:
                self.acik = False
                self.cikis += 1
        return cm()


def uzun_metin(cumle_sayisi):
    """Her cümlesi ~300 karakter: ikisi bir parçaya sığmaz → cümle sayısı kadar parça."""
    cumleler = [f"Bölüm {i + 1} başlıyor ve " + "kahraman uzun yolda yürümeye devam etti " * 7 + "sonunda dinlendi."
                for i in range(cumle_sayisi)]
    return " ".join(cumleler)


class KuyrukTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.kok = Path(self._tmp.name)
        self.ref = self.kok / "ref_kaynak.wav"
        wav_yaz(self.ref, 2.0)
        self.kuyruklar = []

    def tearDown(self):
        for k in self.kuyruklar:
            k.durdur()
            k.bekle(10)
            k._surec_kilidi.birak()
        self._tmp.cleanup()

    def yeni(self, kok=None, **kw):
        kok = Path(kok or self.kok)
        kw.setdefault("uret_fn", SahteUretim())
        kw.setdefault("engel", SahteEngel())
        k = kq.Kuyruk(dizin=kok / "kuyruk", cikti_dir=kok / "outputs", simdi=lambda: SABIT_ZAMAN, **kw)
        self.kuyruklar.append(k)
        return k

    def ses(self, **kw):
        return dict(dict(ses_id="masalci", ses_adi="Yaşlı Masalcı", ref_kaynak=str(self.ref), ref_metin="Bir varmış"),
                    **kw)

    def calistir(self, k):
        self.assertTrue(k.baslat())
        self.assertTrue(k.bekle(10), "işçi bitmedi")


class EklemeTests(KuyrukTestBase):
    def test_dogrulama_kodlari(self):
        k = self.yeni()
        durumlar = [
            (dict(tur="kutuphane", metin="  "), "metin_bos"),
            (dict(tur="kutuphane", metin="a" * (kq.OGE_METIN_EN_FAZLA + 1)), "metin_uzun"),
            (dict(tur="kutuphane", metin="Uzun. " * 100), "rastgele_uzun"),  # rastgele ses + 600 karakter
            (dict(tur="klon", metin="Merhaba."), "ref_yok"),
            (dict(tur="kutuphane", metin="Merhaba.", ses_id="masalci"), "ref_yok"),
            (dict(tur="klon", metin="Merhaba.", ref_kaynak=str(self.kok / "yok.wav")), "ref_yok"),
            (dict(tur="hizli", metin="Merhaba."), "tur_gecersiz"),
        ]
        for istek, kod in durumlar:
            with self.subTest(kod=kod), self.assertRaises(kq.KuyrukHatasi) as ctx:
                k.ekle(**istek)
            self.assertEqual(ctx.exception.kod, kod)
        self.assertEqual(k.durum()["ogeler"], [])
        self.assertEqual(k.durum()["durum"], kq.BOS)

    def test_uzun_oge_kayitli_seste_parcalanir_rastgele_kisa_kabul(self):
        k = self.yeni()
        uzun = k.ekle("kutuphane", uzun_metin(3), **self.ses())
        self.assertEqual(uzun["parca_sayisi"], 3)
        self.assertTrue(uzun["uzun"])
        kisa = k.ekle("kutuphane", "Merhaba dünya.")  # rastgele ses, ≤500
        self.assertEqual(kisa["parca_sayisi"], 1)
        self.assertEqual(kisa["ses_id"], kq.RASTGELE)
        klon = k.ekle("klon", uzun_metin(2), ref_kaynak=str(self.ref))
        self.assertEqual(klon["parca_sayisi"], 2)
        self.assertEqual(k.durum()["durum"], kq.HAZIR)
        # Referans kopyalanır (Gradio'nun geçici dosyası silinse de üretim yapılabilsin).
        self.assertTrue((k.dizin / uzun["ref"]).is_file())
        self.assertNotEqual(Path(k.dizin / uzun["ref"]), self.ref)

    def test_elli_sinir_ve_toplu_ekleme_hepsi_ya_da_hicbiri(self):
        k = self.yeni()
        k.ekle_toplu([dict(tur="kutuphane", metin=f"Metin {i}.") for i in range(48)])
        with self.assertRaises(kq.KuyrukHatasi) as ctx:
            k.ekle_toplu([dict(tur="kutuphane", metin=f"Ek {i}.") for i in range(3)])
        self.assertEqual(ctx.exception.kod, "dolu")
        self.assertEqual(ctx.exception.bilgi["kalan"], 2)
        with self.assertRaises(kq.KuyrukHatasi) as ctx:
            k.ekle_toplu([dict(tur="kutuphane", metin="Geçerli."), dict(tur="kutuphane", metin="")])
        self.assertEqual((ctx.exception.kod, ctx.exception.bilgi["sira"]), ("metin_bos", 1))
        self.assertEqual(len(k.durum()["ogeler"]), 48)
        k.ekle_toplu([dict(tur="kutuphane", metin="49."), dict(tur="kutuphane", metin="50.")])
        with self.assertRaises(kq.KuyrukHatasi) as ctx:
            k.ekle("kutuphane", "51.")
        self.assertEqual(ctx.exception.kod, "dolu")

    def test_dosya_adlari(self):
        self.assertEqual(kq.dosya_adi(3, "Yaşlı Masalcı", "Bir varmış, bir yokmuş; evvel zaman içinde"),
                         "03_yasli-masalci_bir-varmis-bir-yokmus")
        self.assertEqual(kq.dosya_adi(1, "🎲 Rastgele ses", "Çığ düştü!"), "01_rastgele-ses_cig-dustu")
        self.assertEqual(kq.dosya_adi(12, "", "你好世界"), "12_ses_metin")
        self.assertEqual(kq.dosya_adi(7, "CON", "a/b:c*?<>|"), "07_con_a-b-c")
        uzun = kq.dosya_adi(50, "Çok uzun bir ses adı " * 5, "kelime " * 300)
        self.assertLessEqual(len(uzun), kq.AD_EN_FAZLA)
        self.assertRegex(uzun, r"^[a-z0-9_-]+$")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "01_a_b.wav").write_bytes(b"")
            self.assertEqual(kq._benzersiz(Path(d), "01_a_b"), "01_a_b-2")


class CalismaTests(KuyrukTestBase):
    def test_sirayla_tek_tek_uretir_ciktilari_ve_ozeti_yazar(self):
        engel = SahteEngel()
        uretim = SahteUretim(engel=engel)
        k = self.yeni(uret_fn=uretim, engel=engel)
        a = k.ekle("kutuphane", "Bir varmış bir yokmuş.", **self.ses(efektler=[]))
        b = k.ekle("kutuphane", "İkinci öğe burada.")
        c = k.ekle("klon", "Klonla okunan üçüncü metin.", ref_kaynak=str(self.ref))
        with self.assertLogs("sesver", level="INFO") as gunluk:
            self.calistir(k)
        self.assertEqual([x["oge_id"] for x in uretim.cagrilar], [a["id"], b["id"], c["id"]])
        self.assertEqual(uretim.en_fazla_esz, 1, "aynı anda yalnız bir üretim")
        d = k.durum()
        self.assertEqual(d["durum"], kq.TAMAMLANDI)
        self.assertEqual([o["durum"] for o in d["ogeler"]], [kq.BITTI] * 3)
        klasor = k.cikti_dir / "kuyruk" / "2026-11-03_22-15_AI-ile-uretildi"
        self.assertEqual(Path(d["oturum_klasoru"]), klasor)
        adlar = sorted(p.name for p in klasor.glob("*.wav"))
        self.assertEqual(adlar, ["01_yasli-masalci_bir-varmis-bir-yokmus.wav", "02_rastgele-ses_ikinci-oge-burada.wav",
                                 "03_klon_klonla-okunan-ucuncu-metin.wav"])
        self.assertEqual([Path(o["cikti"]).name for o in d["ogeler"]], adlar)
        self.assertFalse(list(k.cikti_dir.rglob(f"*{kq.GECICI_EK}")))
        self.assertFalse((k.dizin / "parca" / a["id"]).exists(), "ara parçalar temizlenmeli")
        ozet = (klasor / "ozet.txt").read_text(encoding="utf-8")
        self.assertIn("AI ile üretildi", ozet.splitlines()[0])
        self.assertIn("Bitti: 3", ozet)
        self.assertIn("01_yasli-masalci_bir-varmis-bir-yokmus.wav", ozet)
        # Uyku engeli: yalnız çalışırken, işçi iş parçacığında, bir kez aç/kapat.
        self.assertEqual((engel.giris, engel.cikis), (1, 1))
        self.assertFalse(engel.acik)
        self.assertEqual(uretim.engel_acikti, [True, True, True])
        self.assertNotEqual(engel.thread, threading.get_ident())
        self.assertEqual(engel.gerekce, kq.UYKU_GEREKCESI)
        # Günlükte metin yok.
        for satir in gunluk.output:
            for metin in ("Bir varmış", "İkinci öğe", "Klonla okunan", "yasli-masalci"):
                self.assertNotIn(metin, satir)

    def test_hata_kuyrugu_durdurmaz_neden_ogede_kalir(self):
        uretim = SahteUretim(hatalar={2: MemoryError("özel metin içerir")})
        k = self.yeni(uret_fn=uretim, siniflandir=lambda exc, oge: "ram" if isinstance(exc, MemoryError) else "other")
        for i in range(3):
            k.ekle("kutuphane", f"Öğe {i + 1}.")
        self.calistir(k)
        d = k.durum()
        self.assertEqual(len(uretim.cagrilar), 3)
        self.assertEqual([o["durum"] for o in d["ogeler"]], [kq.BITTI, kq.HATA, kq.BITTI])
        hatali = d["ogeler"][1]
        self.assertEqual((hatali["hata_kodu"], hatali["hata_turu"], hatali["hata_parca"]), ("ram", "MemoryError", 1))
        self.assertEqual(d["durum"], kq.TAMAMLANDI)
        ozet = (Path(d["oturum_klasoru"]) / "ozet.txt").read_text(encoding="utf-8")
        self.assertIn("hata kodu: ram", ozet)
        self.assertNotIn("özel metin", ozet)

    def test_art_arda_iki_sistemik_hatada_duraklatir(self):
        engel = SahteEngel()
        uretim = SahteUretim(hatalar=lambda istek, n: KodluHata("download"), engel=engel)
        k = self.yeni(uret_fn=uretim, engel=engel)
        for i in range(4):
            k.ekle("kutuphane", f"Öğe {i + 1}.")
        self.calistir(k)
        d = k.durum()
        self.assertEqual(len(uretim.cagrilar), 2, "ikinci sistemik hatadan sonra durmalı")
        self.assertEqual(d["durum"], kq.DURAKLATILDI)
        self.assertEqual(d["duraklatma"]["neden"], "download")
        self.assertEqual([o["durum"] for o in d["ogeler"]], [kq.BEKLIYOR] * 4, "hiçbir öğe kaybolmaz")
        self.assertEqual([o["son_hata_kodu"] for o in d["ogeler"][:2]], ["download", "download"])
        self.assertEqual((engel.giris, engel.cikis), (1, 1))
        # Sorun giderilince tek tıkla devam: hepsi üretilir.
        uretim.hatalar = {}
        self.calistir(k)
        self.assertEqual([o["durum"] for o in k.durum()["ogeler"]], [kq.BITTI] * 4)

    def test_disk_ve_indirme_karisik_da_sistemik(self):
        hatalar = {1: KodluHata("disk"), 2: KodluHata("download")}
        k = self.yeni(uret_fn=SahteUretim(hatalar=hatalar))
        for i in range(3):
            k.ekle("kutuphane", f"Öğe {i + 1}.")
        self.calistir(k)
        self.assertEqual(k.durum()["durum"], kq.DURAKLATILDI)

    def test_ardisik_olmayan_ya_da_sistemik_olmayan_hata_duraklatmaz(self):
        k = self.yeni(uret_fn=SahteUretim(hatalar={1: KodluHata("download"), 3: KodluHata("disk")}))
        for i in range(4):
            k.ekle("kutuphane", f"Öğe {i + 1}.")
        self.calistir(k)
        self.assertEqual([o["durum"] for o in k.durum()["ogeler"]], [kq.HATA, kq.BITTI, kq.HATA, kq.BITTI])
        self.assertEqual(k.durum()["durum"], kq.TAMAMLANDI)
        k2 = self.yeni(kok=self.kok / "iki", uret_fn=SahteUretim(hatalar=lambda i, n: KodluHata("ram")))
        for i in range(3):
            k2.ekle("kutuphane", f"Öğe {i + 1}.")
        self.calistir(k2)
        self.assertEqual([o["durum"] for o in k2.durum()["ogeler"]], [kq.HATA] * 3)
        self.assertEqual(k2.durum()["durum"], kq.TAMAMLANDI)

    def test_durdur_parca_bitince_ve_kaldigi_yerden_devam(self):
        uretim = SahteUretim()
        basladi, devam = uretim.beklet(1)
        k = self.yeni(uret_fn=uretim)
        uzun = k.ekle("kutuphane", uzun_metin(3), **self.ses())
        k.ekle("kutuphane", "Sonraki öğe.")
        self.assertTrue(k.baslat())
        self.assertTrue(basladi.wait(5))
        self.assertTrue(k.durdur())
        self.assertEqual(k.durum()["durum"], kq.DURUYOR)
        devam.set()
        self.assertTrue(k.bekle(10))
        d = k.durum()
        self.assertEqual(len(uretim.cagrilar), 1, "şu anki parça biter, sonraki başlamaz")
        self.assertEqual(d["durum"], kq.DURAKLATILDI)
        self.assertEqual(d["duraklatma"]["neden"], "kullanici")
        self.assertEqual((d["ogeler"][0]["durum"], d["ogeler"][0]["parca_bitti"]), (kq.BEKLIYOR, 1))
        self.calistir(k)
        self.assertEqual(uretim.parca_nolari(), [1, 2, 3, 1])
        self.assertEqual([c["oge_id"] for c in uretim.cagrilar[1:3]], [uzun["id"]] * 2)
        self.assertEqual([o["durum"] for o in k.durum()["ogeler"]], [kq.BITTI, kq.BITTI])

    def test_elle_uretim_parca_arasinda_araya_girer(self):
        uretim = SahteUretim()
        basladi, devam = uretim.beklet(1)
        k = self.yeni(uret_fn=uretim)
        k.ekle("kutuphane", "Bir.")
        k.ekle("kutuphane", "İki.")
        k.baslat()
        self.assertTrue(basladi.wait(5))
        with k.elle_uretim():
            devam.set()
            time.sleep(0.4)
            self.assertEqual(len(uretim.cagrilar), 1, "elle üretim varken yeni öğeye başlanmamalı")
            self.assertEqual(k.durum()["elle_bekleyen"], 1)
            self.assertEqual(k.durum()["durum"], kq.CALISIYOR)
        self.assertTrue(k.bekle(10))
        self.assertEqual(len(uretim.cagrilar), 2)

    def test_engel_varsa_duraklatir_ogeler_hata_olmaz(self):
        uretim = SahteUretim()
        k = self.yeni(uret_fn=uretim, blok_fn=lambda: "Ekran kartı kurulumu sürüyor")
        k.ekle("kutuphane", "Bir.")
        self.calistir(k)
        d = k.durum()
        self.assertEqual(uretim.cagrilar, [])
        self.assertEqual((d["durum"], d["duraklatma"]["neden"]), (kq.DURAKLATILDI, "blok"))
        self.assertEqual(d["ogeler"][0]["durum"], kq.BEKLIYOR)

    def test_efekt_ve_birlestirme(self):
        cagrilar = []

        def efekt(ham, hedef, efektler):
            cagrilar.append((Path(ham).name, efektler))
            shutil.copyfile(ham, hedef)

        k = self.yeni(efekt_fn=efekt)
        oge = k.ekle("kutuphane", uzun_metin(4), **self.ses(efektler=[{"ad": "oda", "yogunluk": 40}]))
        self.calistir(k)
        o = k.durum()["ogeler"][0]
        self.assertEqual(o["durum"], kq.BITTI)
        self.assertTrue(Path(o["cikti"]).is_file())
        self.assertTrue(Path(o["efektli"]).name.endswith("_efektli.wav"))
        self.assertTrue(Path(o["efektli"]).is_file())
        self.assertEqual(cagrilar[0][1], [{"ad": "oda", "yogunluk": 40}])
        self.assertTrue(cagrilar[0][0].endswith(kq.GECICI_EK))
        # 4 parça + 3 cümle arası duraklama tek dosyada.
        beklenen = 4 * PARCA_SN + 3 * 0.45
        self.assertAlmostEqual(o["ses_sn"], beklenen, delta=0.02)
        self.assertAlmostEqual(sf.info(o["cikti"]).duration, beklenen, delta=0.02)
        self.assertFalse((k.dizin / "parca" / oge["id"]).exists())

    def test_birlestirme_ya_da_efekt_hatasi_oge_hatasi_olur(self):
        def efekt(ham, hedef, efektler):
            raise OSError(28, "No space left on device")

        k = self.yeni(efekt_fn=efekt, siniflandir=lambda exc, oge: "disk")
        k.ekle("kutuphane", "Bir.", **self.ses(efektler=[{"ad": "oda", "yogunluk": 40}]))
        k.ekle("kutuphane", "İki.")
        self.calistir(k)
        d = k.durum()
        self.assertEqual(d["ogeler"][0]["hata_kodu"], "disk")
        self.assertIsNone(d["ogeler"][0]["hata_parca"])
        self.assertEqual(d["ogeler"][1]["durum"], kq.BITTI)
        self.assertFalse(list(k.cikti_dir.rglob(f"*{kq.GECICI_EK}")))

    def test_yeni_calistirma_yeni_klasor(self):
        k = self.yeni()
        k.ekle("kutuphane", "Bir.")
        self.calistir(k)
        k.ekle("kutuphane", "İki.")
        self.assertEqual(k.durum()["durum"], kq.HAZIR)
        self.calistir(k)
        klasorler = sorted(p.name for p in (k.cikti_dir / "kuyruk").iterdir())
        self.assertEqual(klasorler, ["2026-11-03_22-15_AI-ile-uretildi", "2026-11-03_22-15_AI-ile-uretildi-2"])
        self.assertTrue(list((k.cikti_dir / "kuyruk" / klasorler[1]).glob("01_*.wav")))

    def test_tahmin_olculen_hizla(self):
        k = self.yeni()
        k.ekle("kutuphane", "Bir.")
        self.assertIsNone(k.tahmin())
        self.calistir(k)
        k.ekle("kutuphane", "İki iki iki.")
        self.assertIsNotNone(k.durum()["kalan_tahmini_sn"])


class DuzenlemeTests(KuyrukTestBase):
    def test_cikar_yukari_asagi(self):
        uretim = SahteUretim()
        basladi, devam = uretim.beklet(1)
        k = self.yeni(uret_fn=uretim)
        ids = [k.ekle("kutuphane", f"Öğe {i}.")["id"] for i in range(4)]
        k.baslat()
        self.assertTrue(basladi.wait(5))
        with self.assertRaises(kq.KuyrukHatasi) as ctx:
            k.cikar(ids[0])
        self.assertEqual(ctx.exception.kod, "uretiliyor")
        self.assertFalse(k.yukari(ids[1]), "üretilen öğenin üstüne çıkılmaz")
        self.assertTrue(k.asagi(ids[1]))
        self.assertTrue(k.yukari(ids[3]))
        k.cikar(ids[2])
        self.assertEqual([o["id"] for o in k.durum()["ogeler"]], [ids[0], ids[3], ids[1]])
        devam.set()
        self.assertTrue(k.bekle(10))
        self.assertEqual([c["oge_id"] for c in uretim.cagrilar], [ids[0], ids[3], ids[1]])
        with self.assertRaises(kq.KuyrukHatasi) as ctx:
            k.cikar("yok")
        self.assertEqual(ctx.exception.kod, "oge_yok")

    def test_yeniden_dene_sona_alir_biten_parcalari_korur(self):
        uretim = SahteUretim(hatalar={2: RuntimeError("geçici")})
        k = self.yeni(uret_fn=uretim)
        uzun = k.ekle("kutuphane", uzun_metin(3), **self.ses())
        diger = k.ekle("kutuphane", "Diğer.")
        self.calistir(k)
        d = k.durum()
        self.assertEqual((d["ogeler"][0]["durum"], d["ogeler"][0]["hata_parca"], d["ogeler"][0]["parca_bitti"]),
                         (kq.HATA, 2, 1))
        with self.assertRaises(kq.KuyrukHatasi):
            k.yeniden_dene(diger["id"])  # bitmiş öğe yeniden denenmez
        k.yeniden_dene(uzun["id"])
        d = k.durum()
        self.assertEqual([o["id"] for o in d["ogeler"]], [diger["id"], uzun["id"]])
        self.assertEqual((d["ogeler"][1]["durum"], d["durum"]), (kq.BEKLIYOR, kq.HAZIR))
        self.calistir(k)
        self.assertEqual(uretim.parca_nolari()[-2:], [2, 3], "biten 1. parça yeniden üretilmez")
        self.assertEqual(k.durum()["ogeler"][1]["durum"], kq.BITTI)

    def test_temizle_ve_bitenleri_temizle(self):
        uretim = SahteUretim()
        basladi, devam = uretim.beklet(1)
        k = self.yeni(uret_fn=uretim)
        k.ekle("kutuphane", "Bir.", **self.ses())
        k.ekle("klon", "İki.", ref_kaynak=str(self.ref))
        k.baslat()
        self.assertTrue(basladi.wait(5))
        with self.assertRaises(kq.KuyrukHatasi) as ctx:
            k.temizle()
        self.assertEqual(ctx.exception.kod, "calisiyor")
        devam.set()
        self.assertTrue(k.bekle(10))
        cikti = Path(k.durum()["ogeler"][0]["cikti"])
        k.ekle("kutuphane", "Üç.")
        self.assertEqual(k.bitenleri_temizle(), 2)
        self.assertEqual(len(k.durum()["ogeler"]), 1)
        k.temizle()
        self.assertEqual(k.durum()["ogeler"], [])
        self.assertEqual(k.durum()["durum"], kq.BOS)
        self.assertFalse((k.dizin / "ref").exists())
        self.assertTrue(cikti.is_file(), "üretilen sesler asla silinmez")


class KalicilikTests(KuyrukTestBase):
    def test_kapat_ac_ayni_kuyruk_ve_kendiliginden_baslamaz(self):
        k = self.yeni()
        a = k.ekle("kutuphane", "Birinci metin.", **self.ses(duygu="Sakin", kalite="En İyi",
                                                           efektler=[{"ad": "oda", "yogunluk": 30}]))
        b = k.ekle("klon", uzun_metin(2), ref_kaynak=str(self.ref), ref_metin="Kayıt metni", duygu="Neşeli")
        c = k.ekle("kutuphane", "Üçüncü.")
        k.yukari(c["id"])
        once = k.durum()["ogeler"]

        uretim = SahteUretim()
        k2 = self.yeni(uret_fn=uretim)
        sonra = k2.durum()
        alanlar = ("id", "tur", "metin", "ses_id", "ses_adi", "ref", "ref_metin", "duygu", "kalite", "efektler",
                   "durum", "parca_sayisi")
        self.assertEqual([{f: o[f] for f in alanlar} for o in sonra["ogeler"]],
                         [{f: o[f] for f in alanlar} for o in once])
        self.assertEqual([o["id"] for o in sonra["ogeler"]], [a["id"], c["id"], b["id"]])
        self.assertTrue((k2.dizin / sonra["ogeler"][2]["ref"]).is_file())
        self.assertEqual(sonra["durum"], kq.DURAKLATILDI)
        self.assertEqual(sonra["duraklatma"]["neden"], "yeniden_acilis")
        self.assertEqual(sonra["onceki_bekleyen"], 3)
        time.sleep(0.3)
        self.assertFalse(k2.calisiyor)
        self.assertEqual(uretim.cagrilar, [], "açılışta kendiliğinden üretim başlamamalı")
        self.calistir(k2)
        self.assertEqual(len(uretim.cagrilar), 4)  # 1 + 1 + 2 parça

    def test_yarida_kalan_oge_bekliyora_doner_yarim_dosyalar_silinir(self):
        k = self.yeni()
        a = k.ekle("kutuphane", "Bir.")
        k.ekle("kutuphane", "İki.")
        # Çökme anındaki disk durumunu taklit et: öğe üretiliyor, kuyruk çalışıyor, yarım dosyalar var.
        veri = json.loads(k.yol.read_text(encoding="utf-8"))
        veri["durum"] = kq.CALISIYOR
        veri["oturum"], veri["oturum_bitti"] = "kuyruk/2026-11-03_22-15_AI-ile-uretildi", False
        veri["ogeler"][0].update(durum=kq.URETILIYOR, no=1)
        k.yol.write_text(json.dumps(veri), encoding="utf-8")
        oturum = k.cikti_dir / veri["oturum"]
        oturum.mkdir(parents=True)
        yarim = oturum / f"01_rastgele-ses_bir{kq.GECICI_EK}"
        yarim.write_bytes(b"RIFF")
        parca_yarim = k.dizin / "parca" / a["id"] / f"001{kq.GECICI_EK}"
        parca_yarim.parent.mkdir(parents=True)
        parca_yarim.write_bytes(b"RIFF")

        uretim = SahteUretim()
        k2 = self.yeni(uret_fn=uretim)
        d = k2.durum()
        self.assertEqual(d["durum"], kq.DURAKLATILDI)
        self.assertEqual((d["ogeler"][0]["durum"], d["ogeler"][0]["yarida_kaldi"]), (kq.BEKLIYOR, True))
        self.assertFalse(yarim.exists())
        self.assertFalse(parca_yarim.exists())
        time.sleep(0.3)
        self.assertEqual(uretim.cagrilar, [])
        self.calistir(k2)
        d = k2.durum()
        self.assertEqual([o["durum"] for o in d["ogeler"]], [kq.BITTI, kq.BITTI])
        self.assertEqual(Path(d["ogeler"][0]["cikti"]).parent, oturum, "aynı oturum klasörüne devam eder")

    def test_18_parcali_oge_7_parcadan_sonra_kapat_ac_8den_devam(self):
        anlik = self.kok / "anlik"

        def anlik_goruntu(istek, hedef):
            # 8. parçanın üretimi başlarken disk (kayıt + 7 biten parça) kopyalanır: çökme anının durumu.
            shutil.copytree(self.kok / "kuyruk", anlik / "kuyruk")
            if (self.kok / "outputs").exists():
                shutil.copytree(self.kok / "outputs", anlik / "outputs")

        ilk = SahteUretim(hatalar={8: RuntimeError("süreç burada öldü")})
        ilk.ozel[8] = anlik_goruntu
        k = self.yeni(uret_fn=ilk)
        oge = k.ekle("kutuphane", uzun_metin(18), **self.ses())
        self.assertEqual(oge["parca_sayisi"], 18)
        self.calistir(k)
        self.assertEqual(ilk.parca_nolari(), list(range(1, 9)))

        ikinci = SahteUretim()
        k2 = self.yeni(kok=anlik, uret_fn=ikinci)
        o = k2.durum()["ogeler"][0]
        self.assertEqual((o["durum"], o["yarida_kaldi"], o["parca_bitti"]), (kq.BEKLIYOR, True, 7))
        self.assertEqual(k2.durum()["durum"], kq.DURAKLATILDI)
        self.assertFalse(k2.calisiyor)
        self.calistir(k2)
        self.assertEqual(ikinci.parca_nolari(), list(range(8, 19)), "8. parçadan devam etmeli")
        o = k2.durum()["ogeler"][0]
        self.assertEqual(o["durum"], kq.BITTI)
        beklenen = 18 * PARCA_SN + 17 * 0.45
        self.assertAlmostEqual(sf.info(o["cikti"]).duration, beklenen, delta=0.03)

    def test_eksik_parca_dosyasi_yeniden_uretilir(self):
        ilk = SahteUretim(hatalar={3: RuntimeError("dur")})
        k = self.yeni(uret_fn=ilk)
        oge = k.ekle("kutuphane", uzun_metin(3), **self.ses())
        self.calistir(k)
        (k.dizin / "parca" / oge["id"] / "001.wav").unlink()
        ikinci = SahteUretim()
        k2 = self.yeni(uret_fn=ikinci)
        self.assertEqual(k2.durum()["ogeler"][0]["parca_bitti"], 1)
        k2.yeniden_dene(oge["id"])
        self.calistir(k2)
        self.assertEqual(ikinci.parca_nolari(), [1, 3])

    def test_bozuk_kayit_kenara_alinir(self):
        (self.kok / "kuyruk").mkdir()
        (self.kok / "kuyruk" / "kuyruk.json").write_text("{bozuk", encoding="utf-8")
        k = self.yeni()
        self.assertEqual(k.durum()["ogeler"], [])
        self.assertTrue(Path(k.durum()["bozuk_kayit"]).name.startswith("kuyruk.json.bozuk-"))
        self.assertTrue(Path(k.durum()["bozuk_kayit"]).is_file())
        k.ekle("kutuphane", "Yeni.")
        self.assertEqual(len(self.yeni().durum()["ogeler"]), 1)

    def test_kayit_yazilamazsa_onceki_dosya_bozulmaz(self):
        k = self.yeni()
        k.ekle("kutuphane", "Bir.")
        once = k.yol.read_text(encoding="utf-8")
        with mock.patch.object(kq.os, "replace", side_effect=PermissionError("kilitli")), \
                mock.patch.object(kq.time, "sleep"):
            k.ekle("kutuphane", "İki.")
        self.assertEqual(k.yol.read_text(encoding="utf-8"), once)
        self.assertEqual(k.durum()["kayit_hatasi"], "PermissionError")
        self.assertFalse(k.yol.with_name("kuyruk.json.yaz").exists())
        k.ekle("kutuphane", "Üç.")
        self.assertEqual(len(json.loads(k.yol.read_text(encoding="utf-8"))["ogeler"]), 3)
        self.assertIsNone(k.durum()["kayit_hatasi"])

    def test_ikinci_surec_kuyrugu_isleyemez(self):
        uretim = SahteUretim()
        basladi, devam = uretim.beklet(1)
        k = self.yeni(uret_fn=uretim)
        k.ekle("kutuphane", "Bir.")
        k.baslat()
        self.assertTrue(basladi.wait(5))
        k2 = self.yeni(uret_fn=SahteUretim())
        self.assertTrue(k2.durum()["salt_okunur"])
        self.assertEqual(k2.durum()["ogeler"][0]["durum"], kq.URETILIYOR, "çalışan kuyruk 'kurtarılmamalı'")
        for islem in (lambda: k2.ekle("kutuphane", "x."), k2.baslat):
            with self.assertRaises(kq.KuyrukHatasi) as ctx:
                islem()
            self.assertEqual(ctx.exception.kod, "baska_surec")
        devam.set()
        self.assertTrue(k.bekle(10))
        k3 = self.yeni()
        self.assertFalse(k3.durum()["salt_okunur"])
        self.assertEqual(k3.durum()["durum"], kq.TAMAMLANDI)


if __name__ == "__main__":
    unittest.main()
