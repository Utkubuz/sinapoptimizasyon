"""Gerçekçi, sahte bir mühendislik fakültesi verisi üretir.

Aynı `tohum` (seed) her zaman aynı veriyi üretir. Böylece deneyler tekrarlanabilir olur.

Üretilen fakülte:
* 3 bölüm (Endüstri, Bilgisayar, Makine) × 4 sınıf, her bölüm-sınıfta ~125 öğrenci
* Fakülte ortak dersleri (Matematik I, Fizik I, Genel Kimya, İngilizce I, Diferansiyel Denklemler)
* Bölüm zorunlu dersleri ve 3./4. sınıfta seçmeli çiftler (öğrenci her çiftten birini seçer)
* Alttan ders alan öğrenciler (2. sınıf ve üstünün ~%15'i)
* Özel gereksinimli öğrenciler (~%1): tekerlekli sandalye, görme engeli, disleksi vb.
* Personel: her bölümde 2 Prof., 2 Doç., 3 Dr. Öğr. Üyesi, 6 Arş. Gör.
* Derslikler: amfiler, normal sınıflar, bilgisayar laboratuvarları, 2 toplantı odası (bazıları erişilebilir)
* 10 iş günü × 5 oturum (Cuma 13:30 hariç), akşam oturumu 90 dk
* İzinler (ardışık günler), rastgele müsaitsizlikler, tadilattaki derslik, sabit/yasak kurallar
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from sinav_takvimi.domain.modeller import (
    TUM_POLITIKALAR,
    UNVAN_KOTALARI,
    VARSAYILAN_ARDISIK_BOSLUK_DK,
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

ADLAR = (
    "Ahmet", "Mehmet", "Ayşe", "Fatma", "Zeynep", "Elif", "Mustafa", "Emre", "Can", "Deniz", "Ece", "Selin",
    "Burak", "Kerem", "Merve", "Büşra", "Yusuf", "Ömer", "Hakan", "Gizem", "Cem", "İrem", "Oğuz", "Seda",
    "Tolga", "Duygu", "Kaan", "Esra", "Barış", "Derya", "Onur", "Pınar", "Serkan", "Tuğba", "Umut", "Yasemin",
)
SOYADLAR = (
    "Yılmaz", "Kaya", "Demir", "Şahin", "Çelik", "Yıldız", "Yıldırım", "Öztürk", "Aydın", "Özdemir",
    "Arslan", "Doğan", "Kılıç", "Aslan", "Çetin", "Kara", "Koç", "Kurt", "Özkan", "Şimşek", "Polat", "Erdoğan",
)

BOLUMLER = (("END", "Endüstri Mühendisliği"), ("BIL", "Bilgisayar Mühendisliği"), ("MAK", "Makine Mühendisliği"))

# (kod, ad, sınıf, zorluk, sınav türü)
ORTAK_DERSLER = (
    ("MAT101", "Matematik I", 1, 5, "yazili"),
    ("FIZ101", "Fizik I", 1, 4, "yazili"),
    ("KIM101", "Genel Kimya", 1, 3, "yazili"),
    ("ING101", "İngilizce I", 1, 2, "yazili"),
    ("MAT201", "Diferansiyel Denklemler", 2, 5, "yazili"),
)

ZORUNLU_DERSLER = {
    "END": (
        ("END101", "Endüstri Mühendisliğine Giriş", 1, 2, "yazili"),
        ("END103", "Bilgisayar Programlama", 1, 3, "bilgisayar"),
        ("END201", "Yöneylem Araştırması I", 2, 4, "yazili"),
        ("END203", "Mühendislik Ekonomisi", 2, 3, "yazili"),
        ("END205", "Olasılık", 2, 4, "yazili"),
        ("END301", "Üretim Planlama", 3, 4, "yazili"),
        ("END303", "Kalite Kontrol", 3, 3, "yazili"),
        ("END305", "Simülasyon", 3, 4, "bilgisayar"),
        ("END307", "Ergonomi", 3, 2, "yazili"),
        ("END401", "Tedarik Zinciri Yönetimi", 4, 3, "yazili"),
        ("END403", "Proje Yönetimi", 4, 2, "yazili"),
        ("END405", "Karar Analizi", 4, 3, "yazili"),
        ("END409", "Tesis Planlama", 4, 3, "yazili"),
    ),
    "BIL": (
        ("BIL101", "Programlamaya Giriş", 1, 3, "bilgisayar"),
        ("BIL103", "Ayrık Matematik", 1, 4, "yazili"),
        ("BIL201", "Veri Yapıları", 2, 4, "bilgisayar"),
        ("BIL203", "Mantık Devreleri", 2, 3, "yazili"),
        ("BIL205", "Nesne Yönelimli Programlama", 2, 3, "bilgisayar"),
        ("BIL301", "Algoritma Analizi", 3, 5, "yazili"),
        ("BIL303", "İşletim Sistemleri", 3, 4, "yazili"),
        ("BIL305", "Veritabanı Sistemleri", 3, 3, "bilgisayar"),
        ("BIL307", "Bilgisayar Ağları", 3, 3, "yazili"),
        ("BIL401", "Yapay Zekâ", 4, 4, "yazili"),
        ("BIL403", "Yazılım Mühendisliği", 4, 2, "yazili"),
        ("BIL405", "Bilgi Güvenliği", 4, 3, "yazili"),
        ("BIL407", "Derin Öğrenme", 4, 4, "yazili"),
    ),
    "MAK": (
        ("MAK101", "Teknik Resim", 1, 2, "yazili"),
        ("MAK103", "Statik", 1, 4, "yazili"),
        ("MAK201", "Dinamik", 2, 5, "yazili"),
        ("MAK203", "Mukavemet", 2, 5, "yazili"),
        ("MAK205", "Malzeme Bilimi", 2, 3, "yazili"),
        ("MAK301", "Termodinamik", 3, 5, "yazili"),
        ("MAK303", "Akışkanlar Mekaniği", 3, 5, "yazili"),
        ("MAK305", "Makine Elemanları", 3, 4, "yazili"),
        ("MAK307", "Sayısal Yöntemler", 3, 3, "bilgisayar"),
        ("MAK401", "Isı Transferi", 4, 4, "yazili"),
        ("MAK403", "Otomotiv Mühendisliği", 4, 3, "yazili"),
        ("MAK405", "Robotik", 4, 3, "yazili"),
        ("MAK407", "Yenilenebilir Enerji", 4, 2, "yazili"),
    ),
}

# Seçmeli çiftler: öğrenci her çiftten birini seçer
SECMELI_CIFTLER = {
    "END": (
        (("END311", "Veri Madenciliği", 3, 3, "bilgisayar"), ("END313", "Lojistik Yönetimi", 3, 2, "yazili")),
        (("END411", "Optimizasyon Yazılımları", 4, 3, "bilgisayar"), ("END413", "Hizmet Sistemleri", 4, 2, "yazili")),
    ),
    "BIL": (
        (("BIL311", "Mobil Programlama", 3, 3, "bilgisayar"), ("BIL313", "Görüntü İşleme", 3, 4, "yazili")),
        (("BIL411", "Dağıtık Sistemler", 4, 4, "yazili"), ("BIL413", "Oyun Programlama", 4, 3, "bilgisayar")),
    ),
    "MAK": (
        (("MAK311", "Kompozit Malzemeler", 3, 3, "yazili"), ("MAK313", "Hidrolik Sistemler", 3, 3, "yazili")),
        (("MAK411", "Bilgisayar Destekli Tasarım", 4, 3, "bilgisayar"), ("MAK413", "Titreşim", 4, 4, "yazili")),
    ),
}

SINAV_SURESI = {1: 60, 2: 60, 3: 75, 4: 90, 5: 90}  # zorluk → dk
# Kurum politikası VARSAYIMLARI: gerçek veride kurum yönergesinden gelir; sentetik veride kaynakları "varsayım"
# Günlük en fazla gözetmenlik görevi VARSAYIMI (sentetik/öneri değeri; gerçek veride personel kaydından gelir).
GUNLUK_GOREV_VARSAYIMI: dict[str, int] = {"Prof. Dr.": 2, "Doç. Dr.": 2, "Dr. Öğr. Üyesi": 2, "Arş. Gör.": 3}
SALON_BASI_KOLTUK_VARSAYIMI = 40  # derslik.gozetmen_sayisi üretilirken: 40 sınav koltuğuna 1 gözetmen
POLITIKA_VARSAYIMLARI = (
    ("yedek_orani", 0.1, "varsayım: oturum başına ihtiyacın ~%10'u kadar yedek; kurum yönergesiyle güncellenmeli"),
    ("yedek_yuk_katsayisi", 0.5, "varsayım: yedek görev, beklemede geçtiği için yarım görev sayılır"),
    # Türk üniversite yönergelerinde yaygın kural ("bir günde en fazla iki sınav esastır")
    ("gunluk_sinav_ust_siniri", 2, "Sakarya Ü. Sınav Yönergesi; Hasan Kalyoncu Ü. Sınav Yönergesi; Çankaya Ü. Sınav "
                                   "Yönergesi (2024) — 'öğrencinin bir günde en fazla iki sınava girmesi esastır'"),
    ("gunluk_sinir_ortak_ders_haric", 1, "Sakarya Ü. Sınav Yönergesi: üniversite ortak derslerinde senato bu sayıyı "
                                          "artırabilir (basitleştirme: ortak dersler sınıra sayılmaz)"),
    ("gunluk_sinir_alttan_haric", 1, "Çankaya Ü. Sınav Yönergesi (2024): kural öğrencinin kayıtlı olduğu sınıfın "
                                      "müfredatındaki dersler için uygulanır"),
    # UniTime / Timefold zaman damgası yaklaşımı — sira numarasına değil gerçek dinlenme boşluğuna bakar
    ("ardisik_bosluk_dk", VARSAYILAN_ARDISIK_BOSLUK_DK,
     "varsayım: aynı gün iki ardışık oturum arası dinlenme ≤ 60 dk ise arka arkaya (S1), aşarsa aralıklı (S2) sayılır"),
)

OTURUMLAR = (("09:00", 120), ("11:00", 120), ("13:30", 120), ("15:30", 120), ("17:30", 90))

# Özel gereksinim profilleri: ((erişilebilir salon, ayrı salon, ek süre oranı), ağırlık)
# Ayrı salon nadirdir, sadece okutman/yazıcı gereken öğrencilere verilir; diğerleri normal salonda karşılanır.
GEREKSINIM_PROFILLERI = (
    ((True, False, 0.0), 4),    # tekerlekli sandalye: erişilebilir (zemin kat) salon
    ((True, False, 0.25), 2),   # tekerlekli sandalye + yazma güçlüğü: erişilebilir salon + ek süre
    ((False, False, 0.25), 5),  # disleksi / dikkat eksikliği: ek süre, normal salon
    ((False, True, 0.33), 1),   # görme engeli: okutman/yazıcı → ayrı salon + ayrı gözetmen + ek süre
)


@dataclass(slots=True)
class SentetikAyarlar:
    tohum: int = 42
    ogrenci_per_sinif: int = 125
    gun_sayisi: int = 10
    baslangic: date = date(2027, 1, 4)  # Pazartesi
    alttan_orani: float = 0.15
    gereksinim_orani: float = 0.01
    izin_olasiligi: float = 0.3  # personelin dönem içinde 1–2 günlük izin alma olasılığı
    rastgele_musaitsizlik: float = 0.04


def is_gunleri(baslangic: date, gun_sayisi: int) -> list[date]:
    """Başlangıçtan itibaren hafta sonu atlanarak `gun_sayisi` iş günü."""
    gunler: list[date] = []
    g = baslangic
    while len(gunler) < gun_sayisi:
        if g.weekday() < 5:  # hafta sonu yok
            gunler.append(g)
        g += timedelta(days=1)
    return gunler


def dilimleri_uret(gunler: list[date], donem_id: int = 1) -> list[Dilim]:
    """Her iş günü için OTURUMLAR; Cuma 13:30 oturumu açılmaz. Sentetik veri ve 'Temiz Dönem' aynı kuralı kullanır."""
    dilimler: list[Dilim] = []
    for gun, tarih in enumerate(gunler):
        for sira, (saat, sure) in enumerate(OTURUMLAR):
            if tarih.weekday() == 4 and saat == "13:30":  # Cuma namazı oturumu açılmaz
                continue
            dilimler.append(Dilim(len(dilimler) + 1, donem_id, gun, tarih.isoformat(), saat, sira, sure))
    return dilimler


def kurum_politikalari() -> list[KurumPolitikasi]:
    """POLITIKA_VARSAYIMLARI'ndan (kaynaklarıyla) kurum politikası kayıtları."""
    return [
        KurumPolitikasi(anahtar, deger, TUM_POLITIKALAR[anahtar][2], kaynak)
        for anahtar, deger, kaynak in POLITIKA_VARSAYIMLARI
    ]


def sentetik_veri_uret(ayar: SentetikAyarlar | None = None) -> VeriSeti:
    ayar = ayar or SentetikAyarlar()
    rng = random.Random(ayar.tohum)
    veri = VeriSeti()

    # --- Dönem ve oturumlar ---
    gunler = is_gunleri(ayar.baslangic, ayar.gun_sayisi)
    veri.donem = SinavDonemi(
        1, f"{ayar.baslangic.year - 1}-{ayar.baslangic.year} Güz Dönemi Finalleri", "final",
        gunler[0].isoformat(), gunler[-1].isoformat(),
    )
    veri.dilimler = dilimleri_uret(gunler)

    # --- Bölümler ve personel ---
    veri.bolumler = [Bolum(i + 1, kod, ad) for i, (kod, ad) in enumerate(BOLUMLER)]
    bolum_id = {b.kod: b.id for b in veri.bolumler}
    kullanilan_adlar: set[str] = set()

    def yeni_ad() -> str:
        while True:
            ad = f"{rng.choice(ADLAR)} {rng.choice(SOYADLAR)}"
            if ad not in kullanilan_adlar:
                kullanilan_adlar.add(ad)
                return ad

    ogretim_uyeleri: dict[str, list[int]] = {}
    asistanlar: dict[str, list[int]] = {}
    pid = 1
    for kod, _ in BOLUMLER:
        ogretim_uyeleri[kod], asistanlar[kod] = [], []
        for unvan, adet in (("Prof. Dr.", 2), ("Doç. Dr.", 2), ("Dr. Öğr. Üyesi", 3), ("Arş. Gör.", 6)):
            for _ in range(adet):
                gunluk = GUNLUK_GOREV_VARSAYIMI[unvan]
                veri.personeller.append(Personel(pid, yeni_ad(), unvan, bolum_id[kod], UNVAN_KOTALARI[unvan], gunluk))
                (asistanlar if unvan == "Arş. Gör." else ogretim_uyeleri)[kod].append(pid)
                pid += 1

    # --- Dersler (hocalar bölüm içinde sırayla dağıtılır, yük dengeli olsun) ---
    hoca_sirasi = {k: rng.sample(v, len(v)) for k, v in ogretim_uyeleri.items()}
    hoca_sayac = dict.fromkeys(hoca_sirasi, 0)

    def hoca_sec(bolum: str) -> int:
        h = hoca_sirasi[bolum][hoca_sayac[bolum] % len(hoca_sirasi[bolum])]
        hoca_sayac[bolum] += 1
        return h

    did = 1
    ders_kod_id: dict[str, int] = {}

    def ders_ekle(kod: str, ad: str, sinif: int, zorluk: int, tur: str, bolum: str | None, sahip: str) -> None:
        nonlocal did
        veri.dersler.append(Ders(
            did, kod, ad, bolum_id[bolum] if bolum else None, sinif, zorluk, tur, SINAV_SURESI[zorluk],
            hoca_sec(sahip), rng.choice(asistanlar[sahip]),
        ))
        ders_kod_id[kod] = did
        did += 1

    for i, (kod, ad, sinif, zorluk, tur) in enumerate(ORTAK_DERSLER):
        ders_ekle(kod, ad, sinif, zorluk, tur, None, BOLUMLER[i % 3][0])  # ortak dersin hocası sırayla bir bölümden
    for bolum, dersler in ZORUNLU_DERSLER.items():
        for kod, ad, sinif, zorluk, tur in dersler:
            ders_ekle(kod, ad, sinif, zorluk, tur, bolum, bolum)
    for bolum, ciftler in SECMELI_CIFTLER.items():
        for cift in ciftler:
            for kod, ad, sinif, zorluk, tur in cift:
                ders_ekle(kod, ad, sinif, zorluk, tur, bolum, bolum)

    # --- Öğrenciler ve kayıtlar ---
    oid = 1
    kayitlar: set[tuple[int, int]] = set()
    for b_kod, _ in BOLUMLER:
        for sinif in range(1, 5):
            zorunlu = [d[0] for d in ORTAK_DERSLER if d[2] == sinif] + [
                d[0] for d in ZORUNLU_DERSLER[b_kod] if d[2] == sinif
            ]
            onceki = [d[0] for d in ORTAK_DERSLER if d[2] < sinif] + [
                d[0] for d in ZORUNLU_DERSLER[b_kod] if d[2] < sinif
            ]
            sinif_ciftleri = [c for c in SECMELI_CIFTLER[b_kod] if c[0][2] == sinif]
            for n in range(ayar.ogrenci_per_sinif):
                yil = ayar.baslangic.year - sinif
                no = f"{yil % 100:02d}{bolum_id[b_kod]:02d}{n + 1:04d}"
                veri.ogrenciler.append(Ogrenci(oid, no, f"{rng.choice(ADLAR)} {rng.choice(SOYADLAR)}",
                                               bolum_id[b_kod], sinif))
                for kod in zorunlu:
                    kayitlar.add((oid, ders_kod_id[kod]))
                for cift in sinif_ciftleri:
                    kayitlar.add((oid, ders_kod_id[rng.choice(cift)[0]]))
                if onceki and rng.random() < ayar.alttan_orani:
                    for kod in rng.sample(onceki, k=min(len(onceki), rng.choice((1, 1, 2)))):
                        kayitlar.add((oid, ders_kod_id[kod]))
                oid += 1
    veri.kayitlar = sorted(kayitlar)

    # --- Özel gereksinimli öğrenciler ---
    adet = max(1, round(len(veri.ogrenciler) * ayar.gereksinim_orani))
    ayri_adet = max(1, round(adet * 0.15))  # ayrı salon nadir ama her veri setinde bulunsun (özellik test edilebilsin)
    normal_profiller = [p for p in GEREKSINIM_PROFILLERI if not p[0][1]]
    ayri_profil = next(p[0] for p in GEREKSINIM_PROFILLERI if p[0][1])
    for i, o in enumerate(rng.sample(veri.ogrenciler, adet)):
        if i < ayri_adet:
            eris, ayri, ek = ayri_profil
        else:
            eris, ayri, ek = rng.choices([p[0] for p in normal_profiller], weights=[p[1] for p in normal_profiller])[0]
        veri.gereksinimler.append(OgrenciGereksinim(o.id, eris, ayri, ek))
    veri.gereksinimler.sort(key=lambda x: x.ogrenci_id)

    # --- Derslikler ---
    rid = 1

    def derslik_ekle(kod: str, kap: int, sinav_kap: int, tur: str, eris: bool) -> None:
        nonlocal rid
        # Varsayım (gerçek veride kurum belirler): her 40 sınav koltuğu için 1 gözetmen, en az 1
        gozetmen = max(1, -(-sinav_kap // SALON_BASI_KOLTUK_VARSAYIMI))
        veri.derslikler.append(Derslik(rid, kod, kap, sinav_kap, tur, eris, gozetmen))
        rid += 1

    for i in range(1, 4):
        derslik_ekle(f"AMFI-{i}", 240, 120, "amfi", i == 1)
    for kat in (1, 2):
        for sira_no in range(1, 9):
            buyuk = sira_no <= 2
            erisilebilir = kat == 1 and sira_no <= 4  # zemin kattaki ilk 4 sınıf
            derslik_ekle(f"D-{kat}{sira_no:02d}", 80 if buyuk else 60, 40 if buyuk else 30, "normal", erisilebilir)
    for i in range(1, 5):
        derslik_ekle(f"LAB-{i}", 40, 40, "bilgisayar", i <= 2)  # zemin kattaki iki lab erişilebilir
    derslik_ekle("LAB-5", 30, 30, "bilgisayar", False)
    for i in (1, 2):  # bölüm toplantı odaları: ayrı salon (okutman/yazıcı) gereken öğrenciler için
        derslik_ekle(f"TOPLANTI-{i}", 8, 8, "ozel", True)

    # --- Kurum politikaları ---
    veri.politikalar = kurum_politikalari()

    # --- Müsaitsizlikler ---
    gun_dilimleri: dict[int, list[int]] = {}
    for dl in veri.dilimler:
        gun_dilimleri.setdefault(dl.gun, []).append(dl.id)
    for p in veri.personeller:
        if rng.random() < ayar.izin_olasiligi:  # 1–2 günlük izin / kongre
            bas = rng.randrange(ayar.gun_sayisi)
            for gun in range(bas, min(ayar.gun_sayisi, bas + rng.choice((1, 2)))):
                veri.personel_musait_degil.update((p.id, d) for d in gun_dilimleri[gun])
        for dl in veri.dilimler:
            if rng.random() < ayar.rastgele_musaitsizlik:
                veri.personel_musait_degil.add((p.id, dl.id))
    tadilat = next(d for d in veri.derslikler if d.kod == "D-208")
    for gun in range(3):  # D-208 ilk 3 gün tadilatta
        veri.derslik_musait_degil.update((tadilat.id, d) for d in gun_dilimleri[gun])

    # --- Sabit / yasak kurallar ---
    def ilk_dilim(gun: int, sira: int) -> int:
        return next(d.id for d in veri.dilimler if d.gun == gun and d.sira == sira)

    veri.dilim_kurallari = [
        SinavDilimKurali(ders_kod_id["MAT101"], ilk_dilim(0, 0), "zorunlu", "Fakülte kararı: ilk gün sabah"),
        SinavDilimKurali(ders_kod_id["MAT101"], ilk_dilim(0, 1), "zorunlu", "Fakülte kararı: ilk gün sabah"),
        *[
            SinavDilimKurali(ders_kod_id["BIL305"], d, "yasak", "Sunucu bakımı")
            for d in gun_dilimleri[4]
        ],
        SinavDilimKurali(ders_kod_id["END409"], ilk_dilim(ayar.gun_sayisi - 1, 4), "yasak", "Hoca talebi"),
    ]
    # zorunlu kuralın hocası o oturumlarda müsait olsun
    mat101 = next(d for d in veri.dersler if d.kod == "MAT101")
    veri.personel_musait_degil -= {(mat101.hoca_id, ilk_dilim(0, 0)), (mat101.hoca_id, ilk_dilim(0, 1))}

    return veri
