"""Ses motoru soyutlaması (arayüzden bağımsız).

SesVer'in bugünkü üretim hattı (``app.generate_audio``) VoxCPM2'ye bağlıdır.
Bu modül, ikinci bir motor (ElevenLabs) eklenebilsin diye ortak bir sözleşme
tanımlar. Gradio'ya bağımlı değildir; arayüz bu katmanı henüz kullanmaz
(bkz. PLAN-ELEVENLABS.md, Faz 3).

Sözleşme özeti::

    engine.synthesize(text, voice, instruction, seed=None, quality="Dengeli")
        -> SynthesisResult(path=<wav yolu>, sample_rate=..., meta={...})
    engine.list_voices()                         -> [VoiceInfo]
    engine.design_voice(description, preview_text, candidates=1)
        -> [DesignPreview]
    engine.clone_voice(audio, transcript, consent, name=...)  -> VoiceInfo
    engine.usage()                               -> UsageInfo
    engine.capabilities                          -> Capabilities

Bütün motorlar çıktıyı **mono WAV** dosyası olarak verir; böylece efekt
zinciri (``effects.apply``), birleştirme ve SRT hattı motor fark etmeksizin
aynı dosyayı okur.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

QUALITY_MODES = ("Hızlı", "Dengeli", "En İyi")


# --- Hatalar ---------------------------------------------------------------
class EngineError(RuntimeError):
    """Kullanıcıya gösterilebilir Türkçe motor hatası (anahtar/metin içermez)."""

    status: Optional[int] = None       # HTTP durum kodu (bulut motorları)
    code: str = ""                     # sağlayıcının hata kodu (ör. quota_exceeded)
    request_id: Optional[str] = None   # destek için istek kimliği


class EngineConfigError(EngineError):
    """Motor yapılandırması eksik ya da geçersiz (ör. bilinmeyen SESVER_ENGINE)."""


class NotSupportedError(EngineError):
    """Bu motor istenen özelliği desteklemiyor."""


class ConsentError(EngineError, PermissionError):
    """Ses klonu için açık izin verilmedi ya da kişisel ses dışarı gönderilmek istendi."""


class AuthError(EngineError):
    """API anahtarı eksik ya da geçersiz (HTTP 401)."""


class RateLimitError(EngineError):
    """Çok fazla istek ya da eşzamanlılık sınırı (HTTP 429); yeniden denemeler de tükendi."""


class QuotaError(EngineError):
    """Kalan karakter/kredi kotası bu istek için yetmiyor."""


class PlanFeatureError(EngineError):
    """Özellik mevcut abonelik planında kapalı (ör. ücretsiz planda Instant Voice Cloning)."""


class TextTooLongError(EngineError):
    """Metin, modelin tek istekte kabul ettiği karakter sınırını aşıyor."""


class VoiceNotFoundError(EngineError):
    """Belirtilen ses kimliği bulunamadı."""


class ServiceError(EngineError):
    """Sağlayıcı tarafında beklenmeyen hata (5xx) ya da ağ hatası."""


class EngineNotInstalledError(EngineError):
    """Yerel motorun paketi ya da ağırlıkları kurulu değil (ör. EMA henüz indirilmedi)."""


class InstallError(EngineError):
    """Motor kurulumu başarısız oldu; yarım dosyalar temizlendi."""


class InstallCancelledError(EngineError):
    """Motor kurulumu kullanıcı tarafından iptal edildi; yarım dosyalar temizlendi."""


# --- Veri tipleri -----------------------------------------------------------
@dataclass(frozen=True)
class Capabilities:
    """Arayüzün (Faz 3) hangi denetimi göstereceğine karar vereceği bayraklar."""

    name: str
    local: bool                       # %100 yerel mi (metin/ses dışarı çıkmaz)
    seed: bool                        # seed parametresi var mı
    seed_deterministic: bool          # aynı seed = aynı ses garanti mi
    continuation: bool                # "devam kipi" (referans kaydı + metniyle sürdürme)
    instruction: bool                 # duygu/stil talimatı
    description_design: bool          # tariften ses tasarlama
    clone: bool                       # kayıttan ses ekleme
    multi_candidate: bool             # birden çok aday üretilebilir mi
    default_candidates: int           # arayüzün varsayılan aday sayısı
    candidates_per_design_call: int   # tek tasarım çağrısında dönen önizleme sayısı
    quality_modes: tuple = QUALITY_MODES
    max_text_chars: Optional[int] = None
    requires_api_key: bool = False
    metered: bool = False             # kota/kredi harcıyor mu
    notes: tuple = ()
    # EMA ile eklenen bayraklar (varsayılan False: eski motorların davranışı değişmez)
    speed: bool = False               # konuşma hızı parametresi
    word_timestamps: bool = False     # kelime zamanları (SRT doğrudan bunlardan üretilir)
    streaming: bool = False           # parça parça (akış) üretim
    languages: tuple = ()             # boşsa dil kısıtı bildirilmemiş demektir

    def as_dict(self):
        return asdict(self)


@dataclass
class SynthesisResult:
    path: str                 # mono WAV (PCM_16) dosya yolu
    sample_rate: int
    meta: dict = field(default_factory=dict)


@dataclass
class VoiceInfo:
    id: str
    name: str
    category: str = ""
    description: str = ""
    labels: dict = field(default_factory=dict)
    preview: Optional[str] = None     # yerel dosya yolu ya da önizleme URL'si
    engine: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class DesignPreview:
    id: str                   # VoxCPM: "seed-<n>", ElevenLabs: generated_voice_id
    path: str                 # önizleme WAV yolu
    sample_rate: int
    seed: Optional[int] = None
    meta: dict = field(default_factory=dict)


@dataclass
class UsageInfo:
    engine: str
    metered: bool
    tier: Optional[str] = None
    used: Optional[int] = None        # bu dönemde harcanan karakter/kredi
    limit: Optional[int] = None       # dönem sınırı
    remaining: Optional[int] = None
    can_clone: Optional[bool] = None
    voice_slots_used: Optional[int] = None
    voice_limit: Optional[int] = None
    extra: dict = field(default_factory=dict)


@dataclass
class QuotaEstimate:
    characters: int
    credits: float                    # tahmini kredi (muhafazakâr)
    remaining: Optional[int]          # istekten önceki kalan kota (bilinmiyorsa None)
    enough: Optional[bool]
    model: str
    tier: Optional[str] = None

    def as_dict(self):
        return asdict(self)


# --- Motor arayüzü -----------------------------------------------------------
class Engine(ABC):
    """Ortak motor sözleşmesi. Alt sınıflar Gradio'ya dokunmaz."""

    name: str = "base"

    @property
    @abstractmethod
    def capabilities(self) -> Capabilities:
        ...

    @abstractmethod
    def synthesize(self, text: str, voice: Optional[str] = None, instruction: Optional[str] = None,
                   seed: Optional[int] = None, quality: str = "Dengeli", **options: Any) -> SynthesisResult:
        ...

    @abstractmethod
    def list_voices(self) -> list:
        ...

    def design_voice(self, description: str, preview_text: str, candidates: int = 1,
                     **options: Any) -> list:
        raise NotSupportedError(f"{self.name} motoru tariften ses tasarlamayı desteklemiyor.")

    def clone_voice(self, audio: str, transcript: Optional[str], consent: bool, **options: Any) -> VoiceInfo:
        raise NotSupportedError(f"{self.name} motoru kayıttan ses eklemeyi desteklemiyor.")

    @abstractmethod
    def usage(self) -> UsageInfo:
        ...

    def estimate(self, text: str, quality: str = "Dengeli", **options: Any) -> QuotaEstimate:
        """Yerel motorlarda maliyet yok; metered motorlar bunu ezer."""
        return QuotaEstimate(characters=len(text or ""), credits=0.0, remaining=None, enough=True,
                             model=self.name)

    def __repr__(self):  # anahtar ya da ayar sızmasın diye sade tutulur
        return f"<{type(self).__name__} name={self.name!r}>"


def require_consent(consent: Any):
    """Yalnız açık ``True`` izin sayılır ("evet", 1, "on" vb. sayılmaz)."""
    if consent is not True:
        raise ConsentError(
            "Ses klonu için açık izin gerekiyor: kaydın sahibinin izni olduğunu onaylayın (consent=True)."
        )
