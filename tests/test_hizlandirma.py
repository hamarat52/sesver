"""Ekran kartı hızlandırma: algılama ayrıştırıcıları, plan kararları ve kurulum komutu.

Gerçek NVIDIA/AMD donanımı olmadan sınanır: komut çıktıları sahte ``runner``/``which``
ile enjekte edilir. Son sınıf bu makinedeki gerçek algılamayı da çalıştırır.
"""
import os
import platform
import sys
import tempfile
import unittest
import io
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hizlandirma as h  # noqa: E402

NVIDIA_SMI = "NVIDIA GeForce RTX 3080, 581.57, 8.6\n"
NVIDIA_SMI_OLD = "NVIDIA GeForce GTX 1080, 531.79\n"
LSPCI_AMD = (
    "00:02.0 Host bridge [0600]: Intel Corporation Device [8086:a700]\n"
    "03:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. [AMD/ATI] "
    "Navi 31 [Radeon RX 7900 XTX] [1002:744c] (rev c8)\n"
    "03:00.1 Audio device [0403]: Advanced Micro Devices, Inc. [AMD/ATI] Navi 31 HDMI [1002:ab30]\n"
)
LSPCI_NVIDIA = ("01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA102 "
                "[GeForce RTX 3080] [10de:2206] (rev a1)\n")
WMIC = "Name\r\nAMD Radeon RX 6700 XT\r\nMicrosoft Basic Display Adapter\r\n\r\n"
PWSH = "NVIDIA GeForce RTX 4070\nIntel(R) UHD Graphics 770\n"

CPU_TORCH = {"version": "2.14.1+cpu", "cuda": None, "hip": None, "cuda_ok": False, "mps_ok": False}
CUDA_TORCH = {"version": "2.14.1+cu130", "cuda": "13.0", "hip": None, "cuda_ok": True, "mps_ok": False,
              "device_name": "NVIDIA GeForce RTX 3080"}
ROCM_TORCH = {"version": "2.14.1+rocm7.2", "cuda": None, "hip": "7.2.0", "cuda_ok": True, "mps_ok": False}


def fake(outputs, tools=()):
    """runner: komutun ilk öğesine göre sahte çıktı (yoksa None = komut başarısız)."""
    calls = []

    def runner(cmd, timeout=15):
        calls.append(cmd)
        out = outputs.get(cmd[0])
        return out(cmd) if callable(out) else out

    return runner, (lambda name: f"/usr/bin/{name}" if name in tools else None), calls


class ParserTests(unittest.TestCase):
    def test_nvidia_smi(self):
        gpus = h.parse_nvidia_smi(NVIDIA_SMI + "NVIDIA RTX A6000, 581.57, 8.6\n")
        self.assertEqual([g["name"] for g in gpus], ["NVIDIA GeForce RTX 3080", "NVIDIA RTX A6000"])
        self.assertEqual(gpus[0]["driver"], "581.57")
        self.assertEqual(gpus[0]["compute_cap"], 8.6)
        self.assertEqual(h.parse_nvidia_smi(""), [])
        self.assertEqual(h.parse_nvidia_smi("No devices were found\n"), [])
        self.assertIsNone(h.parse_nvidia_smi(NVIDIA_SMI_OLD)[0]["compute_cap"])

    def test_lspci_keeps_only_display_devices(self):
        gpus = h.parse_lspci(LSPCI_AMD)
        self.assertEqual(len(gpus), 1)  # host bridge ve HDMI ses aygıtı sayılmaz
        self.assertEqual(gpus[0]["vendor"], h.AMD)
        self.assertIn("Radeon RX 7900 XTX", gpus[0]["name"])
        self.assertNotIn("1002:744c", gpus[0]["name"])
        self.assertEqual(h.parse_lspci(LSPCI_NVIDIA)[0]["vendor"], h.NVIDIA)

    def test_windows_names_and_vendor(self):
        names = h.parse_windows_names(WMIC)
        self.assertEqual(names, ["AMD Radeon RX 6700 XT", "Microsoft Basic Display Adapter"])
        self.assertEqual([h.vendor_of(n) for n in names], [h.AMD, h.OTHER])
        self.assertEqual(h.vendor_of("NVIDIA GeForce RTX 4070"), h.NVIDIA)
        self.assertEqual(h.vendor_of("Intel(R) UHD Graphics 770"), h.INTEL)
        self.assertEqual(h.vendor_of("Radeon RX 580 Series"), h.AMD)

    def test_sysfs_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            for card, vid in (("card0", "0x1002"), ("card1", "0x1af4")):
                d = Path(tmp, card, "device")
                d.mkdir(parents=True)
                (d / "vendor").write_text(vid + "\n")
            gpus = h.sysfs_gpus(tmp)
        self.assertEqual([g["vendor"] for g in gpus], [h.AMD])  # 0x1af4 (sanal) atlanır

    def test_progress_and_versions(self):
        self.assertEqual(h.parse_progress("Progress 262144 of 5388483\n"), (262144, 5388483))
        self.assertIsNone(h.parse_progress("Collecting torch"))
        listing = ('<a href="/whl/cu130/torch-2.9.1%2Bcu130-cp311-cp311-win_amd64.whl">'
                   '<a href="/whl/cu130/torch-2.14.1%2Bcu130-cp311-cp311-win_amd64.whl">'
                   '<a href="/whl/cu130/torch-2.14.1%2Bcu130-cp312-cp312-win_amd64.whl">'
                   '<a href="/whl/cu130/torch-2.14.0%2Bcu130-cp311-cp311-manylinux_2_28_x86_64.whl">')
        self.assertEqual(h.wheel_versions(listing, "torch", "cu130", "cp311", "win_amd64"), ["2.9.1", "2.14.1"])
        self.assertEqual(h.pick_version(["2.9.1", "2.14.1"], "2.14.1+cpu"), "2.14.1")
        self.assertEqual(h.pick_version(["2.9.1", "2.14.1"], "2.20.0"), "2.14.1")
        self.assertIsNone(h.pick_version(["2.4.1"], None))  # VoxCPM2 torch>=2.5 ister


class DetectTests(unittest.TestCase):
    def test_no_gpu_linux(self):
        runner, which, _ = fake({"lspci": "00:02.0 Host bridge [0600]: Intel [8086:a700]\n"})
        hw = h.detect("Linux", "x86_64", runner, which, sysfs_root="/yok")
        self.assertEqual(hw["gpus"], [])
        self.assertFalse(hw["nvidia_smi"])
        self.assertEqual(h.plan(hw, CPU_TORCH)["durum"], h.NO_GPU)

    def test_nvidia_windows(self):
        runner, which, calls = fake({"nvidia-smi": NVIDIA_SMI, "powershell": PWSH}, tools=("nvidia-smi",))
        hw = h.detect("Windows", "AMD64", runner, which)
        self.assertEqual([g["name"] for g in hw["gpus"]], ["NVIDIA GeForce RTX 3080", "Intel(R) UHD Graphics 770"])
        self.assertTrue(hw["nvidia_smi"])
        p = h.plan(hw, CPU_TORCH)
        self.assertEqual((p["durum"], p["hedef"], p["etiket"]), (h.INSTALL, "cuda", h.CUDA_NEW))
        self.assertIn("compute_cap", calls[0][-1])

    def test_nvidia_old_driver_uses_cu126_or_asks_update(self):
        def smi(cmd):  # eski nvidia-smi compute_cap alanını tanımaz → yedek sorgu
            return None if "compute_cap" in cmd[-1] else NVIDIA_SMI_OLD
        runner, which, _ = fake({"nvidia-smi": smi, "powershell": ""}, tools=("nvidia-smi",))
        hw = h.detect("Windows", "AMD64", runner, which)
        p = h.plan(hw, CPU_TORCH)
        self.assertEqual((p["durum"], p["etiket"]), (h.INSTALL, h.CUDA_OLD))  # 531 < 580
        hw["gpus"][0]["driver"] = "472.12"
        p = h.plan(hw, CPU_TORCH)
        self.assertEqual((p["durum"], p["surucu"]), (h.DRIVER_OLD, "472.12"))
        hw["gpus"][0].update(driver="581.57", compute_cap=6.1)  # Pascal: cu130 desteklemez
        self.assertEqual(h.plan(hw, CPU_TORCH)["etiket"], h.CUDA_OLD)

    def test_nvidia_card_without_driver(self):
        runner, which, _ = fake({"lspci": LSPCI_NVIDIA})
        hw = h.detect("Linux", "x86_64", runner, which)
        self.assertEqual(h.plan(hw, CPU_TORCH)["durum"], h.NO_DRIVER)

    def test_amd_windows_is_explained_not_installed(self):
        runner, which, _ = fake({"wmic": WMIC})  # PowerShell yok → wmic yedeği
        hw = h.detect("Windows", "AMD64", runner, which)
        self.assertEqual(hw["gpus"][0]["vendor"], h.AMD)
        p = h.plan(hw, CPU_TORCH)
        self.assertEqual((p["durum"], p["etiket"]), (h.AMD_WINDOWS, None))

    def test_amd_linux_rocm(self):
        runner, which, _ = fake({"lspci": LSPCI_AMD})
        hw = h.detect("Linux", "x86_64", runner, which)
        p = h.plan(hw, CPU_TORCH)
        self.assertEqual((p["durum"], p["hedef"], p["etiket"]), (h.INSTALL, "rocm", h.ROCM))
        p = h.plan(hw, ROCM_TORCH)
        self.assertEqual((p["durum"], p["hedef"]), (h.ACTIVE, "rocm"))
        self.assertEqual(h.active_backend(ROCM_TORCH), "rocm")
        self.assertEqual(h.plan(dict(hw, machine="aarch64"), CPU_TORCH)["durum"], h.PLATFORM)

    def test_active_and_broken_cuda(self):
        runner, which, _ = fake({"nvidia-smi": NVIDIA_SMI, "lspci": LSPCI_NVIDIA}, tools=("nvidia-smi",))
        hw = h.detect("Linux", "x86_64", runner, which)
        self.assertEqual(len(hw["gpus"]), 1)  # lspci'deki aynı NVIDIA kart tekrarlanmaz
        p = h.plan(hw, CUDA_TORCH)
        self.assertEqual((p["durum"], p["gpu"]), (h.ACTIVE, "NVIDIA GeForce RTX 3080"))
        broken = dict(CUDA_TORCH, cuda_ok=False)
        self.assertEqual(h.plan(hw, broken)["durum"], h.BROKEN)  # yeniden kurulum döngüsü yok

    def test_mac_untouched(self):
        runner, which, calls = fake({})
        hw = h.detect("Darwin", "arm64", runner, which)
        self.assertEqual(calls, [])  # Mac'te hiçbir komut çalıştırılmaz
        mps = dict(CPU_TORCH, version="2.14.1", mps_ok=True)
        self.assertEqual(h.active_backend(mps), "mps")
        self.assertEqual(h.plan(hw, mps)["durum"], h.MAC)
        self.assertEqual(h.plan(h.detect("Darwin", "x86_64", runner, which), CPU_TORCH)["gpu"], None)

    def test_missing_tools_never_raise(self):
        runner, which, _ = fake({})
        for system in ("Windows", "Linux"):
            hw = h.detect(system, "x86_64", runner, which, sysfs_root="/yok")
            self.assertEqual(h.plan(hw, CPU_TORCH)["durum"], h.NO_GPU)
        self.assertIsNone(h.run(["sesver-olmayan-komut-xyz"]))
        self.assertIsNone(h.build_of({"error": "ModuleNotFoundError"}))
        self.assertIsNone(h.active_backend(None))


class InstallTests(unittest.TestCase):
    def test_resolve_keeps_installed_versions(self):
        cp = f"cp{sys.version_info[0]}{sys.version_info[1]}"
        plat = "win_amd64" if os.name == "nt" else "manylinux_2_28_x86_64"

        def fetch(tag, package):
            versions = {"torch": ["2.13.0", "2.14.1"], "torchaudio": ["2.10.0", "2.11.0"]}[package]
            return "".join(f"{package}-{v}%2B{tag}-{cp}-{cp}-{plat}.whl " for v in versions)

        self.assertEqual(h.resolve("cu130", {"torch": "2.14.1", "torchaudio": "2.11.0"}, fetch),
                         ("2.14.1", "2.11.0"))
        # torchaudio'nun aynı sürümü yoksa ona dokunulmaz
        self.assertEqual(h.resolve("cu130", {"torch": "2.14.1", "torchaudio": "2.9.0"}, fetch), ("2.14.1", None))
        # cu128 (Blackwell): resolve/wheel_versions etiket parametreli, cu128'i de taniyor
        # (kurulu surum listede yoksa en yenisi secilir, cu130/cu126 ile ayni davranis).
        self.assertEqual(h.resolve("cu128", {"torch": "2.9.1"}, fetch), ("2.14.1", None))

    def test_install_command(self):
        cmd = h.install_command("cu130", "2.14.1", "2.11.0", python="py", pip_version="26.2.1")
        self.assertEqual(cmd[:6], ["py", "-m", "pip", "install", "torch==2.14.1+cu130", "torchaudio==2.11.0+cu130"])
        self.assertIn("https://download.pytorch.org/whl/cu130", cmd)
        self.assertEqual(cmd[-2:], ["--progress-bar", "raw"])
        self.assertNotIn("raw", h.install_command("cpu", "2.14.1", None, python="py", pip_version="23.0"))


class KernelTestTests(unittest.TestCase):
    """Blackwell (sm_120) + cu126 gibi durumlar: cuda_ok True ama gerçek çekirdek yok."""

    def test_active_backend_requires_kernel_ok(self):
        cuda_ok_but_broken = dict(CUDA_TORCH, cuda_kernel_ok=False)
        self.assertEqual(h.active_backend(cuda_ok_but_broken), "cpu")
        self.assertEqual(h.active_backend(CUDA_TORCH), "cuda")  # alan hiç yoksa (eski kayıt) geriye dönük uyumlu

    def test_plan_falls_back_to_broken_when_kernel_missing(self):
        runner, which, _ = fake({"nvidia-smi": NVIDIA_SMI, "lspci": LSPCI_NVIDIA}, tools=("nvidia-smi",))
        hw = h.detect("Linux", "x86_64", runner, which)
        blackwell_cu126 = dict(CUDA_TORCH, cuda="12.6", cuda_kernel_ok=False,
                               cuda_kernel_error="RuntimeError: CUDA error: no kernel image is available")
        p = h.plan(hw, blackwell_cu126)
        self.assertEqual(p["durum"], h.BROKEN)  # "kuruldu" denip sonra her uretimde patlamasindansa acikca soylenir

    def test_probe_script_runs_a_real_op_not_just_is_available(self):
        # _PROBE ayri bir surecte calisir (gercek CUDA olmadan calistirilamaz); burada
        # yalniz is_available() ile yetinmedigini, gercek bir islemi dogruladigini sinariz.
        self.assertIn("cuda_kernel_ok", h._PROBE)
        self.assertIn("torch.cuda.synchronize()", h._PROBE)
        self.assertIn("torch.matmul", h._PROBE)


class RecommendedTagCliTests(unittest.TestCase):
    """WINDOWS_BASLAT.bat'in cagirdigi --onerilen-etiket / --cuda-dogrula CLI'si."""

    def test_rtx_50_blackwell_driver_580_picks_cu130(self):
        runner, which, _ = fake({"nvidia-smi": "NVIDIA GeForce RTX 5070, 581.57, 12.0\n"},
                                tools=("nvidia-smi",))
        hw = h.detect("Windows", "AMD64", runner, which)
        self.assertEqual(h.recommended_tag(hw, None), h.CUDA_NEW)  # sm_120: yalniz cu128/cu130 destekler

    def test_rtx_3060_old_driver_picks_cu126(self):
        runner, which, _ = fake({"nvidia-smi": "NVIDIA GeForce RTX 3060, 535.98, 8.6\n"},
                                tools=("nvidia-smi",))
        hw = h.detect("Windows", "AMD64", runner, which)
        self.assertEqual(h.recommended_tag(hw, None), h.CUDA_OLD)  # 535 < 580: cu130 kosulu saglanmaz

    def test_driver_520_is_too_old_for_any_cuda_tag(self):
        runner, which, _ = fake({"nvidia-smi": "NVIDIA GeForce RTX 3060, 520.61, 8.6\n"},
                                tools=("nvidia-smi",))
        hw = h.detect("Windows", "AMD64", runner, which)
        p = h.plan(hw, None)
        self.assertEqual(p["durum"], h.DRIVER_OLD)
        self.assertIsNone(h.recommended_tag(hw, None))  # kurulum yapma, surucu guncellemesi gerekir

    def test_blackwell_driver_570_to_579_picks_cu128(self):
        # RTX 5070, surucu 572, cc 12.0: cu126'da cekirdek yok; cu130 henuz gerekmez (580 alti).
        runner, which, _ = fake({"nvidia-smi": "NVIDIA GeForce RTX 5070, 572.16, 12.0\n"},
                                tools=("nvidia-smi",))
        hw = h.detect("Windows", "AMD64", runner, which)
        p = h.plan(hw, None)
        self.assertEqual((p["durum"], p["hedef"], p["etiket"]), (h.INSTALL, "cuda", h.CUDA_BLACKWELL))
        self.assertEqual(h.recommended_tag(hw, None), "cu128")

    def test_blackwell_driver_580_plus_picks_cu130(self):
        # RTX 5060 Laptop, surucu 581: Blackwell + driver>=580 -> cu130 (genel yolla ayni).
        runner, which, _ = fake({"nvidia-smi": "NVIDIA GeForce RTX 5060 Laptop GPU, 581.80, 12.0\n"},
                                tools=("nvidia-smi",))
        hw = h.detect("Windows", "AMD64", runner, which)
        self.assertEqual(h.recommended_tag(hw, None), h.CUDA_NEW)

    def test_blackwell_driver_below_570_is_driver_old_not_cu126(self):
        # RTX 5090, surucu 560: >=525 (genel esik) ama Blackwell icin 570 sarti saglanmaz;
        # cu126 onerilirse "no kernel image is available" ile patlar - DRIVER_OLD donulmeli.
        runner, which, _ = fake({"nvidia-smi": "NVIDIA GeForce RTX 5090, 560.94, 12.0\n"},
                                tools=("nvidia-smi",))
        hw = h.detect("Windows", "AMD64", runner, which)
        p = h.plan(hw, None)
        self.assertEqual((p["durum"], p["min_surucu"]), (h.DRIVER_OLD, 570))
        self.assertIsNone(h.recommended_tag(hw, None))

    def test_blackwell_without_compute_cap_detected_by_name(self):
        # Eski nvidia-smi compute_cap alanini desteklemiyor; ad "RTX 50xx" deseniyle taninir.
        def smi(cmd):
            return None if "compute_cap" in cmd[-1] else "NVIDIA GeForce RTX 5070 Laptop GPU, 575.64\n"
        runner, which, _ = fake({"nvidia-smi": smi}, tools=("nvidia-smi",))
        hw = h.detect("Windows", "AMD64", runner, which)
        self.assertIsNone(hw["gpus"][0]["compute_cap"])
        p = h.plan(hw, None)
        self.assertEqual((p["durum"], p["etiket"]), (h.INSTALL, h.CUDA_BLACKWELL))

    def test_no_gpu_and_already_active_and_broken_give_no_tag(self):
        runner, which, _ = fake({})
        hw = h.detect("Windows", "AMD64", runner, which)
        self.assertIsNone(h.recommended_tag(hw, None))  # NO_GPU
        runner, which, _ = fake({"nvidia-smi": NVIDIA_SMI}, tools=("nvidia-smi",))
        hw = h.detect("Windows", "AMD64", runner, which)
        self.assertIsNone(h.recommended_tag(hw, CUDA_TORCH))  # ACTIVE: zaten calisiyor, yeniden kurma
        broken = dict(CUDA_TORCH, cuda_kernel_ok=False)
        self.assertIsNone(h.recommended_tag(hw, broken))  # BROKEN: donguye sokmaz

    def test_cli_onerilen_etiket_prints_tag_or_empty_line(self):
        with patch.object(h, "detect", return_value={"system": "Windows", "machine": "amd64", "gpus": [], "nvidia_smi": False}), \
                patch.object(h, "probe_torch", return_value=None), \
                patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(h._cli(["--onerilen-etiket"]), 0)
        self.assertEqual(out.getvalue().strip(), "")  # NO_GPU: bos satir, CPU'ya devam

    def test_cli_cuda_dogrula_exit_code_reflects_kernel_test(self):
        with patch.object(h, "probe_torch", return_value=dict(CUDA_TORCH, cuda_kernel_ok=True)), \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(h._cli(["--cuda-dogrula"]), 0)
        with patch.object(h, "probe_torch", return_value=dict(CUDA_TORCH, cuda_kernel_ok=False)), \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(h._cli(["--cuda-dogrula"]), 1)


class RealMachineTests(unittest.TestCase):
    """Bu bilgisayarda gerçek algılama: NVIDIA/AMD yoksa "kurulum" önerilmemeli."""

    def test_real_detection_does_not_offer_bogus_install(self):
        hw = h.detect()
        vendors = {g["vendor"] for g in hw["gpus"]}
        p = h.plan(hw, h.probe_torch())
        if not vendors & {h.NVIDIA, h.AMD}:
            self.assertNotEqual(p["durum"], h.INSTALL)
        if platform.system() == "Darwin":
            self.assertEqual(p["durum"], h.MAC)
            self.assertFalse(hw["nvidia_smi"])


if __name__ == "__main__":
    unittest.main()
