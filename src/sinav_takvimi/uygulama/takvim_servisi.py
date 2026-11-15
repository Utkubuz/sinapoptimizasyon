"""Takvim servisi: yükle → çöz → doğrula → kaydet (ve kayıttan geri yükle). Arayüz ve komut satırı bu sınıfı çağırır.

Katman kuralları: domain/çözücü veritabanı bilmez; SQL repolar.py'dedir; bu servis sadece orkestrasyon yapar.
Her servis nesnesi KENDİ bağlantısıyla çalışır: Streamlit'te oturum başına ayrı bağlantı kullanılır.

Referans değişmezi: Hangi algoritma seçilirse seçilsin (`yapici`, `tavlama`, `tabu`) önce DSatur
yapıcı çözücü çalışır ve onun tam takvimi `referans` ölçeğini sabitler. Böylece tüm algoritmalar birebir aynı cetvelle
değerlendirilir ve karşılaştırılır.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sinav_takvimi.altyapi.ayar_okuyucu import ayarlari_yukle
from sinav_takvimi.altyapi.db import VARSAYILAN_DB, SemaSurumHatasi, baglan
from sinav_takvimi.altyapi.repolar import VeriDeposu
from sinav_takvimi.cozuculer.tabu import ALGORITMA_TABU, tabu_coz
from sinav_takvimi.cozuculer.tavlama import ALGORITMA_TAVLAMA, tavlama_coz
from sinav_takvimi.cozuculer.yapici import YapiciSonuc, Yerlesmeyen, yapici_coz
from sinav_takvimi.domain.adalet import AdaletRaporu, adalet_raporu
from sinav_takvimi.domain.ahp import AhpSonucu, ahp_sozlukten
from sinav_takvimi.domain.ayarlar import Ayarlar
from sinav_takvimi.domain.ceza import TOLERANS, Ceza
from sinav_takvimi.domain.cozum import Cozum
from sinav_takvimi.domain.degerlendirici import REFERANS_RASTGELE_ORNEK, Degerlendirici, KisitSonucu
from sinav_takvimi.domain.dogrulayici import DogrulamaRaporu, dogrula
from sinav_takvimi.domain.modeller import SinavDonemi
from sinav_takvimi.domain.problem import ProblemOrnegi
from sinav_takvimi.domain.veri_kontrol import veri_kontrol
from sinav_takvimi.uygulama.agirlik_servisi import AgirlikServisi
from sinav_takvimi.uygulama.kayit_donusturucu import KayitHatasi, cozum_olustur, kayit_olustur
from sinav_takvimi.uygulama.veri_servisi import VeriHatasi

ALGORITMA_YAPICI = "yapici"
ALGORITMA_KARSILASTIR = "karsilastir"
GECERLI_ALGORITMALAR = (ALGORITMA_YAPICI, ALGORITMA_TAVLAMA, ALGORITMA_TABU)
ALGORITMA_ADLAR: dict[str, str] = {
    ALGORITMA_YAPICI: "Yapıcı (DSatur)",
    ALGORITMA_TAVLAMA: "Benzetimli Tavlama",
    ALGORITMA_TABU: "Tabu Arama",
}
VARSAYILAN_ALGORITMA = ALGORITMA_TABU
_YAPISAL_KODLAR = frozenset({"H6", "SC", "SK", "SM"})  # doğrulayıcının ek denetlediği yapısal salon kuralları
_CR_UYARISI = "AHP anketlerinde tutarlılık oranı (CR) 0,10'dan büyük bir matris var (`agirliklar` komutu)"


def veritabani_baglantisi(yol: str | Path = VARSAYILAN_DB) -> sqlite3.Connection:
    """Yeni bir veritabanı bağlantısı açar (arayüz katmanı altyapıyı doğrudan import etmesin diye burada sunulur)."""
    return baglan(yol)


class TakvimUretilemedi(Exception):
    """Bazı sınavlar sert ihlal olmadan yerleştirilemedi. Hiçbir şey kaydedilmez; `yerlesmeyenler` kullanıcıya
    gösterilir. `sonuc`: o ana kadar kurulan (eksik) takvim; `problem`: indeksleri çözmek için."""

    def __init__(self, yerlesmeyenler: list[Yerlesmeyen], sonuc: YapiciSonuc, problem: ProblemOrnegi) -> None:
        kodlar = ", ".join(y.ders_kod for y in yerlesmeyenler)
        super().__init__(f"{len(yerlesmeyenler)} sınav sert ihlal olmadan yerleştirilemedi: {kodlar}")
        self.yerlesmeyenler = yerlesmeyenler
        self.sonuc = sonuc
        self.problem = problem


class IcTutarsizlik(RuntimeError):
    """Değerlendirici ile bağımsız doğrulayıcı aynı sonucu vermiyor ya da çözücü sert ihlalli takvim üretti. Bu bir
    programlama hatasıdır (değişmez bozuldu), kullanıcı hatası değildir; sessizce geçilmez."""


@dataclass(slots=True)
class TakvimSonucu:
    problem: ProblemOrnegi
    cozum: Cozum
    degerlendirici: Degerlendirici
    ceza: Ceza
    kisit_raporu: list[KisitSonucu]
    dogrulama: DogrulamaRaporu
    adalet: AdaletRaporu
    ahp: AhpSonucu
    referans: dict[str, float]
    referans_kaynagi: dict[str, str]
    algoritma: str
    zaman: str
    sure_sn: float
    gecmis: list[list[float]] = field(default_factory=list)
    kayit_id: int | None = None
    uyarilar: list[str] = field(default_factory=list)
    baslangic_ceza: Ceza | None = None
    parametreler: dict[str, Any] = field(default_factory=dict)

    @property
    def iyilesme_orani(self) -> float | None:
        """Yapıcı başlangıç cezasına göre bağıl iyileşme oranı (yapıcı çalışmada None)."""
        if self.baslangic_ceza is None:
            return None
        if self.baslangic_ceza.yumusak <= 1e-12:
            return 0.0
        return (self.baslangic_ceza.yumusak - self.ceza.yumusak) / self.baslangic_ceza.yumusak


class TakvimServisi:
    def __init__(self, conn: sqlite3.Connection, ayarlar: Ayarlar | None = None) -> None:
        self.conn = conn
        self.depo = VeriDeposu(conn)
        self.agirlik = AgirlikServisi(conn)
        self.ayarlar = ayarlar if ayarlar is not None else ayarlari_yukle()

    # --- veri ---
    def donemler(self) -> list[SinavDonemi]:
        return self.depo.donemler.hepsi()

    def varsayilan_donem(self) -> int:
        donemler = self.donemler()
        if not donemler:
            raise LookupError("Veritabanında dönem yok. Önce `veri-uret` ya da `csv-yukle` çalıştırın.")
        return donemler[0].id  # DonemRepo.hepsi başlangıca göre yeniden eskiye sıralı → en güncel dönem

    def veri_ozeti(self, donem_id: int | None = None) -> dict[str, int]:
        return self.depo.yukle(donem_id if donem_id is not None else self.varsayilan_donem()).ozet()

    def calistirmalar(self, donem_id: int | None = None) -> list[dict[str, Any]]:
        return self.depo.calistirmalar.listele(donem_id if donem_id is not None else self.varsayilan_donem())

    # --- çöz ---
    def olustur(
        self,
        donem_id: int | None = None,
        tohum: int = 0,
        algoritma: str = VARSAYILAN_ALGORITMA,
        sure_sn: float | None = None,
    ) -> TakvimSonucu:
        """Yükle → AHP ağırlıkları → yapıcı (referans) → seçili iyileştirici → doğrula → kaydet.

        Yerleşmeyen sınav varsa `TakvimUretilemedi` (kayıt yapılmaz, referans belirlenmez).
        Değerlendirici ile doğrulayıcı uyuşmazsa ya da sert ihlal oluşursa `IcTutarsizlik`.
        """
        if algoritma not in GECERLI_ALGORITMALAR:
            raise ValueError(f"Geçersiz algoritma '{algoritma}'. Seçenekler: {', '.join(GECERLI_ALGORITMALAR)}")

        baslangic = time.perf_counter()
        pr, deg, ahp, referans, yapici, bas_ceza, veri_uyarilari, yapici_sure = self._hazirla_ve_yapici_coz(
            donem_id, tohum
        )
        return self._calistir_ve_kaydet(
            pr=pr, deg=deg, ahp=ahp, referans=referans, yapici=yapici, baslangic_ceza=bas_ceza,
            veri_uyarilari=veri_uyarilari, algoritma=algoritma, sure_sn=sure_sn, tohum=tohum,
            ek_sure_sn=yapici_sure if algoritma != ALGORITMA_YAPICI else (time.perf_counter() - baslangic),
        )

    def karsilastir(
        self,
        donem_id: int | None = None,
        tohum: int = 0,
        sure_sn: float | None = None,
    ) -> list[TakvimSonucu]:
        """Yapıcı, Benzetimli Tavlama ve Tabu Arama'yı aynı referans ölçeğinde çalıştırıp kaydeder."""
        pr, deg, ahp, referans, yapici, bas_ceza, veri_uyarilari, yapici_sure = self._hazirla_ve_yapici_coz(
            donem_id, tohum
        )
        sonuclar: list[TakvimSonucu] = []
        for alg in GECERLI_ALGORITMALAR:
            sonuclar.append(
                self._calistir_ve_kaydet(
                    pr=pr, deg=deg, ahp=ahp, referans=referans, yapici=yapici, baslangic_ceza=bas_ceza,
                    veri_uyarilari=veri_uyarilari, algoritma=alg, sure_sn=sure_sn, tohum=tohum,
                    ek_sure_sn=yapici_sure,
                )
            )
        return sonuclar

    def _hazirla_ve_yapici_coz(
        self, donem_id: int | None, tohum: int
    ) -> tuple[ProblemOrnegi, Degerlendirici, AhpSonucu, dict[str, float], YapiciSonuc, Ceza, list[str], float]:
        t0 = time.perf_counter()
        donem_id = donem_id if donem_id is not None else self.varsayilan_donem()
        veri = self.depo.yukle(donem_id)
        hatalar, veri_uyarilari = veri_kontrol(veri)
        if hatalar:
            raise VeriHatasi(hatalar)
        ahp = self.agirlik.hesapla()
        pr = ProblemOrnegi(veri)
        deg = Degerlendirici(pr, ahp=ahp)

        yapici = yapici_coz(deg)
        if not yapici.tam:
            raise TakvimUretilemedi(yapici.yerlesmeyenler, yapici, pr)
        referans = deg.referans_belirle(yapici.cozum, tohum=tohum)  # yapıcının tam takvimi referans olur
        baslangic_ceza = deg.degerlendir(yapici.cozum)
        return pr, deg, ahp, referans, yapici, baslangic_ceza, list(veri_uyarilari), time.perf_counter() - t0

    def _calistir_ve_kaydet(
        self,
        *,
        pr: ProblemOrnegi,
        deg: Degerlendirici,
        ahp: AhpSonucu,
        referans: dict[str, float],
        yapici: YapiciSonuc,
        baslangic_ceza: Ceza,
        veri_uyarilari: list[str],
        algoritma: str,
        sure_sn: float | None,
        tohum: int,
        ek_sure_sn: float,
    ) -> TakvimSonucu:
        if algoritma == ALGORITMA_YAPICI:
            cozum = yapici.cozum
            gecmis = yapici.gecmis
            toplam_sure = ek_sure_sn
            bas_ceza_alan: Ceza | None = None
            parametreler: dict[str, Any] = {"tohum": tohum, "rastgele_ornek": REFERANS_RASTGELE_ORNEK}
        else:
            t_iyil = time.perf_counter()
            if algoritma == ALGORITMA_TAVLAMA:
                iyil = tavlama_coz(yapici.cozum, deg, self.ayarlar.tavlama, sure_sn=sure_sn, tohum=tohum)
            else:
                iyil = tabu_coz(yapici.cozum, deg, self.ayarlar.tabu, sure_sn=sure_sn, tohum=tohum)
            cozum = iyil.cozum
            gecmis = iyil.gecmis
            toplam_sure = ek_sure_sn + (time.perf_counter() - t_iyil)
            bas_ceza_alan = baslangic_ceza
            parametreler = {
                **iyil.ozet_parametreler,
                "rastgele_ornek": REFERANS_RASTGELE_ORNEK,
                "baslangic_yumusak": baslangic_ceza.yumusak,
                "adim_sayisi": iyil.adim_sayisi,
                "kabul_sayisi": iyil.kabul_sayisi,
                "iyilestirme_sayisi": iyil.iyilestirme_sayisi,
            }

        sonuc = self._degerlendir(pr, cozum, deg, ahp, referans)
        if not sonuc.dogrulama.gecerli or not sonuc.ceza.uygun:
            raise IcTutarsizlik(
                f"{algoritma} sert ihlalli takvim üretti: ceza={sonuc.ceza}, doğrulama={sonuc.dogrulama.sayilar()}"
            )
        sonuc.algoritma = algoritma
        sonuc.gecmis = gecmis
        sonuc.sure_sn = toplam_sure
        sonuc.baslangic_ceza = bas_ceza_alan
        sonuc.parametreler = parametreler
        sonuc.uyarilar = list(veri_uyarilari)
        if not ahp.tutarli:
            sonuc.uyarilar.append(_CR_UYARISI)

        kayit = kayit_olustur(
            pr, cozum, zaman=sonuc.zaman, algoritma=sonuc.algoritma, parametreler=parametreler,
            ceza=sonuc.ceza, ham_ihlaller=deg.ihlaller(cozum), sure_sn=sonuc.sure_sn, gecmis=sonuc.gecmis,
            ahp=ahp, referans=referans, referans_kaynagi=deg.referans_kaynagi,
        )
        with self.conn:  # tek işlem: kayıt ya tamamen yazılır ya hiç
            sonuc.kayit_id = self.depo.calistirmalar.ekle(kayit)
        return sonuc

    def _degerlendir(
        self, pr: ProblemOrnegi, cozum: Cozum, deg: Degerlendirici, ahp: AhpSonucu, referans: dict[str, float]
    ) -> TakvimSonucu:
        """Doğrulayıcıyla çapraz kontrol + tüm raporlar. Hem yeni çözümde hem geri yüklemede aynı yol."""
        dogrulama = dogrula(cozum)
        ortak_sayilar = {k: v for k, v in dogrulama.sayilar().items() if k not in _YAPISAL_KODLAR}
        if deg.sert_ihlaller(cozum) != ortak_sayilar:
            raise IcTutarsizlik(
                f"Değerlendirici {deg.sert_ihlaller(cozum)} buldu, doğrulayıcı {dogrulama.sayilar()} buldu"
            )
        rapor = deg.rapor(cozum)
        simdi = datetime.now().isoformat(timespec="seconds")
        return TakvimSonucu(
            problem=pr, cozum=cozum, degerlendirici=deg, ceza=deg.degerlendir(cozum), kisit_raporu=rapor,
            dogrulama=dogrulama, adalet=adalet_raporu(pr, deg.analiz(cozum)), ahp=ahp, referans=dict(referans),
            referans_kaynagi=dict(deg.referans_kaynagi), algoritma="", zaman=simdi, sure_sn=0.0,
        )

    # --- geri yükle ---
    def yukle(self, calistirma_id: int) -> TakvimSonucu:
        """Kayıtlı çalıştırmayı aynı AHP ağırlıkları ve aynı referans ölçekleriyle yeniden değerlendirir.

        Uyarılar: derslik dağıtımı ya da ham ceza kayıttakinden farklıysa (veri/kod değişmiş) listelenir."""
        kayit = self.depo.calistirmalar.getir(calistirma_id)
        if kayit is None:
            raise LookupError(f"{calistirma_id} numaralı çalıştırma bulunamadı")
        pr = ProblemOrnegi(self.depo.yukle(kayit.donem_id))
        if not kayit.ahp_agirliklari:
            raise KayitHatasi("Kayıtta AHP ağırlıkları eksik")
        try:
            ahp = ahp_sozlukten(kayit.ahp_agirliklari)
            referans = {k: float(v) for k, v in kayit.referans.get("olcek", {}).items()}
            referans_kaynagi = {str(k): str(v) for k, v in kayit.referans.get("kaynak", {}).items()}
        except (KeyError, TypeError, ValueError) as hata:
            raise KayitHatasi(f"Kayıttaki AHP ağırlıkları veya referans verisi geçersiz: {hata}") from hata
        deg = Degerlendirici(pr, ahp=ahp, referans=referans)
        deg.referans_kaynagi = referans_kaynagi
        cozum, uyarilar = cozum_olustur(pr, kayit)

        sonuc = self._degerlendir(pr, cozum, deg, ahp, referans)
        sonuc.algoritma, sonuc.zaman, sonuc.sure_sn = kayit.algoritma, kayit.zaman, kayit.sure_sn
        sonuc.gecmis, sonuc.kayit_id, sonuc.uyarilar = kayit.gecmis, kayit.id, list(uyarilar)
        sonuc.parametreler = dict(kayit.parametreler)
        if "baslangic_yumusak" in kayit.parametreler:
            sonuc.baslangic_ceza = Ceza(0.0, float(kayit.parametreler["baslangic_yumusak"]))
        if not ahp.tutarli:
            sonuc.uyarilar.append(_CR_UYARISI)
        yapisal = sorted(_YAPISAL_KODLAR & set(sonuc.dogrulama.sayilar()))
        if yapisal:
            sonuc.uyarilar.append(f"Doğrulayıcı yapısal salon ihlali buldu: {', '.join(yapisal)}")
        yeni = deg.ihlaller(cozum)
        fark = sorted(k for k in kayit.ceza_detay if abs(yeni.get(k, 0.0) - kayit.ceza_detay[k]) > TOLERANS)
        if fark:
            sonuc.uyarilar.append(f"Yeniden hesaplanan ihlaller kayıttakinden farklı: {', '.join(fark)}")
        return sonuc


__all__ = [
    "ALGORITMA_ADLAR",
    "ALGORITMA_KARSILASTIR",
    "ALGORITMA_TABU",
    "ALGORITMA_TAVLAMA",
    "ALGORITMA_YAPICI",
    "GECERLI_ALGORITMALAR",
    "IcTutarsizlik",
    "KayitHatasi",
    "SemaSurumHatasi",
    "TakvimServisi",
    "TakvimSonucu",
    "TakvimUretilemedi",
    "VARSAYILAN_ALGORITMA",
    "VARSAYILAN_DB",
    "veritabani_baglantisi",
]
