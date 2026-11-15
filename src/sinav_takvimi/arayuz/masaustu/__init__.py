"""PySide6 masaüstü arayüzü (Veri Stüdyosu + Takvim Oluşturma + Kanıt & Kurallar)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from sinav_takvimi.arayuz.masaustu.ana_pencere import AnaPencere
from sinav_takvimi.arayuz.masaustu.tema import STIL_SAYFASI
from sinav_takvimi.uygulama.takvim_servisi import VARSAYILAN_DB


def uygulamayi_baslat(db_yolu: str | Path | None = None) -> int:
    """Masaüstü uygulamasını başlatır ve olay döngüsü kapanana kadar çalıştırır."""
    mevcut = QApplication.instance()
    app = mevcut if isinstance(mevcut, QApplication) else QApplication(sys.argv)
    app.setApplicationName("Sınav Takvimi Optimizasyon Sistemi")
    app.setStyle("Fusion")
    app.setStyleSheet(STIL_SAYFASI)

    hedef_db = Path(db_yolu or os.environ.get("SINAV_TAKVIMI_DB") or VARSAYILAN_DB)
    try:
        pencere = AnaPencere(db_yolu=hedef_db)
    except Exception as h:  # noqa: BLE001 - .exe konsolsuz: hata bir pencereyle gösterilmeli
        QMessageBox.critical(
            None, "Program başlatılamadı",
            f"Veritabanı açılamadı: {hedef_db}\n\n{type(h).__name__}: {h}\n\n"
            "Program yazma izni olmayan bir klasördeyse (ör. Program Files), klasörü Belgeler gibi yazılabilir bir "
            "yere kopyalayıp oradan açın.",
        )
        return 1
    pencere.show()
    return int(app.exec())


__all__ = ["AnaPencere", "uygulamayi_baslat"]
