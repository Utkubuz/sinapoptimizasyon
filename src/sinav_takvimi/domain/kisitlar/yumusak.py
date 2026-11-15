"""Yumuşak kriterler. Her biri HAM değer üretir; `payda` ile doğal bir orana çevrilir.

Ölçek eşitleme: Degerlendirici bir REFERANS takvim (yapıcı çözüm) verilirse her kriteri o takvimdeki
doğal değerine de böler; referansta her kriter 1 olur ve AHP ağırlığı gerçekten sadece önem anlamı taşır.

| Kod | Ham                                         | Payda               | Normalize anlam                         |
|-----|---------------------------------------------|---------------------|-----------------------------------------|
| S1  | arka arkaya sınavı olan öğrenci-çift        | aktif öğrenci       | öğrenci başına arka arkaya sınav        |
| S2  | aynı gün (ardışık olmayan) öğrenci-çift     | aktif öğrenci       | öğrenci başına aynı gün sınav           |
| S3  | FARKLI gün çiftleri: Σ ortak × (z₁z₂/25)/(1+gün farkı) | Σ ortak öğrenci | 0–1 "zorluk-yakınlık" oranı |
| S4  | Σ (n/n_max) × (gün/son gün)                 | Σ (n/n_max)         | 0–1 büyük sınavların ne kadar geç olduğu|
| S5  | ek derslik (ana grup)                       | sınav sayısı        | sınav başına ek salon                   |
| S6  | boş koltuk (ana grup salonları)             | Σ sınav öğrencisi   | oturan öğrenci başına boş koltuk        |
| S7  | Σ max(0, günlük sınav − 2)                  | aktif öğrenci       | öğrenci başına fazladan günlük sınav    |
| S8  | Carter: Σ ortak × 2^(5−s), s ≤ 5 oturum     | aktif öğrenci       | sadece RAPOR (ağırlık 0; literatür kıyası) |
| S9  | √(ortalama p²), p: çift başına kişisel ceza | 1                   | konveks, monoton adalet                 |
| S10 | kohort ortalamalarının karesel ortalaması   | 1                   | konveks, monoton grup adaleti           |
| S11 | hocası müsait olmayan sınav                 | sınav sayısı        | hocasız sınav oranı                     |

S6 notu: payda "kullanılan koltuk" olsaydı oran çözüme bağlı (toplanamaz) olurdu; bu yüzden sabit
payda "Σ sınav öğrencisi" seçildi.
"""

from __future__ import annotations

from sinav_takvimi.domain.derslik_dagitici import DilimDagitimi
from sinav_takvimi.domain.kisitlar.temel import CiftKisit, DilimKisit, OgrenciKisit, TekliKisit, _pozitif
from sinav_takvimi.domain.ogrenci_analizi import OgrenciAnalizi, hazirlik_cezasi
from sinav_takvimi.domain.problem import ProblemOrnegi


class S1ArkaArkaya(CiftKisit):
    kod, ad, birim = "S1", "Arka arkaya iki sınav", "öğrenci başına"

    def hazirla(self, pr: ProblemOrnegi) -> None:
        self.payda = _pozitif(pr.aktif_ogrenci_sayisi)

    def ihlal(self, pr: ProblemOrnegi, e: int, f: int, pe: int, pf: int) -> float:
        return pr.cakisma[e].get(f, 0) if pe != pf and pr.ardisik(pe, pf) else 0


class S2AyniGun(CiftKisit):
    kod, ad, birim = "S2", "Aynı gün iki sınav", "öğrenci başına"

    def hazirla(self, pr: ProblemOrnegi) -> None:
        self.payda = _pozitif(pr.aktif_ogrenci_sayisi)

    def ihlal(self, pr: ProblemOrnegi, e: int, f: int, pe: int, pf: int) -> float:
        if pe == pf or not pr.ayni_gun(pe, pf) or pr.ardisik(pe, pf):
            return 0
        return pr.cakisma[e].get(f, 0)


class S3HazirlikSuresi(CiftKisit):
    kod, ad, birim = "S3", "Zor sınavlar arası hazırlık süresi", "0–1 oran"

    def hazirla(self, pr: ProblemOrnegi) -> None:
        self.payda = _pozitif(pr.toplam_ortak)

    def ihlal(self, pr: ProblemOrnegi, e: int, f: int, pe: int, pf: int) -> float:
        if pr.ayni_gun(pe, pf):
            return 0  # aynı gün S1/S2/S7'de sayılır; her çift bir kez
        return pr.cakisma[e].get(f, 0) * hazirlik_cezasi(pr, e, f, pe, pf)


class S4GecBuyukSinav(TekliKisit):
    kod, ad, birim = "S4", "Büyük sınavın dönem sonunda olması", "0–1 oran"

    def hazirla(self, pr: ProblemOrnegi) -> None:
        self.payda = _pozitif(sum(n / pr.en_buyuk_sinav for n in pr.ogrenci_sayisi) if pr.en_buyuk_sinav else 0)

    def ihlal(self, pr: ProblemOrnegi, e: int, p: int) -> float:
        if pr.son_gun == 0 or pr.en_buyuk_sinav == 0:
            return 0
        return (pr.ogrenci_sayisi[e] / pr.en_buyuk_sinav) * (pr.dilim_gun[p] / pr.son_gun)


class S5Bolunme(DilimKisit):
    kod, ad, birim = "S5", "Sınavın ek dersliğe bölünmesi", "sınav başına"

    def hazirla(self, pr: ProblemOrnegi) -> None:
        self.payda = _pozitif(pr.E)

    def ihlal(self, pr: ProblemOrnegi, p: int, dagitim: DilimDagitimi) -> float:
        return dagitim.ek_derslik


class S6Israf(DilimKisit):
    kod, ad, birim = "S6", "Boş kalan koltuk", "öğrenci başına"

    def hazirla(self, pr: ProblemOrnegi) -> None:
        self.payda = _pozitif(pr.toplam_ogrenci)

    def ihlal(self, pr: ProblemOrnegi, p: int, dagitim: DilimDagitimi) -> float:
        return dagitim.bos_koltuk


class S7GundeUcSinav(OgrenciKisit):
    kod, ad, birim = "S7", "Günde 3 veya daha fazla sınav", "öğrenci başına"

    def hazirla(self, pr: ProblemOrnegi) -> None:
        self.payda = _pozitif(pr.aktif_ogrenci_sayisi)

    def ihlal(self, pr: ProblemOrnegi, analiz: OgrenciAnalizi) -> float:
        return sum(analiz.a7)


class S8Carter(CiftKisit):
    kod, ad, birim = "S8", "Carter yakınlık maliyeti (rapor)", "öğrenci başına"

    def hazirla(self, pr: ProblemOrnegi) -> None:
        self.payda = _pozitif(pr.aktif_ogrenci_sayisi)

    def ihlal(self, pr: ProblemOrnegi, e: int, f: int, pe: int, pf: int) -> float:
        s = abs(pe - pf)  # Carter: oturumlar ardışık numaralı kabul edilir (gün sınırı yok)
        return pr.cakisma[e].get(f, 0) * 2 ** (5 - s) if 1 <= s <= 5 else 0


class S9OgrenciAdaleti(OgrenciKisit):
    kod, ad, birim = "S9", "Öğrenci adaleti (kişisel cezaların karesel ortalaması)", "çift başına"

    def ihlal(self, pr: ProblemOrnegi, analiz: OgrenciAnalizi) -> float:
        return analiz.ogrenci_karesel()


class S10KohortAdaleti(OgrenciKisit):
    kod, ad, birim = "S10", "Kohort adaleti (grup ortalamalarının karesel ortalaması)", "çift başına"

    def ihlal(self, pr: ProblemOrnegi, analiz: OgrenciAnalizi) -> float:
        return analiz.kohort_karesel()


class S11HocasizSinav(TekliKisit):
    kod, ad, birim = "S11", "Hocası müsait olmayan sınav", "sınav başına"

    def hazirla(self, pr: ProblemOrnegi) -> None:
        self.payda = _pozitif(pr.E)

    def ihlal(self, pr: ProblemOrnegi, e: int, p: int) -> float:
        return 0 if pr.hoca_musait[e][p] else 1
