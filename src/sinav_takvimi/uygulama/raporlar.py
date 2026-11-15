"""Raporlama yardımcıları: takvim ızgarası (gün × oturum), sınav listesi, kısıt raporu ve adalet özeti satırları;
bölüm/sınıf görünümü (`gorunen_sinavlar`), öğrenci ve hoca kişisel sınav programları.

Saf fonksiyonlardır (veritabanı ve arayüz bilmez); hem komut satırı hem Streamlit sayfası aynı satırları kullanır.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date

from sinav_takvimi.domain.adalet import AdaletRaporu
from sinav_takvimi.domain.cozum import Cozum
from sinav_takvimi.domain.degerlendirici import KisitSonucu
from sinav_takvimi.domain.problem import ProblemOrnegi

GUN_ADLARI = ("Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz")


@dataclass(frozen=True, slots=True)
class Izgara:
    """Gün (satır) × oturum (sütun) tablosu. `hucreler[g][o]`: o gün ve oturumdaki sınavlar (boş: oturum yok/boş)."""

    satirlar: tuple[str, ...]
    sutunlar: tuple[str, ...]
    hucreler: tuple[tuple[tuple[str, ...], ...], ...]

    def metin_tablosu(self) -> dict[str, list[str]]:
        """Tablo kitaplıklarına (ör. st.dataframe) verilebilecek {sütun: [hücre metni]} sözlüğü; ilk sütun gün."""
        sonuc: dict[str, list[str]] = {"Gün": list(self.satirlar)}
        for o, ad in enumerate(self.sutunlar):
            sonuc[ad] = [", ".join(self.hucreler[g][o]) for g in range(len(self.satirlar))]
        return sonuc


def _kucuk_harf(metin: str) -> str:
    """Türkçe küçük harf: 'I' → 'ı', 'İ' → 'i' (str.lower() bunu yanlış yapar)."""
    return metin.replace("I", "ı").replace("İ", "i").lower()


def gorunen_sinavlar(pr: ProblemOrnegi, bolum_id: int | None = None, sinif: int | None = None) -> set[int]:
    """Bölüm/sınıf takvimi için gösterilecek sınavlar (indeks e).

    Bölüm verilirse: bölümün kendi dersleri + o bölüm öğrencilerinin girdiği fakülte ortak dersleri (ör. MAT101).
    Sınıf verilirse dersin sınıfı eşleşmelidir ("END 2. sınıf takvimi"). İkisi de None ise bütün sınavlar.
    """
    sonuc: set[int] = set()
    for e, d in enumerate(pr.sinavlar):
        if sinif is not None and d.sinif != sinif:
            continue
        if bolum_id is None or d.bolum_id == bolum_id or (
            d.bolum_id is None and any(pr.ogrenciler[s].bolum_id == bolum_id for s in pr.sinav_ogrencileri[e])
        ):
            sonuc.add(e)
    return sonuc


def takvim_izgarasi(pr: ProblemOrnegi, cozum: Cozum, sinavlar: Collection[int] | None = None) -> Izgara:
    """`sinavlar` verilirse yalnızca o sınavlar yazılır (gün ve oturum satır/sütunları hep tamdır)."""
    gunler = sorted(set(pr.dilim_gun))
    siralar = sorted(set(pr.dilim_sira))
    satir_etiketi: dict[int, str] = {}
    sutun_etiketi: dict[int, str] = {}
    for dilim in pr.dilimler:
        gun_adi = GUN_ADLARI[date.fromisoformat(dilim.tarih).weekday()]
        satir_etiketi.setdefault(dilim.gun, f"{dilim.tarih} {gun_adi}")
        sutun_etiketi.setdefault(dilim.sira, f"{dilim.sira + 1}. oturum ({dilim.baslangic})")
    hucre: dict[tuple[int, int], list[str]] = {}
    for e, p in enumerate(cozum.dilim):
        if p is not None and (sinavlar is None or e in sinavlar):
            ders = pr.sinavlar[e]
            hucre.setdefault((pr.dilim_gun[p], pr.dilim_sira[p]), []).append(f"{ders.kod} ({pr.ogrenci_sayisi[e]})")
    return Izgara(
        satirlar=tuple(satir_etiketi[g] for g in gunler),
        sutunlar=tuple(sutun_etiketi[s] for s in siralar),
        hucreler=tuple(tuple(tuple(sorted(hucre.get((g, s), []))) for s in siralar) for g in gunler),
    )


def sinav_listesi(
    pr: ProblemOrnegi, cozum: Cozum, sinavlar: Collection[int] | None = None
) -> list[dict[str, object]]:
    """Her sınav için bir satır: ders, tarih, saat, öğrenci sayısı, derslikler (ayrı salon öğrencileri dahil)."""
    satirlar = []
    for e, d in enumerate(pr.sinavlar):
        if sinavlar is not None and e not in sinavlar:
            continue
        p = cozum.dilim[e]
        dilim = None if p is None else pr.dilimler[p]
        salonlar = ", ".join(
            f"{pr.derslikler[a.r].kod} ({a.ogrenci}{', ayrı salon' if a.ayri else ''})" for a in cozum.salonlari(e)
        )
        satirlar.append({
            "Ders": d.kod, "Ad": d.ad, "Öğrenci": pr.ogrenci_sayisi[e],
            "Tarih": dilim.tarih if dilim else "—", "Saat": dilim.baslangic if dilim else "—",
            "Derslikler": salonlar or "—",
        })
    return sorted(satirlar, key=lambda s: (str(s["Tarih"]), str(s["Saat"]), str(s["Ders"])))


def kisit_satirlari(rapor: list[KisitSonucu]) -> list[dict[str, object]]:
    """Kısıt raporu tablosu. Sert kısıtlarda ihlal = etkilenen kişi; yumuşakta normalize değer ve AHP katkısı."""
    return [
        {
            "Kod": s.kod, "Kısıt": s.ad, "Tür": "sert" if s.sert else ("rapor" if s.agirlik == 0 else "yumuşak"),
            "Ham ihlal": round(s.ihlal, 4), "Normalize": round(s.deger, 4),
            "Ağırlık": round(s.agirlik, 4), "Ceza": round(s.ceza, 4), "Birim": s.birim,
        }
        for s in rapor
    ]


def adalet_satirlari(a: AdaletRaporu) -> list[tuple[str, str]]:
    """Adalet özeti: çift başına kişisel ceza; Gini, Jain, değişim katsayısı ve en kötü %10."""
    return [
        ("Aktif öğrenci", str(a.ogrenci_sayisi)),
        ("Ortalama ceza (çift başına)", f"{a.ortalama:.4f}"),
        ("Medyan", f"{a.medyan:.4f}"),
        ("En kötü %10 ortalaması", f"{a.en_kotu_yuzde10_ortalamasi:.4f}"),
        ("En kötü öğrenci", f"{a.en_kotu:.4f}"),
        ("Cezasız öğrenci oranı", f"%{100 * a.cezasiz_oran:.1f}"),
        ("Gini", f"{a.gini:.4f}"),
        ("Jain indeksi (1 = eşit)", f"{a.jain:.4f}"),
        ("Değişim katsayısı", f"{a.degisim_katsayisi:.4f}"),
        ("Kohort değişim katsayısı", f"{a.kohort_degisim_katsayisi:.4f}"),
        ("S9 karesel ortalama", f"{a.karesel_ortalama:.4f}"),
        ("S10 kohort karesel", f"{a.kohort_karesel:.4f}"),
    ]


def _zaman(pr: ProblemOrnegi, cozum: Cozum, e: int) -> tuple[str, str, str]:
    """(tarih, gün adı, saat); yerleşmemişse "—"."""
    p = cozum.dilim[e]
    if p is None:
        return "—", "—", "—"
    dilim = pr.dilimler[p]
    return dilim.tarih, GUN_ADLARI[date.fromisoformat(dilim.tarih).weekday()], dilim.baslangic


def ogrenci_bul(pr: ProblemOrnegi, metin: str) -> list[int]:
    """Numarası tam eşleşen ya da adında `metin` geçen öğrencilerin indeksleri (büyük/küçük harf duyarsız)."""
    aranan = _kucuk_harf(metin.strip())
    if not aranan:
        return []
    tam = [s for s, o in enumerate(pr.ogrenciler) if o.no == metin.strip()]
    if tam:
        return tam
    return [s for s, o in enumerate(pr.ogrenciler) if aranan in _kucuk_harf(o.ad) or o.no.startswith(metin.strip())]


def ogrenci_programi(pr: ProblemOrnegi, cozum: Cozum, s: int) -> list[dict[str, object]]:
    """Bir öğrencinin kişisel sınav programı (tarih sırasıyla). Ayrı salon öğrencisi için kendi odası yazılır;
    sınav birden fazla salona bölündüyse salonların hepsi yazılır (oturma listesi kapıda ilan edilir)."""
    satirlar: list[dict[str, object]] = []
    for e in pr.ogrenci_sinavlari[s]:
        d = pr.sinavlar[e]
        tarih, gun, saat = _zaman(pr, cozum, e)
        p = cozum.dilim[e]
        ozel = [] if p is None else [r for s2, r in cozum.dagitim[p].ozel_yerlesim.get(e, ()) if s2 == s]
        if ozel:
            salon = f"{pr.derslikler[ozel[0]].kod} (ayrı salon)"
        else:
            salon = ", ".join(sorted(pr.derslikler[a.r].kod for a in cozum.salonlari(e) if not a.ayri)) or "—"
        satirlar.append({"Ders": d.kod, "Ad": d.ad, "Tarih": tarih, "Gün": gun, "Saat": saat, "Derslik": salon})
    return sorted(satirlar, key=lambda x: (str(x["Tarih"]), str(x["Saat"])))


def hoca_programi(pr: ProblemOrnegi, cozum: Cozum, personel_id: int) -> list[dict[str, object]]:
    """Bir öğretim elemanının hocası ya da asistanı olduğu derslerin sınavları (tarih sırasıyla)."""
    satirlar = []
    for e, d in enumerate(pr.sinavlar):
        rol = "Hoca" if d.hoca_id == personel_id else ("Asistan" if d.asistan_id == personel_id else None)
        if rol is None:
            continue
        tarih, gun, saat = _zaman(pr, cozum, e)
        salonlar = ", ".join(sorted(pr.derslikler[a.r].kod for a in cozum.salonlari(e))) or "—"
        satirlar.append({
            "Ders": d.kod, "Ad": d.ad, "Rol": rol, "Tarih": tarih, "Gün": gun, "Saat": saat,
            "Öğrenci": pr.ogrenci_sayisi[e], "Derslikler": salonlar,
        })
    return sorted(satirlar, key=lambda x: (str(x["Tarih"]), str(x["Saat"])))
