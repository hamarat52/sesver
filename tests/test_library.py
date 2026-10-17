"""Ses kütüphanesi (voices/) okuma-yazma ve gerçek kişi koruması testleri."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

import voice_library as vl

SYNTH = "Tarifle tasarlandı (sentetik ses, gerçek kişi değil)"


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "voices"
        self.wav = self.tmp / "in.wav"
        sr = 16000
        t = np.arange(sr * 5) / sr
        sf.write(self.wav, (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), sr, subtype="PCM_16")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save(self, **kw):
        args = dict(ad="Gece Anlatıcısı", ref_wav=self.wav, ref_text="Merhaba dünya.", kaynak=SYNTH, root=self.root)
        args.update(kw)
        return vl.save_voice(**args)

    def test_save_writes_ref_files_and_schema(self):
        v = self.save(tarif="a calm voice", seed=33, secimler={"ton": "Sakin"})
        folder = self.root / "seslerim" / "gece-anlaticisi"
        for name in ("ref.wav", "ref.txt", "ses.json", "ornek.wav"):
            self.assertTrue((folder / name).is_file(), name)
        meta = json.loads((folder / "ses.json").read_text(encoding="utf-8"))
        self.assertEqual(vl.validate_meta(meta), [])
        self.assertEqual((meta["seed"], meta["tarif"], meta["hazir"]), (33, "a calm voice", False))
        self.assertEqual((folder / "ref.txt").read_text(encoding="utf-8").strip(), "Merhaba dünya.")
        self.assertEqual(v["id"], "gece-anlaticisi")
        self.assertAlmostEqual(sf.info(folder / "ornek.wav").duration, 3.0, places=2)

    def test_voices_persist_across_restart(self):
        self.save()
        # "Yeniden başlatma": modül durumu yok, her şey diskten okunur.
        ids = [v["id"] for v in vl.list_voices(self.root)]
        self.assertEqual(ids, ["gece-anlaticisi"])
        self.assertEqual(vl.get_voice("gece-anlaticisi", self.root)["ref_text"], "Merhaba dünya.")

    def test_empty_text_or_name_rejected(self):
        with self.assertRaises(vl.VoiceError):
            self.save(ref_text="  ")
        with self.assertRaises(vl.VoiceError):
            self.save(ad="")

    def test_unique_ids(self):
        a, b = self.save(), self.save()
        self.assertNotEqual(a["id"], b["id"])

    def test_hazir_voice_cannot_be_deleted_only_copied(self):
        self.save(ad="Masalcı", voice_id="masalci", hazir=True)
        with self.assertRaises(vl.VoiceError):
            vl.delete_voice("masalci", self.root)
        self.assertTrue((self.root / "hazir" / "masalci").is_dir())
        copy = vl.copy_voice("masalci", root=self.root)
        self.assertFalse(copy["hazir"])
        self.assertTrue(Path(copy["_dir"]).parent.name == "seslerim")
        vl.delete_voice(copy["id"], self.root)
        self.assertIsNone(vl.get_voice(copy["id"], self.root))

    def test_protected_real_person_names_never_written_to_hazir(self):
        for name in ("yusuf", "Yusuf2", "AKİF", "yusuf-ses", "Akif Bey"):
            with self.subTest(name=name), self.assertRaises(PermissionError):
                self.save(ad=name, hazir=True)
            with self.subTest(voice_id=name), self.assertRaises((PermissionError, vl.VoiceError)):
                self.save(ad="Sentetik", voice_id=vl.slugify(name), hazir=True)
        self.assertFalse((self.root / "hazir").exists() and any((self.root / "hazir").iterdir()))

    def test_uploaded_or_real_source_never_hazir(self):
        for kaynak in ("yüklendi", "gerçek kişi", "Yüklendi (kopya: x)", ""):
            with self.subTest(kaynak=kaynak), self.assertRaises(PermissionError):
                self.save(ad="Temiz Ad", kaynak=kaynak, hazir=True)

    def test_misplaced_real_voice_in_hazir_is_not_listed(self):
        folder = self.root / "hazir" / "yusuf"
        folder.mkdir(parents=True)
        shutil.copy(self.wav, folder / "ref.wav")
        (folder / "ref.txt").write_text("x", encoding="utf-8")
        (folder / "ses.json").write_text(json.dumps({"id": "yusuf", "ad": "Yusuf", "kaynak": SYNTH}), encoding="utf-8")
        self.assertEqual(vl.list_voices(self.root), [])

    def test_import_preset_copies_and_strips_extra_fields(self):
        src = self.tmp / "paket" / "masalci"
        src.mkdir(parents=True)
        shutil.copy(self.wav, src / "ref.wav")
        (src / "ref.txt").write_text("Bir varmış.\n", encoding="utf-8")
        raw = {"id": "masalci", "ad": "Yaşlı Masalcı", "kategori": "Hikâye", "tarif": "x", "seed": None,
               "ref_audio": "ref.wav", "ref_text_file": "ref.txt", "model": "m", "mod": "continuation",
               "kaynak": SYNTH, "varsayilan_efektler": []}
        (src / "ses.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        before = {p.name: p.read_bytes() for p in src.iterdir()}
        v = vl.import_preset(src, root=self.root)
        self.assertEqual(before, {p.name: p.read_bytes() for p in src.iterdir()})  # kaynak değişmedi
        meta = json.loads((self.root / "hazir" / "masalci" / "ses.json").read_text(encoding="utf-8"))
        self.assertEqual(vl.validate_meta(meta), [])
        for extra in ("ref_audio", "ref_text_file", "model", "mod"):
            self.assertNotIn(extra, meta)
        self.assertIsNone(meta["seed"])
        self.assertTrue(v["hazir"])
        self.assertEqual((self.root / "hazir" / "masalci" / "ref.wav").read_bytes(), before["ref.wav"])

    def test_effect_preset_saved_only_on_own_voice(self):
        own = self.save()
        vl.update_effects(own["id"], [{"ad": "telefon", "yogunluk": 60}], root=self.root)
        self.assertEqual(vl.get_voice(own["id"], self.root)["varsayilan_efektler"], [{"ad": "telefon", "yogunluk": 60}])
        self.save(ad="Hazır", voice_id="hazir-ses", hazir=True)
        with self.assertRaises(vl.VoiceError):
            vl.update_effects("hazir-ses", [], root=self.root)

    def test_path_traversal_ids_rejected(self):
        for bad in ("../x", "a/b", "", "X"):
            with self.subTest(bad=bad), self.assertRaises(vl.VoiceError):
                vl.delete_voice(bad, self.root)
            self.assertIsNone(vl.get_voice(bad, self.root))


class ShippedPresetsTests(unittest.TestCase):
    def test_three_presets_shipped_and_valid(self):
        voices = vl.list_voices()
        hazir = {v["id"]: v for v in voices if v["hazir"]}
        self.assertEqual(set(hazir) & {"masalci", "belgesel", "heyecanli"}, {"masalci", "belgesel", "heyecanli"})
        for voice_id in ("masalci", "belgesel", "heyecanli"):
            folder = vl.hazir_dir() / voice_id
            meta = json.loads((folder / "ses.json").read_text(encoding="utf-8"))
            self.assertEqual(vl.validate_meta(meta), [], voice_id)
            self.assertTrue(meta["hazir"])
            vl.assert_can_be_hazir(meta)
            self.assertTrue(8 <= sf.info(folder / "ref.wav").duration <= 20)
            self.assertTrue((folder / "ornek.wav").is_file())

    def test_no_protected_name_anywhere_under_hazir(self):
        for path in vl.hazir_dir().rglob("*"):
            self.assertFalse(vl.is_protected(path.name), path)

    def test_gitignore_keeps_personal_voices_out(self):
        text = (Path(vl.__file__).parent / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("voices/seslerim/", text)
        self.assertIn("!voices/hazir/*/ref.wav", text)
        for name in ("yusuf", "akif"):
            self.assertIn(f"voices/**/*{name}*", text)


if __name__ == "__main__":
    unittest.main()
