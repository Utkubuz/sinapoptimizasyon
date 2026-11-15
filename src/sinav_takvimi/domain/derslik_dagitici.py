"""Bir dilimdeki sınavlara derslik dağıtan sezgisel (takvim içinde iç içe çalışan alt problem).

Takvim algoritmaları sadece "hangi sınav hangi dilimde?" kararını verir. Bir dilimin sınav listesi değişince bu modül
o dilimin dersliklerini yeniden dağıtır. Böylece derslik kararları her zaman takvimle tutarlı kalır.

Adımlar:
  1. Ayrı salon öğrencileri: önce özel odalar, yetmezse türe uygun en küçük salon. Erişilebilirlik GEREKMİYORSA
     erişilebilir olmayan salon tercih edilir (kıt erişilebilir salonlar boşa harcanmasın). Her öğrenciye 1 gözetmen.
  2. Ana gruplar. Sıra: erişilebilir salon gereken sınavlar önce, sonra az seçeneği olan, sonra kalabalık olan:
       a) erişilebilir salon gereken öğrenci varsa ilk salon erişilebilir seçilir;
       b) kalan öğrenciler: hepsi tek salona sığıyorsa sığan en küçük salon, sığmıyorsa en büyük salon (tekrar);
          erişilebilir salonlar kıt olduğu için sığan salonlardan önce erişilebilir OLMAYANLAR denenir;
       c) öğrenciler seçilen salonlara KAPASİTEYLE ORANTILI dağıtılır (azınlık salonu oluşmaz; eşik gerekmez).
  3. Açgözlü sıra bazen yerleştirilebilir bir dilimi "yerleştirilemez" gösterebilir (kutu paketleme). Bu yüzden
     ihlal çıkarsa birkaç farklı sınav sırası daha denenir ve en iyi sonuç alınır (deterministik).
  4. Gözetmen ihtiyacı: salon başına max(1, ⌈gözetmen_sayısı × yerleşen ÷ kapasite⌉), ayrı salonda 1,
     üstüne ⌈yedek_oranı × ihtiyaç⌉ yedek (politikalar veriden).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from sinav_takvimi.domain.problem import ProblemOrnegi


@dataclass(frozen=True, slots=True)
class SalonAtamasi:
    r: int
    ogrenci: int
    ayri: bool = False  # özel gereksinim (ayrı salon) odası mı?


@dataclass(frozen=True, slots=True)
class DilimDagitimi:
    atamalar: dict[int, tuple[SalonAtamasi, ...]] = field(default_factory=dict)  # e → salonlar
    ozel_yerlesim: dict[int, tuple[tuple[int, int], ...]] = field(default_factory=dict)  # e → ((s, r), …)
    oturamayan: int = 0  # H2: hiçbir salona sığmayan öğrenci
    ozel_ihlal: int = 0  # H10: gereksinimi karşılanamayan özel öğrenci
    ek_derslik: int = 0  # S5: ana grupların ilk salondan sonra kullandığı salon sayısı
    bos_koltuk: int = 0  # S6: ana grup salonlarında boş kalan koltuk
    gozetmen_ihtiyaci: int = 0  # yedek dahil
    yedek_ihtiyaci: int = 0
    gozetmen_asimi: int = 0  # H7: müsait personelden fazla ihtiyaç

    def kalite_anahtari(self) -> tuple[int, int, int, int]:
        """Farklı sınav sıralarıyla bulunan dağıtımları karşılaştırmak için (küçük = iyi)."""
        return (self.oturamayan + self.ozel_ihlal, self.gozetmen_asimi, self.ek_derslik, self.bos_koltuk)


BOS_DAGITIM = DilimDagitimi()


def orantili_dagit(toplam: int, kapasiteler: list[int]) -> list[int]:
    """`toplam` öğrenciyi kapasitelerle orantılı dağıtır (en büyük kalan yöntemi). Hiçbir salon kapasitesini aşmaz."""
    kap_toplam = sum(kapasiteler)
    if toplam <= 0 or kap_toplam == 0:
        return [0] * len(kapasiteler)
    toplam = min(toplam, kap_toplam)
    paylar = [toplam * k / kap_toplam for k in kapasiteler]
    sonuc = [min(k, math.floor(x)) for x, k in zip(paylar, kapasiteler, strict=True)]
    sira = sorted(range(len(kapasiteler)), key=lambda i: (-(paylar[i] - math.floor(paylar[i])), i))
    kalan = toplam - sum(sonuc)
    while kalan > 0:
        for i in sira:
            if kalan == 0:
                break
            if sonuc[i] < kapasiteler[i]:
                sonuc[i] += 1
                kalan -= 1
    return sonuc


def _sec(adaylar: Sequence[int], kalan: int, kap: list[int], eris: list[bool]) -> int:
    """Kalanın hepsi sığıyorsa sığan en küçük salon (erişilebilir olmayanlar önce), sığmıyorsa en büyük salon."""
    sigan = [r for r in adaylar if kap[r] >= kalan]
    if sigan:
        return min(sigan, key=lambda r: (eris[r], kap[r], r))  # erişilebilir salonlar kıt: önce diğerleri
    return max(adaylar, key=lambda r: (kap[r], not eris[r], -r))


def _sirali_dagit(pr: ProblemOrnegi, p: int, sirali: Sequence[int]) -> DilimDagitimi:
    kap, eris = pr.derslik_kapasite, pr.derslik_erisilebilir
    bos = {r for r in range(pr.R) if pr.derslik_musait[r][p]}
    atamalar: dict[int, list[SalonAtamasi]] = {e: [] for e in sirali}
    ozel_yer: dict[int, list[tuple[int, int]]] = {e: [] for e in sirali}
    ana_grup = {e: pr.ogrenci_sayisi[e] for e in sirali}
    oturamayan = ozel_ihlal = ek_derslik = bos_koltuk = ihtiyac = 0

    # 1) Ayrı salon öğrencileri
    for e in sirali:
        for o in pr.ozel_ogrenciler[e]:
            if not o.ayri_salon:
                continue

            def uygun(r: int, gerek: bool = o.erisilebilir) -> bool:
                return r in bos and (eris[r] or not gerek)

            # erişilebilirlik gerekmiyorsa erişilebilir olmayan salon tercih edilir
            tercih = (lambda r: (eris[r], kap[r], r)) if not o.erisilebilir else (lambda r: (kap[r], r))
            adaylar = sorted((r for r in pr.ozel_derslikler if uygun(r)), key=tercih)
            if not adaylar:
                adaylar = sorted((r for r in pr.uygun_derslikler[e] if uygun(r)), key=tercih)
            if not adaylar:
                ozel_ihlal += 1  # ayrı salon bulunamadı: öğrenci ana grupla oturur, gereksinimi karşılanmamış olur
                continue
            r = adaylar[0]
            bos.discard(r)
            atamalar[e].append(SalonAtamasi(r, 1, ayri=True))
            ozel_yer[e].append((o.s, r))
            ana_grup[e] -= 1
            ihtiyac += 1

    # 2) Ana gruplar
    for e in sirali:
        kalan = ana_grup[e]
        if kalan == 0:
            continue
        adaylar = [r for r in pr.uygun_derslikler[e] if r in bos]
        secilen: list[int] = []
        eris_ogr = [o.s for o in pr.ozel_ogrenciler[e] if o.erisilebilir and not o.ayri_salon]
        if eris_ogr:
            eris_adaylar = [r for r in adaylar if eris[r]]
            if eris_adaylar:
                # kalan ≥ erişilebilir öğrenci sayısı olduğundan _sec, varsa hepsini alabilecek bir salon seçer
                r = _sec(eris_adaylar, kalan, kap, eris)
                secilen.append(r)
                adaylar.remove(r)
                kalan -= min(kalan, kap[r])
        while kalan > 0 and adaylar:
            r = _sec(adaylar, kalan, kap, eris)
            secilen.append(r)
            adaylar.remove(r)
            kalan -= min(kalan, kap[r])
        oturamayan += kalan

        dagilim = orantili_dagit(ana_grup[e] - kalan, [kap[r] for r in secilen])
        eris_salon_var = bool(secilen) and bool(eris_ogr) and eris[secilen[0]]
        if eris_salon_var and dagilim[0] < len(eris_ogr):
            # erişilebilir salon (ilk seçilen) en az erişilebilirlik gereken öğrenci kadar kişi almalı
            eksik = min(len(eris_ogr), kap[secilen[0]]) - dagilim[0]
            for i in range(len(dagilim) - 1, 0, -1):
                al = min(eksik, dagilim[i])
                dagilim[i] -= al
                dagilim[0] += al
                eksik -= al
                if eksik == 0:
                    break
        kullanilan_salonlar = [(r, n) for r, n in zip(secilen, dagilim, strict=True) if n > 0]
        for r, n in kullanilan_salonlar:
            bos.discard(r)
            atamalar[e].append(SalonAtamasi(r, n))
            ihtiyac += pr.derslik_gozetmen_ihtiyaci(r, n)
            bos_koltuk += kap[r] - n
        ek_derslik += max(0, len(kullanilan_salonlar) - 1)

        # erişilebilir salon gereken öğrenciler: erişilebilir salona sığanlar yerleşir,
        # sığmayanların gereksinimi karşılanmamış sayılır (H10)
        yerlesen_eris = min(len(eris_ogr), dagilim[0]) if eris_salon_var else 0
        ozel_yer[e].extend((s, secilen[0]) for s in eris_ogr[:yerlesen_eris])
        ozel_ihlal += len(eris_ogr) - yerlesen_eris

    yedek = math.ceil(round(pr.yedek_orani * ihtiyac, 9)) if ihtiyac > 0 else 0
    toplam_ihtiyac = ihtiyac + yedek
    return DilimDagitimi(
        atamalar={e: tuple(a) for e, a in atamalar.items() if a},
        ozel_yerlesim={e: tuple(x) for e, x in ozel_yer.items() if x},
        oturamayan=oturamayan,
        ozel_ihlal=ozel_ihlal,
        ek_derslik=ek_derslik,
        bos_koltuk=bos_koltuk,
        gozetmen_ihtiyaci=toplam_ihtiyac,
        yedek_ihtiyaci=yedek,
        gozetmen_asimi=max(0, toplam_ihtiyac - pr.musait_personel_sayisi[p]),
    )


def dagit(problem: ProblemOrnegi, p: int, sinavlar: Iterable[int]) -> DilimDagitimi:
    pr = problem
    liste = list(sinavlar)
    if not liste:
        return BOS_DAGITIM
    temel = sorted(
        liste,
        key=lambda e: (not pr.ana_grup_erisilebilir[e], len(pr.uygun_derslikler[e]), -pr.ogrenci_sayisi[e], e),
    )
    en_iyi = _sirali_dagit(pr, p, temel)
    if en_iyi.oturamayan + en_iyi.ozel_ihlal == 0 or len(liste) == 1:
        return en_iyi
    # İhlal var: farklı sıralar dene (az sayıda sınav olduğu için ucuz; sonuç yine deterministik)
    for sira in (
        sorted(liste, key=lambda e: (-pr.ogrenci_sayisi[e], e)),
        sorted(liste, key=lambda e: (pr.ogrenci_sayisi[e], e)),
        temel[::-1],
    ):
        aday = _sirali_dagit(pr, p, sira)
        if aday.kalite_anahtari() < en_iyi.kalite_anahtari():
            en_iyi = aday
    return en_iyi


def dagitim_kur(
    problem: ProblemOrnegi,
    p: int,
    sinavlar: Iterable[int],
    atamalar: Mapping[int, Sequence[SalonAtamasi]],
    ozel_yerlesim: Mapping[int, Sequence[tuple[int, int]]],
) -> DilimDagitimi:
    """Verilen salon ve özel öğrenci atamalarından (ör. veritabanından geri yüklerken) `DilimDagitimi` kurar.
    Özet metrikleri (H2, H7, H10, S5, S6) dağıtıcı ve doğrulayıcıyla birebir aynı kurallarla hesaplanır."""
    pr = problem
    sinav_listesi = sorted(set(sinavlar))
    if not sinav_listesi:
        return BOS_DAGITIM
    atama_sozluk = {e: tuple(atamalar[e]) for e in sinav_listesi if atamalar.get(e)}
    ozel_sozluk = {e: tuple(ozel_yerlesim[e]) for e in sinav_listesi if ozel_yerlesim.get(e)}
    oturamayan = ozel_ihlal = ek_derslik = bos_koltuk = ihtiyac = 0

    for e in sinav_listesi:
        liste = atama_sozluk.get(e, ())
        oturan = sum(a.ogrenci for a in liste)
        oturamayan += max(0, pr.ogrenci_sayisi[e] - oturan)
        ana = [a for a in liste if not a.ayri]
        ek_derslik += max(0, len(ana) - 1)
        bos_koltuk += sum(max(0, pr.derslik_kapasite[a.r] - a.ogrenci) for a in ana)
        for a in liste:
            ihtiyac += 1 if a.ayri else pr.derslik_gozetmen_ihtiyaci(a.r, a.ogrenci)

        salon_kisi: Counter[int] = Counter()
        for a in liste:
            salon_kisi[a.r] += a.ogrenci
        ozel_harita = dict(ozel_sozluk.get(e, ()))
        for r, adet in Counter(ozel_harita.values()).items():
            yerlesen = salon_kisi.get(r, 0)
            if yerlesen > 0 and adet > yerlesen:
                ozel_ihlal += adet - yerlesen
        for o in pr.ozel_ogrenciler[e]:
            ozel_r = ozel_harita.get(o.s)
            salon_uygunsuz = ozel_r is None or salon_kisi.get(ozel_r, 0) == 0
            eris_eksik = not salon_uygunsuz and o.erisilebilir and not pr.derslik_erisilebilir[ozel_r]  # type: ignore[index]
            if salon_uygunsuz or eris_eksik:
                ozel_ihlal += 1
            elif o.ayri_salon:
                kayit = [a for a in liste if a.r == ozel_r]
                if not kayit or kayit[0].ogrenci != 1 or not kayit[0].ayri:
                    ozel_ihlal += 1

    yedek = math.ceil(round(pr.yedek_orani * ihtiyac, 9)) if ihtiyac > 0 else 0
    toplam_ihtiyac = ihtiyac + yedek
    return DilimDagitimi(
        atamalar=atama_sozluk,
        ozel_yerlesim=ozel_sozluk,
        oturamayan=oturamayan,
        ozel_ihlal=ozel_ihlal,
        ek_derslik=ek_derslik,
        bos_koltuk=bos_koltuk,
        gozetmen_ihtiyaci=toplam_ihtiyac,
        yedek_ihtiyaci=yedek,
        gozetmen_asimi=max(0, toplam_ihtiyac - pr.musait_personel_sayisi[p]),
    )
