"""M1-1: EMA kurulumu kendi ema_install() fonksiyonuyla; süre, inen bayt, ema_status()."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engines.ema import ema_install, ema_status  # noqa: E402

OUT = Path(__file__).resolve().parent
events = []
t0 = time.perf_counter()


def cb(p):
    events.append({"t": round(time.perf_counter() - t0, 3), **p.as_dict()})
    if p.stage != "indirme" or p.done_bytes == p.total_bytes:
        print(f"[{events[-1]['t']:7.2f}s] {p.stage:10s} {p.fraction:4.0%} {p.message}", flush=True)


before = ema_status().as_dict()
print("ONCE:", json.dumps({k: before[k] for k in ("ready", "package_installed", "weights_present",
                                                   "download_label", "missing_dependencies")}, ensure_ascii=False))
t0 = time.perf_counter()
st = ema_install(cb, timeout=60.0)
elapsed = time.perf_counter() - t0
after_fast = ema_status().as_dict()
t1 = time.perf_counter()
after_verify = ema_status(verify=True).as_dict()
verify_s = time.perf_counter() - t1
t2 = time.perf_counter()
again = ema_install(None).as_dict()   # ikinci çağrı: ağa çıkmadan dönmeli
again_s = time.perf_counter() - t2
res = {"install_s": round(elapsed, 2), "verify_s": round(verify_s, 2), "second_install_s": round(again_s, 2),
       # done_bytes dosyalar boyunca BİRİKİMLİ ilerler; doğru toplam = son indirme olayındaki değer.
       # (İlk koşuda dosya başı maksimumlar toplanmıştı → m1_kurulum.json'da 56676051 yazıyor; gerçek 34389489.)
       "weights_downloaded_bytes": max((e["done_bytes"] for e in events if e["stage"] == "indirme"), default=0),
       "status_before": before, "status_after": after_fast, "status_after_verify": after_verify,
       "status_second_install": again, "events": events}
(OUT / "m1_kurulum.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), "utf-8")
print("SURE", res["install_s"], "s; indirilen ağırlık", res["weights_downloaded_bytes"], "B; verify", res["verify_s"],
      "s; ikinci", res["second_install_s"], "s")
print("SONRA:", json.dumps({k: after_verify[k] for k in ("ready", "package_version", "normalizer_version",
                                                          "weights_present", "verified", "weights_label",
                                                          "download_label", "weights_dir")}, ensure_ascii=False))
