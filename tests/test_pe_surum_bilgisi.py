"""tools/pe_surum_bilgisi.py: Inno Setup'ın sürüm bilgisindeki boşluk yer tutucularının kırpılması.

Kök neden (CI 1.2.1, koşu 42358133201): Inno Setup dizgileri SetupLdr'ın sabit uzunluklu boşluk
yer tutucularının üstüne yazar; ProductName dosyada 'SesVer' + 54 boşluk olur. Bu testler aracın
Inno'nun yerleşimini doğru kırptığını ve kurulum programının geri kalanına dokunmadığını sınar.
Gerçek .exe yalnız CI'da derlenir; burada aynı yerleşimde küçük bir PE dosyası kurulur.
"""
import io
import struct
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tools import pe_surum_bilgisi as pe

ROOT = Path(__file__).resolve().parent.parent

# issrc Projects/Res/SetupLdr.version.rc (is-6_7_1): yer tutucu uzunlukları (karakter).
YER_TUTUCU = {"CompanyName": 60, "FileDescription": 60, "FileVersion": 20, "LegalCopyright": 100,
              "OriginalFileName": 50, "ProductName": 60, "ProductVersion": 50}
SESVER = {"CompanyName": "HamaratLabs", "FileDescription": "SesVer kurulum programı", "FileVersion": "1.2.1",
          "LegalCopyright": "Muhammed Yusuf Hamarat - Founder of HamaratLabs", "OriginalFileName": "",
          "ProductName": "SesVer", "ProductVersion": "1.2.1"}
YORUM = "This installation was built with Inno Setup."
KURULUM_VERISI = bytes(range(256)) * 64  # SetupLdr'ın dosya sonuna eklenen setup-0/1.bin yerine


def _metin(anahtar, deger):
    return pe.Dugum(anahtar, 1, (deger + "\0").encode("utf-16-le"), [])


def inno_surum_kaynagi(degerler=SESVER, doldur=True):
    """Inno'nun derlediği yerleşim: değer yer tutucunun başına yazılmış, kalanı boşluk.

    ``doldur=False``: aynı ağaç boşluksuz değerlerle (kırpmadan beklenen sonuç).
    """
    sabit = struct.pack("<13I", 0xFEEF04BD, 0x10000, 0x10002, 1, 0x10002, 1, 0x3F, 0, 4, 1, 0, 0, 0)
    dizgiler = [_metin("Comments", YORUM)]
    for anahtar, boy in YER_TUTUCU.items():
        dizgiler.append(_metin(anahtar, degerler[anahtar].ljust(boy) if doldur else degerler[anahtar]))
    kok = pe.Dugum("VS_VERSION_INFO", 0, sabit, [
        pe.Dugum("StringFileInfo", 1, b"", [pe.Dugum("000004b0", 1, b"", dizgiler)]),
        pe.Dugum("VarFileInfo", 1, b"", [pe.Dugum("Translation", 0, struct.pack("<HH", 0, 1200), [])]),
    ])
    return pe.serilestir(kok)


def kucuk_pe(surum, saglama=True, ek=KURULUM_VERISI):
    """Tek .rsrc bölümlü PE32: kaynak dizini RT_VERSION → 1 → dil 0 → veri; sonunda kurulum verisi."""
    dizin = bytearray()

    def dizin_yaz(kimlik, hedef):
        dizin.extend(struct.pack("<IIHHHH", 0, 0, 0, 0, 0, 1) + struct.pack("<II", kimlik, hedef))

    dizin_yaz(16, 0x80000000 | 0x18)
    dizin_yaz(1, 0x80000000 | 0x30)
    dizin_yaz(0, 0x48)
    dizin.extend(struct.pack("<IIII", 0x1000 + 0x58, len(surum), 0, 0))
    dizin.extend(b"\0" * (0x58 - len(dizin)))
    bolum = bytes(dizin) + surum
    ham_boy = (len(bolum) + 0x1FF) & ~0x1FF
    bolum += b"\0" * (ham_boy - len(bolum))

    dos = bytearray(0x40)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)
    coff = struct.pack("<HHIIIHH", 0x14C, 1, 0, 0, 0, 224, 0x102)
    opt = bytearray(224)
    struct.pack_into("<H", opt, 0, 0x10B)
    struct.pack_into("<I", opt, 92, 16)                       # NumberOfRvaAndSizes
    struct.pack_into("<II", opt, 96 + 16, 0x1000, len(bolum))  # kaynak dizini
    baslik = struct.pack("<8sIIIIIIHHI", b".rsrc", len(bolum), 0x1000, ham_boy, 0x200, 0, 0, 0, 0, 0x40000040)
    on = bytes(dos) + b"PE\0\0" + coff + bytes(opt) + baslik
    veri = bytearray(on + b"\0" * (0x200 - len(on)) + bolum + ek)
    if saglama:
        alan = 0x40 + 4 + 20 + 64
        struct.pack_into("<I", veri, alan, pe.pe_saglama_toplami(veri, alan))
    return veri


SAGLAMA_ALANI = 0x40 + 4 + 20 + 64
VERI_GIRDISI_BOYU = 0x200 + 0x48 + 4
KAYNAK_BASI = 0x200 + 0x58


class InnoYerTutucusuTests(unittest.TestCase):
    def test_derlenmis_hali_ci_gunlugundeki_gibi_bosluklu(self):
        """Kök neden: kırpılmadan önce değerler yer tutucu uzunluğunda (CI günlüğündeki 'SesVer   ...')."""
        ham = {k: v for (_t, k), v in pe.dizgiler(kucuk_pe(inno_surum_kaynagi())).items()}
        self.assertEqual(ham["ProductName"], "SesVer" + " " * 54)
        self.assertEqual(ham["ProductVersion"], "1.2.1" + " " * 45)
        self.assertEqual(ham["FileVersion"], "1.2.1" + " " * 15)

    def test_kirpinca_degerler_tam_sesver_ve_surum(self):
        veri = kucuk_pe(inno_surum_kaynagi())
        degisen = pe.kirp(veri)
        sonra = {k: v for (_t, k), v in pe.dizgiler(veri).items()}
        self.assertEqual(sonra, {"Comments": YORUM, **SESVER})
        self.assertEqual(set(k for _t, k in degisen), set(YER_TUTUCU))  # Comments'te boşluk yoktu

    def test_yeni_kaynak_microsoft_yapisiyla_tutarli(self):
        """wLength/wValueLength yeniden hesaplanır; veri girdisinin boyu yeni kaynağın boyu."""
        veri = kucuk_pe(inno_surum_kaynagi())
        pe.kirp(veri)
        boy = struct.unpack_from("<I", veri, VERI_GIRDISI_BOYU)[0]
        yeni = bytes(veri[KAYNAK_BASI:KAYNAK_BASI + boy])
        self.assertEqual(struct.unpack_from("<H", yeni, 0)[0], boy)
        self.assertEqual(pe.serilestir(pe._coz(yeni, 0)), yeni)
        self.assertLess(boy, len(inno_surum_kaynagi()))
        self.assertEqual(yeni, inno_surum_kaynagi(doldur=False))  # baştan boşluksuz yazılmışla birebir
        urun = next(d for _t, d in pe.dizgi_dugumleri(pe._coz(yeni, 0)) if d.anahtar == "ProductName")
        self.assertEqual(urun.deger, "SesVer\0".encode("utf-16-le"))

    def test_string_dugumu_elle_yazilmis_yerlesimle_ayni(self):
        """Serileştirme bağımsız bir elle hesaba göre: başlık 6 bayt, anahtar + NUL, 4'e hizalama, değer."""
        beklenen = (struct.pack("<HHH", 38, 3, 1) + "ProductName\0".encode("utf-16-le") + b"\0\0"
                    + "Ab\0".encode("utf-16-le"))
        self.assertEqual(pe.serilestir(_metin("ProductName", "Ab")), beklenen)

    def test_kurulum_programinin_geri_kalani_degismez(self):
        """SetupLdr ofset tablosu, gömülü veri ve dosya boyu korunur; değişen yalnız sürüm kaynağı."""
        for saglama in (True, False):
            with self.subTest(saglama=saglama):
                once = bytes(kucuk_pe(inno_surum_kaynagi(), saglama=saglama))
                veri = bytearray(once)
                pe.kirp(veri)
                self.assertEqual(len(veri), len(once))
                self.assertTrue(bytes(veri).endswith(KURULUM_VERISI))
                eski_boy = len(inno_surum_kaynagi())
                izinli = set(range(KAYNAK_BASI, KAYNAK_BASI + eski_boy))
                izinli |= set(range(VERI_GIRDISI_BOYU, VERI_GIRDISI_BOYU + 4))
                izinli |= set(range(SAGLAMA_ALANI, SAGLAMA_ALANI + 4))
                disarida = [i for i in range(len(once)) if once[i] != veri[i] and i not in izinli]
                self.assertEqual(disarida, [])
                yeni_boy = struct.unpack_from("<I", veri, VERI_GIRDISI_BOYU)[0]
                self.assertEqual(bytes(veri[KAYNAK_BASI + yeni_boy:KAYNAK_BASI + eski_boy]),
                                 b"\0" * (eski_boy - yeni_boy))

    def test_pe_saglama_toplami_guncellenir_sifirsa_sifir_kalir(self):
        veri = kucuk_pe(inno_surum_kaynagi())
        eski = struct.unpack_from("<I", veri, SAGLAMA_ALANI)[0]
        pe.kirp(veri)
        yeni = struct.unpack_from("<I", veri, SAGLAMA_ALANI)[0]
        self.assertNotEqual(yeni, eski)
        self.assertEqual(yeni, pe.pe_saglama_toplami(veri, SAGLAMA_ALANI))
        veri = kucuk_pe(inno_surum_kaynagi(), saglama=False)
        pe.kirp(veri)
        self.assertEqual(struct.unpack_from("<I", veri, SAGLAMA_ALANI)[0], 0)

    def test_ikinci_kirpma_hicbir_sey_degistirmez(self):
        veri = kucuk_pe(inno_surum_kaynagi())
        pe.kirp(veri)
        ilk = bytes(veri)
        self.assertEqual(pe.kirp(veri), {})
        self.assertEqual(bytes(veri), ilk)

    def test_bozuk_dosyada_hata_ve_dosyaya_dokunulmaz(self):
        with tempfile.TemporaryDirectory() as d:
            for ad, icerik in (("metin.exe", b"MZ" + b"\0" * 10), ("pe_degil.exe", b"bir metin dosyasi" * 10)):
                with self.subTest(ad=ad):
                    yol = Path(d) / ad
                    yol.write_bytes(icerik)
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as hata:
                        self.assertEqual(pe.main(["--kirp", str(yol)]), 2)
                    self.assertIn("HATA:", hata.getvalue())
                    self.assertEqual(yol.read_bytes(), icerik)

    def test_komut_satiri_kirpar_ve_ham_degeri_yazar(self):
        with tempfile.TemporaryDirectory() as d:
            yol = Path(d) / "SesVer-Kurulum-1.2.1.exe"
            yol.write_bytes(bytes(kucuk_pe(inno_surum_kaynagi())))
            boy = yol.stat().st_size
            with redirect_stdout(io.StringIO()) as cikti:
                self.assertEqual(pe.main(["--kirp", str(yol)]), 0)
            metin = cikti.getvalue()
            self.assertIn("ProductName: 'SesVer' + 54 sondaki boşluk", metin)  # kök neden günlüğe girer
            self.assertIn("ProductName: 'SesVer' + 0 sondaki boşluk", metin)
            self.assertEqual(yol.stat().st_size, boy)
            sonra = {k: v for (_t, k), v in pe.dizgiler(bytearray(yol.read_bytes())).items()}
            self.assertEqual((sonra["ProductName"], sonra["ProductVersion"]), ("SesVer", "1.2.1"))


class IssDegerleriYerTutucuyaSigarTests(unittest.TestCase):
    def test_iss_dosya_ozellikleri_kesilmez(self):
        """Yer tutucunun öbür yüzü: daha uzun metin sessizce kesilir (SetupLdr.version.rc)."""
        metin = (ROOT / "windows" / "SesVer.iss").read_text(encoding="utf-8")
        surum = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        tanim = {"AppName": "SesVer", "AppVersion": surum, "AppPublisher": "HamaratLabs"}
        for anahtar, inno in (("ProductName", "VersionInfoProductName"), ("ProductVersion", "VersionInfoProductTextVersion"),
                              ("FileVersion", "VersionInfoTextVersion"), ("CompanyName", "VersionInfoCompany"),
                              ("FileDescription", "VersionInfoDescription"), ("LegalCopyright", "VersionInfoCopyright")):
            satir = next(s for s in metin.splitlines() if s.startswith(inno + "="))
            deger = satir.split("=", 1)[1]
            for ad, karsilik in tanim.items():
                deger = deger.replace("{#%s}" % ad, karsilik)
            with self.subTest(anahtar=anahtar):
                self.assertNotIn("{#", deger)
                self.assertLessEqual(len(deger), YER_TUTUCU[anahtar])
                if anahtar in SESVER and anahtar not in ("FileVersion", "ProductVersion"):
                    self.assertEqual(deger, SESVER[anahtar])


if __name__ == "__main__":
    unittest.main()
