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


def _pascal_ansi_lowercase(s):
    # Inno AnsiLowercase (CharLowerBuff): ASCII dışı harfler de küçülür, her karakter tek
    # karaktere gider (uzunluk korunur). Python'un tam eşlemesi 'İ'yi iki karaktere açar;
    # Windows'un basit eşlemesi 'i' verir.
    cikti = []
    for c in s:
        k = c.lower()
        cikti.append(k if len(k) == 1 else ("i" if c == "\u0130" else c))
    return "".join(cikti)


def pascal_harf_duyarsiz_degistir(metin, bul, yeni):
    if bul == "":
        return metin
    sonuc, kalan = "", metin
    kucuk_bul, kucuk = _pascal_ansi_lowercase(bul), _pascal_ansi_lowercase(kalan)
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


# --- Günlük kodlaması (bulgu B) ----------------------------------------------------------
# WINDOWS_BASLAT.bat yalnız-kurulum kipinde PID satırından sonra ``chcp 65001`` ve
# ``PYTHONIOENCODING=utf-8`` ile günlüğü UTF-8 yazar. Sihirbaz (PaylasilabilirGunlukBaytlari)
# geçerli UTF-8 günlüğü UTF-8 çözer; değilse ANSI kod sayfasıyla çözer ve ev klasörünü UTF-8
# baytlarının ANSI okunuşuyla da arar. Aşağıdakiler GecerliUtf8 ve PaylasilabilirGunlukBaytlari
# işlevlerinin karşılığıdır. ``ansi``: Windows'un ANSI kod sayfası (Türkçe Windows: cp1254).

BAT_KOD_SAYFASI_SATIRI = "chcp 65001 >nul 2>nul"
BAT_PYTHON_KODLAMA_SATIRI = 'set "PYTHONIOENCODING=utf-8"'


def pascal_gecerli_utf8(b):
    """GecerliUtf8 karşılığı (1 tabanlı döngü 0 tabanlıya çevrildi)."""
    n, i = len(b), 0
    while i < n:
        c = b[i]
        alt, ust = 0x80, 0xBF
        if c < 0x80:
            ek = 0
        elif 0xC2 <= c <= 0xDF:
            ek = 1
        elif 0xE0 <= c <= 0xEF:
            ek = 2
            if c == 0xE0:
                alt = 0xA0
            if c == 0xED:
                ust = 0x9F
        elif 0xF0 <= c <= 0xF4:
            ek = 3
            if c == 0xF0:
                alt = 0x90
            if c == 0xF4:
                ust = 0x8F
        else:
            return False
        if i + ek >= n:
            if ek:
                return False
        if ek:
            if not alt <= b[i + 1] <= ust:
                return False
            if any(not 0x80 <= x <= 0xBF for x in b[i + 2:i + ek + 1]):
                return False
        i += ek + 1
    return True


def ansi_coz(b, ansi="cp1254"):
    """String(AnsiString) karşılığı: tanımsız baytlar Windows'taki gibi aynı kod noktasına gider."""
    return "".join(bytes([x]).decode(ansi, errors="ignore") or chr(x) for x in b)


def ansi_kodla(s, ansi="cp1254"):
    """AnsiString(String) karşılığı: kod sayfasında olmayan karakter '?' olur."""
    cikti = bytearray()
    for ch in s:
        try:
            cikti += ch.encode(ansi)
        except UnicodeEncodeError:
            cikti += bytes([ord(ch)]) if ord(ch) < 256 and not bytes([ord(ch)]).decode(ansi, "ignore") else b"?"
    return bytes(cikti)


def pascal_paylasilabilir_gunluk_baytlari(ham, ev, kisa_ad=None, ansi="cp1254"):
    """PaylasilabilirGunlukBaytlari karşılığı: ham günlük baytlarından paylaşılabilir kopya baytları."""
    if pascal_gecerli_utf8(ham):
        return pascal_gunluk_maskele(ham.decode("utf-8"), ev, kisa_ad).encode("utf-8")
    # GetShortName var olmayan (yanlış okunmuş) yol için uzun adı döndürür: kısa ad = ev.
    metin = pascal_gunluk_maskele(ansi_coz(ham, ansi), ansi_coz(ev.encode("utf-8"), ansi))
    metin = pascal_gunluk_maskele(metin, ansi_coz(_pascal_ansi_lowercase(ev).encode("utf-8"), ansi))
    return ansi_kodla(pascal_gunluk_maskele(metin, ev, kisa_ad), ansi)


# --- Açılışta güncelleme denetimi (kurulum sihirbazı seçeneği) ------------------------------
# Sihirbazın "Gizlilik ve güncelleme denetimi" sayfasındaki kutu uygulamanın Ayarlar'daki
# aynı seçeneğidir: {app}\ayarlar.json "guncelleme_kontrolu" (guncelleme.AYAR_ANAHTARI).
# Aşağıdakiler windows/SesVer.iss AyarGovdesiGecerli, GuncellemeDegerKonumu,
# GuncellemeAyariAcikMi, GuncellemeAyariniYerlestir ve GuncellemeKarari karşılığıdır.

AYAR_DOSYASI = "ayarlar.json"
GUNCELLEME_AYAR_ANAHTARI = "guncelleme_kontrolu"
GUNCELLEME_PARAMETRESI = "/GUNCELLEMEDENETIMI"


def _pascal_trim_left(s):
    # Delphi TrimLeft: baştaki kontrol karakterleri ve boşluk (<= ' ').
    i = 0
    while i < len(s) and s[i] <= " ":
        i += 1
    return s[i:]


def _pascal_trim(s):
    s = _pascal_trim_left(s)
    j = len(s)
    while j > 0 and s[j - 1] <= " ":
        j -= 1
    return s[:j]


def pascal_ayar_govdesi_gecerli(metin):
    g = _pascal_trim(metin)
    return len(g) >= 2 and g[0] == "{" and g[-1] == "}"


def pascal_guncelleme_deger_konumu(metin):
    """Değerin 1 tabanlı başlangıç konumu; yoksa 0."""
    p = metin.find(f'"{GUNCELLEME_AYAR_ANAHTARI}"') + 1
    if p == 0:
        return 0
    i = p + len(GUNCELLEME_AYAR_ANAHTARI) + 2
    while i <= len(metin) and metin[i - 1] <= " ":
        i += 1
    if metin[i - 1:i] != ":":
        return 0
    i += 1
    while i <= len(metin) and metin[i - 1] <= " ":
        i += 1
    return i


def pascal_guncelleme_ayari_acik_mi(metin):
    if not pascal_ayar_govdesi_gecerli(metin):
        return True
    p = pascal_guncelleme_deger_konumu(metin)
    return metin[p - 1:p + 4] != "false" if p > 0 else True


def pascal_guncelleme_ayarini_yerlestir(metin, acik):
    deger = "true" if acik else "false"
    anahtar = f'  "{GUNCELLEME_AYAR_ANAHTARI}": {deger}'
    if not pascal_ayar_govdesi_gecerli(metin):
        return "{\n" + anahtar + "\n}\n"
    p = pascal_guncelleme_deger_konumu(metin)
    if p > 0:
        son = p
        while son <= len(metin) and metin[son - 1] not in ",}] \t\n\r":
            son += 1
        return metin[:p - 1] + deger + metin[son - 1:]
    p = metin.find("{") + 1
    kalan = metin[p:]
    if _pascal_trim_left(kalan)[:1] == "}":
        return metin[:p] + "\n" + anahtar + "\n" + _pascal_trim_left(kalan)
    return metin[:p] + "\n" + anahtar + "," + kalan


# GuncellemeYazimBicimi sonuçları (SesVer.iss const bölümü).
AYAR_YOK, AYAR_TANIDIK, AYAR_BOZUK, AYAR_DEGER_BEKLENMEDIK = 0, 1, 2, 3
AYAR_YEDEK_EKI = ".bozuk"
AYAR_YEDEK_SINIRI = 20


def _pascal_deger_sinirinda_mi(metin, i):
    return i > len(metin) or metin[i - 1] in ",}] \t\n\r"


def pascal_guncelleme_yazim_bicimi(metin):
    """Dosya yerinde düzenlenebilir mi (AYAR_* değerlerinden biri)."""
    if _pascal_trim(metin) == "":
        return AYAR_YOK
    if not pascal_ayar_govdesi_gecerli(metin):
        return AYAR_BOZUK
    p = pascal_guncelleme_deger_konumu(metin)
    if p == 0:
        return AYAR_TANIDIK
    for kelime in ("true", "false"):
        if metin[p - 1:p - 1 + len(kelime)] == kelime and _pascal_deger_sinirinda_mi(metin, p + len(kelime)):
            return AYAR_TANIDIK
    return AYAR_DEGER_BEKLENMEDIK


def pascal_ayar_yedek_adi(yol, var_mi):
    """AyarYedekAdi: ``yol`` + .bozuk, sonra .bozuk-2 ... .bozuk-20; hepsi doluysa ''."""
    sonuc = yol + AYAR_YEDEK_EKI
    n = 2
    while var_mi(sonuc):
        if n > AYAR_YEDEK_SINIRI:
            return ""
        sonuc = f"{yol}{AYAR_YEDEK_EKI}-{n}"
        n += 1
    return sonuc


def pascal_guncelleme_tercihini_uygula(ham, okunabildi, sessiz, parametre, kutu, var_mi):
    """GuncellemeTercihiniUygula'nın dosya sonucu: (yeni ayar baytları ya da None, yedek adı ya da None).

    ``ham``: dosyanın baytları (yoksa b''); ``okunabildi``: LoadStringFromFile sonucu.
    """
    if not okunabildi:
        return None, None
    metin = ham.decode("utf-8") if pascal_gecerli_utf8(ham) else ansi_coz(ham)
    mevcut = pascal_guncelleme_ayari_acik_mi(metin)
    yaz, yeni = pascal_guncelleme_karari(sessiz, parametre, kutu, mevcut)
    if not yaz:
        return None, None
    bicim = pascal_guncelleme_yazim_bicimi(metin)
    if bicim == AYAR_DEGER_BEKLENMEDIK:
        return None, None
    yedek = None
    if bicim == AYAR_BOZUK:
        yedek = pascal_ayar_yedek_adi(AYAR_DOSYASI, var_mi)
        if not yedek:
            return None, None
    return pascal_guncelleme_ayarini_yerlestir(metin, yeni).encode("utf-8"), yedek


def pascal_guncelleme_karari(sessiz, parametre, kutu, mevcut):
    """(yazılsın mı, yeni değer). parametre: 0/1, verilmediyse -1."""
    if sessiz:
        if parametre < 0:
            return False, None
        yeni = parametre == 1
    else:
        yeni = kutu
    return yeni != mevcut, yeni
