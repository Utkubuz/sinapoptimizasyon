"""Ceza: bir takvimin kalitesi = (sert ihlal, yumuşak ceza), sözlükbilimsel karşılaştırma.

ITC 2007'de olduğu gibi önce sert ihlale bakılır; sert ihlali az olan çözüm, yumuşak cezası ne olursa olsun daha
iyidir. Bu sayede "sert ihlal × 10000" gibi keyfi bir sabite gerek kalmaz.
"""

from __future__ import annotations

from dataclasses import dataclass

TOLERANS = 1e-9  # kayan nokta toplama hatalarına karşı (0.1 + 0.2 ≠ 0.3)


@dataclass(frozen=True, slots=True)
class Ceza:
    sert: float = 0.0
    yumusak: float = 0.0

    def __add__(self, o: Ceza) -> Ceza:
        return Ceza(self.sert + o.sert, self.yumusak + o.yumusak)

    def __sub__(self, o: Ceza) -> Ceza:
        return Ceza(self.sert - o.sert, self.yumusak - o.yumusak)

    def __lt__(self, o: Ceza) -> bool:
        if abs(self.sert - o.sert) > TOLERANS:
            return self.sert < o.sert
        return self.yumusak < o.yumusak - TOLERANS

    def __le__(self, o: Ceza) -> bool:
        return not o < self

    def __gt__(self, o: Ceza) -> bool:
        return o < self

    def __ge__(self, o: Ceza) -> bool:
        return not self < o

    def esit_mi(self, o: Ceza) -> bool:
        return abs(self.sert - o.sert) <= TOLERANS and abs(self.yumusak - o.yumusak) <= TOLERANS

    @property
    def uygun(self) -> bool:
        """Sert ihlal yok mu? (ITC'deki 'feasible')"""
        return self.sert <= TOLERANS

    def __str__(self) -> str:
        return f"sert={self.sert:g}, yumuşak={self.yumusak:.4f}"
