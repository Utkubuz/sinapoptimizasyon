"""Domain varlıkları.

`frozen=True` nesneyi değiştirilemez yapar,
`slots=True` bellek kullanımını azaltır. Alan adları veritabanı sütun adlarıyla aynıdır; repository'ler ve
CSV aktarımı bu sayede satırları doğrudan nesneye çevirebilir.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

UNVANLAR: tuple[str, ...] = ("Prof. Dr.", "Doç. Dr.", "Dr. Öğr. Üyesi", "Arş. Gör.")
OGRETIM_UYESI_UNVANLARI: frozenset[str] = frozenset({"Prof. Dr.", "Doç. Dr.", "Dr. Öğr. Üyesi"})

UNVAN_KOTALARI: dict[str, float] = {
    "Prof. Dr.": 0.5,
    "Doç. Dr.": 0.7,
    "Dr. Öğr. Üyesi": 0.8,
    "Arş. Gör.": 1.0,
}

# Sınav türü → kullanılabilecek derslik türleri (H6)
UYGUN_DERSLIK_TURLERI: dict[str, frozenset[str]] = {
    "yazili": frozenset({"normal", "amfi"}),
    "bilgisayar": frozenset({"bilgisayar"}),
}


DERSLIK_TURLERI: frozenset[str] = frozenset({"normal", "amfi", "bilgisayar", "ozel"})
OZEL_DERSLIK_TURU = "ozel"  # sadece ayrı salon öğrencileri; her sınav türüne uygun (dizüstü/kâğıt verilir)
DONEM_TURLERI: frozenset[str] = frozenset({"vize", "final", "butunleme"})
KURAL_TURLERI: frozenset[str] = frozenset({"zorunlu", "yasak"})

# Kurum politikası anahtarları → (alt sınır, üst sınır, açıklama). Değerler kodda değil, veride.
GEREKLI_POLITIKALAR: dict[str, tuple[float, float, str]] = {
    "yedek_orani": (0.0, 1.0, "Dilimdeki gözetmen ihtiyacının bu oranı kadar yedek gözetmen (yukarı yuvarlanır)"),
    "yedek_yuk_katsayisi": (0.0, 1.0, "Yedek görevin, gözetmen yük hesabındaki ağırlığı"),
}

# İsteğe bağlı politikalar. Tanımlı değilse ilgili kural uygulanmaz veya nötr varsayılan kullanılır.
VARSAYILAN_ARDISIK_BOSLUK_DK = 60.0  # aynı gün iki ardışık oturum arası dinlenme ≤ 60 dk ise arka arkaya (S1)
ISTEGE_BAGLI_POLITIKALAR: dict[str, tuple[float, float, str]] = {
    "gunluk_sinav_ust_siniri": (1.0, 10.0, "Öğrencinin bir günde girebileceği en fazla sınav (H11, sert)"),
    "gunluk_sinir_ortak_ders_haric": (0.0, 1.0, "1: fakülte ortak dersleri günlük sınıra sayılmaz"),
    "gunluk_sinir_alttan_haric": (0.0, 1.0, "1: öğrencinin kendi sınıfından alt sınıf dersleri sınıra sayılmaz"),
    "ardisik_bosluk_dk": (0.0, 240.0, "Aynı gün iki ardışık oturum arası dinlenme bu dakikayı aşmıyorsa S1 sayılır"),
}
TUM_POLITIKALAR = {**GEREKLI_POLITIKALAR, **ISTEGE_BAGLI_POLITIKALAR}


def gereken_sure(sinav_suresi_dk: int, ek_sure_orani: float) -> int:
    """Ek süreli bir öğrencinin ihtiyaç duyduğu süre, dakika olarak YUKARI yuvarlanır (öğrenci aleyhine yuvarlanmaz).

    90 dk × 1.33 = 119.7 → 120 dk. Kayan nokta hatası (ör. 119.99999) yüzünden fazladan 1 dk eklenmemesi için
    küçük bir tolerans çıkarılır. H8 kısıtı ve veri kontrolü bu fonksiyonu kullanır.
    """
    return math.ceil(sinav_suresi_dk * (1 + ek_sure_orani) - 1e-9)


@dataclass(frozen=True, slots=True)
class Bolum:
    id: int
    kod: str
    ad: str


@dataclass(frozen=True, slots=True)
class SinavDonemi:
    id: int
    ad: str
    tur: str  # vize / final / butunleme
    baslangic: str
    bitis: str


@dataclass(frozen=True, slots=True)
class Personel:
    id: int
    ad: str
    unvan: str
    bolum_id: int
    kota_carpani: float
    gunluk_max: int

    @property
    def tam_ad(self) -> str:
        return f"{self.unvan} {self.ad}"

    @property
    def ogretim_uyesi(self) -> bool:
        return self.unvan in OGRETIM_UYESI_UNVANLARI


@dataclass(frozen=True, slots=True)
class Ders:
    id: int
    kod: str
    ad: str
    bolum_id: int | None  # None: fakülte ortak dersi
    sinif: int
    zorluk: int
    sinav_turu: str
    sinav_suresi_dk: int
    hoca_id: int
    asistan_id: int | None


@dataclass(frozen=True, slots=True)
class Ogrenci:
    id: int
    no: str
    ad: str
    bolum_id: int
    sinif: int


@dataclass(frozen=True, slots=True)
class OgrenciGereksinim:
    ogrenci_id: int
    erisilebilir_salon: bool
    ayri_salon: bool
    ek_sure_orani: float


@dataclass(frozen=True, slots=True)
class Derslik:
    id: int
    kod: str
    kapasite: int
    sinav_kapasitesi: int
    tur: str
    erisilebilir: bool
    gozetmen_sayisi: int  # salon tam doluyken gereken gözetmen (kurum politikası, veri)


@dataclass(frozen=True, slots=True)
class Dilim:
    id: int
    donem_id: int
    gun: int
    tarih: str
    baslangic: str
    sira: int
    sure_dk: int

    @property
    def etiket(self) -> str:
        return f"{self.tarih} {self.baslangic}"


@dataclass(frozen=True, slots=True)
class KurumPolitikasi:
    anahtar: str
    deger: float
    aciklama: str
    kaynak: str


@dataclass(frozen=True, slots=True)
class SinavDilimKurali:
    ders_id: int
    dilim_id: int
    tur: str  # zorunlu / yasak
    aciklama: str | None


@dataclass(slots=True)
class VeriSeti:
    """Bir sınav döneminin tüm girdi verisi. Veritabanı, CSV ve sentetik üretici bu nesneyi alıp verir."""

    donem: SinavDonemi | None = None
    bolumler: list[Bolum] = field(default_factory=list)
    personeller: list[Personel] = field(default_factory=list)
    dersler: list[Ders] = field(default_factory=list)
    ogrenciler: list[Ogrenci] = field(default_factory=list)
    gereksinimler: list[OgrenciGereksinim] = field(default_factory=list)
    kayitlar: list[tuple[int, int]] = field(default_factory=list)  # (ogrenci_id, ders_id)
    derslikler: list[Derslik] = field(default_factory=list)
    dilimler: list[Dilim] = field(default_factory=list)
    personel_musait_degil: set[tuple[int, int]] = field(default_factory=set)  # (personel_id, dilim_id)
    derslik_musait_degil: set[tuple[int, int]] = field(default_factory=set)  # (derslik_id, dilim_id)
    dilim_kurallari: list[SinavDilimKurali] = field(default_factory=list)
    politikalar: list[KurumPolitikasi] = field(default_factory=list)

    def politika(self, anahtar: str, varsayilan: float | None = None) -> float:
        for p in self.politikalar:
            if p.anahtar == anahtar:
                return p.deger
        if varsayilan is not None:
            return varsayilan
        raise KeyError(f"Kurum politikası tanımlı değil: {anahtar}")

    def politika_var_mi(self, anahtar: str) -> bool:
        return any(p.anahtar == anahtar for p in self.politikalar)

    def ozet(self) -> dict[str, int]:
        return {
            "Bölüm": len(self.bolumler),
            "Ders": len(self.dersler),
            "Öğrenci": len(self.ogrenciler),
            "Özel gereksinimli öğrenci": len(self.gereksinimler),
            "Kayıt": len(self.kayitlar),
            "Personel": len(self.personeller),
            "Derslik": len(self.derslikler),
            "Dilim (oturum)": len(self.dilimler),
            "Personel müsait değil": len(self.personel_musait_degil),
            "Derslik müsait değil": len(self.derslik_musait_degil),
            "Sabit/yasak kural": len(self.dilim_kurallari),
            "Kurum politikası": len(self.politikalar),
        }
