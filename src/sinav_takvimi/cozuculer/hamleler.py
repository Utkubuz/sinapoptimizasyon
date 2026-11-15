"""Yerel arama komşuluk operatörleri ve ortak sonuç modeli.

Literatür dayanakları:
* **Kempe zinciri** (Thompson & Dowsland 1996, 1998, *Computers & Operations Research*): Sınav `e` kaynak oturum `p1`den
  hedef oturum `p2`ye taşındığında, `p1 ∪ p2` alt çizgesinde çakışan komşular (`H1` ortak öğrenci ∪ `H4` aynı hoca)
  üzerinden genişlik öncelikli aramayla (BFS) bağlantılı bileşen bulunur ve iki küme karşılıklı yer değiştirir.
  Karşı oturumda çakışan sınav yoksa (`|K| = 1`) doğal olarak **tekli taşıma**ya indirgenir.
* **İkili takas (*pair swap*)** (McCollum vd. 2010, ITC 2007 Track 1): Ortak öğrencisi/hocası olmayan iki sınavın
  `komsular` çizgesinde kenarı bulunmadığından Kempe zinciri bunları karşılıklı takas etmez; derslik kapasitesi veya
  erken/geç gün (`S4, S5, S6`) takası için tamamlayıcı operatör olarak kullanılır.
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

from sinav_takvimi.domain.ceza import Ceza
from sinav_takvimi.domain.cozum import Cozum
from sinav_takvimi.domain.problem import ProblemOrnegi

type Hamle = dict[int, int]


@dataclass(slots=True)
class IyilestirmeSonucu:
    """Metasezgisel çözücülerin (Benzetimli Tavlama, Tabu Arama) ortak çıktısı."""

    algoritma: str
    cozum: Cozum
    baslangic_ceza: Ceza
    en_iyi_ceza: Ceza
    adim_sayisi: int
    kabul_sayisi: int
    iyilestirme_sayisi: int
    sure_sn: float
    gecmis: list[list[float]] = field(default_factory=list)  # [gecen_sn, mevcut_yumusak, en_iyi_yumusak]
    ozet_parametreler: dict[str, float | int] = field(default_factory=dict)

    @property
    def iyilesme_orani(self) -> float:
        """Başlangıç yumuşak cezasına göre bağıl azalma oranı (ör. 0.35 → %35 iyileşme)."""
        if self.baslangic_ceza.yumusak <= 1e-12:
            return 0.0
        return (self.baslangic_ceza.yumusak - self.en_iyi_ceza.yumusak) / self.baslangic_ceza.yumusak


def _alan_uygun_mu(pr: ProblemOrnegi, e: int, p: int) -> bool:
    """Sınav `e`, oturum `p`nin H8/H9 sert alan kısıtlarını sağlıyor mu?"""
    return pr.dilim_uygun_mu(e, p)


def hareketli_sinavlar(pr: ProblemOrnegi, cozum: Cozum) -> list[int]:
    """Yerleşmiş ve en az iki geçerli oturum seçeneği olan sınavların indeks listesi."""
    return [
        e for e in range(pr.E)
        if cozum.dilim[e] is not None and not pr.uygun_dilimi_yok[e] and len(pr.uygun_dilimler[e]) > 1
    ]


def kempe_zinciri(pr: ProblemOrnegi, cozum: Cozum, e: int, hedef_p: int) -> Hamle | None:
    """`e` sınavını `hedef_p` oturumuna taşıyan en küçük Kempe zinciri hamlesini (`{sinav: yeni_dilim}`) üretir.

    Zincirdeki herhangi bir sınav karşı oturumun `H8` (süre) veya `H9` (sabit/yasak) kuralını ihlal ediyorsa `None`
    döner. Başlangıç çözümü H1/H4 çakışmasız ise dönen hamle de H1/H4 çakışmasızlığı korur.
    """
    kaynak_p = cozum.dilim[e]
    if kaynak_p is None or kaynak_p == hedef_p or not (0 <= hedef_p < pr.P):
        return None
    if not _alan_uygun_mu(pr, e, hedef_p):
        return None

    hamle: dict[int, int] = {e: hedef_p}
    kuyruk: deque[int] = deque([e])
    while kuyruk:
        u = kuyruk.popleft()
        yeni_p = hamle[u]
        karsi_p = kaynak_p if yeni_p == hedef_p else hedef_p
        for v in pr.komsular[u]:
            if cozum.dilim[v] == yeni_p and v not in hamle:
                if not _alan_uygun_mu(pr, v, karsi_p):
                    return None
                hamle[v] = karsi_p
                kuyruk.append(v)
    return hamle


def ikili_takas(pr: ProblemOrnegi, cozum: Cozum, e1: int, e2: int) -> Hamle | None:
    """Farklı oturumlardaki `e1` ve `e2` sınavlarını karşılıklı takas eder (`{e1: p2, e2: p1}`).

    Alan kısıtlarını (`H8, H9`) veya doğrudan çakışmayı (`H1, H4`) ihlal ediyorsa `None` döner.
    """
    if e1 == e2:
        return None
    p1, p2 = cozum.dilim[e1], cozum.dilim[e2]
    if p1 is None or p2 is None or p1 == p2:
        return None
    if not (_alan_uygun_mu(pr, e1, p2) and _alan_uygun_mu(pr, e2, p1)):
        return None
    if any(f != e2 and cozum.dilim[f] == p2 for f in pr.komsular[e1]):
        return None
    if any(f != e1 and cozum.dilim[f] == p1 for f in pr.komsular[e2]):
        return None
    return {e1: p2, e2: p1}


def rastgele_hamle(
    pr: ProblemOrnegi,
    cozum: Cozum,
    rng: random.Random,
    takas_olasiligi: float = 0.20,
    aday_sinavlar: Sequence[int] | None = None,
    en_fazla_deneme: int = 12,
) -> Hamle | None:
    """Alan ve çakışma ön-kontrolünden geçmiş rastgele bir Kempe zinciri veya ikili takas hamlesi döndürür."""
    havuz = aday_sinavlar if aday_sinavlar is not None else hareketli_sinavlar(pr, cozum)
    if not havuz or pr.P <= 1:
        return None

    for _ in range(en_fazla_deneme):
        if len(havuz) >= 2 and rng.random() < takas_olasiligi:
            e1, e2 = rng.sample(havuz, 2)
            takas = ikili_takas(pr, cozum, e1, e2)
            if takas is not None:
                return takas
        e = rng.choice(havuz)
        mevcut_p = cozum.dilim[e]
        uygunlar = [p for p in pr.uygun_dilimler[e] if p != mevcut_p]
        if not uygunlar:
            continue
        zincir = kempe_zinciri(pr, cozum, e, rng.choice(uygunlar))
        if zincir is not None:
            return zincir
    return None


def sinav_yumusak_agirliklari(pr: ProblemOrnegi, cozum: Cozum, aday_sinavlar: Sequence[int]) -> list[float]:
    """Di Gaspero & Schaerf (2001) aday listesi için sınav bazlı yumuşak sıkışıklık ağırlıkları.

    Yakın oturumlardaki ortak öğrenciler, hocasız oturum (`S11`) ve bölünmüş salonlar (`S5`) sınavın seçilme
    olasılığını artırır; taban `1.0` sayesinde hiçbir sınav tamamen dışlanmaz.
    """
    agirliklar: list[float] = []
    for e in aday_sinavlar:
        pe = cozum.dilim[e]
        if pe is None:
            agirliklar.append(1.0)
            continue
        puan = 1.0
        if not pr.hoca_musait[e][pe]:
            puan += 3.0
        if len(cozum.salonlari(e)) > 1:
            puan += 1.5
        for f, ortak in pr.cakisma[e].items():
            pf = cozum.dilim[f]
            if pf is None or pe == pf:
                continue
            if pr.ardisik(pe, pf):
                puan += ortak * 0.25
            elif pr.ayni_gun(pe, pf):
                puan += ortak * 0.15
            elif pr.gun_farki(pe, pf) <= 2:
                puan += ortak * 0.05
        agirliklar.append(puan)
    return agirliklar
