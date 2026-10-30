"""Ses motoru soyutlaması (arayüzden bağımsız).

SesVer'in ana üretim hattı (``app.generate_audio``) VoxCPM2'ye doğrudan bağlıdır.
Bu modül, yerel ek motorların (bugün yalnız EMA Lightning — "⚡ Hızlı Mod")
uyduğu ortak sözleşmeyi tanımlar. Gradio'ya bağımlı değildir.

Sözleşme özeti::

    engine.synthesize(text, voice, instruction, seed=None, quality="Dengeli")
        -> SynthesisResult(path=<wav yolu>, sample_rate=..., meta={...})
    engine.list_voices()                         -> [VoiceInfo]
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
    """Kullanıcıya gösterilebilir Türkçe motor hatası (metin içermez)."""


class EngineConfigError(EngineError):
    """Motor yapılandırması eksik ya da geçersiz (ör. bilinmeyen motor adı)."""


class NotSupportedError(EngineError):
    """Bu motor istenen özelliği desteklemiyor."""


class TextTooLongError(EngineError):
    """Metin, motorun tek istekte kabul ettiği karakter sınırını aşıyor."""


class EngineNotInstalledError(EngineError):
    """Yerel motorun paketi ya da ağırlıkları kurulu değil (ör. EMA henüz indirilmedi)."""


class InstallError(EngineError):
    """Motor kurulumu başarısız oldu; yarım dosyalar temizlendi."""


class InstallCancelledError(EngineError):
    """Motor kurulumu kullanıcı tarafından iptal edildi; yarım dosyalar temizlendi."""


# --- Veri tipleri -----------------------------------------------------------
@dataclass(frozen=True)
class Capabilities:
    """Arayüzün hangi denetimi göstereceğine karar vereceği bayraklar."""

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
    preview: Optional[str] = None     # yerel dosya yolu
    engine: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class UsageInfo:
    engine: str
    metered: bool
    tier: Optional[str] = None
    used: Optional[int] = None
    limit: Optional[int] = None
    remaining: Optional[int] = None
    can_clone: Optional[bool] = None
    voice_slots_used: Optional[int] = None
    voice_limit: Optional[int] = None
    extra: dict = field(default_factory=dict)


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

    def __repr__(self):  # ayar sızmasın diye sade tutulur
        return f"<{type(self).__name__} name={self.name!r}>"
