from sinav_takvimi.domain.ahp import AhpSonucu, esit_agirliklar
from sinav_takvimi.domain.kisitlar.sert import (
    H1OgrenciCakismasi,
    H2DerslikKapasitesi,
    H4HocaCakismasi,
    H7GozetmenKapasitesi,
    H8SinavSuresi,
    H9SabitYasakKural,
    H10OzelGereksinim,
    H11GunlukSinavSiniri,
)
from sinav_takvimi.domain.kisitlar.temel import CiftKisit, DilimKisit, Kisit, OgrenciKisit, TekliKisit
from sinav_takvimi.domain.kisitlar.yumusak import (
    S1ArkaArkaya,
    S2AyniGun,
    S3HazirlikSuresi,
    S4GecBuyukSinav,
    S5Bolunme,
    S6Israf,
    S7GundeUcSinav,
    S8Carter,
    S9OgrenciAdaleti,
    S10KohortAdaleti,
    S11HocasizSinav,
)


def sert_kisitlar() -> list[Kisit]:
    """Tüm sert kısıtlar (birim: etkilenen kişi); sert/yumuşak ayrımı `Ceza`da sözlükbilimseldir."""
    return [
        H1OgrenciCakismasi(),
        H2DerslikKapasitesi(),
        H4HocaCakismasi(),
        H7GozetmenKapasitesi(),
        H8SinavSuresi(),
        H9SabitYasakKural(),
        H10OzelGereksinim(),
        H11GunlukSinavSiniri(),
    ]


def yumusak_kisitlar(ahp: AhpSonucu | None = None) -> list[Kisit]:
    """Yumuşak kriterler, AHP küresel ağırlıklarıyla (anket yoksa eşit ağırlık). S8 sadece rapor (ağırlık 0)."""
    w = (ahp or esit_agirliklar()).kuresel
    siniflar: list[type[Kisit]] = [
        S1ArkaArkaya, S2AyniGun, S3HazirlikSuresi, S7GundeUcSinav,
        S9OgrenciAdaleti, S10KohortAdaleti,
        S4GecBuyukSinav, S5Bolunme, S6Israf, S11HocasizSinav,
    ]
    return [sinif(w[sinif.kod]) for sinif in siniflar] + [S8Carter(0.0)]


def tum_kisitlar(ahp: AhpSonucu | None = None) -> list[Kisit]:
    return sert_kisitlar() + yumusak_kisitlar(ahp)


__all__ = [
    "Kisit", "CiftKisit", "TekliKisit", "DilimKisit", "OgrenciKisit",
    "sert_kisitlar", "yumusak_kisitlar", "tum_kisitlar",
]
