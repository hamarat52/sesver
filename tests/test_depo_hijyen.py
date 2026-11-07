"""Depo hijyeni (bulgu 7): izlenen dosyalarda geliştiricinin yerel ev klasörü yolu geçmez.

Testi çalıştıran makinenin ev klasörü (ör. ``/Users/<ad>``) hiçbir izlenen metin dosyasında
olmamalı; örnek yollar ``/Users/ornekkullanici`` gibi genel adlarla yazılır.
"""
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tracked_files():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [ROOT / p for p in out.decode("utf-8").split("\0") if p]


@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "git deposu değil")
class LocalHomePathTests(unittest.TestCase):
    def test_no_tracked_file_contains_this_machines_home(self):
        home = os.path.expanduser("~").rstrip("\\/")
        self.assertGreater(len(home), 3)
        needles = {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}
        hits = []
        for path in _tracked_files():
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if b"\0" in data[:4096]:
                continue  # ikili dosya (png, ico, wav)
            text = data.decode("utf-8", errors="replace")
            hits += [f"{path.relative_to(ROOT)}: {n}" for n in needles if n in text]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
