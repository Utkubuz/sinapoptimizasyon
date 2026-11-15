"""Girdi verisinin tutarlılık kontrolleri.

Veritabanı yabancı anahtar ve CHECK kısıtlarıyla bozuk satırları zaten reddeder; bu modül kayıt öncesinde
*anlamlı* hata mesajları üretir (veritabanı kurallarının hepsini önceden denetler) ve veritabanının yakalayamadığı
mantık sorunlarını uyarı olarak bildirir. Örnek: "BIL101: özel gereksinimler uygun salonlarla karşılanamıyor".
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date

from sinav_takvimi.domain.modeller import (
    DERSLIK_TURLERI,
    DONEM_TURLERI,
    GEREKLI_POLITIKALAR,
    KURAL_TURLERI,
    OZEL_DERSLIK_TURU,
    TUM_POLITIKALAR,
    UNVANLAR,
    UYGUN_DERSLIK_TURLERI,
    VeriSeti,
    gereken_sure,
)

_SAAT = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _tarih_gecerli(metin: str) -> bool:
    try:
        date.fromisoformat(metin)
        return True
    except ValueError:
        return False


def _dakika(saat: str) -> int:
    s, d = saat.split(":")
    return int(s) * 60 + int(d)


def _tekrarlar(ad: str, degerler: Iterable[object], hatalar: list[str]) -> None:
    for deger, adet in Counter(degerler).items():
        if adet > 1:
            hatalar.append(f"Tekrarlanan {ad}: {deger} ({adet} kez)")


def veri_kontrol(veri: VeriSeti) -> tuple[list[str], list[str]]:
    """(hatalar, uyarilar) döndürür. Hata varsa veri kaydedilemez; uyarılar bilgi amaçlıdır."""
    hatalar: list[str] = []
    uyarilar: list[str] = []

    # ------------------------------------------------------------------ 1. Değer aralıkları
    d0 = veri.donem
    if d0 is None:
        hatalar.append("Sınav dönemi tanımlı değil.")
    else:
        if d0.tur not in DONEM_TURLERI:
            hatalar.append(f"Dönem türü geçersiz: '{d0.tur}'")
        if not (_tarih_gecerli(d0.baslangic) and _tarih_gecerli(d0.bitis)):
            hatalar.append("Dönem tarihleri YYYY-AA-GG biçiminde olmalı.")
        elif d0.bitis < d0.baslangic:
            hatalar.append("Dönem bitişi başlangıçtan önce.")
    if not veri.dilimler:
        hatalar.append("Hiç sınav oturumu (dilim) yok.")

    for p in veri.personeller:
        if p.unvan not in UNVANLAR:
            hatalar.append(f"{p.ad}: geçersiz unvan '{p.unvan}'.")
        if p.kota_carpani <= 0:
            hatalar.append(f"{p.ad}: kota çarpanı pozitif olmalı.")
        if p.gunluk_max < 0:
            hatalar.append(f"{p.ad}: günlük görev üst sınırı negatif olamaz.")
    for d in veri.dersler:
        if not 1 <= d.zorluk <= 5:
            hatalar.append(f"{d.kod}: zorluk 1–5 arasında olmalı ({d.zorluk}).")
        if not 1 <= d.sinif <= 4:
            hatalar.append(f"{d.kod}: sınıf 1–4 arasında olmalı ({d.sinif}).")
        if d.sinav_suresi_dk <= 0:
            hatalar.append(f"{d.kod}: sınav süresi pozitif olmalı.")
        if d.sinav_turu not in UYGUN_DERSLIK_TURLERI:
            hatalar.append(f"{d.kod}: geçersiz sınav türü '{d.sinav_turu}'.")
    for o in veri.ogrenciler:
        if not 1 <= o.sinif <= 4:
            hatalar.append(f"Öğrenci {o.no}: sınıf 1–4 arasında olmalı.")
    for g in veri.gereksinimler:
        if not 0 <= g.ek_sure_orani <= 1:
            hatalar.append(f"Öğrenci {g.ogrenci_id}: ek süre oranı 0–1 arasında olmalı ({g.ek_sure_orani}).")
    for r in veri.derslikler:
        if r.tur not in DERSLIK_TURLERI:
            hatalar.append(f"{r.kod}: geçersiz derslik türü '{r.tur}'.")
        if r.kapasite <= 0 or r.sinav_kapasitesi <= 0:
            hatalar.append(f"{r.kod}: kapasiteler pozitif olmalı.")
        if r.sinav_kapasitesi > r.kapasite:
            hatalar.append(f"{r.kod}: sınav kapasitesi ({r.sinav_kapasitesi}) normal kapasiteden ({r.kapasite}) büyük.")
    for dl in veri.dilimler:
        if dl.sure_dk <= 0:
            hatalar.append(f"Dilim {dl.id}: süre pozitif olmalı.")
        if not _tarih_gecerli(dl.tarih):
            hatalar.append(f"Dilim {dl.id}: tarih YYYY-AA-GG biçiminde olmalı ('{dl.tarih}').")
        if not _SAAT.match(dl.baslangic):
            hatalar.append(f"Dilim {dl.id}: başlangıç SS:DD biçiminde olmalı ('{dl.baslangic}').")
        if d0 is not None and dl.donem_id != d0.id:
            hatalar.append(f"Dilim {dl.id} başka bir döneme ait.")
    for r in veri.derslikler:
        if r.gozetmen_sayisi < 1:
            hatalar.append(f"{r.kod}: gözetmen sayısı en az 1 olmalı.")
    politikalar = {p.anahtar: p for p in veri.politikalar}
    for anahtar in GEREKLI_POLITIKALAR:
        if anahtar not in politikalar:
            hatalar.append(f"Kurum politikası eksik: '{anahtar}'.")
    for anahtar, (alt, ust, _) in TUM_POLITIKALAR.items():
        if anahtar in politikalar and not alt <= politikalar[anahtar].deger <= ust:
            hatalar.append(
                f"Kurum politikası '{anahtar}' {alt:g}–{ust:g} arasında olmalı ({politikalar[anahtar].deger})."
            )
    if "gunluk_sinav_ust_siniri" in politikalar and politikalar["gunluk_sinav_ust_siniri"].deger % 1:
        hatalar.append("Kurum politikası 'gunluk_sinav_ust_siniri' tam sayı olmalı.")
    for pol in veri.politikalar:
        if not pol.kaynak.strip():
            hatalar.append(f"Kurum politikası '{pol.anahtar}': kaynak yazılmalı (yönerge maddesi ya da 'varsayım: …').")
        if pol.anahtar not in TUM_POLITIKALAR:
            uyarilar.append(f"Bilinmeyen kurum politikası '{pol.anahtar}' (kullanılmayacak).")
    _tekrarlar("kurum politikası", (p.anahtar for p in veri.politikalar), hatalar)
    for k in veri.dilim_kurallari:
        if k.tur not in KURAL_TURLERI:
            hatalar.append(f"Kural türü geçersiz: '{k.tur}' (ders {k.ders_id}).")

    # ------------------------------------------------------------------ 2. Tekrarlar
    _tekrarlar("bölüm", (b.id for b in veri.bolumler), hatalar)
    _tekrarlar("bölüm kodu", (b.kod for b in veri.bolumler), hatalar)
    _tekrarlar("personel", (p.id for p in veri.personeller), hatalar)
    _tekrarlar("ders", (d.id for d in veri.dersler), hatalar)
    _tekrarlar("ders kodu", (d.kod for d in veri.dersler), hatalar)
    _tekrarlar("öğrenci", (o.id for o in veri.ogrenciler), hatalar)
    _tekrarlar("öğrenci no", (o.no for o in veri.ogrenciler), hatalar)
    _tekrarlar("gereksinim kaydı (öğrenci)", (g.ogrenci_id for g in veri.gereksinimler), hatalar)
    _tekrarlar("kayıt (öğrenci, ders)", veri.kayitlar, hatalar)
    _tekrarlar("derslik", (r.id for r in veri.derslikler), hatalar)
    _tekrarlar("derslik kodu", (r.kod for r in veri.derslikler), hatalar)
    _tekrarlar("dilim", (dl.id for dl in veri.dilimler), hatalar)
    _tekrarlar("dilim (gün, sıra)", ((dl.gun, dl.sira) for dl in veri.dilimler), hatalar)
    _tekrarlar("sabit/yasak kural (ders, dilim)", ((k.ders_id, k.dilim_id) for k in veri.dilim_kurallari), hatalar)

    # ------------------------------------------------------------------ 3. Referans bütünlüğü
    bolumler = {b.id for b in veri.bolumler}
    personel = {p.id for p in veri.personeller}
    ogrenciler = {o.id for o in veri.ogrenciler}
    dersler = {d.id: d for d in veri.dersler}
    derslikler = {r.id for r in veri.derslikler}
    dilimler = {dl.id: dl for dl in veri.dilimler}

    for p in veri.personeller:
        if p.bolum_id not in bolumler:
            hatalar.append(f"{p.ad}: bölümü ({p.bolum_id}) yok.")
    for o in veri.ogrenciler:
        if o.bolum_id not in bolumler:
            hatalar.append(f"Öğrenci {o.no}: bölümü ({o.bolum_id}) yok.")
    for d in veri.dersler:
        if d.hoca_id not in personel:
            hatalar.append(f"{d.kod}: hocası ({d.hoca_id}) personel listesinde yok.")
        if d.asistan_id is not None and d.asistan_id not in personel:
            hatalar.append(f"{d.kod}: asistanı ({d.asistan_id}) personel listesinde yok.")
        if d.bolum_id is not None and d.bolum_id not in bolumler:
            hatalar.append(f"{d.kod}: bölümü ({d.bolum_id}) yok.")
    for o_id, d_id in veri.kayitlar:
        if o_id not in ogrenciler or d_id not in dersler:
            hatalar.append(f"Geçersiz kayıt: öğrenci {o_id} → ders {d_id}")
    for g in veri.gereksinimler:
        if g.ogrenci_id not in ogrenciler:
            hatalar.append(f"Gereksinim kaydı olan öğrenci ({g.ogrenci_id}) yok.")
    for k_id, p_id in veri.personel_musait_degil:
        if k_id not in personel or p_id not in dilimler:
            hatalar.append(f"Geçersiz personel müsaitlik kaydı: {k_id} / {p_id}")
    for r_id, p_id in veri.derslik_musait_degil:
        if r_id not in derslikler or p_id not in dilimler:
            hatalar.append(f"Geçersiz derslik müsaitlik kaydı: {r_id} / {p_id}")
    for k in veri.dilim_kurallari:
        if k.ders_id not in dersler or k.dilim_id not in dilimler:
            hatalar.append(f"Geçersiz sabit/yasak kural: ders {k.ders_id} / dilim {k.dilim_id}")

    # ------------------------------------------------------------------ 4. Oturumlar zaman olarak çakışmamalı
    gunluk: dict[str, list] = defaultdict(list)
    for dl in veri.dilimler:
        if _SAAT.match(dl.baslangic):
            gunluk[dl.tarih].append(dl)
    for tarih, liste in gunluk.items():
        liste.sort(key=lambda x: _dakika(x.baslangic))
        for a, b in zip(liste, liste[1:], strict=False):
            if _dakika(a.baslangic) + a.sure_dk > _dakika(b.baslangic):
                hatalar.append(f"{tarih} {a.baslangic} oturumu {b.baslangic} oturumuyla çakışıyor.")
            if a.sira >= b.sira:
                hatalar.append(f"{tarih}: oturum sırası saat sırasıyla uyumsuz ({a.baslangic}, {b.baslangic}).")

    if hatalar:
        return hatalar, uyarilar  # veri bozukken aşağıdaki fizibilite kontrolleri anlamsız

    # ------------------------------------------------------------------ 5. Fizibilite uyarıları (sınav bazında)
    ders_ogrencileri: dict[int, list[int]] = defaultdict(list)
    for o_id, d_id in veri.kayitlar:
        ders_ogrencileri[d_id].append(o_id)
    gereksinim = {g.ogrenci_id: g for g in veri.gereksinimler}
    zorunlu: dict[int, list[int]] = defaultdict(list)
    yasak: dict[int, set[int]] = defaultdict(set)
    for k in veri.dilim_kurallari:
        (zorunlu[k.ders_id].append if k.tur == "zorunlu" else yasak[k.ders_id].add)(k.dilim_id)

    for d in veri.dersler:
        ogr = ders_ogrencileri.get(d.id, [])
        if not ogr:
            uyarilar.append(f"{d.kod}: kayıtlı öğrencisi yok, sınavı planlanmayacak.")
            continue
        en_buyuk_oran = max((gereksinim[o].ek_sure_orani for o in ogr if o in gereksinim), default=0.0)
        sure = gereken_sure(d.sinav_suresi_dk, en_buyuk_oran)

        # Uygun oturum var mı? (H8 süre, H9 sabit/yasak; hoca müsaitliği yumuşak)
        adaylar = zorunlu[d.id] if zorunlu.get(d.id) else list(dilimler)
        uygun = [p for p in adaylar if p not in yasak[d.id] and dilimler[p].sure_dk >= sure]
        if not uygun:
            uyarilar.append(f"{d.kod}: uygun oturum yok (süre {sure} dk ve sabit/yasak kurallar birlikte).")
        elif all((d.hoca_id, p) in veri.personel_musait_degil for p in uygun):
            uyarilar.append(f"{d.kod}: hocası uygun oturumların hiçbirinde müsait değil (sınav hocasız yapılacak).")

        # Salonlar yeterli mi? (H2, H6, H10) — ayrı salon öğrencileri önce özel odaları, sonra en küçük
        # tür-uygun salonları alır; ana grup kalan tür-uygun salonlara sığmalı.
        tur_uygun = sorted(
            (r for r in veri.derslikler if r.tur in UYGUN_DERSLIK_TURLERI[d.sinav_turu]),
            key=lambda r: r.sinav_kapasitesi,
        )
        ozel_odalar = [r for r in veri.derslikler if r.tur == OZEL_DERSLIK_TURU]
        ayri = [gereksinim[o] for o in ogr if o in gereksinim and gereksinim[o].ayri_salon]
        ayri_tur_uygunda = max(0, len(ayri) - len(ozel_odalar))  # özel odalar yetmezse tür-uygun salon kullanılır
        ana_grup = len(ogr) - len(ayri)
        ozel = [gereksinim[o] for o in ogr if o in gereksinim]
        ana_eris = any(g.erisilebilir_salon and not g.ayri_salon for g in ozel)
        if ana_eris and not any(r.erisilebilir for r in tur_uygun):
            uyarilar.append(f"{d.kod}: erişilebilir salon gereken öğrenci var, türe uygun erişilebilir salon yok.")
        if ayri_tur_uygunda >= len(tur_uygun):
            uyarilar.append(f"{d.kod}: ayrı salon öğrencilerinden sonra ana grup için salon kalmıyor.")
        else:
            kalan_kapasite = sum(r.sinav_kapasitesi for r in tur_uygun[ayri_tur_uygunda:])
            if kalan_kapasite < ana_grup:
                uyarilar.append(
                    f"{d.kod}: {ana_grup} öğrenci, uygun salonların kapasitesi yetersiz ({kalan_kapasite})."
                )

    return hatalar, uyarilar
