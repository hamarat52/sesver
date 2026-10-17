"""Seçimlerden İngilizce ses tarifi kuran kurallı birleştirici (LLM yok).

Saf fonksiyonlar; Gradio'ya ya da modele bağımlı değildir. Bütün kelimeler
``voice_design_map.json`` içinde durur, kod değiştirmeden ayarlanabilir.
"""
import json
import re
from pathlib import Path

MAP_PATH = Path(__file__).resolve().parent / "voice_design_map.json"
FIRST_SEEDS = (11, 22, 33, 44)
_VOWELS = "aeiou"


def load_map(path=None):
    with open(path or MAP_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def group_choices(harita, grup):
    """Arayüzde gösterilecek Türkçe seçenekler (sırası korunur)."""
    g = harita["gruplar"][grup]
    labels = list(g["secenekler"].keys())
    if g["tip"] == "tek":
        return [harita.get("bos_secenek", "Fark etmez")] + labels
    return labels


def default_selections(harita):
    """Her şey 'Fark etmez' / orta konumda."""
    out = {}
    for name, g in harita["gruplar"].items():
        if g["tip"] == "tek":
            out[name] = harita.get("bos_secenek", "Fark etmez")
        elif g["tip"] == "coklu":
            out[name] = []
        else:
            out[name] = g.get("varsayilan")
    return out


def template(harita, ad):
    """Şablonun seçimleri (eksik gruplar varsayılanla doldurulur) ve örnek kategorisi."""
    raw = dict(harita["sablonlar"][ad])
    kategori = raw.pop("kategori", None)
    secimler = default_selections(harita)
    secimler.update(raw)
    return secimler, kategori


def _option(harita, grup, label):
    """Seçilen Türkçe etiketin sözlüğü; boş/bilinmeyen seçim için None."""
    if label in (None, "", harita.get("bos_secenek", "Fark etmez")):
        return None
    return harita["gruplar"][grup]["secenekler"].get(label)


def _article(head, harita):
    first = re.split(r"[\s,-]", head.strip(), maxsplit=1)[0].lower()
    exc = harita.get("unlu_istisnalari", {})
    if first in exc.get("an", []):
        return "an"
    if first in exc.get("a", []):
        return "a"
    return "an" if first[:1] in _VOWELS else "a"


def _word_count(text):
    return len(re.findall(r"[A-Za-z][A-Za-z'-]*", text))


def build_description(secimler, harita=None):
    """Seçimleri sabit sıradaki İngilizce tarife çevirir.

    Sıra: ``a/an [yaş] [cinsiyet] [kullanım | voice], [perde], [ton], [doku], [hız], [enerji]``.
    Dönüş: ``(tarif, parcalar, uyarilar)``; ``parcalar`` her parçanın
    ``(ingilizce, türkçe)`` çiftidir (arayüzde fareyle üstüne gelince Türkçe görünür).
    """
    harita = harita or load_map()
    secimler = secimler or {}
    uyarilar = []
    parcalar = []

    cins = _option(harita, "cinsiyet", secimler.get("cinsiyet"))
    zamir = (cins or {}).get("zamir", "their")
    yas = _option(harita, "yas", secimler.get("yas"))
    kullanim = _option(harita, "kullanim", secimler.get("kullanim"))

    yas_en = yas["en"].replace("{zamir}", zamir) if yas else ""
    yas_konum = (yas or {}).get("konum", "once")
    head_words = []
    if yas and yas_konum == "once":
        head_words.append(yas_en)
        parcalar.append((yas_en, secimler["yas"]))
    if cins:
        head_words.append(cins["en"])
        parcalar.append((cins["en"], secimler["cinsiyet"]))
    if yas and yas_konum == "cinsiyetten_sonra":
        head_words.append(yas_en)
        parcalar.append((yas_en, secimler["yas"]))
    if kullanim:
        head_words.append(kullanim["en"])
        parcalar.append((kullanim["en"], secimler["kullanim"]))
    else:
        head_words.append("voice")
    if yas and yas_konum == "sona":
        head_words.append(yas_en)
        parcalar.append((yas_en, secimler["yas"]))
    head = " ".join(head_words)
    head = f"{_article(head, harita)} {head}"

    # Diğer parçalar sabit sırayla; boşlar atlanır (", ".join fazla virgül bırakmaz).
    tail = []  # (grup, en, tr)
    for grup in harita["sira"]:
        g = harita["gruplar"][grup]
        value = secimler.get(grup)
        if g["tip"] == "coklu":
            labels = [v for v in (value or []) if v in g["secenekler"]]
            limit = g.get("en_fazla")
            if limit and len(labels) > limit:
                uyarilar.append(f"{g['etiket'].split(' (')[0]} için en fazla {limit} seçim kullanıldı.")
                labels = labels[:limit]
            for label in labels:
                tail.append((grup, g["secenekler"][label]["en"], label))
        else:
            opt = _option(harita, grup, value)
            if opt and opt["en"]:
                tail.append((grup, opt["en"], value))

    def compose(items):
        return ", ".join([head] + [en for _g, en, _tr in items])

    limit = harita.get("max_kelime", 25)
    tarif = compose(tail)
    if _word_count(tarif) > limit:
        # Önce belirlenen sırayla (enerji → doku → hız), yetmezse sondan kısalt.
        order = list(harita.get("kisaltma_sirasi", [])) + list(reversed(harita["sira"]))
        for grup in order:
            while _word_count(tarif) > limit and any(g == grup for g, _e, _t in tail):
                idx = max(i for i, item in enumerate(tail) if item[0] == grup)
                tail.pop(idx)
                tarif = compose(tail)
        uyarilar.append(f"Tarif {limit} kelimeyi aşmasın diye bazı ayrıntılar çıkarıldı.")

    parcalar.extend((en, tr) for _g, en, tr in tail)

    for rule in harita.get("uyarilar", []):
        if all(_matches(secimler.get(k), allowed) for k, allowed in rule["kosul"].items()):
            uyarilar.append(rule["mesaj"])
    return tarif, parcalar, uyarilar


def _matches(value, allowed):
    if isinstance(value, (list, tuple)):
        return any(v in allowed for v in value)
    return value in allowed


def estimate_seconds(text, harita=None):
    cps = (harita or {}).get("karakter_per_saniye", 15)
    return len((text or "").strip()) / float(cps)


def sample_text(kategori, saniye, harita=None):
    """Kategori metninden, hedef süreye en yakın cümle grubunu seçer.

    Ses uzunluğu modelde doğrudan ayarlanamaz; süre okunacak metnin uzunluğuyla
    belirlenir (~15 karakter/sn, hazır seslerin ölçümüyle uyumlu).
    """
    harita = harita or load_map()
    pool = harita["ornek_metinler"].get(kategori) or next(iter(harita["ornek_metinler"].values()))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", pool) if s.strip()]
    target = float(saniye) * harita.get("karakter_per_saniye", 15)
    chosen = [sentences[0]]
    for sentence in sentences[1:]:
        current = len(" ".join(chosen))
        candidate = len(" ".join(chosen + [sentence]))
        if abs(candidate - target) < abs(current - target):
            chosen.append(sentence)
        else:
            break
    return " ".join(chosen)


def candidate_seeds(batch):
    """0. tur 11/22/33/44, 1. tur 55/66/77/88 …"""
    start = 4 * int(batch) + 1
    return [11 * k for k in range(start, start + 4)]


def parts_html(parcalar):
    """Her parçayı Türkçe karşılığı ipucu olan bir rozet olarak gösterir."""
    from html import escape
    return "".join(
        f'<span class="sv-part" title="{escape(tr)}">{escape(en)}</span>' for en, tr in parcalar
    )
