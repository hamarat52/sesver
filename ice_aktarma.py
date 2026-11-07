"""Toplu içe aktarma (TXT / CSV) → kuyruk önizlemesi. Arayüzden bağımsız; dosya yalnız yerelde okunur.

- Kodlama: UTF-8 (BOM'lu/BOM'suz), UTF-16 (BOM'lu; Excel "Unicode metin"), Windows-1254
  (Türkçe Excel'in varsayılan CSV'si). UTF-8 olarak çözülemeyen dosya Windows-1254 sayılır.
- CSV ayracı başlık satırından seçilir: `;` (Türkçe Excel), `,` ya da sekme.
- Sütunlar (Türkçe ya da İngilizce, büyük/küçük harf ve Türkçe harf farkı gözetilmez):
  metin/text (zorunlu), ses/voice, duygu/emotion, kalite/quality. Bilinmeyen sütunlar yok sayılır.
  `ses` sütunu yoksa ya da hücre boşsa içe aktarma ekranında seçilen ses kullanılır.
- Önizleme hiçbir şeyi kuyruğa eklemez: kabul edilen öğeleri, reddedilen satırları (neden
  koduyla) ve kuyruk sınırını aşan satırları döndürür. Onaydan sonra arayüz
  `Kuyruk.ekle_toplu(onizleme.istekler())` çağırır.
- Dosya içeriği günlüğe yazılmaz.

Red nedenleri: metin_bos, metin_uzun, bilinmeyen_ses, bilinmeyen_duygu, bilinmeyen_kalite, rastgele_uzun.
Dosya düzeyi hatalar (Onizleme.hata): dosya_bos, dosya_buyuk, metin_sutunu_yok, kip_gecersiz.
"""
import codecs
import csv
import io
import re
from dataclasses import dataclass, field

import kuyruk as kq

DOSYA_EN_FAZLA_BAYT = 2 * 1024 * 1024  # 50 öğe × 10.000 karakter rahatça sığar

# Kanonik değer (uygulamadaki Türkçe anahtar) → kabul edilen yazımlar (katlanmış biçimde)
DUYGULAR = {
    "Nötr": ("notr", "neutral", "normal"), "Sakin": ("sakin", "calm"), "Enerjik": ("enerjik", "energetic"),
    "Neşeli": ("neseli", "cheerful", "happy"), "Ciddi": ("ciddi", "serious"),
    "Heyecanlı": ("heyecanli", "excited"), "Üzgün": ("uzgun", "sad"),
}
KALITELER = {
    "Hızlı": ("hizli", "fast"), "Dengeli": ("dengeli", "balanced"), "En İyi": ("en iyi", "eniyi", "best"),
}
SUTUNLAR = {
    "metin": ("metin", "text", "yazi", "icerik", "content"),
    "ses": ("ses", "voice", "ses adi", "konusmaci", "speaker", "voice name"),
    "duygu": ("duygu", "emotion", "ton", "duygu ton", "tone"),
    "kalite": ("kalite", "quality"),
}
RASTGELE_ADLARI = ("rastgele", "rastgele ses", "random", "random voice")

_KATLA = str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ç": "c", "ö": "o", "ü": "u", "â": "a", "î": "i", "û": "u"})


def katla(s):
    """Karşılaştırma anahtarı: BOM/boşluk atılır, Türkçe harfler ASCII'ye, küçük harf, ayraçlar tek boşluk."""
    s = (s or "").replace("\ufeff", "").strip().replace("İ", "i").replace("I", "ı").lower().translate(_KATLA)
    s = s.replace("i̇", "i")  # birleşik noktalı i
    return re.sub(r"[\s_/\-]+", " ", s).strip()


def _esle(tablo, deger):
    k = katla(deger)
    for kanonik, yazimlar in tablo.items():
        if k == katla(kanonik) or k in yazimlar:
            return kanonik
    return None


def coz(veri):
    """bytes → (metin, kodlama). Satır sonları \\n'e indirgenir."""
    if veri.startswith(codecs.BOM_UTF8):
        metin, kodlama = veri[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace"), "utf-8-sig"
    elif veri.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        metin, kodlama = veri.decode("utf-16", errors="replace"), "utf-16"
    else:
        try:
            metin, kodlama = veri.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            metin, kodlama = veri.decode("cp1254", errors="replace"), "cp1254"
    return metin.replace("\r\n", "\n").replace("\r", "\n"), kodlama


@dataclass
class Onizleme:
    ogeler: list = field(default_factory=list)  # [{"satir": n, "tur":…, "metin":…, …}] — eklenecekler
    reddedilen: list = field(default_factory=list)  # [{"satir": n, "neden": kod, "ozet": "ilk 40 karakter"}]
    asan: list = field(default_factory=list)  # kuyruk sınırını aştığı için eklenmeyecek satır numaraları
    kodlama: str = ""
    ayrac: str = ""
    yok_sayilan_sutunlar: list = field(default_factory=list)
    hata: str = ""  # dosya düzeyi hata kodu (doluysa hiçbir öğe yok)

    def istekler(self):
        """Kuyruk.ekle_toplu için istek listesi (satır numarası atılır)."""
        return [{k: v for k, v in o.items() if k != "satir"} for o in self.ogeler]

    @property
    def uzun_sayisi(self):
        return sum(len(o["metin"]) > kq.PARCA_EN_FAZLA for o in self.ogeler)


def _ozet(metin):
    metin = re.sub(r"\s+", " ", metin or "").strip()
    return metin[:40] + ("…" if len(metin) > 40 else "")


def _ses_ayarlari(ad, ses_bul):
    """Hücredeki ses adı → kütüphane ayarları; bilinmiyorsa None."""
    if katla(ad) in RASTGELE_ADLARI:
        return {"tur": "kutuphane", "ses_id": kq.RASTGELE, "ses_adi": "Rastgele ses", "ref_kaynak": None,
                "ref_metin": None}
    ses = ses_bul(ad) if ses_bul else None
    if not ses:
        return None
    return {"tur": "kutuphane", "ses_id": ses["id"], "ses_adi": ses["ad"], "ref_kaynak": ses.get("ref_wav"),
            "ref_metin": ses.get("ref_text")}


def _dogrula(metin, ayar):
    if not metin:
        return "metin_bos"
    if len(metin) > kq.OGE_METIN_EN_FAZLA:
        return "metin_uzun"
    if ayar.get("tur") == "kutuphane" and (ayar.get("ses_id") or kq.RASTGELE) == kq.RASTGELE \
            and len(metin) > kq.PARCA_EN_FAZLA:
        return "rastgele_uzun"
    return None


def _sinirla(onizleme, kalan_yer):
    kalan_yer = max(0, int(kalan_yer))
    if len(onizleme.ogeler) > kalan_yer:
        onizleme.asan = [o["satir"] for o in onizleme.ogeler[kalan_yer:]]
        onizleme.ogeler = onizleme.ogeler[:kalan_yer]
    return onizleme


def _varsayilan(ayarlar):
    a = {"tur": "kutuphane", "ses_id": kq.RASTGELE, "ses_adi": "Rastgele ses", "ref_kaynak": None, "ref_metin": None,
         "duygu": "Nötr", "kalite": "Dengeli", "efektler": []}
    a.update({k: v for k, v in (ayarlar or {}).items() if v is not None})
    return a


def onizle_txt(veri, kip, ayarlar=None, kalan_yer=kq.KUYRUK_EN_FAZLA):
    """kip: "tek" (dosyanın tamamı tek öğe) ya da "paragraf" (boş satırla ayrılan her paragraf bir öğe).
    Ses ve ayarlar içe aktarma ekranında bir kez seçilir (`ayarlar`)."""
    oz = Onizleme()
    if len(veri) > DOSYA_EN_FAZLA_BAYT:
        oz.hata = "dosya_buyuk"
        return oz
    metin, oz.kodlama = coz(veri)
    if kip not in ("tek", "paragraf"):
        oz.hata = "kip_gecersiz"
        return oz
    ayar = _varsayilan(ayarlar)
    if kip == "tek":
        parcalar = [(1, metin.strip())]
    else:
        parcalar = [(i + 1, p.strip()) for i, p in enumerate(re.split(r"\n[ \t]*\n", metin)) if p.strip()]
    parcalar = [(n, p) for n, p in parcalar if p]
    if not parcalar:
        oz.hata = "dosya_bos"
        return oz
    for n, p in parcalar:
        neden = _dogrula(p, ayar)
        if neden:
            oz.reddedilen.append({"satir": n, "neden": neden, "ozet": _ozet(p)})
        else:
            oz.ogeler.append(dict(ayar, metin=p, satir=n))
    return _sinirla(oz, kalan_yer)


def _ayrac(baslik):
    sayim = {a: baslik.count(a) for a in (";", ",", "\t")}
    en = max(sayim, key=lambda a: sayim[a])
    return en if sayim[en] else ","


def onizle_csv(veri, ayarlar=None, ses_bul=None, kalan_yer=kq.KUYRUK_EN_FAZLA):
    """Her satır bir öğe. ses_bul(ad) -> {"id","ad","ref_wav","ref_text"} | None (kayıtlı ses arama)."""
    oz = Onizleme()
    if len(veri) > DOSYA_EN_FAZLA_BAYT:
        oz.hata = "dosya_buyuk"
        return oz
    metin, oz.kodlama = coz(veri)
    satirlar = metin.split("\n")
    baslik = next((s for s in satirlar if s.strip()), "")
    if not baslik:
        oz.hata = "dosya_bos"
        return oz
    oz.ayrac = _ayrac(baslik)
    okuyucu = csv.reader(io.StringIO(metin), delimiter=oz.ayrac)
    sutun = {}
    for satir in okuyucu:
        if not any(h.strip() for h in satir):
            continue
        for i, h in enumerate(satir):
            ad = next((k for k, yazimlar in SUTUNLAR.items() if katla(h) in yazimlar), None)
            if ad and ad not in sutun:
                sutun[ad] = i
            elif h.strip():
                oz.yok_sayilan_sutunlar.append(h.strip())
        break
    if "metin" not in sutun:
        oz.hata = "metin_sutunu_yok"
        return oz
    temel = _varsayilan(ayarlar)

    def hucre(satir, ad):
        i = sutun.get(ad)
        return satir[i].strip() if i is not None and i < len(satir) else ""

    for satir in okuyucu:
        n = okuyucu.line_num
        if not any(h.strip() for h in satir):
            continue
        yazi = hucre(satir, "metin")
        ayar = dict(temel)
        neden = None
        ses_adi = hucre(satir, "ses")
        if ses_adi:
            ses = _ses_ayarlari(ses_adi, ses_bul)
            if ses is None:
                neden = "bilinmeyen_ses"
            else:
                ayar.update(ses)
        duygu = hucre(satir, "duygu")
        if not neden and duygu:
            ayar["duygu"] = _esle(DUYGULAR, duygu)
            neden = None if ayar["duygu"] else "bilinmeyen_duygu"
        kalite = hucre(satir, "kalite")
        if not neden and kalite:
            ayar["kalite"] = _esle(KALITELER, kalite)
            neden = None if ayar["kalite"] else "bilinmeyen_kalite"
        if not yazi:
            neden = "metin_bos"  # boş metin her şeyden önce söylenir
        else:
            neden = neden or _dogrula(yazi, ayar)
        if neden:
            oz.reddedilen.append({"satir": n, "neden": neden, "ozet": _ozet(yazi)})
        else:
            oz.ogeler.append(dict(ayar, metin=yazi, satir=n))
    return _sinirla(oz, kalan_yer)


def sablon_csv(dil="tr"):
    """İndirilebilir örnek CSV: UTF-8 BOM, `;` ayraçlı, CRLF (Excel'de Türkçe harflerle doğru açılır)."""
    if dil == "tr":
        satirlar = [
            ["metin", "ses", "duygu", "kalite"],
            ["Bir varmış bir yokmuş, evvel zaman içinde küçük bir köyde bir masalcı yaşarmış.",
             "Yaşlı Masalcı", "Sakin", "Dengeli"],
            ["Bugün sizlere doğanın en sabırlı yapı ustası olan karıncaları anlatacağız.",
             "Belgesel Anlatıcı", "Nötr", "En İyi"],
            ["Hazır mısınız? Yarışmamız birazdan başlıyor!", "Heyecanlı Sunucu", "Heyecanlı", "Hızlı"],
        ]
    else:
        satirlar = [
            ["text", "voice", "emotion", "quality"],
            ["Once upon a time, in a small village, there lived an old storyteller.", "Yaşlı Masalcı", "calm",
             "balanced"],
            ["Today we will talk about ants, nature's most patient builders.", "Belgesel Anlatıcı", "neutral", "best"],
        ]
    tampon = io.StringIO()
    yazici = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    yazici.writerows(satirlar)
    return codecs.BOM_UTF8 + tampon.getvalue().encode("utf-8")
