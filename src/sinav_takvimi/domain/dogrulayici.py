"""Bağımsız doğrulayıcı: bir takvimin sert kurallara uyup uymadığını, kısıt sınıflarını HİÇ kullanmadan kontrol eder.

Neden ayrı? Değerlendirici hızlı olmak için önceden hesaplanmış yapılar (çakışma matrisi, komşu listeleri, uygun dilim
listeleri) kullanır; bunlarda bir hata olursa değerlendirici de yanılır. Doğrulayıcı ise *ham veriden* (VeriSeti)
öğrenci öğrenci, salon salon basit döngülerle sayar. İkisinin her kural için aynı sayıyı bulması testlerle
doğrulanır: doğrulayıcı testlerin hakemidir.

Mesajlar insan okunur: "Öğrenci 2501-0012: MAT101 ve FIZ101 aynı oturumda (2027-01-04 09:00)".
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from sinav_takvimi.domain.cozum import Cozum
from sinav_takvimi.domain.modeller import OZEL_DERSLIK_TURU, UYGUN_DERSLIK_TURLERI, gereken_sure


@dataclass(frozen=True, slots=True)
class Hata:
    kod: str
    mesaj: str
    miktar: int = 1


@dataclass(slots=True)
class DogrulamaRaporu:
    hatalar: list[Hata] = field(default_factory=list)

    def ekle(self, kod: str, mesaj: str, miktar: int = 1) -> None:
        self.hatalar.append(Hata(kod, mesaj, miktar))

    def sayilar(self) -> dict[str, int]:
        sonuc: Counter[str] = Counter()
        for h in self.hatalar:
            sonuc[h.kod] += h.miktar
        return dict(sonuc)

    @property
    def gecerli(self) -> bool:
        return not self.hatalar


def dogrula(cozum: Cozum) -> DogrulamaRaporu:
    pr = cozum.problem  # sadece id ↔ indeks dönüşümü için; kurallar ham veriden okunur
    veri = pr.veri
    rapor = DogrulamaRaporu()

    dersler = {d.id: d for d in veri.dersler}
    derslikler = {r.id: r for r in veri.derslikler}
    dilimler = {d.id: d for d in veri.dilimler}
    ogrenci_no = {o.id: o.no for o in veri.ogrenciler}
    gereksinim = {g.ogrenci_id: g for g in veri.gereksinimler}
    personel_musait_degil = set(veri.personel_musait_degil)
    derslik_musait_degil = set(veri.derslik_musait_degil)

    # Çözümü ham kimliklere çevir: ders_id → dilim_id, (dilim_id, ders_id) → [(derslik_id, n, ayrı)]
    sinav_dilimi: dict[int, int | None] = {}
    salonlar: dict[int, list[tuple[int, int, bool]]] = defaultdict(list)
    ozel_salon: dict[tuple[int, int], int] = {}  # (ogrenci_id, ders_id) → derslik_id
    for e, d in enumerate(pr.sinavlar):
        p = cozum.dilim[e]
        sinav_dilimi[d.id] = None if p is None else pr.dilimler[p].id
        for atama in cozum.salonlari(e):
            salonlar[d.id].append((pr.derslikler[atama.r].id, atama.ogrenci, atama.ayri))
        if p is not None:
            for s, r_i in cozum.dagitim[p].ozel_yerlesim.get(e, ()):
                ozel_salon[(pr.ogrenciler[s].id, d.id)] = pr.derslikler[r_i].id

    ders_ogrencileri: dict[int, list[int]] = defaultdict(list)
    for o_id, d_id in veri.kayitlar:
        ders_ogrencileri[d_id].append(o_id)

    def etiket(dilim_id: int) -> str:
        return dilimler[dilim_id].etiket

    # Y0: yerleşmemiş sınav (öğrenci sayısı kadar)
    for d_id, dl in sinav_dilimi.items():
        if dl is None:
            rapor.ekle("Y0", f"{dersler[d_id].kod} hiçbir oturuma yerleştirilmemiş", len(ders_ogrencileri[d_id]))

    # H1: öğrencinin aynı oturumda iki sınavı
    ogrenci_sinavlari: dict[int, list[int]] = defaultdict(list)
    for o_id, d_id in veri.kayitlar:
        if sinav_dilimi.get(d_id) is not None:
            ogrenci_sinavlari[o_id].append(d_id)
    for o_id, d_idler in ogrenci_sinavlari.items():
        oturum: dict[int, list[int]] = defaultdict(list)
        for d_id in d_idler:
            oturum[sinav_dilimi[d_id]].append(d_id)  # type: ignore[index]
        for dl, ayni in oturum.items():
            for x, y in combinations(sorted(ayni), 2):
                rapor.ekle("H1", f"Öğrenci {ogrenci_no[o_id]}: {dersler[x].kod} ve {dersler[y].kod} aynı oturumda "
                                 f"({etiket(dl)})")

    # H4: hocanın aynı oturumda iki sınavı
    hoca_oturum: dict[tuple[int, int], list[int]] = defaultdict(list)
    for d_id, dl in sinav_dilimi.items():
        if dl is not None:
            hoca_oturum[(dersler[d_id].hoca_id, dl)].append(d_id)
    personel_adi = {p.id: p.tam_ad for p in veri.personeller}
    for (hoca, dl), ayni in hoca_oturum.items():
        for x, y in combinations(sorted(ayni), 2):
            rapor.ekle("H4", f"{personel_adi.get(hoca, hoca)}: {dersler[x].kod} ve {dersler[y].kod} aynı oturumda "
                             f"({etiket(dl)})")

    # H8, H9: sınavın oturumu (etkilenen öğrenci sayısı kadar). Hoca müsaitliği yumuşak, burada yok.
    zorunlu: dict[int, set[int]] = defaultdict(set)
    yasak: dict[int, set[int]] = defaultdict(set)
    for k in veri.dilim_kurallari:
        (zorunlu if k.tur == "zorunlu" else yasak)[k.ders_id].add(k.dilim_id)
    for d_id, dl in sinav_dilimi.items():
        if dl is None:
            continue
        d = dersler[d_id]
        oran = max((gereksinim[o].ek_sure_orani for o in ders_ogrencileri[d_id] if o in gereksinim), default=0.0)
        gereken = gereken_sure(d.sinav_suresi_dk, oran)
        if dilimler[dl].sure_dk < gereken:
            rapor.ekle("H8", f"{d.kod}: {gereken} dk gerekiyor, {etiket(dl)} oturumu {dilimler[dl].sure_dk} dk",
                       len(ders_ogrencileri[d_id]))
        if dl in yasak[d_id] or (zorunlu[d_id] and dl not in zorunlu[d_id]):
            rapor.ekle("H9", f"{d.kod}: {etiket(dl)} oturumu sabit/yasak kurala aykırı", len(ders_ogrencileri[d_id]))

    # H2, H6, salon kuralları
    salon_kullanimi: dict[tuple[int, int], list[int]] = defaultdict(list)  # (dilim, derslik) → dersler
    for d_id, dl in sinav_dilimi.items():
        if dl is None:
            continue
        d, liste = dersler[d_id], salonlar.get(d_id, [])  # hiç salon bulamamış sınav da sayılmalı
        oturan = sum(n for _, n, _ in liste)
        if oturan < len(ders_ogrencileri[d_id]):
            rapor.ekle("H2", f"{d.kod}: {len(ders_ogrencileri[d_id]) - oturan} öğrenciye yer yok",
                       len(ders_ogrencileri[d_id]) - oturan)
        for r_id, n, ayri in liste:
            salon = derslikler[r_id]
            salon_kullanimi[(dl, r_id)].append(d_id)
            if n > salon.sinav_kapasitesi:
                rapor.ekle("SK", f"{d.kod}: {salon.kod} salonuna kapasitesinden fazla ({n} > {salon.sinav_kapasitesi})")
            tur_uygun = salon.tur in UYGUN_DERSLIK_TURLERI[d.sinav_turu] or (ayri and salon.tur == OZEL_DERSLIK_TURU)
            if not tur_uygun:
                rapor.ekle("H6", f"{d.kod} ({d.sinav_turu}): {salon.kod} ({salon.tur}) uygun değil")
            if (r_id, dl) in derslik_musait_degil:
                rapor.ekle("SM", f"{d.kod}: {salon.kod} {etiket(dl)} oturumunda kullanılamaz durumda")
    for (dl, r_id), kullanan in salon_kullanimi.items():
        if len(kullanan) > 1:
            rapor.ekle("SC", f"{derslikler[r_id].kod} {etiket(dl)}: aynı anda {len(kullanan)} sınav")
        elif sum(1 for x in salonlar[kullanan[0]] if x[0] == r_id) > 1:
            rapor.ekle("SC", f"{derslikler[r_id].kod} {etiket(dl)}: aynı sınava iki kez atanmış")

    # H10: özel gereksinimler. Dağıtıcının "kim nerede" beyanına körü körüne güvenilmez: beyan edilen salon
    # sınavın salonlarından biri olmalı ve bir salona beyan edilen özel öğrenci sayısı oradaki kişi sayısını aşmamalı.
    beyan_sayisi: Counter[tuple[int, int]] = Counter((d_id, r_id) for (_, d_id), r_id in ozel_salon.items())
    for (d_id, r_id), adet in beyan_sayisi.items():
        yerlesen = sum(n for x, n, _ in salonlar.get(d_id, []) if x == r_id)
        if yerlesen == 0:
            continue  # sınavın salonu değil: aşağıda öğrenci bazında (bir kez) sayılır
        if adet > yerlesen:
            rapor.ekle("H10", f"{dersler[d_id].kod}: {derslikler[r_id].kod} salonuna {adet} özel öğrenci beyan "
                              f"edilmiş, salonda {yerlesen} kişi var", adet - yerlesen)
    for o_id, d_id in veri.kayitlar:
        g = gereksinim.get(o_id)
        if g is None or sinav_dilimi.get(d_id) is None or not (g.ayri_salon or g.erisilebilir_salon):
            continue
        ozel_r = ozel_salon.get((o_id, d_id))
        kod = dersler[d_id].kod
        if ozel_r is None:
            rapor.ekle("H10", f"Öğrenci {ogrenci_no[o_id]} ({kod}): özel gereksinim salonu atanmamış")
            continue
        if all(x != ozel_r for x, _, _ in salonlar.get(d_id, [])):
            rapor.ekle("H10", f"Öğrenci {ogrenci_no[o_id]} ({kod}): beyan edilen salon bu sınavın salonu değil")
        elif g.erisilebilir_salon and not derslikler[ozel_r].erisilebilir:
            rapor.ekle("H10", f"Öğrenci {ogrenci_no[o_id]} ({kod}): {derslikler[ozel_r].kod} erişilebilir değil")
        elif g.ayri_salon:
            salon_kaydi = [x for x in salonlar[d_id] if x[0] == ozel_r]
            if not salon_kaydi or salon_kaydi[0][1] != 1 or not salon_kaydi[0][2]:
                rapor.ekle("H10", f"Öğrenci {ogrenci_no[o_id]} ({kod}): ayrı salonda tek başına değil")

    # H11: öğrencinin günlük sınav üst sınırı (isteğe bağlı kurum politikası, istisnalarıyla)
    politikalar = {p.anahtar: p.deger for p in veri.politikalar}
    if "gunluk_sinav_ust_siniri" in politikalar:
        sinir = int(politikalar["gunluk_sinav_ust_siniri"])
        ortak_haric = politikalar.get("gunluk_sinir_ortak_ders_haric", 0) >= 0.5
        alttan_haric = politikalar.get("gunluk_sinir_alttan_haric", 0) >= 0.5
        ogrenci_sinifi = {o.id: o.sinif for o in veri.ogrenciler}
        for o_id, d_idler in ogrenci_sinavlari.items():
            gunluk: dict[int, set[int]] = defaultdict(set)
            for d_id in d_idler:
                d = dersler[d_id]
                if ortak_haric and d.bolum_id is None:
                    continue
                if alttan_haric and d.sinif < ogrenci_sinifi[o_id]:
                    continue
                dl = sinav_dilimi[d_id]
                assert dl is not None
                gunluk[dilimler[dl].gun].add(dl)
            for _gun, oturumlar in gunluk.items():
                if len(oturumlar) > sinir:
                    tarih = dilimler[next(iter(oturumlar))].tarih
                    rapor.ekle("H11", f"Öğrenci {ogrenci_no[o_id]}: {tarih} günü {len(oturumlar)} sınav "
                                      f"(sınır {sinir})", len(oturumlar) - sinir)

    # H7: oturum başına gözetmen ihtiyacı ≤ müsait personel (politikalar veriden)
    ihtiyac: Counter[int] = Counter()
    for d_id, liste in salonlar.items():
        oturum_id = sinav_dilimi[d_id]
        assert oturum_id is not None
        for r_id, n, ayri in liste:
            salon = derslikler[r_id]
            oran = salon.gozetmen_sayisi * n / salon.sinav_kapasitesi
            ihtiyac[oturum_id] += 1 if ayri else max(1, math.ceil(oran - 1e-9))
    for dl, gerek in ihtiyac.items():
        toplam = gerek + math.ceil(round(politikalar["yedek_orani"] * gerek, 9))
        musait = sum(1 for p in veri.personeller if p.gunluk_max > 0 and (p.id, dl) not in personel_musait_degil)
        if toplam > musait:
            rapor.ekle("H7", f"{etiket(dl)}: {toplam} gözetmen gerekiyor (yedek dahil), {musait} kişi müsait",
                       toplam - musait)

    return rapor
