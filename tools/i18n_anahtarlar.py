"""Çevrilecek Türkçe kaynak metinleri toplar → locales/_kaynak.json (sıralı anahtar listesi).

Kaynaklar:
  * app.py / desktop.py içinde t("...") çağrılarının sabit (literal) ilk argümanı
  * t()/tr_message() ile çalışma anında çevrilen veri metinleri: duygu/kalite/efekt/oda
    adları, ses tasarımı haritası (grup etiketleri, seçenekler, şablonlar, uyarılar,
    örnek metin türleri), hazır seslerin meta verisi
  * voice_library / audio_prep / voice_designer'ın kullanıcıya dönen hata/uyarı
    iletileri (f-string'ler {yer tutucu} kalıbına çevrilir; i18n.tr_message eşler)
  * hata_rehberi metinleri
  * hata_raporu.py içindeki t("...") çağrıları (hata türleri, rapor/e-posta iletileri)
Kullanım: python tools/i18n_anahtarlar.py [--check]
--check: her locales/<dil>.json dosyasında eksik/fazla anahtar ve yer tutucu uyuşmazlığı arar.
"""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _src(node, code):
    return ast.get_source_segment(code, node)


def _template(node, code):
    """Constant → metin; JoinedStr (f-string) → '{ifade}' yer tutuculu kalıp."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                out.append(part.value)
            else:  # FormattedValue: kaynaktaki hâliyle {ifade[!c][:biçim]}
                expr = ast.unparse(part.value)
                conv = "" if part.conversion == -1 else "!" + chr(part.conversion)
                spec = ""
                if part.format_spec is not None:
                    spec = ":" + "".join(p.value for p in part.format_spec.values if isinstance(p, ast.Constant))
                out.append("{" + expr + conv + spec + "}")
        return "".join(out)
    return None


def t_literals(path):
    code = path.read_text(encoding="utf-8")
    keys = []
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t" and node.args:
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                keys.append((node.lineno, a.value))
    return [k for _, k in sorted(keys)]


def module_messages(path, call_names=("VoiceError", "PermissionError", "PrepError"), append_targets=("warnings", "uyarilar")):
    code = path.read_text(encoding="utf-8")
    found = []
    for node in ast.walk(ast.parse(code)):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        f = node.func
        hit = (isinstance(f, ast.Name) and f.id in call_names) or (
            isinstance(f, ast.Attribute) and f.attr == "append" and isinstance(f.value, ast.Name)
            and f.value.id in append_targets)
        if hit:
            tpl = _template(node.args[0], code)
            if tpl and re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]", tpl):
                found.append((node.lineno, tpl))
    return [k for _, k in sorted(found)]


def collect():
    import app
    import audio_prep
    import effects as fx
    import hata_rehberi

    keys = []
    keys += t_literals(ROOT / "app.py")
    keys += [app._SAMPLE_TEXT, app.SIMILARITY_NOTE, app.SHORT_SAMPLE_WARNING, app.TEXTURE_WARNING,
             audio_prep.CLEAN_NOTE, "Genel"]
    keys += list(app.EMOTIONS) + list(app.QUALITY)
    keys += list(fx.EFFECTS.values()) + [v[0] for v in fx.ROOM_PRESETS.values()]
    rc = app._RANDOM_CARD
    keys += [rc["ad"], rc["kategori"], rc["aciklama"]]
    for v in app.vlib.list_voices():
        if v["hazir"]:
            keys += [v["ad"], v["kategori"] or "", v["aciklama"] or ""]
    m = app._DMAP
    keys.append(m.get("bos_secenek", "Fark etmez"))
    for g in m["gruplar"].values():
        keys.append(g["etiket"])
        keys.append(g["etiket"].split(" (")[0])  # voice_designer uyarısındaki kısa grup adı
        keys += list(g["secenekler"])
    keys += list(m["sablonlar"]) + list(m["kategori_etiketleri"].values())
    keys += [u["mesaj"] for u in m.get("uyarilar", [])]
    keys += module_messages(ROOT / "voice_library.py")
    keys += module_messages(ROOT / "audio_prep.py")
    keys += module_messages(ROOT / "voice_designer.py")
    keys += [hata_rehberi._ADIMLAR, hata_rehberi._OLASI_EK]
    keys += t_literals(ROOT / "desktop.py")
    keys += t_literals(ROOT / "hata_raporu.py")
    seen, out = set(), []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


_PH = re.compile(r"\{[^{}]*\}")
_TAG = re.compile(r"</?[a-z0-9]+[^>]*>", re.I)


def check(keys):
    ok = True
    for f in sorted((ROOT / "locales").glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = {k: v for k, v in json.loads(f.read_text(encoding="utf-8")).items() if not k.startswith("_")}
        missing = [k for k in keys if k not in data]
        extra = [k for k in data if k not in keys]
        bad = [k for k in keys if k in data and (sorted(_PH.findall(k)) != sorted(_PH.findall(data[k]))
                                                 or sorted(_TAG.findall(k)) != sorted(_TAG.findall(data[k])))]
        empty = [k for k in keys if k in data and not data[k].strip()]
        print(f"{f.name}: {len(data)} çeviri, eksik {len(missing)}, fazla {len(extra)}, "
              f"yer tutucu/etiket uyuşmazlığı {len(bad)}, boş {len(empty)}")
        for k in (missing + bad + empty)[:10]:
            print("   !", k[:100])
        ok = ok and not (missing or extra or bad or empty)
    return ok


if __name__ == "__main__":
    keys = collect()
    if "--check" in sys.argv:
        sys.exit(0 if check(keys) else 1)
    out = ROOT / "locales" / "_kaynak.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(keys, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(len(keys), "anahtar →", out)
