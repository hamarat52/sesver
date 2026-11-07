"""Windows ilk kurulum durum satırı biçimi — TEK KAYNAK.

Üretici: WINDOWS_BASLAT.bat yalnız-kurulum kipinde (SESVER_YALNIZ_KURULUM=1 ya da
``/yalniz-kurulum`` argümanı) her adımda ``{app}\\kurulum_durum.txt`` dosyasına TEK satır
yazar (``:durum`` alt yordamı)::

    <adım no>/<toplam>|<ASCII kısa metin>

Son satır ``<n>/<toplam>|tamam`` ya da ``<n>/<toplam>|hata:<ADIM>`` olur. Tüm çıktı
``kurulum_log.txt``'ye, betiği çalıştıran cmd.exe'nin PID'i ``kurulum_pid.txt``'ye gider.

Tüketici: windows/SesVer.iss ``[Code]`` (DurumSatiriniAyristir / OrtamBitisiniIsle) bu
satırı ~0,5 sn'de bir okuyup ilerleme çubuğunu günceller. ``pascal_ayristir`` ve
``bitis`` o Pascal işlevlerinin birebir Python karşılığıdır.

Bu modül uygulamaya paketlenmez (tools/); tests/test_windows_kurulum.py bat, iss ve
buradaki sabitlerin birbiriyle eşleştiğini sınar. Biçimi değiştirirseniz üçünü birlikte
güncelleyin.
"""
import re

DURUM_DOSYASI = "kurulum_durum.txt"
GUNLUK_DOSYASI = "kurulum_log.txt"
PID_DOSYASI = "kurulum_pid.txt"
YALNIZ_KURULUM_ARGUMANI = "/yalniz-kurulum"
YALNIZ_KURULUM_ORTAM_DEGISKENI = "SESVER_YALNIZ_KURULUM"
# Sessiz kurulumda (/VERYSILENT) ilk kurulumu açan Setup parametresi ve başarısızlık kodu.
ORTAMKUR_PARAMETRESI = "/ORTAMKUR"
ORTAM_HATA_CIKIS_KODU = 30

TOPLAM_ADIM = 6
TAMAM = "tamam"
HATA_ONEKI = "hata:"
AYIRICI = "|"

# Adımlar (bat'taki ``call :durum N "..."`` numaraları; iss'te OrtamAdim0..6 mesajları).
ADIMLAR = {
    0: "Basliyor",
    1: "Python indiriliyor",
    2: "pip",
    3: "Ekran karti algilama",
    4: "PyTorch (CUDA etiketi ya da CPU)",
    5: "voxcpm",
    6: "Paketler (requirements.txt)",
}

# Geçerli satır: rakamlar, "/", rakamlar, "|", en az bir yazdırılabilir ASCII karakter.
SATIR = re.compile(r"^(\d+)/(\d+)\|([\x20-\x7e]+)$")


def bicimle(adim, metin, toplam=TOPLAM_ADIM):
    """Bat'ın yazdığı satırı üretir (testlerde beklenen değer)."""
    return f"{adim}/{toplam}{AYIRICI}{metin}"


def ayristir(satir):
    """Katı ayrıştırma: (adım, toplam, metin) ya da biçim dışıysa None."""
    m = SATIR.match(satir)
    if not m:
        return None
    adim, toplam, metin = int(m.group(1)), int(m.group(2)), m.group(3).strip()
    if toplam <= 0 or adim > toplam or not metin:
        return None
    return adim, toplam, metin


def _str_to_int_def(s, varsayilan):
    # Delphi StrToIntDef'in bu biçimde karşılaşılan kısmı: yalnız ondalık rakamlar.
    return int(s) if s.isdigit() else varsayilan


def pascal_ayristir(satir):
    """windows/SesVer.iss DurumSatiriniAyristir'in birebir karşılığı (1 tabanlı Pos/Copy)."""
    cizgi = satir.find("|") + 1  # Pos: bulunamazsa 0
    if cizgi < 4:
        return None
    sol = satir[: cizgi - 1]
    bolu = sol.find("/") + 1
    if bolu < 2:
        return None
    adim = _str_to_int_def(sol[: bolu - 1], -1)
    toplam = _str_to_int_def(sol[bolu:], -1)
    metin = satir[cizgi:].strip()
    if adim >= 0 and toplam > 0 and adim <= toplam and metin:
        return adim, toplam, metin
    return None


def bitis(metin):
    """OrtamBitisiniIsle karşılığı: ("tamam", None) / ("hata", ADIM) / None (sürüyor)."""
    if metin == TAMAM:
        return "tamam", None
    if metin.startswith(HATA_ONEKI):
        return "hata", metin[len(HATA_ONEKI):]
    return None


# --- Paylaşılabilir günlük -------------------------------------------------------------
# Kurulum hata ya da iptalle bitince sihirbaz (PaylasilabilirGunlukYaz) kurulum_log.txt'den
# ev klasörü yolları gizlenmiş PAYLAS_GUNLUK_DOSYASI'nı üretir; kullanıcıya gönderilmesi
# söylenen dosya budur. Aşağıdaki işlevler windows/SesVer.iss'teki HarfDuyarsizDegistir,
# IlkEvIsareti, EvYollariniMaskele ve GunlukMaskele'nin birebir (1 tabanlı) karşılığıdır.

PAYLAS_GUNLUK_DOSYASI = "kurulum_log_paylas.txt"
EV_MASKESI = "<ev>"
EV_ISARETLERI = (":\\users\\", ":\\\\users\\\\", ":/users/")
EV_ADI_BITISLERI = "\\/\"'<>|\t\n\r"


def _pascal_lowercase(s):
    # Inno Lowercase: yalnız 7 bit A-Z küçülür (uzunluk korunur).
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)


def pascal_harf_duyarsiz_degistir(metin, bul, yeni):
    if bul == "":
        return metin
    sonuc, kalan = "", metin
    kucuk_bul, kucuk = _pascal_lowercase(bul), _pascal_lowercase(kalan)
    p = kucuk.find(kucuk_bul) + 1
    while p > 0:
        sonuc += kalan[: p - 1] + yeni
        kalan = kalan[p - 1 + len(bul):]
        kucuk = kucuk[p - 1 + len(bul):]
        p = kucuk.find(kucuk_bul) + 1
    return sonuc + kalan


def pascal_ilk_ev_isareti(kucuk):
    """(konum, işaret uzunluğu); yoksa (0, 0). Konum 1 tabanlıdır (Pascal Pos)."""
    sonuc, uzunluk = 0, 0
    for isaret in EV_ISARETLERI:
        p = kucuk.find(isaret) + 1
        if p > 0 and (sonuc == 0 or p < sonuc):
            sonuc, uzunluk = p, len(isaret)
    return sonuc, uzunluk


def pascal_ev_yollarini_maskele(metin):
    sonuc, kalan = "", metin
    kucuk = _pascal_lowercase(kalan)
    p, uzunluk = pascal_ilk_ev_isareti(kucuk)
    while p > 0:
        bas = p
        if p > 1 and "a" <= kucuk[p - 2] <= "z":  # Pascal Kucuk[P - 1]
            bas = p - 1
        son = p + uzunluk
        while son <= len(kalan) and kalan[son - 1] not in EV_ADI_BITISLERI:
            son += 1
        sonuc += kalan[: bas - 1] + EV_MASKESI
        kalan = kalan[son - 1:]
        kucuk = kucuk[son - 1:]
        p, uzunluk = pascal_ilk_ev_isareti(kucuk)
    return sonuc + kalan


def pascal_gunluk_maskele(metin, ev, kisa_ad=None):
    """GunlukMaskele karşılığı. ``kisa_ad``: GetShortName(ev) sonucu (yoksa ev)."""
    sonuc = metin
    if len(ev) > 3:
        egik = ev.replace("\\", "/")
        kisa = ev if kisa_ad is None else kisa_ad
        sonuc = pascal_harf_duyarsiz_degistir(sonuc, ev, EV_MASKESI)
        sonuc = pascal_harf_duyarsiz_degistir(sonuc, egik, EV_MASKESI)
        if kisa and kisa != ev:
            sonuc = pascal_harf_duyarsiz_degistir(sonuc, kisa, EV_MASKESI)
    return pascal_ev_yollarini_maskele(sonuc)
