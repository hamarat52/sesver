"""Yüklenen ses dosyasının hazırlanması (çözme, kırpma, kontroller)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

import audio_prep as ap

SR = 22050


def tone(seconds, amp=0.3, sr=SR):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * 200 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 2 * t))).astype(np.float32)


class AudioPrepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wav(self, audio, name="a.wav", channels=1):
        path = self.tmp / name
        data = np.stack([audio] * channels, axis=1) if channels > 1 else audio
        sf.write(path, data, SR)
        return path

    def test_stereo_wav_becomes_mono_and_silence_trimmed(self):
        audio = np.concatenate([np.zeros(SR * 2, np.float32), tone(10), np.zeros(SR * 2, np.float32)])
        info = ap.analyze(self.wav(audio, channels=2))
        self.assertEqual(info["audio"].ndim, 1)
        self.assertEqual(info["sr"], SR)
        self.assertAlmostEqual(info["duration"], 10, delta=0.4)
        self.assertEqual(info["warnings"], [])
        out = ap.write_wav(info["audio"], info["sr"], self.tmp / "out.wav")
        meta = sf.info(out)
        self.assertEqual((meta.channels, meta.subtype), (1, "PCM_16"))

    def test_duration_rules(self):
        self.assertTrue(any("en az 8" in w for w in ap.analyze(self.wav(tone(4)))["warnings"]))
        self.assertTrue(any("aralığı seçin" in w for w in ap.analyze(self.wav(tone(30)))["warnings"]))
        audio = tone(30)
        self.assertAlmostEqual(len(ap.cut(audio, SR, 2, 14)) / SR, 12, places=2)
        for start, end in ((0, 5), (0, 25), (10, 5)):
            with self.subTest(start=start, end=end), self.assertRaises(ap.PrepError):
                ap.cut(audio, SR, start, end)

    def test_clipping_and_low_level_warnings(self):
        clipped = np.clip(tone(10, amp=3.0), -1, 1)
        self.assertTrue(any("kırpılma" in w for w in ap.level_warnings(clipped)))
        quiet = tone(10, amp=0.004)
        self.assertTrue(any("çok düşük" in w for w in ap.level_warnings(quiet)))

    def test_rejects_unsupported_and_broken_files(self):
        bad = self.tmp / "x.ogg"
        bad.write_bytes(b"0")
        with self.assertRaises(ap.PrepError):
            ap.decode(bad)
        broken = self.tmp / "y.mp3"
        broken.write_bytes(b"not audio")
        with self.assertRaises(ap.PrepError):
            ap.decode(broken)

    @unittest.skipUnless(shutil.which("ffmpeg"), "test dosyası üretmek için ffmpeg gerekli")
    def test_mp3_and_m4a_decode_with_pyav(self):
        src = self.wav(tone(9))
        for ext in ("mp3", "m4a"):
            dst = self.tmp / f"t.{ext}"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "2", str(dst)], check=True)
            with self.subTest(ext=ext):
                info = ap.analyze(dst)
                self.assertAlmostEqual(info["duration"], 9, delta=0.5)
                self.assertEqual(info["audio"].ndim, 1)


if __name__ == "__main__":
    unittest.main()
