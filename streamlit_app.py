"""Streamlit Community Cloud giriş noktası.

Bulutta paket kurulumu yapılmadan `src/` içindeki `sinav_takvimi` paketini kullanır. Veritabanında henüz dönem
yoksa (ilk açılış) sentetik fakülte verisi bir kez üretilir; ardından asıl arayüz (`arayuz/streamlit_app.py`) açılır.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st  # noqa: E402

from sinav_takvimi.altyapi.db import VARSAYILAN_DB, baglan  # noqa: E402
from sinav_takvimi.araclar.sentetik_veri import SentetikAyarlar  # noqa: E402
from sinav_takvimi.arayuz.streamlit_app import calistir  # noqa: E402
from sinav_takvimi.uygulama.veri_servisi import VeriServisi  # noqa: E402


@st.cache_resource(show_spinner=False)
def _ornek_veriyi_hazirla() -> None:
    """Sunucu süreci başına bir kez: veritabanı boşsa sentetik veri üretir (`veri-uret` komutunun karşılığı)."""
    conn = baglan(VARSAYILAN_DB)
    try:
        servis = VeriServisi(conn)
        if not servis.donemler():
            servis.sentetik_uret(SentetikAyarlar())
    finally:
        conn.close()


_ornek_veriyi_hazirla()
calistir()
