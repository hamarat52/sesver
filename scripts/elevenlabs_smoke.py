"""ElevenLabs duman testi (Faz 2) — YALNIZ Yusuf kendi terminalinde çalıştırır.

Anahtar ajan tarafından girilmez. Kullanım (worktree kökünde; venv ana repodadır):

    read -s ELEVENLABS_API_KEY && export ELEVENLABS_API_KEY   # ekrana/geçmişe yazılmaz
    ~/Desktop/Projeler/sesver/.venv/bin/python scripts/elevenlabs_smoke.py               # 0 kredi: yalnız kota + ses listesi
    ~/Desktop/Projeler/sesver/.venv/bin/python scripts/elevenlabs_smoke.py --harca       # ~50–100 kredi: 1 kısa TTS (97 karakter, Hızlı)
    ~/Desktop/Projeler/sesver/.venv/bin/python scripts/elevenlabs_smoke.py --harca --tasarim   # + ~180 kredi: 1 Voice Design çağrısı
    unset ELEVENLABS_API_KEY

Uygulamayı ya da VoxCPM2 modelini başlatmaz. Çıktılar outputs/ altına yazılır.
Klon (IVC) bilerek bu betikte YOK: kişisel ses yüklenmez.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import soundfile as sf  # noqa: E402

from engines import EngineError  # noqa: E402
from engines.elevenlabs import API_KEY_ENV, ElevenLabsEngine, mask_secret  # noqa: E402

SMOKE_TEXT = "Merhaba! Bu, SesVer için ElevenLabs duman testidir. Saat 14:30, sıcaklık 21 derece."
DESIGN_TEXT = ("Merhaba, ben SesVer için tarifle tasarlanmış yeni bir anlatıcı sesiyim. Bu cümleyi sakin, "
               "anlaşılır ve sıcak bir tonla okuyorum; böylece sesin karakterini rahatça duyabilirsiniz.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--harca", action="store_true", help="kredi harcayan TTS denemesini yap")
    parser.add_argument("--tasarim", action="store_true", help="--harca ile birlikte 1 Voice Design çağrısı")
    parser.add_argument("--ses", default=None, help="voice_id (varsayılan: listedeki ilk hazır ses)")
    parser.add_argument("--kalite", default="Hızlı", choices=("Hızlı", "Dengeli", "En İyi"))
    args = parser.parse_args(argv)

    import os
    key = os.environ.get(API_KEY_ENV, "")
    print(f"Anahtar: {mask_secret(key)}")
    engine = ElevenLabsEngine()
    try:
        before = engine.usage(refresh=True)
        print(f"1) Kota: plan={before.tier} kullanılan={before.used} sınır={before.limit} kalan={before.remaining} "
              f"klon={before.can_clone} ses_slotu={before.voice_slots_used}/{before.voice_limit}")
        voices = engine.list_voices(max_pages=1)
        print(f"2) Ses listesi: {len(voices)} ses (ilk 5) →",
              ", ".join(f"{v.name} [{v.id}] ({v.category})" for v in voices[:5]))
        if not args.harca:
            print("Kredi harcanmadı. TTS denemesi için --harca ekleyin.")
            return 0
        voice = args.ses or next((v.id for v in voices if v.category == "premade"), voices[0].id if voices else None)
        est = engine.estimate(SMOKE_TEXT, args.kalite)
        print(f"3) Tahmin: {est.characters} karakter, ~{est.credits:.0f} kredi, model={est.model}, "
              f"yeterli={est.enough}")
        res = engine.synthesize(SMOKE_TEXT, voice=voice, quality=args.kalite)
        info = sf.info(res.path)
        print(f"4) TTS: {res.path} — {info.samplerate} Hz, {info.channels} kanal, {info.duration:.2f} sn, "
              f"kaynak {res.meta.get('source_sample_rate')} Hz, istek={res.meta.get('request_id')}")
        again = engine.synthesize(SMOKE_TEXT, voice=voice, quality=args.kalite)
        print(f"5) Önbellek: ikinci istek cached={again.meta['cached']} (kredi {again.meta['credits']})")
        if args.tasarim:
            previews = engine.design_voice("calm, warm adult narrator, clear diction, medium pitch", DESIGN_TEXT)
            for p in previews:
                print(f"6) Tasarım önizlemesi: {p.id} → {p.path} ({p.meta.get('duration_secs')} sn)")
            print("   Kalıcı kaydetme bu betikte yapılmaz (ses slotu harcar).")
        after = engine.usage(refresh=True)
        if before.used is not None and after.used is not None:
            print(f"7) Gerçek harcama: {after.used - before.used} kredi (tahmin muhafazakârdı: ~{est.credits:.0f}"
                  f"{' + tasarım' if args.tasarim else ''})")
        return 0
    except EngineError as exc:
        print(f"HATA ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
