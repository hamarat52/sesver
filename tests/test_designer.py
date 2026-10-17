"""Kurallı tarif birleştiricisi (LLM yok) için birim testleri."""
import unittest

import voice_designer as vd


class DesignerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harita = vd.load_map()

    def build(self, **secimler):
        return vd.build_description(secimler, self.harita)

    def test_user_example_storyteller_exact(self):
        tarif, _parts, warns = self.build(yas="Yaşlı", cinsiyet="Erkek", kullanim="Masal", perde="Kalın",
                                          ton="Sıcak", doku=["Boğuk"], hiz="Yavaş")
        self.assertEqual(tarif, "an elderly male storyteller, deep, warm, husky, slow")
        self.assertEqual(warns, [])

    def test_user_example_podcast_exact(self):
        tarif, _parts, _warns = self.build(yas="30'lar", cinsiyet="Kadın", kullanim="Podcast", ton="Neşeli",
                                           doku=["Berrak"], hiz="Hızlı", enerji="Yüksek")
        self.assertEqual(tarif, "a female podcast host in her thirties, cheerful, clear, fast, high energy")

    def test_thirties_pronoun_follows_gender(self):
        self.assertIn("in his thirties", self.build(yas="30'lar", cinsiyet="Erkek")[0])
        self.assertIn("in their thirties", self.build(yas="30'lar", cinsiyet="Belirsiz")[0])
        self.assertIn("in their thirties", self.build(yas="30'lar")[0])

    def test_article_a_an(self):
        self.assertTrue(self.build(cinsiyet="Belirsiz")[0].startswith("an androgynous voice"))
        self.assertTrue(self.build(yas="Orta yaş", cinsiyet="Erkek")[0].startswith("a middle-aged male"))
        self.assertTrue(self.build(yas="Genç", cinsiyet="Kadın")[0].startswith("a young female"))
        # "young" ünlüyle başlamaz ama istisna listesi önce bakılır: "a"
        self.assertTrue(self.build(cinsiyet="Kadın", kullanim="Sohbet")[0].startswith("a female"))

    def test_child_goes_after_gender(self):
        self.assertTrue(self.build(yas="Çocuk", cinsiyet="Kadın")[0].startswith("a female child voice"))

    def test_empty_selection_has_no_extra_commas(self):
        tarif, parts, warns = self.build()
        self.assertEqual(tarif, "a voice")
        self.assertEqual(parts, [])
        for secimler in ({"perde": "Orta", "hiz": "Normal", "enerji": "Orta"},
                         {"cinsiyet": "Fark etmez", "ton": "Fark etmez", "doku": []}):
            tarif = vd.build_description(secimler, self.harita)[0]
            self.assertEqual(tarif, "a voice")
        tarif = self.build(cinsiyet="Erkek", hiz="Hızlı")[0]
        self.assertEqual(tarif, "a male voice, fast")
        self.assertNotIn(",,", tarif)
        self.assertNotIn(", ,", tarif)
        self.assertFalse(tarif.endswith(","))

    def test_fixed_order(self):
        tarif = self.build(enerji="Düşük", hiz="Çok yavaş", doku=["Yumuşak"], ton="Sakin", perde="İnce",
                           cinsiyet="Kadın")[0]
        self.assertEqual(tarif, "a female voice, high-pitched, calm, soft, very slow, low energy, relaxed")

    def test_texture_limited_to_two(self):
        tarif, _parts, warns = self.build(doku=["Berrak", "Boğuk", "Nefesli"])
        self.assertIn("clear, husky", tarif)
        self.assertNotIn("breathy", tarif)
        self.assertTrue(any("en fazla 2" in w for w in warns))

    def test_odd_combination_warns_but_does_not_block(self):
        tarif, _parts, warns = self.build(yas="Çocuk", cinsiyet="Erkek", perde="Çok kalın")
        self.assertIn("very deep, low-pitched", tarif)
        self.assertTrue(any("Çocuk" in w for w in warns))

    def test_word_limit_trims_in_order(self):
        harita = dict(self.harita, max_kelime=8)
        tarif, _parts, warns = vd.build_description(
            {"yas": "Yaşlı", "cinsiyet": "Erkek", "kullanim": "Belgesel", "perde": "Çok kalın", "ton": "Ciddi",
             "doku": ["Tok", "Pürüzlü"], "hiz": "Yavaş", "enerji": "Düşük"}, harita)
        self.assertLessEqual(vd._word_count(tarif), 8)
        self.assertNotIn("low energy", tarif)  # ilk kısaltılan enerji
        self.assertTrue(any("kelime" in w for w in warns))

    def test_default_limit_25_words_never_exceeded(self):
        tarif = self.build(yas="30'lar", cinsiyet="Belirsiz", kullanim="Reklam", perde="Çok kalın",
                           ton="Heyecanlı", doku=["Tok", "Nefesli"], hiz="Çok hızlı", enerji="Düşük")[0]
        self.assertLessEqual(vd._word_count(tarif), 25)

    def test_parts_carry_turkish_labels(self):
        _tarif, parts, _w = self.build(cinsiyet="Kadın", ton="Sıcak")
        self.assertIn(("female", "Kadın"), parts)
        self.assertIn(("warm", "Sıcak"), parts)
        html = vd.parts_html(parts)
        self.assertIn('title="Kadın"', html)
        self.assertIn(">female<", html)

    def test_templates_fill_selections(self):
        for name in ("Masalcı", "Belgesel", "Sunucu", "Sıcak kadın anlatıcı"):
            secimler, kategori = vd.template(self.harita, name)
            self.assertIn(kategori, self.harita["ornek_metinler"])
            tarif = vd.build_description(secimler, self.harita)[0]
            self.assertTrue(tarif.startswith(("a ", "an ")))
        secimler, _k = vd.template(self.harita, "Masalcı")
        self.assertEqual(vd.build_description(secimler, self.harita)[0],
                         "an elderly male storyteller, deep, warm, husky, slow")

    def test_candidate_seeds(self):
        self.assertEqual(vd.candidate_seeds(0), [11, 22, 33, 44])
        self.assertEqual(vd.candidate_seeds(1), [55, 66, 77, 88])

    def test_sample_text_tracks_requested_duration(self):
        for kategori in ("masal", "belgesel", "sunucu"):
            short = vd.sample_text(kategori, 4, self.harita)
            default = vd.sample_text(kategori, 8, self.harita)
            long_ = vd.sample_text(kategori, 20, self.harita)
            self.assertLess(len(short), len(default))
            self.assertLess(len(default), len(long_))
            self.assertLess(abs(vd.estimate_seconds(default, self.harita) - 8), 3)
            self.assertNotIn("(", default)


if __name__ == "__main__":
    unittest.main()
