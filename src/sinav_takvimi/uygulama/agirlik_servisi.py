"""Kriter ağırlıkları servisi: AHP anket yanıtlarını kaydeder, doğrular ve birleşik ağırlıkları hesaplar.

Anket dosyası (TOML) biçimi — `config/ahp_anket_sablonu.toml`:
    [katilimci]
    ad = "…"
    rol = "ogrenci"            # ogrenci / ogretim_elemani / idari
    [ust]                      # gruplar arası: "a/b" = a, b'ye göre ne kadar önemli (1/9 … 9)
    "ogrenci_konforu/adalet" = 3
    [ogrenci_konforu]
    "S1/S2" = 2
    …
"""

from __future__ import annotations

import itertools
import sqlite3
import tomllib
from datetime import datetime
from fractions import Fraction
from pathlib import Path

from sinav_takvimi.altyapi.repolar import AhpKatilimci, AhpRepo
from sinav_takvimi.domain.ahp import GRUPLAR, HIYERARSI, UST, AhpSonucu, ahp_hesapla, rol_bazli_hesapla

ROLLER = ("ogrenci", "ogretim_elemani", "idari")
MATRISLER: dict[str, tuple[str, ...]] = {UST: GRUPLAR, **HIYERARSI}


class AnketHatasi(ValueError):
    pass


def _deger(metin: object) -> float:
    """3, 0.25, "1/3" gibi değerleri sayıya çevirir ve Saaty ölçeğinde (1/9 … 9) olduğunu denetler."""
    try:
        d = float(Fraction(str(metin)))
    except (ValueError, ZeroDivisionError) as hata:
        raise AnketHatasi(f"Geçersiz yargı değeri: {metin!r}") from hata
    if not (1 / 9 - 1e-9 <= d <= 9 + 1e-9):
        raise AnketHatasi(f"Yargı 1/9 ile 9 arasında olmalı (Saaty ölçeği): {metin!r}")
    return d


def yargilari_dogrula(yargilar: dict[str, dict[tuple[str, str], float]]) -> None:
    for matris, ciftler in yargilar.items():
        if matris not in MATRISLER:
            raise AnketHatasi(f"Bilinmeyen matris: {matris} (geçerli: {', '.join(MATRISLER)})")
        kriterler = set(MATRISLER[matris])
        for a, b in ciftler:
            if a not in kriterler or b not in kriterler or a == b:
                raise AnketHatasi(f"[{matris}] geçersiz karşılaştırma: {a} / {b}")
            if (b, a) in ciftler:
                raise AnketHatasi(f"[{matris}] {a}/{b} ve {b}/{a} birlikte verilmiş; yalnızca biri yeterli")


def anket_dosyasi_oku(yol: str | Path) -> AhpKatilimci:
    with Path(yol).open("rb") as f:
        veri = tomllib.load(f)
    k = veri.get("katilimci", {})
    if k.get("rol") not in ROLLER:
        raise AnketHatasi(f"rol şunlardan biri olmalı: {', '.join(ROLLER)}")
    yargilar: dict[str, dict[tuple[str, str], float]] = {}
    for matris in MATRISLER:
        for anahtar, deger in veri.get(matris, {}).items():
            if "/" not in anahtar:
                raise AnketHatasi(f"[{matris}] anahtar 'a/b' biçiminde olmalı: {anahtar}")
            a, b = (x.strip() for x in anahtar.split("/", 1))
            yargilar.setdefault(matris, {})[(a, b)] = _deger(deger)
    fazla = set(veri) - {"katilimci", *MATRISLER}
    if fazla:
        raise AnketHatasi(f"Bilinmeyen bölüm(ler): {sorted(fazla)}")
    yargilari_dogrula(yargilar)
    return AhpKatilimci(str(k.get("ad", "isimsiz")), k["rol"], datetime.now().isoformat(timespec="seconds"), yargilar)


def sablon_metni() -> str:
    """Tüm karşılaştırmaları 1 (eşit önem) olan boş bir anket şablonu üretir."""
    satirlar = [
        "# AHP anket şablonu (swing ağırlıklandırma). Her satır \"a/b\" şu soruyu yanıtlar:",
        "# 'Referans takvimdeki a sorununu ideale indirmek, b sorununu ideale indirmekten ne kadar önemli?'",
        "# 1 eşit · 3 biraz daha · 5 çok daha · 7 çok çok daha · 9 kesinlikle daha önemli",
        "# Ters yön için kesri TIRNAK içinde yazın: \"1/3\", \"1/5\" … Değiştirmediğiniz satırlar 'eşit önem' sayılır.",
        "# Kriterler: S1 arka arkaya sınav · S2 aynı gün sınav · S3 zor sınavlar arası hazırlık süresi",
        "#            S7 günde 3+ sınav · S9 öğrenciler arası adalet · S10 bölüm-sınıf grupları arası adalet",
        "#            S4 büyük sınavlar dönem başında · S5 sınavın az salona bölünmesi · S6 boş koltuk",
        "#            S11 hocanın kendi sınavında bulunması",
        "",
        "[katilimci]",
        'ad = "Adınız"',
        'rol = "ogrenci"  # ogrenci / ogretim_elemani / idari',
    ]
    for matris, kriterler in MATRISLER.items():
        satirlar += ["", f"[{matris}]"]
        satirlar += [f'"{a}/{b}" = 1' for a, b in itertools.combinations(kriterler, 2)]
    return "\n".join(satirlar) + "\n"


class AgirlikServisi:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = AhpRepo(conn)

    def katilimci_ekle(self, k: AhpKatilimci) -> int:
        yargilari_dogrula(k.yargilar)
        with self.conn:
            return self.repo.ekle(k)

    def katilimcilar(self) -> list[AhpKatilimci]:
        return self.repo.hepsi()

    def katilimci_sil(self, katilimci_id: int) -> None:
        with self.conn:
            self.repo.sil(katilimci_id)

    @staticmethod
    def tutarlilik(k: AhpKatilimci) -> dict[str, float]:
        """Katılımcının her matrisi için tutarlılık oranı (CR). CR > 0.10 ise yargılar gözden geçirilmeli (Saaty)."""
        sonuc = ahp_hesapla([k.yargilar])
        return {UST: sonuc.ust.cr, **{g: m.cr for g, m in sonuc.gruplar.items()}}

    def hesapla(self, rol: str | None = None) -> AhpSonucu:
        """Birleşik ağırlıklar: rol içinde AIJ, roller arasında eşit paylı AIP. `rol` verilirse sadece o rol.
        Katılımcı yoksa eşit ağırlık."""
        katilimcilar = [x for x in self.repo.hepsi() if rol is None or x.rol == rol]
        rol_bazli: dict[str, list[dict[str, dict[tuple[str, str], float]]]] = {}
        for x in katilimcilar:
            rol_bazli.setdefault(x.rol, []).append(x.yargilar)
        return rol_bazli_hesapla(rol_bazli)
