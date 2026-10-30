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
