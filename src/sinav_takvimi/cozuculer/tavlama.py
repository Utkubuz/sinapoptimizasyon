"""Benzetimli Tavlama (*Simulated Annealing*) çözücüsü.

Tasarım ve literatür dayanakları:
* **Komşuluk:** Kempe zinciri (tekli taşımayı kapsar; Thompson & Dowsland 1998) + ikili takas (McCollum vd. 2010).
* **Otomatik başlangıç sıcaklığı (`T0`):** Ben-Ameur (2004, *Comput. Optim. Appl.*, 29(3), 369–385) sabit nokta
  algoritmasıyla başlangıç çözümünden örneklenen kötüleşen hamle farkları `{Δ > 0}` üzerinden hedef kabul oranı `χ0`ı
  (varsayılan `0,80`) sağlayacak şekilde otomatik hesaplanır; keyfi sıcaklık sabiti yoktur.
* **Süre bütçeli geometrik soğutma ve yeniden ısıtma:** `T(u) = T0 · (T_son / T0)^u` (`u ∈ [0, 1]` geçen süre/adım
  oranı); uzun tıkanmada en iyi çözüme dönülüp kısmi yeniden ısıtma (*reheating*, Thompson & Dowsland 1998) uygulanır.
* **Sert kısıt değişmezi:** Sert ihlali artıran hamleler kesin olarak reddedilir; geçerli (`sert = 0`) uzaydan çıkılmaz.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Sequence

from sinav_takvimi.cozuculer.hamleler import IyilestirmeSonucu, hareketli_sinavlar, rastgele_hamle
from sinav_takvimi.domain.artimli_degerlendirici import ArtimliDegerlendirici
from sinav_takvimi.domain.ayarlar import TavlamaAyarlari
from sinav_takvimi.domain.ceza import TOLERANS
from sinav_takvimi.domain.cozum import Cozum
from sinav_takvimi.domain.degerlendirici import Degerlendirici

ALGORITMA_TAVLAMA = "tavlama"
_SAAT_KONTROL_ARALIGI = 32
_MAKS_GECMIS_NOKTASI = 250


def sicaklik_kalibre_et(
    artimli: ArtimliDegerlendirici,
    ayar: TavlamaAyarlari,
    rng: random.Random,
    aday_sinavlar: Sequence[int],
) -> tuple[float, float, int]:
    """Ben-Ameur (2004) yöntemiyle veriye ve AHP ölçeğine uyumlu `(T0, T_son, pozitif_ornek)` hesaplar."""
    pr = artimli.problem
    mevcut_ceza = artimli.ceza()
    artilar: list[float] = []

    for _ in range(ayar.orneklem_boyutu):
        hamle = rastgele_hamle(pr, artimli.cozum, rng, ayar.takas_olasiligi, aday_sinavlar)
        if hamle is None:
            continue
        kayit = artimli.tasi(hamle)
        yeni_ceza = artimli.ceza()
        artimli.geri_al(kayit)
        if yeni_ceza.sert > mevcut_ceza.sert + TOLERANS:
            continue
        delta = yeni_ceza.yumusak - mevcut_ceza.yumusak
        if delta > TOLERANS:
            artilar.append(delta)

    if not artilar:
        return 1e-3, 1e-6, 0

    ln_chi0 = math.log(ayar.baslangic_kabul_orani)
    ort_delta = sum(artilar) / len(artilar)
    t0 = max(1e-9, -ort_delta / ln_chi0)
    en_buyuk_delta = max(artilar)

    # Ben-Ameur (2004) sabit nokta iterasyonu: T_{k+1} = T_k * (ln χ̂(T_k) / ln χ_0)
    for _ in range(30):
        t0 = max(t0, en_buyuk_delta * 1e-6)
        kabul = sum(math.exp(-min(700.0, d / t0)) for d in artilar) / len(artilar)
        if abs(kabul - ayar.baslangic_kabul_orani) <= 1e-4:
            break
        if kabul <= 1e-15:
            t0 *= 2.0
        elif kabul >= 1.0 - 1e-15:
            t0 *= 0.5
        else:
            t0 *= math.log(kabul) / ln_chi0

    sirali = sorted(artilar)
    delta_kucuk = sirali[max(0, len(sirali) // 20)]  # %5'lik dilim: sayısal gürültüye karşı dayanıklı en küçük fark
    t_son = min(t0 * 0.1, -delta_kucuk / math.log(ayar.bitis_kabul_orani))
    t_son = max(1e-9, t_son)
    return t0, t_son, len(artilar)


def tavlama_coz(
    cozum: Cozum,
    deg: Degerlendirici,
    ayar: TavlamaAyarlari | None = None,
    *,
    sure_sn: float | None = None,
    tohum: int = 0,
    maks_adim: int | None = None,
) -> IyilestirmeSonucu:
    """Başlangıç takvimini Benzetimli Tavlama ile iyileştirir (girdi `cozum` değiştirilmez)."""
    ayar = ayar or TavlamaAyarlari()
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
    t0, t_son, pozitif_ornek = sicaklik_kalibre_et(artimli, ayar, rng, aday_sinavlar)
    t_isitma = math.sqrt(t0 * t_son)

    gecmis: list[list[float]] = [[0.0, mevcut_ceza.yumusak, en_iyi_ceza.yumusak]]
    adim = kabul_sayisi = iyilestirme_sayisi = isitma_sayisi = 0
    son_iyilesme_orani = 0.0
    isitma_baslangic_orani: float | None = None
    son_kayit_orani = 0.0
    kayit_araligi = 1.0 / _MAKS_GECMIS_NOKTASI

    if aday_sinavlar and pr.P > 1:
        oran = 0.0
        while True:
            if maks_adim is not None:
                if adim >= maks_adim:
                    break
                oran = adim / maks_adim
            elif adim % _SAAT_KONTROL_ARALIGI == 0:
                gecen = time.perf_counter() - baslangic_zamani
                if gecen >= butce:
                    break
                oran = min(1.0, gecen / butce)

            # Tıkanmada en iyi çözüme dönüp kısmi yeniden ısıtma (Thompson & Dowsland 1998)
            if (
                ayar.yeniden_isitma_orani > 0
                and oran < 0.90
                and (oran - son_iyilesme_orani) >= ayar.yeniden_isitma_orani
            ):
                mevcut_cozum = en_iyi_cozum.kopya()
                artimli = ArtimliDegerlendirici(deg, mevcut_cozum)
                mevcut_ceza = artimli.ceza()
                isitma_baslangic_orani = oran
                son_iyilesme_orani = oran
                isitma_sayisi += 1

            if isitma_baslangic_orani is not None:
                yerel_oran = min(1.0, (oran - isitma_baslangic_orani) / max(1e-6, 1.0 - isitma_baslangic_orani))
                sicaklik = t_isitma * (t_son / t_isitma) ** yerel_oran
            else:
                sicaklik = t0 * (t_son / t0) ** oran

            adim += 1
            hamle = rastgele_hamle(pr, mevcut_cozum, rng, ayar.takas_olasiligi, aday_sinavlar)
            if hamle is None:
                continue

            kayit = artimli.tasi(hamle)
            yeni_ceza = artimli.ceza()

            # Sert kısıt değişmezi: sert ihlali artıran hamle asla kabul edilmez
            if yeni_ceza.sert > mevcut_ceza.sert + TOLERANS:
                artimli.geri_al(kayit)
                continue

            delta = yeni_ceza.yumusak - mevcut_ceza.yumusak
            if delta <= 0.0:
                kabul = True
            else:
                us = delta / max(1e-12, sicaklik)
                kabul = us < 700.0 and rng.random() < math.exp(-us)

            if kabul:
                mevcut_ceza = yeni_ceza
                kabul_sayisi += 1
                artimli.periyodik_yenile_gerekirse()
                if yeni_ceza < en_iyi_ceza:
                    en_iyi_ceza = yeni_ceza
                    en_iyi_cozum = mevcut_cozum.kopya()
                    iyilestirme_sayisi += 1
                    son_iyilesme_orani = oran
                    isitma_baslangic_orani = None
                    simdi = time.perf_counter() - baslangic_zamani
                    gecmis.append([round(simdi, 4), mevcut_ceza.yumusak, en_iyi_ceza.yumusak])
                    son_kayit_orani = oran
            else:
                artimli.geri_al(kayit)

            if oran - son_kayit_orani >= kayit_araligi:
                simdi = time.perf_counter() - baslangic_zamani
                gecmis.append([round(simdi, 4), mevcut_ceza.yumusak, en_iyi_ceza.yumusak])
                son_kayit_orani = oran

    toplam_sure = time.perf_counter() - baslangic_zamani
    if len(gecmis) == 1 or gecmis[-1][2] != en_iyi_ceza.yumusak:
        gecmis.append([round(toplam_sure, 4), mevcut_ceza.yumusak, en_iyi_ceza.yumusak])

    return IyilestirmeSonucu(
        algoritma=ALGORITMA_TAVLAMA,
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
            "t0": round(t0, 6),
            "t_son": round(t_son, 8),
            "kalibrasyon_pozitif_ornek": pozitif_ornek,
            "yeniden_isitma_sayisi": isitma_sayisi,
        },
    )
