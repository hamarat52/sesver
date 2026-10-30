"""Kelime zamanlarından SRT altyazı üretimi (stdlib; arayüzden bağımsız).

Kelime zamanı veren motorlar (bugün EMA Lightning) altyazıyı doğrudan bu
zamanlardan üretir: Whisper ile yeniden yazıya dökmek ya da tahmin yapmak
gerekmez. Girdi, ``text``/``start``/``end`` alanı olan nesneler, sözlükler ya
da ``(metin, başlangıç, bitiş)`` üçlüleri olabilir; süreler saniyedir.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

MAX_CHARS = 42        # tek altyazı satırı için yaygın okunabilirlik sınırı
MAX_DURATION = 5.0    # bir altyazının ekranda kalacağı en uzun süre (sn)
MAX_GAP = 0.6         # bu kadar sessizlikten sonra yeni altyazı başlar (sn)
SENTENCE_END = (".", "!", "?", "…")


@dataclass(frozen=True)
class TimedWord:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Cue:
    index: int
    start: float
    end: float
    text: str


def _as_word(item) -> TimedWord:
    if isinstance(item, TimedWord):
        return item
    if isinstance(item, dict):
        text, start, end = item["text"], item["start"], item["end"]
    elif isinstance(item, (tuple, list)):
        text, start, end = item
    else:
        text, start, end = item.text, item.start, item.end
    start, end = float(start), float(end)
    if start < 0 or end < start:
        raise ValueError(f"Geçersiz kelime zamanı: {text!r} {start}–{end}")
    return TimedWord(str(text), start, end)


def normalize_words(words: Iterable) -> List[TimedWord]:
    """Boş kelimeleri atar, başlangıca göre sıralar."""
    out = [_as_word(w) for w in (words or ())]
    return sorted((w for w in out if w.text.strip()), key=lambda w: (w.start, w.end))


def group_cues(words: Iterable, max_chars: int = MAX_CHARS, max_duration: float = MAX_DURATION,
               max_gap: float = MAX_GAP) -> List[Cue]:
    """Kelimeleri okunabilir altyazılara böler (karakter, süre, sessizlik ve cümle sonu)."""
    cues: List[Cue] = []
    current: List[TimedWord] = []

    def flush():
        if current:
            cues.append(Cue(len(cues) + 1, current[0].start, current[-1].end,
                            " ".join(w.text.strip() for w in current)))
            current.clear()

    for word in normalize_words(words):
        if current:
            text_len = len(" ".join(w.text for w in current)) + 1 + len(word.text)
            too_long = text_len > max_chars
            too_slow = word.end - current[0].start > max_duration
            gap = word.start - current[-1].end > max_gap
            sentence = current[-1].text.rstrip().endswith(SENTENCE_END)
            if too_long or too_slow or gap or sentence:
                flush()
        current.append(word)
    flush()
    return cues


def format_timestamp(seconds: float) -> str:
    """``SS:DD:ss,mmm`` (SRT biçimi)."""
    ms = int(round(max(0.0, float(seconds)) * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def cues_to_srt(cues: Iterable[Cue]) -> str:
    blocks = [f"{c.index}\n{format_timestamp(c.start)} --> {format_timestamp(c.end)}\n{c.text}\n" for c in cues]
    return "\n".join(blocks)


def words_to_srt(words: Iterable, **kwargs) -> str:
    """Kelime zamanlarından doğrudan SRT metni (kelime yoksa boş metin)."""
    return cues_to_srt(group_cues(words, **kwargs))
