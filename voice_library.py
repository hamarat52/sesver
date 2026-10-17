"""Ses kütüphanesi: ``voices/`` klasörünü okur/yazar.

Yapı::

    voices/hazir/<id>/     ref.wav, ref.txt, ses.json, ornek.wav   (repoyla gelir)
    voices/seslerim/<id>/  ...                                     (kişisel, git dışı)

Gerçek kişi sesleri hiçbir koşulda ``hazir/`` altına yazılamaz: hem kaynak
alanına hem de ad/kimlik içindeki korumalı isimlere bakılır (bkz.
``assert_can_be_hazir``). ``.gitignore`` tek başına güvence sayılmaz.
"""
import json
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

VOICES_DIR = Path(__file__).resolve().parent / "voices"
SCHEMA_VERSION = 1
SAMPLE_SECONDS = 3.0
SYNTHETIC_PREFIX = "Tarifle tasarlandı"
# Gerçek kişilere ait klon adları/kimlikleri: bunları içeren hiçbir ses hazır
# (repoya giren) ses olarak işaretlenemez ve hazir/ klasörüne yazılamaz.
PROTECTED_NAMES = ("yusuf", "yusuf2", "akif")
SCHEMA_KEYS = (
    "id", "ad", "aciklama", "kategori", "tarif", "seed", "secimler",
    "varsayilan_efektler", "kaynak", "hazir", "surum", "olusturma",
)
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_TR_FOLD = str.maketrans("çğıİöşüÇĞÖŞÜâîûÂÎÛ", "cgiiosucgosuaiuaiu")


class VoiceError(ValueError):
    """Kullanıcıya gösterilebilir Türkçe kütüphane hatası."""


def hazir_dir(root=None):
    return Path(root or VOICES_DIR) / "hazir"


def seslerim_dir(root=None):
    return Path(root or VOICES_DIR) / "seslerim"


def fold(text):
    """Türkçe harfleri ASCII'ye indirip küçük harfe çevirir (karşılaştırma için)."""
    text = (text or "").translate(_TR_FOLD)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.lower()


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-")[:40].strip("-")
    return slug or "ses"


def is_protected(*texts):
    """Ad, kimlik ya da açıklamada gerçek kişi klonu adı geçiyor mu?"""
    for text in texts:
        tokens = re.split(r"[^a-z0-9]+", fold(str(text or "")))
        joined = fold(str(text or ""))
        for name in PROTECTED_NAMES:
            if name in tokens or name in joined:
                return True
    return False


def assert_can_be_hazir(meta):
    """Hazır (repoya giren) ses yalnız sentetik, tarifle tasarlanmış olabilir."""
    if is_protected(meta.get("id"), meta.get("ad"), meta.get("aciklama")):
        raise PermissionError("Gerçek kişi ses klonu hazır ses olarak kaydedilemez.")
    kaynak = fold(meta.get("kaynak"))
    if not kaynak.startswith(fold(SYNTHETIC_PREFIX)) or "yuklendi" in kaynak or "gercek kisi" in kaynak.replace(
            "gercek kisi degil", ""):
        raise PermissionError("Yalnız tarifle tasarlanmış sentetik sesler hazır ses olabilir.")


def _now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_meta(raw, voice_id, hazir):
    meta = {
        "id": voice_id,
        "ad": str(raw.get("ad") or voice_id).strip(),
        "aciklama": str(raw.get("aciklama") or "").strip(),
        "kategori": str(raw.get("kategori") or "Genel").strip(),
        "tarif": raw.get("tarif") or None,
        "seed": raw.get("seed") if isinstance(raw.get("seed"), int) else None,
        "secimler": raw.get("secimler") if isinstance(raw.get("secimler"), dict) else None,
        "varsayilan_efektler": list(raw.get("varsayilan_efektler") or []),
        "kaynak": str(raw.get("kaynak") or "").strip(),
        "hazir": bool(hazir),
        "surum": SCHEMA_VERSION,
        "olusturma": raw.get("olusturma") or _now(),
    }
    return meta


def validate_meta(meta):
    errors = [f"eksik alan: {k}" for k in SCHEMA_KEYS if k not in meta]
    extra = sorted(set(meta) - set(SCHEMA_KEYS))
    errors += [f"bilinmeyen alan: {k}" for k in extra]
    if "id" in meta and not _ID_RE.match(str(meta["id"])):
        errors.append("geçersiz id")
    if not str(meta.get("ad") or "").strip():
        errors.append("ad boş")
    if meta.get("seed") is not None and not isinstance(meta.get("seed"), int):
        errors.append("seed tam sayı olmalı")
    if not isinstance(meta.get("varsayilan_efektler", []), list):
        errors.append("varsayilan_efektler liste olmalı")
    return errors


def _check_id(voice_id):
    if not isinstance(voice_id, str) or not _ID_RE.match(voice_id):
        raise VoiceError("Geçersiz ses kimliği.")
    return voice_id


def make_sample(ref_wav, out_path, seconds=SAMPLE_SECONDS, fade=0.35):
    """ref.wav'ın ilk ``seconds`` saniyesinden sonu kısık örnek üretir."""
    audio, sr = sf.read(str(ref_wav), dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)[: int(seconds * sr)].copy()
    n_fade = min(len(audio), int(fade * sr))
    if n_fade:
        audio[-n_fade:] *= np.linspace(1.0, 0.0, n_fade, dtype=np.float32)
    sf.write(str(out_path), audio, sr, subtype="PCM_16")
    return Path(out_path)


def _voice_from_dir(path, hazir):
    meta_path = path / "ses.json"
    ref_wav, ref_txt = path / "ref.wav", path / "ref.txt"
    if not (meta_path.is_file() and ref_wav.is_file() and ref_txt.is_file()):
        return None
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        text = ref_txt.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    if not text or raw.get("id") != path.name or not _ID_RE.match(path.name):
        return None
    meta = normalize_meta(raw, path.name, hazir)
    if hazir:
        try:
            assert_can_be_hazir(meta)
        except PermissionError:
            # Elle yanlış yere konmuş gerçek kişi sesi hazır gibi gösterilmez.
            return None
    sample = path / "ornek.wav"
    meta.update(_dir=str(path), ref_wav=str(ref_wav), ref_text=text,
                ornek=str(sample) if sample.is_file() else str(ref_wav))
    return meta


def list_voices(root=None):
    """Önce hazır sesler (ada göre), sonra Seslerim (oluşturma sırasına göre)."""
    result = []
    for hazir, folder in ((True, hazir_dir(root)), (False, seslerim_dir(root))):
        if not folder.is_dir():
            continue
        voices = [v for v in (_voice_from_dir(p, hazir) for p in folder.iterdir() if p.is_dir()) if v]
        voices.sort(key=(lambda v: fold(v["ad"])) if hazir else (lambda v: v["olusturma"]))
        result.extend(voices)
    return result


def get_voice(voice_id, root=None):
    if not isinstance(voice_id, str) or not _ID_RE.match(voice_id):
        return None
    for hazir, folder in ((True, hazir_dir(root)), (False, seslerim_dir(root))):
        path = folder / voice_id
        if path.is_dir():
            return _voice_from_dir(path, hazir)
    return None


def _unique_id(base, root):
    base = slugify(base)
    candidate, n = base, 2
    while (hazir_dir(root) / candidate).exists() or (seslerim_dir(root) / candidate).exists():
        candidate = f"{base[:44]}-{n}"
        n += 1
    return candidate


def save_voice(*, ad, ref_wav, ref_text, kaynak, aciklama="", kategori="Genel", tarif=None,
               seed=None, secimler=None, varsayilan_efektler=None, hazir=False,
               voice_id=None, root=None):
    """Yeni ses klasörünü atomik olarak yazar ve okunmuş hâlini döndürür.

    ``hazir=True`` yalnız sentetik sesler içindir; korumalı isimler ya da
    yüklenmiş/gerçek kişi kaynağı reddedilir.
    """
    ad = (ad or "").strip()
    ref_text = (ref_text or "").strip()
    if not ad:
        raise VoiceError("Sese bir ad verin.")
    if not ref_text:
        raise VoiceError("Kaydın metni boş olamaz; devam kipi bu metinle çalışır.")
    if not ref_wav or not Path(ref_wav).is_file():
        raise VoiceError("Kaydedilecek ses dosyası bulunamadı.")
    voice_id = _check_id(voice_id) if voice_id else _unique_id(ad, root)
    meta = normalize_meta(dict(
        ad=ad, aciklama=aciklama, kategori=kategori, tarif=tarif, seed=seed, secimler=secimler,
        varsayilan_efektler=varsayilan_efektler or [], kaynak=kaynak,
    ), voice_id, hazir)
    if hazir:
        assert_can_be_hazir(meta)
    target_root = hazir_dir(root) if hazir else seslerim_dir(root)
    final = target_root / voice_id
    if final.exists():
        raise VoiceError("Bu adla bir ses zaten var.")
    target_root.mkdir(parents=True, exist_ok=True)
    tmp = target_root / f".tmp-{uuid4().hex}"
    tmp.mkdir()
    try:
        info = sf.info(str(ref_wav))
        if info.channels == 1 and info.format == "WAV":
            shutil.copyfile(str(ref_wav), str(tmp / "ref.wav"))  # birebir kopya
        else:
            audio, sr = sf.read(str(ref_wav), dtype="float32", always_2d=True)
            sf.write(str(tmp / "ref.wav"), audio.mean(axis=1), sr, subtype="PCM_16")
        (tmp / "ref.txt").write_text(ref_text + "\n", encoding="utf-8")
        (tmp / "ses.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        make_sample(tmp / "ref.wav", tmp / "ornek.wav")
        tmp.rename(final)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return _voice_from_dir(final, hazir)


def import_preset(src_dir, root=None):
    """Ses paketindeki bir klasörü hazır ses olarak KOPYALAR (kaynak değişmez)."""
    src = Path(src_dir)
    raw = json.loads((src / "ses.json").read_text(encoding="utf-8"))
    voice_id = _check_id(raw.get("id") or src.name)
    return save_voice(
        ad=raw.get("ad"), ref_wav=src / "ref.wav", ref_text=(src / "ref.txt").read_text(encoding="utf-8"),
        kaynak=raw.get("kaynak"), aciklama=raw.get("aciklama", ""), kategori=raw.get("kategori", "Genel"),
        tarif=raw.get("tarif"), seed=raw.get("seed"), secimler=raw.get("secimler"),
        varsayilan_efektler=raw.get("varsayilan_efektler"), hazir=True, voice_id=voice_id, root=root,
    )


def copy_voice(voice_id, yeni_ad=None, root=None):
    """Hazır ya da kişisel bir sesi Seslerim'e kopyalar (düzenlenebilir hâle gelir)."""
    voice = get_voice(voice_id, root)
    if not voice:
        raise VoiceError("Ses bulunamadı.")
    ad = (yeni_ad or "").strip() or f"{voice['ad']} (kopya)"
    kaynak = voice["kaynak"] or ""
    if "kopya" not in fold(kaynak):
        kaynak = f"{kaynak} (kopya: {voice['id']})".strip()
    return save_voice(
        ad=ad, ref_wav=voice["ref_wav"], ref_text=voice["ref_text"], kaynak=kaynak,
        aciklama=voice["aciklama"], kategori=voice["kategori"], tarif=voice["tarif"],
        seed=voice["seed"], secimler=voice["secimler"],
        varsayilan_efektler=voice["varsayilan_efektler"], hazir=False, root=root,
    )


def delete_voice(voice_id, root=None):
    """Yalnız Seslerim altındaki sesler silinebilir; hazır sesler korunur."""
    _check_id(voice_id)
    if (hazir_dir(root) / voice_id).exists():
        raise VoiceError("Hazır sesler silinemez; kopyalayıp kopyasını düzenleyebilirsiniz.")
    path = (seslerim_dir(root) / voice_id).resolve()
    base = seslerim_dir(root).resolve()
    if path.parent != base or not path.is_dir():
        raise VoiceError("Ses bulunamadı.")
    meta_path = path / "ses.json"
    try:
        if json.loads(meta_path.read_text(encoding="utf-8")).get("hazir"):
            raise VoiceError("Hazır sesler silinemez.")
    except (OSError, ValueError):
        pass
    shutil.rmtree(path)


def update_effects(voice_id, efektler, root=None):
    """Sese efekt ön ayarı yazar; hazır seslerde önce kopyalamak gerekir."""
    voice = get_voice(voice_id, root)
    if not voice:
        raise VoiceError("Ses bulunamadı.")
    if voice["hazir"]:
        raise VoiceError("Hazır seslerin ön ayarı değiştirilemez; önce sesi kopyalayın.")
    path = Path(voice["_dir"]) / "ses.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["varsayilan_efektler"] = list(efektler or [])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return get_voice(voice_id, root)
