"""ProblemOrnegi: girdi verisinin algoritmalar için hızlı erişilebilir, indekslenmiş hâli.

Veritabanı kimlikleri (id) yerine 0'dan başlayan indeksler kullanılır:
    e → sınav, p → dilim (oturum), r → derslik, k → personel, s → öğrenci, c → kohort (bölüm-sınıf).
Algoritmalar dict yerine list ile çalışır, bu yüzden çok daha hızlıdır. Bu sınıf bir kez kurulur ve sonra değişmez.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sinav_takvimi.domain.modeller import (
    OZEL_DERSLIK_TURU,
    UYGUN_DERSLIK_TURLERI,
    VARSAYILAN_ARDISIK_BOSLUK_DK,
    Ders,
    Derslik,
    Dilim,
    OgrenciGereksinim,
    Personel,
    VeriSeti,
    gereken_sure,
)


def _dakika(saat: str) -> int:
    s, d = saat.split(":")
    return int(s) * 60 + int(d)


@dataclass(frozen=True, slots=True)
class OzelOgrenci:
    """Bir sınavdaki özel gereksinimli öğrenci (indeksli)."""

    s: int
    erisilebilir: bool
    ayri_salon: bool


class ProblemOrnegi:
    def __init__(self, veri: VeriSeti) -> None:
        self.veri = veri

        # --- Öğrenciler ve kohortlar (bölüm-sınıf grupları; adalet için) ---
        self.ogrenciler = list(veri.ogrenciler)
        self.S = len(self.ogrenciler)
        self.ogrenci_indeks: dict[int, int] = {o.id: s for s, o in enumerate(self.ogrenciler)}
        kohort_anahtar = sorted({(o.bolum_id, o.sinif) for o in self.ogrenciler})
        self.kohortlar: list[tuple[int, int]] = kohort_anahtar
        kohort_indeks = {k: c for c, k in enumerate(kohort_anahtar)}
        self.ogrenci_kohort: list[int] = [kohort_indeks[(o.bolum_id, o.sinif)] for o in self.ogrenciler]

        # --- Sınavlar: en az bir öğrencisi olan dersler (id sırasıyla; tekrarlanabilirlik) ---
        ders_ogrencileri: dict[int, list[int]] = defaultdict(list)
        for ogrenci_id, ders_id in veri.kayitlar:
            ders_ogrencileri[ders_id].append(self.ogrenci_indeks[ogrenci_id])
        self.sinavlar: list[Ders] = sorted((d for d in veri.dersler if ders_ogrencileri.get(d.id)), key=lambda d: d.id)
        self.E = len(self.sinavlar)
        self.sinav_indeks: dict[int, int] = {d.id: e for e, d in enumerate(self.sinavlar)}
        self.sinav_ogrencileri: list[list[int]] = [sorted(ders_ogrencileri[d.id]) for d in self.sinavlar]
        self.ogrenci_sayisi: list[int] = [len(x) for x in self.sinav_ogrencileri]
        self.ogrenci_sinavlari: list[list[int]] = [[] for _ in range(self.S)]
        for e, ogr in enumerate(self.sinav_ogrencileri):
            for s in ogr:
                self.ogrenci_sinavlari[s].append(e)

        # --- Dilimler (gün, sıra sırasıyla) ---
        self.dilimler: list[Dilim] = sorted(veri.dilimler, key=lambda d: (d.gun, d.sira))
        self.P = len(self.dilimler)
        self.dilim_indeks: dict[int, int] = {d.id: p for p, d in enumerate(self.dilimler)}
        self.dilim_gun: list[int] = [d.gun for d in self.dilimler]
        self.dilim_takvim_gunu: list[int] = [date.fromisoformat(d.tarih).toordinal() for d in self.dilimler]
        self.dilim_sira: list[int] = [d.sira for d in self.dilimler]
        self.dilim_sure: list[int] = [d.sure_dk for d in self.dilimler]
        self.son_gun: int = max(self.dilim_gun, default=0)

        # Ardışıklık matrisi: aynı gündeki kronolojik komşu iki oturum arasındaki gerçek dinlenme boşluğu
        # `ardisik_bosluk_dk` (varsayılan 60 dk) eşiğini aşmıyorsa S1 (arka arkaya), aşıyorsa S2 sayılır.
        self.ardisik_bosluk_dk: float = veri.politika("ardisik_bosluk_dk", VARSAYILAN_ARDISIK_BOSLUK_DK)
        ardisik_matris = [[False] * self.P for _ in range(self.P)]
        gun_dilimleri: dict[int, list[int]] = defaultdict(list)
        for p in range(self.P):
            gun_dilimleri[self.dilim_gun[p]].append(p)
        for p_listesi in gun_dilimleri.values():
            p_listesi.sort(key=lambda p: (_dakika(self.dilimler[p].baslangic), self.dilim_sira[p], p))
            for a, b in zip(p_listesi, p_listesi[1:], strict=False):
                bitis_a = _dakika(self.dilimler[a].baslangic) + self.dilim_sure[a]
                bosluk = _dakika(self.dilimler[b].baslangic) - bitis_a
                if bosluk <= self.ardisik_bosluk_dk + 1e-9:
                    ardisik_matris[a][b] = ardisik_matris[b][a] = True
        self._ardisik: tuple[tuple[bool, ...], ...] = tuple(tuple(satir) for satir in ardisik_matris)

        # --- Derslikler ---
        self.derslikler: list[Derslik] = sorted(veri.derslikler, key=lambda d: d.id)
        self.R = len(self.derslikler)
        self.derslik_indeks: dict[int, int] = {d.id: r for r, d in enumerate(self.derslikler)}
        self.derslik_kapasite: list[int] = [d.sinav_kapasitesi for d in self.derslikler]
        self.derslik_erisilebilir: list[bool] = [d.erisilebilir for d in self.derslikler]
        self.derslik_gozetmen: list[int] = [d.gozetmen_sayisi for d in self.derslikler]
        self.derslik_musait: list[list[bool]] = [
            [(d.id, dl.id) not in veri.derslik_musait_degil for dl in self.dilimler] for d in self.derslikler
        ]
        # Ayrı salon öğrencileri için özel odalar, küçükten büyüğe
        self.ozel_derslikler: list[int] = sorted(
            (r for r, d in enumerate(self.derslikler) if d.tur == OZEL_DERSLIK_TURU),
            key=lambda r: self.derslik_kapasite[r],
        )

        # --- Personel ---
        self.personeller: list[Personel] = sorted(veri.personeller, key=lambda p: p.id)
        self.K = len(self.personeller)
        self.personel_indeks: dict[int, int] = {p.id: k for k, p in enumerate(self.personeller)}
        self.personel_musait: list[list[bool]] = [
            [(p.id, dl.id) not in veri.personel_musait_degil for dl in self.dilimler] for p in self.personeller
        ]
        self.musait_personel_sayisi: list[int] = [
            sum(1 for k in range(self.K) if self.personel_musait[k][p] and self.personeller[k].gunluk_max > 0)
            for p in range(self.P)
        ]

        # --- Kurum politikaları (veriden) ---
        self.yedek_orani: float = veri.politika("yedek_orani")
        self.yedek_yuk_katsayisi: float = veri.politika("yedek_yuk_katsayisi")

        # --- Günlük sınav üst sınırı (H11, isteğe bağlı kurum politikası) ---
        self.gunluk_ust_sinir: int | None = (
            int(veri.politika("gunluk_sinav_ust_siniri")) if veri.politika_var_mi("gunluk_sinav_ust_siniri") else None
        )
        ortak_haric = veri.politika("gunluk_sinir_ortak_ders_haric", 0.0) >= 0.5
        alttan_haric = veri.politika("gunluk_sinir_alttan_haric", 0.0) >= 0.5

        def sinira_sayilir(s: int, e: int) -> bool:
            d = self.sinavlar[e]
            if ortak_haric and d.bolum_id is None:
                return False
            return not (alttan_haric and d.sinif < self.ogrenciler[s].sinif)

        self.sinira_sayilan: list[frozenset[int]] = [
            frozenset(e for e in self.ogrenci_sinavlari[s] if sinira_sayilir(s, e)) for s in range(self.S)
        ]

        # --- Özel gereksinimler ve gereken süre (H8, H10) ---
        gereksinim: dict[int, OgrenciGereksinim] = {g.ogrenci_id: g for g in veri.gereksinimler}
        self.ozel_ogrenciler: list[tuple[OzelOgrenci, ...]] = []
        self.gereken_sure: list[int] = []
        for e, d in enumerate(self.sinavlar):
            ozel: list[OzelOgrenci] = []
            en_buyuk_oran = 0.0
            for s in self.sinav_ogrencileri[e]:
                g = gereksinim.get(self.ogrenciler[s].id)
                if g is None:
                    continue
                en_buyuk_oran = max(en_buyuk_oran, g.ek_sure_orani)
                if g.erisilebilir_salon or g.ayri_salon:
                    ozel.append(OzelOgrenci(s, g.erisilebilir_salon, g.ayri_salon))
            self.ozel_ogrenciler.append(tuple(ozel))
            self.gereken_sure.append(gereken_sure(d.sinav_suresi_dk, en_buyuk_oran))
        self.ayri_sayisi: list[int] = [sum(1 for o in x if o.ayri_salon) for x in self.ozel_ogrenciler]
        self.ana_grup_erisilebilir: list[bool] = [
            any(o.erisilebilir and not o.ayri_salon for o in x) for x in self.ozel_ogrenciler
        ]

        # --- Çakışma matrisi: iki sınavın ortak öğrenci sayısı (seyrek: sadece > 0 olanlar) ---
        cakisma: list[dict[int, int]] = [defaultdict(int) for _ in range(self.E)]
        for sinavlar in self.ogrenci_sinavlari:
            for i, e in enumerate(sinavlar):
                for f in sinavlar[i + 1 :]:
                    cakisma[e][f] += 1
                    cakisma[f][e] += 1
        self.cakisma: list[dict[int, int]] = [dict(c) for c in cakisma]

        # --- Aynı hocanın sınavları (H4) ---
        hoca_sinavlari: dict[int, list[int]] = defaultdict(list)
        for e, d in enumerate(self.sinavlar):
            hoca_sinavlari[d.hoca_id].append(e)
        self.hoca_komsu: list[frozenset[int]] = [
            frozenset(f for f in hoca_sinavlari[d.hoca_id] if f != e) for e, d in enumerate(self.sinavlar)
        ]
        # Komşular: bir sınav taşınınca çift kısıtları etkilenebilecek diğer sınavlar
        self.komsular: list[tuple[int, ...]] = [
            tuple(sorted(set(self.cakisma[e]) | self.hoca_komsu[e])) for e in range(self.E)
        ]

        # --- Sabit / yasak kurallar (H9) ---
        self.zorunlu_dilimler: list[frozenset[int]] = [frozenset() for _ in range(self.E)]
        self.yasak_dilimler: list[frozenset[int]] = [frozenset() for _ in range(self.E)]
        zorunlu: dict[int, set[int]] = defaultdict(set)
        yasak: dict[int, set[int]] = defaultdict(set)
        for kural in veri.dilim_kurallari:
            if kural.ders_id in self.sinav_indeks and kural.dilim_id in self.dilim_indeks:
                hedef = zorunlu if kural.tur == "zorunlu" else yasak
                hedef[self.sinav_indeks[kural.ders_id]].add(self.dilim_indeks[kural.dilim_id])
        for e in range(self.E):
            self.zorunlu_dilimler[e] = frozenset(zorunlu[e])
            self.yasak_dilimler[e] = frozenset(yasak[e])

        # --- Hoca müsaitliği (S11, yumuşak) ---
        self.hoca_musait: list[list[bool]] = []
        for d in self.sinavlar:
            k = self.personel_indeks.get(d.hoca_id)
            self.hoca_musait.append([True] * self.P if k is None else list(self.personel_musait[k]))

        # --- Alan kısıtları: H8 + H9'u birlikte sağlayan dilimler. Çözücüler sadece bunlardan seçer. ---
        # (Hoca müsaitliği yumuşak kriterdir; bu listeyi daraltmaz.)
        self.uygun_dilimler: list[tuple[int, ...]] = []
        self.uygun_dilimi_yok: list[bool] = []  # veri gereği hiçbir dilim uygun değilse (bkz. veri_kontrol uyarısı)
        for e in range(self.E):
            uygun = tuple(p for p in range(self.P) if self.dilim_uygun_mu(e, p))
            self.uygun_dilimi_yok.append(not uygun)
            self.uygun_dilimler.append(uygun or tuple(range(self.P)))

        # --- Sınav türüne uygun derslikler (H6), kapasiteye göre artan ---
        self.uygun_derslikler: list[tuple[int, ...]] = [
            tuple(sorted(
                (r for r, dr in enumerate(self.derslikler) if dr.tur in UYGUN_DERSLIK_TURLERI[d.sinav_turu]),
                key=lambda r: (self.derslik_kapasite[r], r),
            ))
            for d in self.sinavlar
        ]

        # Dersin kendi personeli (G6): hoca ve asistan indeksleri
        self.ders_personeli: list[frozenset[int]] = [
            frozenset(
                self.personel_indeks[pid]
                for pid in (d.hoca_id, d.asistan_id)
                if pid is not None and pid in self.personel_indeks
            )
            for d in self.sinavlar
        ]

        # --- Yumuşak kriterlerin normalizasyon paydaları için sabitler ---
        self.zorluk: list[int] = [d.zorluk for d in self.sinavlar]
        self.aktif_ogrenci_sayisi: int = sum(1 for x in self.ogrenci_sinavlari if x)  # en az bir sınavı olan
        self.toplam_ortak: int = sum(n for e in range(self.E) for f, n in self.cakisma[e].items() if f > e)
        self.toplam_ogrenci: int = sum(self.ogrenci_sayisi)  # Σ sınav başına öğrenci (oturacak kişi)
        self.en_buyuk_sinav: int = max(self.ogrenci_sayisi, default=0)

    # --- Kurallar ---
    def dilim_sure_yeterli(self, e: int, p: int) -> bool:  # H8
        return self.dilim_sure[p] >= self.gereken_sure[e]

    def dilim_kurala_uygun(self, e: int, p: int) -> bool:  # H9
        if p in self.yasak_dilimler[e]:
            return False
        return not self.zorunlu_dilimler[e] or p in self.zorunlu_dilimler[e]

    def dilim_uygun_mu(self, e: int, p: int) -> bool:  # H8 + H9 (sert alan kısıtları)
        return self.dilim_sure_yeterli(e, p) and self.dilim_kurala_uygun(e, p)

    # --- Dilimler arası ilişkiler ---
    def ayni_gun(self, p: int, q: int) -> bool:
        return self.dilim_gun[p] == self.dilim_gun[q]

    def ardisik(self, p: int, q: int) -> bool:
        return self._ardisik[p][q]

    def gun_farki(self, p: int, q: int) -> int:
        return abs(self.dilim_takvim_gunu[p] - self.dilim_takvim_gunu[q])

    def derslik_gozetmen_ihtiyaci(self, r: int, yerlesen: int) -> int:
        """Bir salonun gözetmen ihtiyacı: max(1, ⌈salonun gözetmen sayısı × yerleşen ÷ sınav kapasitesi⌉)."""
        g, kap = self.derslik_gozetmen[r], self.derslik_kapasite[r]
        return max(1, -(-g * yerlesen // kap))  # tam sayı tavan bölmesi (kayan nokta hatası olmaz)
