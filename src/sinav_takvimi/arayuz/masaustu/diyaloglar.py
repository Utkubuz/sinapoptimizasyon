"""Masaüstü Veri Stüdyosu diyalog pencereleri (elle veri girişi, 'Rastgele Doldur' ve oturum matrisi)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sinav_takvimi.araclar.sentetik_veri import (
    GUNLUK_GOREV_VARSAYIMI,
    SALON_BASI_KOLTUK_VARSAYIMI,
    SINAV_SURESI,
    SentetikAyarlar,
)
from sinav_takvimi.domain.modeller import (
    DERSLIK_TURLERI,
    DONEM_TURLERI,
    UNVANLAR,
    UYGUN_DERSLIK_TURLERI,
    Dilim,
    Ogrenci,
    OgrenciGereksinim,
    VeriSeti,
)
from sinav_takvimi.uygulama.raporlar import GUN_ADLARI
from sinav_takvimi.uygulama.veri_studyosu import (
    DerslikTaslagi,
    DersTaslagi,
    OgrenciTaslagi,
    PersonelTaslagi,
    VeriHatasi,
    VeriStudyosuServisi,
)

_EK_SURE_SECENEKLERI: tuple[tuple[str, float], ...] = (
    ("Yok (%0)", 0.0),
    ("%25 Ek Süre", 0.25),
    ("%50 Ek Süre", 0.50),
)


def _ust_cubuk_rastgele(baslik_metni: str, on_rastgele: Callable[[], None]) -> tuple[QHBoxLayout, QPushButton]:
    satir = QHBoxLayout()
    etiket = QLabel(baslik_metni)
    etiket.setObjectName("bolumBasligi")
    satir.addWidget(etiket)
    satir.addStretch()
    btn = QPushButton("🎲 Rastgele Doldur")
    btn.setObjectName("rastgeleButon")
    btn.clicked.connect(on_rastgele)
    satir.addWidget(btn)
    return satir, btn


def _alt_butonlar(diyalog: QDialog, on_kaydet: Callable[[], None] | None = None) -> QDialogButtonBox:
    kutu = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    ok_btn = kutu.button(QDialogButtonBox.StandardButton.Ok)
    iptal_btn = kutu.button(QDialogButtonBox.StandardButton.Cancel)
    if ok_btn is not None:
        ok_btn.setText("Kaydet")
        ok_btn.setObjectName("birincilButon")
    if iptal_btn is not None:
        iptal_btn.setText("İptal")
    kutu.accepted.connect(on_kaydet if on_kaydet is not None else diyalog.accept)
    kutu.rejected.connect(diyalog.reject)
    return kutu


class HizliFakulteDiyalogu(QDialog):
    """Tek tıkla sentetik fakülte verisi üretmek için parametre diyalogu."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hızlı Fakülte Verisi Üret")
        self.setMinimumWidth(420)

        yerlesim = QVBoxLayout(self)
        aciklama = QLabel(
            "3 mühendislik bölümü, öğretim elemanları, derslikler, zorunlu/seçmeli dersler ve öğrenciler "
            "tek adımda oluşturulur. Mevcut veri yenisiyle değiştirilir."
        )
        aciklama.setWordWrap(True)
        aciklama.setObjectName("altBaslik")
        yerlesim.addWidget(aciklama)

        form = QFormLayout()
        self.sp_ogrenci = QSpinBox()
        self.sp_ogrenci.setRange(15, 300)
        self.sp_ogrenci.setValue(125)
        self.sp_gun = QSpinBox()
        self.sp_gun.setRange(5, 20)
        self.sp_gun.setValue(10)
        self.sp_alttan = QSpinBox()
        self.sp_alttan.setRange(0, 50)
        self.sp_alttan.setSuffix(" %")
        self.sp_alttan.setValue(15)
        self.sp_ozel = QSpinBox()
        self.sp_ozel.setRange(0, 10)
        self.sp_ozel.setSuffix(" %")
        self.sp_ozel.setValue(1)
        self.sp_tohum = QSpinBox()
        self.sp_tohum.setRange(0, 99999)
        self.sp_tohum.setValue(42)

        form.addRow("Bölüm-sınıf başına öğrenci:", self.sp_ogrenci)
        form.addRow("Sınav iş günü sayısı:", self.sp_gun)
        form.addRow("Alttan ders alan öğrenci oranı:", self.sp_alttan)
        form.addRow("Özel gereksinimli öğrenci oranı:", self.sp_ozel)
        form.addRow("Rastgelelik tohumu (seed):", self.sp_tohum)
        yerlesim.addLayout(form)
        yerlesim.addWidget(_alt_butonlar(self))

    def ayarlar(self) -> SentetikAyarlar:
        return SentetikAyarlar(
            tohum=int(self.sp_tohum.value()),
            ogrenci_per_sinif=int(self.sp_ogrenci.value()),
            alttan_orani=float(self.sp_alttan.value()) / 100.0,
            gereksinim_orani=float(self.sp_ozel.value()) / 100.0,
            gun_sayisi=int(self.sp_gun.value()),
        )


class TemizDonemDiyalogu(QDialog):
    """Sıfırdan kendi verisini kurmak isteyen kullanıcı için boş sınav dönemi oluşturma diyalogu."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Temiz Sınav Dönemi Aç")
        self.setMinimumWidth(420)

        yerlesim = QVBoxLayout(self)
        aciklama = QLabel(
            "Öğrenci, hoca, ders ve derslik listelerini sıfırlayarak temiz bir sınav dönemi açar. "
            "Ardından istediğiniz varlıkları elle veya '🎲 Rastgele Ekle' ile ekleyebilirsiniz."
        )
        aciklama.setWordWrap(True)
        aciklama.setObjectName("altBaslik")
        yerlesim.addWidget(aciklama)

        form = QFormLayout()
        self.ed_ad = QLineEdit("2026-2027 Güz Dönemi Finalleri")
        self.cb_tur = QComboBox()
        for tur in sorted(DONEM_TURLERI):  # frozenset sırasız: listede kararlı sıra için sıralanır
            self.cb_tur.addItem(tur.capitalize(), tur)
        self.cb_tur.setCurrentIndex(self.cb_tur.findData("final"))
        self.dt_baslangic = QDateEdit(QDate(2027, 1, 4))
        self.dt_baslangic.setCalendarPopup(True)
        self.dt_baslangic.setDisplayFormat("yyyy-MM-dd")
        self.sp_gun = QSpinBox()
        self.sp_gun.setRange(2, 20)
        self.sp_gun.setValue(10)

        form.addRow("Dönem adı:", self.ed_ad)
        form.addRow("Dönem türü:", self.cb_tur)
        form.addRow("Başlangıç tarihi:", self.dt_baslangic)
        form.addRow("İş günü sayısı:", self.sp_gun)
        yerlesim.addLayout(form)
        yerlesim.addWidget(_alt_butonlar(self))

    def veri_al(self) -> tuple[str, str, date, int]:
        qd = self.dt_baslangic.date()
        return (
            self.ed_ad.text().strip() or "Yeni Sınav Dönemi",
            str(self.cb_tur.currentData()),
            date(qd.year(), qd.month(), qd.day()),
            int(self.sp_gun.value()),
        )


class BolumEkleDiyalogu(QDialog):
    """Yeni bölüm ekleme diyalogu."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Yeni Bölüm Ekle")
        self.setMinimumWidth(360)

        yerlesim = QVBoxLayout(self)
        form = QFormLayout()
        self.ed_kod = QLineEdit()
        self.ed_kod.setPlaceholderText("Örn: EEM")
        self.ed_ad = QLineEdit()
        self.ed_ad.setPlaceholderText("Örn: Elektrik-Elektronik Mühendisliği")
        form.addRow("Bölüm kodu:", self.ed_kod)
        form.addRow("Bölüm adı:", self.ed_ad)
        yerlesim.addLayout(form)
        yerlesim.addWidget(_alt_butonlar(self, self._dogrula_ve_kabul))

    def _dogrula_ve_kabul(self) -> None:
        if not self.ed_kod.text().strip() or not self.ed_ad.text().strip():
            QMessageBox.warning(self, "Eksik Bilgi", "Bölüm kodu ve adı boş bırakılamaz.")
            return
        self.accept()

    def veri_al(self) -> tuple[str, str]:
        return self.ed_kod.text().strip().upper(), self.ed_ad.text().strip()


class PersonelEkleDiyalogu(QDialog):
    """Öğretim elemanı ekleme diyalogu ('🎲 Rastgele Doldur' destekli)."""

    def __init__(self, stud: VeriStudyosuServisi, veri: VeriSeti, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stud = stud
        self._veri = veri
        self._kapali_dilimler: list[int] = []
        self.setWindowTitle("Öğretim Elemanı Ekle")
        self.setMinimumWidth(420)

        yerlesim = QVBoxLayout(self)
        ust_satir, self.btn_rastgele = _ust_cubuk_rastgele("Yeni Öğretim Elemanı", self.rastgele_doldur)
        yerlesim.addLayout(ust_satir)

        form = QFormLayout()
        self.ed_ad = QLineEdit()
        self.ed_ad.setPlaceholderText("Örn: Ayşe Yılmaz")
        self.cb_unvan = QComboBox()
        for u in UNVANLAR:
            self.cb_unvan.addItem(u, u)
        self.cb_unvan.currentTextChanged.connect(self._unvan_degisti)
        self.cb_bolum = QComboBox()
        for b in veri.bolumler:
            self.cb_bolum.addItem(f"{b.kod} — {b.ad}", b.id)
        self.sp_gunluk = QSpinBox()
        self.sp_gunluk.setRange(0, 5)
        self.sp_gunluk.setValue(GUNLUK_GOREV_VARSAYIMI[str(self.cb_unvan.currentData())])

        form.addRow("Ad Soyad:", self.ed_ad)
        form.addRow("Unvan:", self.cb_unvan)
        form.addRow("Bölüm:", self.cb_bolum)
        form.addRow("Günlük maks. görev:", self.sp_gunluk)
        yerlesim.addLayout(form)
        yerlesim.addWidget(_alt_butonlar(self, self._dogrula_ve_kabul))

    def _unvan_degisti(self, unvan: str) -> None:
        # öneri değeri (varsayım); kullanıcı değiştirebilir
        self.sp_gunluk.setValue(GUNLUK_GOREV_VARSAYIMI.get(unvan, self.sp_gunluk.value()))

    def taslak_uygula(self, taslak: PersonelTaslagi) -> None:
        self.ed_ad.setText(taslak.ad)
        idx_u = self.cb_unvan.findData(taslak.unvan)
        if idx_u >= 0:
            self.cb_unvan.setCurrentIndex(idx_u)
        idx_b = self.cb_bolum.findData(taslak.bolum_id)
        if idx_b >= 0:
            self.cb_bolum.setCurrentIndex(idx_b)
        self.sp_gunluk.setValue(taslak.gunluk_max)
        self._kapali_dilimler = list(taslak.kapali_dilimler)

    def rastgele_doldur(self) -> None:
        try:
            self.taslak_uygula(self._stud.rastgele_personel_taslagi())
        except VeriHatasi as hata:
            QMessageBox.warning(self, "Rastgele Üretilemedi", "\n".join(hata.hatalar))

    def _dogrula_ve_kabul(self) -> None:
        if not self.ed_ad.text().strip():
            QMessageBox.warning(self, "Eksik Bilgi", "Öğretim elemanı adı boş olamaz.")
            return
        self.accept()

    def veri_al(self) -> tuple[str, str, int, int, list[int]]:
        return (
            self.ed_ad.text().strip(),
            str(self.cb_unvan.currentData()),
            int(self.cb_bolum.currentData()),
            int(self.sp_gunluk.value()),
            list(self._kapali_dilimler),
        )


class DerslikEkleDiyalogu(QDialog):
    """Derslik ekleme diyalogu ('🎲 Rastgele Doldur' destekli)."""

    _TUR_ETIKETLERI = {
        "normal": "Normal Derslik",
        "amfi": "Amfi",
        "bilgisayar": "Bilgisayar Laboratuvarı",
        "ozel": "Özel Gereksinim Salonu",
    }

    def __init__(self, stud: VeriStudyosuServisi, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stud = stud
        self.setWindowTitle("Derslik Ekle")
        self.setMinimumWidth(420)

        yerlesim = QVBoxLayout(self)
        ust_satir, self.btn_rastgele = _ust_cubuk_rastgele("Yeni Derslik", self.rastgele_doldur)
        yerlesim.addLayout(ust_satir)

        form = QFormLayout()
        self.ed_kod = QLineEdit()
        self.ed_kod.setPlaceholderText("Örn: D-101, AMFI-1, LAB-1")
        self.cb_tur = QComboBox()
        for tur in sorted(DERSLIK_TURLERI):
            self.cb_tur.addItem(self._TUR_ETIKETLERI.get(tur, tur), tur)
        self.cb_tur.currentIndexChanged.connect(self._tur_degisti)

        self.sp_kapasite = QSpinBox()
        self.sp_kapasite.setRange(1, 500)
        self.sp_kapasite.setValue(60)
        self.sp_sinav_kap = QSpinBox()
        self.sp_sinav_kap.setRange(1, 500)
        self.sp_sinav_kap.setValue(30)
        self.sp_sinav_kap.valueChanged.connect(self._sinav_kap_degisti)

        self.chk_erisilebilir = QCheckBox("Engelli / tekerlekli sandalye erişimine uygun")
        self.sp_gozetmen = QSpinBox()
        self.sp_gozetmen.setRange(1, 10)
        self.sp_gozetmen.setValue(1)

        # Başlangıç türü "normal"; sıralı listede ilk öğe "amfi" olduğu için açıkça seçilir ve öneri değerleri yüklenir.
        self.cb_tur.setCurrentIndex(self.cb_tur.findData("normal"))
        self._tur_degisti()

        form.addRow("Derslik kodu:", self.ed_kod)
        form.addRow("Derslik türü:", self.cb_tur)
        form.addRow("Normal kapasite:", self.sp_kapasite)
        form.addRow("Sınav kapasitesi:", self.sp_sinav_kap)
        form.addRow("Erişilebilirlik:", self.chk_erisilebilir)
        form.addRow("Tam dolu gözetmen:", self.sp_gozetmen)
        yerlesim.addLayout(form)
        yerlesim.addWidget(_alt_butonlar(self, self._dogrula_ve_kabul))

    def _tur_degisti(self) -> None:
        """Türe göre ÖNERİ değerleri (sentetik fakültedeki derslik varsayımları); kullanıcı istediği gibi değiştirir."""
        tur = str(self.cb_tur.currentData())
        if tur == "amfi":
            self.sp_kapasite.setValue(200)
            self.sp_sinav_kap.setValue(100)
            self.chk_erisilebilir.setChecked(True)
        elif tur == "bilgisayar":
            self.sp_kapasite.setValue(40)
            self.sp_sinav_kap.setValue(40)
        elif tur == "ozel":
            self.sp_kapasite.setValue(8)
            self.sp_sinav_kap.setValue(8)
            self.chk_erisilebilir.setChecked(True)
        else:
            self.sp_kapasite.setValue(60)
            self.sp_sinav_kap.setValue(30)

    def _sinav_kap_degisti(self, s_kap: int) -> None:
        if s_kap > self.sp_kapasite.value():
            self.sp_kapasite.setValue(s_kap)
        self.sp_gozetmen.setValue(max(1, -(-s_kap // SALON_BASI_KOLTUK_VARSAYIMI)))

    def taslak_uygula(self, taslak: DerslikTaslagi) -> None:
        self.ed_kod.setText(taslak.kod)
        idx = self.cb_tur.findData(taslak.tur)
        if idx >= 0:
            self.cb_tur.blockSignals(True)
            self.cb_tur.setCurrentIndex(idx)
            self.cb_tur.blockSignals(False)
        self.sp_kapasite.setValue(taslak.kapasite)
        self.sp_sinav_kap.setValue(taslak.sinav_kapasitesi)
        self.chk_erisilebilir.setChecked(taslak.erisilebilir)
        self.sp_gozetmen.setValue(taslak.gozetmen_sayisi)

    def rastgele_doldur(self) -> None:
        try:
            self.taslak_uygula(self._stud.rastgele_derslik_taslagi())
        except VeriHatasi as hata:
            QMessageBox.warning(self, "Rastgele Üretilemedi", "\n".join(hata.hatalar))

    def _dogrula_ve_kabul(self) -> None:
        if not self.ed_kod.text().strip():
            QMessageBox.warning(self, "Eksik Bilgi", "Derslik kodu boş olamaz.")
            return
        if self.sp_sinav_kap.value() > self.sp_kapasite.value():
            QMessageBox.warning(self, "Geçersiz Kapasite", "Sınav kapasitesi normal kapasiteden büyük olamaz.")
            return
        self.accept()

    def veri_al(self) -> tuple[str, str, int, int, bool, int]:
        return (
            self.ed_kod.text().strip().upper(),
            str(self.cb_tur.currentData()),
            int(self.sp_kapasite.value()),
            int(self.sp_sinav_kap.value()),
            bool(self.chk_erisilebilir.isChecked()),
            int(self.sp_gozetmen.value()),
        )


class DersEkleDiyalogu(QDialog):
    """Ders ekleme diyalogu ('🎲 Rastgele Doldur' destekli)."""

    def __init__(self, stud: VeriStudyosuServisi, veri: VeriSeti, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stud = stud
        self._veri = veri
        self.setWindowTitle("Ders Ekle")
        self.setMinimumWidth(460)

        yerlesim = QVBoxLayout(self)
        ust_satir, self.btn_rastgele = _ust_cubuk_rastgele("Yeni Ders", self.rastgele_doldur)
        yerlesim.addLayout(ust_satir)

        form = QFormLayout()
        self.ed_kod = QLineEdit()
        self.ed_kod.setPlaceholderText("Örn: END101, MAT101")
        self.ed_ad = QLineEdit()
        self.ed_ad.setPlaceholderText("Örn: Yöneylem Araştırması I")

        self.cb_bolum = QComboBox()
        self.cb_bolum.addItem("Ortak Ders (Tüm Bölümler)", None)
        for b in veri.bolumler:
            self.cb_bolum.addItem(f"{b.kod} — {b.ad}", b.id)

        self.sp_sinif = QSpinBox()
        self.sp_sinif.setRange(1, 4)
        self.sp_sinif.setValue(1)

        self.sp_zorluk = QSpinBox()
        self.sp_zorluk.setRange(1, 5)
        self.sp_zorluk.setValue(3)
        self.sp_zorluk.valueChanged.connect(self._zorluk_degisti)

        self.cb_tur = QComboBox()
        for tur in UYGUN_DERSLIK_TURLERI:
            etiket = "Yazılı Sınav (Normal/Amfi)" if tur == "yazili" else "Bilgisayar Sınavı (Lab)"
            self.cb_tur.addItem(etiket, tur)

        self.sp_sure = QSpinBox()
        self.sp_sure.setRange(30, 180)
        self.sp_sure.setSingleStep(15)
        self.sp_sure.setSuffix(" dk")
        self.sp_sure.setValue(SINAV_SURESI[3])

        self.cb_hoca = QComboBox()
        self.cb_asistan = QComboBox()
        self.cb_asistan.addItem("Yok", None)
        for p in veri.personeller:
            self.cb_hoca.addItem(f"{p.tam_ad}", p.id)
            self.cb_asistan.addItem(f"{p.tam_ad}", p.id)

        form.addRow("Ders kodu:", self.ed_kod)
        form.addRow("Ders adı:", self.ed_ad)
        form.addRow("Bölüm:", self.cb_bolum)
        form.addRow("Sınıf:", self.sp_sinif)
        form.addRow("Zorluk (1–5):", self.sp_zorluk)
        form.addRow("Sınav türü:", self.cb_tur)
        form.addRow("Sınav süresi:", self.sp_sure)
        form.addRow("Dersi veren hoca:", self.cb_hoca)
        form.addRow("Asistan:", self.cb_asistan)
        yerlesim.addLayout(form)
        yerlesim.addWidget(_alt_butonlar(self, self._dogrula_ve_kabul))

    def _zorluk_degisti(self, zorluk: int) -> None:
        if zorluk in SINAV_SURESI:
            self.sp_sure.setValue(SINAV_SURESI[zorluk])

    def taslak_uygula(self, taslak: DersTaslagi) -> None:
        self.ed_kod.setText(taslak.kod)
        self.ed_ad.setText(taslak.ad)
        idx_b = self.cb_bolum.findData(taslak.bolum_id)
        if idx_b >= 0:
            self.cb_bolum.setCurrentIndex(idx_b)
        self.sp_sinif.setValue(taslak.sinif)
        self.sp_zorluk.setValue(taslak.zorluk)
        idx_t = self.cb_tur.findData(taslak.sinav_turu)
        if idx_t >= 0:
            self.cb_tur.setCurrentIndex(idx_t)
        self.sp_sure.setValue(taslak.sinav_suresi_dk)
        idx_h = self.cb_hoca.findData(taslak.hoca_id)
        if idx_h >= 0:
            self.cb_hoca.setCurrentIndex(idx_h)
        idx_a = self.cb_asistan.findData(taslak.asistan_id)
        if idx_a >= 0:
            self.cb_asistan.setCurrentIndex(idx_a)

    def rastgele_doldur(self) -> None:
        try:
            self.taslak_uygula(self._stud.rastgele_ders_taslagi())
        except VeriHatasi as hata:
            QMessageBox.warning(self, "Rastgele Üretilemedi", "\n".join(hata.hatalar))

    def _dogrula_ve_kabul(self) -> None:
        if not self.ed_kod.text().strip() or not self.ed_ad.text().strip():
            QMessageBox.warning(self, "Eksik Bilgi", "Ders kodu ve ders adı boş olamaz.")
            return
        if self.cb_hoca.count() == 0:
            QMessageBox.warning(self, "Eksik Bilgi", "Önce en az bir öğretim elemanı eklemelisiniz.")
            return
        self.accept()

    def veri_al(self) -> tuple[str, str, int | None, int, int, str, int, int, int | None]:
        bolum_data = self.cb_bolum.currentData()
        asistan_data = self.cb_asistan.currentData()
        hoca_id = int(self.cb_hoca.currentData())
        asistan_id = int(asistan_data) if asistan_data is not None and int(asistan_data) != hoca_id else None
        return (
            self.ed_kod.text().strip().upper(),
            self.ed_ad.text().strip(),
            int(bolum_data) if bolum_data is not None else None,
            int(self.sp_sinif.value()),
            int(self.sp_zorluk.value()),
            str(self.cb_tur.currentData()),
            int(self.sp_sure.value()),
            hoca_id,
            asistan_id,
        )


class OgrenciDiyalogu(QDialog):
    """Yeni öğrenci ekleme ('🎲 Rastgele Doldur' destekli) ya da mevcut öğrencinin ders/gereksinim düzenlemesi."""

    def __init__(
        self,
        stud: VeriStudyosuServisi,
        veri: VeriSeti,
        *,
        mevcut_ogrenci: Ogrenci | None = None,
        mevcut_dersler: set[int] | None = None,
        mevcut_gereksinim: OgrenciGereksinim | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._stud = stud
        self._veri = veri
        self._duzenleme_modu = mevcut_ogrenci is not None
        self.setWindowTitle("Öğrenci Ders & Gereksinim Düzenle" if self._duzenleme_modu else "Öğrenci Ekle")
        self.setMinimumSize(500, 520)

        yerlesim = QVBoxLayout(self)
        if not self._duzenleme_modu:
            ust_satir, self.btn_rastgele = _ust_cubuk_rastgele("Yeni Öğrenci", self.rastgele_doldur)
            yerlesim.addLayout(ust_satir)

        form = QFormLayout()
        self.ed_no = QLineEdit()
        self.ed_no.setPlaceholderText("Örn: 26010001")
        self.ed_ad = QLineEdit()
        self.ed_ad.setPlaceholderText("Örn: Mehmet Demir")
        self.cb_bolum = QComboBox()
        for b in veri.bolumler:
            self.cb_bolum.addItem(f"{b.kod} — {b.ad}", b.id)
        self.sp_sinif = QSpinBox()
        self.sp_sinif.setRange(1, 4)
        self.sp_sinif.setValue(1)

        self.chk_erisilebilir = QCheckBox("Erişilebilir salon gerekir")
        self.chk_ayri = QCheckBox("Ayrı salon + ayrı gözetmen gerekir")
        self.cb_ek_sure = QComboBox()
        for etiket, oran in _EK_SURE_SECENEKLERI:
            self.cb_ek_sure.addItem(etiket, oran)

        form.addRow("Öğrenci no:", self.ed_no)
        form.addRow("Ad Soyad:", self.ed_ad)
        form.addRow("Bölüm:", self.cb_bolum)
        form.addRow("Sınıf:", self.sp_sinif)
        form.addRow("Erişilebilirlik:", self.chk_erisilebilir)
        form.addRow("Ayrı salon:", self.chk_ayri)
        form.addRow("Ek süre:", self.cb_ek_sure)
        yerlesim.addLayout(form)

        # Ders kayıtları seçim listesi
        ders_ust = QHBoxLayout()
        ders_etiket = QLabel("Kayıtlı Olduğu Dersler")
        ders_etiket.setObjectName("bolumBasligi")
        ders_ust.addWidget(ders_etiket)
        ders_ust.addStretch()
        btn_kohort = QPushButton("Bölüm & Sınıf Derslerini Seç")
        btn_kohort.clicked.connect(self.bolum_sinif_derslerini_sec)
        btn_temizle = QPushButton("Seçimi Temizle")
        btn_temizle.clicked.connect(lambda: self._secili_dersleri_ayarla(set()))
        ders_ust.addWidget(btn_kohort)
        ders_ust.addWidget(btn_temizle)
        yerlesim.addLayout(ders_ust)

        bolum_kod = {b.id: b.kod for b in veri.bolumler}
        self.lst_dersler = QListWidget()
        for d in sorted(veri.dersler, key=lambda x: (x.sinif, x.kod)):
            b_etiket = bolum_kod.get(d.bolum_id, "ORTAK") if d.bolum_id is not None else "ORTAK"
            oge = QListWidgetItem(f"{d.kod} — {d.ad} ({b_etiket}, {d.sinif}. sınıf)")
            oge.setData(Qt.ItemDataRole.UserRole, d.id)
            oge.setFlags(oge.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            oge.setCheckState(Qt.CheckState.Unchecked)
            self.lst_dersler.addItem(oge)
        yerlesim.addWidget(self.lst_dersler, stretch=1)

        if mevcut_ogrenci is not None:
            self.ed_no.setText(mevcut_ogrenci.no)
            self.ed_no.setReadOnly(True)
            self.ed_ad.setText(mevcut_ogrenci.ad)
            self.ed_ad.setReadOnly(True)
            idx_b = self.cb_bolum.findData(mevcut_ogrenci.bolum_id)
            if idx_b >= 0:
                self.cb_bolum.setCurrentIndex(idx_b)
            self.cb_bolum.setEnabled(False)
            self.sp_sinif.setValue(mevcut_ogrenci.sinif)
            self.sp_sinif.setEnabled(False)
            self._secili_dersleri_ayarla(mevcut_dersler or set())
            if mevcut_gereksinim is not None:
                self.chk_erisilebilir.setChecked(mevcut_gereksinim.erisilebilir_salon)
                self.chk_ayri.setChecked(mevcut_gereksinim.ayri_salon)
                en_yakin_idx = min(
                    range(len(_EK_SURE_SECENEKLERI)),
                    key=lambda i: abs(_EK_SURE_SECENEKLERI[i][1] - mevcut_gereksinim.ek_sure_orani),
                )
                self.cb_ek_sure.setCurrentIndex(en_yakin_idx)

        yerlesim.addWidget(_alt_butonlar(self, self._dogrula_ve_kabul))

    def _secili_dersleri_ayarla(self, secili: set[int]) -> None:
        for i in range(self.lst_dersler.count()):
            oge = self.lst_dersler.item(i)
            if oge is not None:
                did = int(oge.data(Qt.ItemDataRole.UserRole))
                oge.setCheckState(Qt.CheckState.Checked if did in secili else Qt.CheckState.Unchecked)

    def bolum_sinif_derslerini_sec(self) -> None:
        bolum_id = int(self.cb_bolum.currentData())
        sinif = int(self.sp_sinif.value())
        uygun = {
            d.id for d in self._veri.dersler if (d.bolum_id is None or d.bolum_id == bolum_id) and d.sinif == sinif
        }
        self._secili_dersleri_ayarla(uygun)

    def taslak_uygula(self, taslak: OgrenciTaslagi) -> None:
        self.ed_no.setText(taslak.no)
        self.ed_ad.setText(taslak.ad)
        idx_b = self.cb_bolum.findData(taslak.bolum_id)
        if idx_b >= 0:
            self.cb_bolum.setCurrentIndex(idx_b)
        self.sp_sinif.setValue(taslak.sinif)
        self.chk_erisilebilir.setChecked(taslak.erisilebilir_salon)
        self.chk_ayri.setChecked(taslak.ayri_salon)
        en_yakin_idx = min(
            range(len(_EK_SURE_SECENEKLERI)),
            key=lambda i: abs(_EK_SURE_SECENEKLERI[i][1] - taslak.ek_sure_orani),
        )
        self.cb_ek_sure.setCurrentIndex(en_yakin_idx)
        self._secili_dersleri_ayarla(set(taslak.ders_idleri))

    def rastgele_doldur(self) -> None:
        try:
            self.taslak_uygula(self._stud.rastgele_ogrenci_taslagi())
        except VeriHatasi as hata:
            QMessageBox.warning(self, "Rastgele Üretilemedi", "\n".join(hata.hatalar))

    def _dogrula_ve_kabul(self) -> None:
        if not self.ed_no.text().strip() or not self.ed_ad.text().strip():
            QMessageBox.warning(self, "Eksik Bilgi", "Öğrenci numarası ve adı boş olamaz.")
            return
        self.accept()

    def secili_ders_idleri(self) -> list[int]:
        secilen: list[int] = []
        for i in range(self.lst_dersler.count()):
            oge = self.lst_dersler.item(i)
            if oge is not None and oge.checkState() == Qt.CheckState.Checked:
                secilen.append(int(oge.data(Qt.ItemDataRole.UserRole)))
        return secilen

    def veri_al(self) -> tuple[str, str, int, int, list[int], bool, bool, float]:
        return (
            self.ed_no.text().strip(),
            self.ed_ad.text().strip(),
            int(self.cb_bolum.currentData()),
            int(self.sp_sinif.value()),
            self.secili_ders_idleri(),
            bool(self.chk_erisilebilir.isChecked()),
            bool(self.chk_ayri.isChecked()),
            float(self.cb_ek_sure.currentData()),
        )


class OturumMatrisiDiyalogu(QDialog):
    """Gün × oturum matrisinde tıklayarak müsaitlik (personel/derslik) ya da ders kuralı (zorunlu/yasak) düzenler."""

    def __init__(
        self,
        baslik: str,
        dilimler: list[Dilim],
        *,
        mod: str = "musaitlik",
        kapali_dilimler: set[int] | None = None,
        ders_kurallari: dict[int, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._mod = mod
        self._durum: dict[int, str] = {}
        if mod == "musaitlik":
            for dl in dilimler:
                self._durum[dl.id] = "kapali" if (kapali_dilimler and dl.id in kapali_dilimler) else "acik"
        else:
            for dl in dilimler:
                self._durum[dl.id] = (ders_kurallari or {}).get(dl.id, "normal")

        self.setWindowTitle(baslik)
        self.setMinimumSize(700, 440)

        yerlesim = QVBoxLayout(self)
        ipucu = (
            "Hücrelere tıklayarak oturumu 'Müsait' ↔ 'Kapalı' arasında değiştirebilirsiniz."
            if mod == "musaitlik"
            else "Hücrelere tıklayarak oturumu 'Normal' → 'Zorunlu (Sabit)' → 'Yasak' arasında değiştirebilirsiniz."
        )
        lbl = QLabel(ipucu)
        lbl.setObjectName("altBaslik")
        yerlesim.addWidget(lbl)

        gunler = sorted({d.gun for d in dilimler})
        siralar = sorted({d.sira for d in dilimler})
        gun_etiket: dict[int, str] = {}
        sira_etiket: dict[int, str] = {}
        self._hucre_dilim: dict[tuple[int, int], int] = {}

        gun_indeks = {g: i for i, g in enumerate(gunler)}
        sira_indeks = {s: j for j, s in enumerate(siralar)}
        for dl in dilimler:
            hafta_gunu = GUN_ADLARI[date.fromisoformat(dl.tarih).weekday()]
            gun_etiket.setdefault(dl.gun, f"{dl.tarih} {hafta_gunu}")
            sira_etiket.setdefault(dl.sira, f"{dl.sira + 1}. Oturum ({dl.baslangic})")
            self._hucre_dilim[(gun_indeks[dl.gun], sira_indeks[dl.sira])] = dl.id

        self.tablo = QTableWidget(len(gunler), len(siralar))
        self.tablo.setVerticalHeaderLabels([gun_etiket[g] for g in gunler])
        self.tablo.setHorizontalHeaderLabels([sira_etiket[s] for s in siralar])
        self.tablo.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tablo.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tablo.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.tablo.cellClicked.connect(self.hucre_tikla)

        for r in range(len(gunler)):
            for c in range(len(siralar)):
                oge = QTableWidgetItem()
                oge.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                did = self._hucre_dilim.get((r, c))
                if did is None:
                    oge.setText("—")
                    oge.setBackground(QColor("#F1F5F9"))
                    oge.setForeground(QColor("#94A3B8"))
                self.tablo.setItem(r, c, oge)
                if did is not None:
                    self._hucre_boya(r, c, self._durum[did])

        yerlesim.addWidget(self.tablo, stretch=1)

        alt_cubuk = QHBoxLayout()
        btn_sifirla = QPushButton("Tümünü Normal / Müsait Yap")
        btn_sifirla.clicked.connect(self.tumunu_sifirla)
        alt_cubuk.addWidget(btn_sifirla)
        alt_cubuk.addStretch()
        alt_cubuk.addWidget(_alt_butonlar(self))
        yerlesim.addLayout(alt_cubuk)

    def _hucre_boya(self, satir: int, sutun: int, durum: str) -> None:
        oge = self.tablo.item(satir, sutun)
        if oge is None:
            return
        if durum == "acik":
            oge.setText("Müsait")
            oge.setBackground(QColor("#F0FDF4"))
            oge.setForeground(QColor("#166534"))
        elif durum == "kapali":
            oge.setText("Kapalı")
            oge.setBackground(QColor("#FEE2E2"))
            oge.setForeground(QColor("#991B1B"))
        elif durum == "zorunlu":
            oge.setText("Zorunlu")
            oge.setBackground(QColor("#DBEAFE"))
            oge.setForeground(QColor("#1E40AF"))
        elif durum == "yasak":
            oge.setText("Yasak")
            oge.setBackground(QColor("#FEE2E2"))
            oge.setForeground(QColor("#991B1B"))
        else:
            oge.setText("Normal")
            oge.setBackground(QColor("#FFFFFF"))
            oge.setForeground(QColor("#334155"))

    def hucre_tikla(self, satir: int, sutun: int) -> None:
        did = self._hucre_dilim.get((satir, sutun))
        if did is None:
            return
        mevcut = self._durum[did]
        if self._mod == "musaitlik":
            yeni = "kapali" if mevcut == "acik" else "acik"
        else:
            dongu = {"normal": "zorunlu", "zorunlu": "yasak", "yasak": "normal"}
            yeni = dongu.get(mevcut, "normal")
        self._durum[did] = yeni
        self._hucre_boya(satir, sutun, yeni)

    def tumunu_sifirla(self) -> None:
        varsayilan = "acik" if self._mod == "musaitlik" else "normal"
        for (r, c), did in self._hucre_dilim.items():
            self._durum[did] = varsayilan
            self._hucre_boya(r, c, varsayilan)

    def kapali_dilim_idleri(self) -> list[int]:
        return sorted(did for did, d in self._durum.items() if d == "kapali")

    def ders_kurallari_listesi(self) -> list[tuple[int, str, str]]:
        return sorted((did, d, "Arayüz kuralı") for did, d in self._durum.items() if d in ("zorunlu", "yasak"))
