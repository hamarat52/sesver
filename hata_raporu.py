"""Hata raporu: kullanıcının onayıyla e-postayla (mailto:) gönderilecek teknik rapor.

Gizlilik sözleşmesi (SesVer tamamen yereldir):
  * Hiçbir şey otomatik/sessiz gönderilmez. Rapor önce arayüzde gösterilir; yalnız
    kullanıcı "E-posta uygulamasında aç" derse varsayılan e-posta uygulamasında bir
    TASLAK açılır (gönderen yine kullanıcıdır). Sunucu, SMTP ya da API anahtarı yoktur.
  * Rapora yalnız teknik bilgi girer: sürüm, işletim sistemi, Python/PyTorch/GPU
    bilgisi, boş RAM/disk, arayüz dili, hata türü/mesajı/traceback ve günlüğün son
    satırları. Kullanıcının metni ve sesleri girmez: başarısız üretimin metni
    ``record_error(..., redact=[metin])`` ile kaydedilir ve hem günlüğe yazılan
    traceback'ten hem de rapordan silinir.
  * Ev dizini/kullanıcı adı içeren yollar ``<ev>``, e-posta adresleri ve
    hf_/sk- benzeri anahtarlar maskelenir (``sanitize``).

Yalnız standart kütüphane kullanır ve torch'u içe aktarmaz (torch bu süreçte zaten
yüklüyse ondan okur; değilse hizlandirma.probe_torch ayrı süreçte okur): desktop.py
başlatma hatası ekranında da (torch/numpy yüklenemese bile) çalışmalıdır.
"""
import collections
import datetime
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import traceback
import urllib.parse
from pathlib import Path

from i18n import get_lang, t

DESTEK_EPOSTA = "premium.hamarat@gmail.com"  # raporların tek alıcısı (yalnız burada tanımlı)
ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "sesver_log.txt"
PREV_LOG_PATH = ROOT / "sesver_log_onceki.txt"
REPORT_DIR = ROOT / "hata_raporlari"
VERSION_FILE = ROOT / ".sesver_payload_version"  # macos/release_mac.sh damgası: "1.2.0 (abc1234)"
MAILTO_LIMIT = 1800  # Windows'ta ShellExecute/varsayılan istemci için güvenli URL uzunluğu
LOG_TAIL_LINES = 300

# --- Maskeleme ------------------------------------------------------------------

HOME_MASK = "<ev>"
_SEP = r"(?:\\\\|\\|/)+"  # \, \\ (repr içinde) ya da /
_HOME_PATTERNS = (
    re.compile(rf"\b[A-Za-z]:{_SEP}(?:Users|Documents and Settings){_SEP}[^\\/\s'\"<>:|*?]+", re.I),
    re.compile(r"(?<![\w.])/Users/[^/\s'\"<>:]+"),
    re.compile(r"(?<![\w.])/home/[^/\s'\"<>:]+"),
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TOKENS = (
    re.compile(r"\bhf_[A-Za-z0-9]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"\bxox[abpors]-[A-Za-z0-9-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
)
_KEY_VALUE = re.compile(
    r"(?i)\b((?:access[_-]?|auth[_-]?)?token|api[_-]?key|secret|password|passwd|authorization)"
    r"(\s*[=:]\s*)(['\"]?)([^\s'\",;]{6,})")
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")


def _home_variants():
    homes = set()
    for value in (os.path.expanduser("~"), os.environ.get("USERPROFILE"), os.environ.get("HOME")):
        if value and len(value) > 3:
            homes.add(value.rstrip("\\/"))
    out = set()
    for h in homes:
        out |= {h, h.replace("\\", "/"), h.replace("\\", "\\\\"), h.replace("/", "\\")}
    return sorted(out, key=len, reverse=True)


def sanitize(text, homes=None):
    """Ev dizini yollarını, e-posta adreslerini ve erişim anahtarlarını maskeler.

    ``homes``: maskelenecek ek ev dizinleri (varsayılan: bu kullanıcının ev dizini);
    Windows ``C:\\Users\\<ad>``, macOS ``/Users/<ad>`` ve Linux ``/home/<ad>`` her zaman
    maskelenir (rapor başka bir makinede oluşmuş olsa da).
    """
    if not text:
        return text or ""
    text = str(text)
    for home in (homes if homes is not None else _home_variants()):
        if home:
            text = re.sub(re.escape(home), HOME_MASK, text, flags=re.I)
    for pattern in _HOME_PATTERNS:
        text = pattern.sub(HOME_MASK, text)
    text = _EMAIL.sub("<e-posta>", text)
    for pattern in _TOKENS:
        text = pattern.sub("<anahtar>", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)}<gizli>", text)
    return _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}<gizli>", text)


# --- Kullanıcı metni (rapora asla girmez) -------------------------------------------

_redact = collections.deque(maxlen=32)  # yalnız bellekte; başarısız üretimlerin metin parçaları
_lock = threading.Lock()
_errors = []  # bu oturumda kaydedilen son hatalar (en çok 5)
_error_count = 0  # arayüz: "bu üretim sırasında yeni hata oldu mu?"
_MIN_FRAGMENT = 6


def _fragments(value):
    """Metnin kendisi ve rapora parça parça sızabilecek alt parçaları (satır/cümle)."""
    value = str(value or "").strip()
    if len(value) < 3:
        return []
    parts = {value, repr(value)[1:-1], value.replace("\n", "\\n")}
    for piece in re.split(r"[\n\r.!?;:…]+", value):
        piece = piece.strip()
        if len(piece) >= _MIN_FRAGMENT:
            parts.add(piece)
    return sorted(parts, key=len, reverse=True)


def remember_private(*values):
    """Bu değerler (ör. üretim metni) bundan sonra günlük çıktısından ve rapordan silinir."""
    with _lock:
        for value in values:
            for piece in _fragments(value):
                if piece not in _redact:
                    _redact.append(piece)


def scrub_private(text, extra=()):
    if not text:
        return text or ""
    with _lock:
        pieces = list(_redact)
    for value in extra:
        pieces += _fragments(value)
    for piece in sorted(set(pieces), key=len, reverse=True):
        text = text.replace(piece, "<metin>")
    return text


# --- Hata sınıflandırma ---------------------------------------------------------------

def _exc_text(exc_or_text):
    if isinstance(exc_or_text, BaseException):
        names, seen, cur = [], set(), exc_or_text
        while cur is not None and id(cur) not in seen:  # zincir: raise ... from / bağlam
            seen.add(id(cur))
            names.append(f"{type(cur).__name__}: {cur}")
            names += [c.__name__ for c in type(cur).__mro__]
            cur = cur.__cause__ or cur.__context__
        return "\n".join(names)
    return str(exc_or_text or "")


# "_ArrayMemoryError" (numpy) gibi alt çizgiyle başlayan özel sınıf adları da tür sayılır.
_EXC_NAME = r"_*[A-Z][A-Za-z0-9_]*(?:Error|Exception|Exit|Interrupt)"
_LEADING_EXC = re.compile(rf"\s*(?:[A-Za-z_]\w*\.)*({_EXC_NAME})\s*(?::|$)")  # "numpy.x._ArrayMemoryError:"


def _class_name(exc_or_text):
    if isinstance(exc_or_text, BaseException):
        return type(exc_or_text).__name__
    m = re.search(rf"\b({_EXC_NAME})\b", str(exc_or_text or ""))
    return m.group(1) if m else "Error"


def _strip_kind(kind, message):
    """Mesajın başındaki (modül önekli olabilir) "Tür:" öneklerini — tekrarlansa da — atar;
    yalnız tür adından ibaret mesaj boş döner."""
    pat = re.compile(rf"\s*(?:[A-Za-z_]\w*\.)*{re.escape(kind)}\s*(?::\s*|$)")
    message = str(message or "")
    while message and (m := pat.match(message)):
        message = message[m.end():]
    return message.strip()


def exc_line(exc):
    """Tek satır "Tür: mesaj". Mesaj zaten tür adıyla başlıyorsa (ör. bir kütüphane hatayı
    "MemoryError: ..." metniyle yeniden fırlattıysa) tür ikinci kez eklenmez; boş mesajda yalnız tür."""
    name = type(exc).__name__
    try:
        rest = _strip_kind(name, str(exc))
    except Exception:  # noqa: BLE001 — __str__ hatası başlatma hatasını gizlemesin
        rest = ""
    return f"{name}: {rest}" if rest else name


_NET_MARKERS = (
    "huggingface", "hf_hub", "localentrynotfounderror", "offlinemodeisenabled", "repositorynotfounderror",
    "connectionerror", "connecterror", "max retries exceeded", "getaddrinfo", "name or service not known",
    "nodename nor servname", "temporary failure in name resolution", "name resolution", "sslerror",
    "certificate verify failed", "readtimeout", "connecttimeout", "remotedisconnected", "urlerror",
    "connection reset", "connection refused", "network is unreachable",
)


def classify_error(exc_or_text):
    """(kod, kullanıcıya gösterilecek kısa neden) — neden arayüz dilindedir.

    Kodlar: cuda_kernel, cuda_oom, gpu_oom, ram, disk, download, other.
    """
    raw = _exc_text(exc_or_text)
    low = raw.casefold()
    if "no kernel image is available" in low or "cudaerrornokernelimagefordevice" in low:
        return "cuda_kernel", t("CUDA çekirdeği bu kartta yok (kurulu PyTorch bu ekran kartını desteklemiyor)")
    if ("outofmemoryerror" in low and ("cuda" in low or "hip" in low)) or "cuda out of memory" in low \
            or "cuda error: out of memory" in low or "hip out of memory" in low \
            or "cublas_status_alloc_failed" in low:
        return "cuda_oom", t("CUDA bellek yetersiz (ekran kartı belleği doldu)")
    if "mps backend out of memory" in low or "outofmemoryerror" in low:
        return "gpu_oom", t("ekran kartı belleği yetersiz")
    if "memoryerror" in low or "defaultcpuallocator" in low or "bad_alloc" in low \
            or "not enough memory" in low or "alloc_cpu" in low or "cannot allocate memory" in low:
        return "ram", t("bellek (RAM) yetersiz")
    if "no space left on device" in low or "errno 28" in low or "not enough space on the disk" in low:
        return "disk", t("disk alanı yetersiz")
    if any(m in low for m in _NET_MARKERS):
        return "download", t("model indirilemedi (internet bağlantısını kontrol edin)")
    return "other", _class_name(exc_or_text)


# --- Hata kaydı ------------------------------------------------------------------------

def record_error(exc, redact=(), where="generate"):
    """Yakalanan hatayı rapor için saklar ve günlüğe (stderr) yazar.

    ``redact``: kullanıcının metni gibi rapora/günlüğe girmemesi gereken değerler;
    traceback ve mesajdan ``<metin>`` olarak silinir (traceback.print_exc yerine).
    Dönen sözlük: kod, neden, tür, mesaj, traceback, zaman.
    """
    global _error_count
    remember_private(*[v for v in redact if v])
    tb = scrub_private("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    code, reason = classify_error(exc)
    entry = {
        "where": where, "code": code, "reason": reason, "type": type(exc).__name__,
        "message": scrub_private(str(exc)), "traceback": tb,
        "time": datetime.datetime.now().astimezone(),
    }
    try:
        print(tb, end="" if tb.endswith("\n") else "\n", file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 — günlük yazılamasa da hata kaydı kalsın
        pass
    with _lock:
        _errors.append(entry)
        del _errors[:-5]
        _error_count += 1
    return entry


def record_text_error(message, tb="", where="startup"):
    """Yalnız metni bilinen bir hata (ör. desktop.py başlatma hatası); günlüğe yazmaz."""
    global _error_count
    last_lines = "\n".join((tb or "").strip().splitlines()[-3:])  # çerçeve yolları sınıflandırmayı yanıltmasın
    code, reason = classify_error(f"{message}\n{last_lines}")
    message = str(message or "")
    lead = _LEADING_EXC.match(message)  # tür, varsa mesajın başındaki addır (ortadaki bir ad değil)
    kind = lead.group(1) if lead else _class_name(message)
    # "MemoryError: x" → tür ayrı alanda, mesaj "x". Rapor satırı "Tür: mesaj" diye birleştirdiği
    # için önek tekrarlansa ("MemoryError: MemoryError: x") ya da mesaj yalnız türse hepsi atılır.
    message = _strip_kind(kind, message)
    entry = {"where": where, "code": code, "reason": reason, "type": kind,
             "message": scrub_private(message), "traceback": scrub_private(tb or ""),
             "time": datetime.datetime.now().astimezone()}
    with _lock:
        _errors.append(entry)
        del _errors[:-5]
        _error_count += 1
    return entry


def error_count():
    return _error_count


def last_error():
    with _lock:
        return dict(_errors[-1]) if _errors else None


# --- Günlük ---------------------------------------------------------------------------

def rotate_log(log_path=None, prev_path=None):
    """Açılışta: dolu bir sesver_log.txt varsa sesver_log_onceki.txt olarak saklanır
    (tek kopya; bir önceki 'önceki' günlüğün üzerine yazılır). Taşındıysa True."""
    log_path, prev_path = Path(log_path or LOG_PATH), Path(prev_path or PREV_LOG_PATH)
    try:
        if log_path.is_file() and log_path.stat().st_size > 0:
            os.replace(log_path, prev_path)
            return True
    except OSError:
        pass
    return False


_ERROR_MARKERS = re.compile(r"Traceback \(most recent call last\)|\[HATA\]|\bError\b|Exception\b|"
                            r"Üretim başarısız|failed|başarısız", re.I)


def log_has_error(path=None):
    try:
        text = Path(path or PREV_LOG_PATH).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_ERROR_MARKERS.search(text))


def tail_lines(path, n=LOG_TAIL_LINES):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [line.rstrip("\r\n") for line in collections.deque(f, maxlen=n)]
    except OSError:
        return None


# --- Sistem bilgisi -------------------------------------------------------------------

def _run(cmd, timeout=5):
    kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                             errors="replace", **kw)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return res.stdout.strip() if res.returncode == 0 else None


def sesver_version():
    """Yayın damgası (.sesver_payload_version) ya da git (geliştirici kopyası); yoksa 'unknown'."""
    try:
        stamp = VERSION_FILE.read_text(encoding="utf-8").strip()
        if stamp:
            return stamp
    except OSError:
        pass
    if (ROOT / ".git").exists() and shutil.which("git"):
        desc = _run(["git", "-C", str(ROOT), "describe", "--tags", "--always", "--dirty"], timeout=3)
        if desc:
            return f"dev {desc}"
    return "unknown"


def os_info(system=None):
    """(ad, sürüm, açıklama): ("Windows", "10.0.22631", "Windows 11 ...") / ("macOS", "15.1", ...)."""
    system = system or platform.system()
    if system == "Darwin":
        ver = platform.mac_ver()[0] or platform.release()
        return "macOS", ver, f"macOS {ver} (Darwin {platform.release()})"
    if system == "Windows":
        ver = platform.version()
        try:
            build = int(ver.split(".")[2])
        except (IndexError, ValueError):
            build = 0
        name = "Windows 11" if build >= 22000 else f"Windows {platform.release()}"
        edition = ""
        try:
            edition = platform.win32_edition() or ""
        except Exception:  # noqa: BLE001
            pass
        return "Windows", ver, f"{name} {edition} {ver}".replace("  ", " ").strip()
    return system or "unknown", platform.release(), f"{system} {platform.release()} {platform.version()}"


def _gb(n):
    return f"{n / 1024 ** 3:.1f} GB" if n else "n/a"


def memory_info():
    """(toplam, kullanılabilir) bayt; okunamazsa None (yalnız standart kütüphane)."""
    try:
        if os.name == "nt":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):  # noqa: N801 — Win32 adı
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if getattr(ctypes, "windll").kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return st.ullTotalPhys, st.ullAvailPhys
            return None
        if sys.platform == "darwin":
            total = int(_run(["/usr/sbin/sysctl", "-n", "hw.memsize"]) or 0)
            out = _run(["/usr/bin/vm_stat"]) or ""
            page = int((re.search(r"page size of (\d+)", out) or [0, 4096])[1])
            pages = {k.strip(): int(v.strip(" .")) for k, v in re.findall(r"^Pages ([^:]+):\s+(\d+)", out, re.M)}
            avail = (pages.get("free", 0) + pages.get("inactive", 0) + pages.get("speculative", 0)) * page
            return (total or None), (avail or None)
        info = dict(re.findall(r"^(\w+):\s+(\d+)", Path("/proc/meminfo").read_text(), re.M))
        return int(info["MemTotal"]) * 1024, int(info.get("MemAvailable", info.get("MemFree", 0))) * 1024
    except Exception:  # noqa: BLE001 — bilgi yoksa rapor yine oluşur
        return None


def _torch_in_process():
    torch = sys.modules.get("torch")
    if torch is None:
        return None
    info = {"source": "in-process", "version": getattr(torch, "__version__", "?")}
    ver = getattr(torch, "version", None)
    info["cuda"] = getattr(ver, "cuda", None)
    info["hip"] = getattr(ver, "hip", None)
    for key, fn in (("cuda_ok", lambda: bool(torch.cuda.is_available())),
                    ("mps_ok", lambda: bool(torch.backends.mps.is_available()))):
        try:
            info[key] = fn()
        except Exception as exc:  # noqa: BLE001 — bozuk CUDA bağlamında da rapor oluşsun
            info[key] = f"error: {type(exc).__name__}"
    if info.get("cuda_ok") is True:
        try:
            info["device_name"] = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            info["vram_total"] = int(props.total_memory)
            info["capability"] = f"{props.major}.{props.minor}"
        except Exception as exc:  # noqa: BLE001
            info["device_error"] = f"{type(exc).__name__}: {exc}"
        try:
            info["arch_list"] = " ".join(torch.cuda.get_arch_list())
        except Exception:  # noqa: BLE001
            pass
    return info


_probe_cache = {}


def torch_info():
    """torch bu süreçte yüklüyse ondan; değilse ayrı süreçte (pencere açmadan) okunur."""
    info = _torch_in_process()
    if info is not None:
        return info
    if "probe" not in _probe_cache:
        try:
            import hizlandirma as hiz
            _probe_cache["probe"] = hiz.probe_torch(runner=lambda cmd, timeout=60: hiz.run(cmd, timeout=60))
        except Exception:  # noqa: BLE001
            _probe_cache["probe"] = None
    probe = _probe_cache["probe"]
    return dict(probe, source="subprocess") if probe else {"source": "subprocess", "error": "torch unreadable"}


def gpu_info():
    if "detect" not in _probe_cache:
        try:
            import hizlandirma as hiz
            _probe_cache["detect"] = hiz.detect()
        except Exception:  # noqa: BLE001
            _probe_cache["detect"] = None
    return _probe_cache["detect"]


def system_lines():
    """Raporun 'System' bölümü (İngilizce, sabit anahtarlar)."""
    name, ver, desc = os_info()
    lines = [f"SesVer: {sesver_version()}",
             f"OS: {desc}",
             f"Arch: {platform.machine() or '?'}",
             f"Python: {platform.python_implementation()} {sys.version.split()[0]}"]
    tinfo = torch_info()
    if tinfo.get("error"):
        lines.append(f"Torch: {tinfo['error']} ({tinfo['source']})")
    else:
        lines.append(f"Torch: {tinfo.get('version')} ({tinfo['source']})")
        lines.append(f"CUDA: {tinfo.get('cuda') or '-'} | HIP: {tinfo.get('hip') or '-'} | "
                     f"cuda.is_available: {tinfo.get('cuda_ok')} | mps: {tinfo.get('mps_ok')}")
        if tinfo.get("device_name") or tinfo.get("vram_total"):
            extra = f" | cc {tinfo['capability']}" if tinfo.get("capability") else ""
            lines.append(f"GPU (torch): {tinfo.get('device_name') or '?'} | VRAM: {_gb(tinfo.get('vram_total'))}{extra}")
        if tinfo.get("arch_list"):
            lines.append(f"Torch arch list: {tinfo['arch_list']}")
        if tinfo.get("device_error"):
            lines.append(f"GPU error: {tinfo['device_error']}")
    hw = gpu_info()
    if hw is not None:
        gpus = "; ".join(f"{g['name']}" + (f" (driver {g['driver']})" if g.get("driver") else "")
                         + (f" cc {g['compute_cap']}" if g.get("compute_cap") else "") for g in hw["gpus"])
        lines.append(f"GPUs (system): {gpus or 'none'} | nvidia-smi: {'yes' if hw.get('nvidia_smi') else 'no'}")
    mem = memory_info()
    if mem:
        lines.append(f"RAM: {_gb(mem[1])} available / {_gb(mem[0])} total")
    try:
        lines.append(f"Disk free (SesVer folder): {_gb(shutil.disk_usage(ROOT).free)}")
    except OSError:
        pass
    lines.append(f"UI language: {get_lang()}")
    return lines


# --- Rapor -------------------------------------------------------------------------------

def build_report(error=None, include_previous=False, log_path=None, prev_path=None, now=None, system=None):
    """Tam rapor (sözlük). ``error``: record_error sözlüğü; None ise son kaydedilen hata.

    Dönen anahtarlar: text (tam rapor), summary (satırlar), tail (günlük son satırları),
    subject, filename, time.
    """
    log_path = Path(log_path or LOG_PATH)
    prev_path = Path(prev_path or PREV_LOG_PATH)
    now = now or datetime.datetime.now().astimezone()
    error = error if error is not None else last_error()
    sys_lines = system if system is not None else system_lines()
    summary = [f"Report time: {now:%Y-%m-%d %H:%M:%S %z}"] + sys_lines
    if error:
        summary += [f"Error time: {error['time']:%Y-%m-%d %H:%M:%S %z}",
                    f"Error kind: {error['code']} ({error['where']})",
                    f"Error: {error['type']}: {error['message']}"[:600]]
    else:
        summary.append("Error: none recorded in this session (user-initiated report)")
    sections = ["SesVer error report", "=" * 40, *summary]
    if error and error.get("traceback"):
        sections += ["", "--- Traceback ---", error["traceback"].rstrip()]
    tail = tail_lines(log_path)
    sections += ["", f"--- {log_path.name} (last {len(tail)} lines) ---" if tail is not None
                 else f"--- {log_path.name}: not found ---", *(tail or [])]
    tail = tail or []
    if include_previous:
        prev = tail_lines(prev_path)
        if prev is not None:
            sections += ["", f"--- {prev_path.name} (previous session, last {len(prev)} lines) ---", *prev]
    clean = lambda s: sanitize(scrub_private(s))  # noqa: E731
    name, ver, _desc = os_info()
    return {
        "text": clean("\n".join(sections)) + "\n",
        "summary": [clean(s) for s in summary],
        "tail": [clean(s) for s in tail],
        "subject": f"SesVer hata raporu {sesver_version()} ({name} {ver})",
        "filename": f"SesVer-hata-raporu-{now:%Y%m%d-%H%M%S}.txt",
        "time": now,
    }


def _quote(s):
    return urllib.parse.quote(s.replace("\r\n", "\n").replace("\n", "\r\n"), safe="")


def mail_body(report, tail):
    intro = t("Lütfen yanınızda açılan {dosya} dosyasını bu e-postaya ekleyin.", dosya=report["filename"])
    parts = [intro, "", *report["summary"]]
    if tail is not None:
        parts += ["", "--- log (last lines) ---", *tail]
    return "\n".join(parts)


def mailto_url(report, limit=MAILTO_LIMIT):
    """``mailto:`` adresi (URL-kodlanmış toplam uzunluk ≤ limit).

    Gövde: kısa sistem özeti + günlüğün son satırları. Sığmazsa günlükten en eski
    satırlar atılır (en yeni satırlar kalır) ve "(tam rapor ekte)" notu eklenir.
    """
    head = f"mailto:{DESTEK_EPOSTA}?subject={_quote(report['subject'])}&body="
    tail = list(report.get("tail") or [])
    note = t("(tam rapor ekte)")

    def url(lines, truncated):
        body = mail_body(report, lines)
        if truncated:
            body += "\n" + note
        return head + _quote(body)

    full = url(tail, False)
    if len(full) <= limit:
        return full
    lo, hi = 0, len(tail)  # en çok kaç son satır sığar (ikili arama)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(url(tail[-mid:] if mid else [], True)) <= limit:
            lo = mid
        else:
            hi = mid - 1
    out = url(tail[-lo:] if lo else [], True)
    if len(out) <= limit:
        return out
    # Özet bile sığmıyor (çok uzun hata mesajı): gövde sondan kısaltılır, not başta kalır.
    body = note + "\n" + mail_body(report, None)
    lo, hi = 0, len(body)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(head + _quote(body[:mid] + "…")) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return head + _quote(body[:lo] + "…")


def clipboard_text(report):
    """Yedek yol (e-posta uygulaması yoksa): alıcı + konu + tam rapor."""
    return (f"{t('Alıcı')}: {DESTEK_EPOSTA}\n{t('Konu')}: {report['subject']}\n\n{report['text']}")


def save_report(report, directory=None):
    """Tam raporu hata_raporlari/SesVer-hata-raporu-<YYYYAAGG-SSddss>.txt olarak yazar."""
    directory = Path(directory or REPORT_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / report["filename"]
    path.write_text(report["text"], encoding="utf-8")
    return path


def _platform():
    return sys.platform


def reveal(path, platform_name=None, popen=subprocess.Popen):
    """Dosyayı klasöründe seçili gösterir (Windows Explorer / macOS Finder). Başarıda True."""
    plat = platform_name or _platform()
    path = str(path)
    try:
        if plat == "win32":
            popen(["explorer", f"/select,{path}"])
        elif plat == "darwin":
            popen(["open", "-R", path])
        else:
            popen(["xdg-open", os.path.dirname(path)])
        return True
    except (OSError, ValueError):
        return False


def open_mailto(url, platform_name=None, startfile=None, run=subprocess.run):
    """Varsayılan e-posta uygulamasında taslak açar (göndermez). Başarıda True.

    pywebview içinde webbrowser.open güvenilir değildir; Python tarafından açılır.
    """
    plat = platform_name or _platform()
    try:
        if plat == "win32":
            (startfile or getattr(os, "startfile"))(url)
            return True
        cmd = ["open", url] if plat == "darwin" else ["xdg-open", url]
        return run(cmd, capture_output=True, timeout=15).returncode == 0
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return False


def copy_to_clipboard(text, platform_name=None, run=subprocess.run):
    """Panoya kopyalar (Windows clip.exe UTF-16, macOS pbcopy, Linux xclip/wl-copy)."""
    plat = platform_name or _platform()
    try:
        if plat == "win32":
            res = run(["clip"], input=("\ufeff" + text).encode("utf-16-le"), capture_output=True, timeout=10,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        elif plat == "darwin":
            res = run(["pbcopy"], input=text.encode("utf-8"), capture_output=True, timeout=10,
                      env={**os.environ, "LANG": "en_US.UTF-8"})
        else:
            tool = shutil.which("wl-copy") and ["wl-copy"] or ["xclip", "-selection", "clipboard"]
            res = run(tool, input=text.encode("utf-8"), capture_output=True, timeout=10)
        return res.returncode == 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def send(report, directory=None):
    """Onaydan sonra: raporu kaydet, klasörde göster, e-posta taslağını aç.

    Dönen: (kayıt yolu, taslak açıldı mı). Hiçbir şey gönderilmez; gönderen kullanıcıdır.
    """
    path = save_report(report, directory)
    reveal(path)
    return path, open_mailto(mailto_url(report))


# --- Arayüz iletileri (app.py ve desktop.py hata ekranı ortak kullanır) -----------------------

def consent_text():
    return (t("Bu bilgileri gönderiyorum; metnim ve seslerim dahil değil."),
            t("Rapor yalnız teknik bilgi içerir (sürüm, sistem, ekran kartı, hata ve günlüğün son satırları); "
              "ev klasörü yolları, e-posta adresleri ve erişim anahtarları gizlenir."))


def recipient_text(addr=DESTEK_EPOSTA):
    return t("Alıcı: {adres} · E-posta uygulamanız yoksa raporu panoya kopyalayıp Gmail'de yeni ileti "
             "açın ve yapıştırın.", adres=addr)


def send_message(path, opened, fmt_path=None, fmt_addr=None):
    fmt_path, fmt_addr = fmt_path or str, fmt_addr or str
    if opened:
        return "✅ " + t("E-posta taslağı açıldı. Rapor dosyası klasöründe seçili: {yol} — e-postaya "
                        "sürükleyip ekleyin ve kendiniz gönderin.", yol=fmt_path(path))
    return "⚠️ " + t("E-posta uygulaması açılamadı. “Panoya kopyala”ya basın, Gmail'de yeni ileti açıp "
                    "yapıştırın ve {adres} adresine gönderin. Rapor dosyası: {yol}",
                    adres=fmt_addr(DESTEK_EPOSTA), yol=fmt_path(path))


def copy_message(ok, fmt_addr=None):
    fmt_addr = fmt_addr or str
    if ok:
        return "✅ " + t("Rapor panoya kopyalandı. Gmail'de yeni ileti açıp yapıştırın; alıcı: {adres}",
                        adres=fmt_addr(DESTEK_EPOSTA))
    return "⚠️ " + t("Panoya kopyalanamadı; kutudaki metni seçip kopyalayın (Ctrl+A, Ctrl+C) ve {adres} "
                    "adresine gönderin.", adres=fmt_addr(DESTEK_EPOSTA))
