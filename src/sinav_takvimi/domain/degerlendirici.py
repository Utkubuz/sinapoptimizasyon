"""Degerlendirici: kısıtları toplayıp bir takvimin `Ceza`sını ve kısıt bazlı raporunu üretir.

* Sert kısıtlar: ham ihlal (etkilenen kişi) doğrudan `Ceza.sert`e eklenir.
* Yumuşak kriterler: doğal değer = ham ÷ payda. Bir REFERANS takvim verilmişse (yapıcı çözüm)
  normalize değer = doğal değer ÷ referanstaki doğal değer, yani referansta her kriter 1'dir. Referansta 0 olan
  kriterin ölçeği rastgele tam takvimlerin ortalamasıdır. Ceza = AHP küresel ağırlığı × normalize değer.
  Ölçek sabit olduğu için artımlı (delta) hesap bozulmaz.

Bu sürüm *tam hesap* yapar (her çağrıda takvimin tamamını tarar). `fark()` metodu çoklu sınav hamlesinin etkisini
uygula → hesapla → geri al ile bulur. Artımlı (delta) hesabın referansı ve test hakemi budur.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass

from sinav_takvimi.domain.ahp import AhpSonucu, esit_agirliklar
from sinav_takvimi.domain.ceza import Ceza
from sinav_takvimi.domain.cozum import Cozum
from sinav_takvimi.domain.kisitlar import (
    CiftKisit,
    DilimKisit,
    Kisit,
    OgrenciKisit,
    TekliKisit,
    tum_kisitlar,
)
from sinav_takvimi.domain.ogrenci_analizi import OgrenciAnalizi
from sinav_takvimi.domain.problem import ProblemOrnegi

REFERANS_RASTGELE_ORNEK = 30  # istatistiksel örneklem büyüklüğü (referansta 0 olan kriterlerin ölçeği için)
YERLESMEMIS = "Y0"  # yerleşmemiş sınav: öğrenci sayısı kadar sert ihlal (ITC'deki "uygunluğa uzaklık" fikri)


@dataclass(frozen=True, slots=True)
class KisitSonucu:
    kod: str
    ad: str
    sert: bool
    ihlal: float  # ham değer (sertte: etkilenen kişi)
    deger: float  # normalize değer (sertte = ham)
    agirlik: float
    ceza: float  # sertte = ham; yumuşakta = ağırlık × normalize
    birim: str = ""


class Degerlendirici:
    def __init__(
        self,
        problem: ProblemOrnegi,
        kisitlar: list[Kisit] | None = None,
        ahp: AhpSonucu | None = None,
        referans: Mapping[str, float] | None = None,
    ) -> None:
        self.problem = problem
        self.ahp = ahp or esit_agirliklar()
        self.kisitlar = kisitlar if kisitlar is not None else tum_kisitlar(self.ahp)
        for k in self.kisitlar:
            k.hazirla(problem)
        self.cift = [k for k in self.kisitlar if isinstance(k, CiftKisit)]
        self.tekli = [k for k in self.kisitlar if isinstance(k, TekliKisit)]
        self.dilimsel = [k for k in self.kisitlar if isinstance(k, DilimKisit)]
        self.ogrencisel = [k for k in self.kisitlar if isinstance(k, OgrenciKisit)]
        self.konfor_agirliklari = self.ahp.yerel("ogrenci_konforu")  # öğrencinin kişisel cezası p_s için
        self.referans: dict[str, float] = dict(referans or {})  # kriter → ölçek (referanstaki doğal değer)
        self.referans_kaynagi: dict[str, str] = {}

    def analiz(self, cozum: Cozum) -> OgrenciAnalizi:
        return OgrenciAnalizi.hesapla(self.problem, cozum, self.konfor_agirliklari)

    def ihlaller(self, cozum: Cozum) -> dict[str, float]:
        """Kısıt kodu → HAM ihlal (tam hesap)."""
        pr = self.problem
        sonuc: dict[str, float] = {YERLESMEMIS: 0.0, **{k.kod: 0.0 for k in self.kisitlar}}
        for e, pe in enumerate(cozum.dilim):
            if pe is None:
                sonuc[YERLESMEMIS] += pr.ogrenci_sayisi[e]
                continue
            for k in self.tekli:
                sonuc[k.kod] += k.ihlal(pr, e, pe)
            for f in pr.komsular[e]:
                pf = cozum.dilim[f]
                if f > e and pf is not None:  # her çift bir kez
                    for c in self.cift:
                        sonuc[c.kod] += c.ihlal(pr, e, f, pe, pf)
        for p in range(pr.P):
            for d in self.dilimsel:
                sonuc[d.kod] += d.ihlal(pr, p, cozum.dagitim[p])
        if self.ogrencisel:
            analiz = self.analiz(cozum)
            for o in self.ogrencisel:
                sonuc[o.kod] += o.ihlal(pr, analiz)
        return sonuc

    def sert_ihlaller(self, cozum: Cozum) -> dict[str, float]:
        """Sadece sıfırdan farklı sert ihlaller (doğrulayıcıyla karşılaştırma için)."""
        sert_kodlar = {YERLESMEMIS} | {k.kod for k in self.kisitlar if k.sert}
        return {k: v for k, v in self.ihlaller(cozum).items() if k in sert_kodlar and v}

    def rapor(self, cozum: Cozum) -> list[KisitSonucu]:
        ihlal = self.ihlaller(cozum)
        y = ihlal[YERLESMEMIS]
        satirlar = [KisitSonucu(YERLESMEMIS, "Yerleşmemiş sınav", True, y, y, 1.0, y, "öğrenci")]
        for k in self.kisitlar:
            ham = ihlal[k.kod]
            if k.sert:
                satirlar.append(KisitSonucu(k.kod, k.ad, True, ham, ham, 1.0, ham, "kişi"))
            else:
                deger = ham / k.payda / self.olcek(k.kod)
                satirlar.append(KisitSonucu(k.kod, k.ad, False, ham, deger, k.agirlik, k.agirlik * deger, k.birim))
        return satirlar

    def olcek(self, kod: str) -> float:
        """Yumuşak kriter `kod` için referans ölçeği (belirlenmemişse `1.0`)."""
        ref = self.referans.get(kod, 0.0)
        return ref if ref > 1e-12 else 1.0

    def dogal_degerler(self, cozum: Cozum) -> dict[str, float]:
        """Yumuşak kriterlerin doğal (ham ÷ payda) değerleri: referans olarak saklanmak üzere."""
        ihlal = self.ihlaller(cozum)
        return {k.kod: ihlal[k.kod] / k.payda for k in self.kisitlar if not k.sert}

    def referans_belirle(
        self, cozum: Cozum, rastgele_ornek: int = REFERANS_RASTGELE_ORNEK, tohum: int = 0
    ) -> dict[str, float]:
        """Bu takvimi ölçek referansı yapar ve referans ölçeklerini döndürür
        (çalıştırma kaydında saklanır).

        * Referans TAM olmalıdır (her sınav yerleşmiş): yarım takvimin doğal değerleri küçük çıkar
          ve bütün ölçeği bozar.
        * Referansta 0 olan kriter (zaten ideal) için ölçek "kötü uç"tan alınır: rastgele üretilmiş tam takvimlerin
          ortalaması (ÇKKV'deki ideal-nadir normalizasyonu). `rastgele_ornek` bir istatistiksel örneklem büyüklüğüdür,
          sonuç `tohum` ile tekrarlanabilir. Kriter rastgele takvimlerde de hiç oluşmuyorsa ölçek 1'dir.
        * Sadece rapor amaçlı kriterler (ağırlık 0, ör. Carter) literatürle kıyas için doğal ölçeğinde kalır.
        """
        if cozum.yerlesmemis():
            raise ValueError(
                f"Referans takvim tam olmalı: {len(cozum.yerlesmemis())} sınav yerleşmemiş"
            )
        agirlikli = {k.kod for k in self.kisitlar if not k.sert and k.agirlik > 0}
        olcek = {kod: v for kod, v in self.dogal_degerler(cozum).items() if kod in agirlikli}
        sifirlar = [kod for kod, v in olcek.items() if v <= 1e-12]
        self.referans_kaynagi = dict.fromkeys(olcek, "referans")
        if sifirlar:
            rng = random.Random(tohum)
            pr = self.problem
            toplam = dict.fromkeys(sifirlar, 0.0)
            for _ in range(rastgele_ornek):
                c = Cozum.atamalardan(pr, {e: rng.choice(pr.uygun_dilimler[e]) for e in range(pr.E)})
                d = self.dogal_degerler(c)
                for kod in sifirlar:
                    toplam[kod] += d[kod]
            for kod in sifirlar:
                ort = toplam[kod] / rastgele_ornek
                olcek[kod] = ort if ort > 1e-12 else 1.0
                self.referans_kaynagi[kod] = "rastgele ortalama" if ort > 1e-12 else "oluşmuyor (1)"
        self.referans = olcek
        return dict(self.referans)

    def degerlendir(self, cozum: Cozum) -> Ceza:
        sert = yumusak = 0.0
        for s in self.rapor(cozum):
            if s.sert:
                sert += s.ceza
            else:
                yumusak += s.ceza
        return Ceza(sert, yumusak)

    def fark(self, cozum: Cozum, hamle: Mapping[int, int | None]) -> Ceza:
        """Hamle uygulanırsa ceza ne kadar değişir? Çözüm sonunda değişmemiş olur (uygula → tam hesap → geri al).

        Referans uygulamadır; artımlı hesap bununla karşılaştırılarak test edilir.
        """
        once = self.degerlendir(cozum)
        geri = cozum.tasi(hamle)
        sonra = self.degerlendir(cozum)
        cozum.geri_al(geri)
        return sonra - once
