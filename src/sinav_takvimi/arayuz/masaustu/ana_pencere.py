"""Masaüstü ana penceresi: üç sekme.

1. **Veri Stüdyosu:** tek tıkla fakülte üretme, temiz dönem, CSV; öğrenci/hoca/ders/derslik ekle, düzenle, sil.
2. **Takvim Oluştur:** algoritma ve süre seçip takvimi üretir; kayıtlı takvimleri açar.
3. **Kanıt & Kurallar:** bağımsız doğrulayıcının sonucu, sert kuralların ihlal sayısı, yumuşak kriterlerin cezası ve
   kısa bir adalet özeti. Bilinçli olarak sade tutuldu (ayrıntılı rapor Streamlit arayüzünde).

Katman kuralı: arayüz yalnızca `uygulama` katmanını çağırır. Çözücü uzun sürdüğü için ayrı bir
`QThread`'de, KENDİ veritabanı bağlantısıyla çalışır (bir SQLite bağlantısının işlemi iki thread arasında paylaşılmaz).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sinav_takvimi.arayuz.masaustu.diyaloglar import (
    BolumEkleDiyalogu,
    DersEkleDiyalogu,
    DerslikEkleDiyalogu,
    HizliFakulteDiyalogu,
    OgrenciDiyalogu,
    OturumMatrisiDiyalogu,
    PersonelEkleDiyalogu,
    TemizDonemDiyalogu,
)
from sinav_takvimi.domain.modeller import VeriSeti
from sinav_takvimi.uygulama.raporlar import (
    gorunen_sinavlar,
    hoca_programi,
    ogrenci_bul,
    ogrenci_programi,
    sinav_listesi,
    takvim_izgarasi,
)
from sinav_takvimi.uygulama.takvim_servisi import (
    ALGORITMA_ADLAR,
    ALGORITMA_KARSILASTIR,
    ALGORITMA_YAPICI,
    GECERLI_ALGORITMALAR,
    VARSAYILAN_ALGORITMA,
    KayitHatasi,
    SemaSurumHatasi,
    TakvimServisi,
    TakvimSonucu,
    TakvimUretilemedi,
    veritabani_baglantisi,
)
from sinav_takvimi.uygulama.veri_studyosu import VeriHatasi, VeriStudyosuServisi, veritabanini_yenile

_ALGORITMA_SECENEKLERI: dict[str, str] = {
    **ALGORITMA_ADLAR,
    ALGORITMA_KARSILASTIR: "Üçünü karşılaştır (en iyisini göster)",
}


# ---------------------------------------------------------------------------------------------- küçük yardımcılar
def _tablo_olustur() -> QTableWidget:
    t = QTableWidget()
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.verticalHeader().setVisible(False)
    return t


def _tablo_doldur(
    tablo: QTableWidget,
    basliklar: Sequence[str],
    satirlar: Sequence[Sequence[object]],
    idler: Sequence[int] = (),
    esnek_sutun: int | None = None,
) -> None:
    """Tabloyu baştan doldurur. `idler` verilirse her satırın ilk hücresine kaydın veritabanı id'si saklanır.
    `esnek_sutun` verilirse kalan genişliği o sütun alır (dar tablolarda sayılar görünür kalsın diye)."""
    tablo.setSortingEnabled(False)
    tablo.clear()
    tablo.setColumnCount(len(basliklar))
    tablo.setHorizontalHeaderLabels(list(basliklar))
    tablo.setRowCount(len(satirlar))
    for i, satir in enumerate(satirlar):
        for j, deger in enumerate(satir):
            oge = QTableWidgetItem("" if deger is None else str(deger))
            if j == 0 and idler:
                oge.setData(Qt.ItemDataRole.UserRole, idler[i])
            tablo.setItem(i, j, oge)
    baslik = tablo.horizontalHeader()
    baslik.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if esnek_sutun is not None and esnek_sutun < len(basliklar):
        baslik.setSectionResizeMode(esnek_sutun, QHeaderView.ResizeMode.Stretch)
    else:
        baslik.setStretchLastSection(True)


class _MetrikKarti(QFrame):
    def __init__(self, etiket: str) -> None:
        super().__init__()
        self.setObjectName("kart")
        y = QVBoxLayout(self)
        lbl = QLabel(etiket)
        lbl.setObjectName("metrikEtiket")
        self.deger = QLabel("—")
        self.deger.setObjectName("metrikDeger")
        y.addWidget(lbl)
        y.addWidget(self.deger)

    def ayarla(self, metin: str) -> None:
        self.deger.setText(metin)


# ---------------------------------------------------------------------------------------------- çözücü thread'i
class CozumIscisi(QThread):
    """Takvimi arka planda üretir.

    Sinyaller thread'ler arası güvenlidir: Qt, `bitti`/`hata` sinyallerini ana (arayüz) thread'inde çalıştırır.
    """

    bitti = Signal(object)  # TakvimSonucu
    hata = Signal(str, list)  # başlık, ayrıntı satırları

    def __init__(self, db_yolu: Path, algoritma: str, sure_sn: float, tohum: int) -> None:
        super().__init__()
        self.db_yolu, self.algoritma, self.sure_sn, self.tohum = db_yolu, algoritma, sure_sn, tohum

    def run(self) -> None:  # QThread.run: ayrı thread'de çalışan gövde
        try:
            conn = veritabani_baglantisi(self.db_yolu)  # bu thread'e ait bağlantı
        except Exception as h:  # noqa: BLE001 - kullanıcıya gösterilir
            self.hata.emit("Veritabanı açılamadı", [str(h)])
            return
        try:
            servis = TakvimServisi(conn)
            if self.algoritma == ALGORITMA_KARSILASTIR:
                sonuc = min(servis.karsilastir(tohum=self.tohum, sure_sn=self.sure_sn), key=lambda s: s.ceza)
            else:
                sonuc = servis.olustur(tohum=self.tohum, algoritma=self.algoritma, sure_sn=self.sure_sn)
            self.bitti.emit(sonuc)
        except TakvimUretilemedi as h:
            self.hata.emit(str(h), [f"{y.ders_kod} ({y.ogrenci} öğrenci): {y.neden}" for y in h.yerlesmeyenler])
        except (VeriHatasi, LookupError) as h:
            self.hata.emit("Veri hatası", h.hatalar if isinstance(h, VeriHatasi) else [str(h)])
        except Exception as h:  # noqa: BLE001 - beklenmeyen hata pencereyi çökertmesin
            self.hata.emit("Beklenmeyen hata", [f"{type(h).__name__}: {h}"])
        finally:
            conn.close()


# ---------------------------------------------------------------------------------------------- Veri Stüdyosu
def _kucuk_harf(metin: str) -> str:
    """Türkçe küçük harf (Python'un lower()'ı 'I'yı 'i' yapar; Türkçede 'ı' olmalı, 'İ' de 'i')."""
    return metin.replace("I", "ı").replace("İ", "i").lower()


class _VarlikPaneli(QWidget):
    """Bir varlık listesi (tablo) + arama kutusu + Ekle / Rastgele Ekle / Düzenle / Sil / Bölüme Göre Sil düğmeleri.

    Ctrl ya da Shift ile birden çok satır seçilip tek seferde silinebilir.
    """

    def __init__(
        self,
        *,
        ekle: Callable[[], None],
        rastgele: Callable[[int], None],
        sil: Callable[[list[int]], None],
        duzenle: Callable[[int], None] | None = None,
        duzenle_metni: str = "Düzenle",
        bolume_gore_sil: Callable[[], None] | None = None,
        arama_ipucu: str = "Ara…",
    ) -> None:
        super().__init__()
        y = QVBoxLayout(self)
        self.ed_ara = QLineEdit()
        self.ed_ara.setPlaceholderText(arama_ipucu)
        self.ed_ara.setClearButtonEnabled(True)
        self.ed_ara.textChanged.connect(lambda _: self.suz())
        self.lbl_sayi = QLabel()
        self.lbl_sayi.setObjectName("altBaslik")
        arama = QHBoxLayout()
        arama.addWidget(QLabel("🔍"))
        arama.addWidget(self.ed_ara, stretch=1)
        arama.addWidget(self.lbl_sayi)
        y.addLayout(arama)
        cubuk = QHBoxLayout()
        btn_ekle = QPushButton("+ Ekle")
        btn_ekle.setObjectName("birincilButon")
        btn_ekle.clicked.connect(ekle)
        self.sp_adet = QSpinBox()
        self.sp_adet.setRange(1, 500)
        self.sp_adet.setPrefix("Adet: ")
        btn_rastgele = QPushButton("🎲 Rastgele Ekle")
        btn_rastgele.setObjectName("rastgeleButon")
        btn_rastgele.clicked.connect(lambda: rastgele(int(self.sp_adet.value())))
        cubuk.addWidget(btn_ekle)
        cubuk.addWidget(self.sp_adet)
        cubuk.addWidget(btn_rastgele)
        cubuk.addStretch()
        if duzenle is not None:
            btn_duzenle = QPushButton(duzenle_metni)
            btn_duzenle.clicked.connect(lambda: self._secili_ile(duzenle))
            cubuk.addWidget(btn_duzenle)
        btn_sil = QPushButton("Seçilenleri Sil")
        btn_sil.setObjectName("tehlikeButon")
        btn_sil.setToolTip("Ctrl ya da Shift ile birden çok satır seçebilirsiniz.")
        btn_sil.clicked.connect(lambda: self._secililer_ile(sil))
        cubuk.addWidget(btn_sil)
        if bolume_gore_sil is not None:
            btn_bolum = QPushButton("Bölüme Göre Sil")
            btn_bolum.setObjectName("tehlikeButon")
            btn_bolum.clicked.connect(bolume_gore_sil)
            cubuk.addWidget(btn_bolum)
        y.addLayout(cubuk)
        self.tablo = _tablo_olustur()
        self.tablo.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)  # çoklu seçim
        y.addWidget(self.tablo, stretch=1)

    def suz(self) -> None:
        """Arama metnini içermeyen satırları gizler (tüm sütunlarda, büyük/küçük harf duyarsız)."""
        aranan = _kucuk_harf(self.ed_ara.text().strip())
        gorunen = 0
        for i in range(self.tablo.rowCount()):
            hucreler = (self.tablo.item(i, j) for j in range(self.tablo.columnCount()))
            uyar = not aranan or any(h is not None and aranan in _kucuk_harf(h.text()) for h in hucreler)
            self.tablo.setRowHidden(i, not uyar)
            gorunen += uyar
        self.tablo.clearSelection()  # gizlenen satırlar yanlışlıkla silinmesin
        toplam = self.tablo.rowCount()
        self.lbl_sayi.setText(f"{gorunen} / {toplam} kayıt" if aranan else f"{toplam} kayıt")

    def secili_idler(self) -> list[int]:
        """Seçili ve görünür satırların veritabanı id'leri."""
        satirlar = sorted({ix.row() for ix in self.tablo.selectedIndexes()})
        idler = []
        for i in satirlar:
            oge = self.tablo.item(i, 0)
            if oge is not None and not self.tablo.isRowHidden(i):
                idler.append(int(oge.data(Qt.ItemDataRole.UserRole)))
        return idler

    def _secili_ile(self, islem: Callable[[int], None]) -> None:
        idler = self.secili_idler()
        if len(idler) != 1:
            QMessageBox.information(self, "Seçim", "Düzenlemek için tablodan tek bir satır seçin.")
            return
        islem(idler[0])

    def _secililer_ile(self, islem: Callable[[list[int]], None]) -> None:
        idler = self.secili_idler()
        if not idler:
            QMessageBox.information(self, "Seçim yok", "Önce tablodan en az bir satır seçin.")
            return
        islem(idler)


class VeriStudyosuSekmesi(QWidget):
    def __init__(
        self, stud: VeriStudyosuServisi, veri_degisti: Callable[[], None], kayit_sayisi: Callable[[], int]
    ) -> None:
        super().__init__()
        self.stud = stud
        self._veri_degisti = veri_degisti  # takvim sekmesi eski kayıtları temizlesin diye
        self._kayit_sayisi = kayit_sayisi  # kayıtlı takvim sayısı (veri değişince silinecekler)
        self.veri: VeriSeti | None = None

        y = QVBoxLayout(self)
        ust = QHBoxLayout()
        for metin, islem, ad in (
            ("⚡ Hızlı Fakülte Üret", self.hizli_fakulte, "birincilButon"),
            ("📄 Temiz Dönem Aç", self.temiz_donem, ""),
            ("+ Bölüm", self.bolum_ekle, ""),
        ):
            b = QPushButton(metin)
            if ad:
                b.setObjectName(ad)
            b.clicked.connect(islem)
            ust.addWidget(b)
        # İçe / dışa aktarma: Excel (tek .xlsx, her tablo bir sayfa) ya da CSV klasörü; sütunlar ikisinde de aynı
        for metin, secenekler in (
            ("📥 İçe Aktar ▾", (("Excel dosyası (.xlsx)…", self.excel_ice), ("CSV klasörü…", self.csv_ice))),
            ("📤 Dışa Aktar ▾", (("Excel dosyası (.xlsx)…", self.excel_disa), ("CSV klasörü…", self.csv_disa))),
        ):
            b = QPushButton(metin)
            menu = QMenu(b)
            for etiket, islem in secenekler:
                menu.addAction(etiket, islem)
            b.setMenu(menu)
            ust.insertWidget(2 if metin.startswith("📥") else 3, b)
        ust.addStretch()
        for metin, islem in (("🗑 Bölümü Sil", self.bolumu_sil), ("⛔ Tüm Verileri Sil", self.tum_veriyi_sil)):
            b = QPushButton(metin)
            b.setObjectName("tehlikeButon")
            b.clicked.connect(islem)
            ust.addWidget(b)
        y.addLayout(ust)

        self.lbl_ozet = QLabel()
        self.lbl_ozet.setObjectName("altBaslik")
        self.lbl_ozet.setWordWrap(True)
        y.addWidget(self.lbl_ozet)
        self.lbl_uyari = QLabel()
        self.lbl_uyari.setObjectName("altBaslik")
        self.lbl_uyari.setWordWrap(True)
        y.addWidget(self.lbl_uyari)

        self.alt_sekmeler = QTabWidget()
        self.p_ogrenci = _VarlikPaneli(
            ekle=self.ogrenci_ekle, rastgele=self._rastgele(self.stud.rastgele_ogrenci_ekle),
            sil=self._sil(self.stud.ogrencileri_sil, "öğrenci"), duzenle=self.ogrenci_duzenle,
            duzenle_metni="Dersler / Gereksinim",
            bolume_gore_sil=self._bolume_gore_sil(
                "öğrenci", lambda v, b: [o.id for o in v.ogrenciler if o.bolum_id == b], self.stud.ogrencileri_sil
            ),
            arama_ipucu="Ad, öğrenci numarası ya da bölüm ile ara…",
        )
        self.p_personel = _VarlikPaneli(
            ekle=self.personel_ekle, rastgele=self._rastgele(self.stud.rastgele_personel_ekle),
            sil=self._sil(self.stud.personelleri_sil, "öğretim elemanı"), duzenle=self.personel_musaitlik,
            duzenle_metni="Müsaitlik",
            bolume_gore_sil=self._bolume_gore_sil(
                "öğretim elemanı", lambda v, b: [p.id for p in v.personeller if p.bolum_id == b],
                self.stud.personelleri_sil,
            ),
            arama_ipucu="Ad, unvan ya da bölüm ile ara…",
        )
        self.p_ders = _VarlikPaneli(
            ekle=self.ders_ekle, rastgele=self._rastgele(self.stud.rastgele_ders_ekle),
            sil=self._sil(self.stud.dersleri_sil, "ders"), duzenle=self.ders_kurallari,
            duzenle_metni="Sabit / Yasak Oturum",
            bolume_gore_sil=self._bolume_gore_sil(
                "ders", lambda v, b: [d.id for d in v.dersler if d.bolum_id == b], self.stud.dersleri_sil,
                ortak_secenegi=True,
            ),
            arama_ipucu="Ders kodu, adı, bölüm ya da hoca ile ara…",
        )
        self.p_derslik = _VarlikPaneli(
            ekle=self.derslik_ekle, rastgele=self._rastgele(self.stud.rastgele_derslik_ekle),
            sil=self._sil(self.stud.derslikleri_sil, "derslik"), duzenle=self.derslik_musaitlik,
            duzenle_metni="Müsaitlik",
            arama_ipucu="Derslik kodu ya da türü ile ara…",
        )
        self.alt_sekmeler.addTab(self.p_ogrenci, "Öğrenciler")
        self.alt_sekmeler.addTab(self.p_personel, "Öğretim Elemanları")
        self.alt_sekmeler.addTab(self.p_ders, "Dersler")
        self.alt_sekmeler.addTab(self.p_derslik, "Derslikler")
        y.addWidget(self.alt_sekmeler, stretch=1)

    # --- ortak akış: servis çağrısı → hata/uyarı göster → yenile ---
    def _takvim_uyarisi(self) -> str:
        """Kayıtlı takvim varsa, veri değişince silineceklerini söyleyen cümle (VeriDeposu.degistir hepsini siler)."""
        n = self._kayit_sayisi()
        return f"\n\nDikkat: {n} kayıtlı takvim eski veriye göre üretildiği için silinecek." if n else ""

    def _uygula(self, islem: Callable[[], object], onaylandi: bool = False) -> bool:
        """Servis çağrısı → hata/uyarı göster → yenile. Kayıtlı takvim varsa önce onay istenir (`onaylandi` değilse)."""
        uyari = self._takvim_uyarisi()
        if uyari and not onaylandi:
            cevap = QMessageBox.question(self, "Değişikliği kaydet", "Değişiklik kaydedilsin mi?" + uyari)
            if cevap != QMessageBox.StandardButton.Yes:
                return False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            islem()
        except VeriHatasi as h:
            QMessageBox.warning(self, "Kaydedilmedi", "Veri kurallara uymuyor, değişiklik yapılmadı:\n\n" +
                                "\n".join(f"• {m}" for m in h.hatalar[:15]))
            return False
        except OSError as h:  # CSV klasörü okunamadı/yazılamadı vb.
            QMessageBox.warning(self, "Dosya hatası", str(h))
            return False
        except Exception as h:  # noqa: BLE001 - .exe'de konsol yok: hata sessizce kaybolmasın
            QMessageBox.critical(self, "Beklenmeyen hata", f"Değişiklik kaydedilemedi.\n\n{type(h).__name__}: {h}")
            return False
        finally:
            QApplication.restoreOverrideCursor()  # her durumda
        self.yenile()
        self._veri_degisti()
        return True

    def _rastgele(self, fonk: Callable[[int], object]) -> Callable[[int], None]:
        def calistir(adet: int) -> None:
            if self._donem_var():
                self._uygula(lambda: fonk(adet))
        return calistir

    def _sil(self, fonk: Callable[[list[int]], object], nesne: str) -> Callable[[list[int]], None]:
        def calistir(idler: list[int]) -> None:
            cevap = QMessageBox.question(
                self, "Silme onayı", f"Seçili {len(idler)} {nesne} silinsin mi?" + self._takvim_uyarisi()
            )
            if cevap == QMessageBox.StandardButton.Yes:
                self._uygula(lambda: fonk(idler), onaylandi=True)
        return calistir

    def _bolum_sec(self, baslik: str, ortak_secenegi: bool = False) -> tuple[bool, int | None]:
        """Bölüm seçim penceresi. (seçildi_mi, bolum_id); bolum_id None = fakülte ortak dersleri."""
        if not self._donem_var():
            return False, None
        assert self.veri is not None
        secenekler: dict[str, int | None] = {f"{b.kod} — {b.ad}": b.id for b in self.veri.bolumler}
        if ortak_secenegi:
            secenekler["ORTAK — Fakülte ortak dersleri"] = None
        if not secenekler:
            QMessageBox.information(self, "Bölüm yok", "Tanımlı bölüm yok.")
            return False, None
        secim, tamam = QInputDialog.getItem(self, baslik, "Bölüm:", list(secenekler), 0, False)
        return (True, secenekler[secim]) if tamam else (False, None)

    def _bolume_gore_sil(
        self,
        nesne: str,
        idleri_bul: Callable[[VeriSeti, int | None], list[int]],
        fonk: Callable[[list[int]], object],
        ortak_secenegi: bool = False,
    ) -> Callable[[], None]:
        def calistir() -> None:
            secildi, bolum_id = self._bolum_sec(f"Bölüme göre {nesne} sil", ortak_secenegi)
            if not secildi:
                return
            assert self.veri is not None
            idler = idleri_bul(self.veri, bolum_id)
            if not idler:
                QMessageBox.information(self, "Silinecek kayıt yok", f"Bu bölümde hiç {nesne} yok.")
                return
            self._sil(fonk, nesne)(idler)
        return calistir

    def bolumu_sil(self) -> None:
        """Bölümü öğrencileri, dersleri ve öğretim elemanlarıyla birlikte siler."""
        secildi, bolum_id = self._bolum_sec("Bölümü sil")
        if not secildi or bolum_id is None:
            return
        assert self.veri is not None
        v = self.veri
        sayilar = (
            sum(o.bolum_id == bolum_id for o in v.ogrenciler),
            sum(d.bolum_id == bolum_id for d in v.dersler),
            sum(p.bolum_id == bolum_id for p in v.personeller),
        )
        cevap = QMessageBox.question(
            self, "Bölümü sil",
            f"Bölüm; {sayilar[0]} öğrenci, {sayilar[1]} ders ve {sayilar[2]} öğretim elemanıyla birlikte silinsin mi?"
            + self._takvim_uyarisi(),
        )
        if cevap == QMessageBox.StandardButton.Yes:
            self._uygula(lambda: self.stud.bolumu_sil(bolum_id), onaylandi=True)

    def tum_veriyi_sil(self) -> None:
        """Sıfırdan başlamak için: dönem, bütün kayıtlar ve takvimler silinir (AHP anketleri korunur)."""
        if not self._donem_var():
            return
        cevap = QMessageBox.warning(
            self, "Tüm verileri sil",
            "Dönem, bölümler, öğrenciler, öğretim elemanları, dersler, derslikler ve kayıtlı takvimlerin TAMAMI "
            "silinecek. Bu işlem geri alınamaz.\n\nDevam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if cevap == QMessageBox.StandardButton.Yes:
            self._uygula(self.stud.tum_veriyi_sil, onaylandi=True)

    def _donem_var(self) -> bool:
        if self.veri is None:
            QMessageBox.information(self, "Dönem yok", "Önce 'Hızlı Fakülte Üret' ya da 'Temiz Dönem Aç' seçin.")
            return False
        return True

    def _degisiklik_onayi(self, baslik: str) -> bool:
        if self.veri is None:
            return True
        cevap = QMessageBox.question(
            self, baslik, "Mevcut veri ve kayıtlı takvimler silinip yenisiyle değiştirilecek. Devam edilsin mi?"
        )
        return cevap == QMessageBox.StandardButton.Yes

    # --- üst düğmeler ---
    def hizli_fakulte(self) -> None:
        d = HizliFakulteDiyalogu(self)
        if d.exec() and self._degisiklik_onayi("Hızlı fakülte üret"):
            self._uygula(lambda: self.stud.sentetik_olustur(d.ayarlar()), onaylandi=True)

    def temiz_donem(self) -> None:
        d = TemizDonemDiyalogu(self)
        if d.exec() and self._degisiklik_onayi("Temiz dönem aç"):
            ad, tur, baslangic, gun = d.veri_al()
            self._uygula(lambda: self.stud.temiz_donem_olustur(ad, tur, baslangic, gun), onaylandi=True)

    def csv_ice(self) -> None:
        klasor = QFileDialog.getExistingDirectory(self, "CSV klasörünü seçin")
        if klasor and self._degisiklik_onayi("CSV içe aktar"):
            self._uygula(lambda: self.stud.csv_ice_aktar(klasor), onaylandi=True)

    def excel_ice(self) -> None:
        dosya, _ = QFileDialog.getOpenFileName(self, "Excel dosyasını seçin", "", "Excel dosyası (*.xlsx)")
        if dosya and self._degisiklik_onayi("Excel'den içe aktar"):
            self._uygula(lambda: self.stud.excel_ice_aktar(dosya), onaylandi=True)

    def excel_disa(self) -> None:
        if not self._donem_var():
            return
        dosya, _ = QFileDialog.getSaveFileName(
            self, "Excel olarak kaydet", "sinav_verisi.xlsx", "Excel dosyası (*.xlsx)"
        )
        if not dosya:
            return
        if not dosya.lower().endswith(".xlsx"):
            dosya += ".xlsx"
        try:
            self.stud.excel_disa_aktar(dosya)
        except OSError as h:  # dosya Excel'de açık, yazma izni yok vb.
            QMessageBox.warning(self, "Dışa aktarılamadı", f"{h}\n\nDosya Excel'de açıksa kapatıp tekrar deneyin.")
            return
        QMessageBox.information(self, "Dışa aktarıldı", f"Excel dosyası yazıldı:\n{dosya}")

    def csv_disa(self) -> None:
        if not self._donem_var():
            return
        klasor = QFileDialog.getExistingDirectory(self, "CSV dosyalarının yazılacağı klasör")
        if not klasor:
            return
        try:
            self.stud.csv_disa_aktar(klasor)
        except OSError as h:  # klasöre yazma izni yok, dosya Excel'de açık vb.
            QMessageBox.warning(self, "Dışa aktarılamadı", str(h))
            return
        QMessageBox.information(self, "Dışa aktarıldı", f"CSV dosyaları yazıldı:\n{klasor}")

    def bolum_ekle(self) -> None:
        if not self._donem_var():
            return
        d = BolumEkleDiyalogu(self)
        if d.exec():
            self._uygula(lambda: self.stud.bolum_ekle(*d.veri_al()))

    # --- varlık işlemleri ---
    def ogrenci_ekle(self) -> None:
        if not self._donem_var():
            return
        assert self.veri is not None
        d = OgrenciDiyalogu(self.stud, self.veri, parent=self)
        if d.exec():
            self._uygula(lambda: self.stud.ogrenci_ekle(*d.veri_al()))

    def ogrenci_duzenle(self, ogrenci_id: int) -> None:
        assert self.veri is not None
        ogr = next(o for o in self.veri.ogrenciler if o.id == ogrenci_id)
        dersler = {did for oid, did in self.veri.kayitlar if oid == ogrenci_id}
        gerek = next((g for g in self.veri.gereksinimler if g.ogrenci_id == ogrenci_id), None)
        d = OgrenciDiyalogu(
            self.stud, self.veri, mevcut_ogrenci=ogr, mevcut_dersler=dersler, mevcut_gereksinim=gerek, parent=self
        )
        if d.exec():
            _, _, _, _, ders_idleri, eris, ayri, ek = d.veri_al()
            self._uygula(lambda: self.stud.ogrenci_kayit_ayarla(ogrenci_id, ders_idleri, eris, ayri, ek))

    def personel_ekle(self) -> None:
        if not self._donem_var():
            return
        assert self.veri is not None
        d = PersonelEkleDiyalogu(self.stud, self.veri, self)
        if d.exec():
            self._uygula(lambda: self.stud.personel_ekle(*d.veri_al()))

    def personel_musaitlik(self, personel_id: int) -> None:
        assert self.veri is not None
        kapali = {did for pid, did in self.veri.personel_musait_degil if pid == personel_id}
        d = OturumMatrisiDiyalogu("Öğretim elemanı müsaitliği", self.veri.dilimler, kapali_dilimler=kapali, parent=self)
        if d.exec():
            self._uygula(lambda: self.stud.personel_musaitlik_ayarla(personel_id, d.kapali_dilim_idleri()))

    def ders_ekle(self) -> None:
        if not self._donem_var():
            return
        assert self.veri is not None
        d = DersEkleDiyalogu(self.stud, self.veri, self)
        if d.exec():
            self._uygula(lambda: self.stud.ders_ekle(*d.veri_al()))

    def ders_kurallari(self, ders_id: int) -> None:
        assert self.veri is not None
        mevcut = [k for k in self.veri.dilim_kurallari if k.ders_id == ders_id]
        kurallar = {k.dilim_id: k.tur for k in mevcut}
        aciklamalar = {(k.dilim_id, k.tur): k.aciklama or "" for k in mevcut}
        d = OturumMatrisiDiyalogu(
            "Sabit / yasak oturumlar", self.veri.dilimler, mod="kural", ders_kurallari=kurallar, parent=self
        )
        if d.exec():
            # değişmeyen hücreler eski açıklamasını korur (ör. CSV'den gelen "Senato kararı ...")
            yeni = [(did, tur, aciklamalar.get((did, tur), acik)) for did, tur, acik in d.ders_kurallari_listesi()]
            self._uygula(lambda: self.stud.ders_kurallari_ayarla(ders_id, yeni))

    def derslik_ekle(self) -> None:
        if not self._donem_var():
            return
        d = DerslikEkleDiyalogu(self.stud, self)
        if d.exec():
            self._uygula(lambda: self.stud.derslik_ekle(*d.veri_al()))

    def derslik_musaitlik(self, derslik_id: int) -> None:
        assert self.veri is not None
        kapali = {did for rid, did in self.veri.derslik_musait_degil if rid == derslik_id}
        d = OturumMatrisiDiyalogu("Derslik müsaitliği", self.veri.dilimler, kapali_dilimler=kapali, parent=self)
        if d.exec():
            self._uygula(lambda: self.stud.derslik_musaitlik_ayarla(derslik_id, d.kapali_dilim_idleri()))

    # --- görünüm ---
    def yenile(self) -> None:
        self.veri = v = self.stud.aktif_veri()
        if v is None or v.donem is None:
            self.lbl_ozet.setText("Henüz sınav dönemi yok. 'Hızlı Fakülte Üret' ile örnek veri oluşturabilirsiniz.")
            self.lbl_uyari.setText("")
            for p in (self.p_ogrenci, self.p_personel, self.p_ders, self.p_derslik):
                _tablo_doldur(p.tablo, [], [])
                p.suz()
            return
        ozet = v.ozet()
        self.lbl_ozet.setText(
            f"<b>{v.donem.ad}</b> ({v.donem.baslangic} – {v.donem.bitis}) · "
            + " · ".join(f"{ad}: {ozet[ad]}" for ad in ("Bölüm", "Öğrenci", "Personel", "Ders", "Derslik"))
            + f" · Oturum: {ozet['Dilim (oturum)']}"
        )
        uyarilar = self.stud.aktif_uyarilar()
        self.lbl_uyari.setText(
            "⚠ " + " | ".join(uyarilar[:3]) + (f" (+{len(uyarilar) - 3} uyarı)" if len(uyarilar) > 3 else "")
            if uyarilar else ""
        )

        bolum = {b.id: b.kod for b in v.bolumler}
        personel = {p.id: p.tam_ad for p in v.personeller}
        ders_sayisi: dict[int, int] = {}
        ogrenci_sayisi: dict[int, int] = {}
        for oid, did in v.kayitlar:
            ders_sayisi[oid] = ders_sayisi.get(oid, 0) + 1
            ogrenci_sayisi[did] = ogrenci_sayisi.get(did, 0) + 1
        gerek = {g.ogrenci_id: g for g in v.gereksinimler}

        def gerek_metni(oid: int) -> str:
            g = gerek.get(oid)
            if g is None:
                return ""
            parca = [m for m, var in (("erişilebilir", g.erisilebilir_salon), ("ayrı salon", g.ayri_salon)) if var]
            if g.ek_sure_orani > 0:
                parca.append(f"+%{g.ek_sure_orani * 100:.0f} süre")
            return ", ".join(parca)

        _tablo_doldur(
            self.p_ogrenci.tablo, ["No", "Ad", "Bölüm", "Sınıf", "Ders", "Özel gereksinim"],
            [(o.no, o.ad, bolum.get(o.bolum_id, "?"), o.sinif, ders_sayisi.get(o.id, 0), gerek_metni(o.id))
             for o in v.ogrenciler],
            [o.id for o in v.ogrenciler],
        )
        kapali_p: dict[int, int] = {}
        for pid, _ in v.personel_musait_degil:
            kapali_p[pid] = kapali_p.get(pid, 0) + 1
        _tablo_doldur(
            self.p_personel.tablo, ["Ad", "Bölüm", "Günlük maks. görev", "Kapalı oturum"],
            [(p.tam_ad, bolum.get(p.bolum_id, "?"), p.gunluk_max, kapali_p.get(p.id, 0)) for p in v.personeller],
            [p.id for p in v.personeller],
        )
        kural_sayisi: dict[int, int] = {}
        for k in v.dilim_kurallari:
            kural_sayisi[k.ders_id] = kural_sayisi.get(k.ders_id, 0) + 1
        _tablo_doldur(
            self.p_ders.tablo, ["Kod", "Ad", "Bölüm", "Sınıf", "Zorluk", "Süre (dk)", "Öğrenci", "Hoca", "Kural"],
            [(d.kod, d.ad, "ORTAK" if d.bolum_id is None else bolum.get(d.bolum_id, "?"), d.sinif, d.zorluk,
              d.sinav_suresi_dk, ogrenci_sayisi.get(d.id, 0), personel.get(d.hoca_id, "?"), kural_sayisi.get(d.id, 0))
             for d in v.dersler],
            [d.id for d in v.dersler],
        )
        kapali_r: dict[int, int] = {}
        for rid, _ in v.derslik_musait_degil:
            kapali_r[rid] = kapali_r.get(rid, 0) + 1
        _tablo_doldur(
            self.p_derslik.tablo, ["Kod", "Tür", "Kapasite", "Sınav kapasitesi", "Erişilebilir", "Gözetmen", "Kapalı"],
            [(r.kod, r.tur, r.kapasite, r.sinav_kapasitesi, "evet" if r.erisilebilir else "", r.gozetmen_sayisi,
              kapali_r.get(r.id, 0)) for r in v.derslikler],
            [r.id for r in v.derslikler],
        )
        for p in (self.p_ogrenci, self.p_personel, self.p_ders, self.p_derslik):
            p.suz()  # arama kutusundaki metin yenilemeden sonra da geçerli kalsın


# ---------------------------------------------------------------------------------------------- Takvim Oluştur
class TakvimSekmesi(QWidget):
    sonuc_hazir = Signal(object)  # TakvimSonucu (ya da None: gösterilecek takvim yok)

    def __init__(self, servis: TakvimServisi, db_yolu: Path, mesgul: Callable[[bool], None]) -> None:
        super().__init__()
        self.servis = servis
        self.db_yolu = db_yolu
        self._mesgul = mesgul
        self._isci: CozumIscisi | None = None

        y = QVBoxLayout(self)
        ayar = QHBoxLayout()
        self.cb_alg = QComboBox()
        for anahtar in (*GECERLI_ALGORITMALAR, ALGORITMA_KARSILASTIR):
            self.cb_alg.addItem(_ALGORITMA_SECENEKLERI[anahtar], anahtar)
        self.cb_alg.setCurrentIndex(self.cb_alg.findData(VARSAYILAN_ALGORITMA))
        self.cb_alg.currentIndexChanged.connect(self._alg_degisti)
        self.sp_sure = QSpinBox()
        self.sp_sure.setRange(1, 300)
        self.sp_sure.setSuffix(" sn")
        self.sp_sure.setValue(int(servis.ayarlar.tabu.sure_sn))
        self.sp_tohum = QSpinBox()
        self.sp_tohum.setRange(0, 99999)
        self.btn_olustur = QPushButton("Takvim Oluştur")
        self.btn_olustur.setObjectName("birincilButon")
        self.btn_olustur.clicked.connect(self.olustur)
        self.ilerleme = QProgressBar()
        self.ilerleme.setRange(0, 0)  # belirsiz ilerleme (süre bütçesi kadar sürer)
        self.ilerleme.setMaximumWidth(160)
        self.ilerleme.hide()
        for etiket, w in (("Algoritma:", self.cb_alg), ("Süre:", self.sp_sure), ("Tohum:", self.sp_tohum)):
            ayar.addWidget(QLabel(etiket))
            ayar.addWidget(w)
        ayar.addWidget(self.btn_olustur)
        ayar.addWidget(self.ilerleme)
        ayar.addStretch()
        y.addLayout(ayar)

        kayit = QHBoxLayout()
        kayit.addWidget(QLabel("Kayıtlı takvim:"))
        self.cb_kayit = QComboBox()
        self.cb_kayit.setMinimumWidth(420)
        self.cb_kayit.activated.connect(lambda _: self.kayit_ac())
        kayit.addWidget(self.cb_kayit)
        kayit.addStretch()
        y.addLayout(kayit)

        kartlar = QGridLayout()
        self.k_alg, self.k_yer, self.k_sert, self.k_yum, self.k_iyi, self.k_sure = (
            _MetrikKarti(e) for e in ("ALGORİTMA", "YERLEŞEN SINAV", "SERT İHLAL", "YUMUŞAK CEZA",
                                      "YAPICIYA GÖRE İYİLEŞME", "SÜRE")
        )
        for i, k in enumerate((self.k_alg, self.k_yer, self.k_sert, self.k_yum, self.k_iyi, self.k_sure)):
            kartlar.addWidget(k, 0, i)
        y.addLayout(kartlar)

        self._sonuc: TakvimSonucu | None = None

        # Bölüm / sınıf görünümü: takvim ızgarası ve sınav listesi bu filtreye göre gösterilir
        filtre = QHBoxLayout()
        filtre.addWidget(QLabel("Görünüm —  Bölüm:"))
        self.cb_bolum = QComboBox()
        self.cb_bolum.addItem("Tüm bölümler", None)
        self.cb_bolum.setMinimumWidth(260)
        self.cb_sinif = QComboBox()
        self.cb_sinif.addItem("Tüm sınıflar", None)
        for s in range(1, 5):
            self.cb_sinif.addItem(f"{s}. sınıf", s)
        self.cb_bolum.currentIndexChanged.connect(lambda _: self._gorunumu_yenile())
        self.cb_sinif.currentIndexChanged.connect(lambda _: self._gorunumu_yenile())
        filtre.addWidget(self.cb_bolum)
        filtre.addWidget(QLabel("Sınıf:"))
        filtre.addWidget(self.cb_sinif)
        self.lbl_filtre = QLabel()
        self.lbl_filtre.setObjectName("altBaslik")
        filtre.addWidget(self.lbl_filtre)
        filtre.addStretch()
        y.addLayout(filtre)

        self.ic_sekmeler = QTabWidget()
        self.t_izgara = _tablo_olustur()
        self.t_izgara.setWordWrap(True)
        self.t_liste = _tablo_olustur()
        self.ic_sekmeler.addTab(self.t_izgara, "Takvim (Gün × Oturum)")
        self.ic_sekmeler.addTab(self.t_liste, "Sınav Listesi")

        # Öğrenci programı: numara ya da ad ile ara → kişisel sınav listesi
        ogr = QWidget()
        oy = QVBoxLayout(ogr)
        ust = QHBoxLayout()
        self.ed_ogrenci = QLineEdit()
        self.ed_ogrenci.setPlaceholderText("Öğrenci numarası ya da adı yazın…")
        self.ed_ogrenci.setClearButtonEnabled(True)
        self.ed_ogrenci.textChanged.connect(lambda _: self._ogrenci_ara())
        self.cb_ogrenci = QComboBox()
        self.cb_ogrenci.setMinimumWidth(360)
        self.cb_ogrenci.currentIndexChanged.connect(lambda _: self._ogrenci_goster())
        ust.addWidget(QLabel("🔍"))
        ust.addWidget(self.ed_ogrenci, stretch=1)
        ust.addWidget(self.cb_ogrenci)
        oy.addLayout(ust)
        self.lbl_ogrenci = QLabel()
        self.lbl_ogrenci.setObjectName("altBaslik")
        oy.addWidget(self.lbl_ogrenci)
        self.t_ogrenci = _tablo_olustur()
        oy.addWidget(self.t_ogrenci, stretch=1)
        self.ic_sekmeler.addTab(ogr, "Öğrenci Programı")

        # Hoca programı: aranabilir hoca listesi → hocası/asistanı olduğu derslerin sınavları
        hoca = QWidget()
        hy = QVBoxLayout(hoca)
        hust = QHBoxLayout()
        hust.addWidget(QLabel("Öğretim elemanı:"))
        self.cb_hoca = QComboBox()
        self.cb_hoca.setEditable(True)  # yazarak aranabilir
        self.cb_hoca.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.cb_hoca.setMinimumWidth(360)
        tamamlayici = self.cb_hoca.completer()
        if tamamlayici is not None:
            tamamlayici.setFilterMode(Qt.MatchFlag.MatchContains)
            tamamlayici.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.cb_hoca.currentIndexChanged.connect(lambda _: self._hoca_goster())
        hust.addWidget(self.cb_hoca)
        hust.addStretch()
        hy.addLayout(hust)
        self.t_hoca = _tablo_olustur()
        hy.addWidget(self.t_hoca, stretch=1)
        self.ic_sekmeler.addTab(hoca, "Hoca Programı")
        y.addWidget(self.ic_sekmeler, stretch=1)

    def _alg_degisti(self) -> None:
        self.sp_sure.setEnabled(self.cb_alg.currentData() != ALGORITMA_YAPICI)

    def olustur(self) -> None:
        if not self.servis.donemler():
            QMessageBox.information(self, "Veri yok", "Önce Veri Stüdyosu'nda bir dönem oluşturun.")
            return
        self.btn_olustur.setEnabled(False)
        self.ilerleme.show()
        self._mesgul(True)
        self._isci = CozumIscisi(
            self.db_yolu, str(self.cb_alg.currentData()), float(self.sp_sure.value()), int(self.sp_tohum.value())
        )
        self._isci.bitti.connect(self._bitti)
        self._isci.hata.connect(self._hata)
        self._isci.finished.connect(self._isci_kapandi)
        self._isci.start()

    def _isci_kapandi(self) -> None:
        self.btn_olustur.setEnabled(True)
        self.ilerleme.hide()
        self._mesgul(False)

    def _bitti(self, sonuc: TakvimSonucu) -> None:
        self.yenile(secili=sonuc.kayit_id)
        self.goster(sonuc)

    def _hata(self, baslik: str, ayrinti: list[str]) -> None:
        QMessageBox.warning(self, "Takvim oluşturulamadı", baslik + "\n\n" + "\n".join(f"• {s}" for s in ayrinti[:20]))

    def yenile(self, secili: int | None = None) -> None:
        """Kayıtlı takvim listesini yeniler; liste boşsa ekranı temizler."""
        self.cb_kayit.clear()
        kayitlar = self.servis.calistirmalar() if self.servis.donemler() else []
        for k in kayitlar:
            self.cb_kayit.addItem(
                f"#{k['id']} · {k['zaman']} · {ALGORITMA_ADLAR.get(k['algoritma'], k['algoritma'])} · "
                f"yumuşak ceza {k['toplam_ceza']:.4f}",
                int(k["id"]),
            )
        if secili is not None:
            self.cb_kayit.setCurrentIndex(max(0, self.cb_kayit.findData(secili)))
        if not kayitlar:
            self.goster(None)

    def kayit_ac(self) -> None:
        kimlik = self.cb_kayit.currentData()
        if kimlik is None:
            return
        try:
            self.goster(self.servis.yukle(int(kimlik)))
        except (KayitHatasi, LookupError) as h:
            QMessageBox.warning(self, "Açılamadı", f"Seçili takvim bu veriyle yüklenemedi: {h}")

    def goster(self, sonuc: TakvimSonucu | None) -> None:
        self._sonuc = sonuc
        if sonuc is None:
            for k in (self.k_alg, self.k_yer, self.k_sert, self.k_yum, self.k_iyi, self.k_sure):
                k.ayarla("—")
            for tablo in (self.t_izgara, self.t_liste, self.t_ogrenci, self.t_hoca):
                _tablo_doldur(tablo, [], [])
            self.lbl_filtre.setText("")
            self.sonuc_hazir.emit(None)
            return
        pr = sonuc.problem
        self.k_alg.ayarla(ALGORITMA_ADLAR.get(sonuc.algoritma, sonuc.algoritma))
        self.k_yer.ayarla(f"{pr.E - len(sonuc.cozum.yerlesmemis())} / {pr.E}")
        self.k_sert.ayarla(f"{sonuc.ceza.sert:g}")
        self.k_yum.ayarla(f"{sonuc.ceza.yumusak:.4f}")
        self.k_iyi.ayarla("referans" if sonuc.iyilesme_orani is None else f"%{sonuc.iyilesme_orani * 100:.1f}")
        self.k_sure.ayarla(f"{sonuc.sure_sn:.1f} sn")

        # filtre listeleri bu takvimin verisinden kurulur; önceki seçim mümkünse korunur
        secili_bolum = self.cb_bolum.currentData()
        self.cb_bolum.blockSignals(True)
        self.cb_bolum.clear()
        self.cb_bolum.addItem("Tüm bölümler", None)
        for b in pr.veri.bolumler:
            self.cb_bolum.addItem(f"{b.kod} — {b.ad}", b.id)
        self.cb_bolum.setCurrentIndex(max(0, self.cb_bolum.findData(secili_bolum)))
        self.cb_bolum.blockSignals(False)

        secili_hoca = self.cb_hoca.currentData()
        self.cb_hoca.blockSignals(True)
        self.cb_hoca.clear()
        ders_verenler = {d.hoca_id for d in pr.sinavlar} | {d.asistan_id for d in pr.sinavlar}
        for kisi in pr.personeller:
            if kisi.id in ders_verenler:
                self.cb_hoca.addItem(kisi.tam_ad, kisi.id)
        self.cb_hoca.setCurrentIndex(max(0, self.cb_hoca.findData(secili_hoca)))
        self.cb_hoca.blockSignals(False)

        self._gorunumu_yenile()
        self._ogrenci_ara()
        self._hoca_goster()
        self.sonuc_hazir.emit(sonuc)

    def _gorunumu_yenile(self) -> None:
        """Takvim ızgarasını ve sınav listesini seçili bölüm/sınıfa göre doldurur."""
        if self._sonuc is None:
            return
        pr, cozum = self._sonuc.problem, self._sonuc.cozum
        bolum, sinif = self.cb_bolum.currentData(), self.cb_sinif.currentData()
        secim = None if bolum is None and sinif is None else gorunen_sinavlar(pr, bolum, sinif)
        izgara = takvim_izgarasi(pr, cozum, secim)
        _tablo_doldur(
            self.t_izgara, ["Gün", *izgara.sutunlar],
            [(gun, *("\n".join(h) for h in izgara.hucreler[g])) for g, gun in enumerate(izgara.satirlar)],
        )
        self.t_izgara.resizeRowsToContents()
        liste = sinav_listesi(pr, cozum, secim)
        _tablo_doldur(self.t_liste, list(liste[0]) if liste else [], [tuple(s.values()) for s in liste])
        self.lbl_filtre.setText("" if secim is None else f"{len(secim)} / {pr.E} sınav gösteriliyor")

    def _ogrenci_ara(self) -> None:
        self.cb_ogrenci.blockSignals(True)
        self.cb_ogrenci.clear()
        if self._sonuc is not None:
            pr = self._sonuc.problem
            bolum = {b.id: b.kod for b in pr.veri.bolumler}
            bulunan = ogrenci_bul(pr, self.ed_ogrenci.text())
            for s in bulunan[:100]:
                o = pr.ogrenciler[s]
                self.cb_ogrenci.addItem(f"{o.no} — {o.ad} ({bolum.get(o.bolum_id, '?')}, {o.sinif}. sınıf)", s)
            if self.ed_ogrenci.text().strip():
                fazla = " (ilk 100 gösteriliyor)" if len(bulunan) > 100 else ""
                metin = f"{len(bulunan)} öğrenci bulundu{fazla}." if bulunan else "Öğrenci bulunamadı."
                self.lbl_ogrenci.setText(metin)
            else:
                self.lbl_ogrenci.setText("Programını görmek istediğiniz öğrencinin numarasını ya da adını yazın.")
        self.cb_ogrenci.blockSignals(False)
        self._ogrenci_goster()

    def _ogrenci_goster(self) -> None:
        s = self.cb_ogrenci.currentData()
        if self._sonuc is None or s is None:
            _tablo_doldur(self.t_ogrenci, [], [])
            return
        satirlar = ogrenci_programi(self._sonuc.problem, self._sonuc.cozum, int(s))
        _tablo_doldur(self.t_ogrenci, list(satirlar[0]) if satirlar else [], [tuple(r.values()) for r in satirlar])

    def _hoca_goster(self) -> None:
        kimlik = self.cb_hoca.currentData()
        if self._sonuc is None or kimlik is None:
            _tablo_doldur(self.t_hoca, [], [])
            return
        satirlar = hoca_programi(self._sonuc.problem, self._sonuc.cozum, int(kimlik))
        _tablo_doldur(self.t_hoca, list(satirlar[0]) if satirlar else [], [tuple(r.values()) for r in satirlar])


# ---------------------------------------------------------------------------------------------- Kanıt & Kurallar
class KanitSekmesi(QWidget):
    """Sade kanıt ekranı: takvim kurallara uyuyor mu? Hangi kural ne kadar ceza getirdi? Öğrenciler ne kadar adil?"""

    def __init__(self) -> None:
        super().__init__()
        y = QVBoxLayout(self)
        self.kutu = QFrame()
        self.kutu.setObjectName("uyariKutusu")
        k = QVBoxLayout(self.kutu)
        self.lbl_baslik = QLabel("Henüz gösterilecek bir takvim yok.")
        self.lbl_baslik.setObjectName("bolumBasligi")
        self.lbl_aciklama = QLabel("'Takvim Oluştur' sekmesinde bir takvim üretin ya da kayıtlı bir takvimi açın.")
        self.lbl_aciklama.setWordWrap(True)
        k.addWidget(self.lbl_baslik)
        k.addWidget(self.lbl_aciklama)
        y.addWidget(self.kutu)

        izgara = QGridLayout()
        for sutun, metin in enumerate(("Sert kurallar (asla çiğnenemez)", "Yumuşak kriterler (en aza indirilir)",
                                       "Adalet özeti")):
            lbl = QLabel(metin)
            lbl.setObjectName("bolumBasligi")
            izgara.addWidget(lbl, 0, sutun)
        self.t_sert, self.t_yumusak, self.t_adalet = _tablo_olustur(), _tablo_olustur(), _tablo_olustur()
        for t in (self.t_sert, self.t_yumusak, self.t_adalet):
            t.setWordWrap(True)
        for sutun, t in enumerate((self.t_sert, self.t_yumusak, self.t_adalet)):
            izgara.addWidget(t, 1, sutun)
        izgara.setColumnStretch(0, 3)
        izgara.setColumnStretch(1, 3)
        izgara.setColumnStretch(2, 2)
        y.addLayout(izgara, stretch=1)

    def goster(self, sonuc: TakvimSonucu | None) -> None:
        if sonuc is None:
            self.kutu.setObjectName("uyariKutusu")
            self.lbl_baslik.setText("Henüz gösterilecek bir takvim yok.")
            self.lbl_aciklama.setText("'Takvim Oluştur' sekmesinde bir takvim üretin ya da kayıtlı bir takvimi açın.")
            for t in (self.t_sert, self.t_yumusak, self.t_adalet):
                _tablo_doldur(t, [], [])
        else:
            gecerli = sonuc.dogrulama.gecerli
            self.kutu.setObjectName("kanitBasarili" if gecerli else "kanitHatali")
            self.lbl_baslik.setText(
                "✔ Takvim tüm sert kurallara uyuyor." if gecerli
                else f"✘ Bağımsız doğrulayıcı {len(sonuc.dogrulama.hatalar)} ihlal buldu."
            )
            aciklama = (
                "Bu sonuç, çözücüden ayrı yazılmış bağımsız bir doğrulayıcıdan gelir: her öğrenci, salon ve oturum "
                "basit döngülerle tek tek kontrol edilir."
            )
            if not gecerli:
                aciklama += "\n" + "\n".join(f"• {h.kod}: {h.mesaj}" for h in sonuc.dogrulama.hatalar[:5])
            if sonuc.uyarilar:
                aciklama += "\n⚠ " + "\n⚠ ".join(sonuc.uyarilar[:3])
            self.lbl_aciklama.setText(aciklama)

            sert = [s for s in sonuc.kisit_raporu if s.sert]
            _tablo_doldur(
                self.t_sert, ["Kod", "Kural", "Etkilenen kişi"],
                [(s.kod, s.ad, f"{s.ihlal:g} ✔" if s.ihlal == 0 else f"{s.ihlal:g} ✘") for s in sert],
                esnek_sutun=1,
            )
            yumusak = [s for s in sonuc.kisit_raporu if not s.sert and s.agirlik > 0]
            _tablo_doldur(
                self.t_yumusak, ["Kod", "Kriter", "Ağırlık", "Ceza"],
                [(s.kod, s.ad, f"%{s.agirlik * 100:.1f}", f"{s.ceza:.4f}") for s in yumusak],
                esnek_sutun=1,
            )
            a = sonuc.adalet
            _tablo_doldur(
                self.t_adalet, ["Ölçüt", "Değer"],
                [
                    ("Öğrenci sayısı", a.ogrenci_sayisi),
                    ("Ortalama kişisel ceza", f"{a.ortalama:.4f}"),
                    ("En kötü %10'un ortalaması", f"{a.en_kotu_yuzde10_ortalamasi:.4f}"),
                    ("Hiç cezası olmayan öğrenci", f"%{a.cezasiz_oran * 100:.1f}"),
                    ("Jain eşitlik indeksi (1 = herkes eşit)", f"{a.jain:.3f}"),
                ],
                esnek_sutun=0,
            )
        for t in (self.t_sert, self.t_yumusak, self.t_adalet):
            t.resizeRowsToContents()
        self.kutu.style().unpolish(self.kutu)  # objectName değişince stil yeniden uygulansın
        self.kutu.style().polish(self.kutu)


# ---------------------------------------------------------------------------------------------- ana pencere
class AnaPencere(QMainWindow):
    def __init__(self, db_yolu: Path) -> None:
        super().__init__()
        self.db_yolu = Path(db_yolu)
        self.setWindowTitle("Sınav Takvimi Optimizasyon Sistemi")
        self.resize(1280, 800)
        self.conn = self._baglan()

        self.stud = VeriStudyosuServisi(self.conn)
        self.servis = TakvimServisi(self.conn)

        merkez = QWidget()
        y = QVBoxLayout(merkez)
        baslik = QLabel("Sınav Takvimi Optimizasyon Sistemi")
        baslik.setObjectName("baslik")
        baslik.setToolTip(f"Veritabanı: {self.db_yolu}")  # yalnızca fareyle üzerine gelince (sorun giderme için)
        y.addWidget(baslik)

        self.sekmeler = QTabWidget()
        self.veri_sekmesi = VeriStudyosuSekmesi(self.stud, self._veri_degisti, self._kayit_sayisi)
        self.takvim_sekmesi = TakvimSekmesi(self.servis, self.db_yolu, self._mesgul)
        self.kanit_sekmesi = KanitSekmesi()
        self.takvim_sekmesi.sonuc_hazir.connect(self.kanit_sekmesi.goster)
        self.sekmeler.addTab(self.veri_sekmesi, "1 · Veri Stüdyosu")
        self.sekmeler.addTab(self.takvim_sekmesi, "2 · Takvim Oluştur")
        self.sekmeler.addTab(self.kanit_sekmesi, "3 · Kanıt && Kurallar")  # && → ekranda tek & (Qt kısayol işareti)
        y.addWidget(self.sekmeler, stretch=1)
        self.setCentralWidget(merkez)

        self.veri_sekmesi.yenile()
        self.takvim_sekmesi.yenile()
        self.takvim_sekmesi.kayit_ac()  # en son kayıtlı takvim varsa göster
        self.statusBar().showMessage("Hazır")

    def _baglan(self) -> sqlite3.Connection:
        try:
            return veritabani_baglantisi(self.db_yolu)
        except SemaSurumHatasi as h:
            cevap = QMessageBox.question(
                None, "Veritabanı eski sürümde",
                f"{h}\n\nVeritabanı yeniden kurulsun mu? Eski dosya yedeklenir, AHP anketleri korunur; "
                "dönem verisi yeniden üretilmelidir.",
            )
            if cevap != QMessageBox.StandardButton.Yes:
                raise
            veritabanini_yenile(self.db_yolu)
            return veritabani_baglantisi(self.db_yolu)

    def _kayit_sayisi(self) -> int:
        return len(self.servis.calistirmalar()) if self.servis.donemler() else 0

    def _veri_degisti(self) -> None:
        """Veri değişince eski takvim kayıtları silinir (VeriDeposu.degistir); takvim ve kanıt ekranı temizlenir."""
        self.takvim_sekmesi.yenile()
        self.statusBar().showMessage("Veri kaydedildi.", 4000)

    def _mesgul(self, mesgul: bool) -> None:
        """Çözüm sürerken veri değiştirilemesin (çözücü veritabanını okuyor/yazıyor)."""
        self.sekmeler.setTabEnabled(0, not mesgul)
        self.statusBar().showMessage("Takvim hesaplanıyor…" if mesgul else "Hazır")

    def closeEvent(self, olay: QCloseEvent) -> None:  # Qt'nin sanal metodu; adı Qt'den gelir
        isci = self.takvim_sekmesi._isci
        if isci is not None and isci.isRunning():
            # Çözücünün iptal mekanizması yok; thread'i zorla öldürmek yarım veritabanı kaydı bırakabilir.
            # Bu yüzden pencere kapanmaz, kullanıcıya süre bütçesinin dolmasını beklemesi söylenir.
            QMessageBox.information(
                self, "Hesaplama sürüyor",
                "Takvim hâlâ hesaplanıyor. Seçtiğiniz süre dolunca sonuç kaydedilecek; "
                "sonra pencereyi kapatabilirsiniz.",
            )
            olay.ignore()
            return
        self.conn.close()
        super().closeEvent(olay)
