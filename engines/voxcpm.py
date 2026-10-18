"""VoxCPM2 (yerel) motoru: ``app.generate_audio`` etrafında İNCE sarmalayıcı.

Üretim mantığı yeniden yazılmaz; ``app.generate_audio`` jeneratörü aynen
çağrılır ve son ``yield`` değeri okunur. Böylece model kilidi, seed,
kalite (inference_timesteps), devam/kontrollü klon kipleri ve WAV yazımı
bugünkü uygulamayla birebir aynı kalır. ``app`` modülü yalnız çağrı anında
içe aktarılır (motor seçimi Gradio'yu ya da modeli yüklemez).
"""
from __future__ import annotations

from typing import Any, Optional

from .base import (Capabilities, DesignPreview, Engine, EngineError, SynthesisResult, UsageInfo, VoiceInfo,
                   VoiceNotFoundError, require_consent)

RANDOM_VOICE = "rastgele"


def _noop_progress(*_args, **_kwargs):
    """``gr.Progress`` yerine geçen sessiz ilerleme geri çağrısı (arayüz yok)."""


def _app():
    import app  # noqa: WPS433 — tembel içe aktarma; model yüklenmez (get_model ilk üretimde çağrılır)
    return app


class VoxCPMEngine(Engine):
    name = "voxcpm"

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            name=self.name, local=True, seed=True, seed_deterministic=True, continuation=True, instruction=True,
            description_design=True, clone=True, multi_candidate=True, default_candidates=4,
            candidates_per_design_call=1, max_text_chars=500, requires_api_key=False, metered=False,
            notes=("%100 yerel: metin ve ses bilgisayardan çıkmaz.",
                   "Aynı tarif + aynı seed = aynı ses (kabul testi).",
                   "Kayıtlı ses + Nötr → devam kipi; kayıtlı ses + duygu → kontrollü klon."),
        )

    # -- çekirdek: generate_audio'yu sür, son çıktıyı al
    def _run(self, text, reference_audio, instruction, prompt_text, seed, timesteps, voice_id, log_mode=None):
        app = _app()
        try:
            last = None
            for last in app.generate_audio(text, reference_audio, instruction, prompt_text,
                                           progress=_noop_progress, seed=seed, timesteps=timesteps,
                                           voice_id=voice_id, log_mode=log_mode):
                pass
        except Exception as exc:  # gr.Error dahil: kullanıcı mesajı korunur
            if type(exc).__name__ == "Error" or isinstance(exc, EngineError):
                raise EngineError(str(exc)) from exc
            raise
        if not last or not last[0]:
            raise EngineError(last[2] if last else "Üretim başarısız.")
        import soundfile as sf
        return last[0], int(sf.info(last[0]).samplerate), last[2]

    def _instruction(self, instruction: Optional[str]):
        """Türkçe duygu etiketi ("Neşeli") ya da doğrudan İngilizce talimat kabul edilir."""
        if not instruction:
            return None
        return _app().EMOTIONS.get(instruction, instruction)

    def synthesize(self, text: str, voice: Optional[str] = None, instruction: Optional[str] = None,
                   seed: Optional[int] = None, quality: str = "Dengeli", **options: Any) -> SynthesisResult:
        """``app.library_generate`` ile aynı kip seçimi (+ isteğe bağlı seed)."""
        app = _app()
        steps = app.QUALITY.get(quality, 10)
        instr = self._instruction(instruction)
        voice = voice or RANDOM_VOICE
        if voice == RANDOM_VOICE:
            ref, prompt, mode = None, None, ("tarif" if instr else "referanssiz")
        else:
            entry = app.vlib.get_voice(voice)
            if not entry:
                raise VoiceNotFoundError("Seçili ses bulunamadı; kütüphaneden yeniden seçin.")
            ref = entry["ref_wav"]
            prompt = None if instr else entry["ref_text"]
            mode = "kontrollu_klon" if instr else "devam"
        path, sr, status = self._run(text, ref, instr, prompt, seed, steps, voice, options.get("log_mode"))
        return SynthesisResult(path=path, sample_rate=sr, meta={
            "engine": self.name, "mode": mode, "voice": voice, "seed": seed, "quality": quality,
            "timesteps": steps, "characters": len((text or "").strip()), "status": status, "credits": 0.0})

    def list_voices(self) -> list:
        app = _app()
        out = [VoiceInfo(id=RANDOM_VOICE, name="Rastgele ses", category="Referanssız", engine=self.name)]
        for v in app.vlib.list_voices():
            out.append(VoiceInfo(id=v["id"], name=v["ad"], category=v.get("kategori", ""),
                                 description=v.get("aciklama", ""), preview=v.get("ornek"), engine=self.name,
                                 extra={"hazir": v.get("hazir")}))
        return out

    def design_voice(self, description: str, preview_text: str, candidates: int = 4, *,
                     seeds: Optional[list] = None, batch: int = 0, quality: str = "Dengeli",
                     **_options) -> list:
        """``design_candidates`` ile aynı sözleşme: aynı tarif + aynı cümle, farklı seed."""
        app = _app()
        tarif = (description or "").strip().strip("()").strip()
        if not tarif:
            raise EngineError("Önce seçim yapın ya da bir tarif yazın.")
        seeds = list(seeds or app.vdes.candidate_seeds(batch))[:max(1, int(candidates))]
        previews = []
        for seed in seeds:
            path, sr, _status = self._run(preview_text, None, tarif, None, seed, app.QUALITY.get(quality, 10),
                                          f"aday-{seed}", log_mode="tasarim")
            previews.append(DesignPreview(id=f"seed-{seed}", path=path, sample_rate=sr, seed=seed,
                                          meta={"engine": self.name, "tarif": tarif}))
        return previews

    def clone_voice(self, audio: str, transcript: Optional[str], consent: bool, *, name: str = "",
                    description: str = "", category: str = "Genel", **_options) -> VoiceInfo:
        """Yerel kütüphaneye kaydeder (``save_uploaded_ui`` ile aynı ``vlib.save_voice`` çağrısı)."""
        require_consent(consent)
        if not (transcript or "").strip():
            raise EngineError("Kaydın metni boş olamaz; devam kipi bu metinle çalışır.")
        app = _app()
        try:
            voice = app.vlib.save_voice(ad=name, ref_wav=audio, ref_text=transcript, kaynak="yüklendi",
                                        aciklama=description, kategori=(category or "").strip() or "Genel")
        except (app.vlib.VoiceError, PermissionError) as exc:
            raise EngineError(str(exc)) from exc
        return VoiceInfo(id=voice["id"], name=voice["ad"], category=voice.get("kategori", ""),
                         description=voice.get("aciklama", ""), engine=self.name)

    def usage(self) -> UsageInfo:
        return UsageInfo(engine=self.name, metered=False, extra={"not": "Yerel motor; kota yok."})
