"""Üretim sonrası DSP efektleri ve seviye eşitleme testleri."""
import unittest

import numpy as np
from scipy import signal

import effects as fx

SR = 24000


def speechlike(seconds=3.0, sr=SR, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    tone = sum(np.sin(2 * np.pi * f * t) / k for k, f in enumerate((140, 280, 560, 1200, 2500, 6000), 1))
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 3 * t) ** 2
    return (0.15 * tone * env + 0.01 * rng.standard_normal(len(t))).astype(np.float32)


def band_energy(x, lo, hi, sr=SR):
    f, p = signal.welch(x, sr, nperseg=2048)
    return float(np.sum(p[(f >= lo) & (f < hi)]))


class EffectsTests(unittest.TestCase):
    def setUp(self):
        self.x = speechlike()

    def test_no_effect_returns_raw_unchanged(self):
        out = fx.apply(self.x, SR, [])
        np.testing.assert_array_equal(out, self.x)

    def test_raw_input_never_mutated(self):
        original = self.x.copy()
        for name in fx.EFFECTS:
            fx.apply(self.x, SR, [{"ad": name, "yogunluk": 100}])
        np.testing.assert_array_equal(self.x, original)

    def test_every_effect_changes_the_sound(self):
        for name in fx.EFFECTS:
            with self.subTest(name=name):
                out = fx.apply(self.x, SR, [{"ad": name, "yogunluk": 70}], level_match=False)
                n = min(len(out), len(self.x))
                self.assertGreater(float(np.mean(np.abs(out[:n] - self.x[:n]))), 1e-3)
                self.assertTrue(np.all(np.isfinite(out)))

    def test_intensity_is_audible(self):
        for name in fx.EFFECTS:
            with self.subTest(name=name):
                low = fx.apply(self.x, SR, [{"ad": name, "yogunluk": 10}], level_match=False)
                high = fx.apply(self.x, SR, [{"ad": name, "yogunluk": 90}], level_match=False)
                n = min(len(low), len(high))
                diff = float(np.sqrt(np.mean((high[:n] - low[:n]) ** 2)))
                self.assertGreater(diff / fx._rms(self.x), 0.02, name)

    def test_telephone_band_limits(self):
        out = fx.apply(self.x, SR, [{"ad": "telefon", "yogunluk": 100}], level_match=False)
        ratio_in = band_energy(self.x, 5000, 12000) / band_energy(self.x, 300, 3400)
        ratio_out = band_energy(out, 5000, 12000) / band_energy(out, 300, 3400)
        self.assertLess(ratio_out, ratio_in * 0.05)

    def test_megaphone_removes_lows(self):
        out = fx.apply(self.x, SR, [{"ad": "megafon", "yogunluk": 50}], level_match=False)
        self.assertLess(band_energy(out, 50, 250) / band_energy(out, 500, 4000),
                        band_energy(self.x, 50, 250) / band_energy(self.x, 500, 4000) * 0.2)

    def test_radio_adds_squelch_bursts(self):
        out = fx.apply(self.x, SR, [{"ad": "telsiz", "yogunluk": 50}], level_match=False)
        self.assertEqual(len(out), len(self.x) + 2 * int(0.12 * SR))

    def test_room_presets_differ(self):
        outs = {p: fx.apply(self.x, SR, [{"ad": "oda", "yogunluk": 80, "on_ayar": p}], level_match=False)
                for p in fx.ROOM_PRESETS}
        self.assertGreater(len(outs["kilise"]), len(outs["kucuk"]))

    def test_loudness_target_and_true_peak(self):
        for name in fx.EFFECTS:
            with self.subTest(name=name):
                out = fx.apply(self.x, SR, [{"ad": name, "yogunluk": 60}])
                self.assertLess(abs(fx.loudness_lufs(out, SR) - fx.TARGET_LUFS), 1.0)
                self.assertLessEqual(fx.true_peak_dbtp(out), fx.PEAK_DBTP + 0.05)

    def test_lufs_reference_sine(self):
        # BS.1770: 997 Hz, 0 dBFS tepe sinüs (mono) ≈ -3.01 LUFS.
        t = np.arange(48000 * 3) / 48000
        sine = np.sin(2 * np.pi * 997 * t)
        self.assertAlmostEqual(fx.loudness_lufs(sine, 48000), -3.01, delta=0.1)

    def test_settings_are_cleaned_and_ordered(self):
        cleaned = fx.clean_settings([{"ad": "cizirti", "yogunluk": 500}, {"ad": "bilinmeyen"},
                                     {"ad": "oda", "on_ayar": "uzay"}, {"ad": "telefon", "yogunluk": -3}])
        self.assertEqual([e["ad"] for e in cleaned], ["telefon", "oda", "cizirti"])
        self.assertEqual(cleaned[0]["yogunluk"], 0)
        self.assertEqual(cleaned[2]["yogunluk"], 100)
        self.assertEqual(cleaned[1]["on_ayar"], "salon")

    def test_crackle_is_deterministic(self):
        a = fx.apply(self.x, SR, [{"ad": "cizirti", "yogunluk": 50}])
        b = fx.apply(self.x, SR, [{"ad": "cizirti", "yogunluk": 50}])
        np.testing.assert_array_equal(a, b)


if __name__ == "__main__":
    unittest.main()
