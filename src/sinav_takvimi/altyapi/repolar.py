"""Repository'ler: SQL'in yazıldığı tek yer.

Kurallar:
* Tüm sorgular parametrelidir (`?`). Kullanıcı verisi asla SQL metnine eklenmez, SQL injection olmaz.
* Repository'ler commit yapmaz. İşlem (transaction) sınırını çağıran belirler: `with conn:` bloğu
  başarılı biterse commit, hata olursa rollback yapar.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
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


class BolumRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle_hepsi(self, bolumler: Iterable[Bolum]) -> None:
        self.conn.executemany(
            "INSERT INTO bolum (id, kod, ad) VALUES (?, ?, ?)",
            [(b.id, b.kod, b.ad) for b in bolumler],
        )

    def hepsi(self) -> list[Bolum]:
        return [Bolum(**r) for r in self.conn.execute("SELECT id, kod, ad FROM bolum ORDER BY id")]


class DonemRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle(self, d: SinavDonemi) -> None:
        self.conn.execute(
            "INSERT INTO sinav_donemi (id, ad, tur, baslangic, bitis) VALUES (?, ?, ?, ?, ?)",
            (d.id, d.ad, d.tur, d.baslangic, d.bitis),
        )

    def hepsi(self) -> list[SinavDonemi]:
        sql = "SELECT id, ad, tur, baslangic, bitis FROM sinav_donemi ORDER BY baslangic DESC"
        return [SinavDonemi(**r) for r in self.conn.execute(sql)]

    def getir(self, donem_id: int) -> SinavDonemi | None:
        r = self.conn.execute(
            "SELECT id, ad, tur, baslangic, bitis FROM sinav_donemi WHERE id = ?", (donem_id,)
        ).fetchone()
        return SinavDonemi(**r) if r else None


class PersonelRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle_hepsi(self, personeller: Iterable[Personel]) -> None:
        self.conn.executemany(
            "INSERT INTO personel (id, ad, unvan, bolum_id, kota_carpani, gunluk_max) VALUES (?, ?, ?, ?, ?, ?)",
            [(p.id, p.ad, p.unvan, p.bolum_id, p.kota_carpani, p.gunluk_max) for p in personeller],
        )

    def hepsi(self) -> list[Personel]:
        sql = "SELECT id, ad, unvan, bolum_id, kota_carpani, gunluk_max FROM personel ORDER BY id"
        return [Personel(**r) for r in self.conn.execute(sql)]


class DersRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle_hepsi(self, dersler: Iterable[Ders]) -> None:
        self.conn.executemany(
            """INSERT INTO ders (id, kod, ad, bolum_id, sinif, zorluk, sinav_turu, sinav_suresi_dk, hoca_id, asistan_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (d.id, d.kod, d.ad, d.bolum_id, d.sinif, d.zorluk, d.sinav_turu, d.sinav_suresi_dk,
                 d.hoca_id, d.asistan_id)
                for d in dersler
            ],
        )

    def hepsi(self) -> list[Ders]:
        sql = """SELECT id, kod, ad, bolum_id, sinif, zorluk, sinav_turu, sinav_suresi_dk, hoca_id, asistan_id
                 FROM ders ORDER BY id"""
        return [Ders(**r) for r in self.conn.execute(sql)]


class OgrenciRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle_hepsi(self, ogrenciler: Iterable[Ogrenci]) -> None:
        self.conn.executemany(
            "INSERT INTO ogrenci (id, no, ad, bolum_id, sinif) VALUES (?, ?, ?, ?, ?)",
            [(o.id, o.no, o.ad, o.bolum_id, o.sinif) for o in ogrenciler],
        )

    def hepsi(self) -> list[Ogrenci]:
        return [Ogrenci(**r) for r in self.conn.execute("SELECT id, no, ad, bolum_id, sinif FROM ogrenci ORDER BY id")]

    def ekle_gereksinimler(self, gereksinimler: Iterable[OgrenciGereksinim]) -> None:
        self.conn.executemany(
            """INSERT INTO ogrenci_gereksinim (ogrenci_id, erisilebilir_salon, ayri_salon, ek_sure_orani)
               VALUES (?, ?, ?, ?)""",
            [(g.ogrenci_id, int(g.erisilebilir_salon), int(g.ayri_salon), g.ek_sure_orani) for g in gereksinimler],
        )

    def gereksinimler(self) -> list[OgrenciGereksinim]:
        sql = """SELECT ogrenci_id, erisilebilir_salon, ayri_salon, ek_sure_orani
                 FROM ogrenci_gereksinim ORDER BY ogrenci_id"""
        return [
            OgrenciGereksinim(r["ogrenci_id"], bool(r["erisilebilir_salon"]), bool(r["ayri_salon"]), r["ek_sure_orani"])
            for r in self.conn.execute(sql)
        ]


class KayitRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle_hepsi(self, kayitlar: Iterable[tuple[int, int]]) -> None:
        self.conn.executemany("INSERT INTO kayit (ogrenci_id, ders_id) VALUES (?, ?)", list(kayitlar))

    def hepsi(self) -> list[tuple[int, int]]:
        sql = "SELECT ogrenci_id, ders_id FROM kayit ORDER BY ogrenci_id, ders_id"
        return [(r[0], r[1]) for r in self.conn.execute(sql)]

    def ders_ogrenci_sayilari(self) -> dict[int, int]:
        sql = "SELECT ders_id, COUNT(*) FROM kayit GROUP BY ders_id"
        return {r[0]: r[1] for r in self.conn.execute(sql)}


class DerslikRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle_hepsi(self, derslikler: Iterable[Derslik]) -> None:
        self.conn.executemany(
            """INSERT INTO derslik (id, kod, kapasite, sinav_kapasitesi, tur, erisilebilir, gozetmen_sayisi)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (d.id, d.kod, d.kapasite, d.sinav_kapasitesi, d.tur, int(d.erisilebilir), d.gozetmen_sayisi)
                for d in derslikler
            ],
        )

    def hepsi(self) -> list[Derslik]:
        sql = """SELECT id, kod, kapasite, sinav_kapasitesi, tur, erisilebilir, gozetmen_sayisi
                 FROM derslik ORDER BY id"""
        return [
            Derslik(r["id"], r["kod"], r["kapasite"], r["sinav_kapasitesi"], r["tur"], bool(r["erisilebilir"]),
                    r["gozetmen_sayisi"])
            for r in self.conn.execute(sql)
        ]


class DilimRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle_hepsi(self, dilimler: Iterable[Dilim]) -> None:
        self.conn.executemany(
            "INSERT INTO dilim (id, donem_id, gun, tarih, baslangic, sira, sure_dk) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(d.id, d.donem_id, d.gun, d.tarih, d.baslangic, d.sira, d.sure_dk) for d in dilimler],
        )

    def donem_icin(self, donem_id: int) -> list[Dilim]:
        sql = """SELECT id, donem_id, gun, tarih, baslangic, sira, sure_dk FROM dilim
                 WHERE donem_id = ? ORDER BY gun, sira"""
        return [Dilim(**r) for r in self.conn.execute(sql, (donem_id,))]


class MusaitlikRepo:
    """Personel ve derslik müsaitsizlikleri (sadece verilen dönemin dilimleri)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle_personel(self, ciftler: Iterable[tuple[int, int]]) -> None:
        self.conn.executemany(
            "INSERT INTO personel_musait_degil (personel_id, dilim_id) VALUES (?, ?)", sorted(ciftler)
        )

    def ekle_derslik(self, ciftler: Iterable[tuple[int, int]]) -> None:
        self.conn.executemany("INSERT INTO derslik_musait_degil (derslik_id, dilim_id) VALUES (?, ?)", sorted(ciftler))

    def personel_donem_icin(self, donem_id: int) -> set[tuple[int, int]]:
        sql = """SELECT m.personel_id, m.dilim_id FROM personel_musait_degil m
                 JOIN dilim d ON d.id = m.dilim_id WHERE d.donem_id = ?"""
        return {(r[0], r[1]) for r in self.conn.execute(sql, (donem_id,))}

    def derslik_donem_icin(self, donem_id: int) -> set[tuple[int, int]]:
        sql = """SELECT m.derslik_id, m.dilim_id FROM derslik_musait_degil m
                 JOIN dilim d ON d.id = m.dilim_id WHERE d.donem_id = ?"""
        return {(r[0], r[1]) for r in self.conn.execute(sql, (donem_id,))}


class DilimKuraliRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle_hepsi(self, kurallar: Iterable[SinavDilimKurali]) -> None:
        self.conn.executemany(
            "INSERT INTO sinav_dilim_kurali (ders_id, dilim_id, tur, aciklama) VALUES (?, ?, ?, ?)",
            [(k.ders_id, k.dilim_id, k.tur, k.aciklama) for k in kurallar],
        )

    def donem_icin(self, donem_id: int) -> list[SinavDilimKurali]:
        sql = """SELECT k.ders_id, k.dilim_id, k.tur, k.aciklama FROM sinav_dilim_kurali k
                 JOIN dilim d ON d.id = k.dilim_id WHERE d.donem_id = ? ORDER BY k.ders_id, k.dilim_id"""
        return [SinavDilimKurali(**r) for r in self.conn.execute(sql, (donem_id,))]


class PolitikaRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle_hepsi(self, politikalar: Iterable[KurumPolitikasi]) -> None:
        self.conn.executemany(
            "INSERT INTO kurum_politikasi (anahtar, deger, aciklama, kaynak) VALUES (?, ?, ?, ?)",
            [(p.anahtar, p.deger, p.aciklama, p.kaynak) for p in politikalar],
        )

    def hepsi(self) -> list[KurumPolitikasi]:
        sql = "SELECT anahtar, deger, aciklama, kaynak FROM kurum_politikasi ORDER BY anahtar"
        return [KurumPolitikasi(**r) for r in self.conn.execute(sql)]


# ---------------------------------------------------------------------------------------------
# AHP anketi
# ---------------------------------------------------------------------------------------------


@dataclass(slots=True)
class AhpKatilimci:
    ad: str
    rol: str  # ogrenci / ogretim_elemani / idari
    tarih: str
    yargilar: dict[str, dict[tuple[str, str], float]]  # matris adı → {(a, b): değer}
    id: int | None = None


class AhpRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle(self, k: AhpKatilimci) -> int:
        cur = self.conn.execute(
            "INSERT INTO ahp_katilimci (ad, rol, tarih) VALUES (?, ?, ?)", (k.ad, k.rol, k.tarih)
        )
        kid = cur.lastrowid
        assert kid is not None
        self.conn.executemany(
            "INSERT INTO ahp_yargi (katilimci_id, matris, a, b, deger) VALUES (?, ?, ?, ?, ?)",
            [(kid, m, a, b, d) for m, yargi in k.yargilar.items() for (a, b), d in yargi.items()],
        )
        return kid

    def hepsi(self) -> list[AhpKatilimci]:
        katilimcilar = {
            r["id"]: AhpKatilimci(r["ad"], r["rol"], r["tarih"], {}, r["id"])
            for r in self.conn.execute("SELECT id, ad, rol, tarih FROM ahp_katilimci ORDER BY id")
        }
        sql = "SELECT katilimci_id, matris, a, b, deger FROM ahp_yargi ORDER BY katilimci_id, matris, a, b"
        for r in self.conn.execute(sql):
            katilimcilar[r["katilimci_id"]].yargilar.setdefault(r["matris"], {})[(r["a"], r["b"])] = r["deger"]
        return list(katilimcilar.values())

    def sil(self, katilimci_id: int) -> None:
        self.conn.execute("DELETE FROM ahp_katilimci WHERE id = ?", (katilimci_id,))


# ---------------------------------------------------------------------------------------------
# Çalıştırma sonuçları
# ---------------------------------------------------------------------------------------------


@dataclass(slots=True)
class CalistirmaKaydi:
    """Bir takvim çalıştırmasının veritabanına yazılacak/okunacak hâli (ham kimliklerle)."""

    donem_id: int
    zaman: str
    algoritma: str
    parametreler: dict[str, Any]
    sert_ihlal: int
    toplam_ceza: float
    gozetmen_ceza: float
    sure_sn: float
    ceza_detay: dict[str, float]
    gecmis: list[list[float]]
    sinav_atamalari: list[tuple[int, int]]  # (ders_id, dilim_id)
    derslik_atamalari: list[tuple[int, int, int, bool]]  # (ders_id, derslik_id, ogrenci_sayisi, ayri_salon)
    gozetmen_atamalari: list[tuple[int, int | None, int | None, int, str]]  # (dilim, ders, derslik, personel, rol)
    ozel_oturmalar: list[tuple[int, int, int]] = field(default_factory=list)  # (ogrenci_id, ders_id, derslik_id)
    ahp_agirliklari: dict[str, Any] = field(default_factory=dict)  # şema v7: çalıştırmanın AHP sonucu
    referans: dict[str, Any] = field(default_factory=dict)  # şema v7: {"olcek": {kriter: ölçek}, "kaynak": {kriter: …}}
    id: int | None = None


class CalistirmaRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ekle(self, k: CalistirmaKaydi) -> int:
        cur = self.conn.execute(
            """INSERT INTO calistirma (donem_id, zaman, algoritma, parametreler, sert_ihlal, toplam_ceza,
                                       gozetmen_ceza, sure_sn, ceza_detay, gecmis, ahp_agirliklari, referans)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (k.donem_id, k.zaman, k.algoritma, json.dumps(k.parametreler, ensure_ascii=False), k.sert_ihlal,
             k.toplam_ceza, k.gozetmen_ceza, k.sure_sn, json.dumps(k.ceza_detay, ensure_ascii=False),
             json.dumps(k.gecmis), json.dumps(k.ahp_agirliklari, ensure_ascii=False),
             json.dumps(k.referans, ensure_ascii=False)),
        )
        cid = cur.lastrowid
        assert cid is not None
        self.conn.executemany(
            "INSERT INTO sinav_atama (calistirma_id, ders_id, dilim_id) VALUES (?, ?, ?)",
            [(cid, d, p) for d, p in k.sinav_atamalari],
        )
        self.conn.executemany(
            """INSERT INTO derslik_atama (calistirma_id, ders_id, derslik_id, ogrenci_sayisi, ayri_salon)
               VALUES (?, ?, ?, ?, ?)""",
            [(cid, d, r, n, int(a)) for d, r, n, a in k.derslik_atamalari],
        )
        self.conn.executemany(
            """INSERT INTO gozetmen_atama (calistirma_id, dilim_id, ders_id, derslik_id, personel_id, rol)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(cid, p, d, r, k_, rol) for p, d, r, k_, rol in k.gozetmen_atamalari],
        )
        self.conn.executemany(
            "INSERT INTO ozel_oturma (calistirma_id, ogrenci_id, ders_id, derslik_id) VALUES (?, ?, ?, ?)",
            [(cid, o, d, r) for o, d, r in k.ozel_oturmalar],
        )
        return cid

    def listele(self, donem_id: int) -> list[dict[str, Any]]:
        sql = """SELECT id, zaman, algoritma, sert_ihlal, toplam_ceza, gozetmen_ceza, sure_sn
                 FROM calistirma WHERE donem_id = ? ORDER BY id DESC"""
        return [dict(r) for r in self.conn.execute(sql, (donem_id,))]

    def getir(self, calistirma_id: int) -> CalistirmaKaydi | None:
        r = self.conn.execute("SELECT * FROM calistirma WHERE id = ?", (calistirma_id,)).fetchone()
        if r is None:
            return None
        sinav = [(x[0], x[1]) for x in self.conn.execute(
            "SELECT ders_id, dilim_id FROM sinav_atama WHERE calistirma_id = ? ORDER BY ders_id", (calistirma_id,))]
        derslik = [(x[0], x[1], x[2], bool(x[3])) for x in self.conn.execute(
            """SELECT ders_id, derslik_id, ogrenci_sayisi, ayri_salon FROM derslik_atama
               WHERE calistirma_id = ? ORDER BY ders_id, ayri_salon, ogrenci_sayisi DESC""", (calistirma_id,))]
        gozetmen = [(x[0], x[1], x[2], x[3], x[4]) for x in self.conn.execute(
            """SELECT dilim_id, ders_id, derslik_id, personel_id, rol FROM gozetmen_atama
               WHERE calistirma_id = ? ORDER BY id""", (calistirma_id,))]
        ozel = [(x[0], x[1], x[2]) for x in self.conn.execute(
            """SELECT ogrenci_id, ders_id, derslik_id FROM ozel_oturma WHERE calistirma_id = ?
               ORDER BY ders_id, ogrenci_id""", (calistirma_id,))]
        return CalistirmaKaydi(
            id=r["id"], donem_id=r["donem_id"], zaman=r["zaman"], algoritma=r["algoritma"],
            parametreler=json.loads(r["parametreler"]), sert_ihlal=r["sert_ihlal"], toplam_ceza=r["toplam_ceza"],
            gozetmen_ceza=r["gozetmen_ceza"], sure_sn=r["sure_sn"], ceza_detay=json.loads(r["ceza_detay"]),
            gecmis=json.loads(r["gecmis"]), sinav_atamalari=sinav, derslik_atamalari=derslik,
            gozetmen_atamalari=gozetmen, ozel_oturmalar=ozel,
            ahp_agirliklari=json.loads(r["ahp_agirliklari"]), referans=json.loads(r["referans"]),
        )

    def sil(self, calistirma_id: int) -> None:
        self.conn.execute("DELETE FROM calistirma WHERE id = ?", (calistirma_id,))


# ---------------------------------------------------------------------------------------------
# VeriDeposu: bir dönemin tüm girdisini tek işlemde kaydeder / yükler (Unit of Work benzeri)
# ---------------------------------------------------------------------------------------------

_SILME_SIRASI = (
    "ozel_oturma", "kurum_politikasi", "gozetmen_atama", "derslik_atama", "sinav_atama", "calistirma",
    "sinav_dilim_kurali",
    "derslik_musait_degil", "personel_musait_degil", "dilim", "kayit", "ogrenci_gereksinim", "ogrenci",
    "ders", "derslik", "personel", "sinav_donemi", "bolum",
)


class VeriDeposu:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.bolumler = BolumRepo(conn)
        self.donemler = DonemRepo(conn)
        self.personel = PersonelRepo(conn)
        self.dersler = DersRepo(conn)
        self.ogrenciler = OgrenciRepo(conn)
        self.kayitlar = KayitRepo(conn)
        self.derslikler = DerslikRepo(conn)
        self.dilimler = DilimRepo(conn)
        self.musaitlik = MusaitlikRepo(conn)
        self.kurallar = DilimKuraliRepo(conn)
        self.calistirmalar = CalistirmaRepo(conn)
        self.politikalar = PolitikaRepo(conn)

    # Not: `_sil` ve `_ekle` işlem açmaz/kapatmaz; işlem sınırını aşağıdaki herkese açık metotlar belirler.

    def _sil(self) -> None:
        for tablo in _SILME_SIRASI:  # yabancı anahtarlar yüzünden çocuk tablolardan başlanır
            self.conn.execute(f"DELETE FROM {tablo}")  # tablo adı sabit listeden geliyor, kullanıcıdan değil

    def _ekle(self, veri: VeriSeti) -> None:
        if veri.donem is None:
            raise ValueError("Veri setinde sınav dönemi yok")
        self.bolumler.ekle_hepsi(veri.bolumler)
        self.donemler.ekle(veri.donem)
        self.personel.ekle_hepsi(veri.personeller)
        self.dersler.ekle_hepsi(veri.dersler)
        self.ogrenciler.ekle_hepsi(veri.ogrenciler)
        self.ogrenciler.ekle_gereksinimler(veri.gereksinimler)
        self.kayitlar.ekle_hepsi(veri.kayitlar)
        self.derslikler.ekle_hepsi(veri.derslikler)
        self.dilimler.ekle_hepsi(veri.dilimler)
        self.musaitlik.ekle_personel(veri.personel_musait_degil)
        self.musaitlik.ekle_derslik(veri.derslik_musait_degil)
        self.kurallar.ekle_hepsi(veri.dilim_kurallari)
        self.politikalar.ekle_hepsi(veri.politikalar)

    def tumunu_sil(self) -> None:
        with self.conn:
            self._sil()

    def kaydet(self, veri: VeriSeti) -> None:
        """Bir veri setini tek bir işlemde kaydeder. Herhangi bir satır hatalıysa hiçbir şey yazılmaz."""
        with self.conn:
            self._ekle(veri)

    def degistir(self, veri: VeriSeti) -> None:
        """Mevcut tüm veriyi yenisiyle TEK işlemde değiştirir: yeni veri hatalıysa eski veri olduğu gibi kalır."""
        with self.conn:
            self._sil()
            self._ekle(veri)

    def yukle(self, donem_id: int) -> VeriSeti:
        donem = self.donemler.getir(donem_id)
        if donem is None:
            raise LookupError(f"{donem_id} numaralı sınav dönemi bulunamadı")
        return VeriSeti(
            donem=donem,
            bolumler=self.bolumler.hepsi(),
            personeller=self.personel.hepsi(),
            dersler=self.dersler.hepsi(),
            ogrenciler=self.ogrenciler.hepsi(),
            gereksinimler=self.ogrenciler.gereksinimler(),
            kayitlar=self.kayitlar.hepsi(),
            derslikler=self.derslikler.hepsi(),
            dilimler=self.dilimler.donem_icin(donem_id),
            personel_musait_degil=self.musaitlik.personel_donem_icin(donem_id),
            derslik_musait_degil=self.musaitlik.derslik_donem_icin(donem_id),
            dilim_kurallari=self.kurallar.donem_icin(donem_id),
            politikalar=self.politikalar.hepsi(),
        )
