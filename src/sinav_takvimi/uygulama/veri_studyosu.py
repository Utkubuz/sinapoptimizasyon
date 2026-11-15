"""Veri Stüdyosu servisi: masaüstü arayüzden hem tek tıkla dönem/fakülte kurma, hem elle varlık ekleme/silme/düzenleme,
hem de tekil veya toplu rastgele varlık (öğrenci, öğretim elemanı, ders, derslik) üretme işlemleri.

Katman kuralları: arayüz (`PySide6`) bu servisi çağırır; her değişiklik önce `veri_kontrol` ile doğrulanır, ardından
`VeriDeposu.degistir` üzerinden tek atomik SQLite işleminde (`with conn:`) kaydedilir. Hata varsa veritabanındaki eski
durum bozulmadan `VeriHatasi` fırlatılır.

Not: "Rastgele Doldur / Rastgele Ekle" üreticilerindeki oranlar (unvan dağılımı, derslik türü dağılımı, kapalı
oturum olasılığı vb.) yalnızca ÖRNEK VERİ VARSAYIMLARIDIR (`sentetik_veri.py` ile aynı statüde). Optimizasyon
modeline girmezler; gerçek kullanımda veri elle ya da CSV ile girilir.
"""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from sinav_takvimi.altyapi.db import anketleri_koruyarak_yenile
from sinav_takvimi.altyapi.repolar import VeriDeposu
from sinav_takvimi.araclar.sentetik_veri import (
    ADLAR,
    BOLUMLER,
    GEREKSINIM_PROFILLERI,
    GUNLUK_GOREV_VARSAYIMI,
    ORTAK_DERSLER,
    SALON_BASI_KOLTUK_VARSAYIMI,
    SECMELI_CIFTLER,
    SINAV_SURESI,
    SOYADLAR,
    ZORUNLU_DERSLER,
    SentetikAyarlar,
    dilimleri_uret,
    is_gunleri,
    kurum_politikalari,
)
from sinav_takvimi.domain.modeller import (
    UNVAN_KOTALARI,
    UNVANLAR,
    Bolum,
    Ders,
    Derslik,
    Ogrenci,
    OgrenciGereksinim,
    Personel,
    SinavDilimKurali,
    SinavDonemi,
    VeriSeti,
)
from sinav_takvimi.domain.veri_kontrol import veri_kontrol
from sinav_takvimi.uygulama.veri_servisi import VeriHatasi, VeriServisi

_EK_DERS_ADLARI: tuple[tuple[str, str], ...] = (
    ("Sayısal Analiz", "yazili"),
    ("İstatistik ve Veri Analizi", "yazili"),
    ("Bilişim Sistemleri", "bilgisayar"),
    ("İş Sağlığı ve Güvenliği", "yazili"),
    ("Mühendislik Etiği", "yazili"),
    ("Yöneylem Araştırması II", "yazili"),
    ("Gömülü Sistemler", "bilgisayar"),
    ("Akıllı Üretim Sistemleri", "yazili"),
    ("Sonlu Elemanlar Yöntemi", "bilgisayar"),
    ("Kalite Mühendisliği", "yazili"),
)


@dataclass(slots=True)
class PersonelTaslagi:
    ad: str
    unvan: str
    bolum_id: int
    gunluk_max: int
    kapali_dilimler: list[int]


@dataclass(slots=True)
class DerslikTaslagi:
    kod: str
    tur: str
    kapasite: int
    sinav_kapasitesi: int
    erisilebilir: bool
    gozetmen_sayisi: int


@dataclass(slots=True)
class DersTaslagi:
    kod: str
    ad: str
    bolum_id: int | None
    sinif: int
    zorluk: int
    sinav_turu: str
    sinav_suresi_dk: int
    hoca_id: int
    asistan_id: int | None


@dataclass(slots=True)
class OgrenciTaslagi:
    no: str
    ad: str
    bolum_id: int
    sinif: int
    ders_idleri: list[int]
    erisilebilir_salon: bool = False
    ayri_salon: bool = False
    ek_sure_orani: float = 0.0


def veritabanini_yenile(yol: str | Path) -> int:
    """Eski şemalı veritabanını yedekleyip yeniden kurar, AHP anketlerini korur (CLI `yenile` ile aynı).

    Arayüz altyapıyı doğrudan import etmesin diye burada sunulur. Taşınan katılımcı sayısını döndürür."""
    return anketleri_koruyarak_yenile(yol)


def _ogrenci_cikar(veri: VeriSeti, silinecek: set[int]) -> None:
    veri.ogrenciler = [o for o in veri.ogrenciler if o.id not in silinecek]
    veri.kayitlar = [(oid, did) for (oid, did) in veri.kayitlar if oid not in silinecek]
    veri.gereksinimler = [g for g in veri.gereksinimler if g.ogrenci_id not in silinecek]


def _ders_cikar(veri: VeriSeti, silinecek: set[int]) -> None:
    veri.dersler = [d for d in veri.dersler if d.id not in silinecek]
    veri.kayitlar = [(oid, did) for (oid, did) in veri.kayitlar if did not in silinecek]
    veri.dilim_kurallari = [k for k in veri.dilim_kurallari if k.ders_id not in silinecek]


def _personel_cikar(veri: VeriSeti, silinecek: set[int]) -> None:
    """Kalan derslerin hocası silinemez (ders hocasız kalamaz); asistanlık ise boşaltılır."""
    bagli = sorted(d.kod for d in veri.dersler if d.hoca_id in silinecek)
    if bagli:
        raise VeriHatasi(
            [f"Silinecek öğretim elemanları şu derslerin hocası: {', '.join(bagli)}. Önce bu dersleri silin "
             "ya da hocasını değiştirin."]
        )
    veri.personeller = [p for p in veri.personeller if p.id not in silinecek]
    veri.dersler = [replace(d, asistan_id=None) if d.asistan_id in silinecek else d for d in veri.dersler]
    veri.personel_musait_degil = {(pid, did) for (pid, did) in veri.personel_musait_degil if pid not in silinecek}


def _yeni_id(mevcut_idler: Iterable[int]) -> int:
    return max(mevcut_idler, default=0) + 1


def _benzersiz_ad(mevcut: set[str], rng: random.Random) -> str:
    for _ in range(200):
        aday = f"{rng.choice(ADLAR)} {rng.choice(SOYADLAR)}"
        if aday not in mevcut:
            return aday
    return f"{rng.choice(ADLAR)} {rng.choice(SOYADLAR)} {rng.randint(2, 99)}"


class VeriStudyosuServisi:
    """Masaüstü Veri Stüdyosu için üst düzey veri oluşturma, düzenleme ve rastgele varlık üretme servisi."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.depo = VeriDeposu(conn)
        self.veri_servisi = VeriServisi(conn)
        self._rng = random.Random()

    # ------------------------------------------------------------------ Dönem yükleme / sıfırlama
    def aktif_veri(self) -> VeriSeti | None:
        donemler = self.depo.donemler.hepsi()  # başlangıca göre yeniden eskiye sıralı
        if not donemler:
            return None
        return self.depo.yukle(donemler[0].id)

    def zorunlu_veri(self) -> VeriSeti:
        veri = self.aktif_veri()
        if veri is None:
            raise VeriHatasi(
                ["Henüz aktif bir sınav dönemi yok. Önce 'Temiz Dönem Aç' veya 'Hızlı Fakülte Üret' seçin."]
            )
        return veri

    def aktif_uyarilar(self) -> list[str]:
        veri = self.aktif_veri()
        if veri is None:
            return []
        _, uyarilar = veri_kontrol(veri)
        return uyarilar

    def _kaydet(self, veri: VeriSeti) -> list[str]:
        hatalar, uyarilar = veri_kontrol(veri)
        if hatalar:
            raise VeriHatasi(hatalar)
        try:
            self.depo.degistir(veri)  # tek işlem: hata olursa eski veri korunur
        except sqlite3.IntegrityError as hata:
            raise VeriHatasi([f"Veritabanı kuralı ihlal edildi: {hata}"]) from hata
        return uyarilar

    def sentetik_olustur(self, ayar: SentetikAyarlar | None = None) -> tuple[VeriSeti, list[str]]:
        return self.veri_servisi.sentetik_uret(ayar)

    def temiz_donem_olustur(
        self,
        donem_adi: str = "2026-2027 Güz Dönemi Finalleri",
        tur: str = "final",
        baslangic: date = date(2027, 1, 4),
        gun_sayisi: int = 10,
    ) -> tuple[VeriSeti, list[str]]:
        """3 varsayılan bölüm, sınav oturumları ve kurum politikalarıyla sıfırdan boş bir dönem kurar."""
        if gun_sayisi < 1:
            raise VeriHatasi(["Gün sayısı en az 1 olmalıdır."])
        gunler = is_gunleri(baslangic, gun_sayisi)
        veri = VeriSeti()
        veri.donem = SinavDonemi(
            1, donem_adi.strip() or "Yeni Sınav Dönemi", tur, gunler[0].isoformat(), gunler[-1].isoformat()
        )
        veri.dilimler = dilimleri_uret(gunler)
        veri.bolumler = [Bolum(i + 1, kod, ad) for i, (kod, ad) in enumerate(BOLUMLER)]
        veri.politikalar = kurum_politikalari()
        uyarilar = self._kaydet(veri)
        return veri, uyarilar

    def csv_ice_aktar(self, klasor: str | Path) -> tuple[VeriSeti, list[str]]:
        return self.veri_servisi.csv_den_yukle(klasor)

    def csv_disa_aktar(self, klasor: str | Path) -> None:
        veri = self.zorunlu_veri()
        assert veri.donem is not None
        self.veri_servisi.csv_ye_aktar(veri.donem.id, klasor)

    def excel_ice_aktar(self, dosya: str | Path) -> tuple[VeriSeti, list[str]]:
        return self.veri_servisi.excel_den_yukle(dosya)

    def excel_disa_aktar(self, dosya: str | Path) -> None:
        veri = self.zorunlu_veri()
        assert veri.donem is not None
        self.veri_servisi.excel_e_aktar(veri.donem.id, dosya)

    # ------------------------------------------------------------------ Bölüm işlemleri
    def bolum_ekle(self, kod: str, ad: str) -> tuple[Bolum, list[str]]:
        veri = self.zorunlu_veri()
        temiz_kod = kod.strip().upper()
        temiz_ad = ad.strip()
        if not temiz_kod or not temiz_ad:
            raise VeriHatasi(["Bölüm kodu ve adı boş olamaz."])
        yeni = Bolum(_yeni_id(b.id for b in veri.bolumler), temiz_kod, temiz_ad)
        veri.bolumler.append(yeni)
        return yeni, self._kaydet(veri)

    # ------------------------------------------------------------------ Öğretim elemanı işlemleri
    def _taslak_personel_veriden(self, veri: VeriSeti, r: random.Random) -> PersonelTaslagi:
        if not veri.bolumler:
            raise VeriHatasi(["Önce en az bir bölüm tanımlanmalıdır."])
        mevcut_adlar = {p.ad for p in veri.personeller}
        unvan = r.choices(UNVANLAR, weights=(2, 2, 3, 5), k=1)[0]
        bolum = r.choice(veri.bolumler)
        gunluk = GUNLUK_GOREV_VARSAYIMI[unvan]
        kapali: list[int] = []
        if veri.dilimler and r.random() < 0.35:
            kapali = sorted(d.id for d in r.sample(veri.dilimler, k=min(len(veri.dilimler), r.randint(1, 3))))
        return PersonelTaslagi(_benzersiz_ad(mevcut_adlar, r), unvan, bolum.id, gunluk, kapali)

    def rastgele_personel_taslagi(self, rng: random.Random | None = None) -> PersonelTaslagi:
        return self._taslak_personel_veriden(self.zorunlu_veri(), rng or self._rng)

    def personel_ekle(
        self,
        ad: str,
        unvan: str,
        bolum_id: int,
        gunluk_max: int,
        kapali_dilimler: Iterable[int] = (),
    ) -> tuple[Personel, list[str]]:
        veri = self.zorunlu_veri()
        temiz_ad = ad.strip()
        if not temiz_ad:
            raise VeriHatasi(["Öğretim elemanı adı boş olamaz."])
        if unvan not in UNVAN_KOTALARI:
            raise VeriHatasi([f"Geçersiz unvan: {unvan}"])
        yeni = Personel(
            _yeni_id(p.id for p in veri.personeller), temiz_ad, unvan, bolum_id, UNVAN_KOTALARI[unvan], gunluk_max
        )
        veri.personeller.append(yeni)
        for dilim_id in kapali_dilimler:
            veri.personel_musait_degil.add((yeni.id, dilim_id))
        return yeni, self._kaydet(veri)

    def rastgele_personel_ekle(self, adet: int = 1, tohum: int | None = None) -> tuple[list[Personel], list[str]]:
        veri = self.zorunlu_veri()
        rng = random.Random(tohum) if tohum is not None else self._rng
        eklenenler: list[Personel] = []
        for _ in range(max(1, adet)):
            t = self._taslak_personel_veriden(veri, rng)
            yeni = Personel(
                _yeni_id(p.id for p in veri.personeller),
                t.ad,
                t.unvan,
                t.bolum_id,
                UNVAN_KOTALARI[t.unvan],
                t.gunluk_max,
            )
            veri.personeller.append(yeni)
            for did in t.kapali_dilimler:
                veri.personel_musait_degil.add((yeni.id, did))
            eklenenler.append(yeni)
        return eklenenler, self._kaydet(veri)

    def personel_musaitlik_ayarla(self, personel_id: int, kapali_dilimler: Iterable[int]) -> list[str]:
        veri = self.zorunlu_veri()
        veri.personel_musait_degil = {
            (pid, did) for (pid, did) in veri.personel_musait_degil if pid != personel_id
        } | {(personel_id, did) for did in kapali_dilimler}
        return self._kaydet(veri)

    def personel_sil(self, personel_id: int) -> list[str]:
        return self.personelleri_sil([personel_id])

    def personelleri_sil(self, personel_idleri: Iterable[int]) -> list[str]:
        """Toplu silme, tek işlem. Kalan bir dersin hocası olan kişi varsa hiçbiri silinmez."""
        veri = self.zorunlu_veri()
        _personel_cikar(veri, set(personel_idleri))
        return self._kaydet(veri)

    # ------------------------------------------------------------------ Derslik işlemleri
    def rastgele_derslik_taslagi(self, rng: random.Random | None = None) -> DerslikTaslagi:
        return self._taslak_derslik_veriden(self.zorunlu_veri(), rng or self._rng)

    def derslik_ekle(
        self,
        kod: str,
        tur: str,
        kapasite: int,
        sinav_kapasitesi: int,
        erisilebilir: bool = False,
        gozetmen_sayisi: int | None = None,
        kapali_dilimler: Iterable[int] = (),
    ) -> tuple[Derslik, list[str]]:
        veri = self.zorunlu_veri()
        temiz_kod = kod.strip().upper()
        if not temiz_kod:
            raise VeriHatasi(["Derslik kodu boş olamaz."])
        goz = gozetmen_sayisi if gozetmen_sayisi is not None else max(
            1, -(-sinav_kapasitesi // SALON_BASI_KOLTUK_VARSAYIMI)
        )
        yeni = Derslik(
            _yeni_id(d.id for d in veri.derslikler), temiz_kod, kapasite, sinav_kapasitesi, tur, erisilebilir, goz
        )
        veri.derslikler.append(yeni)
        for did in kapali_dilimler:
            veri.derslik_musait_degil.add((yeni.id, did))
        return yeni, self._kaydet(veri)

    def rastgele_derslik_ekle(self, adet: int = 1, tohum: int | None = None) -> tuple[list[Derslik], list[str]]:
        veri = self.zorunlu_veri()
        rng = random.Random(tohum) if tohum is not None else self._rng
        eklenenler: list[Derslik] = []
        for _ in range(max(1, adet)):
            taslak = self._taslak_derslik_veriden(veri, rng)
            yeni = Derslik(
                _yeni_id(d.id for d in veri.derslikler),
                taslak.kod,
                taslak.kapasite,
                taslak.sinav_kapasitesi,
                taslak.tur,
                taslak.erisilebilir,
                taslak.gozetmen_sayisi,
            )
            veri.derslikler.append(yeni)
            eklenenler.append(yeni)
        return eklenenler, self._kaydet(veri)

    def _taslak_derslik_veriden(self, veri: VeriSeti, r: random.Random) -> DerslikTaslagi:
        mevcut_kodlar = {d.kod for d in veri.derslikler}
        tur = r.choices(("normal", "amfi", "bilgisayar", "ozel"), weights=(7, 2, 3, 1), k=1)[0]
        if tur == "amfi":
            onek, kap, s_kap, eris = "AMFI", 220, 110, True
        elif tur == "bilgisayar":
            onek, kap, s_kap, eris = "LAB", 40, 40, r.random() < 0.5
        elif tur == "ozel":
            onek, kap, s_kap, eris = "OZEL", 8, 8, True
        else:
            buyuk = r.random() < 0.35
            onek, kap, s_kap, eris = "D", (80 if buyuk else 60), (40 if buyuk else 30), r.random() < 0.4
        sayac = 1
        while True:
            kod = f"{onek}-{100 + sayac}" if onek == "D" else f"{onek}-{sayac}"
            if kod not in mevcut_kodlar:
                break
            sayac += 1
        gozetmen = max(1, -(-s_kap // SALON_BASI_KOLTUK_VARSAYIMI))
        return DerslikTaslagi(kod, tur, kap, s_kap, eris, gozetmen)

    def derslik_musaitlik_ayarla(self, derslik_id: int, kapali_dilimler: Iterable[int]) -> list[str]:
        veri = self.zorunlu_veri()
        veri.derslik_musait_degil = {
            (rid, did) for (rid, did) in veri.derslik_musait_degil if rid != derslik_id
        } | {(derslik_id, did) for did in kapali_dilimler}
        return self._kaydet(veri)

    def derslik_sil(self, derslik_id: int) -> list[str]:
        return self.derslikleri_sil([derslik_id])

    def derslikleri_sil(self, derslik_idleri: Iterable[int]) -> list[str]:
        veri = self.zorunlu_veri()
        silinecek = set(derslik_idleri)
        veri.derslikler = [d for d in veri.derslikler if d.id not in silinecek]
        veri.derslik_musait_degil = {(rid, did) for (rid, did) in veri.derslik_musait_degil if rid not in silinecek}
        return self._kaydet(veri)

    # ------------------------------------------------------------------ Ders ve kural işlemleri
    def _taslak_ders_veriden(self, veri: VeriSeti, r: random.Random) -> DersTaslagi:
        if not veri.personeller:
            raise VeriHatasi(["Ders oluşturmadan önce en az bir öğretim elemanı eklemelisiniz."])
        mevcut_kodlar = {d.kod for d in veri.dersler}
        bolum_haritasi = {b.kod: b.id for b in veri.bolumler}

        havuz: list[tuple[str, str, int | None, int, int, str]] = []
        for kod, ad, sinif, zorluk, tur in ORTAK_DERSLER:
            if kod not in mevcut_kodlar:
                havuz.append((kod, ad, None, sinif, zorluk, tur))
        for b_kod, liste in ZORUNLU_DERSLER.items():
            if b_kod in bolum_haritasi:
                for kod, ad, sinif, zorluk, tur in liste:
                    if kod not in mevcut_kodlar:
                        havuz.append((kod, ad, bolum_haritasi[b_kod], sinif, zorluk, tur))
        for b_kod, ciftler in SECMELI_CIFTLER.items():
            if b_kod in bolum_haritasi:
                for cift in ciftler:
                    for kod, ad, sinif, zorluk, tur in cift:
                        if kod not in mevcut_kodlar:
                            havuz.append((kod, ad, bolum_haritasi[b_kod], sinif, zorluk, tur))

        if havuz:
            kod, ad, bolum_id, sinif, zorluk, tur = r.choice(havuz)
        else:
            bolum = r.choice(veri.bolumler) if veri.bolumler and r.random() < 0.85 else None
            sinif = r.randint(1, 4)
            zorluk = r.randint(2, 5)
            ad_taban, tur = r.choice(_EK_DERS_ADLARI)
            onek = bolum.kod if bolum is not None else "ORT"
            num = 50 + len(veri.dersler)
            while f"{onek}{sinif}{num:02d}" in mevcut_kodlar:
                num += 1
            kod = f"{onek}{sinif}{num:02d}"
            ad = f"{ad_taban} ({kod})"
            bolum_id = bolum.id if bolum is not None else None

        bolum_hocalari = [
            p for p in veri.personeller if (bolum_id is None or p.bolum_id == bolum_id) and p.ogretim_uyesi
        ]
        if not bolum_hocalari:
            bolum_hocalari = [p for p in veri.personeller if p.ogretim_uyesi] or list(veri.personeller)
        hoca = r.choice(bolum_hocalari)
        asistan_adaylari = [
            p for p in veri.personeller
            if p.id != hoca.id and p.unvan == "Arş. Gör." and (bolum_id is None or p.bolum_id == bolum_id)
        ]
        asistan_id = r.choice(asistan_adaylari).id if asistan_adaylari else None
        return DersTaslagi(kod, ad, bolum_id, sinif, zorluk, tur, SINAV_SURESI[zorluk], hoca.id, asistan_id)

    def rastgele_ders_taslagi(self, rng: random.Random | None = None) -> DersTaslagi:
        veri = self.zorunlu_veri()
        return self._taslak_ders_veriden(veri, rng or self._rng)

    def ders_ekle(
        self,
        kod: str,
        ad: str,
        bolum_id: int | None,
        sinif: int,
        zorluk: int,
        sinav_turu: str,
        sinav_suresi_dk: int,
        hoca_id: int,
        asistan_id: int | None = None,
    ) -> tuple[Ders, list[str]]:
        veri = self.zorunlu_veri()
        temiz_kod = kod.strip().upper()
        temiz_ad = ad.strip()
        if not temiz_kod or not temiz_ad:
            raise VeriHatasi(["Ders kodu ve ders adı boş olamaz."])
        yeni = Ders(
            _yeni_id(d.id for d in veri.dersler),
            temiz_kod,
            temiz_ad,
            bolum_id,
            sinif,
            zorluk,
            sinav_turu,
            sinav_suresi_dk,
            hoca_id,
            asistan_id,
        )
        veri.dersler.append(yeni)
        return yeni, self._kaydet(veri)

    def rastgele_ders_ekle(self, adet: int = 1, tohum: int | None = None) -> tuple[list[Ders], list[str]]:
        veri = self.zorunlu_veri()
        rng = random.Random(tohum) if tohum is not None else self._rng
        eklenenler: list[Ders] = []
        for _ in range(max(1, adet)):
            t = self._taslak_ders_veriden(veri, rng)
            yeni = Ders(
                _yeni_id(d.id for d in veri.dersler),
                t.kod,
                t.ad,
                t.bolum_id,
                t.sinif,
                t.zorluk,
                t.sinav_turu,
                t.sinav_suresi_dk,
                t.hoca_id,
                t.asistan_id,
            )
            veri.dersler.append(yeni)
            eklenenler.append(yeni)
        return eklenenler, self._kaydet(veri)

    def ders_kurallari_ayarla(self, ders_id: int, kurallar: Iterable[tuple[int, str, str]]) -> list[str]:
        veri = self.zorunlu_veri()
        kalan = [k for k in veri.dilim_kurallari if k.ders_id != ders_id]
        for dilim_id, tur, aciklama in kurallar:
            kalan.append(SinavDilimKurali(ders_id, dilim_id, tur, aciklama.strip() or None))
        veri.dilim_kurallari = kalan
        return self._kaydet(veri)

    def ders_sil(self, ders_id: int) -> list[str]:
        return self.dersleri_sil([ders_id])

    def dersleri_sil(self, ders_idleri: Iterable[int]) -> list[str]:
        """Derslerle birlikte o derslerin öğrenci kayıtları ve sabit/yasak oturum kuralları da silinir."""
        veri = self.zorunlu_veri()
        _ders_cikar(veri, set(ders_idleri))
        return self._kaydet(veri)

    # ------------------------------------------------------------------ Öğrenci işlemleri
    def _taslak_ogrenci_veriden(self, veri: VeriSeti, r: random.Random) -> OgrenciTaslagi:
        if not veri.bolumler:
            raise VeriHatasi(["Öğrenci oluşturmadan önce en az bir bölüm tanımlanmalıdır."])
        bolum = r.choice(veri.bolumler)
        sinif = r.randint(1, 4)
        mevcut_nolar = {o.no for o in veri.ogrenciler}
        mevcut_adlar = {o.ad for o in veri.ogrenciler}
        assert veri.donem is not None
        yil = (int(veri.donem.baslangic[:4]) - sinif) % 100  # sentetik veriyle aynı: giriş yılı = dönem yılı − sınıf
        sira = len(veri.ogrenciler) + 1
        while True:
            no = f"{yil:02d}{bolum.id:02d}{sira:04d}"
            if no not in mevcut_nolar:
                break
            sira += 1

        # Bölüme ve sınıfa uygun dersleri seç (yoksa mevcut derslerden makul bir alt küme ata)
        uygun_dersler = [
            d.id for d in veri.dersler if (d.bolum_id is None or d.bolum_id == bolum.id) and d.sinif == sinif
        ]
        alt_dersler = [
            d.id for d in veri.dersler if (d.bolum_id is None or d.bolum_id == bolum.id) and d.sinif < sinif
        ]
        secilen: list[int] = []
        if uygun_dersler:
            hedef = min(len(uygun_dersler), r.randint(min(3, len(uygun_dersler)), min(6, len(uygun_dersler))))
            secilen.extend(sorted(r.sample(uygun_dersler, k=hedef)))
            if alt_dersler and r.random() < 0.20:
                secilen.append(r.choice(alt_dersler))
        elif veri.dersler:
            hedef = min(len(veri.dersler), r.randint(1, min(4, len(veri.dersler))))
            secilen.extend(sorted(d.id for d in r.sample(veri.dersler, k=hedef)))

        eris = ayri = False
        ek_sure = 0.0
        if r.random() < 0.08:
            (eris, ayri, ek_sure) = r.choices(
                [p[0] for p in GEREKSINIM_PROFILLERI], weights=[p[1] for p in GEREKSINIM_PROFILLERI], k=1
            )[0]

        return OgrenciTaslagi(
            no=no,
            ad=_benzersiz_ad(mevcut_adlar, r),
            bolum_id=bolum.id,
            sinif=sinif,
            ders_idleri=sorted(set(secilen)),
            erisilebilir_salon=eris,
            ayri_salon=ayri,
            ek_sure_orani=ek_sure,
        )

    def rastgele_ogrenci_taslagi(self, rng: random.Random | None = None) -> OgrenciTaslagi:
        veri = self.zorunlu_veri()
        return self._taslak_ogrenci_veriden(veri, rng or self._rng)

    def ogrenci_ekle(
        self,
        no: str,
        ad: str,
        bolum_id: int,
        sinif: int,
        ders_idleri: Iterable[int] = (),
        erisilebilir_salon: bool = False,
        ayri_salon: bool = False,
        ek_sure_orani: float = 0.0,
    ) -> tuple[Ogrenci, list[str]]:
        veri = self.zorunlu_veri()
        temiz_no = no.strip()
        temiz_ad = ad.strip()
        if not temiz_no or not temiz_ad:
            raise VeriHatasi(["Öğrenci numarası ve adı boş olamaz."])
        yeni = Ogrenci(_yeni_id(o.id for o in veri.ogrenciler), temiz_no, temiz_ad, bolum_id, sinif)
        veri.ogrenciler.append(yeni)
        for did in sorted(set(ders_idleri)):
            veri.kayitlar.append((yeni.id, did))
        if erisilebilir_salon or ayri_salon or ek_sure_orani > 0.0:
            veri.gereksinimler.append(OgrenciGereksinim(yeni.id, erisilebilir_salon, ayri_salon, ek_sure_orani))
        return yeni, self._kaydet(veri)

    def rastgele_ogrenci_ekle(self, adet: int = 1, tohum: int | None = None) -> tuple[list[Ogrenci], list[str]]:
        veri = self.zorunlu_veri()
        if not veri.bolumler:
            raise VeriHatasi(["Önce en az bir bölüm tanımlanmalıdır."])
        rng = random.Random(tohum) if tohum is not None else self._rng
        eklenenler: list[Ogrenci] = []
        for _ in range(max(1, adet)):
            t = self._taslak_ogrenci_veriden(veri, rng)
            yeni = Ogrenci(_yeni_id(o.id for o in veri.ogrenciler), t.no, t.ad, t.bolum_id, t.sinif)
            veri.ogrenciler.append(yeni)
            for did in t.ders_idleri:
                veri.kayitlar.append((yeni.id, did))
            if t.erisilebilir_salon or t.ayri_salon or t.ek_sure_orani > 0.0:
                veri.gereksinimler.append(
                    OgrenciGereksinim(yeni.id, t.erisilebilir_salon, t.ayri_salon, t.ek_sure_orani)
                )
            eklenenler.append(yeni)
        return eklenenler, self._kaydet(veri)

    def ogrenci_kayit_ayarla(
        self,
        ogrenci_id: int,
        ders_idleri: Iterable[int],
        erisilebilir_salon: bool = False,
        ayri_salon: bool = False,
        ek_sure_orani: float = 0.0,
    ) -> list[str]:
        veri = self.zorunlu_veri()
        veri.kayitlar = [(oid, did) for (oid, did) in veri.kayitlar if oid != ogrenci_id]
        for did in sorted(set(ders_idleri)):
            veri.kayitlar.append((ogrenci_id, did))
        veri.gereksinimler = [g for g in veri.gereksinimler if g.ogrenci_id != ogrenci_id]
        if erisilebilir_salon or ayri_salon or ek_sure_orani > 0.0:
            veri.gereksinimler.append(
                OgrenciGereksinim(ogrenci_id, erisilebilir_salon, ayri_salon, ek_sure_orani)
            )
        return self._kaydet(veri)

    def ogrenci_sil(self, ogrenci_id: int) -> list[str]:
        return self.ogrencileri_sil([ogrenci_id])

    def ogrencileri_sil(self, ogrenci_idleri: Iterable[int]) -> list[str]:
        veri = self.zorunlu_veri()
        _ogrenci_cikar(veri, set(ogrenci_idleri))
        return self._kaydet(veri)

    # ------------------------------------------------------------------ Bölüm ve tüm veri silme
    def bolumu_sil(self, bolum_id: int) -> list[str]:
        """Bölümü öğrencileri, bölüm dersleri (kayıt ve kurallarıyla) ve öğretim elemanlarıyla birlikte TEK işlemde
        siler. Bölümün bir hocası başka bölümün/ortak bir dersin hocasıysa hiçbir şey silinmez (önce o ders)."""
        veri = self.zorunlu_veri()
        if not any(b.id == bolum_id for b in veri.bolumler):
            raise VeriHatasi([f"{bolum_id} numaralı bölüm bulunamadı."])
        _ogrenci_cikar(veri, {o.id for o in veri.ogrenciler if o.bolum_id == bolum_id})
        _ders_cikar(veri, {d.id for d in veri.dersler if d.bolum_id == bolum_id})
        _personel_cikar(veri, {p.id for p in veri.personeller if p.bolum_id == bolum_id})
        veri.bolumler = [b for b in veri.bolumler if b.id != bolum_id]
        return self._kaydet(veri)

    def tum_veriyi_sil(self) -> None:
        """Dönem dahil bütün veriyi ve kayıtlı takvimleri siler (sıfırdan başlamak için). AHP anketleri korunur."""
        self.depo.tumunu_sil()


__all__ = [
    "DersTaslagi",
    "DerslikTaslagi",
    "OgrenciTaslagi",
    "PersonelTaslagi",
    "VeriHatasi",
    "VeriStudyosuServisi",
    "veritabanini_yenile",
]
