"""Öğrenci bazlı takvim analizi: her öğrencinin kişisel "rahatsızlık" cezası ve kohort ortalamaları.

Bir öğrencinin yerleşmiş sınavları için (aynı oturumdaki sınavlar sert ihlaldir, H1; yumuşak cezaya katılmaz):
    a1 = arka arkaya (aynı gün, ardışık oturum) çift sayısı                                → S1
    a2 = aynı gün, ardışık olmayan çift sayısı                                             → S2
    a3 = FARKLI günlerdeki çiftler için Σ (zorluk₁·zorluk₂/25) / (1 + gün farkı)            → S3
         (aynı gün zaten S1/S2/S7'de; her çift bir kez sayılır)
    a7 = Σ_gün max(0, o günkü farklı oturum sayısı − 2)   (UniTime "günde 3+")               → S7
    h11 = Σ_gün max(0, sınıra sayılan farklı oturum − kurum üst sınırı)                       → H11 (sert)
    ham p = w1·a1 + w2·a2 + w3·a3 + w7·a7   (w: AHP "öğrenci konforu" grubunun yerel ağırlıkları)
    p     = ham p ÷ max(1, C(n, 2))         (n: KAYITLI sınav sayısı → ÇİFT BAŞINA ceza)

Çift başına normalizasyonun nedeni: 7 sınavlı öğrencinin 21, 4 sınavlı öğrencinin 6 sınav çifti var. Ham ceza ders
yükünü ölçer; p ise "bu öğrencinin takvimi ne kadar sıkışık?" sorusunu ders yükünden bağımsız yanıtlar. Payda kayıtlı
(yerleşmiş değil) sınav sayısıdır: böylece bir sınavın yerleşmesi diğerlerinin cezasını yapay olarak düşürmez.

Adalet: S9 = √(ortalama p²), S10 = √(Σ_c n_c · m_c² / N) (m_c: kohort ortalaması). İkisi de MONOTONDUR
(kimsenin cezası artmadan artmaz) ve KONVEKSTİR (cezanın birkaç kişide/grupta yığılması daha pahalıdır).
Değişim katsayısı ve Gini sadece raporda kullanılır: onlar göreli ölçülerdir, herkesi kötüleştiren bir takvimi
"daha adil" gösterebilirler.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sinav_takvimi.domain.cozum import Cozum
from sinav_takvimi.domain.problem import ProblemOrnegi


def hazirlik_cezasi(pr: ProblemOrnegi, e: int, f: int, pe: int, pf: int) -> float:
    """S3'ün bir öğrenci için tek çift katkısı (farklı günler; zorluk ve gün farkıyla sürekli, eşik yok)."""
    return pr.zorluk[e] * pr.zorluk[f] / 25 / (1 + pr.gun_farki(pe, pf))


def karesel_ortalama(degerler: list[float], agirliklar: list[float] | None = None) -> float:
    """√(Σ w·x² / Σ w). Boş liste → 0."""
    if not degerler:
        return 0.0
    w = agirliklar or [1.0] * len(degerler)
    toplam_w = sum(w)
    return math.sqrt(sum(a * x * x for x, a in zip(degerler, w, strict=True)) / toplam_w) if toplam_w else 0.0


def degisim_katsayisi(degerler: list[float], agirliklar: list[float] | None = None) -> float:
    """σ/μ (ağırlıklı, nüfus). μ = 0 ise 0. SADECE RAPOR İÇİN (monoton değildir)."""
    if not degerler:
        return 0.0
    w = agirliklar or [1.0] * len(degerler)
    toplam_w = sum(w)
    mu = sum(x * a for x, a in zip(degerler, w, strict=True)) / toplam_w
    if mu <= 1e-12:
        return 0.0
    var = sum(a * (x - mu) ** 2 for x, a in zip(degerler, w, strict=True)) / toplam_w
    return math.sqrt(var) / mu


def gini(degerler: list[float]) -> float:
    """Gini katsayısı (0: tam eşitlik, 1'e yakın: ceza birkaç kişide toplanmış). SADECE RAPOR İÇİN."""
    n = len(degerler)
    toplam = sum(degerler)
    if n == 0 or toplam <= 1e-12:
        return 0.0
    sirali = sorted(degerler)
    return sum((2 * (i + 1) - n - 1) * x for i, x in enumerate(sirali)) / (n * toplam)


def jain_indeksi(degerler: list[float]) -> float:
    """Jain adalet indeksi (Σx)² / (n·Σx²) ∈ (0, 1]; 1 = herkes eşit. Muklason vd. (MISTA 2013) bunu kullanır.
    = 1 / (1 + CV²): göreli bir ölçüdür, SADECE RAPOR İÇİN. Kimsenin cezası yoksa 1."""
    n = len(degerler)
    kare = sum(x * x for x in degerler)
    if n == 0 or kare <= 1e-24:
        return 1.0
    return sum(degerler) ** 2 / (n * kare)


@dataclass(frozen=True, slots=True)
class OgrenciAnalizi:
    a1: list[float]
    a2: list[float]
    a3: list[float]
    a7: list[float]
    h11: list[float]  # günlük sınav üst sınırı aşımı (sert)
    p: list[float]  # çift başına kişisel ceza (sadece aktif öğrenciler anlamlı)
    aktif: list[bool]  # en az bir yerleşmiş sınavı olan öğrenci
    kohort_ortalama: list[float]
    kohort_boyut: list[int]

    @classmethod
    def hesapla(cls, pr: ProblemOrnegi, cozum: Cozum, w: dict[str, float]) -> OgrenciAnalizi:
        w1, w2, w3, w7 = w.get("S1", 0.0), w.get("S2", 0.0), w.get("S3", 0.0), w.get("S7", 0.0)
        a1 = [0.0] * pr.S
        a2 = [0.0] * pr.S
        a3 = [0.0] * pr.S
        a7 = [0.0] * pr.S
        h11 = [0.0] * pr.S
        p = [0.0] * pr.S
        aktif = [False] * pr.S
        for s, sinavlar in enumerate(pr.ogrenci_sinavlari):
            yerlesik = [(e, cozum.dilim[e]) for e in sinavlar if cozum.dilim[e] is not None]
            if not yerlesik:
                continue
            aktif[s] = True
            gun_oturumlari: dict[int, set[int]] = {}
            for i, (e, pe) in enumerate(yerlesik):
                assert pe is not None
                gun_oturumlari.setdefault(pr.dilim_gun[pe], set()).add(pe)
                for f, pf in yerlesik[i + 1 :]:
                    assert pf is not None
                    if pe == pf:
                        continue  # sert ihlal (H1); yumuşak cezaya katılmaz
                    if pr.ardisik(pe, pf):
                        a1[s] += 1
                    elif pr.ayni_gun(pe, pf):
                        a2[s] += 1
                    else:
                        a3[s] += hazirlik_cezasi(pr, e, f, pe, pf)
            a7[s] = sum(max(0, len(o) - 2) for o in gun_oturumlari.values())
            if pr.gunluk_ust_sinir is not None:
                sayilan: dict[int, set[int]] = {}
                for e, pe in yerlesik:
                    if e in pr.sinira_sayilan[s] and pe is not None:
                        sayilan.setdefault(pr.dilim_gun[pe], set()).add(pe)
                h11[s] = sum(max(0, len(o) - pr.gunluk_ust_sinir) for o in sayilan.values())
            n = len(sinavlar)
            p[s] = (w1 * a1[s] + w2 * a2[s] + w3 * a3[s] + w7 * a7[s]) / max(1, n * (n - 1) // 2)

        kohort_toplam = [0.0] * len(pr.kohortlar)
        kohort_boyut = [0] * len(pr.kohortlar)
        for s in range(pr.S):
            if aktif[s]:
                kohort_toplam[pr.ogrenci_kohort[s]] += p[s]
                kohort_boyut[pr.ogrenci_kohort[s]] += 1
        kohort_ortalama = [t / n if n else 0.0 for t, n in zip(kohort_toplam, kohort_boyut, strict=True)]
        return cls(a1, a2, a3, a7, h11, p, aktif, kohort_ortalama, kohort_boyut)

    def aktif_cezalar(self) -> list[float]:
        return [x for x, a in zip(self.p, self.aktif, strict=True) if a]

    def _dolu_kohortlar(self) -> tuple[list[float], list[float]]:
        dolu = [(m, n) for m, n in zip(self.kohort_ortalama, self.kohort_boyut, strict=True) if n > 0]
        return [m for m, _ in dolu], [float(n) for _, n in dolu]

    # --- Optimizasyonda kullanılan adalet ölçütleri (monoton, konveks) ---
    def ogrenci_karesel(self) -> float:  # S9
        return karesel_ortalama(self.aktif_cezalar())

    def kohort_karesel(self) -> float:  # S10
        return karesel_ortalama(*self._dolu_kohortlar())

    # --- Sadece raporda kullanılan göreli ölçütler ---
    def ogrenci_cv(self) -> float:
        return degisim_katsayisi(self.aktif_cezalar())

    def kohort_cv(self) -> float:
        return degisim_katsayisi(*self._dolu_kohortlar())
