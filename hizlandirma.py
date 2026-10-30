"""Ekran kartı (GPU) hızlandırma: donanım algılama + doğru PyTorch derlemesini kurma.

Neden ayrı bir kurulum gerekiyor? PyTorch'un CPU, CUDA (NVIDIA) ve ROCm (AMD)
derlemeleri ayrı pip paketleridir; kurulu tek bir torch bunlardan yalnız birini
destekler. Bu yüzden "ayarı değiştir" ile çalışma anında backend değişmez: doğru
derleme kurulur ve SesVer yeniden başlatılır.

Model cihazı VoxCPM'in kendi seçimidir (CUDA → Apple MPS → CPU); ROCm derlemeleri
de ``torch.cuda`` arayüzünü kullandığından AMD (Linux) kartlar aynı yoldan çalışır.

Desteklenen kurulum yolları (2026-10 itibarıyla doğrulandı):
  * NVIDIA, Windows/Linux x86-64: download.pytorch.org/whl/cu130 (sürücü >= 580,
    compute capability >= 7.5) veya cu126 (sürücü >= 525, daha eski kartlar).
  * NVIDIA Blackwell (RTX 50 serisi, compute capability >= 12.0 ya da sürücüde
    compute_cap alanı yoksa kart adı "RTX 50xx"): cu126'da bu mimari için çekirdek
    YOK ("no kernel image is available"). cu128 CUDA 12.8 GA'dan beri gerekli en
    düşük sürücü Linux >=570.26 / Windows >=570.65'tir (NVIDIA CUDA 12.8 Release
    Notes, Table 3: https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/ ;
    cu128 cp311 win_amd64 tekerlekleri doğrulandı: https://download.pytorch.org/whl/cu128/torch/ ,
    ör. torch-2.9.1+cu128-cp311-cp311-win_amd64.whl). Bu yüzden Blackwell için:
    sürücü >= 580 → cu130, sürücü 570-579 → cu128, sürücü < 570 → DRIVER_OLD
    (genel kartların 525 alt sınırından farklı: Blackwell çekirdekleri cu126'da
    hiç yok, 525-569 sürücüyle de çalışan bir etiket kurulamaz).
  * AMD, Linux x86-64: download.pytorch.org/whl/rocm7.2.
Desteklenmeyen (algılanır ve nedeni açıklanır):
  * AMD, Windows: torch-directml en son torch 2.4.1'e bağlı (VoxCPM2 >= 2.5 ister,
    ayrıca DirectML cihazını kabul etmez); AMD'nin resmi Windows PyTorch'u yalnız
    Python 3.12 ve belirli kartlar için var (SesVer Python 3.11 kullanır).

Bu modül yalnız standart kütüphaneyi kullanır ve torch'u bu süreçte İÇE AKTARMAZ:
Windows'ta yüklü torch DLL'leri kilitlenir ve pip onların üzerine yazamaz. Torch
bilgisi ayrı bir Python sürecinde okunur.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

NVIDIA, AMD, INTEL, APPLE, OTHER = "nvidia", "amd", "intel", "apple", "other"
INDEX = "https://download.pytorch.org/whl/{tag}"
PYPI = "https://pypi.org/simple"
CUDA_NEW, CUDA_OLD, CUDA_BLACKWELL, ROCM, CPU = "cu130", "cu126", "cu128", "rocm7.2", "cpu"
MIN_TORCH = (2, 5, 0)  # voxcpm 2.0.3: torch>=2.5.0

# Planın durum kodları (arayüz metni app.py'de, i18n ile)
MAC, ACTIVE, INSTALL, DRIVER_OLD, NO_DRIVER, AMD_WINDOWS, NO_GPU, PLATFORM, BROKEN = (
    "mac", "aktif", "kur", "surucu_eski", "surucu_yok", "amd_windows", "gpu_yok", "platform",
    "calismiyor")

# Hedef → (yaklaşık indirme GB, gereken boş disk GB). 2026-10 ölçümü (cp311, torch 2.14.1):
# cu130 Windows 2,0 GB, cu126 Windows 2,6 GB, cu130 Linux 0,55 GB + PyPI'den nvidia-*
# kütüphaneleri (~2,5 GB), rocm7.2 Linux 6,2 GB, cpu Windows 0,12 GB.
SIZES = {"cuda": (3, 8), "rocm": (7, 20), "cpu": (1, 3)}


def _no_window():
    """Windows'ta konsolsuz (pythonw) modda alt süreç siyah pencere açmasın."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def run(cmd, timeout=15):
    """Komutu çalıştırır; başarılıysa stdout, değilse (yok/hata/zaman aşımı) None."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                             encoding="utf-8", errors="replace", **_no_window())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return res.stdout if res.returncode == 0 else None


# --- Ayrıştırıcılar (birim testlerde sahte çıktıyla sınanır) ---------------------


def vendor_of(name):
    n = f" {(name or '').lower()} "
    if any(k in n for k in ("nvidia", "geforce", "quadro", "tesla")):
        return NVIDIA
    if any(k in n for k in (" amd", "radeon", " ati ", "advanced micro devices")):
        return AMD
    if "intel" in n:
        return INTEL
    return OTHER


def _num(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_nvidia_smi(out):
    """``nvidia-smi --query-gpu=name,driver_version[,compute_cap] --format=csv,noheader``"""
    gpus = []
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if not parts[0] or parts[0].lower().startswith(("name", "no devices", "nvidia-smi has failed")):
            continue
        gpus.append({
            "vendor": NVIDIA, "name": parts[0],
            "driver": parts[1] if len(parts) > 1 and parts[1] else None,
            "compute_cap": _num(parts[2]) if len(parts) > 2 else None,
        })
    return gpus


def parse_windows_names(out):
    """PowerShell (Win32_VideoController.Name) veya ``wmic ... get name`` çıktısı."""
    names = []
    for line in (out or "").splitlines():
        line = line.strip()
        if line and line.lower() != "name" and line not in names:
            names.append(line)
    return names


_LSPCI_CLASS = re.compile(r"(VGA compatible controller|3D controller|Display controller)", re.I)
_LSPCI_IDS = re.compile(r"\[([0-9a-f]{4}):([0-9a-f]{4})\]", re.I)
_VENDOR_IDS = {"10de": NVIDIA, "1002": AMD, "1022": AMD, "8086": INTEL}


def parse_lspci(out):
    """``lspci -nn`` satırları: ``03:00.0 VGA compatible controller [0300]: Advanced Micro
    Devices, Inc. [AMD/ATI] Navi 31 [Radeon RX 7900 XTX] [1002:744c] (rev c8)``"""
    gpus = []
    for line in (out or "").splitlines():
        if not _LSPCI_CLASS.search(line):
            continue
        ids = _LSPCI_IDS.findall(line)
        desc = line.split(": ", 1)[1] if ": " in line else line
        desc = re.sub(r"\s*\[[0-9a-f]{4}:[0-9a-f]{4}\].*$", "", desc, flags=re.I).strip()
        vendor = _VENDOR_IDS.get(ids[-1][0].lower()) if ids else None
        gpus.append({"vendor": vendor or vendor_of(desc), "name": desc, "driver": None,
                     "compute_cap": None})
    return gpus


def sysfs_gpus(root="/sys/class/drm"):
    """lspci yoksa: /sys/class/drm/card*/device/vendor (ör. 0x1002 = AMD)."""
    gpus, seen = [], set()
    for vendor_file in sorted(Path(root).glob("card*/device/vendor")):
        try:
            vid = vendor_file.read_text().strip().lower().removeprefix("0x")
            dev = vendor_file.parent.resolve()
        except OSError:
            continue
        if dev in seen or vid not in _VENDOR_IDS:
            continue
        seen.add(dev)
        vendor = _VENDOR_IDS[vid]
        gpus.append({"vendor": vendor, "name": {NVIDIA: "NVIDIA GPU", AMD: "AMD Radeon GPU",
                                                 INTEL: "Intel GPU"}[vendor],
                     "driver": None, "compute_cap": None})
    return gpus


def _driver_major(driver):
    m = re.match(r"\s*(\d+)", driver or "")
    return int(m.group(1)) if m else None


_RTX_50_RE = re.compile(r"\brtx\s*50\d\d\b", re.I)


def is_blackwell(gpu):
    """Blackwell (RTX 50 serisi, sm_120+): cc biliniyorsa cc >= 12.0; bilinmiyorsa

    (ör. eski nvidia-smi ``compute_cap`` alanını desteklemiyor) kart adından
    "RTX 50xx" deseni aranır. cu126'da bu mimari için derlenmiş çekirdek yok;
    cu128/cu130 gerekir (bkz. modül başındaki not + kaynak linkler)."""
    cc = (gpu or {}).get("compute_cap")
    if cc is not None:
        return cc >= 12.0
    return bool(_RTX_50_RE.search((gpu or {}).get("name") or ""))


# --- Algılama --------------------------------------------------------------------


def _nvidia(runner, which):
    if not which("nvidia-smi"):
        return None  # sürücü kurulu değil (ya da NVIDIA kart yok)
    base = ["nvidia-smi", "--format=csv,noheader", "--query-gpu=name,driver_version"]
    out = runner(base[:2] + [base[2] + ",compute_cap"])
    if out is None:  # eski nvidia-smi compute_cap alanını tanımaz
        out = runner(base)
    return parse_nvidia_smi(out)


def detect(system=None, machine=None, runner=run, which=shutil.which, sysfs_root="/sys/class/drm"):
    """Ekran kartlarını bulur. Dönen sözlük: system, machine, gpus[], nvidia_smi (bool)."""
    system = system or platform.system()
    machine = (machine or platform.machine() or "").lower()
    hw = {"system": system, "machine": machine, "gpus": [], "nvidia_smi": False}
    if system == "Darwin":
        # Apple Silicon'da VoxCPM MPS'i kendisi kullanır; macOS'ta CUDA/ROCm yoktur.
        if machine in ("arm64", "aarch64"):
            hw["gpus"].append({"vendor": APPLE, "name": "Apple Silicon (Metal/MPS)",
                               "driver": None, "compute_cap": None})
        return hw
    nvidia = _nvidia(runner, which)
    if nvidia is not None:
        hw["nvidia_smi"] = True
        hw["gpus"] += nvidia
    others = []
    if system == "Windows":
        out = runner(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                      "Get-CimInstance Win32_VideoController | "
                      "ForEach-Object { $_.Name }"], timeout=30)
        if out is None:  # PowerShell yoksa: wmic (Windows 11'de kaldırılıyor)
            out = runner(["wmic", "path", "win32_VideoController", "get", "name"])
        others = [{"vendor": vendor_of(n), "name": n, "driver": None, "compute_cap": None}
                  for n in parse_windows_names(out)]
    elif system == "Linux":
        out = runner(["lspci", "-nn"])
        others = parse_lspci(out) if out is not None else sysfs_gpus(sysfs_root)
    for gpu in others:
        # NVIDIA kartlar nvidia-smi'den (sürücü sürümüyle) zaten geldiyse tekrarlanmaz.
        if gpu["vendor"] == NVIDIA and hw["nvidia_smi"]:
            continue
        if gpu["vendor"] in (NVIDIA, AMD, INTEL):
            hw["gpus"].append(gpu)
    return hw


# --- Kurulu PyTorch ---------------------------------------------------------------

_PROBE = r"""
import json
try:
    import torch
except Exception as e:
    print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
    raise SystemExit(0)
info = {"version": torch.__version__, "cuda": torch.version.cuda,
        "hip": getattr(torch.version, "hip", None), "cuda_ok": False, "mps_ok": False,
        "cuda_kernel_ok": False, "device_name": None}
try:
    info["cuda_ok"] = bool(torch.cuda.is_available())
    if info["cuda_ok"]:
        info["device_name"] = torch.cuda.get_device_name(0)
        info["vram_total"] = int(torch.cuda.get_device_properties(0).total_memory)  # hata raporu için
        # torch.cuda.is_available() yalnız sürücü+bağlamı denetler; derlemede bu kartın
        # mimarisi (ör. Blackwell sm_120) için çekirdek yoksa yine True döner ve asıl
        # hata ilk gerçek işlemde ("no kernel image is available") patlar. Bu yüzden
        # "kuruldu" demeden önce küçük bir gerçek işlem çalıştırılır.
        x = torch.ones(8, device="cuda") * 2
        torch.cuda.synchronize()
        y = torch.matmul(torch.randn(64, 64, device="cuda"), torch.randn(64, 64, device="cuda"))
        torch.cuda.synchronize()
        info["cuda_kernel_ok"] = bool(torch.all(x == 2).item()) and tuple(y.shape) == (64, 64)
except Exception as e:
    info["cuda_kernel_error"] = f"{type(e).__name__}: {e}"
try:
    info["mps_ok"] = bool(torch.backends.mps.is_available())
except Exception:
    pass
print(json.dumps(info))
"""


def probe_torch(python=None, runner=run):
    """Kurulu torch'un derlemesini AYRI bir süreçte okur (bu süreç torch'u kilitlemez)."""
    out = runner([python or sys.executable, "-c", _PROBE], timeout=180)
    if not out:
        return None
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def build_of(info):
    """Kurulu torch'un derlemesi: cuda / rocm / cpu (None: torch okunamadı)."""
    if not info or info.get("error"):
        return None
    if info.get("hip"):
        return "rocm"
    if info.get("cuda"):
        return "cuda"
    return "cpu"


def active_backend(info):
    """Modelin bu derlemeyle kullanacağı cihaz (VoxCPM sırası: CUDA → MPS → CPU).

    ``cuda_ok`` (``torch.cuda.is_available()``) yalnız sürücü/bağlamı denetler;
    derlemede kartın mimarisi için çekirdek yoksa (ör. Blackwell sm_120 + cu126)
    yine True döner. ``cuda_kernel_ok`` (gerçek bir işlemle doğrulanır, bkz.
    ``_PROBE``) eksikse (eski kayıt/testler) geriye dönük uyumluluk için True
    varsayılır; False ise derleme kurulu kabul edilir ama BROKEN'a düşülür.
    """
    build = build_of(info)
    if build is None:
        return None
    if info.get("cuda_ok") and info.get("cuda_kernel_ok", True):
        return "rocm" if build == "rocm" else "cuda"
    if info.get("mps_ok"):
        return "mps"
    return "cpu"


def _x86(machine):
    return machine in ("x86_64", "amd64")


def plan(hw, info):
    """Ne yapılabileceği: {"durum", "hedef" (cuda/rocm/None), "etiket" (cu130…), "gpu"}."""
    def out(durum, hedef=None, etiket=None, gpu=None, min_surucu=None):
        return {"durum": durum, "hedef": hedef, "etiket": etiket,
                "gpu": gpu["name"] if gpu else None, "surucu": (gpu or {}).get("driver"),
                "min_surucu": min_surucu}

    if hw["system"] == "Darwin":
        return out(MAC, gpu=hw["gpus"][0] if hw["gpus"] else None)
    nvidia = [g for g in hw["gpus"] if g["vendor"] == NVIDIA]
    amd = [g for g in hw["gpus"] if g["vendor"] == AMD]
    active = active_backend(info)
    if active in ("cuda", "rocm"):
        gpu = (nvidia or amd or [None])[0]
        if info.get("device_name"):
            gpu = {"name": info["device_name"]}
        return out(ACTIVE, hedef=active, gpu=gpu)
    if build_of(info) in ("cuda", "rocm"):
        # Hızlandırmalı derleme kurulu ama kart kullanılamıyor (sürücü uyumsuz/eksik):
        # yeniden kurmayı önermek döngüye sokar; sürücü güncellemesi veya CPU'ya dönüş önerilir.
        return out(BROKEN, hedef=build_of(info), gpu=(nvidia or amd or [None])[0])
    if nvidia:
        gpu = nvidia[0]
        if not _x86(hw["machine"]):
            return out(PLATFORM, gpu=gpu)
        if not hw["nvidia_smi"]:
            return out(NO_DRIVER, gpu=gpu)
        major = _driver_major(gpu["driver"])
        if major is None or major < 525:
            return out(DRIVER_OLD, gpu=gpu, min_surucu=525)
        if is_blackwell(gpu):
            # cu126'da bu mimari icin cekirdek yok (bkz. modul basi notu); cu128'in
            # gerektirdigi en dusuk surucu 570'tir (CUDA 12.8 GA), genel 525 degil.
            if major < 570:
                return out(DRIVER_OLD, gpu=gpu, min_surucu=570)
            tag = CUDA_NEW if major >= 580 else CUDA_BLACKWELL
            return out(INSTALL, "cuda", tag, gpu)
        cc = gpu["compute_cap"]
        new = major >= 580 and (cc is None or cc >= 7.5)
        return out(INSTALL, "cuda", CUDA_NEW if new else CUDA_OLD, gpu)
    if amd:
        gpu = amd[0]
        if hw["system"] == "Windows":
            return out(AMD_WINDOWS, gpu=gpu)
        if hw["system"] != "Linux" or not _x86(hw["machine"]):
            return out(PLATFORM, gpu=gpu)
        return out(INSTALL, "rocm", ROCM, gpu)
    return out(NO_GPU)


# --- Kurulum ----------------------------------------------------------------------


def _vkey(version):
    return tuple(int(x) for x in re.findall(r"\d+", version.split("+")[0])[:3])


def wheel_versions(listing, package, tag, cp=None, plat=None):
    """İndeks sayfasındaki ``torch-2.14.1+cu130-cp311-cp311-win_amd64.whl`` adlarından,
    bu Python/platforma uyan sürümler (yerel etiketsiz), küçükten büyüğe."""
    cp = cp or f"cp{sys.version_info[0]}{sys.version_info[1]}"
    plat = plat or (r"win_amd64" if os.name == "nt" else r"manylinux[0-9_]*x86_64")
    pat = re.compile(rf"{re.escape(package)}-([0-9][0-9.]*)(?:\+|%2B){re.escape(tag)}-{cp}-{cp}-{plat}\.whl",
                     re.I)
    return sorted({m.group(1) for m in pat.finditer(listing or "")}, key=_vkey)


def pick_version(available, current):
    """Kurulu sürüm (torchcodec gibi derlenmiş eklerle uyum için) varsa o; yoksa en yenisi."""
    base = (current or "").split("+")[0]
    if base in available:
        return base
    ok = [v for v in available if _vkey(v) >= MIN_TORCH] if available else []
    return ok[-1] if ok else None


def fetch_listing(tag, package, timeout=30):
    with urllib.request.urlopen(f"{INDEX.format(tag=tag)}/{package}/", timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def resolve(tag, installed, fetch=fetch_listing):
    """Kurulacak (torch, torchaudio) sürümleri; uygun torch yoksa None.

    torchaudio artık torch'tan ayrı sürümlenir (ör. torch 2.14.1 + torchaudio 2.11.0):
    yalnız kurulu sürümün aynı derlemesi indekste varsa değiştirilir, yoksa dokunulmaz.
    Ağ hatası (OSError) çağırana bırakılır.
    """
    torch_v = pick_version(wheel_versions(fetch(tag, "torch"), "torch", tag), installed.get("torch"))
    if not torch_v:
        return None
    current_audio = (installed.get("torchaudio") or "").split("+")[0]
    audio_v = None
    if current_audio:
        try:
            if current_audio in wheel_versions(fetch(tag, "torchaudio"), "torchaudio", tag):
                audio_v = current_audio
        except OSError:
            pass
    return torch_v, audio_v


def installed_versions(python=None, runner=run):
    """pip'in gördüğü paket sürümleri ({"torch": "2.14.1", "pip": "26.2.1", ...})."""
    out = runner([python or sys.executable, "-m", "pip", "list", "--format=json",
                  "--disable-pip-version-check"], timeout=60)
    try:
        return {p["name"].lower(): p["version"] for p in json.loads(out or "[]")}
    except (ValueError, TypeError, KeyError):
        return {}


def install_command(tag, torch_version, audio_version, python=None, pip_version=None):
    """Tam yerel etiketle sabitlenir (``torch==2.14.1+cu130``): kurulu ``2.14.1`` (CPU)
    bu koşulu karşılamadığı için pip yalnız torch'u (ve torchaudio'yu) yeniden kurar."""
    pkgs = [f"torch=={torch_version}+{tag}"]
    if audio_version:
        pkgs.append(f"torchaudio=={audio_version}+{tag}")
    cmd = [python or sys.executable, "-m", "pip", "install", *pkgs,
           "--index-url", INDEX.format(tag=tag), "--extra-index-url", PYPI,
           "--no-cache-dir", "--no-warn-script-location", "--disable-pip-version-check"]
    if pip_version and _vkey(pip_version) >= (24, 1, 0):
        cmd += ["--progress-bar", "raw"]  # boru üzerinden de "Progress X of Y" satırları
    return cmd


_PROGRESS = re.compile(r"^Progress (\d+) of (\d+)")


def parse_progress(line):
    """pip ``--progress-bar raw`` satırı → (indirilen bayt, toplam bayt) ya da None."""
    m = _PROGRESS.match(line.strip())
    return (int(m.group(1)), int(m.group(2))) if m and int(m.group(2)) > 0 else None


def free_gb(path=None):
    try:
        return shutil.disk_usage(path or sys.prefix).free / 1024 ** 3
    except OSError:
        return None


def windows_files_locked():
    """Windows'ta bu süreçte torch yüklüyse DLL'leri kilitli: pip üzerine yazamaz."""
    return os.name == "nt" and "torch" in sys.modules


def pip_env():
    env = dict(os.environ)
    env.update(PYTHONUNBUFFERED="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONIOENCODING="utf-8")
    return env


def start_install(cmd):
    """pip'i başlatır; çıktısı satır satır okunur (ilerleme günlüğü)."""
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", bufsize=1, env=pip_env(),
                            **_no_window())


# --- Başlatıcı (WINDOWS_BASLAT.bat / MACOS_BASLAT.command) için CLI --------------------
#
# Başlatıcılar torch'u kendi süreçlerinde İÇE AKTARAMAZ (bkz. modül başı not) ve ayrı bir
# batch/shell dilinde bu modülün plan() mantığını tekrarlamamalı: tek doğru seçim burada,
# başlatıcı yalnız bu CLI'nin çıktısını kullanır.


def recommended_tag(hw, info):
    """Başlatıcının ilk kurulumda/GPU düzeltmede kuracağı pip index etiketi (``cu130`` …).

    Yalnız ``plan()`` INSTALL derse bir etiket döner (NVIDIA/AMD algılandı, sürücü yeterli).
    Diğer durumlarda (GPU yok, sürücü çok eski, zaten etkin, zaten BROKEN, desteklenmeyen
    platform) None döner: başlatıcı hiçbir şey kurmaz, requirements.txt'nin sade
    ``torch>=2.5.0``'ı PyPI'den CPU derlemesini kurar.
    """
    p = plan(hw, info)
    return p["etiket"] if p["durum"] == INSTALL else None


def _cli(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--onerilen-etiket" in argv:
        # İlk kurulumda henüz torch yok: probe_torch() None döner, plan() bunu bekler.
        print(recommended_tag(detect(), probe_torch()) or "")
        return 0
    if "--cuda-dogrula" in argv:
        # torch.cuda.is_available() yetmez (bkz. _PROBE); gerçek çekirdek testi burada.
        info = probe_torch()
        ok = bool(info and info.get("cuda_kernel_ok"))
        print("tamam" if ok else "basarisiz")
        return 0 if ok else 1
    print("Kullanım: hizlandirma.py --onerilen-etiket | --cuda-dogrula", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli())
