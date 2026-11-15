"""Çalıştırma kaydı ↔ Cozum dönüştürücüsü.

* `kayit_olustur`: bellekteki tam bir takvimi (indeksli `Cozum`) veritabanı kimlikleriyle `CalistirmaKaydi`'na çevirir.
  Sınav, derslik ve özel öğrenci atamaları, ham ceza detayı, AHP ağırlıkları ve referans ölçekleri kayda girer.
* `cozum_olustur`: kayıttaki sınav, derslik ve özel öğrenci atamalarını birebir `Cozum`'a geri yükler; böylece hem
  değerlendirici hem bağımsız doğrulayıcı gerçekten kaydedilmiş satırları denetler. Kayıttaki derslik/özel oturma
  atamaları güncel dağıtıcının üreteceğinden farklıysa (ör. veri değişmiş ya da harici çözücü kullanılmış) uyarı döner.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from sinav_takvimi.altyapi.repolar import CalistirmaKaydi
from sinav_takvimi.domain.ahp import AhpSonucu, ahp_sozluge
from sinav_takvimi.domain.ceza import Ceza
from sinav_takvimi.domain.cozum import Cozum
from sinav_takvimi.domain.derslik_dagitici import SalonAtamasi
from sinav_takvimi.domain.problem import ProblemOrnegi


class KayitHatasi(ValueError):
    """Kayıt bu veriyle bağdaşmıyor (ör. ders/oturum veride yok) ya da eksik bir takvim kaydedilmek isteniyor."""


def kayit_olustur(
    pr: ProblemOrnegi,
    cozum: Cozum,
    *,
    zaman: str,
    algoritma: str,
    parametreler: dict[str, Any],
    ceza: Ceza,
    ham_ihlaller: Mapping[str, float],
    sure_sn: float,
    gecmis: list[list[float]],
    ahp: AhpSonucu,
    referans: Mapping[str, float],
    referans_kaynagi: Mapping[str, str],
) -> CalistirmaKaydi:
    """Tam bir takvimi kayda çevirir. Yerleşmemiş sınav varsa KayitHatasi (eksik takvim saklanmaz)."""
    if pr.veri.donem is None:
        raise KayitHatasi("Veri setinde sınav dönemi yok")
    eksik = cozum.yerlesmemis()
    if eksik:
        raise KayitHatasi(f"{len(eksik)} sınav yerleşmemiş; eksik takvim kaydedilemez")

    sinav, derslik, ozel = [], [], []
    for e, d in enumerate(pr.sinavlar):
        p = cozum.dilim[e]
        assert p is not None  # yukarıda denetlendi
        sinav.append((d.id, pr.dilimler[p].id))
        derslik += [(d.id, pr.derslikler[a.r].id, a.ogrenci, a.ayri) for a in cozum.salonlari(e)]
        ozel += [(pr.ogrenciler[s].id, d.id, pr.derslikler[r].id) for s, r in cozum.dagitim[p].ozel_yerlesim.get(e, ())]
    return CalistirmaKaydi(
        donem_id=pr.veri.donem.id,
        zaman=zaman,
        algoritma=algoritma,
        parametreler=parametreler,
        sert_ihlal=round(ceza.sert),
        toplam_ceza=ceza.yumusak,  # toplam YUMUŞAK ceza (sert ihlal ayrı sütunda)
        gozetmen_ceza=0.0,  # gözetmen ataması henüz yapılmıyor
        sure_sn=sure_sn,
        ceza_detay=dict(ham_ihlaller),
        gecmis=gecmis,
        sinav_atamalari=sinav,
        derslik_atamalari=derslik,
        gozetmen_atamalari=[],
        ozel_oturmalar=ozel,
        ahp_agirliklari=ahp_sozluge(ahp),
        referans={"olcek": dict(referans), "kaynak": dict(referans_kaynagi)},
    )


def cozum_olustur(pr: ProblemOrnegi, kayit: CalistirmaKaydi) -> tuple[Cozum, list[str]]:
    """Kayıttan Cozum kurar. (cozum, uyarılar) döner; uyarı yoksa kayıt bu veri ve kodla birebir uyumludur."""
    atamalar: dict[int, int | None] = {}
    for ders_id, dilim_id in kayit.sinav_atamalari:
        if ders_id not in pr.sinav_indeks:
            raise KayitHatasi(f"Kayıttaki {ders_id} numaralı ders bu veride sınav değil")
        if dilim_id not in pr.dilim_indeks:
            raise KayitHatasi(f"Kayıttaki {dilim_id} numaralı oturum bu veride yok")
        atamalar[pr.sinav_indeks[ders_id]] = pr.dilim_indeks[dilim_id]

    salonlar: dict[int, list[SalonAtamasi]] = defaultdict(list)
    for ders_id, derslik_id, adet, ayri in kayit.derslik_atamalari:
        if ders_id not in pr.sinav_indeks or pr.sinav_indeks[ders_id] not in atamalar:
            raise KayitHatasi(f"Kayıttaki derslik atamasının dersi ({ders_id}) oturuma atanmamış")
        if derslik_id not in pr.derslik_indeks:
            raise KayitHatasi(f"Kayıttaki {derslik_id} numaralı derslik bu veride yok")
        if adet <= 0:
            raise KayitHatasi(f"Kayıttaki derslik atamasında öğrenci sayısı pozitif olmalı ({adet})")
        salonlar[pr.sinav_indeks[ders_id]].append(SalonAtamasi(pr.derslik_indeks[derslik_id], adet, bool(ayri)))

    ozel: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for ogrenci_id, ders_id, derslik_id in kayit.ozel_oturmalar:
        if ogrenci_id not in pr.ogrenci_indeks:
            raise KayitHatasi(f"Kayıttaki {ogrenci_id} numaralı öğrenci bu veride yok")
        if ders_id not in pr.sinav_indeks or pr.sinav_indeks[ders_id] not in atamalar:
            raise KayitHatasi(f"Kayıttaki özel oturmanın dersi ({ders_id}) oturuma atanmamış")
        if derslik_id not in pr.derslik_indeks:
            raise KayitHatasi(f"Kayıttaki {derslik_id} numaralı derslik bu veride yok")
        ozel[pr.sinav_indeks[ders_id]].append((pr.ogrenci_indeks[ogrenci_id], pr.derslik_indeks[derslik_id]))

    cozum = Cozum.kayittan(pr, atamalar, salonlar, ozel)
    guncel = Cozum.atamalardan(pr, atamalar)

    uyarilar: list[str] = []
    if cozum.yerlesmemis():
        uyarilar.append(f"{len(cozum.yerlesmemis())} sınav kayıtta yok (veriye sonradan ders eklenmiş olabilir)")
    kayit_kumesi = _atama_kumeleri(pr, cozum)
    guncel_kumesi = _atama_kumeleri(pr, guncel)
    if kayit_kumesi[0] != guncel_kumesi[0]:
        uyarilar.append("Kayıttaki derslik atamaları güncel derslik dağıtıcısının sonucundan farklı")
    if kayit_kumesi[1] != guncel_kumesi[1]:
        uyarilar.append("Kayıttaki özel öğrenci yerleşimleri güncel derslik dağıtıcısının sonucundan farklı")
    return cozum, uyarilar


def _atama_kumeleri(
    pr: ProblemOrnegi, cozum: Cozum
) -> tuple[set[tuple[int, int, int, bool]], set[tuple[int, int, int]]]:
    derslik: set[tuple[int, int, int, bool]] = set()
    ozel: set[tuple[int, int, int]] = set()
    for e, d in enumerate(pr.sinavlar):
        p = cozum.dilim[e]
        if p is None:
            continue
        derslik |= {(d.id, pr.derslikler[a.r].id, a.ogrenci, a.ayri) for a in cozum.salonlari(e)}
        ozel |= {(pr.ogrenciler[s].id, d.id, pr.derslikler[r].id) for s, r in cozum.dagitim[p].ozel_yerlesim.get(e, ())}
    return derslik, ozel
