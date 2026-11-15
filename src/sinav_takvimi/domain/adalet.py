"""Adalet raporu: öğrencilerin çift başına cezalarının dağılımı ve kohort karşılaştırması.

Optimizasyon S9/S10 ile eşitsizliği azaltır; bu rapor ise "ceza kime düştü?" sorusunu açıkça gösterir.
"En kötü %10" bir rapor dilimidir (yüzdelik), modelin parametresi değildir.
"""

from __future__ import annotations

from dataclasses import dataclass

from sinav_takvimi.domain.ogrenci_analizi import OgrenciAnalizi, gini, jain_indeksi
from sinav_takvimi.domain.problem import ProblemOrnegi


@dataclass(frozen=True, slots=True)
class KohortSatiri:
    bolum_kod: str
    sinif: int
    ogrenci: int
    ortalama_ceza: float


@dataclass(frozen=True, slots=True)
class AdaletRaporu:
    ogrenci_sayisi: int
    ortalama: float
    medyan: float
    en_kotu_yuzde10_ortalamasi: float
    en_kotu: float
    cezasiz_oran: float  # hiç rahatsızlığı olmayan öğrencilerin oranı
    degisim_katsayisi: float  # göreli eşitsizlik (rapor)
    karesel_ortalama: float  # S9
    gini: float
    jain: float  # Jain adalet indeksi (Muklason vd. 2013'ün ölçütü; 1 = tam eşit)
    kohort_degisim_katsayisi: float  # göreli (rapor)
    kohort_karesel: float  # S10
    kohortlar: tuple[KohortSatiri, ...]
    en_kotu_ogrenciler: tuple[tuple[str, float], ...]  # (öğrenci no, ceza)


def adalet_raporu(pr: ProblemOrnegi, analiz: OgrenciAnalizi, en_kotu_adet: int = 10) -> AdaletRaporu:
    cezalar = [(pr.ogrenciler[s].no, analiz.p[s]) for s in range(pr.S) if analiz.aktif[s]]
    degerler = sorted(x for _, x in cezalar)
    n = len(degerler)
    if n == 0:
        return AdaletRaporu(0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, (), ())
    medyan = degerler[n // 2] if n % 2 else (degerler[n // 2 - 1] + degerler[n // 2]) / 2
    ust = degerler[-max(1, n // 10):]
    bolum_kod = {b.id: b.kod for b in pr.veri.bolumler}
    kohortlar = tuple(
        KohortSatiri(bolum_kod.get(b, str(b)), sinif, boyut, ort)
        for (b, sinif), boyut, ort in zip(pr.kohortlar, analiz.kohort_boyut, analiz.kohort_ortalama, strict=True)
        if boyut > 0
    )
    en_kotuler = tuple(sorted(cezalar, key=lambda x: -x[1])[:en_kotu_adet])
    return AdaletRaporu(
        ogrenci_sayisi=n,
        ortalama=sum(degerler) / n,
        medyan=medyan,
        en_kotu_yuzde10_ortalamasi=sum(ust) / len(ust),
        en_kotu=degerler[-1],
        cezasiz_oran=sum(1 for x in degerler if x <= 1e-12) / n,
        degisim_katsayisi=analiz.ogrenci_cv(),
        karesel_ortalama=analiz.ogrenci_karesel(),
        gini=gini(degerler),
        jain=jain_indeksi(degerler),
        kohort_degisim_katsayisi=analiz.kohort_cv(),
        kohort_karesel=analiz.kohort_karesel(),
        kohortlar=kohortlar,
        en_kotu_ogrenciler=en_kotuler,
    )
