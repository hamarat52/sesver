"""Üretim kuyruğu arayüzünün metin ve HTML parçaları (Gradio içe aktarmaz; sayfa dilinde t()).

app.py bu işlevlerin döndürdüğü HTML'i gr.HTML bileşenlerine yazar. Kuyruk listesindeki
düğmeler `data-act` / `data-id` taşır; listenin js_on_load'u tıklamayı tek bir olaya çevirir
(bkz. LISTE_JS). Kullanıcının metni ve dosya adları her zaman escape edilir.
"""
import datetime
import re
from html import escape
from pathlib import Path

import effects as fx
import kuyruk as kq
from i18n import t

# Liste tıklaması: tek dinleyici (innerHTML yenilense de kök öğe aynı kalır).
LISTE_JS = ("element.addEventListener('click', (e) => { const b = e.target.closest('button[data-act]'); "
            "if (!b || b.disabled) return; e.preventDefault(); "
            "trigger('click', {act: b.dataset.act, id: b.dataset.id}); });")

_IC = {
    "dinle": '<path d="M8 5.5v13l11-6.5z" fill="currentColor" stroke="none"/>',
    "klasor": '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "yukari": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "asagi": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "cikar": '<path d="M6 6l12 12M18 6 6 18"/>',
    "kuyruk": '<path d="M4 6.5h11M4 12h11M4 17.5h6"/><path d="m15.5 14.5 5 3-5 3z"/>',
    "ay": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "oynat": '<circle cx="12" cy="12" r="9"/><path d="m10 8.5 5 3.5-5 3.5z"/>',
}


def _ikon(ad, sinif=""):
    cls = f' class="{sinif}"' if sinif else ""
    return (f'<svg{cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{_IC[ad]}</svg>')


# --- Biçimler ---------------------------------------------------------------------------

def sure(sn):
    """Üretim süresi, sayfa dilinde kısa biçim (\"4 dk 12 sn\")."""
    sn = int(round(sn or 0))
    sa, kalan = divmod(sn, 3600)
    dk, s = divmod(kalan, 60)
    if sa:
        return t("{sa} sa {dk} dk", sa=sa, dk=f"{dk:02d}")
    if dk:
        return t("{dk} dk {sn} sn", dk=dk, sn=f"{s:02d}")
    return t("{sn} sn", sn=s)


def ses_uzunlugu(sn):
    sn = int(round(sn or 0))
    return f"{sn // 60}:{sn % 60:02d}"


def saat(iso):
    try:
        return datetime.datetime.fromisoformat(iso).strftime("%H:%M")
    except (TypeError, ValueError):
        return ""


def sayi(n):
    """Binlik ayraçlı tam sayı (Türkçe yazımla nokta: 8.640)."""
    return f"{int(n):,}".replace(",", ".")


# --- Hata ve red nedenleri -------------------------------------------------------------

def hata_metni(kod, tur=None):
    """Kuyruk öğesinin hata kodu → sayfa dilinde kısa neden (hata_raporu.classify_error ile aynı metinler)."""
    metinler = {
        "cuda_kernel": t("CUDA çekirdeği bu kartta yok (kurulu PyTorch bu ekran kartını desteklemiyor)"),
        "cuda_oom": t("CUDA bellek yetersiz (ekran kartı belleği doldu)"),
        "gpu_oom": t("ekran kartı belleği yetersiz"),
        "ram": t("bellek (RAM) yetersiz"),
        "disk": t("disk alanı yetersiz"),
        "download": t("model indirilemedi (internet bağlantısını kontrol edin)"),
        "ref_okunamadi": t("referans ses okunamadı (dosya silinmiş ya da bozuk)"),
    }
    if kod in metinler:
        return metinler[kod]
    return t("beklenmeyen hata ({tur})", tur=tur or "Error")


def red_metni(kod, bilgi=None):
    """KuyrukHatasi kodu → kullanıcıya gösterilecek ileti (sayfa dilinde)."""
    bilgi = bilgi or {}
    metinler = {
        "metin_bos": t("Lütfen okunacak bir metin yazın."),
        "metin_uzun": t("Kuyruktaki bir öğe en fazla {n} karakter olabilir.", n=sayi(kq.OGE_METIN_EN_FAZLA)),
        "rastgele_uzun": t("500 karakterden uzun metin rastgele sesle kuyruğa eklenemez: her parçada başka biri "
                           "konuşabilir. Kayıtlı bir ses seçin ya da metni kısaltın."),
        "ref_yok": t("Referans ses bulunamadı. Sesi yeniden seçin ya da yükleyin."),
        "ref_kopyalanamadi": t("Referans ses kuyruk klasörüne kopyalanamadı (disk dolu ya da yazma izni yok)."),
        "dolu": t("Kuyrukta en fazla {n} öğe olabilir. Yer açmak için “Bitenleri temizle”yi kullanın.",
                  n=kq.KUYRUK_EN_FAZLA),
        "baska_surec": t("Bu kuyruk başka bir SesVer penceresinde çalışıyor; burada değiştirilemez."),
        "calisiyor": t("Kuyruk çalışırken temizlenemez. Önce durdurun."),
        "oge_yok": t("Öğe artık kuyrukta değil."),
        "uretiliyor": t("Üretilmekte olan öğe çıkarılamaz."),
        "durum_gecersiz": t("Bu işlem öğenin şu anki durumunda yapılamaz."),
        "tur_gecersiz": t("İşlem yapılamadı."),
    }
    return metinler.get(kod, t("İşlem yapılamadı."))


def ice_red_metni(r):
    """İçe aktarmada reddedilen satırın nedeni."""
    deger = escape(str(r.get("deger") or ""))
    metinler = {
        "metin_bos": t("Metin boş"),
        "metin_uzun": t("Metin {n} karakterden uzun", n=sayi(kq.OGE_METIN_EN_FAZLA)),
        "rastgele_uzun": t("Uzun metin rastgele sesle olmaz"),
        "bilinmeyen_ses": t("Bilinmeyen ses: “{ad}”", ad=deger),
        "bilinmeyen_duygu": t("Bilinmeyen duygu: “{ad}”", ad=deger),
        "bilinmeyen_kalite": t("Bilinmeyen kalite: “{ad}”", ad=deger),
    }
    return metinler.get(r.get("neden"), t("İşlem yapılamadı."))


def ice_dosya_hatasi(kod):
    return {
        "dosya_bos": t("Dosya boş ya da okunacak metin yok."),
        "dosya_buyuk": t("Dosya çok büyük (en fazla 2 MB)."),
        "metin_sutunu_yok": t("CSV'de “metin” (ya da “text”) sütunu bulunamadı. İlk satır sütun adları olmalı."),
        "kip_gecersiz": t("İşlem yapılamadı."),
    }.get(kod, t("İşlem yapılamadı."))


# --- Öğe görünümü ----------------------------------------------------------------------

def ses_adi(oge):
    if oge.get("tur") == "klon":
        m = re.match(r"^Klon \((.*)\)$", oge.get("ses_adi") or "")
        return t("Klon ({ad})", ad=m.group(1)) if m else t("Klon")
    if (oge.get("ses_id") or kq.RASTGELE) == kq.RASTGELE:
        return "🎲 " + t("Rastgele ses")
    return t(oge.get("ses_adi") or "")  # hazır seslerin adı çevrilir, kendi sesleriniz olduğu gibi kalır


def _efekt_metni(efektler):
    adlar = [f"{t(fx.EFFECTS.get(e.get('ad'), e.get('ad') or ''))} %{e.get('yogunluk')}" for e in efektler or []]
    return t("efekt: {adlar}", adlar=", ".join(adlar)) if adlar else ""


def _meta(oge):
    parcalar = [ses_adi(oge), t(oge.get("duygu") or "Nötr")]
    if oge.get("tur") != "klon":
        parcalar.append(t(oge.get("kalite") or "Dengeli"))
    ef = _efekt_metni(oge.get("efektler"))
    if ef:
        parcalar.append(ef)
    if oge.get("uzun"):
        parcalar.append(t("{n} karakter", n=sayi(len(oge.get("metin") or ""))))
    return [escape(p) for p in parcalar]


def _rozet(sinif, metin):
    return f'<span class="sv-qbadge {sinif}">{escape(metin)}</span>'


def _dugme(act, oid, ikon=None, etiket=None, baslik="", pasif=False, sinif="sv-qicon"):
    ic = _ikon(ikon) if ikon else escape(etiket or "")
    dis = " disabled" if pasif else ""
    return (f'<button type="button" class="{sinif}" data-act="{act}" data-id="{escape(oid)}" '
            f'title="{escape(baslik)}" aria-label="{escape(baslik)}"{dis}>{ic}</button>')


def _kalan_sure(oge, hiz):
    if not hiz:
        return None
    toplam = len(oge.get("metin") or "")
    n, biten = oge.get("parca_sayisi") or 1, oge.get("parca_bitti") or 0
    return hiz * toplam * max(0.0, 1 - biten / n)


def liste_html(d):
    """Kuyruk listesi (taslak A): sıra, metin, ses/ayarlar, durum, süre, eylemler."""
    ogeler = d["ogeler"]
    if not ogeler:
        return ('<div class="sv-qempty">' + t(
            "Kuyruk boş. <b>Ses Kütüphanesi</b> ya da <b>Ses Klonlama</b> sekmesinde “Kuyruğa ekle”ye basın "
            "ya da sağdaki “Dosyadan içe aktar” ile bir TXT/CSV dosyası ekleyin.") + "</div>")
    salt = d.get("salt_okunur")
    hiz = d.get("hiz_sn_karakter")
    bekleyen = [o["id"] for o in ogeler if o["durum"] == kq.BEKLIYOR]
    satirlar = []
    for i, oge in enumerate(ogeler, 1):
        durum = oge["durum"]
        no = f"{oge['no']:02d}" if oge.get("no") else f"{i:02d}"
        metin = (oge.get("metin") or "").replace("\n", " ")
        meta = _meta(oge)
        if oge.get("uzun"):
            meta.insert(0, _rozet("b-long", t("uzun · {n} parça", n=oge["parca_sayisi"])))
        if durum == kq.BITTI and oge.get("cikti"):
            ad = Path(oge.get("efektli") or oge["cikti"]).name
            meta.append(f'<span class="sv-qfile" dir="ltr">{escape(ad)}</span>')
        if durum == kq.HATA:
            neden = hata_metni(oge.get("hata_kodu"), oge.get("hata_turu"))
            ek = ""
            if oge.get("uzun") and oge.get("hata_parca"):
                ek = " · " + t("parça {i}/{n}", i=oge["hata_parca"], n=oge["parca_sayisi"])
            meta.insert(0, f'<span class="sv-qerr">{escape(t("Hata: {neden}", neden=neden) + ek)}</span>')
        if durum == kq.BEKLIYOR and oge.get("yarida_kaldi"):
            meta.insert(0, f'<span class="sv-qwarn">{escape(t("yarıda kalmıştı, kaldığı yerden sürecek"))}</span>')
        if durum == kq.BEKLIYOR and oge.get("son_hata_kodu"):
            neden = hata_metni(oge["son_hata_kodu"])
            meta.insert(0, f'<span class="sv-qwarn">{escape(t("bekletildi: {neden}", neden=neden))}</span>')
        parcalar = ""
        if durum == kq.URETILIYOR and oge.get("uzun"):
            noktalar = []
            for j in range(1, oge["parca_sayisi"] + 1):
                cls = "d" if j <= oge["parca_bitti"] else ("a" if j == oge.get("aktif_parca") else "")
                noktalar.append(f'<i class="{cls}"></i>')
            parcalar = '<div class="sv-qparts" aria-hidden="true">' + "".join(noktalar) + "</div>"
        # Durum rozeti ve süre
        zaman = ""
        if durum == kq.BITTI:
            rozet = _rozet("b-ok", t("bitti"))
            zaman = sure(oge.get("sure_sn"))
            if oge.get("ses_sn"):
                zaman += " · " + t("ses {sure}", sure=ses_uzunlugu(oge["ses_sn"]))
        elif durum == kq.HATA:
            rozet = _rozet("b-err", t("hata"))
            zaman = sure(oge.get("sure_sn")) if oge.get("sure_sn") else ""
        elif durum == kq.URETILIYOR:
            rozet = _rozet("b-run", t("parça {i}/{n}", i=oge.get("aktif_parca") or 1, n=oge["parca_sayisi"])
                           if oge.get("uzun") else t("üretiliyor"))
            kalan = _kalan_sure(oge, hiz)
            zaman = t("kalan ~{sure}", sure=sure(kalan)) if kalan else t("başladı {saat}", saat=saat(oge.get("baslangic")))
        else:
            rozet = _rozet("b-wait", t("bekliyor"))
            kalan = _kalan_sure(oge, hiz)
            zaman = "~" + sure(kalan) if kalan else ""
        # Eylemler
        eylem = []
        oid = oge["id"]
        if not salt:
            if durum == kq.BEKLIYOR:
                eylem.append(_dugme("yukari", oid, "yukari", baslik=t("Yukarı taşı"), pasif=oid == bekleyen[0]))
                eylem.append(_dugme("asagi", oid, "asagi", baslik=t("Aşağı taşı"), pasif=oid == bekleyen[-1]))
                eylem.append(_dugme("cikar", oid, "cikar", baslik=t("Kuyruktan çıkar")))
            elif durum == kq.URETILIYOR:
                eylem.append(_dugme("cikar", oid, "cikar", baslik=t("Üretilirken çıkarılamaz"), pasif=True))
            elif durum == kq.HATA:
                eylem.append(_dugme("yeniden", oid, etiket=t("Yeniden dene"), baslik=t("Yeniden dene"),
                                    sinif="sv-qmini"))
                eylem.append(_dugme("cikar", oid, "cikar", baslik=t("Kuyruktan çıkar")))
        if durum == kq.BITTI and oge.get("cikti"):
            eylem.append(_dugme("dinle", oid, "dinle", baslik=t("Dinle")))
            eylem.append(_dugme("klasor", oid, "klasor", baslik=t("Klasörde göster")))
        sinif = {kq.URETILIYOR: " is-run", kq.HATA: " is-err", kq.BITTI: " is-done"}.get(durum, "")
        satirlar.append(
            f'<div class="sv-qrow{sinif}"><span class="sv-qno">{no}</span>'
            f'<div class="sv-qmain"><div class="sv-qtext" dir="auto">{escape(metin)}</div>'
            f'<div class="sv-qmeta">{" · ".join(meta)}</div>{parcalar}</div>'
            f'<div class="sv-qstate">{rozet}<span class="sv-qtime">{escape(zaman)}</span></div>'
            f'<div class="sv-qact">{"".join(eylem)}</div></div>')
    return '<div class="sv-qlist">' + "".join(satirlar) + "</div>"


def _stat(sayi_, etiket, renk=None):
    stil = f' style="color:{renk}"' if renk else ""
    return f'<span class="sv-qstat"><b{stil}>{escape(str(sayi_))}</b> {escape(etiket)}</span>'


def ozet_html(d, simdi=None):
    """Özet hapları: öğe sayıları, geçen süre, tahmini bitiş."""
    ogeler, s = d["ogeler"], d["sayilar"]
    if not ogeler:
        return ""
    parcalar = [_stat(len(ogeler), t("öğe")), _stat(s[kq.BITTI], t("bitti"), "#17824A")]
    if s[kq.URETILIYOR]:
        parcalar.append(_stat(s[kq.URETILIYOR], t("üretiliyor"), "#B4432A"))
    parcalar.append(_stat(s[kq.BEKLIYOR], t("bekliyor")))
    if s[kq.HATA]:
        parcalar.append(_stat(s[kq.HATA], t("hata"), "#B3261E"))
    if d.get("toplam_sure_sn"):
        parcalar.append(f'<span class="sv-qstat">{escape(t("geçen"))} <b>{escape(sure(d["toplam_sure_sn"]))}</b></span>')
    kalan = d.get("kalan_tahmini_sn")
    if kalan and (s[kq.BEKLIYOR] or s[kq.URETILIYOR]):
        bitis = (simdi or datetime.datetime.now()) + datetime.timedelta(seconds=kalan)
        parcalar.append(f'<span class="sv-qstat">{escape(t("tahmini bitiş"))} '
                        f'<b>{bitis.strftime("%H:%M")}</b></span>')
    return '<div class="sv-qsummary">' + "".join(parcalar) + "</div>"


def duraklatma_metni(d):
    """Kuyruk duraklatıldıysa nedeni (sayfa dilinde), yoksa boş."""
    if d.get("salt_okunur"):
        return t("Bu kuyruk başka bir SesVer penceresinde çalışıyor; burada yalnız görüntülenir.")
    if d.get("kayit_hatasi"):
        return t("Kuyruk kaydı diske yazılamadı ({hata}). Disk alanını ve klasör iznini kontrol edin.",
                 hata=d["kayit_hatasi"])
    dur = d.get("duraklatma") or {}
    if d["durum"] != kq.DURAKLATILDI or not dur:
        return ""
    neden = dur.get("neden")
    if neden == "kullanici":
        return t("Durduruldu. Kalan öğeler bekliyor; “Devam et” ile kaldığı yerden sürer.")
    if neden == "yeniden_acilis":
        return t("Önceki oturumdan kalan öğeler var. Kuyruk kendiliğinden başlamaz; “Devam et” ile sürer.")
    if neden in ("download", "disk"):
        return t("Art arda iki öğe aynı nedenle üretilemedi: {neden}. Kuyruk duraklatıldı, öğeler kaybolmadı; "
                 "sorunu giderip “Devam et”e basın.", neden=hata_metni(neden))
    if neden == "blok":
        return t("Kuyruk duraklatıldı: {neden}", neden=dur.get("ayrinti") or "")
    return t("Kuyruk beklenmedik bir hatayla duraklatıldı; ayrıntı sesver_log.txt. “Devam et” ile yeniden deneyin.")


def ust_dugme(d):
    """Sağ üstteki Kuyruk düğmesi: (etiket, durum sınıfı). Çalışırken \"Kuyruk 3/10\"."""
    ogeler = d["ogeler"] if d else []
    if not ogeler:
        return t("Kuyruk"), "is-empty"
    s = d["sayilar"]
    if d["durum"] in (kq.CALISIYOR, kq.DURUYOR):
        sira = s[kq.BITTI] + s[kq.HATA] + (1 if s[kq.URETILIYOR] else 0)
        return t("Kuyruk {sira}/{toplam}", sira=max(1, sira), toplam=len(ogeler)), "is-running"
    if s[kq.BEKLIYOR]:
        return t("Kuyruk · {n} bekliyor", n=s[kq.BEKLIYOR]), "is-waiting"
    return t("Kuyruk · {n} bitti", n=s[kq.BITTI]), ("is-error" if s[kq.HATA] else "is-done")


def ana_dugme(d):
    """Başlat / Devam et / Durdur düğmesi: (etiket, etkin mi, durdur mu)."""
    durum = d["durum"]
    if durum == kq.CALISIYOR:
        return t("Durdur"), True, True
    if durum == kq.DURUYOR:
        return t("Duruyor…"), False, True
    bekleyen = d["sayilar"][kq.BEKLIYOR]
    if not bekleyen or d.get("salt_okunur"):
        return t("Başlat"), False, False
    return (t("Devam et") if durum == kq.DURAKLATILDI else t("Başlat")), True, False


def simdi_html(d):
    """Sağ kolondaki \"Şu an üretiliyor\" kartı."""
    aktif = next((o for o in d["ogeler"] if o["durum"] == kq.URETILIYOR), None)
    if aktif is None:
        ikon = '<span class="sv-head-ic">' + _ikon("kuyruk", "sv-ic") + "</span>"
        s = d["sayilar"]
        if d["durum"] == kq.TAMAMLANDI and d["ogeler"]:
            alt = t("Kuyruk tamamlandı: {bitti} bitti, {hata} hata.", bitti=s[kq.BITTI], hata=s[kq.HATA])
        elif s[kq.BEKLIYOR]:
            alt = t("Kuyruk çalışmıyor. “Başlat”a basınca öğeler sırayla üretilir; pencereyi açık bırakın.")
        else:
            alt = t("Kuyruk boş.")
        return (f'<div class="sv-head">{ikon}<div><h3>{escape(t("Kuyruk durumu"))}</h3>'
                f'<p>{escape(alt)}</p></div></div>')
    play = '<span class="sv-head-ic">' + _ikon("oynat", "sv-ic") + "</span>"
    no = f"{aktif['no']:02d}" if aktif.get("no") else "--"
    ozet = (aktif.get("metin") or "").replace("\n", " ")
    ozet = ozet[:48] + ("…" if len(ozet) > 48 else "")
    n, biten = aktif["parca_sayisi"], aktif["parca_bitti"]
    yuzde = int(round(100 * biten / n)) if n else 0
    durum = (t("<b>Parça {i}/{n}</b> üretiliyor · başladı {saat}", i=aktif.get("aktif_parca") or 1, n=n,
               saat=saat(aktif.get("baslangic"))) if aktif.get("uzun")
             else t("<b>Üretiliyor</b> · başladı {saat}", saat=saat(aktif.get("baslangic"))))
    if aktif.get("uzun") and (aktif.get("aktif_parca") or 1) < n:
        durum += "<br>" + escape(t("Sonra parça {i} üretilecek.", i=(aktif.get("aktif_parca") or 1) + 1))
    kalan = _kalan_sure(aktif, d.get("hiz_sn_karakter"))
    if kalan:
        alt = t("Öğe: %{yuzde} tamamlandı · kalan tahmini <b>{sure}</b> (bu oturumda ölçülen hıza göre)",
                yuzde=yuzde, sure=escape(sure(kalan)))
    else:
        alt = t("Öğe: %{yuzde} tamamlandı · kalan süre ilk parça bitince hesaplanır", yuzde=yuzde)
    elle = ""
    if d.get("elle_bekleyen"):
        elle = ('<p class="sv-qnote">' + escape(t("Elle başlatılan bir üretim sırada: bu parça bitince araya "
                                                    "girecek, ardından kuyruk sürecek.")) + "</p>")
    return (f'<div class="sv-head">{play}<div><h3>{escape(t("Şu an üretiliyor"))}</h3>'
            f'<p><span dir="auto">{no} · {escape(ozet)}</span> · {escape(ses_adi(aktif))}</p></div></div>'
            f'<div class="sv-qnow">{durum}</div>'
            f'<div class="sv-qbar"><i style="width:{yuzde}%"></i></div><p class="sv-qfine">{alt}</p>{elle}')


def gece_html(d, pilde=None, model_var=True, bos_gb=None):
    """\"Gece boyunca\" kartı: çıktı klasörü, uyku engeli, prize/kapak uyarısı, disk/model notları."""
    klasor = d.get("oturum_klasoru")
    goster = "outputs/kuyruk/" + Path(klasor).name if klasor else "outputs/kuyruk/"
    ay = _ikon("ay", "sv-ic")
    parca = [f'<div class="sv-head"><span class="sv-head-ic">{ay}</span><div><h3>{escape(t("Gece boyunca"))}</h3>'
             f'<p>{escape(t("Çıktılar:"))} <span dir="ltr">{escape(goster)}</span></p></div></div>']
    if d["durum"] in (kq.CALISIYOR, kq.DURUYOR):
        parca.append('<div class="sv-qok">' + t("<b>Uyku engeli açık.</b> Bilgisayar boşta uyumaz; "
                                                 "ekran kapanabilir.") + "</div>")
    else:
        parca.append('<p class="sv-qfine">' + escape(t("Kuyruk çalışırken bilgisayar boşta uyumaz; ekran "
                                                         "kapanabilir.")) + "</p>")
    parca.append('<div class="sv-qwarnbox">' + t("Prize takılı ve <b>kapağı açık</b> bırakın. Kapak kapanırsa "
                                                  "bilgisayar uyur.") + "</div>")
    if pilde:
        parca.append('<div class="sv-qwarnbox">' + escape(t("Bilgisayar şu an pilde çalışıyor. Gece boyu sürmesi "
                                                             "için prize takın.")) + "</div>")
    if not model_var:
        parca.append('<div class="sv-qwarnbox">' + escape(t("İlk öğede ses modeli (~5 GB) indirilecek; internet "
                                                             "açık kalmalı.")) + "</div>")
    if bos_gb is not None and bos_gb < 1:
        parca.append('<div class="sv-qwarnbox">' + escape(t("Diskte {gb} GB boş yer kaldı; en az 1 GB önerilir.",
                                                             gb=f"{bos_gb:.1f}")) + "</div>")
    return "".join(parca)


def banner_html(d):
    n = d["sayilar"][kq.BEKLIYOR]
    return '<span>' + t("Önceki oturumdan <b>{n}</b> bekleyen üretim var. Kuyruk kendiliğinden başlamaz.",
                        n=n) + "</span>"


def banner_gorunur_mu(d):
    dur = d.get("duraklatma") or {}
    return (d["durum"] == kq.DURAKLATILDI and dur.get("neden") == "yeniden_acilis"
            and d["sayilar"][kq.BEKLIYOR] > 0 and not d.get("salt_okunur"))


# --- İçe aktarma önizlemesi (taslak D) ------------------------------------------------

_KODLAMA = {"utf-8": "UTF-8", "utf-8-sig": "UTF-8 (BOM)", "utf-16": "UTF-16", "cp1254": None}


def ice_dosya_html(ad, oz, csv_mi):
    kodlama = _KODLAMA.get(oz.kodlama, oz.kodlama) or t("Türkçe Windows (Windows-1254)")
    bilgi = [kodlama]
    if csv_mi:
        bilgi.append({";": t("“;” ayraçlı"), ",": t("“,” ayraçlı"), "\t": t("sekme ayraçlı")}.get(oz.ayrac, ""))
        if oz.yok_sayilan_sutunlar:
            bilgi.append(t("yok sayılan sütunlar: {adlar}", adlar=", ".join(oz.yok_sayilan_sutunlar[:6])))
    tur = "CSV" if csv_mi else "TXT"
    return (f'<div class="sv-ifile"><span class="sv-ifi">{tur}</span><div><b dir="auto">{escape(ad)}</b>'
            f'<div class="sv-qfine">{escape(" · ".join(b for b in bilgi if b))}</div></div></div>')


def ice_onizleme(tum, sinirli, kuyrukta):
    """(özet HTML, uyarı HTML, tablo HTML, eklenecek sayısı).

    tum: sınırsız önizleme (tüm kabul edilen satırlar), sinirli: kuyruğun kalan yerine göre.
    """
    if tum.hata:
        return "", '<div class="sv-qwarnbox">' + escape(ice_dosya_hatasi(tum.hata)) + "</div>", "", 0
    eklenecek = len(sinirli.ogeler)
    asan = set(sinirli.asan)
    okunan = len(tum.ogeler) + len(tum.reddedilen)
    uzun = sum(len(o["metin"]) > kq.PARCA_EN_FAZLA for o in sinirli.ogeler)
    ozet = [_stat(okunan, t("satır okundu")), _stat(eklenecek, t("eklenecek"), "#17824A")]
    if tum.reddedilen:
        ozet.append(_stat(len(tum.reddedilen), t("reddedildi"), "#B3261E"))
    if asan:
        ozet.append(_stat(len(asan), t("sınır nedeniyle eklenmeyecek")))
    if uzun:
        ozet.append(_stat(uzun, t("uzun öğe (parçalanacak)")))
    uyari = ""
    if asan:
        uyari = ('<div class="sv-qwarnbox">' + t(
            "Kuyrukta şu an <b>{var}</b> öğe var; en fazla <b>{n}</b>. {satirlar} eklenmeyecek. Yer açmak için "
            "“Bitenleri temizle”yi kullanabilirsiniz.", var=kuyrukta, n=kq.KUYRUK_EN_FAZLA,
            satirlar=escape(t("Satır {liste}", liste=", ".join(str(x) for x in sorted(asan)[:8])))) + "</div>")
    satirlar = []
    for o in tum.ogeler:
        uz = sayi(len(o["metin"]))
        parca = ""
        if len(o["metin"]) > kq.PARCA_EN_FAZLA:
            import metin_bolme
            parca = " " + _rozet("b-long", t("{n} parça", n=len(metin_bolme.bol(o["metin"], kq.PARCA_EN_FAZLA))))
        if o["satir"] in asan:
            durum, sinif = escape(t("50 öğe sınırı")), "over"
        else:
            durum, sinif = _rozet("b-ok", t("eklenecek")), ""
        satirlar.append((o["satir"], f'<tr class="{sinif}"><td>{o["satir"]}</td>'
                                     f'<td class="t" dir="auto">{escape(_kisalt(o["metin"]))}</td>'
                                     f'<td>{escape(ses_adi(o))}</td>'
                                     f'<td>{escape(t(o["duygu"]))} · {escape(t(o["kalite"]))}</td>'
                                     f'<td>{uz}{parca}</td><td>{durum}</td></tr>'))
    for r in tum.reddedilen:
        ozet_metin = r.get("ozet") or ""
        metin = escape(ozet_metin) if ozet_metin else f'<i>{escape(t("(boş)"))}</i>'
        satirlar.append((r["satir"], f'<tr class="rej"><td>{r["satir"]}</td><td class="t" dir="auto">{metin}</td>'
                                     f'<td>–</td><td>–</td><td>{sayi(r.get("uzunluk") or 0)}</td>'
                                     f'<td class="sv-ireason">✕ {ice_red_metni(r)}</td></tr>'))
    satirlar.sort(key=lambda x: x[0])
    bas = "".join(f"<th>{escape(b)}</th>" for b in (t("Satır"), t("Metin"), t("Ses"), t("Duygu · kalite"),
                                                     t("Uzunluk"), t("Durum")))
    tablo = (f'<div class="sv-itable"><table><thead><tr>{bas}</tr></thead><tbody>'
             + "".join(s for _, s in satirlar) + "</tbody></table></div>")
    return '<div class="sv-qsummary">' + "".join(ozet) + "</div>", uyari, tablo, eklenecek


def _kisalt(metin, n=70):
    metin = re.sub(r"\s+", " ", metin or "").strip()
    return metin[:n] + ("…" if len(metin) > n else "")
