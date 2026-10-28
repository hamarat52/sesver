"""Test oturumu ortamı.

ayarlar.json yokken arayüz dili işletim sisteminin dilinden gelir (i18n.system_language).
Testlerin çoğu Türkçe kaynak iletileri bekler; sonuç test eden makinenin diline bağlı
olmasın diye sistem dili Türkçe olarak sabitlenir. Sistem dilini sınayan testler
(tests/test_i18n.py) bu değişkeni kendileri değiştirir ya da hiç kullanmaz.
"""
import os

os.environ["SESVER_SISTEM_DILI"] = "tr-TR"
