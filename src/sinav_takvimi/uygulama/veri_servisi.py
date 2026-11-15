"""Veri işlemleri servisi: arayüz ve komut satırı veritabanına bu sınıf üzerinden erişir."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sinav_takvimi.altyapi import csv_aktarim, excel_aktarim
from sinav_takvimi.altyapi.repolar import VeriDeposu
from sinav_takvimi.araclar.sentetik_veri import SentetikAyarlar, sentetik_veri_uret
from sinav_takvimi.domain.modeller import SinavDonemi, VeriSeti
from sinav_takvimi.domain.veri_kontrol import veri_kontrol


class VeriHatasi(Exception):
    """Girdi verisi tutarsız; `hatalar` listesi kullanıcıya gösterilebilir."""

    def __init__(self, hatalar: list[str]) -> None:
        super().__init__(f"{len(hatalar)} veri hatası: " + "; ".join(hatalar[:5]))
        self.hatalar = hatalar


class VeriServisi:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.depo = VeriDeposu(conn)

    def _kontrol_et_ve_kaydet(self, veri: VeriSeti) -> list[str]:
        hatalar, uyarilar = veri_kontrol(veri)
        if hatalar:
            raise VeriHatasi(hatalar)
        try:
            self.depo.degistir(veri)  # tek işlem: hata olursa eski veri korunur
        except sqlite3.IntegrityError as hata:
            raise VeriHatasi([f"Veritabanı kuralı ihlal edildi: {hata}"]) from hata
        return uyarilar

    def sentetik_uret(self, ayar: SentetikAyarlar | None = None) -> tuple[VeriSeti, list[str]]:
        """Sentetik veri üretir ve veritabanındaki her şeyin yerine kaydeder. (veri, uyarılar) döndürür."""
        veri = sentetik_veri_uret(ayar)
        return veri, self._kontrol_et_ve_kaydet(veri)

    def csv_den_yukle(self, klasor: str | Path) -> tuple[VeriSeti, list[str]]:
        try:
            veri = csv_aktarim.ice_aktar(klasor)
        except FileNotFoundError as hata:
            raise VeriHatasi([f"Dosya bulunamadı: {hata.filename}"]) from hata
        except ValueError as hata:  # csv_aktarim satır/dosya bilgisiyle ValueError fırlatır
            raise VeriHatasi([str(hata)]) from hata
        return veri, self._kontrol_et_ve_kaydet(veri)

    def csv_ye_aktar(self, donem_id: int, klasor: str | Path) -> None:
        csv_aktarim.disa_aktar(self.depo.yukle(donem_id), klasor)

    def excel_den_yukle(self, dosya: str | Path) -> tuple[VeriSeti, list[str]]:
        """Tek .xlsx dosyası (her tablo ayrı sayfa, sütunlar CSV ile aynı)."""
        try:
            veri = excel_aktarim.ice_aktar(dosya)
        except FileNotFoundError as hata:
            raise VeriHatasi([f"Dosya bulunamadı: {hata.filename}"]) from hata
        except (ValueError, KeyError) as hata:  # openpyxl bozuk/uyumsuz dosyada da ValueError/KeyError verir
            raise VeriHatasi([str(hata)]) from hata
        return veri, self._kontrol_et_ve_kaydet(veri)

    def excel_e_aktar(self, donem_id: int, dosya: str | Path) -> None:
        excel_aktarim.disa_aktar(self.depo.yukle(donem_id), dosya)

    def donemler(self) -> list[SinavDonemi]:
        return self.depo.donemler.hepsi()

    def yukle(self, donem_id: int) -> VeriSeti:
        return self.depo.yukle(donem_id)

    def ozet(self, donem_id: int) -> dict[str, int]:
        return self.yukle(donem_id).ozet()
