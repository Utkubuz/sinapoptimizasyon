"""Kısıt motorunun temel sınıfları.

Kısıtlar soyut sınıflardır (ABC). Her kısıt dört biçimden birindedir:

* CiftKisit    : iki komşu sınavın dilimlerine bakar (ör. ortak öğrencisi olan sınavlar aynı anda olmasın)
* TekliKisit   : tek bir sınavın dilimine bakar (ör. sınav süresi oturuma sığıyor mu?)
* DilimKisit   : bir dilimin derslik dağıtımına bakar (ör. yer bulamayan öğrenci var mı?)
* OgrenciKisit : bütün öğrencilerin kişisel takvim analizine bakar (ör. öğrenciler arası eşitsizlik)

Kısıtlar sadece HAM ihlal miktarını hesaplar. Yumuşak kısıtlar ayrıca bir `payda` tanımlar: normalize değer
= ham ÷ payda, doğal bir orandır (ör. "öğrenci başına arka arkaya sınav"). Toplama, ağırlıklandırma ve
artımlı hesap `Degerlendirici` sınıfındadır; yeni bir kısıt eklemek için tek bir küçük sınıf yazmak yeterlidir.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from sinav_takvimi.domain.derslik_dagitici import DilimDagitimi
from sinav_takvimi.domain.problem import ProblemOrnegi

if TYPE_CHECKING:
    from sinav_takvimi.domain.ogrenci_analizi import OgrenciAnalizi


class Kisit(ABC):
    kod: str = ""
    ad: str = ""
    sert: bool = False
    birim: str = ""  # normalize değerin anlamı (raporlarda gösterilir)

    def __init__(self, agirlik: float = 1.0) -> None:
        self.agirlik = agirlik  # sert kısıtlarda 1 (birim: etkilenen kişi); yumuşaklarda AHP küresel ağırlığı
        self.payda: float = 1.0

    def hazirla(self, pr: ProblemOrnegi) -> None:  # noqa: B027 — isteğe bağlı kanca, varsayılanı "hiçbir şey yapma"
        """Probleme bağlı sabitleri (normalizasyon paydası) hesaplar. Değerlendirici bir kez çağırır."""

    def __repr__(self) -> str:
        return f"{self.kod} {self.ad} (ağırlık={self.agirlik:.4g})"


def _pozitif(x: float) -> float:
    """Payda 0 olamaz (ör. hiç ortak öğrencisi olmayan veri): o durumda ham değer zaten 0'dır."""
    return x if x > 0 else 1.0


class CiftKisit(Kisit):
    @abstractmethod
    def ihlal(self, pr: ProblemOrnegi, e: int, f: int, pe: int, pf: int) -> float:
        """e ve f komşu sınavlar, pe ve pf dilimleri. Simetrik olmalı: ihlal(e,f,pe,pf) == ihlal(f,e,pf,pe)."""


class TekliKisit(Kisit):
    @abstractmethod
    def ihlal(self, pr: ProblemOrnegi, e: int, p: int) -> float: ...


class DilimKisit(Kisit):
    @abstractmethod
    def ihlal(self, pr: ProblemOrnegi, p: int, dagitim: DilimDagitimi) -> float: ...


class OgrenciKisit(Kisit):
    @abstractmethod
    def ihlal(self, pr: ProblemOrnegi, analiz: OgrenciAnalizi) -> float: ...


__all__ = ["Kisit", "CiftKisit", "TekliKisit", "DilimKisit", "OgrenciKisit", "_pozitif"]
