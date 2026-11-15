"""Tabu Arama (*Tabu Search*) çözücüsü.

Tasarım ve literatür dayanakları:
* **Aday listesi (*candidate list*):** Di Gaspero & Schaerf (2001, *PATAT / LNCS 2079*) doğrultusunda her adımda tüm
  komşuluğu taramak yerine yumuşak ihlallerde yer alan sınavlara ağırlık veren tekil aday hamleler örneklenir.
* **Dinamik tabu süresi:** Taillard (1991) ve Di Gaspero & Schaerf (2001) ile uyumlu olarak taşınan sınavın eski
  oturumuna dönüşü `(sinav, eski_dilim)`, problem boyutuyla ölçeklenen `τ ~ U[τ_min, τ_max]` (`√E` tabanlı) adım
  boyunca yasaklanır.
* **Aspirasyon kriteri:** Küresel en iyi çözümü iyileştiren hamle tabu olsa bile kabul edilir.
* **Çeşitlendirme (*diversification*):** Uzun süre küresel iyileşme görülmezse en iyi çözüme dönülüp rastgele geçerli
  Kempe adımlarıyla farklı bir arama bölgesine geçilir.
"""

from __future__ import annotations

import math
import random
import time

from sinav_takvimi.cozuculer.hamleler import (
    IyilestirmeSonucu,
    hareketli_sinavlar,
    kempe_zinciri,
    rastgele_hamle,
    sinav_yumusak_agirliklari,
)
from sinav_takvimi.domain.artimli_degerlendirici import ArtimliDegerlendirici
from sinav_takvimi.domain.ayarlar import TabuAyarlari
from sinav_takvimi.domain.ceza import TOLERANS, Ceza
from sinav_takvimi.domain.cozum import Cozum
from sinav_takvimi.domain.degerlendirici import Degerlendirici

ALGORITMA_TABU = "tabu"
_MAKS_GECMIS_NOKTASI = 250


def _aday_listesi_uret(
    artimli: ArtimliDegerlendirici,
    aday_sinavlar: list[int],
    aday_sayisi: int,
    takas_olasiligi: float,
    rng: random.Random,
) -> list[dict[int, int]]:
    """Tekrarlanmayan (tekil) geçerli ön-elemeden geçmiş aday hamleler üretir."""
    pr = artimli.problem
    cozum = artimli.cozum
    agirliklar = sinav_yumusak_agirliklari(pr, cozum, aday_sinavlar)
    gorulen: set[tuple[tuple[int, int], ...]] = set()
    adaylar: list[dict[int, int]] = []
    deneme_siniri = aday_sayisi * 4

    for deneme in range(deneme_siniri):
        if len(adaylar) >= aday_sayisi:
            break
        hamle: dict[int, int] | None = None
        if deneme % 2 == 0:
            # İhlal odaklı Kempe hamlesi (Di Gaspero & Schaerf 2001)
            e = rng.choices(aday_sinavlar, weights=agirliklar, k=1)[0]
            mevcut_p = cozum.dilim[e]
            uygunlar = [p for p in pr.uygun_dilimler[e] if p != mevcut_p]
            if uygunlar:
                hamle = kempe_zinciri(pr, cozum, e, rng.choice(uygunlar))
        else:
            hamle = rastgele_hamle(pr, cozum, rng, takas_olasiligi, aday_sinavlar, en_fazla_deneme=4)

        if hamle is None:
            continue
        imza = tuple(sorted(hamle.items()))
        if imza not in gorulen:
            gorulen.add(imza)
            adaylar.append(hamle)

    return adaylar


def tabu_coz(
    cozum: Cozum,
    deg: Degerlendirici,
    ayar: TabuAyarlari | None = None,
    *,
    sure_sn: float | None = None,
    tohum: int = 0,
    maks_adim: int | None = None,
) -> IyilestirmeSonucu:
    """Başlangıç takvimini Tabu Arama ile iyileştirir (girdi `cozum` değiştirilmez)."""
    ayar = ayar or TabuAyarlari()
    butce = sure_sn if sure_sn is not None else ayar.sure_sn
    if butce <= 0:
        raise ValueError("Süre bütçesi pozitif olmalıdır.")

    baslangic_zamani = time.perf_counter()
    rng = random.Random(tohum)
    pr = deg.problem
    mevcut_cozum = cozum.kopya()
    artimli = ArtimliDegerlendirici(deg, mevcut_cozum)
    baslangic_ceza = artimli.ceza()
    mevcut_ceza = baslangic_ceza
    en_iyi_cozum = mevcut_cozum.kopya()
    en_iyi_ceza = baslangic_ceza

    aday_sinavlar = hareketli_sinavlar(pr, mevcut_cozum)
    kok_e = math.sqrt(max(1, pr.E))
    tau_alt = max(2, round(ayar.tabu_alt_katsayi * kok_e))
    tau_ust = max(tau_alt, round(ayar.tabu_ust_katsayi * kok_e))

    tabu_bitis: dict[tuple[int, int], int] = {}  # (sinav, eski_dilim) → yasak bitiş adımı
    gecmis: list[list[float]] = [[0.0, mevcut_ceza.yumusak, en_iyi_ceza.yumusak]]
    adim = kabul_sayisi = iyilestirme_sayisi = cesitlendirme_sayisi = degerlendirilen_hamle = 0
    son_iyilesme_orani = 0.0
    son_kayit_orani = 0.0
    kayit_araligi = 1.0 / _MAKS_GECMIS_NOKTASI

    if aday_sinavlar and pr.P > 1:
        oran = 0.0
        while True:
            if maks_adim is not None:
                if adim >= maks_adim:
                    break
                oran = adim / maks_adim
            else:
                gecen = time.perf_counter() - baslangic_zamani
                if gecen >= butce:
                    break
                oran = min(1.0, gecen / butce)

            # Tıkanmada çeşitlendirme: en iyi çözüme dönüp 2 rastgele geçerli Kempe sıçraması uygula
            if (
                ayar.cesitlendirme_orani > 0
                and oran < 0.90
                and (oran - son_iyilesme_orani) >= ayar.cesitlendirme_orani
            ):
                mevcut_cozum = en_iyi_cozum.kopya()
                artimli = ArtimliDegerlendirici(deg, mevcut_cozum)
                mevcut_ceza = artimli.ceza()
                tabu_bitis.clear()
                for _ in range(2):
                    sicrama = rastgele_hamle(pr, mevcut_cozum, rng, 0.0, aday_sinavlar)
                    if sicrama is None:
                        continue
                    onceki = {e: mevcut_cozum.dilim[e] for e in sicrama}
                    kayit = artimli.tasi(sicrama)
                    yeni = artimli.ceza()
                    if yeni.sert > mevcut_ceza.sert + TOLERANS:
                        artimli.geri_al(kayit)
                    else:
                        mevcut_ceza = yeni
                        for e, eski_p in onceki.items():
                            if eski_p is not None:
                                tabu_bitis[(e, eski_p)] = adim + tau_ust
                        if mevcut_ceza < en_iyi_ceza:
                            en_iyi_ceza = mevcut_ceza
                            en_iyi_cozum = mevcut_cozum.kopya()
                son_iyilesme_orani = oran
                cesitlendirme_sayisi += 1

            adim += 1
            adaylar = _aday_listesi_uret(artimli, aday_sinavlar, ayar.aday_sayisi, ayar.takas_olasiligi, rng)
            en_iyi_uygun: tuple[Ceza, dict[int, int]] | None = None
            en_iyi_tabu: tuple[tuple[int, Ceza], Ceza, dict[int, int]] | None = None

            for hamle in adaylar:
                degerlendirilen_hamle += 1
                kayit = artimli.tasi(hamle)
                aday_ceza = artimli.ceza()
                artimli.geri_al(kayit)
                if aday_ceza.sert > mevcut_ceza.sert + TOLERANS:
                    continue

                en_gec_bitis = max((tabu_bitis.get((e, p_yeni), 0) for e, p_yeni in hamle.items()), default=0)
                tabu_mu = en_gec_bitis > adim and not (aday_ceza < en_iyi_ceza)  # aspirasyon kriteri

                if not tabu_mu:
                    if en_iyi_uygun is None or aday_ceza < en_iyi_uygun[0]:
                        en_iyi_uygun = (aday_ceza, hamle)
                else:
                    anahtar = (en_gec_bitis, aday_ceza)
                    if en_iyi_tabu is None or anahtar < en_iyi_tabu[0]:
                        en_iyi_tabu = (anahtar, aday_ceza, hamle)

            secim: tuple[Ceza, dict[int, int]] | None = en_iyi_uygun
            if secim is None and en_iyi_tabu is not None:
                secim = (en_iyi_tabu[1], en_iyi_tabu[2])
            if secim is None:
                continue

            secilen_ceza, secilen_hamle = secim
            onceki_dilimler = {e: mevcut_cozum.dilim[e] for e in secilen_hamle}
            artimli.tasi(secilen_hamle)
            artimli.periyodik_yenile_gerekirse()
            mevcut_ceza = secilen_ceza
            kabul_sayisi += 1

            tau = rng.randint(tau_alt, tau_ust)
            for e, eski_p in onceki_dilimler.items():
                if eski_p is not None:
                    tabu_bitis[(e, eski_p)] = adim + tau

            if mevcut_ceza < en_iyi_ceza:
                en_iyi_ceza = mevcut_ceza
                en_iyi_cozum = mevcut_cozum.kopya()
                iyilestirme_sayisi += 1
                son_iyilesme_orani = oran
                simdi = time.perf_counter() - baslangic_zamani
                gecmis.append([round(simdi, 4), mevcut_ceza.yumusak, en_iyi_ceza.yumusak])
                son_kayit_orani = oran
            elif oran - son_kayit_orani >= kayit_araligi:
                simdi = time.perf_counter() - baslangic_zamani
                gecmis.append([round(simdi, 4), mevcut_ceza.yumusak, en_iyi_ceza.yumusak])
                son_kayit_orani = oran

    toplam_sure = time.perf_counter() - baslangic_zamani
    if len(gecmis) == 1 or gecmis[-1][2] != en_iyi_ceza.yumusak:
        gecmis.append([round(toplam_sure, 4), mevcut_ceza.yumusak, en_iyi_ceza.yumusak])

    return IyilestirmeSonucu(
        algoritma=ALGORITMA_TABU,
        cozum=en_iyi_cozum,
        baslangic_ceza=baslangic_ceza,
        en_iyi_ceza=en_iyi_ceza,
        adim_sayisi=adim,
        kabul_sayisi=kabul_sayisi,
        iyilestirme_sayisi=iyilestirme_sayisi,
        sure_sn=toplam_sure,
        gecmis=gecmis,
        ozet_parametreler={
            "tohum": tohum,
            "sure_butcesi_sn": butce,
            "aday_sayisi": ayar.aday_sayisi,
            "tau_alt": tau_alt,
            "tau_ust": tau_ust,
            "degerlendirilen_hamle": degerlendirilen_hamle,
            "cesitlendirme_sayisi": cesitlendirme_sayisi,
        },
    )
