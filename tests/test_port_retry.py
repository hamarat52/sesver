"""Port yarışı: 7860 doluyken SesVer'in 7861'e (ve sonrakilere) geçmesi.

Gerçek soket bind'i kullanılır: sahte demo.launch(), Gradio gibi portu bind etmeye çalışır
ve port doluysa OSError fırlatır. Kullanıcı logundaki hata:
`OSError: Cannot find empty port in range: 7860-7860`.
"""
import socket
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

HOST = "127.0.0.1"


def _occupy(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((HOST, port))
    s.listen(1)
    return s


def _free_block(n):
    """Art arda n boş port bulur (testin sistemdeki 7860'tan bağımsız olması için)."""
    for base in range(20000, 60000, 37):
        socks = []
        try:
            for p in range(base, base + n):
                socks.append(_occupy(p))
            return base
        except OSError:
            continue
        finally:
            for s in socks:
                s.close()
    raise unittest.SkipTest("art arda boş port bulunamadı")


class FakeDemo:
    """Gradio'nun launch()'u gibi portu bind eder; doluysa OSError fırlatır."""

    def __init__(self):
        self.tried, self.sock, self.kwargs = [], None, None

    def launch(self, server_port, **kwargs):
        self.tried.append(server_port)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((HOST, server_port))
        except OSError:
            s.close()
            raise OSError(f"Cannot find empty port in range: {server_port}-{server_port}.")
        s.listen(1)
        self.sock, self.kwargs = s, kwargs

    def close(self):
        if self.sock:
            self.sock.close()


class PortRetryTests(unittest.TestCase):
    def test_bos_portta_dogrudan_acilir(self):
        base = _free_block(5)
        demo = FakeDemo()
        try:
            self.assertEqual(app.launch_with_port_retry(demo, base, server_name=HOST), base)
            self.assertEqual(demo.tried, [base])
            self.assertEqual(demo.kwargs, {"server_name": HOST})
        finally:
            demo.close()

    def test_dolu_portta_sonrakine_gecer(self):
        base = _free_block(5)
        blocker = _occupy(base)  # başka bir süreç portu kapmış gibi
        demo = FakeDemo()
        try:
            self.assertEqual(app.launch_with_port_retry(demo, base), base + 1)
            self.assertEqual(demo.tried, [base, base + 1])
        finally:
            blocker.close()
            demo.close()

    def test_hepsi_doluysa_anlasilir_hata(self):
        base = _free_block(3)
        blockers = [_occupy(p) for p in range(base, base + 3)]
        demo = FakeDemo()
        try:
            with self.assertRaises(OSError) as ctx:
                app.launch_with_port_retry(demo, base, tries=3)
            self.assertEqual(demo.tried, [base, base + 1, base + 2])
            self.assertIn(f"{base}-{base + 2}", str(ctx.exception))
            self.assertIn("kullanımda", str(ctx.exception))
        finally:
            for s in blockers:
                s.close()
            demo.close()

    def test_varsayilan_deneme_sayisi(self):
        self.assertTrue(3 <= app.PORT_TRIES <= 5)


class DesktopPortTests(unittest.TestCase):
    def test_pick_port_yoklamadan_istenen_portu_doner(self):
        import os
        from unittest.mock import patch
        import desktop
        with patch.dict(os.environ, {"GRADIO_SERVER_PORT": "7860"}):
            self.assertEqual(desktop._pick_port(), 7860)


if __name__ == "__main__":
    unittest.main()
