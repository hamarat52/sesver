"""Üretim SONRASI ses efektleri (numpy/scipy; ffmpeg gerekmez).

Efektler modele tarif olarak yazılmaz; ham ses hiç değiştirilmeden kopyası
üzerinde çalışılır. Ayar biçimi (``ses.json`` → ``varsayilan_efektler`` ile aynı)::

    [{"ad": "telefon", "yogunluk": 60}, {"ad": "oda", "yogunluk": 40, "on_ayar": "salon"}]

Sabit sıra: renk (lo-fi, telefon, telsiz, megafon) → oda → cızırtı → seviye
eşitleme (-16 LUFS, gerçek tepe ≤ -1 dBTP).
"""
import numpy as np
from scipy import signal

EFFECTS = {
    "cizirti": "Cızırtı / plak",
    "lofi": "Lo-fi / eski radyo",
    "telefon": "Telefon",
    "telsiz": "Telsiz",
    "oda": "Oda / yankı",
    "megafon": "Megafon",
}
COLOR_ORDER = ("lofi", "telefon", "telsiz", "megafon")
ROOM_PRESETS = {"kucuk": ("Küçük oda", 0.35), "salon": ("Salon", 1.2), "kilise": ("Kilise", 3.2)}
TARGET_LUFS = -16.0
PEAK_DBTP = -1.0
_EPS = 1e-12


# ---------------------------------------------------------------- yardımcılar
def _t(level):
    return float(np.clip(float(level), 0.0, 100.0)) / 100.0


def _rms(x):
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)) + _EPS))


def _sos(kind, cutoff, sr, order=4):
    nyq = sr / 2.0
    if np.ndim(cutoff):
        lo, hi = cutoff
        hi = min(hi, nyq * 0.95)
        lo = min(lo, hi * 0.9)
        return signal.butter(order, [lo, hi], btype="bandpass", fs=sr, output="sos")
    return signal.butter(order, min(cutoff, nyq * 0.95), btype=kind, fs=sr, output="sos")


def _filt(x, kind, cutoff, sr, order=4):
    return signal.sosfiltfilt(_sos(kind, cutoff, sr, order), x).astype(np.float32)


def _saturate(x, drive):
    """tanh yumuşak doygunluk; giriş seviyesi korunacak biçimde ölçeklenir."""
    peak = float(np.max(np.abs(x))) + _EPS
    y = np.tanh(drive * x / peak) / np.tanh(drive)
    return (y * peak).astype(np.float32)


def _compress(x, sr, ratio, threshold_db=-24.0, attack=0.005, release=0.08):
    level = np.abs(x).astype(np.float64)
    coef_a = np.exp(-1.0 / (attack * sr))
    coef_r = np.exp(-1.0 / (release * sr))
    # Basit tepe izleyici: önce hızlı yükselen, sonra yavaş düşen zarf.
    env = signal.lfilter([1 - coef_a], [1, -coef_a], level)
    env = np.maximum(env, signal.lfilter([1 - coef_r], [1, -coef_r], level))
    ref = np.max(env) + _EPS
    env_db = 20 * np.log10(env / ref + _EPS)
    over = np.maximum(env_db - threshold_db, 0.0)
    gain = 10 ** (-over * (1 - 1 / ratio) / 20)
    y = x * gain
    return (y * (np.max(np.abs(x)) / (np.max(np.abs(y)) + _EPS))).astype(np.float32)


def _mix(dry, wet, amount):
    return ((1 - amount) * dry + amount * wet).astype(np.float32)


def _match_rms(y, ref):
    return (y * (_rms(ref) / _rms(y))).astype(np.float32)


# ------------------------------------------------------------------- efektler
def lofi(x, sr, level, **_):
    t = _t(level)
    y = _filt(x, "highpass", 120, sr, 2)
    y = _filt(y, "lowpass", 5000 - 2500 * t, sr, 4)
    y = _saturate(y, 1.0 + 5.0 * t)
    return _match_rms(y, x)


def telefon(x, sr, level, **_):
    t = _t(level)
    y = _filt(x, "bandpass", (300, 3400), sr, 4)
    y = _compress(y, sr, ratio=2 + 6 * t)
    if sr > 8000:
        g = np.gcd(int(sr), 8000)
        y = signal.resample_poly(signal.resample_poly(y, 8000 // g, int(sr) // g), int(sr) // g, 8000 // g)[: len(x)]
        y = np.pad(y, (0, len(x) - len(y))).astype(np.float32)
    return _match_rms(_mix(x, _match_rms(y, x), 0.55 + 0.45 * t), x)


def telsiz(x, sr, level, seed=7, **_):
    t = _t(level)
    y = telefon(x, sr, 100)
    y = _saturate(y, 3.0 + 9.0 * t)
    rng = np.random.default_rng(seed)
    n = int(0.12 * sr)
    noise = _filt(rng.standard_normal(n).astype(np.float32), "bandpass", (500, 3000), sr, 2)
    noise *= (0.15 + 0.6 * t) * float(np.max(np.abs(y))) / (np.max(np.abs(noise)) + _EPS)
    noise *= np.hanning(n).astype(np.float32) ** 0.3
    return np.concatenate([noise, _match_rms(y, x), noise[::-1]]).astype(np.float32)


def megafon(x, sr, level, **_):
    t = _t(level)
    y = _filt(x, "bandpass", (500, 4000), sr, 4)
    y = _saturate(y, 2.0 + 14.0 * t)
    return _match_rms(y, x)


def oda(x, sr, level, on_ayar="salon", seed=3, **_):
    t = _t(level)
    rt60 = ROOM_PRESETS.get(on_ayar, ROOM_PRESETS["salon"])[1]
    n = max(int(rt60 * sr), 16)
    rng = np.random.default_rng(seed)
    times = np.arange(n) / sr
    ir = rng.standard_normal(n) * np.exp(-6.91 * times / rt60)  # 60 dB sönüm
    ir = np.asarray(signal.sosfilt(_sos("lowpass", 6000 if on_ayar != "kilise" else 4000, sr, 2), ir))
    ir[: int(0.002 * sr)] = 0.0  # kısa ön gecikme
    ir /= np.sqrt(np.sum(ir ** 2)) + _EPS
    tail = int(min(rt60, 2.0) * sr * 0.5)
    padded = np.pad(x, (0, tail))
    wet = signal.fftconvolve(padded, ir)[: len(padded)].astype(np.float32)
    return _mix(padded, _match_rms(wet, padded), 0.7 * t)


def cizirti(x, sr, level, seed=1234, **_):
    t = _t(level)
    rng = np.random.default_rng(seed)
    n = len(x)
    ref = max(float(np.max(np.abs(x))), 0.05)
    # Kahverengi gürültü (beyaz gürültünün toplamı), DC'si alınmış.
    brown = np.cumsum(rng.standard_normal(n))
    brown = signal.sosfilt(_sos("highpass", 60, sr, 2), brown)
    brown = brown / (np.max(np.abs(brown)) + _EPS) * ref * (0.004 + 0.05 * t)
    # Seyrek tık ve pop'lar; yoğunluk sıklığı ve şiddeti belirler.
    clicks = np.zeros(n)
    count = rng.poisson(max(n / sr * (1 + 30 * t), 1))
    pos = rng.integers(0, max(n - 64, 1), count)
    amp = rng.uniform(0.05, 0.25 + 0.6 * t, count) * ref * rng.choice([-1, 1], count)
    decay = np.exp(-np.arange(48) / 6.0)
    for p, a in zip(pos, amp):
        seg = clicks[p : p + 48]
        seg += a * decay[: len(seg)]
    crackle = signal.sosfilt(_sos("highpass", 800, sr, 2), clicks)
    return (x + brown + crackle).astype(np.float32)


_FUNCS = {"lofi": lofi, "telefon": telefon, "telsiz": telsiz, "megafon": megafon, "oda": oda, "cizirti": cizirti}


# ---------------------------------------------------------- seviye (BS.1770)
def _k_weight(x, sr):
    """ITU-R BS.1770 K-ağırlıklandırma (yüksek raf + yüksek geçiren).

    Katsayılar libebur128'in türetimiyle her örnekleme hızı için hesaplanır;
    48 kHz'te ITU tablosundaki değerlerle örtüşür.
    """
    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = np.tan(np.pi * f0 / sr)
    Vh = 10 ** (G / 20)
    Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    b = [(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0]
    a = [1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0]
    y = np.asarray(signal.lfilter(b, a, x))
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = np.tan(np.pi * f0 / sr)
    a0 = 1 + K / Q + K * K
    a = [1.0, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0]
    return np.asarray(signal.lfilter([1.0, -2.0, 1.0], a, y))


def loudness_lufs(x, sr):
    """Tümleşik ses yüksekliği (mono, 400 ms blok, %75 örtüşme, iki kapı)."""
    x = np.asarray(x, dtype=np.float64)
    if not len(x):
        return float("-inf")
    y = _k_weight(x, sr)
    block, hop = int(0.4 * sr), int(0.1 * sr)
    if len(y) < block:
        z = np.array([np.mean(y ** 2)])
    else:
        starts = np.arange(0, len(y) - block + 1, hop)
        csum = np.concatenate([[0.0], np.cumsum(y ** 2)])
        z = (csum[starts + block] - csum[starts]) / block
    lk = -0.691 + 10 * np.log10(z + _EPS)
    z = z[lk > -70.0]
    if not len(z):
        return float("-inf")
    rel = -0.691 + 10 * np.log10(np.mean(z) + _EPS) - 10.0
    z2 = z[(-0.691 + 10 * np.log10(z + _EPS)) > rel]
    return float(-0.691 + 10 * np.log10(np.mean(z2 if len(z2) else z) + _EPS))


def true_peak_dbtp(x):
    up = signal.resample_poly(np.asarray(x, dtype=np.float64), 4, 1)
    return float(20 * np.log10(np.max(np.abs(up)) + _EPS))


def _limit(x, sr, ceiling_db, release=0.05):
    """İleri bakışlı basit tepe sınırlayıcı (5 ms), ani kesik yerine yumuşak kazanç."""
    from scipy.ndimage import maximum_filter1d, uniform_filter1d

    ceiling = 10 ** (ceiling_db / 20)
    win = max(int(0.005 * sr), 1)
    peak = maximum_filter1d(np.abs(x), size=2 * win + 1)
    gain = np.minimum(1.0, ceiling / (peak + _EPS))
    gain = np.minimum(gain, uniform_filter1d(gain, size=max(int(release * sr), 1)))
    return (x * gain).astype(np.float32)


def normalize(x, sr, target=TARGET_LUFS, peak=PEAK_DBTP):
    """-16 LUFS hedefi; tepe sınırlayıcı + 4x örneklemeli gerçek tepe ≤ -1 dBTP."""
    x = np.asarray(x, dtype=np.float32)
    for _ in range(3):
        lufs = loudness_lufs(x, sr)
        if not np.isfinite(lufs) or abs(target - lufs) < 0.3:
            break
        x = x * np.float32(10 ** ((target - lufs) / 20))
        x = _limit(x, sr, peak - 0.5)
    tp = true_peak_dbtp(x)
    if tp > peak:
        x = x * np.float32(10 ** ((peak - tp) / 20))
    return x.astype(np.float32)


# ---------------------------------------------------------------- dış arayüz
def clean_settings(efektler):
    """Bilinmeyen efektleri atar, yoğunluğu 0–100'e sıkıştırır, sırayı sabitler."""
    seen, out = set(), []
    for item in efektler or []:
        ad = (item or {}).get("ad")
        if ad not in EFFECTS or ad in seen:
            continue
        seen.add(ad)
        entry = {"ad": ad, "yogunluk": int(round(np.clip(float(item.get("yogunluk", 50)), 0, 100)))}
        if ad == "oda":
            entry["on_ayar"] = item.get("on_ayar") if item.get("on_ayar") in ROOM_PRESETS else "salon"
        out.append(entry)
    rank = {name: i for i, name in enumerate(COLOR_ORDER + ("oda", "cizirti"))}
    return sorted(out, key=lambda e: rank[e["ad"]])


def apply(audio, sr, efektler, level_match=True):
    """Ham sesin KOPYASINA efekt zincirini uygular; ``audio`` değişmez."""
    settings = clean_settings(efektler)
    x = np.array(audio, dtype=np.float32, copy=True)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if not settings:
        return x
    for entry in settings:
        kwargs = {"on_ayar": entry["on_ayar"]} if entry["ad"] == "oda" else {}
        x = _FUNCS[entry["ad"]](x, sr, entry["yogunluk"], **kwargs)
    if level_match:
        x = normalize(x, sr)
    return np.clip(x, -1.0, 1.0).astype(np.float32)
