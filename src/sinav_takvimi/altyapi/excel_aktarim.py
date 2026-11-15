"""VeriSeti ↔ tek Excel (.xlsx) dosyası: her tablo ayrı bir sayfa (sayfa adı = CSV dosya adı, uzantısız).

Sütunlar ve tip kuralları CSV ile birebir aynıdır (`csv_aktarim.tablolardan_oku` / `tablolara_yaz`); böylece bir
CSV klasörü ile bir Excel dosyası aynı veriyi taşır. Kütüphane: openpyxl.

Excel hücreleri metin olmayabilir (sayı, tarih, saat, mantıksal). Okurken hepsi CSV'deki metin biçimine çevrilir:
5.0 → "5", tarih → "2027-01-04", saat → "09:00", DOĞRU/YANLIŞ → "1"/"0", boş → "".
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.exceptions import InvalidFileException

from sinav_takvimi.altyapi.csv_aktarim import tablolara_yaz, tablolardan_oku
from sinav_takvimi.domain.modeller import VeriSeti


def _sayfa_adi(dosya: str) -> str:
    return dosya.removesuffix(".csv")


def _metin(deger: Any) -> str:
    """Excel hücre değerini CSV metnine çevirir."""
    if deger is None:
        return ""
    if isinstance(deger, bool):
        return "1" if deger else "0"
    if isinstance(deger, float) and deger.is_integer():
        return str(int(deger))
    if isinstance(deger, datetime):
        return deger.date().isoformat() if deger.time() == time(0) else deger.strftime("%H:%M")
    if isinstance(deger, date):
        return deger.isoformat()
    if isinstance(deger, time):
        return deger.strftime("%H:%M")
    return str(deger).strip()


def disa_aktar(veri: VeriSeti, dosya: str | Path) -> None:
    """Her tabloyu ayrı sayfaya yazar. Metin alanlar (tarih, saat, öğrenci no) Excel'de metin olarak kalır."""
    kitap = Workbook()
    varsayilan = kitap.active
    if varsayilan is not None:
        kitap.remove(varsayilan)

    def yaz(ad: str, basliklar: list[str], satirlar: list[list[Any]]) -> None:
        sayfa = kitap.create_sheet(_sayfa_adi(ad))
        sayfa.append(basliklar)
        for hucre in sayfa[1]:
            hucre.font = Font(bold=True)
        for satir in satirlar:
            sayfa.append(satir)
        sayfa.freeze_panes = "A2"  # başlık satırı kaydırırken görünsün
        for i, baslik in enumerate(basliklar, start=1):
            genislik = max([len(str(baslik))] + [len(str(s[i - 1])) for s in satirlar[:200]])
            sayfa.column_dimensions[sayfa.cell(1, i).column_letter].width = min(50, genislik + 2)

    tablolara_yaz(veri, yaz)
    Path(dosya).parent.mkdir(parents=True, exist_ok=True)
    kitap.save(dosya)


def ice_aktar(dosya: str | Path) -> VeriSeti:
    """Excel dosyasından VeriSeti oluşturur. Eksik sayfa ya da hatalı hücre, sayfa ve satır numarasıyla bildirilir."""
    try:
        kitap = load_workbook(dosya, read_only=True, data_only=True)  # data_only: formül yerine hesaplanmış değer
    except (BadZipFile, InvalidFileException) as hata:  # .xlsx aslında bir zip arşividir
        raise ValueError(f"{Path(dosya).name} geçerli bir Excel (.xlsx) dosyası değil") from hata
    try:
        def oku(ad: str) -> list[dict[str, str]]:
            sayfa_adi = _sayfa_adi(ad)
            if sayfa_adi not in kitap.sheetnames:
                raise ValueError(f"Excel dosyasında '{sayfa_adi}' sayfası yok")
            satirlar = list(kitap[sayfa_adi].iter_rows(values_only=True))
            if not satirlar:
                return []
            basliklar = [_metin(b) for b in satirlar[0]]
            sonuc = []
            for satir in satirlar[1:]:
                if all(h is None or _metin(h) == "" for h in satir):
                    continue  # tamamen boş satırlar (Excel'de sık görülür) atlanır
                sonuc.append({b: _metin(h) for b, h in zip(basliklar, satir, strict=False) if b})
            return sonuc

        return tablolardan_oku(oku)
    finally:
        kitap.close()
