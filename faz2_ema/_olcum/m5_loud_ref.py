"""M1-4 ebur128 + M1-8 VoxCPM2 meta.jsonl referansı + dinleme mp3'leri. Yalnız ffmpeg ve stdlib.

Çıktı: m5_loud_ref.json ve faz2_ema/*.mp3
"""
import json
import re
import statistics as st
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
WAV = HERE / "wav"
FAZ = HERE.parent
META = Path.home() / "Desktop/Projeler/Video Projeleri/titanik-saat-saat/audio/cand/meta.jsonl"
LOUD = ["a", "b_sayilar", "c_belgesel", "seed1", "seed2", "seed3", "hiz_0.9", "hiz_1.0", "hiz_1.15"]


def ebur128(p):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(p), "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    summ = r[r.rfind("Summary:"):]
    g = lambda k: float(re.search(k + r":\s+(-?[\d.]+|-inf)", summ).group(1).replace("-inf", "-999"))  # noqa: E731
    return {"I_LUFS": g("I"), "LRA_LU": g("LRA"), "TP_dBFS": g("Peak")}


def mp3(inputs, out, gap=0.5):
    if len(inputs) == 1:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(inputs[0])]
    else:
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        for p in inputs:
            cmd += ["-i", str(p)]
        parts, labels = [], []
        for i in range(len(inputs)):
            parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=mono[a{i}]")
            labels.append(f"[a{i}]")
            if i < len(inputs) - 1:
                parts.append(f"anullsrc=r=48000:cl=mono,atrim=duration={gap}[s{i}]")
                labels.append(f"[s{i}]")
        parts.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]")
        cmd += ["-filter_complex", ";".join(parts), "-map", "[out]"]
    subprocess.run(cmd + ["-codec:a", "libmp3lame", "-b:a", "192k", str(out)], check=True)


def main():
    res = {"ebur128": {n: ebur128(WAV / f"{n}.wav") for n in LOUD}}
    rows = [json.loads(l) for l in META.read_text("utf-8").splitlines() if l.strip()]
    g = [r["gen_s"] for r in rows]
    d = [r["dur"] for r in rows]
    rtf = [r["dur"] / r["gen_s"] for r in rows if r["gen_s"]]
    res["voxcpm2_ref"] = {
        "n_aday": len(rows), "n_satir": len({r["id"] for r in rows}),
        "gen_s_toplam": round(sum(g), 1), "gen_s_ort": round(st.mean(g), 1), "gen_s_medyan": round(st.median(g), 1),
        "gen_s_min": min(g), "gen_s_max": max(g), "dur_toplam": round(sum(d), 2), "dur_ort": round(st.mean(d), 2),
        "rtf_ses_bolu_uretim_medyan": round(st.median(rtf), 3), "rtf_ses_bolu_uretim_ort": round(st.mean(rtf), 3),
        "sn_uretim_per_sn_ses": round(sum(g) / sum(d), 2),
        "l01": [{k: r[k] for k in ("file", "seed", "gen_s", "dur")} for r in rows if r["id"] == "l01"],
    }
    asr = META.parent / "asr.jsonl"
    if asr.exists():
        ar = [json.loads(l) for l in asr.read_text("utf-8").splitlines() if l.strip()]
        res["voxcpm2_ref"]["asr_wer_ort"] = round(st.mean(a["wer"] for a in ar), 4)
        res["voxcpm2_ref"]["asr_wer0_orani"] = round(sum(a["wer"] == 0 for a in ar) / len(ar), 3)
    mp3([WAV / "a.wav"], FAZ / "ema_a.mp3")
    mp3([WAV / "b_sayilar.wav"], FAZ / "ema_b_sayilar.mp3")
    mp3([WAV / "c_belgesel.wav"], FAZ / "ema_c_belgesel.mp3")
    mp3([WAV / f"seed{i}.wav" for i in (1, 2, 3)], FAZ / "ema_seed_1-2-3.mp3")
    mp3([WAV / f"hiz_{s}.wav" for s in ("0.9", "1.0", "1.15")], FAZ / "ema_hiz_karsilastirma.mp3")
    (HERE / "m5_loud_ref.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
