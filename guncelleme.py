"""Açılışta "yeni sürüm var" kontrolü (Aşama 1 — yalnız bildirim, otomatik güncelleme YOK).

Akış: başlatıcı (desktop.py / app.py) açılışta `baslat()` çağırır; GitHub'ın
"latest release" uç noktası arka plan thread'inde tek bir GET ile sorgulanır.
Arayüz yüklenince `sonuc()` en fazla toplam süre sınırına (ZAMAN_ASIMI_SN,
başlangıçtan itibaren) kadar bekler; yeni sürüm yoksa ya da herhangi bir hata
olursa None döner ve arayüzde hiçbir şey gösterilmez.

Gizlilik: istek yalnız GET'tir; gövdesi yoktur. Başlıklarda yalnız User-Agent
(SesVer/<sürüm>) ve Accept vardır. Kullanıcının sesleri, metinleri ve dosya
yolları hiçbir şekilde gönderilmez.

Kapatmak için: Ayarlar → "Açılışta güncellemeleri denetle" (ayarlar.json:
"guncelleme_kontrolu": false), Windows kurulum sihirbazındaki aynı kutu (sessiz kurulumda
/GUNCELLEMEDENETIMI=0; windows/SesVer.iss ayarlar.json'a yazar) ya da SESVER_GUNCELLEME_KONTROLU=0 (ayrıca
false/hayir/no/off; ortam değişkeni ayardan önce gelir).
Yalnız standart kütüphane kullanır.
"""
import html
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass

import i18n
import surum
from i18n import t

log = logging.getLogger("sesver")

REPO = "hamarat52/sesver"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
_GUVENLI_SAYFA_ONEKI = f"https://github.com/{REPO}/releases/"
ORTAM_DEGISKENI = "SESVER_GUNCELLEME_KONTROLU"
AYAR_ANAHTARI = "guncelleme_kontrolu"  # ayarlar.json; yoksa açık
ZAMAN_ASIMI_SN = 3.0  # ağ isteği + bekleme için TOPLAM üst sınır
_KAPALI = {"0", "false", "hayir", "hayır", "no", "off"}
_SURUM_RE = re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class YeniSurum:
    surum: str      # "1.2.3" (v öneki temizlenmiş)
    sayfa: str      # release sayfası (yalnız bu reponun github.com adresi)


def surum_parcala(metin):
    """'v1.10.0' / '1.10.0' -> (1, 10, 0). Biçim tutmazsa None."""
    if not isinstance(metin, str):
        return None
    m = _SURUM_RE.match(metin.strip())
    return tuple(int(p) for p in m.groups()) if m else None


def daha_yeni_mi(uzak, yerel):
    """Sayısal karşılaştırma (1.10.0 > 1.9.0). Ayrıştırılamayan sürüm -> False."""
    u, y = surum_parcala(uzak), surum_parcala(yerel)
    return bool(u and y and u > y)


def ayar_acik_mi():
    """Ayarlar'daki "Açılışta güncellemeleri denetle" (varsayılan: açık)."""
    return i18n.get_setting(AYAR_ANAHTARI, True) is not False


def ayar_degistir(acik):
    """Ayarı ayarlar.json'a yazar; bir sonraki açılıştan itibaren geçerlidir."""
    acik = bool(acik)
    i18n.set_setting(AYAR_ANAHTARI, acik)
    log.info("Güncelleme kontrolü ayarı: %s.", "açık" if acik else "kapalı")
    return acik


def kontrol_acik_mi(ortam=None, ayar=None):
    """Ortam değişkeni kapalıysa hayır; değilse Ayarlar'daki seçim (ayar=None → ayarlar.json)."""
    deger = (os.environ if ortam is None else ortam).get(ORTAM_DEGISKENI, "")
    if deger.strip().lower() in _KAPALI:
        return False
    return ayar_acik_mi() if ayar is None else bool(ayar)


def _istek_yap(url, zaman_asimi):
    istek = urllib.request.Request(url, method="GET", headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"SesVer/{surum.__version__}",
    })
    with urllib.request.urlopen(istek, timeout=zaman_asimi) as yanit:  # noqa: S310 — sabit https adresi
        return json.loads(yanit.read(256 * 1024).decode("utf-8"))


class _Yanit(Exception):
    """Yanıt geldi ama kullanılamadı (beklenmeyen biçim, taslak/ön sürüm, tanınmayan etiket)."""


def _son_surum(istek, zaman_asimi):
    """GitHub'daki son kararlı sürüm: (uzak_surum, guvenli_sayfa). Kullanılamazsa _Yanit."""
    veri = istek(API_URL, zaman_asimi)
    if not isinstance(veri, dict):
        raise _Yanit("beklenmeyen yanıt")
    if veri.get("draft") or veri.get("prerelease"):
        raise _Yanit("son release taslak/ön sürüm")
    etiket = veri.get("tag_name")
    parcalar = surum_parcala(etiket)
    if parcalar is None:
        raise _Yanit(f"tanınmayan sürüm etiketi {etiket!r}")
    sayfa = veri.get("html_url")
    # Bağlantı yalnız bu reponun release sayfası olabilir; başka her adres yerine sabit adres.
    if not (isinstance(sayfa, str) and sayfa.startswith(_GUVENLI_SAYFA_ONEKI)):
        sayfa = RELEASES_URL
    return ".".join(str(p) for p in parcalar), sayfa


def kontrol_et(yerel=None, zaman_asimi=ZAMAN_ASIMI_SN, istek=_istek_yap, kayit=None):
    """Yeni sürüm varsa YeniSurum, yoksa/hata olursa None. Asla istisna fırlatmaz.

    Her çağrı log'a en fazla bir satır yazar (kayit, varsayılan log.info).
    """
    yerel = surum.__version__ if yerel is None else yerel
    kayit = log.info if kayit is None else kayit
    try:
        veri = istek(API_URL, zaman_asimi)
        if not isinstance(veri, dict):
            kayit("Güncelleme kontrolü: beklenmeyen yanıt, atlandı.")
            return None
        if veri.get("draft") or veri.get("prerelease"):
            kayit("Güncelleme kontrolü: son release taslak/ön sürüm, yok sayıldı.")
            return None
        etiket = veri.get("tag_name")
        parcalar = surum_parcala(etiket)
        if parcalar is None:
            kayit("Güncelleme kontrolü: tanınmayan sürüm etiketi %r, atlandı.", etiket)
            return None
        uzak = ".".join(str(p) for p in parcalar)
        if not daha_yeni_mi(uzak, yerel):
            kayit("Güncelleme kontrolü: güncel (yerel %s, son %s).", yerel, uzak)
            return None
        sayfa = veri.get("html_url")
        if not (isinstance(sayfa, str) and sayfa.startswith(_GUVENLI_SAYFA_ONEKI)):
            sayfa = RELEASES_URL
        kayit("Güncelleme kontrolü: yeni sürüm var v%s (yerel %s).", uzak, yerel)
        return YeniSurum(uzak, sayfa)
    except Exception as exc:  # noqa: BLE001 — internet yok/rate limit/bozuk yanıt: sessiz kal
        kayit("Güncelleme kontrolü yapılamadı (%s: %s); bildirim gösterilmeyecek.",
                 type(exc).__name__, str(exc)[:120])
        return None


# --- Elle denetim: Ayarlar → "Güncellemeleri şimdi denetle" ------------------------------
# Kullanıcı bastığı için "Açılışta güncellemeleri denetle" kapalıyken (ve ortam değişkeni
# kapalıyken) de çalışır. Aynı istek: tek GET, gövdesiz, yalnız User-Agent/Accept.
ELLE_ZAMAN_ASIMI_SN = 10.0


@dataclass(frozen=True)
class Denetim:
    durum: str          # "guncel" | "yeni" | "hata"
    yerel: str
    uzak: str = ""      # GitHub'daki son sürüm (guncel/yeni)
    sayfa: str = ""     # yalnız _GUVENLI_SAYFA_ONEKI ile başlayan adres (yeni)
    neden: str = ""     # hata: "internet" | "zaman_asimi" | "sinir" | "yanit"


def _hata_nedeni(exc):
    import socket
    import urllib.error
    if isinstance(exc, _Yanit):
        return "yanit"
    if isinstance(exc, urllib.error.HTTPError):
        return "sinir" if exc.code in (403, 429) else "yanit"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "zaman_asimi"
    if isinstance(exc, urllib.error.URLError):
        return "zaman_asimi" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "internet"
    if isinstance(exc, OSError):
        return "internet"
    return "yanit"


class _ElleDenetleyici:
    """Aynı anda yalnız bir istek: süren bir denetim varken gelen çağrı yeni istek atmaz,
    sürenin sonucunu bekleyip onu döndürür (art arda basma, iki sekme)."""

    def __init__(self):
        self._kilit = threading.Lock()
        self._suren = None  # (Event, [sonuc])

    def __call__(self, yerel=None, zaman_asimi=ELLE_ZAMAN_ASIMI_SN, istek=_istek_yap):
        with self._kilit:
            suren = self._suren
            if suren is None:
                suren = self._suren = (threading.Event(), [None])
                sahibi = True
            else:
                sahibi = False
        olay, kutu = suren
        if not sahibi:
            olay.wait(zaman_asimi + 1.0)
            return kutu[0] or Denetim("hata", surum.__version__ if yerel is None else yerel, neden="zaman_asimi")
        try:
            kutu[0] = self._denetle(yerel, zaman_asimi, istek)
            return kutu[0]
        finally:
            with self._kilit:
                self._suren = None
            olay.set()

    @staticmethod
    def _denetle(yerel, zaman_asimi, istek):
        yerel = surum.__version__ if yerel is None else yerel
        try:
            uzak, sayfa = _son_surum(istek, zaman_asimi)
        except Exception as exc:  # noqa: BLE001 — her hata kullanıcıya kısa nedenle gösterilir
            neden = _hata_nedeni(exc)
            log.info("Elle güncelleme denetimi yapılamadı (%s: %s).", type(exc).__name__, str(exc)[:120])
            return Denetim("hata", yerel, neden=neden)
        if daha_yeni_mi(uzak, yerel):
            log.info("Elle güncelleme denetimi: yeni sürüm var v%s (yerel %s).", uzak, yerel)
            return Denetim("yeni", yerel, uzak, sayfa)
        log.info("Elle güncelleme denetimi: güncel (yerel %s, son %s).", yerel, uzak)
        return Denetim("guncel", yerel, uzak)


elle_denetle = _ElleDenetleyici()

def _neden_metni(neden, lang=None):
    # Her metin t("...") ile sabit yazılır: tools/i18n_anahtarlar.py yalnız literal çağrıları toplar.
    if neden == "internet":
        return t("İnternete bağlanılamadı.", lang)
    if neden == "zaman_asimi":
        return t("GitHub zamanında yanıt vermedi.", lang)
    if neden == "sinir":
        return t("GitHub istek sınırına ulaşıldı; biraz sonra yeniden deneyin.", lang)
    return t("GitHub'dan beklenmeyen bir yanıt geldi.", lang)


def denetim_html(sonuc, platform=None, lang=None):
    """Elle denetimin sonucu (``lang`` dilinde). Yeni sürümde açılıştaki bildirimin aynısı."""
    if sonuc.durum == "yeni":
        return bildirim_html(YeniSurum(sonuc.uzak, sonuc.sayfa), platform=platform, lang=lang)
    if sonuc.durum == "guncel":
        metin = t("SesVer güncel: v{surum} (GitHub'daki son sürüm: v{uzak}).", lang, surum=sonuc.yerel,
                  uzak=sonuc.uzak)
        return f'<div class="sv-update sv-update-ok" role="status"><b>{html.escape(metin)}</b></div>'
    neden = _neden_metni(sonuc.neden, lang)
    baslik = t("Güncelleme denetlenemedi.", lang)
    return (f'<div class="sv-update sv-update-err" role="status"><b>{html.escape(baslik)}</b> '
            f'<span class="sv-update-note">{html.escape(neden)}</span></div>')


def bildirim_html(bilgi, platform=None, lang=None):
    """Arayüzde gösterilecek küçük bildirim (``lang`` dilinde). bilgi None ise boş metin."""
    if bilgi is None:
        return ""
    platform = sys.platform if platform is None else platform
    if platform.startswith("win"):
        talimat = t("Güncellemek için release sayfasındaki yeni kurulum programını "
                    "(SesVer-Kurulum-Windows.exe) indirip çalıştırın; ayarlarınız ve sesleriniz korunur.", lang)
    else:
        talimat = t("Mac'te şimdilik yeni sürümü release sayfasından indirin; "
                    "ayrıntı README'deki “Güncelleme” bölümünde.", lang)
    sayfa = html.escape(bilgi.sayfa, quote=True)
    baslik = html.escape(t("Yeni sürüm var: v{surum}", lang, surum=bilgi.surum))
    return (
        f'<div class="sv-update" role="status"><b>{baslik}</b> '
        f'<a href="{sayfa}" target="_blank" rel="noopener noreferrer">{html.escape(t("Release sayfası", lang))}</a>'
        f'<span class="sv-update-note">{html.escape(talimat)}</span></div>'
    )


class ArkaPlanKontrol:
    """Kontrolü bir kez, arka planda başlatır; sonucu toplam süre sınırıyla verir."""

    def __init__(self, kontrol=kontrol_et, zaman_asimi=ZAMAN_ASIMI_SN):
        self._kontrol = kontrol
        self._zaman_asimi = zaman_asimi
        self._bitti = threading.Event()
        self._sonuc = None
        self._baslangic = None
        self._kilit = threading.Lock()
        self._gec_kaldi_yazildi = False

    def baslat(self, ortam=None, ayar=None):
        """Thread'i başlatır (idempotent). Kapalıysa (ortam değişkeni ya da Ayarlar) hiçbir
        istek yapılmaz. ayar=None → ayarlar.json'daki seçim."""
        with self._kilit:
            if self._baslangic is not None:
                return
            self._baslangic = time.monotonic()
            if not kontrol_acik_mi(ortam, ayar):
                log.info("Güncelleme kontrolü kapalı (Ayarlar ya da %s=0).", ORTAM_DEGISKENI)
                self._bitti.set()
                return
            threading.Thread(target=self._calis, name="sesver-guncelleme", daemon=True).start()

    def _calis(self):
        try:
            self._sonuc = self._kontrol(zaman_asimi=self._zaman_asimi, kayit=self._kaydet)
        finally:
            self._bitti.set()

    def _kaydet(self, *args):
        # Bekleyen taraf "bitmedi" satırını zaten yazdıysa geç gelen sonuç
        # ikinci bir satır eklemez (log'a tek satır).
        with self._kilit:
            if self._gec_kaldi_yazildi:
                return
        log.info(*args)

    def sonuc(self):
        """Başlatılmadıysa hemen None. Aksi hâlde başlangıçtan en geç ZAMAN_ASIMI_SN sonra döner."""
        if self._baslangic is None:
            return None
        kalan = self._zaman_asimi - (time.monotonic() - self._baslangic)
        if not self._bitti.wait(max(0.0, kalan)):
            with self._kilit:
                ilk = not self._gec_kaldi_yazildi
                self._gec_kaldi_yazildi = True
            if ilk:
                log.info("Güncelleme kontrolü %.0f sn içinde bitmedi; bildirim gösterilmeyecek.",
                         self._zaman_asimi)
            return None
        return self._sonuc


_VARSAYILAN = ArkaPlanKontrol()
baslat = _VARSAYILAN.baslat
sonuc = _VARSAYILAN.sonuc
