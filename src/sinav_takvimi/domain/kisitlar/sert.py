"""Sert kısıtlar: geçerli bir takvimde ihlal sayısı 0 olmalı.

Birim: ETKİLENEN KİŞİ SAYISI. Böylece sert toplam anlamlı olur: 300 kişilik bir sınavın yasak oturuma
konması, 2 öğrencinin yer bulamamasından daha kötüdür.
* H1: aynı anda iki sınavı olan öğrenci-çift sayısı (3 sınavı çakışan öğrenci 3 sayılır, ITC'deki gibi çift başına)
* H2: hiçbir salona sığmayan öğrenci
* H4: aynı anda iki sınavı olan hoca-çift sayısı (etkilenen kişi: hoca)
* H8, H9: kuralı ihlal eden sınavın öğrenci sayısı
* H7: dilimde müsait personeli aşan gözetmen ihtiyacı (kişi)
* H10: gereksinimi karşılanamayan özel öğrenci
* H11: öğrencinin günlük sınav üst sınırını aşan sınavı (kurum politikası tanımlıysa)

Hoca müsaitliği sert kural değil, yumuşak kriterdir (S11).

H6 (derslik türü) ve dersliğin müsaitliği yapısal olarak sağlanır: dağıtıcı uygun olmayan salonu hiç kullanmaz.
Bağımsız doğrulayıcı bunları da ayrıca kontrol eder. Yerleşmemiş sınavlar `Degerlendirici` tarafından sayılır.
"""

from __future__ import annotations

from sinav_takvimi.domain.derslik_dagitici import DilimDagitimi
from sinav_takvimi.domain.kisitlar.temel import CiftKisit, DilimKisit, OgrenciKisit, TekliKisit
from sinav_takvimi.domain.ogrenci_analizi import OgrenciAnalizi
from sinav_takvimi.domain.problem import ProblemOrnegi


class H1OgrenciCakismasi(CiftKisit):
    kod, ad, sert = "H1", "Öğrencinin iki sınavı aynı anda", True

    def ihlal(self, pr: ProblemOrnegi, e: int, f: int, pe: int, pf: int) -> float:
        return pr.cakisma[e].get(f, 0) if pe == pf else 0


class H2DerslikKapasitesi(DilimKisit):
    kod, ad, sert = "H2", "Yer bulamayan öğrenci", True

    def ihlal(self, pr: ProblemOrnegi, p: int, dagitim: DilimDagitimi) -> float:
        return dagitim.oturamayan


class H4HocaCakismasi(CiftKisit):
    kod, ad, sert = "H4", "Hocanın iki sınavı aynı anda", True

    def ihlal(self, pr: ProblemOrnegi, e: int, f: int, pe: int, pf: int) -> float:
        return 1 if pe == pf and f in pr.hoca_komsu[e] else 0


class H7GozetmenKapasitesi(DilimKisit):
    kod, ad, sert = "H7", "Oturumda yeterli gözetmen yok", True

    def ihlal(self, pr: ProblemOrnegi, p: int, dagitim: DilimDagitimi) -> float:
        return dagitim.gozetmen_asimi


class H8SinavSuresi(TekliKisit):
    kod, ad, sert = "H8", "Sınav (ek süre dahil) oturuma sığmıyor", True

    def ihlal(self, pr: ProblemOrnegi, e: int, p: int) -> float:
        return 0 if pr.dilim_sure_yeterli(e, p) else pr.ogrenci_sayisi[e]


class H9SabitYasakKural(TekliKisit):
    kod, ad, sert = "H9", "Sabit/yasak oturum kuralı ihlali", True

    def ihlal(self, pr: ProblemOrnegi, e: int, p: int) -> float:
        return 0 if pr.dilim_kurala_uygun(e, p) else pr.ogrenci_sayisi[e]


class H10OzelGereksinim(DilimKisit):
    kod, ad, sert = "H10", "Özel gereksinimi karşılanmayan öğrenci", True

    def ihlal(self, pr: ProblemOrnegi, p: int, dagitim: DilimDagitimi) -> float:
        return dagitim.ozel_ihlal


class H11GunlukSinavSiniri(OgrenciKisit):
    kod, ad, sert = "H11", "Öğrencinin günlük sınav sınırı aşıldı", True

    def ihlal(self, pr: ProblemOrnegi, analiz: OgrenciAnalizi) -> float:
        return sum(analiz.h11)
