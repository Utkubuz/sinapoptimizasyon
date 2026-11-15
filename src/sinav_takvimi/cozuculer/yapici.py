"""Yapıcı çözücü: DSatur tabanlı, "en zor sınav önce" (Brélaz 1979; Carter, Laporte & Lee 1996).

Akış:
  1. Henüz yerleşmemiş sınavlar arasından en zoru seçilir (`siradaki_sinav`):
       a) doygunluk (elenen oturum sayısı): sınavın H8/H9 alan kısıtları yüzünden zaten kullanamadığı oturumlar ile
          yerleşmiş çakışan komşularının kullandığı oturumların birleşimi en büyük olan (yani kalan çatışmasız uygun
          oturum sayısı en az olan; tüm oturumlar uygunsa doğrudan "farklı oturumdaki komşu sayısı"na eşittir),
       b) eşitlikte çakışan komşu sayısı (`len(pr.komsular[e])`) en çok olan,
       c) sonra öğrenci sayısı (`pr.ogrenci_sayisi[e]`) en kalabalık olan,
       d) sonra küçük indeks (tekrarlanabilirlik).
  2. Sınavın uygun oturumlarının her biri `Degerlendirici` ile denenir (hamle uygula → ceza hesapla → geri al) ve
     `Ceza` nesneleri sözlükbilimsel karşılaştırılır: sert ihlali ARTIRAN oturum asla seçilmez; geri
     kalanlar arasında en az yumuşak cezalı olan alınır, eşitlikte küçük dilim indeksi (deterministik).
  3. Hiçbir oturum sert ihlalsiz yerleştirmeye izin vermiyorsa sınav YERLEŞTİRİLMEZ. Sessizce geçilmez: sonuçta
     `Yerlesmeyen` kaydı (neden ve en az ihlalli oturumun ihlalleriyle) döner.

Seçim sırasında referans takvim henüz yoktur (yapıcının kendisi referans olacaktır): Degerlendirici'ye
referans verilmediyse yumuşak ceza = AHP ağırlığı × doğal değer olarak karşılaştırılır.

Bu modül sadece domain'e bağımlıdır; veritabanını, dosyayı ya da arayüzü bilmez.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field

from sinav_takvimi.domain.artimli_degerlendirici import ArtimliDegerlendirici
from sinav_takvimi.domain.ceza import TOLERANS, Ceza
from sinav_takvimi.domain.cozum import Cozum
from sinav_takvimi.domain.degerlendirici import Degerlendirici
from sinav_takvimi.domain.problem import ProblemOrnegi


@dataclass(frozen=True, slots=True)
class Yerlesmeyen:
    """Sert ihlal olmadan hiçbir oturuma yerleştirilemeyen sınav (açıkça raporlanır)."""

    e: int
    ders_kod: str
    ogrenci: int
    neden: str
    ihlaller: dict[str, float] = field(default_factory=dict)  # en az ihlalli oturumdaki sert ihlaller (kod → miktar)


@dataclass(slots=True)
class YapiciSonuc:
    cozum: Cozum
    yerlesmeyenler: list[Yerlesmeyen] = field(default_factory=list)
    gecmis: list[list[float]] = field(default_factory=list)  # her yerleştirmeden sonra [yerleşen sınav, sert, yumuşak]

    @property
    def tam(self) -> bool:
        """Her sınav yerleşti mi? (Referans takvim olabilmenin ön koşulu.)"""
        return not self.yerlesmeyenler


def doygunluk(pr: ProblemOrnegi, e: int, komsu_oturumlari: Collection[int]) -> int:
    """Sınav `e` için elenmiş oturum sayısı (Carter vd. 1996 'Saturation Degree' karşılığı):
    toplam oturum − kalan uygun ve komşusuz oturum. Bütün oturumlar başlangıçta uygunsa `len(komsu_oturumlari)` olur;
    sabit/yasak (H9) veya süre (H8) daraltması varsa o daraltma da doygunluğa yansır."""
    if pr.uygun_dilimi_yok[e]:
        return pr.P
    kalan_uygun = sum(1 for p in pr.uygun_dilimler[e] if p not in komsu_oturumlari)
    return pr.P - kalan_uygun


def siradaki_sinav(pr: ProblemOrnegi, adaylar: Collection[int], komsu_oturumlari: Sequence[Collection[int]]) -> int:
    """DSatur sırası: (doygunluk ↓, çakışan komşu sayısı ↓, öğrenci sayısı ↓, indeks ↑)."""
    return min(
        adaylar,
        key=lambda e: (-doygunluk(pr, e, komsu_oturumlari[e]), -len(pr.komsular[e]), -pr.ogrenci_sayisi[e], e),
    )


def yapici_coz(deg: Degerlendirici) -> YapiciSonuc:
    pr = deg.problem
    cozum = Cozum(pr)
    artimli = ArtimliDegerlendirici(deg, cozum)
    kalan = set(range(pr.E))
    komsu_oturumlari: list[set[int]] = [set() for _ in range(pr.E)]
    sert_tekli = [k for k in deg.tekli if k.sert]
    sert_cift = [k for k in deg.cift if k.sert]
    yerlesmeyen_e: list[int] = []
    simdiki = artimli.ceza()  # boş takvim: her sınav yerleşmemiş sayılır (Y0)
    gecmis: list[list[float]] = []
    yerlesen = 0

    while kalan:
        e = siradaki_sinav(pr, kalan, komsu_oturumlari)
        kalan.discard(e)
        # e yerleşirse Y0 (yerleşmemiş sınav) cezası öğrenci sayısı kadar düşer; bundan fazla sert ceza = yeni ihlal
        beklenen_sert = simdiki.sert - pr.ogrenci_sayisi[e]
        en_iyi: tuple[Ceza, int] | None = None
        for p in pr.uygun_dilimler[e]:
            # Hızlı ön eleme: tekli ve çift sert kısıtlar derslik dağıtmadan ve öğrencileri taramadan elenir
            if any(k.ihlal(pr, e, p) > TOLERANS for k in sert_tekli):
                continue
            if any(
                (pf := cozum.dilim[f]) is not None and k.ihlal(pr, e, f, p, pf) > TOLERANS
                for f in pr.komsular[e]
                for k in sert_cift
            ):
                continue
            kayit = artimli.tasi({e: p})
            sonra = artimli.ceza()
            artimli.geri_al(kayit)
            if sonra.sert > beklenen_sert + TOLERANS:
                continue  # sert ihlal doğuran oturum (ör. H2/H7/H10/H11) seçilmez
            if en_iyi is None or sonra < en_iyi[0]:
                en_iyi = (sonra, p)
        if en_iyi is None:
            yerlesmeyen_e.append(e)
            continue
        _, p = en_iyi
        artimli.tasi({e: p})
        simdiki = artimli.ceza()
        yerlesen += 1
        for f in pr.komsular[e]:
            komsu_oturumlari[f].add(p)
        gecmis.append([float(yerlesen), simdiki.sert, simdiki.yumusak])

    yerlesmeyenler = [_yerlesmeyen_raporu(deg, cozum, e) for e in sorted(yerlesmeyen_e)]
    return YapiciSonuc(cozum, yerlesmeyenler, gecmis)


def _yerlesmeyen_raporu(deg: Degerlendirici, cozum: Cozum, e: int) -> Yerlesmeyen:
    """Sınavın neden yerleşemediğini bulur: her oturumda doğan sert ihlalleri hesaplar, en azını raporlar.
    Son takvim üzerinden hesaplanır (yani "diğer her şey yerleşmişken bile" yerleşemiyor demektir)."""
    pr = deg.problem
    d = pr.sinavlar[e]
    if pr.P == 0:
        return Yerlesmeyen(e, d.kod, pr.ogrenci_sayisi[e], "Dönemde hiç oturum yok")
    sert_kodlar = [k.kod for k in deg.kisitlar if k.sert]
    once = deg.ihlaller(cozum)
    aday_dilimler = pr.uygun_dilimler[e] or range(pr.P)
    en_az: tuple[tuple[int, float, int], int, dict[str, float]] | None = None
    for p in aday_dilimler:
        geri = cozum.tasi({e: p})
        sonra = deg.ihlaller(cozum)
        cozum.geri_al(geri)
        ek = {k: sonra[k] - once[k] for k in sert_kodlar if sonra[k] - once[k] > TOLERANS}
        # Doğrudan çakışma (H1/H4) olmayan uygun oturum varsa önce onun neden reddedildiğini (H2/H7/H10/H11) raporla
        anahtar = (1 if ("H1" in ek or "H4" in ek) else 0, sum(ek.values()), p)
        if en_az is None or anahtar < en_az[0]:
            en_az = (anahtar, p, ek)
    assert en_az is not None
    _, p, ek = en_az
    ayrinti = ", ".join(f"{k} +{v:g}" for k, v in sorted(ek.items())) or "ihlal bulunamadı"
    if pr.uygun_dilimi_yok[e]:
        neden = f"Hiçbir oturum süre (H8) ve sabit/yasak (H9) kurallarına birlikte uygun değil ({ayrinti})"
    else:
        etiket = pr.dilimler[p].etiket
        neden = f"Hiçbir oturuma sert ihlalsiz yerleştirilemiyor; en yakın oturum {etiket}: {ayrinti}"
    return Yerlesmeyen(e, d.kod, pr.ogrenci_sayisi[e], neden, ek)


__all__ = ["Yerlesmeyen", "YapiciSonuc", "doygunluk", "siradaki_sinav", "yapici_coz"]
