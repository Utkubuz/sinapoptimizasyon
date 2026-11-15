"""Masaüstü arayüzü görsel teması (sade, ferah, akademik açık renk paleti)."""

from __future__ import annotations

STIL_SAYFASI = """
QMainWindow, QDialog {
    background-color: #F8FAFC;
    color: #0F172A;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}

QWidget {
    color: #0F172A;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}

QFrame#kart, QFrame#ozetRozet {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
}

QFrame#kanitBasarili {
    background-color: #F0FDF4;
    border: 1px solid #86EFAC;
    border-radius: 8px;
}

QFrame#kanitHatali {
    background-color: #FEF2F2;
    border: 1px solid #FCA5A5;
    border-radius: 8px;
}

QFrame#uyariKutusu {
    background-color: #FFFBEB;
    border: 1px solid #FCD34D;
    border-radius: 8px;
}

QLabel#baslik {
    font-size: 18px;
    font-weight: 700;
    color: #0F172A;
}

QLabel#altBaslik {
    font-size: 12px;
    color: #475569;
}

QLabel#bolumBasligi {
    font-size: 14px;
    font-weight: 600;
    color: #1E293B;
}

QLabel#metrikEtiket {
    font-size: 11px;
    font-weight: 600;
    color: #64748B;
}

QLabel#metrikDeger {
    font-size: 19px;
    font-weight: 700;
    color: #0F172A;
}

QLabel#metrikAlt {
    font-size: 11px;
    color: #475569;
}

QTabWidget::pane {
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    background-color: #FFFFFF;
    top: -1px;
}

QTabBar::tab {
    background-color: #F1F5F9;
    color: #475569;
    border: 1px solid #E2E8F0;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 18px;
    margin-right: 4px;
    font-weight: 600;
}

QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #1D4ED8;
    border-bottom: 2px solid #2563EB;
}

QTabBar::tab:hover:!selected {
    background-color: #E2E8F0;
}

QPushButton {
    background-color: #FFFFFF;
    color: #1E293B;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 6px 13px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #F1F5F9;
    border-color: #94A3B8;
}

QPushButton:disabled {
    background-color: #F1F5F9;
    color: #94A3B8;
    border-color: #E2E8F0;
}

QPushButton#birincilButon {
    background-color: #2563EB;
    color: #FFFFFF;
    border: 1px solid #1D4ED8;
    padding: 7px 16px;
}

QPushButton#birincilButon:hover {
    background-color: #1D4ED8;
}

QPushButton#birincilButon:disabled {
    background-color: #93C5FD;
    border-color: #93C5FD;
    color: #FFFFFF;
}

QPushButton#rastgeleButon {
    background-color: #F0FDFA;
    color: #0F766E;
    border: 1px solid #99F6E4;
}

QPushButton#rastgeleButon:hover {
    background-color: #CCFBF1;
    border-color: #5EEAD4;
}

QPushButton#tehlikeButon {
    background-color: #FFFFFF;
    color: #DC2626;
    border: 1px solid #FECACA;
}

QPushButton#tehlikeButon:hover {
    background-color: #FEF2F2;
    border-color: #F87171;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 5px 9px;
    min-height: 22px;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {
    border: 1px solid #2563EB;
}

QTableWidget {
    background-color: #FFFFFF;
    alternate-background-color: #F8FAFC;
    gridline-color: #E2E8F0;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    selection-background-color: #DBEAFE;
    selection-color: #0F172A;
}

QHeaderView::section {
    background-color: #F1F5F9;
    color: #334155;
    font-weight: 600;
    padding: 7px 8px;
    border: none;
    border-right: 1px solid #E2E8F0;
    border-bottom: 1px solid #CBD5E1;
}

QStatusBar {
    background-color: #FFFFFF;
    color: #475569;
    border-top: 1px solid #E2E8F0;
}
"""
