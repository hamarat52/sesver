"""Uzun öğenin parça seslerini tek WAV'da birleştirir (tık/kesik olmadan, doğal duraklamayla).

Her parça: mono'ya indirilir → baştaki/sondaki sessizlik kırpılır (küçük pay bırakılır) →
kenarları yükseltilmiş kosinüsle (varsayılan 12 ms) sıfıra yumuşatılır. Parçalar arasına
metin bölücünün sınır türüne göre sessizlik konur (metin_bolme.ARALAR). Böylece birleşim
yerinde sinyal sıfırdan geçer; ani sıçrama (tık) olmaz. Yalnız numpy (+ dosya için soundfile).
"""
import numpy as np

SOLMA_MS = 12.0
ESIK_DB = -45.0  # tepe değere göre; altı "sessizlik" sayılır
PAY_MS = 40.0  # kırpmada konuşmanın önünde/arkasında bırakılan pay


def mono(ses):
    a = np.asarray(ses, dtype=np.float32)
    if a.ndim == 2:
        a = a.mean(axis=1)
    return np.ascontiguousarray(a.reshape(-1))


def sessizlik_kirp(ses, sr, esik_db=ESIK_DB, pay_ms=PAY_MS):
    a = mono(ses)
    if a.size == 0:
        return a
    tepe = float(np.max(np.abs(a)))
    if tepe <= 0.0:
        return a[:0]
    esik = tepe * (10.0 ** (esik_db / 20.0))
    idx = np.flatnonzero(np.abs(a) > esik)
    pay = int(sr * pay_ms / 1000.0)
    return a[max(0, idx[0] - pay): min(a.size, idx[-1] + pay + 1)]


def kenar_yumusat(ses, sr, solma_ms=SOLMA_MS):
    """Baş ve sonu yükseltilmiş kosinüsle 0'a indirir (ilk ve son örnek tam 0 olur)."""
    a = mono(ses).copy()
    n = min(int(sr * solma_ms / 1000.0), a.size // 2)
    if n <= 0:
        return np.zeros_like(a)
    rampa = (0.5 - 0.5 * np.cos(np.pi * np.arange(n, dtype=np.float32) / n)).astype(np.float32)
    a[:n] *= rampa
    a[-n:] *= rampa[::-1]
    return a


def birlestir(parcalar, sr, aralar, solma_ms=SOLMA_MS, kirp=True):
    """parcalar: ses dizileri; aralar: parçalar ARASI sessizlikler (sn), uzunluğu len(parcalar)-1."""
    parcalar = list(parcalar)
    aralar = list(aralar)
    if len(aralar) != max(0, len(parcalar) - 1):
        raise ValueError("aralar uzunluğu parça sayısının bir eksiği olmalı")
    out = []
    for i, p in enumerate(parcalar):
        p = sessizlik_kirp(p, sr) if kirp else mono(p)
        out.append(kenar_yumusat(p, sr, solma_ms))
        if i < len(aralar):
            out.append(np.zeros(int(round(max(0.0, float(aralar[i])) * sr)), dtype=np.float32))
    if not out:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(out).astype(np.float32)


def birlestir_dosyalar(yollar, hedef, aralar, solma_ms=SOLMA_MS):
    """WAV dosyalarını birleştirip `hedef`e 16-bit PCM yazar; ses süresini (sn) döndürür.

    Örnekleme hızları farklıysa ValueError (aynı modelin çıktılarında olmaz)."""
    import soundfile as sf

    sesler, sr = [], None
    for yol in yollar:
        veri, hiz = sf.read(str(yol), dtype="float32", always_2d=True)
        if sr is None:
            sr = hiz
        elif hiz != sr:
            raise ValueError(f"örnekleme hızı uyuşmuyor: {hiz} != {sr}")
        sesler.append(veri)
    if sr is None:
        raise ValueError("birleştirilecek parça yok")
    sonuc = birlestir(sesler, sr, aralar, solma_ms=solma_ms)
    sf.write(str(hedef), sonuc, sr, subtype="PCM_16", format="WAV")
    return sonuc.size / float(sr)
