"""Toplu içe aktarma: TXT (tek/paragraf), CSV (UTF-8, UTF-8 BOM, Windows-1254; `,` `;`; TR/EN başlık),
red nedenleri, kuyruk sınırı ve önizlemeden kuyruğa ekleme."""
import codecs
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ice_aktarma as ia  # noqa: E402
import kuyruk as kq  # noqa: E402

VERI = Path(__file__).resolve().parent / "veri" / "ice_aktarma"


def oku(ad):
    return (VERI / ad).read_bytes()


class SesKatalogu:
    def __init__(self, ref):
        self.sesler = {ia.katla(ad): {"id": sid, "ad": ad, "ref_wav": str(ref), "ref_text": f"{ad} kaydı"}
                       for sid, ad in (("masalci", "Yaşlı Masalcı"), ("belgesel", "Belgesel Anlatıcı"),
                                       ("heyecanli", "Heyecanlı Sunucu"))}

    def __call__(self, ad):
        return self.sesler.get(ia.katla(ad))


class IceAktarmaTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.kok = Path(self._tmp.name)
        self.ref = self.kok / "ref.wav"
        self.ref.write_bytes(b"RIFF0000WAVE")
        self.ses_bul = SesKatalogu(self.ref)
        self.varsayilan = {"tur": "kutuphane", "ses_id": "belgesel", "ses_adi": "Belgesel Anlatıcı",
                           "ref_kaynak": str(self.ref), "ref_metin": "Belgesel kaydı", "duygu": "Nötr",
                           "kalite": "Dengeli", "efektler": [{"ad": "oda", "yogunluk": 30}]}

    def tearDown(self):
        self._tmp.cleanup()


class KodlamaTests(unittest.TestCase):
    def test_coz(self):
        metin = "Şişli'de ığdır çiçekleri; ĞÜŞİÖÇ"
        self.assertEqual(ia.coz(metin.encode("utf-8")), (metin, "utf-8"))
        self.assertEqual(ia.coz(codecs.BOM_UTF8 + metin.encode("utf-8")), (metin, "utf-8-sig"))
        self.assertEqual(ia.coz(metin.encode("cp1254")), (metin, "cp1254"))
        self.assertEqual(ia.coz(metin.encode("utf-16")), (metin, "utf-16"))
        self.assertEqual(ia.coz(b"a\r\nb\rc")[0], "a\nb\nc")

    def test_katla(self):
        for a, b in (("METİN", "metin"), ("Ses Adı", "ses adi"), ("\ufeffmetin", "metin"), ("VOICE", "voice"),
                     ("Duygu/Ton", "duygu ton"), ("YAŞLI MASALCI", "yasli masalci"), ("En İyi", "en iyi")):
            self.assertEqual(ia.katla(a), b)


class CsvTests(IceAktarmaTestBase):
    def assert_tr_noktalivirgul(self, oz, kodlama):
        self.assertEqual(oz.hata, "")
        self.assertEqual(oz.kodlama, kodlama)
        self.assertEqual(oz.ayrac, ";")
        self.assertEqual([o["satir"] for o in oz.ogeler], [2, 3, 7])
        self.assertEqual(oz.ogeler[0]["metin"], "Çok güzel bir gün, ışıl ışıl güneş doğdu.")
        self.assertEqual(oz.ogeler[1]["metin"], 'Öğretmen dedi ki: "Şimdi başlıyoruz"; herkes sustu.')
        self.assertEqual((oz.ogeler[0]["ses_id"], oz.ogeler[0]["duygu"], oz.ogeler[0]["kalite"]),
                         ("masalci", "Sakin", "Dengeli"))
        self.assertEqual((oz.ogeler[1]["ses_id"], oz.ogeler[1]["kalite"]), ("belgesel", "En İyi"))
        self.assertEqual((oz.ogeler[2]["ses_id"], oz.ogeler[2]["duygu"], oz.ogeler[2]["kalite"]),
                         (kq.RASTGELE, "Neşeli", "Hızlı"))
        self.assertEqual([(r["satir"], r["neden"]) for r in oz.reddedilen],
                         [(4, "metin_bos"), (5, "bilinmeyen_ses"), (6, "bilinmeyen_duygu")])
        self.assertEqual(oz.reddedilen[1]["ozet"], "Bilinmeyen sesli satır.")

    def test_turkce_noktali_virgul_utf8_bom_ve_cp1254_ayni_sonuc(self):
        for ad, kodlama in (("tr_noktalivirgul_utf8.csv", "utf-8"), ("tr_noktalivirgul_utf8_bom.csv", "utf-8-sig"),
                            ("tr_noktalivirgul_cp1254.csv", "cp1254")):
            with self.subTest(ad=ad):
                self.assert_tr_noktalivirgul(ia.onizle_csv(oku(ad), self.varsayilan, self.ses_bul), kodlama)

    def test_virgul_ve_buyuk_harfli_turkce_baslik(self):
        for ad, kodlama in (("tr_virgul_utf8.csv", "utf-8"), ("tr_virgul_cp1254.csv", "cp1254")):
            with self.subTest(ad=ad):
                oz = ia.onizle_csv(oku(ad), self.varsayilan, self.ses_bul)
                self.assertEqual((oz.hata, oz.ayrac, oz.kodlama), ("", ",", kodlama))
                self.assertEqual([o["metin"] for o in oz.ogeler],
                                 ["Şişli'de ığdır çiçekleri açtı", "Gün ağarırken çoban türküsünü söyledi"])
                self.assertEqual([(o["ses_id"], o["duygu"]) for o in oz.ogeler],
                                 [("masalci", "Neşeli"), ("belgesel", "Üzgün")])
                self.assertEqual(oz.ogeler[0]["kalite"], "Dengeli", "sütun yoksa ekranda seçilen kalite")
                self.assertEqual(oz.reddedilen, [])

    def test_ingilizce_baslik_ve_degerler(self):
        oz = ia.onizle_csv(oku("en_virgul_utf8.csv"), self.varsayilan, self.ses_bul)
        self.assertEqual(oz.ayrac, ",")
        self.assertEqual([o["metin"] for o in oz.ogeler], ["Hello, world. This is a test.", "Second line", "Third line"])
        self.assertEqual([(o["ses_id"], o["duygu"], o["kalite"]) for o in oz.ogeler],
                         [("masalci", "Sakin", "Dengeli"), ("belgesel", "Üzgün", "En İyi"),
                          ("belgesel", "Nötr", "Hızlı")])  # boş ses hücresi → ekranda seçilen ses
        self.assertEqual([(r["satir"], r["neden"]) for r in oz.reddedilen], [(5, "bilinmeyen_kalite")])

    def test_kayitli_ses_ayarlari_ve_ekran_varsayilanlari(self):
        oz = ia.onizle_csv(oku("tr_noktalivirgul_utf8.csv"), self.varsayilan, self.ses_bul)
        o = oz.ogeler[0]
        self.assertEqual((o["ref_kaynak"], o["ref_metin"], o["ses_adi"]), (str(self.ref), "Yaşlı Masalcı kaydı",
                                                                           "Yaşlı Masalcı"))
        self.assertEqual(o["efektler"], [{"ad": "oda", "yogunluk": 30}])
        self.assertIsNone(oz.ogeler[2]["ref_kaynak"], "rastgele seste referans yok")

    def test_uzunluk_ve_rastgele_uzun_reddi(self):
        tampon = io.StringIO()
        y = csv.writer(tampon, delimiter=";")
        y.writerow(["metin", "ses"])
        y.writerow(["Kısa. " * 150, "Yaşlı Masalcı"])  # 900 karakter, kayıtlı ses: kabul (parçalanır)
        y.writerow(["Kısa. " * 150, "rastgele"])  # rastgele + uzun: red
        y.writerow(["a" * (kq.OGE_METIN_EN_FAZLA + 1), "Yaşlı Masalcı"])
        oz = ia.onizle_csv(tampon.getvalue().encode("utf-8"), self.varsayilan, self.ses_bul)
        self.assertEqual(len(oz.ogeler), 1)
        self.assertEqual(oz.uzun_sayisi, 1)
        self.assertEqual([(r["satir"], r["neden"]) for r in oz.reddedilen], [(3, "rastgele_uzun"), (4, "metin_uzun")])

    def test_kuyruk_siniri_asan_satirlar_soylenir(self):
        satirlar = ["metin"] + [f"Metin {i}." for i in range(12)]
        oz = ia.onizle_csv("\n".join(satirlar).encode("utf-8"), self.varsayilan, self.ses_bul, kalan_yer=10)
        self.assertEqual(len(oz.ogeler), 10)
        self.assertEqual(oz.asan, [12, 13])

    def test_dosya_duzeyi_hatalar(self):
        self.assertEqual(ia.onizle_csv(b"ses;duygu\nYasli;Sakin\n", self.varsayilan, self.ses_bul).hata,
                         "metin_sutunu_yok")
        self.assertEqual(ia.onizle_csv(b"\n \n", self.varsayilan, self.ses_bul).hata, "dosya_bos")
        self.assertEqual(ia.onizle_csv(b"x" * (ia.DOSYA_EN_FAZLA_BAYT + 1)).hata, "dosya_buyuk")
        oz = ia.onizle_csv("metin;not;ses\nMerhaba.;x;Yaşlı Masalcı\n".encode("utf-8"), self.varsayilan, self.ses_bul)
        self.assertEqual(oz.yok_sayilan_sutunlar, ["not"])
        self.assertEqual(len(oz.ogeler), 1)

    def test_csv_okuyucu_hatasi_dosya_hatasi_olur(self):
        """Siberguvenlik 1.3.0 bulgu C: 128 KB'yi aşan hücre csv.Error fırlatıyordu; artık dosya
        düzeyi hata (csv_okunamadi), hiçbir öğe eklenmez. Başlıkta ve satırda ayrı ayrı denenir."""
        dev = "a" * (csv.field_size_limit() + 1)
        for veri in (f"metin;ses\nMerhaba.;rastgele\n\"{dev}\";rastgele\n", f"\"metin{dev}\";ses\nMerhaba.;x\n"):
            with self.subTest(baslikta=veri.startswith('"')):
                oz = ia.onizle_csv(veri.encode("utf-8"), self.varsayilan, self.ses_bul)
                self.assertEqual(oz.hata, "csv_okunamadi")
                self.assertEqual((oz.ogeler, oz.reddedilen), ([], []))

    def test_sablon_excel_uyumlu_ve_kendi_kendini_okur(self):
        for dil in ("tr", "en"):
            veri = ia.sablon_csv(dil)
            self.assertTrue(veri.startswith(codecs.BOM_UTF8))
            self.assertIn(b"\r\n", veri)
            oz = ia.onizle_csv(veri, self.varsayilan, self.ses_bul)
            self.assertEqual((oz.hata, oz.ayrac, oz.reddedilen), ("", ";", []))
            self.assertGreaterEqual(len(oz.ogeler), 2)

    def test_onizleme_onaydan_sonra_kuyruga_eklenir(self):
        oz = ia.onizle_csv(oku("tr_noktalivirgul_cp1254.csv"), self.varsayilan, self.ses_bul)
        k = kq.Kuyruk(dizin=self.kok / "kuyruk", cikti_dir=self.kok / "outputs")
        self.assertEqual(k.durum()["ogeler"], [], "önizleme kuyruğa bir şey eklememeli")
        eklenen = k.ekle_toplu(oz.istekler())
        self.assertEqual([o["metin"] for o in eklenen], [o["metin"] for o in oz.ogeler])
        self.assertEqual([o["ses_id"] for o in eklenen], ["masalci", "belgesel", kq.RASTGELE])
        self.assertTrue((k.dizin / eklenen[0]["ref"]).is_file())


class TxtTests(IceAktarmaTestBase):
    def test_paragraf_kipi_utf8_ve_cp1254(self):
        for ad, kodlama in (("paragraflar_utf8.txt", "utf-8"), ("paragraflar_cp1254.txt", "cp1254")):
            with self.subTest(ad=ad):
                oz = ia.onizle_txt(oku(ad), "paragraf", self.varsayilan)
                self.assertEqual((oz.hata, oz.kodlama), ("", kodlama))
                self.assertEqual(len(oz.ogeler), 3)
                self.assertTrue(oz.ogeler[0]["metin"].startswith("Birinci paragraf: Bir varmış"))
                self.assertIn("\n", oz.ogeler[0]["metin"], "paragraf içindeki satırlar korunur")
                self.assertEqual(oz.ogeler[1]["metin"], "İkinci paragraf: Çocuk ığdır ağacının gölgesinde şöyle düşünmüş.")
                self.assertEqual([o["ses_id"] for o in oz.ogeler], ["belgesel"] * 3)
                self.assertEqual(oz.ogeler[2]["efektler"], [{"ad": "oda", "yogunluk": 30}])

    def test_tek_oge_kipi(self):
        oz = ia.onizle_txt(oku("paragraflar_utf8.txt"), "tek", self.varsayilan)
        self.assertEqual(len(oz.ogeler), 1)
        self.assertTrue(oz.ogeler[0]["metin"].endswith("muradına ermiş."))

    def test_uzun_masal_tek_oge_ve_sinirlar(self):
        masal = ("Bir varmış bir yokmuş, evvel zaman içinde. " * 200).encode("utf-8")  # ~8800 karakter
        oz = ia.onizle_txt(masal, "tek", self.varsayilan)
        self.assertEqual((len(oz.ogeler), oz.uzun_sayisi), (1, 1))
        rastgele = dict(self.varsayilan, ses_id=kq.RASTGELE, ref_kaynak=None)
        self.assertEqual(ia.onizle_txt(masal, "tek", rastgele).reddedilen[0]["neden"], "rastgele_uzun")
        cok_uzun = ("a" * (kq.OGE_METIN_EN_FAZLA + 1)).encode()
        self.assertEqual(ia.onizle_txt(cok_uzun, "tek", self.varsayilan).reddedilen[0]["neden"], "metin_uzun")
        self.assertEqual(ia.onizle_txt(b"  \n\n ", "paragraf", self.varsayilan).hata, "dosya_bos")
        self.assertEqual(ia.onizle_txt(b"x", "satir", self.varsayilan).hata, "kip_gecersiz")
        paragraflar = "\n\n".join(f"Paragraf {i}." for i in range(60)).encode()
        oz = ia.onizle_txt(paragraflar, "paragraf", self.varsayilan, kalan_yer=50)
        self.assertEqual((len(oz.ogeler), len(oz.asan)), (50, 10))


class DegerTablosuTests(unittest.TestCase):
    def test_duygu_ve_kalite_anahtarlari_uygulamayla_ayni(self):
        import app
        self.assertEqual(set(ia.DUYGULAR), set(app.EMOTIONS))
        self.assertEqual(set(ia.KALITELER), set(app.QUALITY))


if __name__ == "__main__":
    unittest.main()
