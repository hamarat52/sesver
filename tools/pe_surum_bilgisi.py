"""Kurulum programının (Inno Setup) sürüm bilgisi dizgilerindeki sondaki boşlukları kırpar.

Neden (kök neden, Inno Setup kaynağıyla): Inno Setup, Setup.exe'yi hazır bir yükleyiciden
(SetupLdr) üretir. Yükleyicinin sürüm kaynağında her dizgi sabit uzunlukta bir boşluk yer
tutucusudur (issrc Projects/Res/SetupLdr.version.rc: "The spaces are placeholders. Longer texts
will be truncated to the placeholder length."). Derleyici değeri yer tutucunun başına kopyalar,
kalan boşluklara ve uzunluk alanlarına dokunmaz (Projects/Src/Compiler.ExeUpdateFunc.pas,
UpdateStringValue: Move(NewValue, Value, Min(Length(NewValue), lstrlenW(Value)))). Sonuç dosyanın
kendisinde ProductName = "SesVer" + 54 boşluk, ProductVersion = "1.2.1" + 45 boşluk olur.

SignPath Foundation imzalanan dosyalarda ürün adı/sürümü özniteliklerinin proje adıyla ve derleme
sürümüyle aynı olmasını şart koşar ve bunu "file metadata restrictions" (pe-file product-name,
product-version) ile denetler; belgeleri karşılaştırmada boşluğun kırpılıp kırpılmadığını
söylemez. Bu yüzden değerler imzadan önce dosyanın kendisinde tam "SesVer" / VERSION yapılır.

Ne yapar: RT_VERSION kaynağını (VS_VERSIONINFO ağacı) çözer, StringFileInfo altındaki dizgilerin
sondaki boşluklarını atar ve ağacı Microsoft'un yapı kurallarıyla (wLength, wValueLength, 32 bit
hizalama) yeniden yazar. Yeni kaynak eskisinden kısa olduğundan aynı yere sığar; artakalan baytlar
sıfırlanır ve kaynak veri girdisindeki boyut güncellenir. Dosya boyu, bölümler ve dosyanın sonundaki
kurulum verisi değişmez (SetupLdr yalnız ofset tablosunun CRC'sini, dosya boyunu ve gömülü verinin
CRC'lerini denetler: Projects/SetupLdr.dpr). Başlıktaki PE sağlama toplamı sıfır değilse yeniden
hesaplanır. İmzalamadan ÖNCE çalıştırılır (sonra çalıştırmak imzayı bozar).

Kullanım:
  python tools/pe_surum_bilgisi.py DOSYA.exe            dizgileri ham hâliyle yazar
  python tools/pe_surum_bilgisi.py --kirp DOSYA.exe     kırpar, sonucu yazar
Yalnız standart kütüphane. Sınayan: tests/test_pe_surum_bilgisi.py.
"""
import argparse
import array
import struct
import sys

RT_VERSION = 16


class PEHatasi(Exception):
    """Beklenmeyen PE ya da sürüm kaynağı biçimi."""


def _u16(veri, konum):
    return struct.unpack_from("<H", veri, konum)[0]


def _u32(veri, konum):
    return struct.unpack_from("<I", veri, konum)[0]


def _hizala(n):
    return (n + 3) & ~3


# --- PE başlıkları ve kaynak dizini ---------------------------------------------------------

def _basliklar(veri):
    """(sağlama toplamı alanının konumu, kaynak dizininin RVA'sı, bölümler)."""
    if len(veri) < 0x40 or veri[:2] != b"MZ":
        raise PEHatasi("MZ imzası yok")
    pe = _u32(veri, 0x3C)
    if veri[pe:pe + 4] != b"PE\0\0":
        raise PEHatasi("PE imzası yok")
    coff = pe + 4
    bolum_sayisi, opt_boyu = _u16(veri, coff + 2), _u16(veri, coff + 16)
    opt = coff + 20
    sihir = _u16(veri, opt)
    if sihir == 0x10B:
        dizin = opt + 96
    elif sihir == 0x20B:
        dizin = opt + 112
    else:
        raise PEHatasi(f"tanınmayan isteğe bağlı başlık: {sihir:#x}")
    if _u32(veri, dizin - 4) < 3:
        raise PEHatasi("kaynak dizini girdisi yok")
    kaynak_rva = _u32(veri, dizin + 2 * 8)
    if not kaynak_rva:
        raise PEHatasi("kaynak bölümü yok")
    bolumler = []
    for i in range(bolum_sayisi):
        b = opt + opt_boyu + 40 * i
        sanal_boy, sanal_adres, ham_boy, ham_konum = struct.unpack_from("<IIII", veri, b + 8)
        bolumler.append((sanal_adres, min(sanal_boy, ham_boy) or ham_boy, ham_konum))
    return opt + 64, kaynak_rva, bolumler


def _dosya_konumu(rva, bolumler):
    for sanal_adres, boy, ham_konum in bolumler:
        if sanal_adres <= rva < sanal_adres + boy:
            return ham_konum + rva - sanal_adres
    raise PEHatasi(f"RVA {rva:#x} hiçbir bölümün dosyadaki kısmında değil")


def _girdi(veri, dizin_konumu, kimlik=None):
    """Kaynak dizinindeki (kimlik verilmezse ilk) kimlikli girdinin OffsetToData değeri."""
    adli, kimlikli = _u16(veri, dizin_konumu + 12), _u16(veri, dizin_konumu + 14)
    for i in range(adli, adli + kimlikli):
        ad, hedef = struct.unpack_from("<II", veri, dizin_konumu + 16 + 8 * i)
        if kimlik is None or ad == kimlik:
            return hedef
    raise PEHatasi(f"kaynak girdisi yok: {kimlik}")


def _surum_kaynagi(veri):
    """(veri girdisinin konumu, sürüm kaynağının dosyadaki konumu, boyu, sağlama toplamı alanı)."""
    sagla, kaynak_rva, bolumler = _basliklar(veri)
    kok = _dosya_konumu(kaynak_rva, bolumler)
    hedef = _girdi(veri, kok, RT_VERSION)
    for _ in range(2):  # tür → ad (ilk) → dil (ilk)
        if not hedef & 0x80000000:
            raise PEHatasi("sürüm kaynağı dizin yapısı beklenmedik")
        hedef = _girdi(veri, kok + (hedef & 0x7FFFFFFF))
    if hedef & 0x80000000:
        raise PEHatasi("sürüm kaynağı veri girdisi beklenmedik")
    girdi = kok + hedef
    veri_rva, boy = struct.unpack_from("<II", veri, girdi)
    bas = _dosya_konumu(veri_rva, bolumler)
    if bas % 4 or bas + boy > len(veri):
        raise PEHatasi("sürüm kaynağının konumu ya da boyu beklenmedik")
    return girdi, bas, boy, sagla


# --- VS_VERSIONINFO ağacı -------------------------------------------------------------------

class Dugum:
    """VS_VERSIONINFO / StringFileInfo / StringTable / String / VarFileInfo / Var düğümü."""

    def __init__(self, anahtar, tur, deger, cocuklar):
        self.anahtar = anahtar
        self.tur = tur          # 1: metin (değer UTF-16 + NUL), 0: ikili
        self.deger = deger      # ham değer baytları
        self.cocuklar = cocuklar

    def metin(self):
        """Metin değeri, ilk NUL'a kadar (sondaki boşluklar dahil)."""
        return self.deger.decode("utf-16-le").split("\0", 1)[0]


def _coz(kaynak, bas):
    """``kaynak`` içinde ``bas`` konumundaki düğümü çözer (konumlar kaynağın başına göre)."""
    if bas + 6 > len(kaynak):
        raise PEHatasi("sürüm kaynağı kesik")
    uzunluk, deger_uzunlugu, tur = struct.unpack_from("<HHH", kaynak, bas)
    son = bas + uzunluk
    if uzunluk < 6 or son > len(kaynak) or tur not in (0, 1):
        raise PEHatasi("sürüm kaynağında bozuk düğüm")
    k = bas + 6
    while kaynak[k:k + 2] != b"\0\0":
        k += 2
        if k >= son:
            raise PEHatasi("sürüm kaynağında anahtar sonu yok")
    anahtar = bytes(kaynak[bas + 6:k]).decode("utf-16-le")
    deger_bas = _hizala(k + 2)
    deger_son = deger_bas + (deger_uzunlugu * 2 if tur == 1 else deger_uzunlugu)
    if deger_son > son:
        raise PEHatasi(f"{anahtar!r} değeri düğümden taşıyor")
    cocuklar = []
    c = _hizala(deger_son)
    while c + 6 <= son:
        cocuk_uzunlugu = _u16(kaynak, c)
        if not cocuk_uzunlugu:
            break
        cocuklar.append(_coz(kaynak, c))
        c = _hizala(c + cocuk_uzunlugu)
    return Dugum(anahtar, tur, bytes(kaynak[deger_bas:deger_son]), cocuklar)


def _yaz_dugum(d, cikti):
    """Düğümü ``cikti``ya (bytearray, başı kaynağın başı) ekler; wLength'i sonradan doldurur."""
    bas = len(cikti)
    deger_uzunlugu = len(d.deger) // 2 if d.tur == 1 else len(d.deger)
    cikti += struct.pack("<HHH", 0, deger_uzunlugu, d.tur)
    cikti += (d.anahtar + "\0").encode("utf-16-le")
    cikti += b"\0" * (_hizala(len(cikti)) - len(cikti))
    cikti += d.deger
    for cocuk in d.cocuklar:
        cikti += b"\0" * (_hizala(len(cikti)) - len(cikti))
        _yaz_dugum(cocuk, cikti)
    struct.pack_into("<H", cikti, bas, len(cikti) - bas)


def agac(veri):
    """Dosyadaki sürüm kaynağının ağacı."""
    _girdi_konumu, bas, boy, _sagla = _surum_kaynagi(veri)
    kok = _coz(bytes(veri[bas:bas + boy]), 0)
    if kok.anahtar != "VS_VERSION_INFO":
        raise PEHatasi(f"kök düğüm VS_VERSION_INFO değil: {kok.anahtar!r}")
    return kok


def serilestir(kok):
    cikti = bytearray()
    _yaz_dugum(kok, cikti)
    return bytes(cikti)


def dizgi_dugumleri(kok):
    """StringFileInfo altındaki (dil tablosu, String düğümü) çiftleri."""
    for bilgi in kok.cocuklar:
        if bilgi.anahtar != "StringFileInfo":
            continue
        for tablo in bilgi.cocuklar:
            for dizgi in tablo.cocuklar:
                if dizgi.tur == 1:
                    yield tablo.anahtar, dizgi


def dizgiler(veri):
    """{(dil tablosu, anahtar): ham metin}; ham metin sondaki boşlukları da içerir."""
    sonuc = {(tablo, d.anahtar): d.metin() for tablo, d in dizgi_dugumleri(agac(veri))}
    if not sonuc:
        raise PEHatasi("StringFileInfo dizgisi yok")
    return sonuc


def pe_saglama_toplami(veri, alan):
    """MapFileAndCheckSum ile aynı hesap: alan sıfır sayılır, 16 bitlik toplam katlanır, boy eklenir."""
    kopya = bytearray(veri)
    kopya[alan:alan + 4] = b"\0\0\0\0"
    if len(kopya) % 2:
        kopya += b"\0"
    kelimeler = array.array("H")
    kelimeler.frombytes(bytes(kopya))
    if sys.byteorder != "little":
        kelimeler.byteswap()
    toplam = sum(kelimeler)
    while toplam >> 16:
        toplam = (toplam & 0xFFFF) + (toplam >> 16)
    return (toplam + len(veri)) & 0xFFFFFFFF


def kirp(veri):
    """``veri`` (bytearray) içindeki dizgilerin sondaki boşluklarını kırpar.

    Dosya boyu değişmez. {(dil tablosu, anahtar): (eski, yeni)} döner; değişen yoksa dosyaya
    dokunulmaz.
    """
    girdi, bas, boy, sagla = _surum_kaynagi(veri)
    kok = _coz(bytes(veri[bas:bas + boy]), 0)
    degisen = {}
    for tablo, d in dizgi_dugumleri(kok):
        eski = d.metin()
        yeni = eski.rstrip(" ")
        if yeni != eski:
            d.deger = (yeni + "\0").encode("utf-16-le")
            degisen[(tablo, d.anahtar)] = (eski, yeni)
    if not degisen:
        return degisen
    yeni_kaynak = serilestir(kok)
    if len(yeni_kaynak) > boy:
        raise PEHatasi("yeni sürüm kaynağı eskisinden uzun")
    veri[bas:bas + boy] = yeni_kaynak + b"\0" * (boy - len(yeni_kaynak))
    struct.pack_into("<I", veri, girdi + 4, len(yeni_kaynak))
    if _u32(veri, sagla):
        struct.pack_into("<I", veri, sagla, pe_saglama_toplami(veri, sagla))
    return degisen


def _yaz(baslik, degerler):
    print(baslik)
    for (tablo, anahtar), metin in sorted(degerler.items()):
        bosluk = len(metin) - len(metin.rstrip(" "))
        print(f"  [{tablo}] {anahtar}: {metin.rstrip(' ')!r} + {bosluk} sondaki boşluk")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):  # Windows konsol kod sayfasında Türkçe harf çökertmesin
        sys.stdout.reconfigure(errors="backslashreplace")
        sys.stderr.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dosya")
    ap.add_argument("--kirp", action="store_true", help="sondaki boşlukları dosyada kırp")
    a = ap.parse_args(argv)
    with open(a.dosya, "rb") as f:
        veri = bytearray(f.read())
    try:
        _yaz("Sürüm kaynağı (dosyadan, ham):", dizgiler(veri))
        if not a.kirp:
            return 0
        boy = len(veri)
        degisen = kirp(veri)
        sonra = dizgiler(veri)
        if len(veri) != boy:
            raise PEHatasi("dosya boyu değişti")
        kalan = sorted(k for (_t, k), m in sonra.items() if m != m.rstrip(" "))
        if kalan:
            raise PEHatasi(f"kırpmadan sonra boşluk kaldı: {kalan}")
    except PEHatasi as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    if degisen:
        with open(a.dosya, "r+b") as f:
            f.write(veri)
    _yaz(f"Kırpıldı ({len(degisen)} dizgi; dosya boyu değişmedi: {boy} bayt):", sonra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
