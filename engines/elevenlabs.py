"""ElevenLabs bulut motoru adaptörü (arayüz bağlantısı YOK — bkz. PLAN-ELEVENLABS.md).

Güvenlik sözleşmesi
-------------------
* Anahtar yalnız ``ELEVENLABS_API_KEY`` ortam değişkeninden, her istek anında
  okunur; nesnede saklanmaz, ``repr``/hata/log içinde görünmez. Bu modülün
  logger'ına anahtarı maskeleyen bir filtre takılıdır (``mask_secret``).
* Metin ve ses buluta gider: motor ``capabilities.local == False`` bildirir.
* Ses klonu (IVC) için ``consent=True`` zorunludur. SesVer kütüphanesindeki
  kişisel sesler (``voices/seslerim``) ayrıca ``allow_library_upload=True``
  verilmeden, korumalı isimler (``voice_library.PROTECTED_NAMES``) ise HİÇBİR
  koşulda yüklenmez.

Bağımlılık: yalnız stdlib (``urllib``) + projede zaten olan numpy/scipy/
soundfile. HTTP katmanı ``transport`` parametresiyle değiştirilebilir; testler
gerçek ağa çıkmaz.

API olguları (resmî doküman, Ekim 2026):
* TTS:  POST /v1/text-to-speech/{voice_id}?output_format=…  başlık ``xi-api-key``
  https://elevenlabs.io/docs/api-reference/text-to-speech/convert
* Sesler: GET /v2/voices  https://elevenlabs.io/docs/api-reference/voices/search
* Tasarım: POST /v1/text-to-voice/design → kalıcı: POST /v1/text-to-voice
  https://elevenlabs.io/docs/api-reference/text-to-voice/design
* IVC:  POST /v1/voices/add (multipart)  https://elevenlabs.io/docs/api-reference/voices/ivc/create
* Kota: GET /v1/user/subscription  https://elevenlabs.io/docs/api-reference/user/subscription/get
* Hatalar: https://elevenlabs.io/docs/eleven-api/resources/errors
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import math
import os
import random
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

import numpy as np
import soundfile as sf

from . import text_tr
from .base import (AuthError, Capabilities, ConsentError, DesignPreview, Engine, EngineConfigError, EngineError,
                   NotSupportedError, PlanFeatureError, QuotaError, QuotaEstimate, RateLimitError, ServiceError,
                   SynthesisResult, TextTooLongError, UsageInfo, VoiceInfo, VoiceNotFoundError, require_consent)

API_KEY_ENV = "ELEVENLABS_API_KEY"
DEFAULT_BASE_URL = "https://api.elevenlabs.io"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs"
TARGET_SAMPLE_RATE = 48000  # VoxCPM2 çıktısıyla aynı (config.json: out_sample_rate=48000)

# Kalite modu → model. Ortam değişkeniyle ezilebilir (SESVER_ELEVENLABS_MODEL tek modele sabitler).
# eleven_flash_v2_5: multilingual_v2 dilleri (tr dahil) + hu/no/vi; 40.000 karakter; self-serve 0,5 kredi/karakter.
# eleven_multilingual_v2: API'nin varsayılanı, "tr" listede açıkça var; 10.000 karakter; 1 kredi/karakter.
# eleven_v3: 70+ dil (Turkish dahil), 5.000 karakter; "Text to Speech API ile de kullanılabilir" (model sayfası).
# eleven_v4 BİLEREK varsayılan değil: model sayfası "Text to Dialogue API üzerinden" diyor; TTS uç
#   noktasında çalıştığı Faz 2 duman testinde görülürse SESVER_ELEVENLABS_MODEL=eleven_v4 ile açılır.
#   https://elevenlabs.io/docs/overview/models
QUALITY_MODELS = {"Hızlı": "eleven_flash_v2_5", "Dengeli": "eleven_multilingual_v2", "En İyi": "eleven_v3"}
MODEL_CHAR_LIMITS = {"eleven_v4": 10_000, "eleven_v3": 5_000, "eleven_flash_v2_5": 40_000,
                     "eleven_flash_v2": 30_000, "eleven_multilingual_v2": 10_000}
# Kota koruyucu için MUHAFAZAKÂR kredi/karakter: Flash API'de "0,5–1" (pricing SSS) → 1 alınır.
# Gerçek harcama Faz 2'de usage() farkıyla ölçülecek. https://elevenlabs.io/pricing
CREDITS_PER_CHAR = {"eleven_flash_v2_5": 1.0, "eleven_multilingual_v2": 1.0, "eleven_v4": 1.0,
                    "eleven_v3": 1.0}
# language_code multilingual_v2 için desteklenmiyor (doküman); diğerlerinde "tr" gönderilir.
NO_LANGUAGE_CODE_MODELS = {"eleven_multilingual_v2"}
DESIGN_MODEL = "eleven_multilingual_ttv_v2"
DESIGN_TEXT_MIN, DESIGN_TEXT_MAX = 100, 1000   # /text-to-voice/design `text` sınırı
DEFAULT_OUTPUT_FORMAT = "wav_24000"   # WAV kabı; 44.1 kHz WAV/PCM yalnız Pro+ planda
DEFAULT_VOICE_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0,
                          "use_speaker_boost": True, "speed": 1.0}
SEED_MAX = 4_294_967_295
RETRY_STATUSES = {429, 500, 502, 503, 504}

log = logging.getLogger("sesver.engines.elevenlabs")


# --- Anahtar maskeleme -------------------------------------------------------
def mask_secret(value: Optional[str]) -> str:
    """Anahtarı log/hata için maskeler: yalnız son 4 karakter görünür."""
    if not value:
        return "<yok>"
    return "***" + value[-4:] if len(value) > 8 else "***"


class _SecretFilter(logging.Filter):
    """Bu logger'dan geçen her kayıtta ortamdaki anahtarı maskeler (savunma katmanı)."""

    def filter(self, record):
        key = os.environ.get(API_KEY_ENV)
        if key:
            msg = record.getMessage()
            if key in msg:
                record.msg, record.args = msg.replace(key, mask_secret(key)), None
        return True


log.addFilter(_SecretFilter())


# --- HTTP katmanı ------------------------------------------------------------
class HttpResponse:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status = int(status)
        self.headers = {str(k).lower(): v for k, v in (headers or {}).items()}
        self.body = body or b""

    def json(self):
        return json.loads(self.body.decode("utf-8") or "null")


class UrllibTransport:
    """stdlib HTTP istemcisi. ``request`` imzası testlerde taklit edilir."""

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout

    def request(self, method: str, url: str, headers: dict, body: Optional[bytes] = None) -> HttpResponse:
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (sabit https taban)
                return HttpResponse(resp.status, dict(resp.headers), resp.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, dict(exc.headers or {}), exc.read() if exc.fp else b"")


def _multipart(fields: dict, files: list) -> tuple:
    """multipart/form-data gövdesi (IVC için). files: [(alan, dosya_adı, bytes, mime)]."""
    boundary = "----sesver" + uuid4().hex
    out = io.BytesIO()
    for name, value in fields.items():
        if value is None:
            continue
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode())
        out.write((value if isinstance(value, str) else json.dumps(value)).encode("utf-8") + b"\r\n")
    for name, filename, data, mime in files:
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                  f"filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode())
        out.write(data + b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


# --- Ses dönüştürme ----------------------------------------------------------
def decode_audio(data: bytes, output_format: str = "", media_type: str = "") -> tuple:
    """API yanıtını (float32 mono, sr) olarak çözer.

    * RIFF/WAVE (``wav_*``) → soundfile
    * ``pcm_<sr>`` → ham 16-bit işaretli little-endian varsayılır (Faz 2'de
      doğrulanacak; varsayılan biçim WAV olduğu için ana yol buna bağlı değil)
    * mp3/diğer → soundfile, olmazsa projedeki ``audio_prep.decode`` (PyAV)
    """
    if not data:
        raise ServiceError("ElevenLabs boş ses döndürdü; lütfen tekrar deneyin.")
    if data[:4] == b"RIFF" or data[:4] in (b"fLaC", b"OggS"):
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        return audio.mean(axis=1), int(sr)
    fmt = (output_format or "").lower()
    if fmt.startswith("pcm_") or "pcm" in (media_type or "").lower():
        sr = int(fmt.split("_")[1]) if fmt.startswith("pcm_") else 24000
        return (np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0), sr
    try:
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        return audio.mean(axis=1), int(sr)
    except Exception:  # libsndfile mp3 çözemezse PyAV'a düş
        import audio_prep  # noqa: WPS433 (isteğe bağlı, yalnız gerekince)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            handle.write(data)
        try:
            audio, sr = audio_prep.decode(handle.name)
        finally:
            os.unlink(handle.name)
        audio = np.asarray(audio, dtype=np.float32)
        return (audio.mean(axis=1) if audio.ndim > 1 else audio), int(sr)


def to_app_wav(audio: np.ndarray, sr: int, out_path: Path, target_sr: int = TARGET_SAMPLE_RATE) -> int:
    """Mono, ``target_sr`` Hz, PCM_16 WAV yazar (efekt zinciri ve VoxCPM çıktısıyla aynı biçim)."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if target_sr and int(sr) != int(target_sr):
        from scipy import signal
        g = math.gcd(int(sr), int(target_sr))
        audio = signal.resample_poly(audio, int(target_sr) // g, int(sr) // g).astype(np.float32)
        sr = int(target_sr)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), np.clip(audio, -1.0, 1.0), int(sr), subtype="PCM_16")
    return int(sr)


# --- Tarif eşlemesi ----------------------------------------------------------
def map_description(tarif: str, language: str = "Turkish") -> str:
    """``voice_designer.build_description`` çıktısını Voice Design istemine çevirir.

    Resmî rehber dili ilk cümlede açıkça yazmayı önerir ("Native <Language>.")
    ve "accent" kelimesinin lehçe kaymasına yol açabileceğini söyler:
    https://elevenlabs.io/docs/eleven-creative/voices/voice-design
    """
    body = (tarif or "").strip().strip("()").strip().rstrip(".")
    if not body:
        raise EngineError("Ses tarifi boş olamaz.")
    body = body[0].upper() + body[1:]
    prefix = "" if re.search(rf"\b{language}\b", body, re.I) else f"Native {language} speaker. "
    return f"{prefix}{body}. Excellent audio quality."


# --- Motor -------------------------------------------------------------------
class ElevenLabsEngine(Engine):
    name = "elevenlabs"

    def __init__(self, *, transport=None, output_dir: Optional[Path] = None, cache_dir: Optional[Path] = None,
                 base_url: Optional[str] = None, target_sample_rate: int = TARGET_SAMPLE_RATE,
                 output_format: str = DEFAULT_OUTPUT_FORMAT, max_retries: int = 3, backoff_base: float = 1.0,
                 backoff_max: float = 30.0, sleep: Callable[[float], None] = time.sleep,
                 normalize_text: bool = True, usage_ttl: float = 30.0, env: Optional[dict] = None):
        self._env = env if env is not None else os.environ
        self.transport = transport or UrllibTransport()
        self.base_url = (base_url or self._env.get("SESVER_ELEVENLABS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
        self.cache_dir = Path(cache_dir or self._env.get("SESVER_ELEVENLABS_CACHE_DIR")
                              or (self.output_dir / ".cache" / "elevenlabs"))
        self.target_sample_rate = int(target_sample_rate)
        self.output_format = output_format
        self.max_retries = int(max_retries)
        self.backoff_base = float(backoff_base)
        self.backoff_max = float(backoff_max)
        self._sleep = sleep
        self.normalize_text = normalize_text
        self.usage_ttl = float(usage_ttl)
        self._usage_cache = None   # (zaman, UsageInfo)

    # -- yetenekler
    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            name=self.name, local=False, seed=True, seed_deterministic=False, continuation=False,
            instruction=False, description_design=True, clone=True, multi_candidate=True,
            default_candidates=1, candidates_per_design_call=3,
            max_text_chars=min(MODEL_CHAR_LIMITS.get(m, 10_000) for m in self._quality_models().values()),
            requires_api_key=True, metered=True,
            notes=(
                "Bulut: metin ve ses ElevenLabs sunucularına gider (%100 yerel değil).",
                "seed 'en iyi çaba'dır; aynı seed aynı sesi garanti etmez.",
                "Devam kipi yok: previous_text yalnız metin sürekliliğidir, referans kayıt alınmaz.",
                "Duygu/stil talimatı bu sürümde uygulanmaz (meta['uyarilar']); v3/v4 ses etiketleri Faz 2'de.",
                "Tasarım çağrısı başına ~3 önizleme (rehber); varsayılan 1 çağrı = kota koruması.",
                "Instant Voice Cloning ücretsiz planda kapalı (Starter ve üstü).",
            ),
        )

    def __repr__(self):
        return f"<ElevenLabsEngine base_url={self.base_url!r} key={'var' if self._has_key() else 'yok'}>"

    # -- yardımcılar
    def _has_key(self) -> bool:
        return bool((self._env.get(API_KEY_ENV) or "").strip())

    def _key(self) -> str:
        key = (self._env.get(API_KEY_ENV) or "").strip()
        if not key:
            raise AuthError(f"ElevenLabs API anahtarı bulunamadı. {API_KEY_ENV} ortam değişkenini kendi "
                            "terminalinizde tanımlayın (anahtar uygulamaya ya da dosyaya yazılmaz).")
        return key

    def _quality_models(self) -> dict:
        forced = (self._env.get("SESVER_ELEVENLABS_MODEL") or "").strip()
        return {q: forced for q in QUALITY_MODELS} if forced else dict(QUALITY_MODELS)

    def model_for(self, quality: str) -> str:
        models = self._quality_models()
        return models.get(quality, models["Dengeli"])

    def prepare_text(self, text: str) -> str:
        text = (text or "").strip()
        return text_tr.normalize(text) if self.normalize_text else text

    def _request(self, method: str, path: str, *, query: Optional[dict] = None, json_body: Any = None,
                 body: Optional[bytes] = None, content_type: Optional[str] = None,
                 accept: str = "application/json") -> HttpResponse:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None}, doseq=True)
        headers = {"xi-api-key": self._key(), "Accept": accept, "User-Agent": "SesVer"}
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        attempt = 0
        while True:
            try:
                resp = self.transport.request(method, url, headers, body)
            except (OSError, urllib.error.URLError) as exc:
                if attempt < self.max_retries:
                    self._backoff(attempt, None, "ağ hatası")
                    attempt += 1
                    continue
                raise ServiceError("ElevenLabs'e bağlanılamadı. İnternet bağlantınızı kontrol edip tekrar "
                                   "deneyin.") from _scrub(exc)
            log.info("elevenlabs %s %s -> %s (deneme %d)", method, path, resp.status, attempt + 1)
            if resp.status < 400:
                return resp
            code = _error_code(resp)
            retryable = resp.status in RETRY_STATUSES and code not in _QUOTA_CODES
            if retryable and attempt < self.max_retries:
                self._backoff(attempt, resp.headers.get("retry-after"), code or str(resp.status))
                attempt += 1
                continue
            raise map_error(resp, retries=attempt)

    def _backoff(self, attempt: int, retry_after: Optional[str], reason: str):
        """Üstel geri çekilme + küçük rastgele sapma; ``Retry-After`` varsa ona uyar."""
        delay = None
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = None
        if delay is None:
            delay = self.backoff_base * (2 ** attempt) + random.uniform(0, self.backoff_base / 2)
        delay = min(max(delay, 0.0), self.backoff_max)
        log.warning("elevenlabs yeniden deneme %d/%d (%s), %.1f sn bekleniyor", attempt + 1, self.max_retries,
                    reason, delay)
        self._sleep(delay)

    # -- kota
    def usage(self, refresh: bool = False) -> UsageInfo:
        now = time.monotonic()
        if not refresh and self._usage_cache and now - self._usage_cache[0] < self.usage_ttl:
            return self._usage_cache[1]
        data = self._request("GET", "/v1/user/subscription").json() or {}
        used, limit = data.get("character_count"), data.get("character_limit")
        remaining = (limit - used) if isinstance(used, int) and isinstance(limit, int) else None
        info = UsageInfo(
            engine=self.name, metered=True, tier=data.get("tier"), used=used, limit=limit,
            remaining=max(remaining, 0) if remaining is not None else None,
            can_clone=data.get("can_use_instant_voice_cloning"), voice_slots_used=data.get("voice_slots_used"),
            voice_limit=data.get("voice_limit"),
            extra={k: data.get(k) for k in ("next_character_count_reset_unix", "max_credit_limit_extension",
                                            "can_extend_character_limit", "status") if k in data},
        )
        self._usage_cache = (now, info)
        return info

    def _spend(self, credits: float):
        """Başarılı istekten sonra önbellekteki kalan kotayı yerelde düşer (ek istek atmadan)."""
        if self._usage_cache and self._usage_cache[1].remaining is not None:
            info = self._usage_cache[1]
            info.remaining = max(0, int(info.remaining - math.ceil(credits)))
            if info.used is not None:
                info.used = int(info.used + math.ceil(credits))

    def estimate(self, text: str, quality: str = "Dengeli", *, model: Optional[str] = None,
                 check_remaining: bool = True, normalized: bool = False, **_options) -> QuotaEstimate:
        """İstekten ÖNCE: karakter, tahmini kredi ve (istenirse) kalan kota."""
        model = model or self.model_for(quality)
        prepared = text if normalized else self.prepare_text(text)
        chars = len(prepared)
        credits = chars * CREDITS_PER_CHAR.get(model, 1.0)
        remaining = tier = None
        if check_remaining:
            info = self.usage()
            remaining, tier = info.remaining, info.tier
        enough = None if remaining is None else remaining >= math.ceil(credits)
        return QuotaEstimate(characters=chars, credits=credits, remaining=remaining, enough=enough, model=model,
                             tier=tier)

    def _guard(self, estimate: QuotaEstimate):
        if estimate.enough is False:
            raise QuotaError(
                f"ElevenLabs kotası yetmiyor: bu istek yaklaşık {math.ceil(estimate.credits)} kredi istiyor, "
                f"kalan {estimate.remaining}. Metni kısaltın, kotanın yenilenmesini bekleyin ya da yerel "
                "motora (VoxCPM2) dönün."
            )

    # -- önbellek
    def cache_key(self, payload: dict) -> str:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.wav"

    def _fresh_output(self, prefix: str = "ai-ile-uretildi") -> Path:
        return self.output_dir / f"{prefix}-{uuid4().hex}.wav"

    # -- sentez
    def synthesize(self, text: str, voice: Optional[str] = None, instruction: Optional[str] = None,
                   seed: Optional[int] = None, quality: str = "Dengeli", *, voice_settings: Optional[dict] = None,
                   use_cache: bool = True, previous_text: Optional[str] = None, next_text: Optional[str] = None,
                   **_options) -> SynthesisResult:
        voice = (voice or self._env.get("SESVER_ELEVENLABS_VOICE") or "").strip()
        if not voice:
            raise EngineConfigError("ElevenLabs için bir ses seçin (voice_id). Sesleri list_voices() verir.")
        prepared = self.prepare_text(text)
        if not prepared:
            raise EngineError("Lütfen okunacak bir metin yazın.")
        model = self.model_for(quality)
        limit = MODEL_CHAR_LIMITS.get(model)
        if limit and len(prepared) > limit:
            raise TextTooLongError(f"Metin {len(prepared)} karakter; {model} tek istekte en fazla {limit} "
                                   "karakter kabul eder. Metni bölün.")
        if seed is not None and not (0 <= int(seed) <= SEED_MAX):
            raise EngineError(f"seed 0 ile {SEED_MAX} arasında olmalı.")
        settings = {**DEFAULT_VOICE_SETTINGS, **(voice_settings or {})}
        body: dict[str, Any] = {"text": prepared, "model_id": model, "voice_settings": settings,
                "apply_text_normalization": "auto"}
        if model not in NO_LANGUAGE_CODE_MODELS:
            body["language_code"] = "tr"
        if seed is not None:
            body["seed"] = int(seed)
        if previous_text:
            body["previous_text"] = self.prepare_text(previous_text)
        if next_text:
            body["next_text"] = self.prepare_text(next_text)
        warnings = []
        if instruction:
            warnings.append("Duygu/stil talimatı ElevenLabs motorunda bu sürümde uygulanmadı.")
        key = self.cache_key({"v": 1, "voice": voice, "fmt": self.output_format, "sr": self.target_sample_rate,
                              **body})
        meta = {"engine": self.name, "model": model, "voice": voice, "characters": len(prepared),
                "seed": seed, "quality": quality, "uyarilar": warnings, "cache_key": key}
        cached = self._cache_path(key)
        if use_cache and cached.is_file():
            out = self._fresh_output()
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, out)
            log.info("elevenlabs önbellek isabeti (kota harcanmadı) model=%s ses=%s", model, voice)
            return SynthesisResult(path=str(out), sample_rate=sf.info(str(out)).samplerate,
                                   meta={**meta, "cached": True, "credits": 0.0})
        estimate = self.estimate(prepared, model=model, normalized=True)
        self._guard(estimate)
        resp = self._request("POST", f"/v1/text-to-speech/{urllib.parse.quote(voice, safe='')}",
                             query={"output_format": self.output_format}, json_body=body, accept="audio/*")
        audio, sr = decode_audio(resp.body, self.output_format, resp.headers.get("content-type", ""))
        out = self._fresh_output()
        out_sr = to_app_wav(audio, sr, out, self.target_sample_rate)
        if use_cache:
            cached.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out, cached)
        self._spend(estimate.credits)
        log.info("elevenlabs sentez tamam model=%s ses=%s karakter=%d", model, voice, len(prepared))
        return SynthesisResult(path=str(out), sample_rate=out_sr, meta={
            **meta, "cached": False, "credits": estimate.credits, "remaining_before": estimate.remaining,
            "source_sample_rate": sr, "request_id": resp.headers.get("request-id"),
            "character_cost_header": resp.headers.get("character-cost"),
        })

    # -- sesler
    def list_voices(self, *, search: Optional[str] = None, max_pages: int = 10) -> list:
        voices, token = [], None
        for _ in range(max_pages):
            data = self._request("GET", "/v2/voices", query={"page_size": 100, "search": search,
                                                              "next_page_token": token}).json() or {}
            for v in data.get("voices", []):
                voices.append(VoiceInfo(id=v.get("voice_id", ""), name=v.get("name", ""),
                                        category=v.get("category") or "", description=v.get("description") or "",
                                        labels=v.get("labels") or {}, preview=v.get("preview_url"),
                                        engine=self.name))
            token = data.get("next_page_token")
            if not data.get("has_more") or not token:
                break
        return voices

    # -- tarif
    def design_voice(self, description: str, preview_text: str, candidates: int = 1, *, seed: Optional[int] = None,
                     guidance_scale: Optional[float] = None, loudness: Optional[float] = None,
                     map_tarif: bool = True, **_options) -> list:
        """Tariften önizleme sesleri. Kalıcı kaydetmez — bkz. ``save_designed_voice``.

        ``candidates``: döndürülecek önizleme sayısı. Rehbere göre bir çağrı ~3
        önizleme üretir ve yalnız önizleme metni kadar kredi harcar; varsayılan 1
        aday = 1 çağrı. Daha fazlası gerekiyorsa çağrı sayısı ``ceil(candidates /
        önizleme_sayısı)`` olur ve HER çağrı kota koruyucudan geçer.
        """
        candidates = max(1, int(candidates))
        text = self.prepare_text(preview_text)
        if not DESIGN_TEXT_MIN <= len(text) <= DESIGN_TEXT_MAX:
            raise EngineError(f"Örnek metin {len(text)} karakter; ElevenLabs ses tasarımı "
                              f"{DESIGN_TEXT_MIN}–{DESIGN_TEXT_MAX} karakter ister.")
        prompt = map_description(description) if map_tarif else (description or "").strip()
        previews: list = []
        call = 0
        while len(previews) < candidates and call < candidates:
            estimate = self.estimate(text, model=DESIGN_MODEL, normalized=True)
            self._guard(estimate)
            body: dict[str, Any] = {"voice_description": prompt, "text": text, "model_id": DESIGN_MODEL}
            call_seed = None if seed is None else int(seed) + call
            if call_seed is not None:
                body["seed"] = call_seed
            if guidance_scale is not None:
                body["guidance_scale"] = float(guidance_scale)
            if loudness is not None:
                body["loudness"] = float(loudness)
            data = self._request("POST", "/v1/text-to-voice/design", json_body=body).json() or {}
            self._spend(estimate.credits)
            for item in data.get("previews", []):
                raw = base64.b64decode(item.get("audio_base_64") or "")
                audio, sr = decode_audio(raw, "", item.get("media_type", ""))
                out = self._fresh_output("tasarim-onizleme")
                out_sr = to_app_wav(audio, sr, out, self.target_sample_rate)
                previews.append(DesignPreview(
                    id=item.get("generated_voice_id", ""), path=str(out), sample_rate=out_sr, seed=call_seed,
                    meta={"engine": self.name, "prompt": prompt, "call": call + 1,
                          "duration_secs": item.get("duration_secs"), "language": item.get("language"),
                          "credits_this_call": estimate.credits}))
            call += 1
            if not data.get("previews"):
                break
        return previews[:candidates]

    def save_designed_voice(self, generated_voice_id: str, name: str, description: str,
                            labels: Optional[dict] = None) -> VoiceInfo:
        """Seçilen önizlemeyi hesabınızda kalıcı ses yapar (POST /v1/text-to-voice)."""
        if not generated_voice_id or not (name or "").strip():
            raise EngineError("Kaydetmek için bir önizleme ve ses adı gerekli.")
        data = self._request("POST", "/v1/text-to-voice", json_body={
            "voice_name": name.strip(), "voice_description": description, "generated_voice_id": generated_voice_id,
            "labels": labels}).json() or {}
        return VoiceInfo(id=data.get("voice_id", ""), name=data.get("name") or name, category="generated",
                         description=description, labels=data.get("labels") or {}, engine=self.name)

    # -- klon
    def clone_voice(self, audio: str, transcript: Optional[str], consent: bool, *, name: str = "SesVer klon",
                    description: str = "", allow_library_upload: bool = False,
                    remove_background_noise: bool = False, **_options) -> VoiceInfo:
        """Instant Voice Cloning. ``transcript`` API'ye GÖNDERİLMEZ (IVC almıyor; gizlilik)."""
        require_consent(consent)
        path = Path(audio or "")
        _assert_uploadable(path, name, allow_library_upload)
        if not path.is_file():
            raise EngineError("Klon için ses dosyası bulunamadı.")
        info = self.usage()
        if info.can_clone is False:
            raise PlanFeatureError("Bu ElevenLabs planında Instant Voice Cloning kapalı (ücretsiz planda yok; "
                                   "Starter ve üstü gerekir).")
        mime = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
        body, ctype = _multipart({"name": name, "description": description or None,
                                  "remove_background_noise": "true" if remove_background_noise else "false"},
                                 [("files", path.name, path.read_bytes(), mime)])
        data = self._request("POST", "/v1/voices/add", body=body, content_type=ctype).json() or {}
        return VoiceInfo(id=data.get("voice_id", ""), name=name, category="cloned", description=description,
                         engine=self.name, extra={"requires_verification": data.get("requires_verification")})


# --- Hata eşlemesi -----------------------------------------------------------
_QUOTA_CODES = {"quota_exceeded", "insufficient_credits", "payment_required"}
_PLAN_CODES = {"feature_not_available", "subscription_required", "can_not_use_instant_voice_cloning"}
_RATE_CODES = {"rate_limit_exceeded", "concurrent_limit_exceeded", "system_busy", "too_many_concurrent_requests",
               "rate_limit_error"}
_AUTH_CODES = {"invalid_api_key", "missing_api_key", "authentication_error", "unauthorized"}


def _detail(resp: HttpResponse) -> dict:
    try:
        data = resp.json()
    except (ValueError, UnicodeDecodeError):
        return {}
    detail = data.get("detail") if isinstance(data, dict) else None
    return detail if isinstance(detail, dict) else {}


def _error_code(resp: HttpResponse) -> str:
    d = _detail(resp)
    return str(d.get("code") or d.get("status") or d.get("type") or "")


def map_error(resp: HttpResponse, retries: int = 0) -> EngineError:
    """HTTP hata yanıtını Türkçe, kullanıcı dostu bir istisnaya çevirir (anahtar/metin içermez)."""
    d = _detail(resp)
    codes = {str(d.get(k)) for k in ("code", "status", "type") if d.get(k)}
    req = d.get("request_id")
    suffix = f" (istek: {req})" if req else ""
    if codes & _QUOTA_CODES or resp.status == 402:
        err = QuotaError("ElevenLabs kotanız/krediniz bu istek için yetmiyor. Kotanın yenilenmesini bekleyin, "
                         "metni kısaltın ya da yerel motora (VoxCPM2) dönün." + suffix)
    elif resp.status == 401 or codes & _AUTH_CODES:
        err = AuthError("ElevenLabs API anahtarı geçersiz ya da eksik. Anahtarı kendi terminalinizde "
                        f"{API_KEY_ENV} olarak yeniden tanımlayın." + suffix)
    elif codes & _PLAN_CODES:
        err = PlanFeatureError("Bu özellik mevcut ElevenLabs planınızda kapalı." + suffix)
    elif resp.status == 403:
        err = PlanFeatureError("Bu işlem için yetkiniz yok ya da özellik planınızda kapalı (ses/model erişimi)."
                               + suffix)
    elif resp.status == 429 or codes & _RATE_CODES:
        err = RateLimitError(f"ElevenLabs şu an çok yoğun ya da istek sınırına ulaşıldı; {retries} yeniden "
                             "denemeden sonra da olmadı. Biraz bekleyip tekrar deneyin." + suffix)
    elif codes & {"voice_not_found", "invalid_voice_id"} or resp.status == 404:
        err = VoiceNotFoundError("Seçili ElevenLabs sesi bulunamadı; ses listesini yenileyin." + suffix)
    elif codes & {"max_character_limit_exceeded", "text_too_long"}:
        err = TextTooLongError("Metin bu model için çok uzun; metni bölün." + suffix)
    elif resp.status >= 500:
        err = ServiceError("ElevenLabs tarafında geçici bir sorun var; biraz sonra tekrar deneyin." + suffix)
    else:
        err = EngineError(f"ElevenLabs isteği reddetti (HTTP {resp.status}"
                          + (f", {sorted(codes)[0]}" if codes else "") + ")." + suffix)
    err.status = resp.status
    err.code = next(iter(sorted(codes)), "")
    err.request_id = req
    return err


def _scrub(exc: BaseException) -> BaseException:
    """Ağ istisnalarında URL/başlık sızıntısına karşı yalnız tür adını taşı."""
    return EngineError(type(exc).__name__)


def _assert_uploadable(path: Path, name: str, allow_library_upload: bool):
    """Kişisel ses koruması: korumalı isimler asla, kütüphane sesleri yalnız açık izinle yüklenir."""
    import voice_library as vlib  # repo kökü sys.path'te (uygulama/test kökten çalışır)
    if vlib.is_protected(name or "", str(path)):
        raise ConsentError("Kişisel klon sesleri ElevenLabs'e yüklenmez (korumalı isim).")
    try:
        resolved = path.resolve()
        in_library = vlib.VOICES_DIR.resolve() in resolved.parents
    except OSError:
        in_library = False
    if in_library and allow_library_upload is not True:
        raise ConsentError("Bu ses SesVer kütüphanenizde kayıtlı kişisel bir ses. Buluta yüklemek için ayrıca "
                           "açık izin gerekiyor (allow_library_upload=True).")
