"""Analitik Hiyerarşi Süreci (AHP, Saaty 1980): paydaşların ikili karşılaştırmalarından kriter ağırlıkları.

Bir karşılaştırma matrisinde a[i][j] = "i kriteri j'ye göre ne kadar önemli?" (Saaty ölçeği 1/9 … 9) ve
a[j][i] = 1 / a[i][j]. Ağırlıklar matrisin baş özvektörüdür (kuvvet yöntemiyle bulunur). Tutarlılık:
    CI = (λ_max − n) / (n − 1),   CR = CI / RI(n),   CR ≤ 0.10 ise yargılar kabul edilebilir tutarlıdır (Saaty).
Birden fazla katılımcı: AYNI ROLDEKİLER (öğrenci / öğretim elemanı / idari) ortak bir görüş oluşturur:
yargılarının elemanter geometrik ortalaması alınır (AIJ; Forman & Peniwati 1998; geometrik ortalama karşılıklılığı
koruyan tek birleştirmedir). FARKLI ROLLER farklı amaçlara sahip paydaşlardır: her rolün öncelikleri ayrı hesaplanır ve
roller EŞİT PAYLA ortalanır (AIP; Saaty'nin bireysel değerlendirme yapan gruplar için önerisi). Böylece kalabalık bir
rol (ör. 50 öğrenci) diğerlerini (3 hoca) bastıramaz; 9 ile 1/9'un 1'e "ortalanması" gibi görüş kayıpları da rol
sınırını aşmaz.

Hiyerarşi:
    Takvim kalitesi
    ├── ogrenci_konforu    : S1 arka arkaya · S2 aynı gün · S3 hazırlık süresi · S7 günde 3+
    ├── adalet             : S9 öğrenciler arası · S10 kohortlar arası
    └── kurum_verimliligi  : S4 büyük sınavlar erken · S5 bölünme · S6 israf · S11 hocası olmayan sınav
Hiç anket yoksa bütün yargılar 1'dir ("eşit önem"): bu keyfi bir seçim değil, AHP'nin nötr noktasıdır.

Swing ağırlıklandırma: kriterler referans takvime göre ölçeklendiği için anket sorusu şudur: "Referans takvimdeki
a kriterini ideale (0'a) indirmek, b kriterini indirmekten ne kadar önemli?" Böylece ağırlık sadece önem anlamı taşır.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

UST = "ust"
HIYERARSI: dict[str, tuple[str, ...]] = {
    "ogrenci_konforu": ("S1", "S2", "S3", "S7"),
    "adalet": ("S9", "S10"),
    "kurum_verimliligi": ("S4", "S5", "S6", "S11"),
}
GRUPLAR: tuple[str, ...] = tuple(HIYERARSI)
GRUP_ADLARI = {"ogrenci_konforu": "Öğrenci konforu", "adalet": "Adalet", "kurum_verimliligi": "Kurum verimliliği"}

# Saaty'nin rastgele tutarlılık indeksi (RI), n = 1 … 10 (Saaty 1980; yaygın kullanılan tablo)
RASTGELE_INDEKS = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}
CR_SINIRI = 0.10  # Saaty'nin önerdiği kabul sınırı

Matris = list[list[float]]
Yargilar = Mapping[tuple[str, str], float]  # (a, b) → a'nın b'ye göre önemi


@dataclass(frozen=True, slots=True)
class MatrisSonucu:
    kriterler: tuple[str, ...]
    agirliklar: tuple[float, ...]
    lambda_max: float
    ci: float
    cr: float

    @property
    def tutarli(self) -> bool:
        return self.cr <= CR_SINIRI + 1e-12


@dataclass(frozen=True, slots=True)
class AhpSonucu:
    ust: MatrisSonucu  # grupların ağırlıkları
    gruplar: dict[str, MatrisSonucu]  # her grubun içindeki yerel ağırlıklar
    katilimci_sayisi: int = 0
    kuresel: dict[str, float] = field(default_factory=dict)  # kriter → küresel ağırlık (toplam 1)
    roller: dict[str, AhpSonucu] = field(default_factory=dict)  # rol bazlı birleştirmede her rolün sonucu

    @property
    def tutarli(self) -> bool:
        return self.ust.tutarli and all(m.tutarli for m in self.gruplar.values())

    def yerel(self, grup: str) -> dict[str, float]:
        m = self.gruplar[grup]
        return dict(zip(m.kriterler, m.agirliklar, strict=True))


def matris_kur(kriterler: Sequence[str], yargilar: Yargilar) -> Matris:
    """Yargılardan karşılıklı (reciprocal) matris kurar. Verilmeyen çift 1 (eşit önem) sayılır."""
    indeks = {k: i for i, k in enumerate(kriterler)}
    n = len(kriterler)
    a = [[1.0] * n for _ in range(n)]
    for (x, y), deger in yargilar.items():
        if x not in indeks or y not in indeks or x == y:
            raise ValueError(f"Geçersiz karşılaştırma: {x} – {y}")
        if deger <= 0:
            raise ValueError(f"Yargı pozitif olmalı: {x} – {y} = {deger}")
        i, j = indeks[x], indeks[y]
        a[i][j], a[j][i] = deger, 1 / deger
    return a


def matris_coz(kriterler: Sequence[str], a: Matris) -> MatrisSonucu:
    """Baş özvektör (kuvvet yöntemi) → ağırlıklar; λ_max, CI, CR."""
    n = len(kriterler)
    w = [1 / n] * n
    for _ in range(10_000):  # yakınsama genelde < 20 adımda olur
        aw = [sum(a[i][j] * w[j] for j in range(n)) for i in range(n)]
        toplam = sum(aw)
        yeni = [x / toplam for x in aw]
        if max(abs(x - y) for x, y in zip(yeni, w, strict=True)) < 1e-13:
            w = yeni
            break
        w = yeni
    aw = [sum(a[i][j] * w[j] for j in range(n)) for i in range(n)]
    lambda_max = sum(aw[i] / w[i] for i in range(n)) / n
    ci = (lambda_max - n) / (n - 1) if n > 2 else 0.0
    ri = RASTGELE_INDEKS.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0.0
    return MatrisSonucu(tuple(kriterler), tuple(w), lambda_max, max(ci, 0.0), max(cr, 0.0))


def geometrik_birlestir(matrisler: Sequence[Matris]) -> Matris:
    """Katılımcıların matrislerini elemanter geometrik ortalamayla birleştirir (AIJ)."""
    if not matrisler:
        raise ValueError("Birleştirilecek matris yok")
    n = len(matrisler[0])
    return [
        [math.exp(sum(math.log(m[i][j]) for m in matrisler) / len(matrisler)) for j in range(n)] for i in range(n)
    ]


def ahp_hesapla(katilimci_yargilari: Sequence[Mapping[str, Yargilar]]) -> AhpSonucu:
    """AIJ: katılımcıların yargılarını tek bir grup görüşünde birleştirir (aynı rol içinde kullanılır).

    Her katılımcı için {matris adı ("ust" ya da grup adı) → yargılar}. Katılımcı yoksa eşit ağırlık.
    """
    def birlesik(kriterler: Sequence[str], ad: str) -> MatrisSonucu:
        # Bu matrisi hiç doldurmamış katılımcı birleştirmeye katılmaz (yoksa görüşü "eşit önem" sayılıp ortalamayı
        # sulandırırdı). Doldurulmuş bir matristeki boş çiftler ise "eşit önem" (1) kabul edilir.
        matrisler = [matris_kur(kriterler, k[ad]) for k in katilimci_yargilari if k.get(ad)]
        return matris_coz(kriterler, geometrik_birlestir(matrisler or [matris_kur(kriterler, {})]))

    ust = birlesik(GRUPLAR, UST)
    gruplar = {g: birlesik(kriterler, g) for g, kriterler in HIYERARSI.items()}
    kuresel = {
        k: ust.agirliklar[i] * w
        for i, g in enumerate(GRUPLAR)
        for k, w in zip(gruplar[g].kriterler, gruplar[g].agirliklar, strict=True)
    }
    katilan = sum(1 for k in katilimci_yargilari if any(k.values()))
    return AhpSonucu(ust, gruplar, katilan, kuresel)


def _ortalama_matris_sonucu(sonuclar: Sequence[MatrisSonucu]) -> MatrisSonucu:
    """Rollerin öncelik vektörlerinin aritmetik ortalaması (AIP). CR: rollerin en kötüsü (temkinli rapor)."""
    n = len(sonuclar)
    agirliklar = [sum(s.agirliklar[i] for s in sonuclar) / n for i in range(len(sonuclar[0].agirliklar))]
    toplam = sum(agirliklar)
    return MatrisSonucu(
        sonuclar[0].kriterler,
        tuple(w / toplam for w in agirliklar),
        lambda_max=float("nan"),  # birleşik öncelikler bir matristen gelmez
        ci=max(s.ci for s in sonuclar),
        cr=max(s.cr for s in sonuclar),
    )


def rol_bazli_hesapla(rol_yargilari: Mapping[str, Sequence[Mapping[str, Yargilar]]]) -> AhpSonucu:
    """Rol içinde AIJ, roller arasında eşit paylı AIP. {rol → [katılımcı yargıları]}."""
    roller = {rol: ahp_hesapla(k) for rol, k in rol_yargilari.items() if k}
    if len(roller) <= 1:
        tek = next(iter(roller.values()), esit_agirliklar())
        return AhpSonucu(tek.ust, tek.gruplar, tek.katilimci_sayisi, tek.kuresel, roller)
    ust = _ortalama_matris_sonucu([r.ust for r in roller.values()])
    gruplar = {g: _ortalama_matris_sonucu([r.gruplar[g] for r in roller.values()]) for g in GRUPLAR}
    kuresel = {
        k: ust.agirliklar[i] * w
        for i, g in enumerate(GRUPLAR)
        for k, w in zip(gruplar[g].kriterler, gruplar[g].agirliklar, strict=True)
    }
    return AhpSonucu(ust, gruplar, sum(r.katilimci_sayisi for r in roller.values()), kuresel, roller)


def esit_agirliklar() -> AhpSonucu:
    return ahp_hesapla([])


# ---------------------------------------------------------------------------------------------
# Saklama biçimi: çalıştırma kaydı AHP sonucunu JSON taşır; domain veritabanı bilmez, sözlük üretir.
# ---------------------------------------------------------------------------------------------


def _matris_sozluge(m: MatrisSonucu) -> dict[str, Any]:
    # AIP ile birleştirilmiş matrislerde lambda_max yoktur (nan): JSON'da standart olmayan NaN yerine null yazılır.
    lam = None if math.isnan(m.lambda_max) else m.lambda_max
    return {"kriterler": list(m.kriterler), "agirliklar": list(m.agirliklar), "lambda_max": lam, "ci": m.ci, "cr": m.cr}


def _matris_sozlukten(d: Mapping[str, Any]) -> MatrisSonucu:
    lam = float("nan") if d["lambda_max"] is None else float(d["lambda_max"])
    return MatrisSonucu(tuple(d["kriterler"]), tuple(d["agirliklar"]), lam, float(d["ci"]), float(d["cr"]))


def ahp_sozluge(s: AhpSonucu) -> dict[str, Any]:
    """AhpSonucu → JSON'a yazılabilir sözlük (`ahp_sozlukten` ile birebir geri alınır)."""
    return {
        "ust": _matris_sozluge(s.ust),
        "gruplar": {g: _matris_sozluge(m) for g, m in s.gruplar.items()},
        "katilimci_sayisi": s.katilimci_sayisi,
        "kuresel": dict(s.kuresel),
        "roller": {rol: ahp_sozluge(r) for rol, r in s.roller.items()},
    }


def ahp_sozlukten(d: Mapping[str, Any]) -> AhpSonucu:
    return AhpSonucu(
        ust=_matris_sozlukten(d["ust"]),
        gruplar={g: _matris_sozlukten(m) for g, m in d["gruplar"].items()},
        katilimci_sayisi=int(d["katilimci_sayisi"]),
        kuresel={k: float(w) for k, w in d["kuresel"].items()},
        roller={rol: ahp_sozlukten(r) for rol, r in d.get("roller", {}).items()},
    )
