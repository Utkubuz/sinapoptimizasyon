"""Algoritma parametreleri ve gözetmen ağırlıkları (config/agirliklar.toml dosyasının bellekteki hâli).

Takvim kriterlerinin ağırlıkları burada DEĞİL: AHP anketinden gelir, anket yoksa eşittir.

Dosyayı okuma işi `altyapi/ayar_okuyucu.py`'dedir (domain dosya bilmez). Buradaki varsayılan değerler TOML ile aynı
tutulur; `tests/birim/test_ayarlar.py` ikisinin ayrışmasını yakalar.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class GozetmenAgirliklari:
    adalet: float = 1.0           # G4
    ders_personeli: float = 5.0   # G6
    farkli_bolum: float = 0.5     # G7
    ozel_salon_bolum: float = 20.0  # G7 (ayrı salonda)
    sorumlu: float = 30.0         # G8


@dataclass(slots=True)
class TavlamaAyarlari:
    sure_sn: float = 15.0                # çalışma süresi bütçesi (sn; ITC 2007 McCollum vd. 2010)
    orneklem_boyutu: int = 200           # T0/T_son kalibrasyonu için komşu örneklemi (Ben-Ameur 2004)
    baslangic_kabul_orani: float = 0.80  # χ0: başlangıç kötüleşen hamle kabul oranı (Ben-Ameur 2004)
    bitis_kabul_orani: float = 0.001     # χ_son: sonda en küçük pozitif farkın kabul oranı
    yeniden_isitma_orani: float = 0.25   # tıkanmada en iyi çözüme dönüp yeniden ısıtma eşiği (Thompson & Dowsland 1998)
    takas_olasiligi: float = 0.20        # ikili takas olasılığı; kalanı Kempe zinciri (McCollum vd. 2010)

    def __post_init__(self) -> None:
        if self.sure_sn <= 0:
            raise ValueError("Tavlama süre bütçesi pozitif olmalıdır.")
        if self.orneklem_boyutu < 1:
            raise ValueError("Örneklem boyutu en az 1 olmalıdır.")
        if not (0.0 < self.bitis_kabul_orani < self.baslangic_kabul_orani < 1.0):
            raise ValueError("Kabul oranları 0 < bitis_kabul_orani < baslangic_kabul_orani < 1 aralığında olmalıdır.")
        if not (0.0 <= self.takas_olasiligi <= 1.0):
            raise ValueError("Takas olasılığı 0 ile 1 arasında olmalıdır.")
        if not (0.0 <= self.yeniden_isitma_orani <= 1.0):
            raise ValueError("Yeniden ısıtma oranı 0 ile 1 arasında olmalıdır.")


@dataclass(slots=True)
class TabuAyarlari:
    sure_sn: float = 15.0              # çalışma süresi bütçesi (sn; ITC 2007)
    aday_sayisi: int = 40              # her adımda incelenen aday hamle sayısı (Di Gaspero & Schaerf 2001)
    tabu_alt_katsayi: float = 1.0      # τ_min = max(3, round(katsayı × √E)) (Taillard 1991; Di Gaspero & Schaerf 2001)
    tabu_ust_katsayi: float = 2.0      # τ_max = max(τ_min, round(katsayı × √E))
    takas_olasiligi: float = 0.20      # ikili takas olasılığı; kalanı Kempe zinciri
    cesitlendirme_orani: float = 0.25  # tıkanmada çeşitlendirme (rastgele Kempe sıçraması) eşiği

    def __post_init__(self) -> None:
        if self.sure_sn <= 0:
            raise ValueError("Tabu arama süre bütçesi pozitif olmalıdır.")
        if self.aday_sayisi < 1:
            raise ValueError("Aday sayısı en az 1 olmalıdır.")
        if self.tabu_alt_katsayi <= 0 or self.tabu_ust_katsayi < self.tabu_alt_katsayi:
            raise ValueError("Tabu katsayıları 0 < alt ≤ üst koşulunu sağlamalıdır.")
        if not (0.0 <= self.takas_olasiligi <= 1.0):
            raise ValueError("Takas olasılığı 0 ile 1 arasında olmalıdır.")
        if not (0.0 <= self.cesitlendirme_orani <= 1.0):
            raise ValueError("Çeşitlendirme oranı 0 ile 1 arasında olmalıdır.")


@dataclass(slots=True)
class Ayarlar:
    gozetmen: GozetmenAgirliklari = field(default_factory=GozetmenAgirliklari)
    tavlama: TavlamaAyarlari = field(default_factory=TavlamaAyarlari)
    tabu: TabuAyarlari = field(default_factory=TabuAyarlari)

    @classmethod
    def sozlukten(cls, veri: dict[str, Any]) -> Ayarlar:
        """TOML'dan gelen sözlükten oluşturur. Bilinmeyen bir anahtar TypeError verir (yazım hatası sessiz geçmesin)."""
        bilinen = {"gozetmen", "tavlama", "tabu"}
        if fazla := set(veri) - bilinen:
            raise TypeError(f"Bilinmeyen ayar bölümü: {sorted(fazla)}")
        return cls(
            gozetmen=GozetmenAgirliklari(**veri.get("gozetmen", {})),
            tavlama=TavlamaAyarlari(**veri.get("tavlama", {})),
            tabu=TabuAyarlari(**veri.get("tabu", {})),
        )

    def sozluge(self) -> dict[str, Any]:
        return asdict(self)
