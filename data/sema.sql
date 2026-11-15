-- Sınav Takvimi veritabanı şeması (SQLite)
-- Girdi tabloları: bolum … sinav_dilim_kurali   |   Çıktı tabloları: calistirma … gozetmen_atama
PRAGMA foreign_keys = ON;

-- =====================================================================
-- GİRDİ TABLOLARI
-- =====================================================================

CREATE TABLE IF NOT EXISTS bolum (
    id   INTEGER PRIMARY KEY,
    kod  TEXT NOT NULL UNIQUE,          -- END, BIL, MAK
    ad   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sinav_donemi (
    id         INTEGER PRIMARY KEY,
    ad         TEXT NOT NULL,           -- "2026-2027 Güz Finalleri"
    tur        TEXT NOT NULL CHECK (tur IN ('vize', 'final', 'butunleme')),
    baslangic  TEXT NOT NULL,           -- YYYY-MM-DD
    bitis      TEXT NOT NULL,
    CHECK (bitis >= baslangic)
);

CREATE TABLE IF NOT EXISTS personel (
    id            INTEGER PRIMARY KEY,
    ad            TEXT    NOT NULL,
    unvan         TEXT    NOT NULL CHECK (unvan IN ('Prof. Dr.', 'Doç. Dr.', 'Dr. Öğr. Üyesi', 'Arş. Gör.')),
    bolum_id      INTEGER NOT NULL REFERENCES bolum (id),
    kota_carpani  REAL    NOT NULL CHECK (kota_carpani > 0),
    gunluk_max    INTEGER NOT NULL CHECK (gunluk_max >= 0)
);

CREATE TABLE IF NOT EXISTS ders (
    id               INTEGER PRIMARY KEY,
    kod              TEXT    NOT NULL UNIQUE,
    ad               TEXT    NOT NULL,
    bolum_id         INTEGER REFERENCES bolum (id),        -- NULL: fakülte ortak dersi
    sinif            INTEGER NOT NULL CHECK (sinif BETWEEN 1 AND 4),
    zorluk           INTEGER NOT NULL CHECK (zorluk BETWEEN 1 AND 5),
    sinav_turu       TEXT    NOT NULL CHECK (sinav_turu IN ('yazili', 'bilgisayar')),
    sinav_suresi_dk  INTEGER NOT NULL CHECK (sinav_suresi_dk > 0),
    hoca_id          INTEGER NOT NULL REFERENCES personel (id),
    asistan_id       INTEGER REFERENCES personel (id)
);

CREATE TABLE IF NOT EXISTS ogrenci (
    id        INTEGER PRIMARY KEY,
    no        TEXT    NOT NULL UNIQUE,
    ad        TEXT    NOT NULL,
    bolum_id  INTEGER NOT NULL REFERENCES bolum (id),
    sinif     INTEGER NOT NULL CHECK (sinif BETWEEN 1 AND 4)
);

-- Engelli / özel gereksinimli öğrenciler (satırı olmayan öğrencinin özel gereksinimi yok)
CREATE TABLE IF NOT EXISTS ogrenci_gereksinim (
    ogrenci_id          INTEGER PRIMARY KEY REFERENCES ogrenci (id),
    erisilebilir_salon  INTEGER NOT NULL DEFAULT 0 CHECK (erisilebilir_salon IN (0, 1)),
    ayri_salon          INTEGER NOT NULL DEFAULT 0 CHECK (ayri_salon IN (0, 1)),   -- ayrı salon + ayrı gözetmen
    ek_sure_orani       REAL    NOT NULL DEFAULT 0 CHECK (ek_sure_orani BETWEEN 0 AND 1)  -- 0.25 = %25 ek süre
);

CREATE TABLE IF NOT EXISTS kayit (
    ogrenci_id  INTEGER NOT NULL REFERENCES ogrenci (id),
    ders_id     INTEGER NOT NULL REFERENCES ders (id),
    PRIMARY KEY (ogrenci_id, ders_id)
);

CREATE TABLE IF NOT EXISTS derslik (
    id                INTEGER PRIMARY KEY,
    kod               TEXT    NOT NULL UNIQUE,
    kapasite          INTEGER NOT NULL CHECK (kapasite > 0),
    sinav_kapasitesi  INTEGER NOT NULL CHECK (sinav_kapasitesi > 0),
    tur               TEXT    NOT NULL CHECK (tur IN ('normal', 'amfi', 'bilgisayar', 'ozel')),  -- ozel: sadece ayrı salon öğrencileri
    erisilebilir      INTEGER NOT NULL DEFAULT 0 CHECK (erisilebilir IN (0, 1)),    -- engelli erişimine uygun
    gozetmen_sayisi   INTEGER NOT NULL CHECK (gozetmen_sayisi >= 1),      -- salon tam doluyken gereken
    CHECK (sinav_kapasitesi <= kapasite)
);

-- Kurum politikaları: sayısal kurallar kodda değil veride, kaynağıyla birlikte tutulur.
-- Beklenen anahtarlar: yedek_orani, yedek_yuk_katsayisi
CREATE TABLE IF NOT EXISTS kurum_politikasi (
    anahtar   TEXT PRIMARY KEY,
    deger     REAL NOT NULL,
    aciklama  TEXT NOT NULL,
    kaynak    TEXT NOT NULL      -- yönerge maddesi, kurul kararı ya da "varsayım: …"
);

CREATE TABLE IF NOT EXISTS dilim (
    id         INTEGER PRIMARY KEY,
    donem_id   INTEGER NOT NULL REFERENCES sinav_donemi (id) ON DELETE CASCADE,
    gun        INTEGER NOT NULL,          -- dönemin kaçıncı günü (0'dan başlar)
    tarih      TEXT    NOT NULL,          -- YYYY-MM-DD
    baslangic  TEXT    NOT NULL,          -- SS:DD
    sira       INTEGER NOT NULL,          -- gün içindeki oturum sırası (0'dan başlar)
    sure_dk    INTEGER NOT NULL CHECK (sure_dk > 0),
    UNIQUE (donem_id, gun, sira)
);

CREATE TABLE IF NOT EXISTS personel_musait_degil (
    personel_id  INTEGER NOT NULL REFERENCES personel (id),
    dilim_id     INTEGER NOT NULL REFERENCES dilim (id) ON DELETE CASCADE,
    PRIMARY KEY (personel_id, dilim_id)
);

CREATE TABLE IF NOT EXISTS derslik_musait_degil (
    derslik_id  INTEGER NOT NULL REFERENCES derslik (id),
    dilim_id    INTEGER NOT NULL REFERENCES dilim (id) ON DELETE CASCADE,
    PRIMARY KEY (derslik_id, dilim_id)
);

-- Sabit / yasak atamalar: "Bu sınav şu oturumda olsun (zorunlu) / olmasın (yasak)".
-- Bir dersin birden fazla 'zorunlu' satırı varsa bunlardan biri seçilir.
CREATE TABLE IF NOT EXISTS sinav_dilim_kurali (
    ders_id   INTEGER NOT NULL REFERENCES ders (id),
    dilim_id  INTEGER NOT NULL REFERENCES dilim (id) ON DELETE CASCADE,
    tur       TEXT    NOT NULL CHECK (tur IN ('zorunlu', 'yasak')),
    aciklama  TEXT,
    PRIMARY KEY (ders_id, dilim_id)
);

-- =====================================================================
-- ÇIKTI TABLOLARI (her "Takvim Oluştur" çalıştırması ayrı saklanır)
-- =====================================================================

CREATE TABLE IF NOT EXISTS calistirma (
    id             INTEGER PRIMARY KEY,
    donem_id       INTEGER NOT NULL REFERENCES sinav_donemi (id) ON DELETE CASCADE,
    zaman          TEXT    NOT NULL,
    algoritma      TEXT    NOT NULL,
    parametreler   TEXT    NOT NULL,      -- JSON
    sert_ihlal     INTEGER NOT NULL,
    toplam_ceza    REAL    NOT NULL,
    gozetmen_ceza  REAL    NOT NULL,
    sure_sn        REAL    NOT NULL,
    ceza_detay     TEXT    NOT NULL,      -- JSON: kısıt kodu → ihlal
    gecmis         TEXT    NOT NULL,      -- JSON: ceza düşüş eğrisi (yapıcıda: [adım, sert, yumuşak])
    -- v7: bir çalıştırmanın kendi kendine yeterli olması için, o anki AHP ağırlıkları ve ölçek referansı kaydedilir.
    -- Böylece anket sonradan değişse bile eski çalıştırma AYNI cezayla yeniden hesaplanabilir.
    ahp_agirliklari TEXT   NOT NULL,      -- JSON: AhpSonucu (ust, gruplar, kuresel, roller)
    referans        TEXT   NOT NULL       -- JSON: {"olcek": {kriter: ölçek}, "kaynak": {kriter: kaynak}}
);

CREATE TABLE IF NOT EXISTS sinav_atama (
    calistirma_id  INTEGER NOT NULL REFERENCES calistirma (id) ON DELETE CASCADE,
    ders_id        INTEGER NOT NULL REFERENCES ders (id),
    dilim_id       INTEGER NOT NULL REFERENCES dilim (id),
    PRIMARY KEY (calistirma_id, ders_id)
);

CREATE TABLE IF NOT EXISTS derslik_atama (
    calistirma_id   INTEGER NOT NULL REFERENCES calistirma (id) ON DELETE CASCADE,
    ders_id         INTEGER NOT NULL REFERENCES ders (id),
    derslik_id      INTEGER NOT NULL REFERENCES derslik (id),
    ogrenci_sayisi  INTEGER NOT NULL CHECK (ogrenci_sayisi > 0),
    ayri_salon      INTEGER NOT NULL DEFAULT 0 CHECK (ayri_salon IN (0, 1)),  -- özel gereksinimli öğrenci salonu
    PRIMARY KEY (calistirma_id, ders_id, derslik_id)
);

-- Özel gereksinimli öğrencilerin oturduğu salon ("kim nerede" raporu için)
CREATE TABLE IF NOT EXISTS ozel_oturma (
    calistirma_id  INTEGER NOT NULL REFERENCES calistirma (id) ON DELETE CASCADE,
    ogrenci_id     INTEGER NOT NULL REFERENCES ogrenci (id),
    ders_id        INTEGER NOT NULL REFERENCES ders (id),
    derslik_id     INTEGER NOT NULL REFERENCES derslik (id),
    PRIMARY KEY (calistirma_id, ogrenci_id, ders_id)
);

CREATE TABLE IF NOT EXISTS gozetmen_atama (
    id             INTEGER PRIMARY KEY,
    calistirma_id  INTEGER NOT NULL REFERENCES calistirma (id) ON DELETE CASCADE,
    dilim_id       INTEGER NOT NULL REFERENCES dilim (id),
    ders_id        INTEGER REFERENCES ders (id),        -- yedek gözetmende NULL
    derslik_id     INTEGER REFERENCES derslik (id),     -- yedek gözetmende NULL
    personel_id    INTEGER NOT NULL REFERENCES personel (id),
    rol            TEXT    NOT NULL CHECK (rol IN ('sorumlu', 'gozetmen', 'yedek')),
    CHECK (rol = 'yedek' OR (ders_id IS NOT NULL AND derslik_id IS NOT NULL)),
    UNIQUE (calistirma_id, dilim_id, personel_id)        -- G1: kimse aynı anda iki yerde olamaz
);

CREATE INDEX IF NOT EXISTS ix_kayit_ders ON kayit (ders_id);
CREATE INDEX IF NOT EXISTS ix_dilim_donem ON dilim (donem_id);

-- =====================================================================
-- AHP ANKETİ: kriter ağırlıkları paydaş yargılarından hesaplanır.
-- Dönem verisinden bağımsızdır; veri yeniden üretilince silinmez.
-- =====================================================================

CREATE TABLE IF NOT EXISTS ahp_katilimci (
    id     INTEGER PRIMARY KEY,
    ad     TEXT NOT NULL,
    rol    TEXT NOT NULL CHECK (rol IN ('ogrenci', 'ogretim_elemani', 'idari')),
    tarih  TEXT NOT NULL
);

-- deger: "a, b'ye göre ne kadar önemli?" (Saaty ölçeği 1/9 … 9). matris: 'ust' ya da grup adı.
CREATE TABLE IF NOT EXISTS ahp_yargi (
    katilimci_id  INTEGER NOT NULL REFERENCES ahp_katilimci (id) ON DELETE CASCADE,
    matris        TEXT    NOT NULL,
    a             TEXT    NOT NULL,
    b             TEXT    NOT NULL,
    deger         REAL    NOT NULL CHECK (deger >= 1.0 / 9 - 1e-9 AND deger <= 9 + 1e-9),
    PRIMARY KEY (katilimci_id, matris, a, b)
);
