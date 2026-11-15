"""SQLite bağlantısı."""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def _kok_dizinler() -> tuple[Path, Path]:
    """(kaynak_koku, calisma_koku) döndürür.

    Normal çalışmada ikisi de proje köküdür. PyInstaller ile paketlenmiş `.exe` çalışırken salt-okunur paket
    dosyaları (`data/sema.sql`, `config/agirliklar.toml`) `_MEIPASS` içinden, yazılabilir veritabanı (`data/sinav.db`)
    ise `.exe` dosyasının yanındaki `data/` klasöründen okunur/yazılır.
    """
    if getattr(sys, "frozen", False):
        exe_dizini = Path(sys.executable).resolve().parent
        kaynak = Path(getattr(sys, "_MEIPASS", exe_dizini))
        return kaynak, exe_dizini
    proje = Path(__file__).resolve().parents[3]  # src/sinav_takvimi/altyapi/db.py → proje kökü (editable kurulum)
    return proje, proje


KAYNAK_KOKU, CALISMA_KOKU = _kok_dizinler()
PROJE_KOKU = CALISMA_KOKU
SEMA_DOSYASI = KAYNAK_KOKU / "data" / "sema.sql"
VARSAYILAN_DB = CALISMA_KOKU / "data" / "sinav.db"

# sema.sql her değiştiğinde 1 artırılır. Eski sürümlü bir veritabanı açılırsa anlaşılır bir hata verilir
# (CREATE TABLE IF NOT EXISTS mevcut tabloları güncellemez).
SEMA_SURUMU = 7  # v7: calistirma.ahp_agirliklari ve calistirma.referans


class SemaSurumHatasi(RuntimeError):
    pass


def baglan(yol: str | Path = VARSAYILAN_DB) -> sqlite3.Connection:
    """Veritabanını açar (yoksa oluşturur) ve şemayı uygular. Testler için yol=":memory:" verilebilir."""
    if str(yol) != ":memory:":
        Path(yol).parent.mkdir(parents=True, exist_ok=True)
    # Streamlit farklı thread'lerden erişebilir; timeout ile eşzamanlı oturumlar hata vermeden bekler.
    conn = sqlite3.connect(yol, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row  # satırlara sütun adıyla erişim: satir["kod"]
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite'ta yabancı anahtar kontrolü varsayılan olarak kapalı
    try:
        sema_olustur(conn)
    except SemaSurumHatasi:
        conn.close()
        raise
    return conn


def sema_surumu(yol: str | Path) -> int | None:
    """Dosyadaki şema sürümü (dosya yoksa None)."""
    if not Path(yol).exists():
        return None
    c = sqlite3.connect(yol)
    try:
        return int(c.execute("PRAGMA user_version").fetchone()[0])
    finally:
        c.close()


def anketleri_koruyarak_yenile(yol: str | Path) -> int:
    """Eski sürümlü veritabanını siler ve yeni şemayla oluşturur; AHP anketlerini (veriden bağımsız) taşır.

    Dönem verisi taşınmaz (şema değişmiş olabilir; sentetik veri ya da CSV ile yeniden yüklenir). Taşınan katılımcı
    sayısını döndürür.
    """
    yol = Path(yol)
    katilimcilar: list[tuple] = []
    yargilar: list[tuple] = []
    if yol.exists():
        eski = sqlite3.connect(yol)
        try:
            tablolar = {r[0] for r in eski.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if {"ahp_katilimci", "ahp_yargi"} <= tablolar:
                katilimcilar = eski.execute("SELECT id, ad, rol, tarih FROM ahp_katilimci").fetchall()
                yargilar = eski.execute("SELECT katilimci_id, matris, a, b, deger FROM ahp_yargi").fetchall()
        finally:
            eski.close()
        damga = datetime.now().strftime("%Y%m%d-%H%M%S")
        yedek = yol.with_name(f"{yol.name}.{damga}.eski")
        sira = 1
        while yedek.exists():  # aynı saniyede ikinci yenileme
            yedek = yol.with_name(f"{yol.name}.{damga}-{sira}.eski")
            sira += 1
        yol.rename(yedek)  # silmek yerine yedekle; zaman damgası önceki yedeklerin üzerine yazılmasını önler
    yeni = baglan(yol)
    try:
        with yeni:
            yeni.executemany("INSERT INTO ahp_katilimci (id, ad, rol, tarih) VALUES (?, ?, ?, ?)", katilimcilar)
            yeni.executemany(
                "INSERT INTO ahp_yargi (katilimci_id, matris, a, b, deger) VALUES (?, ?, ?, ?, ?)", yargilar
            )
    finally:
        yeni.close()
    return len(katilimcilar)


def sema_olustur(conn: sqlite3.Connection) -> None:
    surum = conn.execute("PRAGMA user_version").fetchone()[0]
    tablo_var = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0] > 0
    if tablo_var and surum != SEMA_SURUMU:
        raise SemaSurumHatasi(
            f"Veritabanı şeması eski (sürüm {surum}, beklenen {SEMA_SURUMU}). "
            "`python -m sinav_takvimi yenile` ile (AHP anketlerini koruyarak) yeniden oluşturun, "
            "ardından `veri-uret` ya da `csv-yukle` çalıştırın."
        )
    conn.executescript(SEMA_DOSYASI.read_text(encoding="utf-8"))
    conn.execute(f"PRAGMA user_version = {SEMA_SURUMU}")  # PRAGMA parametre almaz; değer koddaki sabit
