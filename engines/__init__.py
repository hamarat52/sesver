"""Motor seçimi: yalnız yapılandırma/ortam değişkeni (arayüz bağlantısı YOK).

    SESVER_ENGINE=voxcpm      (varsayılan, %100 yerel)
    SESVER_ENGINE=elevenlabs  (bulut; ELEVENLABS_API_KEY gerekir)

Bugünkü ``app.py`` bu modülü KULLANMAZ; uygulama değişmeden VoxCPM2 ile
açılır. Faz 3'te (Yusuf'un onayıyla) arayüz ``get_engine()`` üzerinden bağlanır.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

from .base import (AuthError, Capabilities, ConsentError, DesignPreview, Engine, EngineConfigError, EngineError,
                   NotSupportedError, PlanFeatureError, QuotaError, QuotaEstimate, RateLimitError, ServiceError,
                   SynthesisResult, TextTooLongError, UsageInfo, VoiceInfo, VoiceNotFoundError)

ENGINE_ENV = "SESVER_ENGINE"
DEFAULT_ENGINE = "voxcpm"
ENGINES = ("voxcpm", "elevenlabs")

__all__ = [
    "AuthError", "Capabilities", "ConsentError", "DesignPreview", "Engine", "EngineConfigError", "EngineError",
    "NotSupportedError", "PlanFeatureError", "QuotaError", "QuotaEstimate", "RateLimitError", "ServiceError",
    "SynthesisResult", "TextTooLongError", "UsageInfo", "VoiceInfo", "VoiceNotFoundError",
    "ENGINE_ENV", "DEFAULT_ENGINE", "ENGINES", "selected_engine_name", "get_engine",
]


def selected_engine_name(env: Optional[Mapping[str, str]] = None) -> str:
    source: Mapping[str, str] = os.environ if env is None else env
    name = (source.get(ENGINE_ENV) or DEFAULT_ENGINE).strip().lower()
    if name not in ENGINES:
        raise EngineConfigError(f"Bilinmeyen motor: {name!r}. {ENGINE_ENV} için geçerli değerler: "
                                f"{', '.join(ENGINES)}.")
    return name


def get_engine(name: Optional[str] = None, **kwargs) -> Engine:
    """Motoru kurar. Ağır modül/model yüklemez; ElevenLabs'te anahtar ilk istekte okunur."""
    name = (name or selected_engine_name()).strip().lower()
    if name == "voxcpm":
        from .voxcpm import VoxCPMEngine
        return VoxCPMEngine()
    if name == "elevenlabs":
        from .elevenlabs import ElevenLabsEngine
        return ElevenLabsEngine(**kwargs)
    raise EngineConfigError(f"Bilinmeyen motor: {name!r}. Geçerli değerler: {', '.join(ENGINES)}.")
