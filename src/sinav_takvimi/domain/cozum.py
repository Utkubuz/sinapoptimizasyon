"""Cozum: bir sınav takviminin bellekteki hâli (hangi sınav hangi dilimde + her dilimin derslik dağıtımı)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sinav_takvimi.domain.derslik_dagitici import BOS_DAGITIM, DilimDagitimi, SalonAtamasi, dagit, dagitim_kur
from sinav_takvimi.domain.problem import ProblemOrnegi


@dataclass(frozen=True, slots=True)
class GeriAlma:
    eski_dilim: dict[int, int | None]  # taşınan sınav → önceki dilimi
    eski_dagitim: dict[int, DilimDagitimi]  # etkilenen dilim → önceki derslik dağıtımı

    @property
    def etkilenen(self) -> set[int]:
        return set(self.eski_dagitim)


class Cozum:
    __slots__ = ("problem", "dilim", "dilim_sinavlari", "dagitim")

    def __init__(self, problem: ProblemOrnegi) -> None:
        self.problem = problem
        self.dilim: list[int | None] = [None] * problem.E  # e → p (None: henüz yerleşmedi)
        self.dilim_sinavlari: list[set[int]] = [set() for _ in range(problem.P)]  # p → {e}
        self.dagitim: list[DilimDagitimi] = [BOS_DAGITIM] * problem.P  # p → derslik dağıtımı

    @classmethod
    def atamalardan(cls, problem: ProblemOrnegi, atamalar: Mapping[int, int | None]) -> Cozum:
        """{e: p} sözlüğünden çözüm kurar (derslikleri dağıtıcı ile hesaplar)."""
        c = cls(problem)
        c.tasi(atamalar)
        return c

    @classmethod
    def kayittan(
        cls,
        problem: ProblemOrnegi,
        atamalar: Mapping[int, int | None],
        salonlar: Mapping[int, Sequence[SalonAtamasi]],
        ozel_yerlesim: Mapping[int, Sequence[tuple[int, int]]],
    ) -> Cozum:
        """Kayıtlı oturum, derslik ve özel öğrenci yerleşimlerinden (dağıtıcıyı yeniden çalıştırmadan) çözüm kurar."""
        c = cls(problem)
        for e, p in atamalar.items():
            if p is not None:
                c.dilim[e] = p
                c.dilim_sinavlari[p].add(e)
        for p in range(problem.P):
            if c.dilim_sinavlari[p]:
                c.dagitim[p] = dagitim_kur(problem, p, c.dilim_sinavlari[p], salonlar, ozel_yerlesim)
        return c

    def kopya(self) -> Cozum:
        yeni = Cozum.__new__(Cozum)
        yeni.problem = self.problem
        yeni.dilim = list(self.dilim)
        yeni.dilim_sinavlari = [set(s) for s in self.dilim_sinavlari]
        yeni.dagitim = list(self.dagitim)  # DilimDagitimi değiştirilemez, paylaşmak güvenli
        return yeni

    def tasi(self, hamle: Mapping[int, int | None]) -> GeriAlma:
        """Bir veya birden çok sınavı yeni dilimlerine taşır (None: yerleşimi kaldır) ve etkilenen dilimlerin
        dersliklerini yeniden dağıtır. Çoklu sınav hamlesi (Kempe zinciri, takas) tek çağrıda yapılır.

        Dönen `GeriAlma` ile hamle, derslikler yeniden dağıtılmadan geri alınabilir. Ayrıca etkilenen dilimlerin
        ESKİ dağıtımlarını taşır; artımlı ceza hesabı bunları kullanır.
        """
        eski_dilim: dict[int, int | None] = {}
        etkilenen: set[int] = set()
        for e, yeni in hamle.items():
            eski = self.dilim[e]
            if eski == yeni:
                continue
            eski_dilim.setdefault(e, eski)
            if eski is not None:
                self.dilim_sinavlari[eski].discard(e)
                etkilenen.add(eski)
            if yeni is not None:
                self.dilim_sinavlari[yeni].add(e)
                etkilenen.add(yeni)
            self.dilim[e] = yeni
        eski_dagitim = {p: self.dagitim[p] for p in etkilenen}
        for p in etkilenen:
            self.dagitim[p] = dagit(self.problem, p, self.dilim_sinavlari[p])
        return GeriAlma(eski_dilim, eski_dagitim)

    def geri_al(self, g: GeriAlma) -> None:
        """`tasi`nın yaptığını geri alır. Sadece en son yapılan hamle geri alınmalı (yığın düzeni)."""
        for e, eski in g.eski_dilim.items():
            simdiki = self.dilim[e]
            if simdiki is not None:
                self.dilim_sinavlari[simdiki].discard(e)
            if eski is not None:
                self.dilim_sinavlari[eski].add(e)
            self.dilim[e] = eski
        for p, d in g.eski_dagitim.items():
            self.dagitim[p] = d

    def yerlesmemis(self) -> list[int]:
        return [e for e, p in enumerate(self.dilim) if p is None]

    def salonlari(self, e: int) -> tuple[SalonAtamasi, ...]:
        p = self.dilim[e]
        return () if p is None else self.dagitim[p].atamalar.get(e, ())
