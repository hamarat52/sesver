"""M1-4/5/7: Whisper (TR) geri okuma + ECAPA gömüleri. Ağa çıkmaz (HF_HUB_OFFLINE).

SesVer .venv'ine ölçüm paketi KURULMAZ; bu betik mevcut voicestudio-test venv'iyle koşar
(faster-whisper 1.2.1 + speechbrain 1.1.0 zaten kurulu). Çıktı: m4_asr_ecapa.json
"""
import json
import os
import sys
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
import torchaudio  # noqa: E402

HERE = Path(__file__).resolve().parent
WAV = HERE / "wav"
ECAPA_DIR = Path.home() / "Desktop/Projeler/Video Projeleri/ses-altyapisi/crow-voices/cache/ecapa"
VOX_REF = Path.home() / "Desktop/Projeler/Video Projeleri/titanik-saat-saat/audio/cand/l01_c11.wav"
ASR = ["a", "b_sayilar", "c_belgesel", "hiz_0.9", "hiz_1.0", "hiz_1.15"]
SPK = ["seed1", "seed1_tekrar", "seed2", "seed3"]


def load16k(p):
    x, sr = sf.read(str(p), dtype="float32", always_2d=True)
    x = torch.from_numpy(x.mean(1))
    return torchaudio.functional.resample(x, sr, 16000) if sr != 16000 else x


def main():
    from faster_whisper import WhisperModel
    m = WhisperModel("medium", device="cpu", compute_type="int8")
    out = {"asr": {}, "ecapa": {}}
    for n in ASR:
        segs, _ = m.transcribe(str(WAV / f"{n}.wav"), language="tr", beam_size=5,
                               word_timestamps=True, vad_filter=False, condition_on_previous_text=False)
        words, txt = [], []
        for s in segs:
            txt.append(s.text.strip())
            words += [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3)} for w in s.words]
        out["asr"][n] = {"hyp": " ".join(txt), "words": words}
        print(n, "|", " ".join(txt)[:160], flush=True)

    from speechbrain.inference.speaker import EncoderClassifier
    enc = EncoderClassifier.from_hparams(source=str(ECAPA_DIR), savedir=str(ECAPA_DIR), run_opts={"device": "cpu"})
    emb = {}
    for n, p in [(n, WAV / f"{n}.wav") for n in SPK] + [("voxcpm2_l01_c11", VOX_REF)]:
        e = enc.encode_batch(load16k(p).unsqueeze(0)).squeeze().detach().numpy()
        emb[n] = e / np.linalg.norm(e)
    names = list(emb)
    out["ecapa"] = {f"{a}~{b}": round(float(emb[a] @ emb[b]), 4)
                    for i, a in enumerate(names) for b in names[i + 1:]}
    for k, v in out["ecapa"].items():
        print("ECAPA", k, v)
    (HERE / "m4_asr_ecapa.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")


if __name__ == "__main__":
    sys.exit(main())
