"""Bulut motorları için küçük, kurallı Türkçe metin normalizasyonu (stdlib).

Neden ayrı modül: SesVer'de bugüne kadar Türkçe bir normalizer YOKTU.
VoxCPM paketinin ``voxcpm.utils.text_normalize`` modülü Çince/İngilizce içindir
(``inflect`` ile İngilizce sayı okur) ve SesVer onu kullanmaz
(``generate(normalize=False)`` varsayılanı). VoxCPM2 hattının davranışı
değişmesin diye bu modül YALNIZ ElevenLabs adaptöründe kullanılır.

Kapsam bilerek dar tutuldu (yanlış okumaktansa dokunmamak):
- tam sayılar (1.250.000 gibi binlik noktalı yazım dahil), ondalık virgül
- yüzde (%25, % 25), saat (14:30), para birimi (TL, ₺)
- sık kısaltmalar (Dr., Prof., vb., vs., örn., km, kg ...)
Sıra sayıları ("3.") ve tarihler bilinçli olarak çevrilmez: cümle sonundaki
noktayla karışır. ElevenLabs'in kendi ``apply_text_normalization`` ayarı
ayrıca açık kalır.
"""
from __future__ import annotations

import re

_ONES = ("", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz")
_TENS = ("", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan")
_SCALES = ((10 ** 12, "trilyon"), (10 ** 9, "milyar"), (10 ** 6, "milyon"), (1000, "bin"))

# Büyük/küçük harf duyarlı; nokta içerenler önce gelsin diye uzunluğa göre sıralanır.
ABBREVIATIONS = {
    "Prof. Dr.": "Profesör Doktor",
    "Doç. Dr.": "Doçent Doktor",
    "Prof.": "Profesör",
    "Doç.": "Doçent",
    "Dr.": "Doktor",
    "Av.": "Avukat",
    "Sn.": "Sayın",
    "vb.": "ve benzeri",
    "vs.": "vesaire",
    "örn.": "örneğin",
    "bkz.": "bakınız",
    "yy.": "yüzyıl",
    "No.": "numara",
    "T.C.": "Türkiye Cumhuriyeti",
}
UNITS = {"km": "kilometre", "kg": "kilogram", "cm": "santimetre", "mm": "milimetre", "m": "metre",
         "gr": "gram", "lt": "litre", "sn": "saniye", "dk": "dakika", "TL": "Türk lirası",
         "₺": "Türk lirası", "$": "dolar", "€": "avro"}


def number_to_words(n: int) -> str:
    """0 ≤ n < 10^15 tam sayıyı Türkçe okur ("bin", "yüz" — "bir bin" değil)."""
    n = int(n)
    if n < 0:
        return "eksi " + number_to_words(-n)
    if n == 0:
        return "sıfır"
    if n >= 10 ** 15:
        raise ValueError("çok büyük sayı")
    parts = []
    for value, word in _SCALES:
        count, n = divmod(n, value)
        if count:
            parts.append(word if (value == 1000 and count == 1) else f"{_below_thousand(count)} {word}")
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def _below_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    tens, ones = divmod(rest, 10)
    words = []
    if hundreds:
        words.append("yüz" if hundreds == 1 else f"{_ONES[hundreds]} yüz")
    if tens:
        words.append(_TENS[tens])
    if ones:
        words.append(_ONES[ones])
    return " ".join(words)


def _int_token(token: str) -> str:
    # "1.250.000" → binlik ayraçlı yazım; "007" → baştaki sıfırlar okunmaz.
    return number_to_words(int(token.replace(".", "")))


def _decimal(int_part: str, frac: str) -> str:
    frac_words = " ".join("sıfır" for _ in range(len(frac) - len(frac.lstrip("0"))))
    rest = frac.lstrip("0")
    tail = (frac_words + " " if frac_words else "") + (number_to_words(int(rest)) if rest else "")
    return f"{_int_token(int_part)} virgül {tail.strip()}"


_NUM = r"(?:\d{1,3}(?:\.\d{3})+|\d+)"
_RE_PERCENT = re.compile(rf"%\s?({_NUM})(?:,(\d+))?")
_RE_TIME = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_RE_DECIMAL = re.compile(rf"(?<![\d.,])({_NUM}),(\d+)(?![\d,])")
_RE_INT = re.compile(rf"(?<![\d,])({_NUM})(?![\d,]|\.\d)")
_RE_UNIT = re.compile(r"(?<=\d)\s?(km|kg|cm|mm|gr|lt|sn|dk|TL|m)\b|(?<=\d)\s?(₺|\$|€)")
_RE_SPACES = re.compile(r"[ \t]{2,}")


def normalize(text: str) -> str:
    """Türkçe metni seslendirmeye uygun hâle getirir; boş/None için ``""``."""
    if not text:
        return ""
    out = text
    for short in sorted(ABBREVIATIONS, key=len, reverse=True):
        out = re.sub(rf"(?<!\w){re.escape(short)}(?=\s|$)", ABBREVIATIONS[short], out)
    out = _RE_UNIT.sub(lambda m: " " + UNITS[m.group(1) or m.group(2)], out)
    out = _RE_PERCENT.sub(lambda m: "yüzde " + (_decimal(m.group(1), m.group(2)) if m.group(2)
                                                else _int_token(m.group(1))), out)
    out = _RE_TIME.sub(lambda m: f"{number_to_words(int(m.group(1)))} "
                                 f"{'sıfır sıfır' if m.group(2) == '00' else number_to_words(int(m.group(2)))}",
                       out)
    out = _RE_DECIMAL.sub(lambda m: _decimal(m.group(1), m.group(2)), out)
    out = _RE_INT.sub(lambda m: _int_token(m.group(1)), out)
    return _RE_SPACES.sub(" ", out).strip()
