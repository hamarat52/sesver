"""Bilinen başlatma hataları için kullanıcıya dönük, adım adım çözüm rehberi.

Yalnız standart kütüphane kullanır ve app/torch/numpy içe aktarmaz: bu kütüphaneler
yüklenemediğinde de (ör. Windows Akıllı Uygulama Denetimi DLL engeli) çalışmalıdır.
desktop.py içe aktarma ve sunucu hatalarında, macos_ortak.sh ise sesver_log.txt
üzerinden aynı algılamayı kullanır. Ayrıntı: AI_KURULUM.md #13.
"""

# Windows Akıllı Uygulama Denetimi (Smart App Control) / uygulama denetimi ilkesi
# engelinin kesin işaretleri (Türkçe ve İngilizce Windows ileti metinleri).
_KESIN_ISARETLER = (
    "uygulama denetimi",
    "application control",
    "blocked by group policy",
)
# Tek başına daha genel: eksik bir DLL/çalışma zamanı da aynı iletiyi verebilir.
_OLASI_ISARETLER = (
    "dll load failed",
)

_ADIMLAR = """\
Bu hata Windows'un 'Akıllı Uygulama Denetimi' güvenlik özelliğinden kaynaklanıyor, \
SesVer'de bir bozukluk değil. Windows, imzasız bir kütüphane dosyasını (genelde NumPy) \
engelledi.

Çözüm:
  1. Ayarlar'ı açın (Windows tuşu + I).
  2. Gizlilik ve Güvenlik > Windows Güvenliği'ne girin.
  3. Uygulama ve Tarayıcı Denetimi'ni açın.
  4. Akıllı Uygulama Denetimi Ayarları'na tıklayın.
  5. Kapalı'yı seçin (izin sorulursa Evet deyin).
  6. SesVer'i tekrar başlatın.

Ayrıntı: SesVer klasöründeki AI_KURULUM.md, madde 13."""

_OLASI_EK = """

Not: Hata metninde 'Uygulama Denetimi' geçmiyorsa ve bu özellik zaten kapalıysa \
sorun başka bir eksik dosya olabilir; sesver_log.txt dosyasındaki tam hatayı inceleyin."""


def smart_app_control_rehberi(metin):
    """Hata metni Akıllı Uygulama Denetimi engeline benziyorsa rehber metnini, değilse None döndürür."""
    if not metin:
        return None
    kucuk = str(metin).casefold()
    if any(i in kucuk for i in _KESIN_ISARETLER):
        return _ADIMLAR
    if any(i in kucuk for i in _OLASI_ISARETLER):
        return _ADIMLAR + _OLASI_EK
    return None


def _ana(argv):
    """Komut satırı: python hata_rehberi.py <dosya> — dosyada eşleşme varsa rehberi yazar, 0 döner; yoksa 1."""
    if len(argv) != 2:
        return 2
    try:
        with open(argv[1], encoding="utf-8", errors="replace") as f:
            rehber = smart_app_control_rehberi(f.read())
    except OSError:
        return 1
    if rehber is None:
        return 1
    print(rehber)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_ana(sys.argv))
