"""M1-2: soğuk başlatma — ayrı süreçte import + SHA doğrulama + model yükleme süresi ve RAM tepe değeri."""
import json
import resource
import sys
import time
from pathlib import Path

T0 = time.perf_counter()
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def rss_mb():
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1)  # macOS: bayt


r = {"rss_basla_mb": rss_mb()}
t = time.perf_counter()
import torch  # noqa: E402,F401
r["import_torch_s"] = round(time.perf_counter() - t, 2)
r["rss_torch_sonrasi_mb"] = rss_mb()
from engines.ema import EmaEngine  # noqa: E402

eng = EmaEngine(output_dir=Path(__file__).resolve().parent / "wav")
t = time.perf_counter()
eng.status(verify=True)
r["sha_dogrulama_s"] = round(time.perf_counter() - t, 2)
t = time.perf_counter()
eng._get_model()  # verify=True + default_loader (ağa çıkmaz)
r["model_yukleme_s_dogrulama_dahil"] = round(time.perf_counter() - t, 2)
r["rss_model_sonrasi_mb"] = rss_mb()
r["device"] = str(eng._model.device)
t = time.perf_counter()
res = eng.synthesize("Merhaba.", seed=0)
r["ilk_kisa_uretim_s"] = round(time.perf_counter() - t, 2)
r["rss_ilk_uretim_sonrasi_mb"] = rss_mb()
r["toplam_soguk_baslangic_ilk_sese_s"] = round(time.perf_counter() - T0, 2)
r["torch_threads"] = torch.get_num_threads()
Path(res.path).unlink(missing_ok=True)
Path(res.path).with_suffix(".srt").unlink(missing_ok=True)
(Path(__file__).resolve().parent / "m2_soguk.json").write_text(json.dumps(r, indent=1), "utf-8")
print(json.dumps(r, indent=1))
