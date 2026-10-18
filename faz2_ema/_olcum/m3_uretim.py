"""M1-3/5/6: EMA üretimleri (a, b, c, seed, hız). WAV'lar _olcum/wav/, ölçüm m3_uretim.json.

Kullanım: python m3_uretim.py            -> tüm üretimler
          python m3_uretim.py --tekrar   -> yeni süreçte seed=1 a) tekrar (süreçler arası belirlenimcilik)
"""
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from engines.ema import EmaEngine  # noqa: E402

WAV = HERE / "wav"
WAV.mkdir(exist_ok=True)

A = "Merhaba, bugün yapay zekânın ses üretiminde neler yapabildiğini deneyeceğiz."
B = "1453'te İstanbul'un fethi, 29 Mayıs günü sabah saat 6'da başladı. TBMM 23 Nisan 1920'de açıldı."
# Titanik brief'i, seslendirme bölümü 1–14 (tamamı); brief'in kuralı gereği yabancı adlar fonetik (TTS girdisi).
C = ("Titanik'in batması iki saat kırk dakika sürdü. İşte o gece, saat saat. "
     "Yirmi üç kırk. Gözcü bağırıyor: tam önümüzde buzdağı! Gemi sağ yanından sürtünerek çarpıyor. "
     "Gece yarısı. Geminin tasarımcısı Tamıs Endruz hesabı yapıyor: gemi batacak. Bir, bilemedin bir buçuk saat. "
     "Sıfır sıfır on beş. Telsizden ilk imdat çağrısı gidiyor. "
     "Ama yakındaki Kaliforniyın gemisinin telsizcisi, çarpışmadan on dakika önce cihazını kapatıp yatmış. "
     "Sıfır sıfır yirmi beş. Yüz yedi kilometre ötedeki Karpeyşa çağrıyı alıyor ve rotasını Titanik'e çeviriyor. "
     "Sıfır sıfır kırk beş. İlk filika suya iniyor. Altmış beş kişilik, ama içinde sadece yirmi sekiz kişi var. "
     "Aynı dakikalarda ilk işaret fişeği atılıyor. Ufukta bir geminin ışığı görünüyor, ama cevap gelmiyor. "
     "Gemide iki bin iki yüzden fazla insan var. Filikalar ise yalnızca bin yüz yetmiş sekiz kişi alabiliyor. "
     "İki on sekiz. Işıklar sönüyor. "
     "İki yirmi. Titanik kayboluyor. Bin beş yüzden fazla insan, eksi iki derecelik suyun içinde. "
     "Dört on. Karpeyşa ilk filikaya ulaşıyor. "
     "O gece tek bir hata yoktu. Bir hatalar zinciri vardı. "
     "Sence bu zincirin en kritik halkası hangisiydi?")
C2 = "Titanik'in batması iki saat kırk dakika sürdü. İşte o gece, saat saat."
SEED = 1


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(eng, name, text, seed=SEED, speed=1.0):
    t = time.perf_counter()
    r = eng.synthesize(text, seed=seed, speed=speed)
    gen = time.perf_counter() - t
    dst = WAV / f"{name}.wav"
    shutil.move(r.path, dst)
    if r.meta.get("srt_path"):
        shutil.move(r.meta["srt_path"], dst.with_suffix(".srt"))
    dur = r.meta["duration"]
    rec = {"name": name, "text": text, "seed": r.meta["seed"], "speed": speed, "gen_s": round(gen, 3),
           "dur_s": dur, "rtf_ses_bolu_uretim": round(dur / gen, 1), "sr": r.sample_rate,
           "chars": len(text), "n_words": len(r.meta["words"]), "sha256": sha(dst)}
    (WAV / f"{name}.words.json").write_text(json.dumps(r.meta["words"], ensure_ascii=False, indent=0), "utf-8")
    print(json.dumps({k: v for k, v in rec.items() if k != "text"}, ensure_ascii=False))
    return rec


def main():
    eng = EmaEngine(output_dir=WAV / "_tmp")
    if "--tekrar" in sys.argv:
        recs = [run(eng, "seed1_surec2", A, seed=1)]
        (HERE / "m3_tekrar.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), "utf-8")
        return
    t = time.perf_counter()
    eng._get_model()
    w = eng.synthesize("Isınma.", seed=0)
    Path(w.path).unlink()
    Path(w.path).with_suffix(".srt").unlink(missing_ok=True)
    print("yükleme+ısınma s", round(time.perf_counter() - t, 2))
    recs = [run(eng, "a", A), run(eng, "b_sayilar", B), run(eng, "c_belgesel", C)]
    recs += [run(eng, "seed1", A, seed=1), run(eng, "seed1_tekrar", A, seed=1),
             run(eng, "seed2", A, seed=2), run(eng, "seed3", A, seed=3)]
    recs += [run(eng, f"hiz_{s}", C2, speed=s) for s in (0.9, 1.0, 1.15)]
    (HERE / "m3_uretim.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), "utf-8")
    shutil.rmtree(WAV / "_tmp", ignore_errors=True)


if __name__ == "__main__":
    main()
