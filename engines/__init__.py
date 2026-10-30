"""Yerel ses motorları — SesVer 1.2.0'da yalnız EMA Lightning ("⚡ Hızlı Mod").

VoxCPM2 hattı (Ses Kütüphanesi / Ses Oluştur / Ses Klonlama) ``app.py``'de
doğrudan çalışır ve bu pakete bağlı değildir. ``app.py`` Hızlı Mod sekmesinde
``engines.ema``'yı kullanır; bu paketi içe aktarmak torch'u, ``ema_lightning``'i
ya da modeli YÜKLEMEZ (model ilk üretimde yüklenir).
"""
from __future__ import annotations

from typing import Optional

from .base import (Capabilities, Engine, EngineConfigError, EngineError, EngineNotInstalledError,
                   InstallCancelledError, InstallError, NotSupportedError, SynthesisResult, TextTooLongError,
                   UsageInfo, VoiceInfo)

ENGINES = ("ema",)

__all__ = [
    "Capabilities", "Engine", "EngineConfigError", "EngineError", "EngineNotInstalledError",
    "InstallCancelledError", "InstallError", "NotSupportedError", "SynthesisResult", "TextTooLongError",
    "UsageInfo", "VoiceInfo", "ENGINES", "get_engine",
]


def get_engine(name: Optional[str] = "ema", **kwargs) -> Engine:
    """Motoru kurar. Ağır modül/model yüklemez; EMA'da model ilk istekte okunur."""
    name = (name or "ema").strip().lower()
    if name == "ema":
        from .ema import EmaEngine
        return EmaEngine(**kwargs)
    raise EngineConfigError(f"Bilinmeyen motor: {name!r}. Geçerli değerler: {', '.join(ENGINES)}.")
