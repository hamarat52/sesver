"""Hata raporu (hata_raporu.py): maskeleme, mailto, sınıflandırma, günlük döndürme, gizlilik.

Hiçbir test e-posta göndermez ya da gerçek bir uygulama açmaz: Windows/macOS yolları
(os.startfile, explorer /select, open -R, clip, pbcopy) sahte işlevlerle doğrulanır.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hata_raporu as hr  # noqa: E402

FAKE_SYSTEM = ["SesVer: 1.2.0 (abc1234)", "OS: Windows 11 Home 10.0.22631", "Arch: AMD64",
               "Python: CPython 3.11.9", "Torch: 2.14.1+cu130 (in-process)",
               "CUDA: 13.0 | HIP: - | cuda.is_available: True | mps: False",
               "GPU (torch): NVIDIA GeForce RTX 4060 Laptop GPU | VRAM: 8.0 GB | cc 8.9",
               "RAM: 9.1 GB available / 15.7 GB total", "Disk free (SesVer folder): 120.4 GB", "UI language: tr"]


def _report(tail_lines=0, line="x" * 60, message="boom", **kw):
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "sesver_log.txt"
        log.write_text("\n".join(f"{i:04d} {line}" for i in range(tail_lines)), encoding="utf-8")
        err = {"where": "generate", "code": "other", "reason": "RuntimeError", "type": "RuntimeError",
               "message": message, "traceback": "Traceback...\nRuntimeError: " + message,
               "time": hr.datetime.datetime(2026, 10, 30, 12, 0, 0).astimezone()}
        return hr.build_report(error=err, log_path=log, prev_path=Path(tmp) / "yok.txt", system=FAKE_SYSTEM,
                               now=hr.datetime.datetime(2026, 10, 30, 12, 0, 5).astimezone(), **kw)


class SanitizeTests(unittest.TestCase):
    def test_windows_home_paths(self):
        cases = [
            r'File "C:\Users\Yusuf Hamarat\SesVer\app.py", line 247',
            "File 'C:\\\\Users\\\\yusuf\\\\SesVer\\\\app.py'",  # repr içindeki çift ters bölü
            "C:/Users/yusuf/AppData/Local/huggingface/hub",
            r"d:\users\Yusuf\x.txt",
        ]
        for text in cases:
            with self.subTest(text=text):
                out = hr.sanitize(text, homes=[])
                self.assertIn("<ev>", out)
                self.assertNotIn("Yusuf", out)
                self.assertNotIn("yusuf", out)
        self.assertEqual(hr.sanitize(r"C:\Users\Yusuf\SesVer\app.py", homes=[]), r"<ev>\SesVer\app.py")

    def test_macos_and_linux_home_paths(self):
        self.assertEqual(hr.sanitize("/Users/hamaratbey/Desktop/SesVer/app.py", homes=[]),
                         "<ev>/Desktop/SesVer/app.py")
        self.assertEqual(hr.sanitize("open /home/ali/.cache/x", homes=[]), "open <ev>/.cache/x")
        # Bu makinenin ev dizini (ör. özel bir yol) de maskelenir.
        self.assertEqual(hr.sanitize("/srv/kisi/proje/a.py", homes=["/srv/kisi"]), "<ev>/proje/a.py")

    def test_emails_and_tokens(self):
        text = ("mail ali.veli+test@example.co.uk token hf_AbCdEfGhIjKlMnOpQrSt key sk-proj-1234567890abcdef "
                "HF_TOKEN=hf_zzzzzzzzzzzz password: hunter2secret Authorization: Bearer abc.def.ghi123456 "
                "ghp_0123456789abcdefABCDEF")
        out = hr.sanitize(text, homes=[])
        for secret in ("ali.veli", "example.co.uk", "hf_AbCd", "sk-proj", "hf_zzzz", "hunter2secret",
                       "abc.def.ghi123456", "ghp_0123"):
            self.assertNotIn(secret, out)
        self.assertIn("<e-posta>", out)
        self.assertIn("<anahtar>", out)
        # Sıradan teknik metin bozulmaz.
        plain = "torch 2.14.1+cu130 | CUDA error: out of memory | sesver_log.txt"
        self.assertEqual(hr.sanitize(plain, homes=[]), plain)

    def test_report_is_sanitized(self):
        rep = _report(message=r"cannot open C:\Users\Yusuf\SesVer\x.wav (user yusuf@mail.com, hf_abcdefghijkl)")
        self.assertNotIn("Yusuf", rep["text"])
        self.assertNotIn("yusuf@mail.com", rep["text"])
        self.assertNotIn("hf_abcdefghijkl", rep["text"])
        self.assertIn(r"<ev>\SesVer\x.wav", rep["text"])


class MailtoTests(unittest.TestCase):
    def _parts(self, url):
        self.assertTrue(url.startswith("mailto:"))
        addr, query = url[len("mailto:"):].split("?", 1)
        q = dict(p.split("=", 1) for p in query.split("&"))
        return addr, urllib.parse.unquote(q["subject"]), urllib.parse.unquote(q["body"])

    def test_recipient_subject_and_attachment_note(self):
        rep = _report(tail_lines=3)
        url = hr.mailto_url(rep)
        addr, subject, body = self._parts(url)
        self.assertEqual(addr, "premium.hamarat@gmail.com")
        self.assertEqual(hr.DESTEK_EPOSTA, "premium.hamarat@gmail.com")
        self.assertRegex(subject, r"^SesVer hata raporu \S+.* \((Windows|macOS|Linux)\b.*\)$")
        self.assertEqual(rep["filename"], "SesVer-hata-raporu-20261030-120005.txt")
        self.assertIn("SesVer-hata-raporu-20261030-120005.txt", body)
        self.assertIn("dosyasını bu e-postaya ekleyin", body)
        self.assertIn("RuntimeError: boom", body)
        self.assertIn("0002 " + "x" * 60, body)
        self.assertNotIn("(tam rapor ekte)", body)  # sığdı: kırpma yok
        self.assertIn("%0D%0A", url)  # RFC 6068 satır sonu

    def test_long_log_is_trimmed_to_limit_keeping_newest_lines(self):
        rep = _report(tail_lines=300)
        url = hr.mailto_url(rep)
        self.assertLessEqual(len(url), 1800)
        _addr, _subject, body = self._parts(url)
        self.assertIn("(tam rapor ekte)", body)
        self.assertIn("0299 ", body)  # en yeni satır kalır
        self.assertNotIn("0000 ", body)  # en eski atılır
        self.assertIn("UI language: tr", body)  # özet korunur
        # Tam rapor hepsini içerir (dosyaya yazılan).
        self.assertIn("0000 ", rep["text"])
        for limit in (600, 1000, 1800):
            self.assertLessEqual(len(hr.mailto_url(rep, limit=limit)), limit)

    def test_huge_error_message_still_fits(self):
        rep = _report(tail_lines=50, message="ğüşiöç " * 600)
        url = hr.mailto_url(rep)
        self.assertLessEqual(len(url), 1800)
        _addr, _subject, body = self._parts(url)
        self.assertIn("(tam rapor ekte)", body)
        self.assertIn("SesVer-hata-raporu-", body)


class ClassifyTests(unittest.TestCase):
    def test_known_error_kinds(self):
        class OutOfMemoryError(RuntimeError):  # torch.OutOfMemoryError taklidi
            pass

        class LocalEntryNotFoundError(Exception):  # huggingface_hub taklidi
            pass

        cases = [
            (OutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB (GPU 0; 8.00 GiB total)"), "cuda_oom"),
            (RuntimeError("CUDA error: out of memory"), "cuda_oom"),
            (RuntimeError("CUDA error: no kernel image is available for execution on the device\n"
                          "CUDA kernel errors might be asynchronously reported"), "cuda_kernel"),
            (MemoryError(), "ram"),
            (RuntimeError("[enforce fail at alloc_cpu.cpp:117] DefaultCPUAllocator: not enough memory"), "ram"),
            (LocalEntryNotFoundError("Cannot find the requested files in the disk cache"), "download"),
            (ConnectionError("HTTPSConnectionPool(host='huggingface.co'): Max retries exceeded"), "download"),
            (OSError(28, "No space left on device"), "disk"),
            (RuntimeError("MPS backend out of memory"), "gpu_oom"),
            (ValueError("something odd"), "other"),
        ]
        for exc, code in cases:
            with self.subTest(exc=repr(exc)[:60]):
                got, reason = hr.classify_error(exc)
                self.assertEqual(got, code)
                self.assertTrue(reason)
        self.assertEqual(hr.classify_error(ValueError("x")), ("other", "ValueError"))
        self.assertEqual(hr.classify_error("KeyError: 'abc'")[1], "KeyError")
        self.assertEqual(hr.classify_error("CUDA error: no kernel image is available")[0], "cuda_kernel")

    def test_chained_cause_is_used_and_reason_is_translated(self):
        try:
            try:
                raise MemoryError()
            except MemoryError as inner:
                raise RuntimeError("model yüklenemedi") from inner
        except RuntimeError as exc:
            self.assertEqual(hr.classify_error(exc)[0], "ram")
        with hr_lang("en"):
            self.assertEqual(hr.classify_error(MemoryError())[1], "not enough memory (RAM)")
        self.assertEqual(hr.classify_error(MemoryError())[1], "bellek (RAM) yetersiz")


@contextlib.contextmanager
def hr_lang(lang):
    import i18n
    with i18n.use(lang):
        yield


class LogRotationTests(unittest.TestCase):
    def test_previous_log_is_kept_single_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, prev = Path(tmp) / "sesver_log.txt", Path(tmp) / "sesver_log_onceki.txt"
            self.assertFalse(hr.rotate_log(log, prev))  # ilk açılış: günlük yok
            log.write_text("oturum 1\nTraceback (most recent call last):\nRuntimeError: x\n", encoding="utf-8")
            self.assertTrue(hr.rotate_log(log, prev))
            self.assertFalse(log.exists())
            self.assertIn("oturum 1", prev.read_text(encoding="utf-8"))
            self.assertTrue(hr.log_has_error(prev))
            log.write_text("oturum 2 temiz\n", encoding="utf-8")
            self.assertTrue(hr.rotate_log(log, prev))
            self.assertEqual(prev.read_text(encoding="utf-8"), "oturum 2 temiz\n")  # tek kopya
            self.assertFalse(hr.log_has_error(prev))
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["sesver_log_onceki.txt"])
            log.write_text("", encoding="utf-8")  # boş günlük önceki kanıtın üzerine yazılmaz
            self.assertFalse(hr.rotate_log(log, prev))
            self.assertEqual(prev.read_text(encoding="utf-8"), "oturum 2 temiz\n")

    def test_desktop_rotates_before_truncating(self):
        import desktop
        with tempfile.TemporaryDirectory() as tmp:
            log, prev = os.path.join(tmp, "sesver_log.txt"), os.path.join(tmp, "sesver_log_onceki.txt")
            Path(log).write_text("onceki oturum: Üretim başarısız\n", encoding="utf-8")
            with mock.patch.object(desktop, "LOG_PATH", log), mock.patch.object(desktop, "PREV_LOG_PATH", prev), \
                    mock.patch.object(sys, "stdout", io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()), \
                    mock.patch.object(sys, "excepthook", sys.excepthook), mock.patch.object(desktop.atexit, "register"):
                desktop._setup_log_file()
                sys.stdout.flush()
                sys.stdout._log.close()
            self.assertEqual(Path(prev).read_text(encoding="utf-8"), "onceki oturum: Üretim başarısız\n")
            self.assertIn("SesVer günlüğü", Path(log).read_text(encoding="utf-8"))

    def test_report_can_include_previous_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, prev = Path(tmp) / "sesver_log.txt", Path(tmp) / "sesver_log_onceki.txt"
            log.write_text("simdiki\n", encoding="utf-8")
            prev.write_text("eski hata satiri\n", encoding="utf-8")
            kw = dict(error={}, log_path=log, prev_path=prev, system=FAKE_SYSTEM)
            self.assertNotIn("eski hata satiri", hr.build_report(**kw)["text"])
            text = hr.build_report(include_previous=True, **kw)["text"]
            self.assertIn("eski hata satiri", text)
            self.assertIn("sesver_log_onceki.txt (previous session", text)


class PrivacyTests(unittest.TestCase):
    """Üretim metnini içeren sahte bir hata akışında metin ne günlüğe ne rapora girer."""

    SECRET = "Gizli müşteri cümlesi 4711. Bu ikinci cümle de kimseye gitmemeli"

    def test_user_text_never_reaches_log_or_report(self):
        import app
        second = self.SECRET.split(". ")[1]
        failing = RuntimeError(f"tokenizer failed on {self.SECRET!r}; last chunk: {second}")
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "sesver_log.txt"
            with open(log, "w", encoding="utf-8") as fh, contextlib.redirect_stderr(fh), \
                    mock.patch.object(app, "get_model", side_effect=failing):
                events = list(app.generate_audio(self.SECRET, None))
            status = events[-1][2]
            self.assertIn("RuntimeError", status)  # gerçek hata türü kullanıcıya söylenir
            self.assertIn("sesver_log.txt", status)
            self.assertNotIn("terminalde", status)
            logged = log.read_text(encoding="utf-8")
            self.assertIn("Traceback", logged)
            self.assertIn("<metin>", logged)
            report = hr.build_report(log_path=log, prev_path=Path(tmp) / "yok", system=FAKE_SYSTEM)
            url = hr.mailto_url(report)
            for blob in (logged, report["text"], urllib.parse.unquote(url), hr.clipboard_text(report)):
                self.assertNotIn("4711", blob)
                self.assertNotIn("Gizli müşteri", blob)
                self.assertNotIn("kimseye gitmemeli", blob)
            self.assertIn("RuntimeError: tokenizer failed on", report["text"])
            self.assertEqual(hr.last_error()["code"], "other")

    def test_generation_status_names_cuda_error(self):
        import app
        with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(
                app, "get_model", side_effect=RuntimeError("CUDA error: no kernel image is available for "
                                                             "execution on the device")):
            before = hr.error_count()
            status = list(app.generate_audio("Merhaba", None))[-1][2]
        self.assertIn("CUDA çekirdeği bu kartta yok", status)
        self.assertEqual(hr.error_count(), before + 1)


class PlatformActionTests(unittest.TestCase):
    """Windows yolları bu Mac'te çalıştırılamaz: komutlar sahte işlevlerle doğrulanır."""

    def test_windows_reveal_mailto_and_clipboard(self):
        calls = []
        self.assertTrue(hr.reveal(r"C:\SesVer\hata_raporlari\r.txt", platform_name="win32",
                                  popen=lambda cmd: calls.append(cmd)))
        self.assertEqual(calls, [["explorer", r"/select,C:\SesVer\hata_raporlari\r.txt"]])
        opened = []
        self.assertTrue(hr.open_mailto("mailto:x@y.z?subject=a", platform_name="win32", startfile=opened.append))
        self.assertEqual(opened, ["mailto:x@y.z?subject=a"])

        def no_client(url):
            raise OSError("Bu işlem için ilişkilendirilmiş uygulama yok")
        self.assertFalse(hr.open_mailto("mailto:x", platform_name="win32", startfile=no_client))
        got = {}

        def run(cmd, **kw):
            got.update(cmd=cmd, **kw)
            return mock.Mock(returncode=0)
        self.assertTrue(hr.copy_to_clipboard("Alıcı ğ", platform_name="win32", run=run))
        self.assertEqual(got["cmd"], ["clip"])
        self.assertEqual(got["input"], "\ufeffAlıcı ğ".encode("utf-16-le"))
        self.assertIn("creationflags", got)

    def test_macos_reveal_mailto_and_clipboard(self):
        calls = []
        hr.reveal("/tmp/r.txt", platform_name="darwin", popen=lambda cmd: calls.append(cmd))
        self.assertEqual(calls, [["open", "-R", "/tmp/r.txt"]])
        ran = []
        ok = hr.open_mailto("mailto:a@b.c", platform_name="darwin",
                            run=lambda cmd, **kw: ran.append(cmd) or mock.Mock(returncode=0))
        self.assertTrue(ok)
        self.assertEqual(ran, [["open", "mailto:a@b.c"]])
        self.assertFalse(hr.open_mailto("mailto:a@b.c", platform_name="darwin",
                                        run=lambda cmd, **kw: mock.Mock(returncode=1)))
        ran.clear()
        hr.copy_to_clipboard("x", platform_name="darwin", run=lambda cmd, **kw: ran.append(cmd) or mock.Mock(returncode=0))
        self.assertEqual(ran, [["pbcopy"]])

    def test_send_saves_reveals_and_opens_draft_only(self):
        rep = _report(tail_lines=5)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(hr, "reveal") as reveal, \
                mock.patch.object(hr, "open_mailto", return_value=True) as open_mailto:
            path, opened = hr.send(rep, directory=tmp)
            self.assertTrue(opened)
            self.assertEqual(path.name, "SesVer-hata-raporu-20261030-120005.txt")
            self.assertRegex(path.name, r"^SesVer-hata-raporu-\d{8}-\d{6}\.txt$")
            self.assertEqual(path.read_text(encoding="utf-8"), rep["text"])
            reveal.assert_called_once_with(path)
            self.assertTrue(open_mailto.call_args[0][0].startswith("mailto:premium.hamarat@gmail.com?subject="))
        self.assertIn("premium.hamarat@gmail.com", hr.clipboard_text(rep))


class SystemInfoTests(unittest.TestCase):
    def test_system_lines_have_required_fields(self):
        fake_torch = {"source": "subprocess", "version": "2.14.1+cu130", "cuda": "13.0", "hip": None,
                      "cuda_ok": True, "mps_ok": False, "device_name": "NVIDIA GeForce RTX 4060",
                      "vram_total": 8 * 1024 ** 3}
        fake_hw = {"system": "Windows", "machine": "amd64", "nvidia_smi": True,
                   "gpus": [{"vendor": "nvidia", "name": "NVIDIA GeForce RTX 4060", "driver": "581.15",
                             "compute_cap": 8.9}]}
        with mock.patch.object(hr, "torch_info", return_value=fake_torch), \
                mock.patch.object(hr, "gpu_info", return_value=fake_hw):
            text = "\n".join(hr.system_lines())
        for needle in ("SesVer:", "OS:", "Arch:", "Python:", "Torch: 2.14.1+cu130", "CUDA: 13.0",
                       "cuda.is_available: True", "NVIDIA GeForce RTX 4060", "VRAM: 8.0 GB", "driver 581.15",
                       "Disk free", "UI language:"):
            self.assertIn(needle, text)

    def test_torch_is_not_imported_by_module(self):
        src = (ROOT / "hata_raporu.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"(?m)^\s*(import torch|from torch)")
        self.assertEqual(src.count("premium.hamarat@gmail.com"), 1)  # alıcı tek yerde tanımlı


class UiTests(unittest.TestCase):
    def test_desktop_error_page_has_report_flow(self):
        import desktop
        entry = hr.record_text_error("MemoryError: yapay", "Traceback ...\nMemoryError: yapay", where="startup")
        self.assertEqual((entry["type"], entry["message"], entry["code"]), ("MemoryError", "yapay", "ram"))
        page = desktop._report_html()
        for needle in ("Hata raporu gönder", "E-posta uygulamasında aç", "Panoya kopyala",
                       "metnim ve seslerim dahil değil", "premium.hamarat@gmail.com", "pywebview.api"):
            self.assertIn(needle, page)
        self.assertNotRegex(page, r"\{(send|consent|details|prev|mail|copy|to|wait|noapi|title)\}")
        api = desktop.ReportApi()
        self.assertIn("raporu hazırlayın", api.eposta())  # önizleme olmadan taslak açılmaz
        with mock.patch.object(hr, "system_lines", return_value=FAKE_SYSTEM):
            data = api.hazirla(False)
        self.assertIn("SesVer error report", data["text"])
        with mock.patch.object(hr, "send", return_value=(Path("/tmp/r.txt"), True)) as send:
            self.assertIn("E-posta taslağı açıldı", api.eposta())
            send.assert_called_once()

    def test_launchers_tell_where_to_send_log(self):
        bat = (ROOT / "WINDOWS_BASLAT.bat").read_bytes()
        line = b"echo Sorun surerse sesver_log.txt dosyasini premium.hamarat@gmail.com adresine gonderin.\r\n"
        self.assertEqual(bat.count(line), 2)  # :baslat_durum ve :hata
        line.decode("ascii")  # eklenen satır ASCII (bat'ın echo satırlarında Türkçe karakter yok)
        sh = (ROOT / "macos_ortak.sh").read_text(encoding="utf-8")
        self.assertEqual(sh.count("premium.hamarat@gmail.com adresine gönderin."), 2)

    def test_settings_and_result_cards_have_report_button(self):
        import app
        demo = app.build_app()
        labels = [c["props"].get("value") for c in demo.config["components"] if c.get("type") == "button"]
        self.assertGreaterEqual(labels.count("Hata raporu gönder"), 4)  # ayarlar + 3 sonuç kartı (TR sayfa)
        self.assertIn("Send error report", labels)
        # Yarış önlemi: üretim, düğmeyi gizleyen/sayacı alan adımdan SONRA zincirlenir; ardından göster adımı gelir.
        deps = demo.config["dependencies"]
        btn = {c["id"] for c in demo.config["components"]
               if c.get("type") == "button" and c["props"].get("value") == "Hata raporu gönder"}
        for api in ("generate_audio", "clone_audio"):
            gen = next(i for i, d in enumerate(deps) if d.get("api_name") == api)
            hide = deps[deps[gen]["trigger_after"]]
            self.assertFalse(hide["queue"])
            self.assertTrue(btn & set(hide["outputs"]))
            show = [d for d in deps if d.get("trigger_after") == gen and btn & set(d["outputs"])]
            self.assertEqual(len(show), 1)
        with mock.patch.object(hr, "system_lines", return_value=FAKE_SYSTEM):
            box, prev, text, report, msg = app.report_open_ui()
        self.assertTrue(box["visible"])
        self.assertIn("SesVer error report", text)
        self.assertEqual(report["text"], text)


class DuplicatePrefixTests(unittest.TestCase):
    """Başlatma hatası satırı tür adını iki kez yazmasın ("MemoryError: MemoryError: …")."""

    def test_exc_line_does_not_repeat_type(self):
        class _ArrayMemoryError(MemoryError):  # numpy.core._exceptions._ArrayMemoryError taklidi
            pass

        cases = [
            (MemoryError("Unable to allocate 2 GiB"), "MemoryError: Unable to allocate 2 GiB"),
            (MemoryError("MemoryError: Unable to allocate 2 GiB"), "MemoryError: Unable to allocate 2 GiB"),
            (MemoryError("MemoryError: MemoryError: x"), "MemoryError: x"),
            (MemoryError("builtins.MemoryError: x"), "MemoryError: x"),
            (MemoryError(), "MemoryError"),
            (MemoryError("MemoryError"), "MemoryError"),
            (RuntimeError("MemoryError: x"), "RuntimeError: MemoryError: x"),  # farklı tür: zincir bilgisi kalır
            (RuntimeError("MemoryErrorish: x"), "RuntimeError: MemoryErrorish: x"),
            (_ArrayMemoryError("Unable to allocate"), "_ArrayMemoryError: Unable to allocate"),
        ]
        for exc, want in cases:
            with self.subTest(exc=repr(exc)):
                self.assertEqual(hr.exc_line(exc), want)

    def test_record_text_error_splits_type_once(self):
        cases = [
            ("MemoryError: MemoryError: x", ("MemoryError", "x")),
            ("MemoryError: ", ("MemoryError", "")),
            ("MemoryError", ("MemoryError", "")),
            ("torch.OutOfMemoryError: CUDA out of memory", ("OutOfMemoryError", "CUDA out of memory")),
            ("_ArrayMemoryError: Unable to allocate", ("_ArrayMemoryError", "Unable to allocate")),
            ("RuntimeError: MemoryError while loading", ("RuntimeError", "MemoryError while loading")),
            ("Sunucu 120 sn içinde başlatılamadı.", ("Error", "Sunucu 120 sn içinde başlatılamadı.")),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                entry = hr.record_text_error(text, "", where="startup")
                self.assertEqual((entry["type"], entry["message"]), want)
                self.assertNotIn(f"{want[0]}: {want[0]}", f"{entry['type']}: {entry['message']}")

    def test_desktop_startup_error_shows_type_once(self):
        import desktop

        class FakeWindow:
            html = ""

            def load_html(self, page):
                self.html = page

        server = desktop.Server(0)
        with mock.patch.object(desktop.app, "build_app",
                               side_effect=MemoryError("MemoryError: Unable to allocate 2.00 GiB")):
            server._run()
        self.assertEqual(server.error, "MemoryError: Unable to allocate 2.00 GiB")
        window = FakeWindow()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            desktop._load_ui(window, server)
        self.assertIn("MemoryError: Unable to allocate 2.00 GiB", window.html)
        self.assertNotIn("MemoryError: MemoryError", window.html)
        err = hr.last_error()
        assert err is not None
        self.assertEqual((err["type"], err["message"], err["code"]), ("MemoryError", "Unable to allocate 2.00 GiB", "ram"))
        with tempfile.TemporaryDirectory() as tmp:
            text = hr.build_report(error=err, log_path=Path(tmp) / "yok.txt", prev_path=Path(tmp) / "yok2.txt",
                                   system=FAKE_SYSTEM)["text"]
        summary = text.split("--- Traceback ---")[0]  # traceback'in son satırı Python'un ham çıktısıdır
        self.assertIn("Error: MemoryError: Unable to allocate 2.00 GiB", summary)
        self.assertNotIn("MemoryError: MemoryError", summary)


if __name__ == "__main__":
    unittest.main()
