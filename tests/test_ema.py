"""EMA Lightning (Hızlı Mod) testleri: paket kurulmaz, ağa çıkılmaz, model yüklenmez.

pip, HTTP indirme, paket sürümleri ve EMA modeli taklit edilir. Ağırlık
listesi (``WEIGHT_FILES``) küçük sahte dosyalarla değiştirilir.
"""
import hashlib
import importlib.metadata
import io
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf

import engines
from engines import base, ema, srt

BASE_VERSIONS = {"torch": "2.14.1", "numpy": "2.4.6", "huggingface-hub": "2.2.0"}
INSTALLED = dict(BASE_VERSIONS, **{"ema-lightning": "1.0.3", "normalizer-tr": "0.4.0"})


def make_payloads():
    cfg = b'{"sample_rate": 48000}'
    return {"config.json": cfg, "ema.pt": os.urandom(300_000), "decoder.pt": os.urandom(150_000)}


def specs_for(payloads):
    return (
        ema.WeightFile("config.json", len(payloads["config.json"]),
                       git_sha1=hashlib.sha1(b"blob %d\0" % len(payloads["config.json"]) + payloads["config.json"]).hexdigest()),
        ema.WeightFile("ema.pt", len(payloads["ema.pt"]), sha256=hashlib.sha256(payloads["ema.pt"]).hexdigest()),
        ema.WeightFile("decoder.pt", len(payloads["decoder.pt"]),
                       sha256=hashlib.sha256(payloads["decoder.pt"]).hexdigest()),
    )


class Versions:
    """importlib.metadata.version yerine geçer; pip taklidi bunu günceller."""

    def __init__(self, versions):
        self.versions = dict(versions)

    def __call__(self, dist):
        if dist in self.versions:
            return self.versions[dist]
        raise importlib.metadata.PackageNotFoundError(dist)


class FakePip:
    def __init__(self, versions, code=0, cancel_on_install=False):
        self.versions = versions
        self.code = code
        self.cancel_on_install = cancel_on_install
        self.calls = []

    def __call__(self, args, is_cancelled):
        self.calls.append(list(args))
        if args[0] == "install":
            if self.cancel_on_install:
                return None, "iptal"
            if self.code != 0:
                return self.code, "ERROR: No matching distribution found for ema-lightning==1.0.3"
            for spec in args:
                if "==" in spec:
                    dist, version = spec.split("==")
                    self.versions.versions[dist] = version
            return 0, "Successfully installed"
        if args[0] == "uninstall":
            for dist in args[2:]:
                self.versions.versions.pop(dist, None)
            return 0, "Successfully uninstalled"
        raise AssertionError(args)


class FakeOpener:
    """Dosya adına göre yanıt verir; hata/kesinti senaryoları için kancalar."""

    def __init__(self, payloads, fail=None, truncate=None, corrupt=None):
        self.payloads = payloads
        self.fail = fail or {}            # ad -> istisna
        self.truncate = truncate or set()
        self.corrupt = corrupt or set()
        self.urls = []

    def __call__(self, url, timeout):
        self.urls.append(url)
        name = url.rsplit("/", 1)[-1]
        if name in self.fail:
            raise self.fail[name]
        data = self.payloads[name]
        if name in self.truncate:
            data = data[: len(data) // 2]
        if name in self.corrupt:
            data = bytes([data[0] ^ 0xFF]) + data[1:]
        return io.BytesIO(data)


def disk_ok(_path):
    return SimpleNamespace(free=10 * 1024 ** 3)


class EmaInstallBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / "models" / "ema-lightning"
        self.payloads = make_payloads()
        self.specs = specs_for(self.payloads)
        patcher = patch.object(ema, "WEIGHT_FILES", self.specs)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def install(self, versions, opener=None, pip=None, **kw):
        versions = versions if isinstance(versions, Versions) else Versions(versions)
        self.versions = versions
        self.pip = pip or FakePip(versions)
        self.opener = opener or FakeOpener(self.payloads)
        self.events = []
        kw.setdefault("progress_cb", self.events.append)
        return ema.ema_install(weights_path=self.folder, opener=self.opener, pip_runner=self.pip,
                               version_lookup=versions, python_version=(3, 11), chunk_size=64_000,
                               disk_usage=kw.pop("disk_usage", disk_ok), **kw)

    def assert_no_residue(self, keep=()):
        if not self.folder.exists():
            return
        leftovers = sorted(p.name for p in self.folder.iterdir())
        self.assertEqual(leftovers, sorted(keep), f"yarım dosya kaldı: {leftovers}")

    def status(self, versions=None, verify=False):
        return ema.ema_status(weights_path=self.folder, verify=verify, python_version=(3, 11),
                              version_lookup=Versions(versions if versions is not None else INSTALLED))


class StatusTests(EmaInstallBase):
    def test_not_installed(self):
        st = self.status(BASE_VERSIONS)
        self.assertFalse(st.package_installed)
        self.assertFalse(st.weights_present)
        self.assertFalse(st.ready)
        self.assertTrue(st.dependencies_ok)
        self.assertEqual(st.weights_bytes, 0)
        self.assertEqual(st.download_bytes, sum(s.size for s in self.specs))
        self.assertEqual(st.package_download_bytes, ema.PACKAGE_DOWNLOAD_BYTES)
        self.assertTrue(st.download_label.startswith("~"))
        self.assertIn("MB", st.download_label)
        self.assertIn("ready", st.as_dict())

    def test_status_does_not_import_heavy_modules(self):
        sys.modules.pop("ema_lightning", None)
        self.status()
        self.assertNotIn("ema_lightning", sys.modules)

    def test_partial_file_is_not_present(self):
        self.folder.mkdir(parents=True)
        (self.folder / "ema.pt").write_bytes(self.payloads["ema.pt"][:100])
        (self.folder / "config.json").write_bytes(self.payloads["config.json"])
        st = self.status()
        self.assertTrue(st.files["config.json"]["present"])
        self.assertFalse(st.files["ema.pt"]["present"])
        self.assertFalse(st.weights_present)
        self.assertEqual(st.download_bytes, self.specs[1].size + self.specs[2].size)

    def test_verify_detects_same_size_corruption(self):
        self.folder.mkdir(parents=True)
        for name, data in self.payloads.items():
            (self.folder / name).write_bytes(data)
        self.assertTrue(self.status(verify=True).ready)
        bad = bytearray(self.payloads["decoder.pt"])
        bad[10] ^= 0xFF
        (self.folder / "decoder.pt").write_bytes(bytes(bad))
        self.assertTrue(self.status(verify=False).weights_present)   # hızlı kontrol: boyut
        self.assertFalse(self.status(verify=True).weights_present)   # hash: bozuk

    def test_wrong_versions_and_missing_deps(self):
        st = self.status(dict(INSTALLED, **{"ema-lightning": "1.1.2"}))
        self.assertFalse(st.package_installed)
        st = self.status(dict(INSTALLED, **{"normalizer-tr": "0.6.0"}))
        self.assertFalse(st.package_installed)
        deps = dict(INSTALLED)
        deps.pop("torch")
        deps["numpy"] = "1.20.0"
        st = self.status(deps)
        self.assertFalse(st.dependencies_ok)
        self.assertTrue(any(m.startswith("torch") for m in st.missing_dependencies))
        self.assertTrue(any(m.startswith("numpy") for m in st.missing_dependencies))
        old_py = ema.ema_status(weights_path=self.folder, python_version=(3, 10), version_lookup=Versions(INSTALLED))
        self.assertTrue(any(m.startswith("python") for m in old_py.missing_dependencies))

    def test_format_size(self):
        self.assertEqual(ema.format_size(34_389_489), "34,4 MB")
        self.assertEqual(ema.format_size(512), "512 B")
        self.assertEqual(ema.format_size(1_298_611), "1,3 MB")

    def test_real_constants_match_hub(self):
        """2026-10-18 HF API: config 342 B, ema.pt 22.285.878 B, decoder.pt 12.103.269 B."""
        self.assertEqual(ema.WEIGHTS_BYTES, 342 + 22_285_878 + 12_103_269)
        self.assertEqual(ema.format_size(ema.WEIGHTS_BYTES), "34,4 MB")
        self.assertEqual(len(ema.HF_REVISION), 40)


class InstallFlowTests(EmaInstallBase):
    def test_success_from_scratch(self):
        st = self.install(BASE_VERSIONS)
        self.assertTrue(st.ready)
        self.assertTrue(st.verified)
        # paket: sabit sürüm + --no-deps (torch'a dokunmaz)
        self.assertEqual(len(self.pip.calls), 1)
        args = self.pip.calls[0]
        self.assertEqual(args[0], "install")
        self.assertIn("--no-deps", args)
        self.assertIn("--only-binary=:all:", args)
        self.assertIn("ema-lightning==1.0.3", args)
        self.assertIn("normalizer-tr==0.4.0", args)
        self.assertFalse(any(a.startswith("torch") for a in args))
        # indirme: sabit revizyondan, her dosya bir kez
        self.assertEqual(len(self.opener.urls), 3)
        for url in self.opener.urls:
            self.assertIn(f"/{ema.HF_REPO}/resolve/{ema.HF_REVISION}/", url)
        # dosyalar yerinde, geçici klasör yok
        self.assert_no_residue(keep=("config.json", "ema.pt", "decoder.pt", ema.MANIFEST))
        for name, data in self.payloads.items():
            self.assertEqual((self.folder / name).read_bytes(), data)
        # ilerleme: aşamalar sıralı, oran artan ve 1.0'da biter
        stages = [e.stage for e in self.events]
        self.assertEqual(stages[0], "kontrol")
        self.assertIn("paket", stages)
        self.assertIn("indirme", stages)
        self.assertEqual(stages[-1], "tamam")
        fractions = [e.fraction for e in self.events]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(fractions[-1], 1.0)
        last_dl = [e for e in self.events if e.stage == "indirme"][-1]
        self.assertEqual(last_dl.done_bytes, last_dl.total_bytes)

    def test_already_installed_is_noop(self):
        self.install(BASE_VERSIONS)
        pip_calls, urls = len(self.pip.calls), len(self.opener.urls)
        st = self.install(self.versions)
        self.assertTrue(st.ready)
        self.assertEqual(self.pip.calls, [])
        self.assertEqual(self.opener.urls, [])
        self.assertEqual((pip_calls, urls), (1, 3))

    def test_only_missing_files_are_downloaded(self):
        self.folder.mkdir(parents=True)
        (self.folder / "config.json").write_bytes(self.payloads["config.json"])
        self.install(INSTALLED)
        self.assertEqual(self.pip.calls, [])
        self.assertEqual([u.rsplit("/", 1)[-1] for u in self.opener.urls], ["ema.pt", "decoder.pt"])

    def test_network_error_leaves_no_partial_files_and_rolls_back_packages(self):
        opener = FakeOpener(self.payloads, fail={"decoder.pt": urllib.error.URLError("Name or service not known")})
        with self.assertRaises(ema.EmaNetworkError) as ctx:
            self.install(BASE_VERSIONS, opener=opener)
        self.assertIn("ağ hatası", str(ctx.exception))
        self.assertIsInstance(ctx.exception, base.InstallError)
        self.assertFalse(self.folder.exists())          # bu çağrının açtığı klasör de silindi
        # bu çağrının kurduğu paketler geri alındı
        self.assertEqual(self.pip.calls[-1][:2], ["uninstall", "-y"])
        self.assertEqual(sorted(self.pip.calls[-1][2:]), ["ema-lightning", "normalizer-tr"])
        self.assertNotIn("ema-lightning", self.versions.versions)
        self.assertEqual([e.stage for e in self.events][-1], "geri_alma")

    def test_http_error(self):
        err = urllib.error.HTTPError("https://huggingface.co/x", 503, "Service Unavailable", {}, None)
        opener = FakeOpener(self.payloads, fail={"ema.pt": err})
        with self.assertRaises(ema.EmaNetworkError) as ctx:
            self.install(INSTALLED, opener=opener)
        self.assertIn("HTTP 503", str(ctx.exception))
        self.assertFalse(self.folder.exists())

    def test_existing_complete_files_survive_failure(self):
        self.folder.mkdir(parents=True)
        (self.folder / "config.json").write_bytes(self.payloads["config.json"])
        opener = FakeOpener(self.payloads, fail={"decoder.pt": TimeoutError("timed out")})
        with self.assertRaises(ema.EmaNetworkError):
            self.install(INSTALLED, opener=opener)
        self.assert_no_residue(keep=("config.json",))   # önceden tam olan korunur, yeni yarım dosya yok

    def test_truncated_download(self):
        opener = FakeOpener(self.payloads, truncate={"ema.pt"})
        with self.assertRaises(ema.EmaNetworkError) as ctx:
            self.install(INSTALLED, opener=opener)
        self.assertIn("eksik indi", str(ctx.exception))
        self.assertFalse(self.folder.exists())

    def test_checksum_mismatch(self):
        opener = FakeOpener(self.payloads, corrupt={"decoder.pt"})
        with self.assertRaises(base.InstallError) as ctx:
            self.install(INSTALLED, opener=opener)
        self.assertNotIsInstance(ctx.exception, ema.EmaNetworkError)
        self.assertIn("SHA-256", str(ctx.exception))
        self.assertFalse(self.folder.exists())

    def test_cancel_from_progress_callback_mid_download(self):
        def cb(progress):
            self.events.append(progress)
            if progress.stage == "indirme" and progress.file == "ema.pt":
                return False

        with self.assertRaises(base.InstallCancelledError) as ctx:
            self.install(BASE_VERSIONS, progress_cb=cb)
        self.assertIn("iptal", str(ctx.exception))
        self.assertFalse(self.folder.exists())
        self.assertEqual(self.pip.calls[-1][0], "uninstall")
        self.assertNotIn("decoder.pt", [u.rsplit("/", 1)[-1] for u in self.opener.urls])

    def test_cancel_with_event_from_another_thread(self):
        event = threading.Event()

        class SlowOpener(FakeOpener):
            def __call__(self, url, timeout):
                event.set()             # "kullanıcı iptal'e bastı"
                return super().__call__(url, timeout)

        with self.assertRaises(base.InstallCancelledError):
            self.install(INSTALLED, opener=SlowOpener(self.payloads), cancel=event)
        self.assertFalse(self.folder.exists())
        self.assertEqual(self.pip.calls, [])          # paket bu çağrıda kurulmadı → geri alınacak bir şey yok

    def test_cancel_during_pip(self):
        versions = Versions(BASE_VERSIONS)
        pip = FakePip(versions, cancel_on_install=True)
        with self.assertRaises(base.InstallCancelledError):
            self.install(versions, pip=pip)
        self.assertEqual(self.opener.urls, [])
        self.assertEqual(pip.calls[-1][0], "uninstall")

    def test_pip_failure_stops_before_download(self):
        versions = Versions(BASE_VERSIONS)
        with self.assertRaises(base.InstallError) as ctx:
            self.install(versions, pip=FakePip(versions, code=1))
        self.assertIn("pip çıkış kodu 1", str(ctx.exception))
        self.assertEqual(self.opener.urls, [])
        self.assertFalse(self.folder.exists())

    def test_missing_torch_is_not_installed_by_ema(self):
        deps = dict(BASE_VERSIONS)
        deps.pop("torch")
        with self.assertRaises(base.InstallError) as ctx:
            self.install(deps)
        self.assertIn("torch", str(ctx.exception))
        self.assertEqual(self.pip.calls, [])
        self.assertEqual(self.opener.urls, [])

    def test_disk_full(self):
        with self.assertRaises(base.InstallError) as ctx:
            self.install(INSTALLED, disk_usage=lambda _p: SimpleNamespace(free=1000))
        self.assertIn("Diskte yer yetmiyor", str(ctx.exception))
        self.assertEqual(self.opener.urls, [])

    def test_version_upgrade_is_restored_on_failure(self):
        versions = Versions(dict(BASE_VERSIONS, **{"ema-lightning": "1.0.1", "normalizer-tr": "0.4.0"}))
        opener = FakeOpener(self.payloads, fail={"config.json": ConnectionError("reset")})
        with self.assertRaises(ema.EmaNetworkError):
            self.install(versions, opener=opener)
        restore = self.pip.calls[-1]
        self.assertEqual(restore[0], "install")
        self.assertIn("ema-lightning==1.0.1", restore)
        self.assertIn("--no-deps", restore)


class DefaultPipRunnerTests(unittest.TestCase):
    def test_cancel_terminates_process(self):
        class FakeProc:
            def __init__(self, *a, **k):
                self.args = a[0]
                self.stdout = io.StringIO("Collecting ema-lightning\n")
                self.terminated = False

            def poll(self):
                return None

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return -15

        procs = []
        with patch.object(ema.subprocess, "Popen", side_effect=lambda *a, **k: procs.append(FakeProc(*a, **k)) or procs[-1]):
            code, out = ema.default_pip_runner(["install", "--no-deps", "x==1"], lambda: True, poll=0)
        self.assertIsNone(code)
        self.assertTrue(procs[0].terminated)
        self.assertEqual(procs[0].args[:3], [sys.executable, "-m", "pip"])


class UninstallTests(EmaInstallBase):
    def test_removes_only_ema_weights(self):
        self.install(INSTALLED)
        (self.folder / "kullanici-notu.txt").write_text("dokunma")
        (self.folder / f"{ema.TMP_PREFIX}eski").mkdir()
        (self.folder / f"{ema.TMP_PREFIX}eski" / "ema.pt").write_bytes(b"yarim")
        result = ema.ema_uninstall(weights_path=self.folder)
        self.assertEqual(sorted(result["removed"]),
                         sorted(["config.json", "ema.pt", "decoder.pt", ema.MANIFEST, f"{ema.TMP_PREFIX}eski"]))
        self.assertGreaterEqual(result["freed_bytes"], sum(s.size for s in self.specs) + len(b"yarim"))
        self.assert_no_residue(keep=("kullanici-notu.txt",))
        self.assertEqual(self.pip.calls, [])            # paketler kaldırılmaz
        self.assertFalse(self.status().weights_present)

    def test_empty_folder_removed_and_idempotent(self):
        self.install(INSTALLED)
        ema.ema_uninstall(weights_path=self.folder)
        self.assertFalse(self.folder.exists())
        self.assertEqual(ema.ema_uninstall(weights_path=self.folder)["removed"], [])

    def test_symlink_folder_refused(self):
        real = self.root / "baska"
        real.mkdir()
        (real / "ema.pt").write_bytes(b"x")
        self.folder.parent.mkdir(parents=True)
        self.folder.symlink_to(real)
        with self.assertRaises(base.EngineError):
            ema.ema_uninstall(weights_path=self.folder)
        self.assertTrue((real / "ema.pt").exists())

    def test_uninstall_releases_loaded_model(self):
        eng = ema.EmaEngine(output_dir=self.root / "out", weights_path=self.folder,
                            status_fn=lambda **k: ready_status(), loader=lambda f, d: FakeModel())
        eng.synthesize("Merhaba.")
        self.assertIsNotNone(eng._model)
        ema.ema_uninstall(weights_path=self.folder)
        self.assertIsNone(eng._model)


# --- Motor ----------------------------------------------------------------------
Word = SimpleNamespace


class FakeModel:
    def __init__(self, sr=48000):
        self.sr = sr
        self.calls = []

    def say(self, text, speed=1.0, seed=None, sample_rate=48000, path=None):
        self.calls.append({"text": text, "speed": speed, "seed": seed, "sample_rate": sample_rate})
        dur = 1.5 / speed
        t = np.arange(int(dur * sample_rate)) / sample_rate
        audio = (0.4 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        words = (Word(text="merhaba", start=0.04, end=0.52), Word(text="dünya", start=0.6, end=1.1),
                 Word(text="nasılsın", start=1.9, end=2.4))
        return SimpleNamespace(audio=audio, sample_rate=sample_rate, duration=dur,
                               seed=seed if seed is not None else 987654, words=words)

    def stream(self, text, speed=1.0, seed=None, sample_rate=48000):
        for _ in range(3):
            yield np.zeros(sample_rate // 10, dtype=np.float64)


def ready_status(**_kw):
    return SimpleNamespace(ready=True, download_label="~0 B", weights_bytes=1)


def missing_status(**_kw):
    return SimpleNamespace(ready=False, download_label="~35,7 MB", weights_bytes=0)


class EmaEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "outputs"
        self.model = FakeModel()
        self.loads = []
        self.status_calls = []

        def loader(folder, device):
            self.loads.append((folder, device))
            return self.model

        def status_fn(**kw):
            self.status_calls.append(kw)
            return ready_status()

        self.engine = ema.EmaEngine(output_dir=self.out, weights_path=Path(self.tmp.name) / "w", loader=loader,
                                    status_fn=status_fn, device="cpu")

    def test_capabilities(self):
        caps = self.engine.capabilities
        self.assertTrue(caps.local)
        self.assertFalse(caps.description_design)   # tarif = yok
        self.assertFalse(caps.clone)                # klon = yok
        self.assertFalse(caps.instruction)
        self.assertTrue(caps.seed)                  # seed = var
        self.assertTrue(caps.seed_deterministic)    # paket belgesi: aynı seed = aynı ses
        self.assertTrue(caps.speed)                 # hız = var
        self.assertTrue(caps.word_timestamps)       # kelime zamanları = var
        self.assertTrue(caps.streaming)             # akış = var
        self.assertEqual(caps.languages, ("tr",))
        self.assertEqual(caps.quality_modes, ())
        self.assertFalse(caps.metered)
        self.assertFalse(caps.requires_api_key)

    def test_old_engines_keep_capability_defaults(self):
        from engines.voxcpm import VoxCPMEngine
        caps = VoxCPMEngine().capabilities
        self.assertFalse(caps.speed or caps.word_timestamps or caps.streaming)
        self.assertEqual(caps.quality_modes, base.QUALITY_MODES)

    def test_say_to_wav(self):
        res = self.engine.synthesize("Merhaba dünya, nasılsın?", speed=1.5, seed=42)
        self.assertEqual(self.model.calls[-1], {"text": "Merhaba dünya, nasılsın?", "speed": 1.5, "seed": 42,
                                                "sample_rate": 48000})
        info = sf.info(res.path)
        self.assertEqual((info.samplerate, info.channels, info.subtype, info.format), (48000, 1, "PCM_16", "WAV"))
        self.assertEqual(res.sample_rate, 48000)
        self.assertAlmostEqual(info.duration, 1.0, places=2)
        self.assertAlmostEqual(res.meta["duration"], 1.0, places=2)
        data, _ = sf.read(res.path, dtype="float32")
        self.assertAlmostEqual(float(np.abs(data).max()), 0.4, places=2)
        self.assertEqual(res.meta["engine"], "ema")
        self.assertEqual(res.meta["seed"], 42)
        self.assertEqual(res.meta["credits"], 0.0)
        self.assertTrue(Path(res.path).name.startswith("ema-"))
        self.assertEqual([p.name for p in self.out.iterdir() if p.name.startswith(".")], [])  # geçici dosya yok
        self.assertEqual(self.loads, [(Path(self.tmp.name) / "w", "cpu")])
        self.assertTrue(self.status_calls[0]["verify"])   # pickle yüklemeden önce hash doğrulaması

    def test_random_seed_is_reported_for_reproducibility(self):
        res = self.engine.synthesize("Merhaba.")
        self.assertIsNone(self.model.calls[-1]["seed"])
        self.assertEqual(res.meta["seed"], 987654)

    def test_model_loaded_once(self):
        self.engine.synthesize("Bir.")
        self.engine.synthesize("İki.")
        self.assertEqual(len(self.loads), 1)

    def test_srt_from_word_timestamps(self):
        res = self.engine.synthesize("Merhaba dünya, nasılsın?")
        expected = ("1\n00:00:00,040 --> 00:00:01,100\nmerhaba dünya\n\n"
                    "2\n00:00:01,900 --> 00:00:02,400\nnasılsın\n")
        self.assertEqual(res.meta["srt"], expected)
        self.assertEqual(Path(res.meta["srt_path"]).read_text(encoding="utf-8"), expected)
        self.assertEqual(Path(res.meta["srt_path"]).stem, Path(res.path).stem)
        self.assertEqual(res.meta["words"][0], {"text": "merhaba", "start": 0.04, "end": 0.52})

    def test_srt_file_optional(self):
        eng = ema.EmaEngine(output_dir=self.out, loader=lambda f, d: FakeModel(), status_fn=ready_status,
                            write_srt=False)
        res = eng.synthesize("Merhaba.")
        self.assertIsNone(res.meta["srt_path"])
        self.assertTrue(res.meta["srt"])

    def test_design_request_rejected_clearly(self):
        with self.assertRaises(base.NotSupportedError) as ctx:
            self.engine.design_voice("Kalın sesli yaşlı adam", "Merhaba")
        self.assertIn("ses tarifi yok", str(ctx.exception))
        with self.assertRaises(base.NotSupportedError) as ctx:
            self.engine.synthesize("Merhaba", description="Kalın sesli yaşlı adam")
        self.assertIn("ses tarifi yok", str(ctx.exception))
        self.assertEqual(self.loads, [])

    def test_clone_request_rejected_clearly(self):
        with self.assertRaises(base.NotSupportedError) as ctx:
            self.engine.clone_voice("kayit.wav", "metin", consent=True)
        self.assertIn("ses klonu yok", str(ctx.exception))
        for kwargs in ({"reference_audio": "kayit.wav"}, {"prompt_text": "metin"}, {"voice": "yusuf"}):
            with self.assertRaises(base.NotSupportedError) as ctx:
                self.engine.synthesize("Merhaba", **kwargs)
            self.assertIn("ses klonu yok", str(ctx.exception))
        self.assertEqual(self.loads, [])

    def test_instruction_rejected(self):
        with self.assertRaises(base.NotSupportedError) as ctx:
            self.engine.synthesize("Merhaba", instruction="Neşeli")
        self.assertIn("duygu/stil talimatı yok", str(ctx.exception))

    def test_argument_validation(self):
        for kwargs in ({"speed": 5}, {"speed": 0.1}, {"speed": True}, {"seed": -1}, {"seed": 1.5},
                       {"sample_rate": 44100}):
            with self.assertRaises(base.EngineError):
                self.engine.synthesize("Merhaba", **kwargs)
        with self.assertRaises(base.EngineError):
            self.engine.synthesize("   ")
        with self.assertRaises(base.TextTooLongError):
            self.engine.synthesize("a" * (ema.MAX_TEXT_CHARS + 1))
        self.assertEqual(self.loads, [])

    def test_quality_and_default_voice_accepted(self):
        res = self.engine.synthesize("Merhaba", voice="ema", quality="En İyi")
        self.assertIsNone(res.meta["quality"])

    def test_not_installed(self):
        eng = ema.EmaEngine(output_dir=self.out, loader=lambda f, d: self.fail("yüklenmemeli"),
                            status_fn=missing_status)
        with self.assertRaises(base.EngineNotInstalledError) as ctx:
            eng.synthesize("Merhaba")
        self.assertIn("ema_install()", str(ctx.exception))
        self.assertIn("35,7 MB", str(ctx.exception))

    def test_loader_and_model_errors_wrapped(self):
        def boom(folder, device):
            raise RuntimeError("bozuk ağırlık")

        eng = ema.EmaEngine(output_dir=self.out, loader=boom, status_fn=ready_status)
        with self.assertRaises(base.EngineError) as ctx:
            eng.synthesize("Merhaba")
        self.assertIn("yüklenemedi", str(ctx.exception))
        self.model.say = lambda *a, **k: (_ for _ in ()).throw(ValueError("x"))
        with self.assertRaises(base.EngineError):
            self.engine.synthesize("Merhaba")

    def test_stream(self):
        chunks = list(self.engine.stream("Merhaba", speed=1.0, seed=3))
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(c.dtype == np.float32 for c in chunks))
        with self.assertRaises(base.NotSupportedError):
            list(self.engine.stream("Merhaba", instruction="Üzgün"))

    def test_voices_and_usage(self):
        voices = self.engine.list_voices()
        self.assertEqual([v.id for v in voices], ["ema"])
        usage = self.engine.usage()
        self.assertFalse(usage.metered)
        self.assertFalse(usage.can_clone)
        self.assertTrue(usage.extra["installed"])


class EmaSelectionTests(unittest.TestCase):
    def test_env_selects_ema_default_stays_voxcpm(self):
        self.assertIn("ema", engines.ENGINES)
        self.assertEqual(engines.DEFAULT_ENGINE, "voxcpm")
        self.assertEqual(engines.selected_engine_name({}), "voxcpm")
        self.assertEqual(engines.selected_engine_name({"SESVER_ENGINE": " EMA "}), "ema")
        sys.modules.pop("ema_lightning", None)
        with patch.dict(os.environ, {"SESVER_ENGINE": "ema"}):
            eng = engines.get_engine()
        self.assertIsInstance(eng, ema.EmaEngine)
        self.assertNotIn("ema_lightning", sys.modules)   # seçim modeli/paketi yüklemez

    def test_app_untouched_by_ema(self):
        source = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("ema_lightning", source)
        self.assertNotIn("engines", source)

    def test_weights_dir_is_gitignored_and_env_override(self):
        self.assertEqual(ema.DEFAULT_WEIGHTS_DIR.parent.name, "models")
        gitignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("models/", gitignore.splitlines())
        with patch.dict(os.environ, {"SESVER_EMA_DIR": "/tmp/ema-x"}):
            self.assertEqual(ema.weights_dir(), Path("/tmp/ema-x"))

    def test_no_ema_venv_reference(self):
        source = (Path(ema.__file__)).read_text(encoding="utf-8")
        self.assertNotIn(".hermes/tts/ema-venv", source)   # ayrı venv SesVer'e bağlanmaz
        self.assertNotIn("hf_hub_download(", source)


class SrtTests(unittest.TestCase):
    def test_timestamp_format(self):
        self.assertEqual(srt.format_timestamp(0), "00:00:00,000")
        self.assertEqual(srt.format_timestamp(3725.4567), "01:02:05,457")
        self.assertEqual(srt.format_timestamp(-1), "00:00:00,000")

    def test_inputs_and_grouping(self):
        words = [{"text": "bir", "start": 0.0, "end": 0.3}, ("iki.", 0.35, 0.7), Word(text="üç", start=0.75, end=1.0)]
        cues = srt.group_cues(words)
        self.assertEqual([c.text for c in cues], ["bir iki.", "üç"])   # cümle sonu yeni altyazı
        long_words = [(f"kelime{i}", i * 0.3, i * 0.3 + 0.25) for i in range(20)]
        for cue in srt.group_cues(long_words):
            self.assertLessEqual(len(cue.text), srt.MAX_CHARS)
            self.assertLessEqual(cue.end - cue.start, srt.MAX_DURATION)
        self.assertEqual(srt.words_to_srt([]), "")
        self.assertEqual(srt.words_to_srt([("  ", 0, 1)]), "")

    def test_unsorted_and_invalid(self):
        cues = srt.group_cues([("iki", 1.0, 1.2), ("bir", 0.0, 0.5)], max_gap=10)
        self.assertEqual(cues[0].text, "bir iki")
        with self.assertRaises(ValueError):
            srt.group_cues([("ters", 2.0, 1.0)])


if __name__ == "__main__":
    unittest.main()
