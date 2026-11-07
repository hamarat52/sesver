"""Uzun metni anlamı bozmayan yerlerden en fazla 500 karakterlik parçalara böler.

Üretim kuyruğunun uzun öğeleri içindir: her parça aynı ayarlarla ayrı üretilir, sonra
ses_birlestirme ile tek WAV'a birleştirilir. Yalnız standart kütüphane kullanır.

Sınır önceliği (yalnız gerektiğinde bir alt düzeye inilir):
  paragraf (boş satır) > cümle sonu (. ! ? …) > yan cümle (, ; : ve boşluklu tire)
  > kelime arası > zorunlu kesme (boşluksuz, 500 karakterden uzun dizi)

Cümle sonu sayılmayanlar: kısaltmalar (Dr., vb., ör. …), baş harfler (A. Yılmaz),
sayılar ve sıra sayıları (3.5, 1.000, 2. Dünya Savaşı, III. Selim) ve noktadan
sonra küçük harfle devam eden metin ("vb. şeyler", "dedi ki: geliyor musun? dedi").
"""
import re
from collections import namedtuple

EN_FAZLA = 500

# Parçanın SONUNDAKİ sınır türü → birleştirmede araya konan sessizlik (saniye).
ARALAR = {"paragraf": 0.7, "cumle": 0.45, "yan_cumle": 0.3, "kelime": 0.15, "kesme": 0.0}
_ONCELIK = ("paragraf", "cumle", "yan_cumle", "kelime", "kesme")

Parca = namedtuple("Parca", "metin sinir")  # sinir: bu parçadan sonraki sınır türü (son parçada None)

# Küçük harfle, noktasız yazılır. Nokta içerenler (a.g.e, t.c) belirteç olarak karşılaştırılır.
KISALTMALAR = frozenset("""
dr prof doç doc av sn bkz vb vs ör örn yy st mr mrs ms no nu tel cad sok mah apt böl bol yrd
uzm op hz ltd şti sti a.ş t.c vd alm ing fr age agm a.g.e a.g.m tic san müh öğr ogr gn gen org kur
bşk bl sy s ss sf c jr etc e.g i.e vol fig pp approx inc co corp yrd.doç doç.dr prof.dr
""".split())
_ROMA = re.compile(r"^[ivxlcdm]+$")
_TR_KUCUK = str.maketrans({"İ": "i", "I": "ı"})


def _kucuk(s):
    return s.translate(_TR_KUCUK).lower()


def _normalize(metin):
    metin = (metin or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    metin = re.sub(r"[ \t\f\v]+", " ", metin)
    metin = re.sub(r" *\n *", "\n", metin)
    return metin.strip()


def _onceki_belirtec(metin, i):
    """i konumundaki noktadan önceki belirteç (baştaki tırnak/parantez atılmış)."""
    m = re.search(r"(\S+)$", metin[:i])
    if not m:
        return ""
    return m.group(1).lstrip("\"'“‘«([{")


def _kisaltma_mi(belirtec):
    """Nokta bu belirteçten sonra geliyorsa cümle sonu sayılmaz."""
    if not belirtec:
        return False
    k = _kucuk(belirtec)
    k_ascii = belirtec.lower()  # "III" Türkçe küçültmede "ııı" olur; Roma rakamı için ASCII
    if k in KISALTMALAR or k_ascii in KISALTMALAR:
        return True
    if len(k) == 1 and k.isalpha():  # baş harf: "A. Yılmaz"
        return True
    if k.isdigit() or _ROMA.match(k_ascii):  # sıra sayısı: "2. Dünya", "III. Selim"
        return True
    if re.fullmatch(r"(\w\.)+\w", k):  # a.g.e, T.C, A.Ş
        return True
    return False


def _sonraki_karakter(metin, j):
    while j < len(metin) and metin[j] in " \n":
        j += 1
    return metin[j] if j < len(metin) else ""


def _cumle_sonu_mu(metin, m):
    nokta = m.group(0)
    sonraki = _sonraki_karakter(metin, m.end())
    if sonraki == "":
        return True
    if sonraki.islower():  # "vb. şeyler", "geliyor musun?" dedi
        return False
    if nokta.rstrip("\"'”’»)]}") == ".":  # tek nokta: kısaltma/sayı mı?
        return not _kisaltma_mi(_onceki_belirtec(metin, m.start()))
    return True


_NOKTALAMA = re.compile(r"(?:\.{2,}|…|[.!?])+[\"'”’»)\]}]*(?=\s|$)")
_SATIR = re.compile(r"\n(?=\S)")


def _cumleler(paragraf):
    """Paragraf → cümle listesi. Tek satır sonu, ardından büyük harf geliyorsa da cümle sınırıdır."""
    sinirlar = {m.end() for m in _NOKTALAMA.finditer(paragraf) if _cumle_sonu_mu(paragraf, m)}
    for m in _SATIR.finditer(paragraf):
        if not paragraf[m.end()].islower():
            sinirlar.add(m.start())
    out, bas = [], 0
    for s in sorted(sinirlar):
        parca = paragraf[bas:s].strip()
        if parca:
            out.append(parca)
        bas = s
    son = paragraf[bas:].strip()
    if son:
        out.append(son)
    return [re.sub(r"\s+", " ", c) for c in out]


_YAN = re.compile(r"(?<=[,;:])\s+|\s+(?=[–—-]\s)")


def _yan_cumleler(cumle):
    return [p for p in (x.strip() for x in _YAN.split(cumle)) if p]


def _kotu_son(kelime):
    """Kelime arası bölmede parça bu kelimeyle bitmesin (\"Dr.\" | \"Ahmet\")."""
    return kelime.endswith(".") and _kisaltma_mi(kelime[:-1].lstrip("\"'“‘«([{"))


def _kelimeler(birim, en_fazla):
    """Kelime arasından paketler; boşluksuz aşırı uzun diziyi zorunlu keser."""
    kelimeler = []
    for k in birim.split(" "):
        while len(k) > en_fazla:
            kelimeler.append((k[:en_fazla], "kesme"))
            k = k[en_fazla:]
        if k:
            kelimeler.append((k, "kelime"))
    paketler, cur = [], []

    def uzunluk(lst):
        return sum(len(w) for w, _ in lst) + max(0, len(lst) - 1)

    for w in kelimeler:
        if cur and uzunluk(cur + [w]) > en_fazla:
            tasinan = []
            if len(cur) > 1 and _kotu_son(cur[-1][0]) and uzunluk([cur[-1], w]) <= en_fazla:
                tasinan = [cur.pop()]
            paketler.append(cur)
            cur = tasinan
        cur.append(w)
    if cur:
        paketler.append(cur)
    out = []
    for p in paketler:
        metin = " ".join(w for w, _ in p)
        sinir = p[-1][1]
        out.append((metin, sinir))
    return out


def _paketle(birimler, en_fazla):
    """(metin, sınır) birimlerini en fazla `en_fazla` karakterlik parçalara paketler.

    Açgözlüdür ama taşma anında geriye bakar: parçanın en az yarısı doluysa, içindeki daha
    güçlü bir sınırdan (ör. paragraf sonu) keser; böylece paragraflar mümkünse bölünmez.
    """
    def uz(lst):
        return sum(len(m) for m, _ in lst) + max(0, len(lst) - 1)

    def derece(sinir):
        return _ONCELIK.index(sinir) if sinir in _ONCELIK else len(_ONCELIK)

    gruplar, cur = [], []
    for birim in birimler:
        if cur and uz(cur + [birim]) > en_fazla:
            k, en_iyi = len(cur), derece(cur[-1][1])
            for j in range(len(cur) - 1, 0, -1):
                if uz(cur[:j]) < en_fazla * 0.5:
                    break
                if derece(cur[j - 1][1]) < en_iyi:
                    k, en_iyi = j, derece(cur[j - 1][1])
            gruplar.append(cur[:k])
            cur = cur[k:]
            if cur and uz(cur + [birim]) > en_fazla:
                gruplar.append(cur)
                cur = []
        cur.append(birim)
    if cur:
        gruplar.append(cur)
    return [Parca(" ".join(m for m, _ in g), g[-1][1]) for g in gruplar]


def _birimler(metin, en_fazla):
    """Metni, her biri en fazla `en_fazla` karakter olan (metin, sonraki sınır) birimlerine ayırır."""
    out = []
    paragraflar = [p for p in re.split(r"\n\s*\n", metin) if p.strip()]
    for pi, paragraf in enumerate(paragraflar):
        cumleler = _cumleler(paragraf)
        for ci, cumle in enumerate(cumleler):
            son_sinir = "paragraf" if ci == len(cumleler) - 1 else "cumle"
            if len(cumle) <= en_fazla:
                out.append((cumle, son_sinir))
                continue
            yanlar = _yan_cumleler(cumle)
            for yi, yan in enumerate(yanlar):
                sinir = son_sinir if yi == len(yanlar) - 1 else "yan_cumle"
                if len(yan) <= en_fazla:
                    out.append((yan, sinir))
                    continue
                kelime_paketleri = _kelimeler(yan, en_fazla)
                for ki, (km, ks) in enumerate(kelime_paketleri):
                    out.append((km, sinir if ki == len(kelime_paketleri) - 1 else ks))
    if out:
        out[-1] = (out[-1][0], None)
    return out


def bol(metin, en_fazla=EN_FAZLA):
    """Metni Parca(metin, sinir) listesine böler; hiçbir parça `en_fazla` karakteri aşmaz.

    Kısa metin (≤ en_fazla) tek parça döner. Boş metin boş liste döner. Parçalar tek
    boşlukla birleştirilince, boşlukları sadeleştirilmiş özgün metin elde edilir.
    """
    metin = _normalize(metin)
    if not metin:
        return []
    if len(metin) <= en_fazla and "\n\n" not in metin:
        return [Parca(re.sub(r"\s+", " ", metin), None)]
    return _paketle(_birimler(metin, en_fazla), en_fazla)


def ara_suresi(sinir):
    """Parçadan sonraki sessizlik (sn); son parça (None) için 0."""
    return ARALAR.get(sinir, 0.0) if sinir else 0.0
