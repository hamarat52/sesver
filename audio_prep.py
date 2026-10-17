"""Yüklenen ses dosyasını referans sese hazırlar (WAV/MP3/M4A → mono 16-bit WAV).

Çözme PyAV ile yapılır (kendi FFmpeg kütüphaneleriyle gelir; sistemde ffmpeg
gerekmez). Müzik/yankı/çoklu konuşmacı modelsiz güvenilir biçimde tespit
edilemez; bu yüzden yalnız uyarı verilir, "tespit edildi" denmez.
"""
from pathlib import Path

import numpy as np
import soundfile as sf

ALLOWED_EXT = {".wav", ".mp3", ".m4a"}
MIN_SECONDS = 8.0
MAX_SECONDS = 20.0
CLIP_LEVEL = 0.999
CLIP_RATIO = 0.001
LOW_RMS_DBFS = -35.0
CLEAN_NOTE = "Temiz ve tek kişilik kayıt önerilir: müzik, yankı ya da arka planda başka konuşmacı olmasın."


class PrepError(ValueError):
    """Kullanıcıya gösterilebilir Türkçe hazırlık hatası."""


def decode(path):
    """Dosyayı mono float32'ye çözer; örnekleme hızı korunur."""
    path = Path(path)
    if path.suffix.lower() not in ALLOWED_EXT:
        raise PrepError("Yalnız WAV, MP3 ve M4A dosyaları kabul edilir.")
    if path.suffix.lower() == ".wav":
        try:
            audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
            return audio.mean(axis=1), int(sr)
        except RuntimeError:
            pass  # sıra dışı WAV kodlaması: PyAV ile dene
    import av

    try:
        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise PrepError("Dosyada ses bulunamadı.")
            stream = container.streams.audio[0]
            sr = int(stream.rate or stream.sample_rate)
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=sr)
            chunks = []
            for frame in container.decode(stream):
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray().reshape(-1))
            for out in resampler.resample(None):
                chunks.append(out.to_ndarray().reshape(-1))
    except PrepError:
        raise
    except Exception as exc:  # PyAV hataları (FFmpegError vb.) ve OSError
        raise PrepError("Ses dosyası okunamadı; bozuk ya da desteklenmeyen bir biçim olabilir.") from exc
    if not chunks:
        raise PrepError("Dosyada ses bulunamadı.")
    return np.concatenate(chunks).astype(np.float32), sr


def trim_silence(audio, sr, top_db=40):
    import librosa

    if not len(audio):
        return audio
    _trimmed, (start, end) = librosa.effects.trim(audio, top_db=top_db, frame_length=2048, hop_length=512)
    pad = int(0.05 * sr)
    return audio[max(start - pad, 0): min(end + pad, len(audio))]


def level_warnings(audio):
    warnings = []
    if len(audio) and np.mean(np.abs(audio) >= CLIP_LEVEL) > CLIP_RATIO:
        warnings.append("Kayıtta kırpılma (clip) var; ses bozuk duyulabilir. Daha düşük seviyede kaydedin.")
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)) + 1e-12)) if len(audio) else 0.0
    if 20 * np.log10(rms + 1e-12) < LOW_RMS_DBFS:
        warnings.append("Kayıt seviyesi çok düşük; mikrofona daha yakın kaydedin.")
    return warnings


def analyze(path):
    """Çöz + sessizliği kırp. Dönüş: ses, sr, süre, uyarılar."""
    audio, sr = decode(path)
    audio = trim_silence(audio, sr)
    duration = len(audio) / float(sr)
    if duration < 1.0:
        raise PrepError("Kayıtta konuşma bulunamadı ya da çok kısa.")
    warnings = level_warnings(audio)
    if duration < MIN_SECONDS:
        warnings.append(f"Kayıt {duration:.1f} sn; en az {MIN_SECONDS:.0f} sn olmalı.")
    elif duration > MAX_SECONDS:
        warnings.append(f"Kayıt {duration:.1f} sn; en fazla {MAX_SECONDS:.0f} sn. Kullanılacak aralığı seçin.")
    return {"audio": audio, "sr": sr, "duration": duration, "warnings": warnings}


def cut(audio, sr, start_s, end_s):
    """Seçilen aralığı keser ve 8–20 sn kuralını doğrular."""
    start_s, end_s = float(start_s), float(end_s)
    if end_s <= start_s:
        raise PrepError("Bitiş, başlangıçtan sonra olmalı.")
    length = end_s - start_s
    if length < MIN_SECONDS - 1e-6 or length > MAX_SECONDS + 1e-6:
        raise PrepError(f"Seçilen aralık {length:.1f} sn; {MIN_SECONDS:.0f}–{MAX_SECONDS:.0f} sn arası olmalı.")
    return audio[int(start_s * sr): int(end_s * sr)]


def write_wav(audio, sr, out_path):
    """Mono, 16-bit PCM WAV yazar."""
    sf.write(str(out_path), np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0), int(sr), subtype="PCM_16")
    return Path(out_path)
