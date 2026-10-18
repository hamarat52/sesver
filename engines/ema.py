"""EMA Lightning (yerel, yalnız Türkçe) motoru: gelecekteki "⚡ Hızlı Mod".

Bu modül iki parçadan oluşur, ikisi de arayüzden bağımsızdır:

1. **Tek tuşla kurulum altyapısı**: ``ema_status()``, ``ema_install(progress_cb)``,
   ``ema_uninstall()``. Arayüz (Faz 3, Yusuf'un onayıyla) yalnız bu üç
   fonksiyonu çağırır.
2. **``EmaEngine``**: ``engines.base.Engine`` sözleşmesine uyan adaptör.
   ``SESVER_ENGINE=ema`` ile seçilir; varsayılan motor yine VoxCPM2'dir.

EMA'nın verdiği imkânlar ve SesVer'deki karşılığı:

* metin → ses (yalnız Türkçe, tek ses)        → ``synthesize``
* ``speed`` 0.25–4                             → ``synthesize(speed=...)``
* ``seed`` (okuma varyasyonu; aynı seed = aynı ses) → ``synthesize(seed=...)``
* kelime zamanları                             → SRT doğrudan bunlardan (``engines.srt``)
* akış (``EMA.stream``)                        → ``stream``

EMA'da **olmayanlar**: ses tarifi, ses klonu / referans kayıt, duygu/stil
talimatı, başka dil. Bunlar istendiğinde açık ``NotSupportedError`` verilir;
sessizce yok sayılmaz.

Kurulum ilkeleri (gerekçe: PLAN-MOTORLAR.md §4):

* Paket SesVer'in **kendi** ``.venv``'ine, sürüm sabitlenerek ve ``--no-deps``
  ile kurulur: torch/numpy/huggingface-hub zaten var, pip bunlara dokunmaz.
* Ağırlıklar Hugging Face'in genel önbelleğine değil, SesVer'in kendi
  klasörüne (``models/ema-lightning``, ``.gitignore``'da) iner; böylece
  ``ema_uninstall()`` yalnız EMA ağırlıklarını siler, başka araçların
  (ör. ``~/.hermes/tts``) önbelleğine dokunmaz.
* İndirme sabit bir model revizyonundan yapılır ve SHA-256 ile doğrulanır
  (ağırlıklar ``torch.load(weights_only=False)`` ile açıldığı için şart).
* Önce geçici klasöre indirilir; hepsi doğrulanınca yerine taşınır. Hata ya da
  iptalde geçici dosyalar silinir, bu çağrının kurduğu paketler geri alınır.

Bu modülü içe aktarmak torch'u, ``ema_lightning``'i ya da modeli YÜKLEMEZ.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import weakref
from collections import deque
from dataclasses import asdict, dataclass, field
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Callable, Iterator, Optional
from uuid import uuid4

from .base import (Capabilities, Engine, EngineError, EngineNotInstalledError, InstallCancelledError, InstallError,
                   NotSupportedError, SynthesisResult, TextTooLongError, UsageInfo, VoiceInfo)
from . import srt as srt_mod

# --- Sabitler (2026-10-18'de PyPI ve Hugging Face API'sinden okundu) ---------
PACKAGE = "ema-lightning"
PACKAGE_VERSION = "1.0.3"                 # Haberci'nin doğruladığı ve makinede denenmiş sürüm
NORMALIZER_PACKAGE = "normalizer-tr"
NORMALIZER_VERSION = "0.4.0"              # ema-lightning 1.0.3: normalizer-tr>=0.4,<0.5
NORMALIZER_RANGE = ((0, 4), (0, 5))
# ema-lightning 1.0.3'ün diğer bağımlılıkları; SesVer'in .venv'inde zaten var, --no-deps ile korunur.
REQUIRED_DEPENDENCIES = {"torch": (2, 1), "numpy": (1, 24), "huggingface-hub": (0, 20)}
MIN_PYTHON = (3, 11)
# Kurulacak tekerleklerin yaklaşık boyutu (PyPI: ema_lightning-1.0.3 32.095 B,
# normalizer_tr-0.4.0 cp311 macOS arm64 1.266.516 B).
PACKAGE_DOWNLOAD_BYTES = 32_095 + 1_266_516

HF_REPO = "canberkkkkkk/ema-lightning"
HF_REVISION = "7a6ba1ad216bb2f1da9863f80ac8770a6a807632"   # sabit revizyon: ağırlık değişirse bilinçli güncellenir
HF_BASE_URL = "https://huggingface.co"
LICENSE = "Apache-2.0"


@dataclass(frozen=True)
class WeightFile:
    name: str
    size: int
    sha256: Optional[str] = None          # LFS dosyaları
    git_sha1: Optional[str] = None        # küçük (LFS olmayan) dosyalar: git blob kimliği


WEIGHT_FILES = (
    WeightFile("config.json", 342, git_sha1="a4f3b575eff6aa203c2142c6d3facaed48a82935"),
    WeightFile("ema.pt", 22_285_878, sha256="95aec03dafbe0e1d69bca774ab597c779464729a14bc99bfcb52480090c7dfe6"),
    WeightFile("decoder.pt", 12_103_269, sha256="9595819b173f411340f63d11332695121a97f8bf1f6d8b6fef0b21cf99c7ad67"),
)
WEIGHTS_BYTES = sum(w.size for w in WEIGHT_FILES)  # 34.389.489 B ≈ 34,4 MB
MANIFEST = "sesver-ema.json"
TMP_PREFIX = ".tmp-"

WEIGHTS_DIR_ENV = "SESVER_EMA_DIR"
DEVICE_ENV = "SESVER_EMA_DEVICE"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEIGHTS_DIR = REPO_ROOT / "models" / "ema-lightning"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs"

SAMPLE_RATE = 48000                       # EMA'nın doğal çıkışı = VoxCPM2 çıkışı (48 kHz)
SAMPLE_RATES = (48000, 24000, 16000, 8000)
SPEED_RANGE = (0.25, 4.0)
MAX_TEXT_CHARS = 5000                     # EMA metni kendisi parçalar; bu sınır yalnız arayüz koruması
VOICE_ID = "ema"
CHUNK_SIZE = 1 << 20

NO_DESIGN_MSG = ("EMA Lightning (Hızlı Mod) motorunda ses tarifi yok: tek bir Türkçe ses var. "
                 "Seed yalnız aynı sesin farklı bir okumasını verir; tarifle ses için VoxCPM2 ya da ElevenLabs motorunu seçin.")
NO_CLONE_MSG = ("EMA Lightning (Hızlı Mod) motorunda ses klonu yok: referans kayıt kabul etmez. "
                "Kayıttan ses için VoxCPM2 motorunu seçin.")
NO_INSTRUCTION_MSG = ("EMA Lightning (Hızlı Mod) motorunda duygu/stil talimatı yok. "
                      "Yalnız hız ve seed ayarlanabilir; duygu için VoxCPM2 motorunu seçin.")


class EmaNetworkError(InstallError):
    """EMA ağırlıkları indirilirken ağ/HTTP hatası; yarım dosyalar temizlendi."""


# --- Yardımcılar ---------------------------------------------------------------
def format_size(num_bytes: int) -> str:
    """Türkçe boyut etiketi (ondalık MB, virgüllü): 34389489 → '34,4 MB'."""
    num = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1000 or unit == "GB":
            text = f"{num:.0f}" if unit == "B" else f"{num:.1f}"
            return f"{text.replace('.', ',')} {unit}"
        num /= 1000.0
    return f"{num_bytes} B"  # pragma: no cover


def _parse_version(text: Optional[str]) -> tuple:
    out = []
    for part in (text or "").split("+")[0].split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


def _installed_version(dist: str, lookup: Optional[Callable[[str], str]] = None) -> Optional[str]:
    lookup = lookup or importlib_metadata.version
    try:
        return lookup(dist)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:  # bozuk metadata: kurulu sayma
        return None


def weights_dir(path: Optional[os.PathLike] = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get(WEIGHTS_DIR_ENV, "").strip()
    return Path(env).expanduser() if env else DEFAULT_WEIGHTS_DIR


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _verify_file(path: Path, spec: WeightFile) -> bool:
    if not path.is_file() or path.stat().st_size != spec.size:
        return False
    if spec.sha256:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(CHUNK_SIZE), b""):
                digest.update(block)
        return digest.hexdigest() == spec.sha256
    if spec.git_sha1:
        return _git_blob_sha1(path.read_bytes()) == spec.git_sha1
    return True


def _url(spec: WeightFile, revision: str = HF_REVISION, base_url: str = HF_BASE_URL) -> str:
    return f"{base_url}/{HF_REPO}/resolve/{revision}/{spec.name}"


# --- Durum ---------------------------------------------------------------------
@dataclass
class EmaStatus:
    package_installed: bool               # ema-lightning beklenen sürümde kurulu mu
    package_version: Optional[str]
    normalizer_version: Optional[str]
    dependencies_ok: bool                 # python + torch/numpy/huggingface-hub uygun mu
    missing_dependencies: tuple
    weights_dir: str
    weights_present: bool                 # üç ağırlık dosyası tam boyutta (verify=True ise hash ile) mevcut
    files: dict = field(default_factory=dict)
    weights_bytes: int = 0                # diskteki EMA ağırlıkları (ema_uninstall'un boşaltacağı yer)
    download_bytes: int = 0               # eksik ağırlıklar için indirilecek
    package_download_bytes: int = 0       # paket eksikse tekerlek boyutu (yaklaşık)
    revision: str = HF_REVISION
    verified: bool = False

    @property
    def ready(self) -> bool:
        return self.package_installed and self.dependencies_ok and self.weights_present

    @property
    def total_download_bytes(self) -> int:
        return self.download_bytes + self.package_download_bytes

    @property
    def download_label(self) -> str:
        """Arayüz düğmesi için: "EMA'yı indir (~34,4 MB)"."""
        return f"~{format_size(self.total_download_bytes)}"

    def as_dict(self) -> dict:
        data = asdict(self)
        data.update(ready=self.ready, total_download_bytes=self.total_download_bytes,
                    download_label=self.download_label, weights_label=format_size(self.weights_bytes))
        return data


def _dependency_report(version_lookup=None, python_version=None) -> tuple:
    missing = []
    py = tuple(python_version or sys.version_info[:2])
    if py < MIN_PYTHON:
        missing.append(f"python>={MIN_PYTHON[0]}.{MIN_PYTHON[1]} (şu an {py[0]}.{py[1]})")
    for dist, minimum in REQUIRED_DEPENDENCIES.items():
        version = _installed_version(dist, version_lookup)
        if version is None or _parse_version(version) < minimum:
            missing.append(f"{dist}>={'.'.join(map(str, minimum))}" + (f" (şu an {version})" if version else ""))
    return tuple(missing)


def ema_status(*, weights_path: Optional[os.PathLike] = None, verify: bool = False,
               version_lookup: Optional[Callable[[str], str]] = None, python_version=None) -> EmaStatus:
    """Kurulu mu, ağırlıklar inmiş mi, ne kadar yer kaplıyor, ne kadar inecek.

    Hızlıdır: torch'u ya da ``ema_lightning``'i içe aktarmaz, ağa çıkmaz.
    ``verify=True`` ağırlıkların SHA-256'sını da hesaplar (~34 MB okuma).
    """
    folder = weights_dir(weights_path)
    package_version = _installed_version(PACKAGE, version_lookup)
    normalizer_version = _installed_version(NORMALIZER_PACKAGE, version_lookup)
    normalizer_ok = (normalizer_version is not None
                     and NORMALIZER_RANGE[0] <= _parse_version(normalizer_version)[:2] < NORMALIZER_RANGE[1])
    package_ok = package_version == PACKAGE_VERSION and normalizer_ok
    missing = _dependency_report(version_lookup, python_version)

    files, on_disk, to_download = {}, 0, 0
    for spec in WEIGHT_FILES:
        path = folder / spec.name
        size = path.stat().st_size if path.is_file() else 0
        ok = _verify_file(path, spec) if verify else (size == spec.size)
        files[spec.name] = {"present": ok, "size": size, "expected": spec.size}
        on_disk += size
        if not ok:
            to_download += spec.size
    return EmaStatus(
        package_installed=package_ok, package_version=package_version, normalizer_version=normalizer_version,
        dependencies_ok=not missing, missing_dependencies=missing, weights_dir=str(folder),
        weights_present=to_download == 0, files=files, weights_bytes=on_disk, download_bytes=to_download,
        package_download_bytes=0 if package_ok else PACKAGE_DOWNLOAD_BYTES, verified=verify,
    )


# --- Kurulum ---------------------------------------------------------------------
@dataclass
class InstallProgress:
    stage: str                  # kontrol | paket | indirme | dogrulama | tamam | geri_alma
    fraction: float             # genel ilerleme 0..1 (ilerleme çubuğu bunu gösterir)
    message: str
    file: Optional[str] = None
    done_bytes: int = 0
    total_bytes: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def _cancel_checker(cancel) -> Callable[[], bool]:
    if cancel is None:
        return lambda: False
    if hasattr(cancel, "is_set"):
        return cancel.is_set
    if callable(cancel):
        return lambda: bool(cancel())
    raise TypeError("cancel bir threading.Event ya da bool döndüren fonksiyon olmalı.")


def default_opener(url: str, timeout: float):
    request = urllib.request.Request(url, headers={"User-Agent": "SesVer-EMA-kurulum/1"})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 — sabit https adresi


def default_pip_runner(args: list, is_cancelled: Callable[[], bool], poll: float = 0.2) -> tuple:
    """``python -m pip <args>`` çalıştırır; iptalde süreci sonlandırır.

    Dönüş: ``(returncode, son_satırlar)``; iptalde ``returncode`` None'dır.
    """
    proc = subprocess.Popen([sys.executable, "-m", "pip", *args], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    tail: deque = deque(maxlen=20)
    reader = threading.Thread(target=lambda: [tail.append(line.rstrip()) for line in proc.stdout], daemon=True)
    reader.start()
    while proc.poll() is None:
        if is_cancelled():
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            reader.join(timeout=1)
            return None, "\n".join(tail)
        time.sleep(poll)
    reader.join(timeout=1)
    return proc.returncode, "\n".join(tail)


def _pip_install_args(specs: list) -> list:
    # --only-binary: normalizer-tr Rust eklentisidir; tekerlek yoksa derlemeye düşmek yerine açık hata.
    return ["install", "--no-deps", "--only-binary=:all:", "--disable-pip-version-check", "--no-input", *specs]


class _Installer:
    def __init__(self, progress_cb, cancel, folder, opener, pip_runner, timeout, chunk_size, version_lookup,
                 python_version, base_url, disk_usage):
        self.progress_cb = progress_cb
        self.is_cancelled_flag = _cancel_checker(cancel)
        self.folder = folder
        self.opener = opener or default_opener
        self.pip_runner = pip_runner or default_pip_runner
        self.timeout = timeout
        self.chunk_size = int(chunk_size)
        self.version_lookup = version_lookup
        self.python_version = python_version
        self.base_url = base_url
        self.disk_usage = disk_usage or shutil.disk_usage
        self.staging: Optional[Path] = None
        self.installed_packages: list = []      # (dağıtım, önceki_sürüm) — geri alma için
        self.created_folder = False
        self._user_cancelled = False

    # -- ilerleme ve iptal
    def emit(self, stage, fraction, message, **extra):
        if self.progress_cb is None:
            return
        answer = self.progress_cb(InstallProgress(stage, max(0.0, min(1.0, fraction)), message, **extra))
        if answer is False:
            self._user_cancelled = True

    def cancelled(self) -> bool:
        return self._user_cancelled or self.is_cancelled_flag()

    def check_cancel(self):
        if self.cancelled():
            raise InstallCancelledError("EMA kurulumu iptal edildi; yarım dosyalar silindi.")

    # -- adımlar
    def run(self) -> EmaStatus:
        try:
            return self._run()
        except InstallCancelledError:
            self.rollback()
            raise
        except InstallError:
            self.rollback()
            raise
        except Exception as exc:  # beklenmeyen: yine de iz bırakma
            self.rollback()
            raise InstallError(f"EMA kurulumu başarısız: {type(exc).__name__}: {exc}") from exc

    def _run(self) -> EmaStatus:
        self.emit("kontrol", 0.0, "Kurulum denetleniyor…")
        status = ema_status(weights_path=self.folder, verify=True, version_lookup=self.version_lookup,
                            python_version=self.python_version)
        if not status.dependencies_ok:
            raise InstallError("EMA için gereken temel paketler eksik ya da eski: "
                               + ", ".join(status.missing_dependencies)
                               + ". SesVer kurulumunu (baslat.command) yeniden çalıştırın; "
                                 "EMA kurulumu torch'u kendisi indirmez.")
        self.check_cancel()
        pkg_share = 0.0 if status.package_installed else 0.05
        if not status.package_installed:
            self.install_packages(status)
        missing = [spec for spec in WEIGHT_FILES if not status.files[spec.name]["present"]]
        if missing:
            self.download(missing, pkg_share)
        self.emit("dogrulama", 0.99, "Kurulum doğrulanıyor…")
        final = ema_status(weights_path=self.folder, verify=True, version_lookup=self.version_lookup,
                           python_version=self.python_version)
        if not final.ready:
            raise InstallError("EMA kurulumu doğrulanamadı; dosyalar beklenen boyut/özetle eşleşmiyor.")
        self.emit("tamam", 1.0, f"EMA hazır ({format_size(final.weights_bytes)}).")
        return final

    def install_packages(self, status: EmaStatus):
        before = {PACKAGE: status.package_version, NORMALIZER_PACKAGE: status.normalizer_version}
        specs = [f"{PACKAGE}=={PACKAGE_VERSION}", f"{NORMALIZER_PACKAGE}=={NORMALIZER_VERSION}"]
        self.emit("paket", 0.01, f"{PACKAGE} {PACKAGE_VERSION} kuruluyor…")
        # Geri alma için kurulumdan ÖNCE kaydedilir (pip yarıda kesilse bile temizlenir).
        self.installed_packages = [(PACKAGE, before[PACKAGE]), (NORMALIZER_PACKAGE, before[NORMALIZER_PACKAGE])]
        code, output = self.pip_runner(_pip_install_args(specs), self.cancelled)
        if code is None:
            self.check_cancel()
            raise InstallCancelledError("EMA kurulumu iptal edildi; yarım dosyalar silindi.")
        if code != 0:
            last = (output or "").strip().splitlines()[-1:] or [""]
            raise InstallError(f"EMA paketi kurulamadı (pip çıkış kodu {code}). {last[0]}".strip())
        import importlib  # noqa: WPS433

        importlib.invalidate_caches()  # aynı süreçte yeni paket içe aktarılabilsin
        self.check_cancel()
        self.emit("paket", 0.05, "Paket kuruldu.")

    def download(self, missing: list, start: float):
        total = sum(spec.size for spec in missing)
        try:
            self.folder.parent.mkdir(parents=True, exist_ok=True)
            free = self.disk_usage(str(self.folder.parent)).free
        except OSError as exc:
            raise InstallError(f"EMA klasörü hazırlanamadı: {exc}") from exc
        if free < total + 50_000_000:
            raise InstallError(f"Diskte yer yetmiyor: EMA için {format_size(total)} + 50 MB pay gerekli, "
                               f"boş {format_size(free)}.")
        if not self.folder.exists():
            self.folder.mkdir(parents=True)
            self.created_folder = True
        self.staging = self.folder / f"{TMP_PREFIX}{uuid4().hex}"
        self.staging.mkdir()
        done = 0
        for spec in missing:
            done = self._download_one(spec, done, total, start)
        self.check_cancel()
        # Hepsi doğrulandı: şimdi yerine taşı (aynı dosya sistemi → os.replace atomik).
        for spec in missing:
            os.replace(self.staging / spec.name, self.folder / spec.name)
        self._write_manifest()
        shutil.rmtree(self.staging, ignore_errors=True)
        self.staging = None

    def _download_one(self, spec: WeightFile, done: int, total: int, start: float) -> int:
        url = _url(spec, base_url=self.base_url)
        target = self.staging / spec.name
        sha256 = hashlib.sha256()
        received = 0
        message = f"{spec.name} indiriliyor…"
        try:
            response = self.opener(url, self.timeout)
            with response, open(target, "wb") as fh:
                while True:
                    self.check_cancel()
                    block = response.read(self.chunk_size)
                    if not block:
                        break
                    fh.write(block)
                    sha256.update(block)
                    received += len(block)
                    if received > spec.size:
                        raise InstallError(f"{spec.name} beklenenden büyük geldi; indirme durduruldu.")
                    self.emit("indirme", start + (1 - start) * 0.98 * (done + received) / total, message,
                              file=spec.name, done_bytes=done + received, total_bytes=total)
        except urllib.error.HTTPError as exc:
            raise EmaNetworkError(f"EMA ağırlığı indirilemedi ({spec.name}): HTTP {exc.code}. "
                                  "Daha sonra yeniden deneyin.") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            reason = getattr(exc, "reason", exc)
            raise EmaNetworkError(f"EMA ağırlığı indirilemedi ({spec.name}): ağ hatası ({reason}). "
                                  "İnternet bağlantısını kontrol edip yeniden deneyin.") from exc
        except OSError as exc:
            raise InstallError(f"EMA ağırlığı yazılamadı ({spec.name}): {exc}") from exc
        if received != spec.size:
            raise EmaNetworkError(f"{spec.name} eksik indi ({received}/{spec.size} bayt); bağlantı kesilmiş olabilir.")
        if spec.sha256 and sha256.hexdigest() != spec.sha256:
            raise InstallError(f"{spec.name} doğrulanamadı (SHA-256 eşleşmiyor); dosya kullanılmadı.")
        if spec.git_sha1 and _git_blob_sha1(target.read_bytes()) != spec.git_sha1:
            raise InstallError(f"{spec.name} doğrulanamadı (özet eşleşmiyor); dosya kullanılmadı.")
        return done + received

    def _write_manifest(self):
        data = {"package": PACKAGE, "package_version": PACKAGE_VERSION, "repo": HF_REPO, "revision": HF_REVISION,
                "license": LICENSE, "files": {s.name: {"size": s.size, "sha256": s.sha256} for s in WEIGHT_FILES}}
        tmp = self.staging / MANIFEST
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.folder / MANIFEST)

    # -- geri alma: bu çağrının bıraktığı her şeyi temizle
    def rollback(self):
        if self.staging is not None:
            shutil.rmtree(self.staging, ignore_errors=True)
            self.staging = None
        if self.created_folder:
            try:
                self.folder.rmdir()  # yalnız boşsa
            except OSError:
                pass
        if self.installed_packages:
            self.emit_safe("geri_alma", 0.0, "Yarım kurulum geri alınıyor…")
            remove = [dist for dist, before in self.installed_packages if before is None]
            restore = [f"{dist}=={before}" for dist, before in self.installed_packages if before is not None]
            never = lambda: False  # noqa: E731 — geri alma iptal edilemez
            try:
                if remove:
                    self.pip_runner(["uninstall", "-y", *remove], never)
                if restore:
                    self.pip_runner(_pip_install_args(restore), never)
            except Exception:  # geri alma en iyi çabadır; asıl hata korunur
                pass
            self.installed_packages = []

    def emit_safe(self, *args, **kwargs):
        try:
            self.emit(*args, **kwargs)
        except Exception:
            pass


def ema_install(progress_cb: Optional[Callable[[InstallProgress], Optional[bool]]] = None, *, cancel=None,
                weights_path: Optional[os.PathLike] = None, opener: Optional[Callable] = None,
                pip_runner: Optional[Callable] = None, timeout: float = 60.0, chunk_size: int = CHUNK_SIZE,
                version_lookup: Optional[Callable[[str], str]] = None, python_version=None,
                base_url: str = HF_BASE_URL, disk_usage: Optional[Callable] = None) -> EmaStatus:
    """"Tek tuşla indir": paketi kurar, ağırlıkları indirip doğrular.

    * ``progress_cb(InstallProgress)`` her adımda çağrılır; ``False`` dönerse kurulum iptal edilir.
    * ``cancel``: ``threading.Event`` (ya da bool döndüren fonksiyon); başka iş parçacığından iptal için.
    * Başarıda doğrulanmış ``EmaStatus`` döner (``ready=True``).
    * Hata → ``InstallError`` (ağ için ``EmaNetworkError``); iptal → ``InstallCancelledError``.
      İkisinde de geçici dosyalar silinir ve bu çağrının kurduğu paketler geri alınır.
    * Zaten kuruluysa ağa çıkmadan döner (ağırlıklar hash ile doğrulanır).

    ``opener``/``pip_runner``/``version_lookup``/``disk_usage`` testlerde taklit edilir.
    """
    installer = _Installer(progress_cb, cancel, weights_dir(weights_path), opener, pip_runner, timeout, chunk_size,
                           version_lookup, python_version, base_url, disk_usage)
    with _INSTALL_LOCK:
        return installer.run()


_INSTALL_LOCK = threading.Lock()
_LOADED_ENGINES: "weakref.WeakSet" = weakref.WeakSet()


def ema_uninstall(*, weights_path: Optional[os.PathLike] = None) -> dict:
    """Yalnız EMA ağırlıklarını siler (paketlere, HF önbelleğine, başka klasöre dokunmaz).

    Silinenler: üç ağırlık dosyası, ``sesver-ema.json`` ve yarım kalmış
    ``.tmp-*`` klasörleri; klasör boş kalırsa o da. Klasörde başka dosya varsa
    korunur. Dönüş: ``{"removed": [...], "freed_bytes": N, "weights_dir": ...}``.
    """
    folder = weights_dir(weights_path)
    for engine in list(_LOADED_ENGINES):
        engine.release()
    removed, freed = [], 0
    with _INSTALL_LOCK:
        if folder.is_symlink():
            raise EngineError("EMA klasörü bir kısayol (symlink); güvenlik için silinmedi.")
        if not folder.is_dir():
            return {"removed": [], "freed_bytes": 0, "weights_dir": str(folder)}
        for name in [spec.name for spec in WEIGHT_FILES] + [MANIFEST]:
            path = folder / name
            if path.is_file() and not path.is_symlink():
                freed += path.stat().st_size
                path.unlink()
                removed.append(name)
        for tmp in folder.glob(f"{TMP_PREFIX}*"):
            if tmp.is_dir() and not tmp.is_symlink():
                freed += sum(f.stat().st_size for f in tmp.rglob("*") if f.is_file())
                shutil.rmtree(tmp, ignore_errors=True)
                removed.append(tmp.name)
        try:
            folder.rmdir()
        except OSError:
            pass
    return {"removed": removed, "freed_bytes": freed, "weights_dir": str(folder)}


# --- Model yükleme ---------------------------------------------------------------
def default_loader(folder: Path, device: str = "auto"):
    """Ağırlıkları SesVer klasöründen yükler (ağa çıkmaz; ``hf_hub_download`` kullanılmaz).

    ``EMA()`` kurucusu ağırlıkları HF önbelleğinden istediği için sabitlenen
    1.0.3'ün kendi parçaları doğrudan kullanılır: ``load_acoustic``,
    ``load_decoder``, ``Frontend`` ve ``EMA._from_parts``.
    """
    import torch  # noqa: WPS433 — yalnız ilk üretimde
    from ema_lightning.api import EMA
    from ema_lightning.decoder import load_decoder
    from ema_lightning.frontend import Frontend
    from ema_lightning.model import load_acoustic

    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    dev = torch.device(device)
    acoustic = load_acoustic(str(folder / "ema.pt"), dev)
    decoder = load_decoder(str(folder / "decoder.pt"), dev)
    return EMA._from_parts(acoustic, decoder, Frontend(acoustic.vocab), dev)


def _word_dict(word) -> dict:
    w = srt_mod._as_word(word)
    return {"text": w.text, "start": w.start, "end": w.end}


# --- Motor -----------------------------------------------------------------------
class EmaEngine(Engine):
    name = "ema"

    def __init__(self, output_dir: Optional[os.PathLike] = None, weights_path: Optional[os.PathLike] = None,
                 device: Optional[str] = None, loader: Optional[Callable] = None,
                 status_fn: Optional[Callable[..., EmaStatus]] = None, write_srt: bool = True):
        self.output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
        self.weights_path = weights_dir(weights_path)
        self.device = device or os.environ.get(DEVICE_ENV, "").strip() or "auto"
        self._loader = loader or default_loader
        self._status_fn = status_fn or ema_status
        self.write_srt = write_srt
        self._model = None
        self._lock = threading.Lock()
        _LOADED_ENGINES.add(self)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            name=self.name, local=True, seed=True, seed_deterministic=True, continuation=False, instruction=False,
            description_design=False, clone=False, multi_candidate=False, default_candidates=1,
            candidates_per_design_call=0, quality_modes=(), max_text_chars=MAX_TEXT_CHARS, requires_api_key=False,
            metered=False, speed=True, word_timestamps=True, streaming=True, languages=("tr",),
            notes=("%100 yerel: metin ve ses bilgisayardan çıkmaz (yalnız ilk kurulumda ~34 MB ağırlık iner).",
                   "Yalnız Türkçe, tek ses: tarif, klon, referans kayıt ve duygu talimatı yok.",
                   "seed okuma varyasyonu verir (ses kimliği tek); paket belgesine göre aynı seed = aynı ses, bu makinede Faz 2'de doğrulanacak.",
                   f"Hız {SPEED_RANGE[0]}–{SPEED_RANGE[1]}; kelime zamanları SRT'ye doğrudan yazılır."),
        )

    # -- yaşam döngüsü
    def status(self, verify: bool = False) -> EmaStatus:
        return self._status_fn(weights_path=self.weights_path, verify=verify)

    def release(self):
        with self._lock:
            self._model = None

    def _get_model(self):
        with self._lock:
            if self._model is None:
                status = self.status(verify=True)  # torch.load(pickle) öncesi SHA-256 şart
                if not status.ready:
                    raise EngineNotInstalledError(
                        f"EMA kurulu değil ya da eksik. Önce ema_install() ile indirin ({status.download_label}).")
                try:
                    self._model = self._loader(self.weights_path, self.device)
                except EngineError:
                    raise
                except Exception as exc:
                    raise EngineError(f"EMA modeli yüklenemedi: {type(exc).__name__}: {exc}") from exc
            return self._model

    # -- doğrulama
    @staticmethod
    def _reject_unsupported(voice, instruction, options: dict):
        if instruction:
            raise NotSupportedError(NO_INSTRUCTION_MSG)
        if options.get("description") or options.get("tarif") or options.get("voice_description"):
            raise NotSupportedError(NO_DESIGN_MSG)
        clone_keys = ("reference_audio", "reference_wav", "prompt_wav", "prompt_text", "audio", "transcript")
        if any(options.get(k) for k in clone_keys):
            raise NotSupportedError(NO_CLONE_MSG)
        if voice not in (None, "", VOICE_ID):
            raise NotSupportedError(f"EMA'da tek ses var ({VOICE_ID!r}); {voice!r} sesi kullanılamaz. " + NO_CLONE_MSG)

    @staticmethod
    def _check_args(text, speed, seed, sample_rate) -> str:
        text = (text or "").strip()
        if not text:
            raise EngineError("Metin boş olamaz.")
        if len(text) > MAX_TEXT_CHARS:
            raise TextTooLongError(f"Metin çok uzun ({len(text)} karakter); Hızlı Mod sınırı {MAX_TEXT_CHARS}.")
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not SPEED_RANGE[0] <= speed <= SPEED_RANGE[1]:
            raise EngineError(f"Hız {SPEED_RANGE[0]} ile {SPEED_RANGE[1]} arasında bir sayı olmalı.")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or seed < 0):
            raise EngineError("Seed sıfır ya da pozitif bir tam sayı olmalı.")
        if sample_rate not in SAMPLE_RATES:
            raise EngineError(f"Örnekleme hızı şunlardan biri olmalı: {SAMPLE_RATES}.")
        return text

    # -- sentez
    def synthesize(self, text: str, voice: Optional[str] = None, instruction: Optional[str] = None,
                   seed: Optional[int] = None, quality: str = "Dengeli", *, speed: float = 1.0,
                   sample_rate: int = SAMPLE_RATE, **options: Any) -> SynthesisResult:
        """Metin → mono 16-bit WAV (+ aynı adla ``.srt``). ``quality`` EMA'da yoktur, yok sayılır."""
        self._reject_unsupported(voice, instruction, options)
        text = self._check_args(text, speed, seed, sample_rate)
        model = self._get_model()
        try:
            speech = model.say(text, speed=float(speed), seed=seed, sample_rate=int(sample_rate))
        except EngineError:
            raise
        except Exception as exc:
            raise EngineError(f"EMA üretimi başarısız: {type(exc).__name__}: {exc}") from exc
        import numpy as np  # noqa: WPS433
        import soundfile as sf  # noqa: WPS433

        audio = np.asarray(speech.audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=-1 if audio.shape[-1] <= 2 else 0)
        if audio.size == 0:
            raise EngineError("EMA boş ses üretti; metni kontrol edin.")
        rate = int(getattr(speech, "sample_rate", sample_rate) or sample_rate)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stem = f"ema-{uuid4().hex}"
        final = self.output_dir / f"{stem}.wav"
        tmp = self.output_dir / f".{stem}.tmp.wav"
        try:
            sf.write(str(tmp), np.clip(audio, -1.0, 1.0), rate, subtype="PCM_16", format="WAV")
            os.replace(tmp, final)
        finally:
            if tmp.exists():
                tmp.unlink()
        words = [_word_dict(w) for w in (getattr(speech, "words", ()) or ())]
        srt_text = srt_mod.words_to_srt(words)
        srt_path = None
        if self.write_srt and srt_text:
            srt_path = str(final.with_suffix(".srt"))
            Path(srt_path).write_text(srt_text, encoding="utf-8")
        used_seed = getattr(speech, "seed", seed)
        return SynthesisResult(path=str(final), sample_rate=rate, meta={
            "engine": self.name, "mode": "ema", "voice": VOICE_ID, "seed": used_seed, "speed": float(speed),
            "quality": None, "duration": round(audio.size / rate, 3), "characters": len(text), "credits": 0.0,
            "words": words, "srt": srt_text, "srt_path": srt_path})

    def stream(self, text: str, *, speed: float = 1.0, seed: Optional[int] = None,
               sample_rate: int = SAMPLE_RATE, voice: Optional[str] = None, instruction: Optional[str] = None,
               **options: Any) -> Iterator:
        """Ses parçalarını üretildikçe verir (float32, mono). Önce kontroller, sonra model."""
        self._reject_unsupported(voice, instruction, options)
        text = self._check_args(text, speed, seed, sample_rate)
        model = self._get_model()
        import numpy as np  # noqa: WPS433

        for chunk in model.stream(text, speed=float(speed), seed=seed, sample_rate=int(sample_rate)):
            yield np.asarray(chunk, dtype=np.float32)

    def list_voices(self) -> list:
        return [VoiceInfo(id=VOICE_ID, name="EMA (Türkçe)", category="Hızlı Mod",
                          description="Tek yerel Türkçe ses; seed ile okuma varyasyonu değişir.", engine=self.name,
                          extra={"license": LICENSE, "languages": ["tr"]})]

    def design_voice(self, description: str, preview_text: str, candidates: int = 1, **options: Any) -> list:
        raise NotSupportedError(NO_DESIGN_MSG)

    def clone_voice(self, audio: str, transcript: Optional[str], consent: bool, **options: Any) -> VoiceInfo:
        raise NotSupportedError(NO_CLONE_MSG)

    def usage(self) -> UsageInfo:
        status = self.status()
        return UsageInfo(engine=self.name, metered=False, can_clone=False,
                         extra={"installed": status.ready, "weights_bytes": status.weights_bytes,
                                "download_label": status.download_label})
