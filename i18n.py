"""Arayüz dili (i18n): basit sözlük tabanlı çeviri.

Kaynak dil Türkçedir ve anahtarlar Türkçe metnin kendisidir (gettext tarzı):
``t("Üret")`` Türkçede "Üret", İngilizcede ``locales/en.json`` içindeki karşılığı
döner. Çevirisi olmayan metin Türkçe kalır (arayüz asla boş anahtar göstermez).

Bu modül yalnız standart kütüphane kullanır: desktop.py, app (torch/numpy)
yüklenemese de hata sayfasını seçili dilde gösterebilsin.

Seçilen dil ``ayarlar.json`` dosyasında saklanır (SESVER_AYARLAR ile değiştirilebilir).
Uygulama tek kullanıcılı, yerel bir masaüstü uygulaması olduğundan sunucu tarafı
iletiler (hata/durum) süreç genelindeki geçerli dili kullanır.

Not: Bu, ARAYÜZ dilidir. Ses üretiminin dili ayrı bir konudur: VoxCPM2 metnin
dilini kendisi anlar (dil etiketi almaz); bkz. README "Diller".
"""
import json
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT = "tr"
# Yerel adlarıyla; sıra dil seçicide görünen sıradır.
LANGUAGES = {
    "tr": "Türkçe",
    "en": "English",
    "es": "Español",
    "zh": "简体中文",
    "hi": "हिन्दी",
    "ar": "العربية",
    "fr": "Français",
    "pt": "Português",
    "ru": "Русский",
    "de": "Deutsch",
    "ja": "日本語",
}
RTL = frozenset({"ar"})
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")

_catalogs = {}
_current = None
_override: ContextVar[str | None] = ContextVar("sesver_lang", default=None)


def settings_path():
    return Path(os.environ.get("SESVER_AYARLAR") or Path(__file__).resolve().parent / "ayarlar.json")


def normalize(lang):
    lang = (lang or "").strip().lower().replace("_", "-")
    if lang in LANGUAGES:
        return lang
    base = lang.split("-", 1)[0]
    return base if base in LANGUAGES else DEFAULT


def catalog(lang):
    """Dilin çeviri sözlüğü (Türkçe için boş: kaynak metin kullanılır)."""
    lang = normalize(lang)
    if lang == DEFAULT:
        return {}
    if lang not in _catalogs:
        try:
            data = json.loads((LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        _catalogs[lang] = {k: v for k, v in data.items() if isinstance(v, str) and not k.startswith("_")}
    return _catalogs[lang]


def saved_language():
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return normalize(data.get("arayuz_dili"))
    except (OSError, ValueError, AttributeError):
        return DEFAULT


def get_lang():
    global _current
    override = _override.get()
    if override:
        return override
    if _current is None:
        _current = saved_language()
    return _current


def set_lang(lang, persist=True):
    """Geçerli arayüz dilini değiştirir; istenirse ayarlar.json'a yazar (hata sessizce yutulur)."""
    global _current
    _current = normalize(lang)
    if persist:
        path = settings_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data["arayuz_dili"] = _current
        try:
            tmp = path.with_name(path.name + ".yaz")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass  # salt okunur klasör: dil yalnız bu oturum için geçerli kalır
    return _current


@contextmanager
def use(lang):
    """Bu blok içinde t() verilen dili kullanır (arayüz metni kurarken)."""
    token = _override.set(normalize(lang))
    try:
        yield
    finally:
        _override.reset(token)


def is_rtl(lang=None):
    return normalize(lang or get_lang()) in RTL


def page_path(lang):
    """Dilin arayüz sayfası yolu: Türkçe kök adreste (""), diğerleri "en", "es" …"""
    lang = normalize(lang)
    return "" if lang == DEFAULT else lang


def t(text, lang=None, /, **kwargs):
    """Türkçe kaynak metnin çevirisi; kwargs varsa str.format ile doldurulur.

    ``text``/``lang`` konumsaldır: ``{text}`` gibi yer tutucular kwargs olarak verilebilir.
    """
    out = catalog(lang or get_lang()).get(text, text)
    if kwargs:
        try:
            return out.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text.format(**kwargs)
    return out


def _template_regex(key):
    parts = _PLACEHOLDER.split(key)
    tokens = _PLACEHOLDER.findall(key)
    pattern = "".join(re.escape(p) + ("(.+?)" if i < len(tokens) else "") for i, p in enumerate(parts))
    return re.compile(f"^{pattern}$", re.S), tokens


_template_cache = {}


def tr_message(text, lang=None):
    """Hazır üretilmiş (biçimlenmiş) Türkçe bir iletiyi çevirir.

    Önce birebir eşleşme aranır; yoksa ``{...}`` yer tutuculu anahtarlar kalıp
    olarak denenir (ör. yardımcı modüllerin f-string hata iletileri). Yer tutucuya
    düşen değer de bilinen bir Türkçe metinse o da çevrilir. Eşleşme yoksa metin
    olduğu gibi döner.
    """
    if not text:
        return text
    lang = normalize(lang or get_lang())
    cat = catalog(lang)
    if not cat:
        return text
    if text in cat:
        return cat[text]
    if lang not in _template_cache:
        # En uzun sabit metinli kalıp önce denenir (genel kalıplar yanlış eşleşmesin).
        keys = sorted((k for k in cat if _PLACEHOLDER.search(k)),
                      key=lambda k: -len(_PLACEHOLDER.sub("", k)))
        _template_cache[lang] = [(k, *_template_regex(k)) for k in keys]
    for key, regex, tokens in _template_cache[lang]:
        value = cat[key]
        match = regex.match(text)
        if not match:
            continue
        out = value
        for token, captured in zip(tokens, match.groups()):
            out = out.replace(token, cat.get(captured, captured))
        return out
    return text


def all_translations(text):
    """Bir kaynak metnin tüm dillerdeki hâlleri (Türkçe dahil)."""
    return {tr_message(text, lang) for lang in LANGUAGES} | {text}
