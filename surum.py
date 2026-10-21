"""SesVer sürümü — tek kaynak proje kökündeki VERSION dosyasıdır.

Yalnız standart kütüphane kullanır. VERSION okunamazsa (dosya yok/bozuk)
uygulama çökmesin diye "0.0.0" döner; bu durumda güncelleme bildirimi her
yayınlanmış sürümü "yeni" sayar, ki bu da doğru davranıştır.
"""
import re
from pathlib import Path

VERSION_PATH = Path(__file__).resolve().parent / "VERSION"
_SURUM_RE = re.compile(r"^\d+\.\d+\.\d+$")
BILINMEYEN = "0.0.0"


def oku(path=VERSION_PATH):
    """VERSION dosyasındaki MAJOR.MINOR.PATCH sürümünü döndürür."""
    try:
        metin = Path(path).read_text(encoding="utf-8-sig").strip()
    except OSError:
        return BILINMEYEN
    return metin if _SURUM_RE.match(metin) else BILINMEYEN


__version__ = oku()
