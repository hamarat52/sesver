"""Arayüz dili (i18n): basit sözlük tabanlı çeviri.

Kaynak dil Türkçedir ve anahtarlar Türkçe metnin kendisidir (gettext tarzı):
``t("Üret")`` Türkçede "Üret", İngilizcede ``locales/en.json`` içindeki karşılığı
döner. Çevirisi olmayan metin Türkçe kalır (arayüz asla boş anahtar göstermez).

Bu modül yalnız standart kütüphane kullanır: desktop.py, app (torch/numpy)
yüklenemese de hata sayfasını seçili dilde gösterebilsin.

Seçilen dil ``ayarlar.json`` dosyasında saklanır (SESVER_AYARLAR ile değiştirilebilir).
Kayıtlı tercih yoksa (ilk açılış) işletim sisteminin dili kullanılır; desteklenmeyen
sistem dilinde arayüz İngilizce açılır (bkz. ``system_language``).
Uygulama tek kullanıcılı, yerel bir masaüstü uygulaması olduğundan sunucu tarafı
iletiler (hata/durum) süreç genelindeki geçerli dili kullanır.

Not: Bu, ARAYÜZ dilidir. Ses üretiminin dili ayrı bir konudur: VoxCPM2 metnin
dilini kendisi anlar (dil etiketi almaz); bkz. README "Diller".
"""
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT = "tr"  # kaynak dil: anahtarlar Türkçe metindir, Türkçe sayfa kök adrestedir
FALLBACK = "en"  # ilk açılışta sistem dili desteklenmiyorsa kullanılan dil
# Yalnız test/kuru çalıştırma içindir: işletim sisteminin dilini taklit eder
# (ör. SESVER_SISTEM_DILI=en-US). Normal kullanımda ayarlanmaz.
SYSTEM_LANG_ENV = "SESVER_SISTEM_DILI"
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


def match(lang):
    """Desteklenen dil kodu ya da None: "tr-TR" → "tr", "zh-Hans-CN" → "zh",
    "en_GB.UTF-8" → "en", "xx" → None."""
    lang = (lang or "").strip().lower().replace("_", "-")
    lang = lang.split(".", 1)[0].split("@", 1)[0]  # POSIX: en_US.UTF-8, sr_RS@latin
    if lang in LANGUAGES:
        return lang
    base = lang.split("-", 1)[0]
    return base if base in LANGUAGES else None


def normalize(lang):
    return match(lang) or DEFAULT


def _run(cmd):
    """Komutun stdout'u; hata/zaman aşımında boş metin."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3, check=False).stdout or ""
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""


def _apple_languages(runner):
    """`defaults read -g AppleLanguages` çıktısının ilk öğesi; ör. '(\\n    "en-US",\\n    "tr-TR"\\n)'."""
    out = runner(["/usr/bin/defaults", "read", "-g", "AppleLanguages"]) or ""
    for item in re.split(r"[,\n]", out.strip().strip("()")):
        item = item.strip().strip('"').strip()
        if item:
            return item
    return ""


def _windows_ui_language():
    """Windows arayüz dili (GetUserDefaultUILanguage); olmazsa varsayılan yerel ayar."""
    import locale
    try:
        import ctypes
        langid = getattr(ctypes, "windll").kernel32.GetUserDefaultUILanguage()
        name = locale.windows_locale.get(langid)
        if name:
            return name
    except (AttributeError, OSError, ImportError):
        pass
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return (locale.getdefaultlocale()[0] or "") if hasattr(locale, "getdefaultlocale") else ""
    except (ValueError, TypeError):
        return ""


def system_language(env=None, runner=None, platform=None, windows_ui=None):
    """İşletim sisteminin dili, desteklenen bir arayüz koduna çevrilmiş hâlde.

    Kaynak sırası: SESVER_SISTEM_DILI (yalnız test) → macOS AppleLanguages ilk öğesi
    ya da Windows arayüz dili → LC_ALL / LC_MESSAGES / LANG. Bulunan İLK dil
    desteklenmiyorsa ``FALLBACK`` (İngilizce) döner; hiçbir kaynak yoksa da öyle.
    Tüm dış bağımlılıklar enjekte edilebilir (testler için): ``env`` ortam sözlüğü,
    ``runner(cmd) -> stdout``, ``platform`` (sys.platform), ``windows_ui() -> "en_US"``.
    """
    env = os.environ if env is None else env
    runner = runner or _run
    platform = platform or sys.platform
    candidates = [env.get(SYSTEM_LANG_ENV, "")]
    if platform == "darwin":
        candidates.append(_apple_languages(runner))
    elif platform == "win32":
        candidates.append((windows_ui or _windows_ui_language)())
    candidates += [env.get(name, "") for name in ("LC_ALL", "LC_MESSAGES", "LANG")]
    for cand in candidates:
        cand = (cand or "").strip()
        if cand and cand.upper() not in ("C", "POSIX") and not cand.upper().startswith("C."):
            return match(cand) or FALLBACK
    return FALLBACK


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


def stored_language():
    """ayarlar.json'da kayıtlı arayüz dili; dosya ya da kayıt yoksa None."""
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("arayuz_dili") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    return normalize(value)


def saved_language():
    """Açılış dili: kayıtlı tercih her zaman önce gelir; yoksa (ilk açılış) sistem dili."""
    return stored_language() or system_language()


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
