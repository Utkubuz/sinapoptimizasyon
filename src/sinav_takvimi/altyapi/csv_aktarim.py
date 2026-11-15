"""VeriSeti ↔ CSV klasörü.

Türkçe Excel'in doğrudan açabilmesi için `;` ayraç ve UTF-8 BOM (`utf-8-sig`) kullanılır.
Her tablo ayrı bir dosyadır. Sütun adları dataclass alan adlarıyla aynıdır.

Okuma/yazma kuralları (tip dönüşümü, satır numaralı hata mesajları) kaynaktan bağımsızdır: `tablolardan_oku` ve
`tablolara_yaz` bir "tablo adı → satırlar" okuyucu/yazıcı fonksiyonu alır; Excel aktarımı (`excel_aktarim.py`) da
aynı fonksiyonları kullanır.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

from sinav_takvimi.domain.modeller import (
    Bolum,
    Ders,
    Derslik,
    Dilim,
    KurumPolitikasi,
    Ogrenci,
    OgrenciGereksinim,
    Personel,
    SinavDilimKurali,
    SinavDonemi,
    VeriSeti,
)

AYRAC = ";"
KODLAMA = "utf-8-sig"

# dosya adı → (sınıf, VeriSeti alanı)
TABLOLAR: dict[str, tuple[type, str]] = {
    "bolumler.csv": (Bolum, "bolumler"),
    "personel.csv": (Personel, "personeller"),
    "dersler.csv": (Ders, "dersler"),
    "ogrenciler.csv": (Ogrenci, "ogrenciler"),
    "gereksinimler.csv": (OgrenciGereksinim, "gereksinimler"),
    "derslikler.csv": (Derslik, "derslikler"),
    "dilimler.csv": (Dilim, "dilimler"),
    "dilim_kurallari.csv": (SinavDilimKurali, "dilim_kurallari"),
    "kurum_politikasi.csv": (KurumPolitikasi, "politikalar"),
}
CIFT_TABLOLAR: dict[str, tuple[str, tuple[str, str]]] = {
    "kayitlar.csv": ("kayitlar", ("ogrenci_id", "ders_id")),
    "personel_musait_degil.csv": ("personel_musait_degil", ("personel_id", "dilim_id")),
    "derslik_musait_degil.csv": ("derslik_musait_degil", ("derslik_id", "dilim_id")),
}


def _yaz(yol: Path, basliklar: list[str], satirlar: list[list[Any]]) -> None:
    with yol.open("w", newline="", encoding=KODLAMA) as f:
        w = csv.writer(f, delimiter=AYRAC)
        w.writerow(basliklar)
        w.writerows(satirlar)


def _oku(yol: Path) -> list[dict[str, str]]:
    with yol.open(newline="", encoding=KODLAMA) as f:
        return list(csv.DictReader(f, delimiter=AYRAC))


def _cevir(deger: str, tip: str) -> Any:
    """CSV metnini dataclass alanının tipine çevirir (tip, `from __future__ import annotations` yüzünden metindir)."""
    if "None" in tip and deger.strip() == "":
        return None
    temel = tip.replace("| None", "").strip()
    if temel == "int":
        return int(deger)
    if temel == "float":
        return float(deger.replace(",", "."))  # Türkçe Excel ondalık virgülü
    if temel == "bool":
        d = deger.strip().lower()
        if d in ("1", "true", "evet", "e"):
            return True
        if d in ("0", "false", "hayir", "hayır", "h", ""):
            return False
        raise ValueError(f"evet/hayır değeri bekleniyordu, '{deger}' geldi")
    return deger


def _bicim(deger: Any) -> Any:
    if deger is None:
        return ""
    if isinstance(deger, bool):
        return int(deger)
    return deger


Yazici = Callable[[str, list[str], list[list[Any]]], None]  # (dosya adı, başlıklar, satırlar)
Okuyucu = Callable[[str], list[dict[str, str]]]  # dosya adı → satırlar (her hücre metin)


def tablolara_yaz(veri: VeriSeti, yaz: Yazici) -> None:
    """VeriSeti'ni tablo tablo yazar (dosya adları: donem.csv, bolumler.csv, …)."""
    if veri.donem is not None:
        alanlar = [f.name for f in fields(SinavDonemi)]
        yaz("donem.csv", alanlar, [[_bicim(getattr(veri.donem, a)) for a in alanlar]])
    for dosya, (sinif, alan) in TABLOLAR.items():
        adlar = [f.name for f in fields(sinif)]
        yaz(dosya, adlar, [[_bicim(getattr(x, a)) for a in adlar] for x in getattr(veri, alan)])
    for dosya, (alan, basliklar) in CIFT_TABLOLAR.items():
        yaz(dosya, list(basliklar), [list(c) for c in sorted(getattr(veri, alan))])


def tablolardan_oku(oku: Okuyucu) -> VeriSeti:
    """Tablo tablo okuyup VeriSeti kurar. Hatalar tablo adı ve satır numarasıyla bildirilir."""
    veri = VeriSeti()

    def nesneler(sinif: type, dosya: str) -> list[Any]:
        tipler = {f.name: str(f.type) for f in fields(sinif)}
        sonuc = []
        for i, satir in enumerate(oku(dosya), start=2):
            try:
                sonuc.append(sinif(**{ad: _cevir(satir[ad], tip) for ad, tip in tipler.items()}))
            except (KeyError, ValueError) as hata:
                raise ValueError(f"{dosya} satır {i}: {hata}") from hata
        return sonuc

    donemler = nesneler(SinavDonemi, "donem.csv")
    if len(donemler) > 1:
        raise ValueError(f"donem.csv: tek bir sınav dönemi olmalı, {len(donemler)} satır var")
    veri.donem = donemler[0] if donemler else None
    for dosya, (sinif, alan) in TABLOLAR.items():
        setattr(veri, alan, nesneler(sinif, dosya))
    for dosya, (alan, (a, b)) in CIFT_TABLOLAR.items():
        ciftler = []
        for i, s in enumerate(oku(dosya), start=2):
            try:
                ciftler.append((int(s[a]), int(s[b])))
            except (KeyError, ValueError) as hata:
                raise ValueError(f"{dosya} satır {i}: {hata}") from hata
        # kayıtlar liste olarak tutulur ki tekrarlanan satırlar veri kontrolünde yakalanabilsin
        setattr(veri, alan, ciftler if alan == "kayitlar" else set(ciftler))
    return veri


def disa_aktar(veri: VeriSeti, klasor: str | Path) -> None:
    klasor = Path(klasor)
    klasor.mkdir(parents=True, exist_ok=True)
    tablolara_yaz(veri, lambda dosya, basliklar, satirlar: _yaz(klasor / dosya, basliklar, satirlar))


def ice_aktar(klasor: str | Path) -> VeriSeti:
    """Bir klasördeki CSV dosyalarından VeriSeti oluşturur. Eksik dosya hata verir (dosya adıyla birlikte)."""
    klasor = Path(klasor)
    return tablolardan_oku(lambda dosya: _oku(klasor / dosya))
