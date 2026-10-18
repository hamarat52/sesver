"""M1-4/5/7 analiz: WER/CER, sayı kontrolü, SRT hizası. SesVer .venv'i ile koşar (normalizer_tr orada).

Hem referans hem Whisper çıktısı aynı söyleyiş biçimine çevrilir (normalizer_tr, fallback), sonra
Türkçe küçük harf + noktalama atma + şapka (â→a) atma. Yani "29 Mayıs" ile "yirmi dokuz mayıs" eşit sayılır.
Çıktı: m6_analiz.json
"""
import difflib
import json
import re
import statistics as st
import unicodedata
from pathlib import Path

from normalizer_tr import Normalizer

HERE = Path(__file__).resolve().parent
FAZ = HERE.parent
WAV = HERE / "wav"
TR = frozenset("çğıöşü")
N = Normalizer()


def spoken(t):
    try:
        t = N.normalize(t, ambiguity_policy="fallback").normalized_text
    except Exception:
        pass
    t = t.replace("’", "'").replace("İ", "i").replace("I", "ı").lower()
    out = []
    for ch in t:
        if ch not in TR:
            ch = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
        out.append(ch if ch.isalpha() or ch == " " else (" " if ch != "'" else ""))
    return re.sub(r"\s+", " ", "".join(out)).strip()


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer_cer(ref, hyp):
    r, h = spoken(ref), spoken(hyp)
    rw, hw = r.split(), h.split()
    diff = [(o, " ".join(rw[i1:i2]), " ".join(hw[j1:j2]))
            for o, i1, i2, j1, j2 in difflib.SequenceMatcher(a=rw, b=hw, autojunk=False).get_opcodes() if o != "equal"]
    return {"wer": round(lev(rw, hw) / len(rw), 4), "cer": round(lev(r.replace(" ", ""), h.replace(" ", "")) / len(r.replace(" ", "")), 4),
            "n_ref_words": len(rw), "farklar": diff}


def srt_cues(p):
    cues = []
    for blk in p.read_text("utf-8").strip().split("\n\n"):
        ln = blk.splitlines()
        a, b = ln[1].split(" --> ")
        sec = lambda s: int(s[:2]) * 3600 + int(s[3:5]) * 60 + float(s[6:].replace(",", "."))  # noqa: E731
        cues.append({"s": sec(a), "e": sec(b), "text": " ".join(ln[2:])})
    return cues


def srt_align(engine_words, asr_words, cues):
    # Whisper kelimelerini söyleyiş biçimine aç (ör. "23.40" -> 3 jeton), zamanı jetonlara eşit böl.
    toks, ts = [], []
    for w in asr_words:
        parts = spoken(w["w"]).split() or [""]
        step = (w["e"] - w["s"]) / len(parts)
        for k, p in enumerate(parts):
            toks.append(p)
            ts.append((w["s"] + k * step, w["s"] + (k + 1) * step))
    etoks = [spoken(w["text"]) for w in engine_words]
    sm = difflib.SequenceMatcher(a=etoks, b=toks, autojunk=False)
    match = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            match[blk.a + k] = blk.b + k
    d_word = [engine_words[i]["start"] - ts[j][0] for i, j in match.items()]
    # Kipleri motor kelimelerine sırayla eşle (kip metni = motor kelimeleri, boşlukla).
    idx, cue_d, cue_rows = 0, [], []
    for c in cues:
        n = len(c["text"].split())
        first, last = idx, idx + n - 1
        idx += n
        row = {"s": c["s"], "e": c["e"], "dur": round(c["e"] - c["s"], 3), "text": c["text"],
               "srt_s_eq_motor": abs(c["s"] - engine_words[first]["start"]) < 1e-3}
        if first in match:
            row["d_start"] = round(c["s"] - ts[match[first]][0], 3)
            cue_d.append(row["d_start"])
        if last in match:
            row["d_end"] = round(c["e"] - ts[match[last]][1], 3)
        cue_rows.append(row)
    absd = sorted(abs(x) for x in d_word)
    absc = sorted(abs(x) for x in cue_d)
    p95 = lambda xs: xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]  # noqa: E731
    return {"motor_kelime": len(engine_words), "whisper_jeton": len(toks), "eslesen_kelime": len(match),
            "kapsama": round(len(match) / len(engine_words), 3), "kip_sayisi": len(cues), "kip_sayisi_kelime_toplami": idx,
            "kelime_abs_d_medyan": round(st.median(absd), 3), "kelime_abs_d_p95": round(p95(absd), 3), "kelime_abs_d_max": round(absd[-1], 3),
            "kelime_d_ort_isaretli": round(st.mean(d_word), 3),
            "kip_bas_abs_d_medyan": round(st.median(absc), 3), "kip_bas_abs_d_p95": round(p95(absc), 3), "kip_bas_abs_d_max": round(absc[-1], 3),
            "kip_bas_200ms_ici": round(sum(x <= 0.2 for x in absc) / len(absc), 3),
            "kip_sure_min": min(r["dur"] for r in cue_rows), "kip_1sn_alti": sum(r["dur"] < 1.0 for r in cue_rows),
            "kip_motor_ile_ayni_bas": all(r["srt_s_eq_motor"] for r in cue_rows), "kipler": cue_rows}


def main():
    gen = {r["name"]: r for r in json.loads((HERE / "m3_uretim.json").read_text("utf-8"))}
    asr = json.loads((HERE / "m4_asr_ecapa.json").read_text("utf-8"))["asr"]
    out = {"wer_cer": {}}
    for n, a in asr.items():
        out["wer_cer"][n] = {"hyp": a["hyp"], **wer_cer(gen[n]["text"], a["hyp"])}
    hb = asr["b_sayilar"]["hyp"]
    out["sayi_kontrolu_b"] = {k: (k in hb) for k in ("1453'te", "29 Mayıs", "saat 6'da", "TBMM", "23 Nisan", "1920'de")}
    hc = asr["c_belgesel"]["hyp"]
    out["c_whisper_tam"] = hc
    ew = json.loads((WAV / "c_belgesel.words.json").read_text("utf-8"))
    out["srt"] = srt_align(ew, asr["c_belgesel"]["words"], srt_cues(FAZ / "ema_c.srt"))
    (HERE / "m6_analiz.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    for n, v in out["wer_cer"].items():
        print(n, "WER", v["wer"], "CER", v["cer"], "n", v["n_ref_words"], v["farklar"])
    print("SAYI_b", out["sayi_kontrolu_b"])
    print("SRT", {k: v for k, v in out["srt"].items() if k != "kipler"})
    print("KISA_KIPLER", [(r["text"], r["dur"]) for r in out["srt"]["kipler"] if r["dur"] < 1.0])
    print("C_HYP", hc)


if __name__ == "__main__":
    main()
