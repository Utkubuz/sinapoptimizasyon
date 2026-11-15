"""Artımlı (delta) değerlendirici: yerel arama hamlelerinde takvimin tamamını taramak yerine yalnızca değişen sınav,
dilim ve öğrencilerin ceza farkını günceller. Her delta sonucu, tam hesapla aynı olmalıdır.

Değişmez: Her tekli/çoklu sınav hamlesi (`tasi`) ve geri alma (`geri_al`) sonrasında `ceza()` ve `ihlaller()`,
tam `Degerlendirici` ile `1e-9` tolerans içinde birebir aynı sonucu vermelidir. Tam `Degerlendirici` testlerin
referans hakemi olarak korunur.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from sinav_takvimi.domain.ceza import Ceza
from sinav_takvimi.domain.cozum import Cozum, GeriAlma
from sinav_takvimi.domain.degerlendirici import YERLESMEMIS, Degerlendirici, KisitSonucu
from sinav_takvimi.domain.ogrenci_analizi import OgrenciAnalizi, hazirlik_cezasi

_STANDART_OGRENCISEL = frozenset(
    {"H11GunlukSinavSiniri", "S7GundeUcSinav", "S9OgrenciAdaleti", "S10KohortAdaleti"}
)
# Kayan nokta birikimini sıfırlamak için kabul edilen hamlelerde periyodik tam eşitleme aralığı
YENILEME_ADIMI = 2000

# (a1, a2, a3, a7, h11, p, aktif, yerlesik_adet)
type _OgrenciYedek = tuple[float, float, float, float, float, float, bool, int]


@dataclass(slots=True)
class ArtimliGeriAlma:
    """`ArtimliDegerlendirici.tasi` çağrısının yığın (stack) düzeninde geri alınmasını sağlayan anlık görüntü."""

    cozum_geri: GeriAlma
    eski_ihlal: dict[str, float]
    eski_aktif_sayisi: int
    eski_toplam_p_kare: float
    eski_toplam_a7: float
    eski_toplam_h11: float
    eski_kohort_toplam: list[float]
    eski_kohort_boyut: list[int]
    ogrenci_yedek: dict[int, _OgrenciYedek]


class ArtimliDegerlendirici:
    """Bir `Cozum` nesnesine bağlanarak hamleleri artımlı değerlendirir."""

    def __init__(self, deg: Degerlendirici, cozum: Cozum) -> None:
        if deg.problem is not cozum.problem:
            raise ValueError("Degerlendirici ve Cozum aynı ProblemOrnegi nesnesini paylaşmalıdır.")
        self.deg = deg
        self.problem = deg.problem
        self.cozum = cozum
        pr = self.problem

        gunler = sorted(set(pr.dilim_gun))
        gun_sira = {g: i for i, g in enumerate(gunler)}
        self._dilim_g: list[int] = [gun_sira[g] for g in pr.dilim_gun]
        self._G = len(gunler)

        ortak: dict[tuple[int, int], list[int]] = defaultdict(list)
        for s, sinavlar in enumerate(pr.ogrenci_sinavlari):
            for i, e in enumerate(sinavlar):
                for f in sinavlar[i + 1 :]:
                    ortak[(e, f)].append(s)
        self._ortak: dict[tuple[int, int], tuple[int, ...]] = {k: tuple(v) for k, v in ortak.items()}

        self._ters_cift: list[float] = [
            1.0 / max(1, len(sinavlar) * (len(sinavlar) - 1) // 2) for sinavlar in pr.ogrenci_sinavlari
        ]
        self._sayilan_ogrenciler: list[tuple[int, ...]] = [
            tuple(s for s in pr.sinav_ogrencileri[e] if e in pr.sinira_sayilan[s]) for e in range(pr.E)
        ]

        w = deg.konfor_agirliklari
        self._w1 = w.get("S1", 0.0)
        self._w2 = w.get("S2", 0.0)
        self._w3 = w.get("S3", 0.0)
        self._w7 = w.get("S7", 0.0)
        self._ozel_ogrencisel = [o for o in deg.ogrencisel if type(o).__name__ not in _STANDART_OGRENCISEL]

        # Öğrenci bazlı durum dizileri
        self.a1: list[float] = [0.0] * pr.S
        self.a2: list[float] = [0.0] * pr.S
        self.a3: list[float] = [0.0] * pr.S
        self.a7: list[float] = [0.0] * pr.S
        self.h11: list[float] = [0.0] * pr.S
        self.p: list[float] = [0.0] * pr.S
        self.aktif: list[bool] = [False] * pr.S
        self._yerlesik_adet: list[int] = [0] * pr.S

        self._ogr_p_adet: list[int] = [0] * (pr.S * pr.P)
        self._ogr_g_oturum: list[int] = [0] * (pr.S * self._G)
        self._sayilan_p_adet: list[int] = [0] * (pr.S * pr.P)
        self._sayilan_g_oturum: list[int] = [0] * (pr.S * self._G)

        self._aktif_sayisi = 0
        self._toplam_p_kare = 0.0
        self._toplam_a7 = 0.0
        self._toplam_h11 = 0.0
        self._kohort_toplam: list[float] = [0.0] * len(pr.kohortlar)
        self._kohort_boyut: list[int] = [0] * len(pr.kohortlar)
        self.ihlal: dict[str, float] = {}
        self._kabul_sayaci = 0

        self.senkronla()

    def senkronla(self) -> None:
        """Mevcut `cozum` üzerinden tüm iç sayaçları ve kısıt toplamlarını baştan kurar."""
        pr = self.problem
        P, G = pr.P, self._G
        self._ogr_p_adet = [0] * (pr.S * P)
        self._ogr_g_oturum = [0] * (pr.S * G)
        self._sayilan_p_adet = [0] * (pr.S * P)
        self._sayilan_g_oturum = [0] * (pr.S * G)
        self._yerlesik_adet = [0] * pr.S

        for e, pe in enumerate(self.cozum.dilim):
            if pe is None:
                continue
            g = self._dilim_g[pe]
            for s in pr.sinav_ogrencileri[e]:
                self._yerlesik_adet[s] += 1
                ip = s * P + pe
                if self._ogr_p_adet[ip] == 0:
                    self._ogr_g_oturum[s * G + g] += 1
                self._ogr_p_adet[ip] += 1
            if pr.gunluk_ust_sinir is not None:
                for s in self._sayilan_ogrenciler[e]:
                    ip = s * P + pe
                    if self._sayilan_p_adet[ip] == 0:
                        self._sayilan_g_oturum[s * G + g] += 1
                    self._sayilan_p_adet[ip] += 1

        analiz = self.deg.analiz(self.cozum)
        self.a1 = list(analiz.a1)
        self.a2 = list(analiz.a2)
        self.a3 = list(analiz.a3)
        self.a7 = list(analiz.a7)
        self.h11 = list(analiz.h11)
        self.p = list(analiz.p)
        self.aktif = list(analiz.aktif)

        self._aktif_sayisi = sum(1 for a in self.aktif if a)
        self._toplam_p_kare = sum(x * x for x, a in zip(self.p, self.aktif, strict=True) if a)
        self._toplam_a7 = sum(self.a7)
        self._toplam_h11 = sum(self.h11)
        self._kohort_toplam = [0.0] * len(pr.kohortlar)
        self._kohort_boyut = [0] * len(pr.kohortlar)
        for s in range(pr.S):
            if self.aktif[s]:
                c = pr.ogrenci_kohort[s]
                self._kohort_toplam[c] += self.p[s]
                self._kohort_boyut[c] += 1

        self.ihlal = self.deg.ihlaller(self.cozum)
        self._kabul_sayaci = 0

    def analiz(self) -> OgrenciAnalizi:
        kohort_ort = [
            max(0.0, t) / n if n else 0.0
            for t, n in zip(self._kohort_toplam, self._kohort_boyut, strict=True)
        ]
        return OgrenciAnalizi(
            list(self.a1), list(self.a2), list(self.a3), list(self.a7),
            list(self.h11), list(self.p), list(self.aktif), kohort_ort, list(self._kohort_boyut),
        )

    def ihlaller(self) -> dict[str, float]:
        return {k: (0.0 if abs(v) <= 1e-12 else v) for k, v in self.ihlal.items()}

    def rapor(self) -> list[KisitSonucu]:
        ihl = self.ihlaller()
        y = ihl[YERLESMEMIS]
        satirlar = [KisitSonucu(YERLESMEMIS, "Yerleşmemiş sınav", True, y, y, 1.0, y, "öğrenci")]
        for k in self.deg.kisitlar:
            ham = ihl[k.kod]
            if k.sert:
                satirlar.append(KisitSonucu(k.kod, k.ad, True, ham, ham, 1.0, ham, "kişi"))
            else:
                deger = ham / k.payda / self.deg.olcek(k.kod)
                satirlar.append(KisitSonucu(k.kod, k.ad, False, ham, deger, k.agirlik, k.agirlik * deger, k.birim))
        return satirlar

    def ceza(self) -> Ceza:
        ihl = self.ihlal
        sert = 0.0 if abs(ihl[YERLESMEMIS]) <= 1e-12 else ihl[YERLESMEMIS]
        yumusak = 0.0
        for k in self.deg.kisitlar:
            ham = 0.0 if abs(ihl[k.kod]) <= 1e-12 else ihl[k.kod]
            if k.sert:
                sert += ham
            elif k.agirlik:
                yumusak += k.agirlik * (ham / k.payda / self.deg.olcek(k.kod))
        return Ceza(sert, yumusak)

    def tasi(self, hamle: Mapping[int, int | None]) -> ArtimliGeriAlma:
        """Hamleyi `cozum` üzerine uygular, kısıt toplamlarını artımlı günceller ve geri alma kaydı döndürür."""
        pr = self.problem
        cozum_geri = self.cozum.tasi(hamle)
        tasinan = cozum_geri.eski_dilim
        if not tasinan:
            return ArtimliGeriAlma(
                cozum_geri, self.ihlal, self._aktif_sayisi, self._toplam_p_kare,
                self._toplam_a7, self._toplam_h11, self._kohort_toplam, self._kohort_boyut, {},
            )

        eski_ihlal = dict(self.ihlal)
        eski_aktif_sayisi = self._aktif_sayisi
        eski_toplam_p_kare = self._toplam_p_kare
        eski_toplam_a7 = self._toplam_a7
        eski_toplam_h11 = self._toplam_h11
        eski_kohort_toplam = list(self._kohort_toplam)
        eski_kohort_boyut = list(self._kohort_boyut)
        ogrenci_yedek: dict[int, _OgrenciYedek] = {}

        a1, a2, a3, a7, h11, p_dizi, aktif = self.a1, self.a2, self.a3, self.a7, self.h11, self.p, self.aktif
        yerlesik = self._yerlesik_adet
        ogrenci_kohort = pr.ogrenci_kohort

        def dokun(s: int) -> None:
            if s in ogrenci_yedek:
                return
            ogrenci_yedek[s] = (a1[s], a2[s], a3[s], a7[s], h11[s], p_dizi[s], aktif[s], yerlesik[s])
            self._toplam_a7 -= a7[s]
            self._toplam_h11 -= h11[s]
            if aktif[s]:
                ps = p_dizi[s]
                self._aktif_sayisi -= 1
                self._toplam_p_kare -= ps * ps
                c = ogrenci_kohort[s]
                self._kohort_toplam[c] -= ps
                self._kohort_boyut[c] -= 1

        ihlal = self.ihlal
        # 1. Y0 ve tekli kısıtlar (H8, H9, S4, S11)
        for e, pe_eski in tasinan.items():
            pe_yeni = self.cozum.dilim[e]
            if pe_eski is None:
                ihlal[YERLESMEMIS] -= pr.ogrenci_sayisi[e]
            else:
                for tk in self.deg.tekli:
                    ihlal[tk.kod] -= tk.ihlal(pr, e, pe_eski)
            if pe_yeni is None:
                ihlal[YERLESMEMIS] += pr.ogrenci_sayisi[e]
            else:
                for tk in self.deg.tekli:
                    ihlal[tk.kod] += tk.ihlal(pr, e, pe_yeni)

        # 2. Dilimsel kısıtlar (H2, H7, H10, S5, S6) — sadece etkilenen dilimler
        for p_idx, eski_dag in cozum_geri.eski_dagitim.items():
            yeni_dag = self.cozum.dagitim[p_idx]
            for dk in self.deg.dilimsel:
                ihlal[dk.kod] += dk.ihlal(pr, p_idx, yeni_dag) - dk.ihlal(pr, p_idx, eski_dag)

        # 3. Çift kısıtlar (H1, H4, S1, S2, S3, S8) ve öğrencinin çift konfor katkıları (a1, a2, a3)
        cift_kisitlar = self.deg.cift
        ogrencisel_var = bool(self.deg.ogrencisel)
        for e, pe_eski in tasinan.items():
            pe_yeni = self.cozum.dilim[e]
            for f in pr.komsular[e]:
                if f in tasinan and f < e:
                    continue
                pf_eski = tasinan[f] if f in tasinan else self.cozum.dilim[f]
                pf_yeni = self.cozum.dilim[f]
                if pe_eski == pe_yeni and pf_eski == pf_yeni:
                    continue
                if e < f:
                    u, v, pu_e, pv_e, pu_y, pv_y = e, f, pe_eski, pf_eski, pe_yeni, pf_yeni
                else:
                    u, v, pu_e, pv_e, pu_y, pv_y = f, e, pf_eski, pe_eski, pf_yeni, pe_yeni

                if pu_e is not None and pv_e is not None:
                    for ck in cift_kisitlar:
                        ihlal[ck.kod] -= ck.ihlal(pr, u, v, pu_e, pv_e)
                if pu_y is not None and pv_y is not None:
                    for ck in cift_kisitlar:
                        ihlal[ck.kod] += ck.ihlal(pr, u, v, pu_y, pv_y)

                if ogrencisel_var and (ortak_ogr := self._ortak.get((u, v))) is not None:
                    da1 = da2 = da3 = 0.0
                    if pu_e is not None and pv_e is not None and pu_e != pv_e:
                        if pr.ardisik(pu_e, pv_e):
                            da1 -= 1.0
                        elif pr.ayni_gun(pu_e, pv_e):
                            da2 -= 1.0
                        else:
                            da3 -= hazirlik_cezasi(pr, u, v, pu_e, pv_e)
                    if pu_y is not None and pv_y is not None and pu_y != pv_y:
                        if pr.ardisik(pu_y, pv_y):
                            da1 += 1.0
                        elif pr.ayni_gun(pu_y, pv_y):
                            da2 += 1.0
                        else:
                            da3 += hazirlik_cezasi(pr, u, v, pu_y, pv_y)
                    if da1 != 0.0 or da2 != 0.0 or da3 != 0.0:
                        for s in ortak_ogr:
                            dokun(s)
                            a1[s] += da1
                            a2[s] += da2
                            a3[s] += da3

        # 4. Öğrencisel günlük sayaçlar (a7, h11) ve aktiflik durumu
        if ogrencisel_var:
            P, G = pr.P, self._G
            ogr_p_adet = self._ogr_p_adet
            ogr_g_oturum = self._ogr_g_oturum
            sayilan_p_adet = self._sayilan_p_adet
            sayilan_g_oturum = self._sayilan_g_oturum
            ust_sinir = pr.gunluk_ust_sinir

            for e, pe_eski in tasinan.items():
                pe_yeni = self.cozum.dilim[e]
                aktiflik_degisir = pe_eski is None or pe_yeni is None
                if pe_eski is not None:
                    g_eski = self._dilim_g[pe_eski]
                    for s in pr.sinav_ogrencileri[e]:
                        if aktiflik_degisir:
                            dokun(s)
                            yerlesik[s] -= 1
                        ip = s * P + pe_eski
                        ogr_p_adet[ip] -= 1
                        if ogr_p_adet[ip] == 0:
                            ig = s * G + g_eski
                            k = ogr_g_oturum[ig]
                            ogr_g_oturum[ig] = k - 1
                            if k > 2:
                                dokun(s)
                                a7[s] -= 1.0
                    if ust_sinir is not None:
                        for s in self._sayilan_ogrenciler[e]:
                            ip = s * P + pe_eski
                            sayilan_p_adet[ip] -= 1
                            if sayilan_p_adet[ip] == 0:
                                ig = s * G + g_eski
                                k = sayilan_g_oturum[ig]
                                sayilan_g_oturum[ig] = k - 1
                                if k > ust_sinir:
                                    dokun(s)
                                    h11[s] -= 1.0

                if pe_yeni is not None:
                    g_yeni = self._dilim_g[pe_yeni]
                    for s in pr.sinav_ogrencileri[e]:
                        if aktiflik_degisir:
                            dokun(s)
                            yerlesik[s] += 1
                        ip = s * P + pe_yeni
                        if ogr_p_adet[ip] == 0:
                            ig = s * G + g_yeni
                            k = ogr_g_oturum[ig]
                            ogr_g_oturum[ig] = k + 1
                            if k >= 2:
                                dokun(s)
                                a7[s] += 1.0
                        ogr_p_adet[ip] += 1
                    if ust_sinir is not None:
                        for s in self._sayilan_ogrenciler[e]:
                            ip = s * P + pe_yeni
                            if sayilan_p_adet[ip] == 0:
                                ig = s * G + g_yeni
                                k = sayilan_g_oturum[ig]
                                sayilan_g_oturum[ig] = k + 1
                                if k >= ust_sinir:
                                    dokun(s)
                                    h11[s] += 1.0
                            sayilan_p_adet[ip] += 1

            w1, w2, w3, w7 = self._w1, self._w2, self._w3, self._w7
            ters_cift = self._ters_cift
            for s in ogrenci_yedek:
                aktif_mi = yerlesik[s] > 0
                aktif[s] = aktif_mi
                self._toplam_a7 += a7[s]
                self._toplam_h11 += h11[s]
                if aktif_mi:
                    ps = max(0.0, w1 * a1[s] + w2 * a2[s] + w3 * a3[s] + w7 * a7[s]) * ters_cift[s]
                    p_dizi[s] = ps
                    self._aktif_sayisi += 1
                    self._toplam_p_kare += ps * ps
                    c = ogrenci_kohort[s]
                    self._kohort_toplam[c] += ps
                    self._kohort_boyut[c] += 1
                else:
                    p_dizi[s] = 0.0

            if "S7" in ihlal:
                ihlal["S7"] = max(0.0, self._toplam_a7)
            if "H11" in ihlal:
                ihlal["H11"] = max(0.0, self._toplam_h11)
            if "S9" in ihlal:
                ihlal["S9"] = (
                    math.sqrt(max(0.0, self._toplam_p_kare / self._aktif_sayisi)) if self._aktif_sayisi > 0 else 0.0
                )
            if "S10" in ihlal:
                pay = payda_k = 0.0
                for t, n in zip(self._kohort_toplam, self._kohort_boyut, strict=True):
                    if n > 0:
                        m = max(0.0, t) / n
                        pay += n * m * m
                        payda_k += n
                ihlal["S10"] = math.sqrt(pay / payda_k) if payda_k > 0 else 0.0
            if self._ozel_ogrencisel:
                analiz = self.analiz()
                for o in self._ozel_ogrencisel:
                    ihlal[o.kod] = o.ihlal(pr, analiz)

        self._kabul_sayaci += 1
        return ArtimliGeriAlma(
            cozum_geri, eski_ihlal, eski_aktif_sayisi, eski_toplam_p_kare,
            eski_toplam_a7, eski_toplam_h11, eski_kohort_toplam, eski_kohort_boyut, ogrenci_yedek,
        )

    def geri_al(self, kayit: ArtimliGeriAlma) -> None:
        """Son `tasi` hamlesini yığın (stack) düzeninde tam olarak geri alır (kayan nokta kayması sıfır)."""
        tasinan = kayit.cozum_geri.eski_dilim
        if not tasinan:
            return

        pr = self.problem
        if self.deg.ogrencisel:
            P, G = pr.P, self._G
            ogr_p_adet = self._ogr_p_adet
            ogr_g_oturum = self._ogr_g_oturum
            sayilan_p_adet = self._sayilan_p_adet
            sayilan_g_oturum = self._sayilan_g_oturum
            ust_sinir = pr.gunluk_ust_sinir

            for e, pe_eski in tasinan.items():
                pe_yeni = self.cozum.dilim[e]
                if pe_yeni is not None:
                    g_yeni = self._dilim_g[pe_yeni]
                    for s in pr.sinav_ogrencileri[e]:
                        ip = s * P + pe_yeni
                        ogr_p_adet[ip] -= 1
                        if ogr_p_adet[ip] == 0:
                            ogr_g_oturum[s * G + g_yeni] -= 1
                    if ust_sinir is not None:
                        for s in self._sayilan_ogrenciler[e]:
                            ip = s * P + pe_yeni
                            sayilan_p_adet[ip] -= 1
                            if sayilan_p_adet[ip] == 0:
                                sayilan_g_oturum[s * G + g_yeni] -= 1
                if pe_eski is not None:
                    g_eski = self._dilim_g[pe_eski]
                    for s in pr.sinav_ogrencileri[e]:
                        ip = s * P + pe_eski
                        if ogr_p_adet[ip] == 0:
                            ogr_g_oturum[s * G + g_eski] += 1
                        ogr_p_adet[ip] += 1
                    if ust_sinir is not None:
                        for s in self._sayilan_ogrenciler[e]:
                            ip = s * P + pe_eski
                            if sayilan_p_adet[ip] == 0:
                                sayilan_g_oturum[s * G + g_eski] += 1
                            sayilan_p_adet[ip] += 1

        self.cozum.geri_al(kayit.cozum_geri)

        for s, (ea1, ea2, ea3, ea7, eh11, ep, eaktif, eyerlesik) in kayit.ogrenci_yedek.items():
            self.a1[s] = ea1
            self.a2[s] = ea2
            self.a3[s] = ea3
            self.a7[s] = ea7
            self.h11[s] = eh11
            self.p[s] = ep
            self.aktif[s] = eaktif
            self._yerlesik_adet[s] = eyerlesik

        self.ihlal = kayit.eski_ihlal
        self._aktif_sayisi = kayit.eski_aktif_sayisi
        self._toplam_p_kare = kayit.eski_toplam_p_kare
        self._toplam_a7 = kayit.eski_toplam_a7
        self._toplam_h11 = kayit.eski_toplam_h11
        self._kohort_toplam = kayit.eski_kohort_toplam
        self._kohort_boyut = kayit.eski_kohort_boyut
        self._kabul_sayaci = max(0, self._kabul_sayaci - 1)

    def fark(self, hamle: Mapping[int, int | None]) -> Ceza:
        """Hamle uygulanırsa ceza ne kadar değişir? Çağrı sonunda `cozum` ve iç durum değişmemiş olur."""
        once = self.ceza()
        kayit = self.tasi(hamle)
        sonra = self.ceza()
        self.geri_al(kayit)
        return sonra - once

    def periyodik_yenile_gerekirse(self, esik: int = YENILEME_ADIMI) -> None:
        """Uzun aramalarda kabul edilen hamle sayısı `esik` değerine ulaştığında kayan nokta birikimini sıfırlar."""
        if self._kabul_sayaci >= esik:
            self.senkronla()
