"""Streamlit arayüzü: veri özeti, algoritma ve süre seçimiyle takvim oluşturma, yakınsama eğrisi, kısıt ve
adalet raporları.

Çalıştırma (proje kökünden):
    .venv\\Scripts\\streamlit run src\\sinav_takvimi\\arayuz\\streamlit_app.py

Eşzamanlılık kuralı: `@st.cache_resource` ile tek bir paylaşılan SQLite bağlantısı KULLANILMAZ; iki tarayıcı
sekmesi aynı bağlantıda işlem (`with conn:`) açarsa birbirinin işlemini bozar. Bunun yerine her kullanıcı oturumu
(`st.session_state`) kendi bağlantısını tutar.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Protocol

import streamlit as st

from sinav_takvimi.uygulama.raporlar import adalet_satirlari, kisit_satirlari, sinav_listesi, takvim_izgarasi
from sinav_takvimi.uygulama.takvim_servisi import (
    ALGORITMA_ADLAR,
    ALGORITMA_KARSILASTIR,
    ALGORITMA_TABU,
    ALGORITMA_YAPICI,
    GECERLI_ALGORITMALAR,
    VARSAYILAN_ALGORITMA,
    VARSAYILAN_DB,
    KayitHatasi,
    SemaSurumHatasi,
    TakvimServisi,
    TakvimSonucu,
    TakvimUretilemedi,
    veritabani_baglantisi,
)
from sinav_takvimi.uygulama.veri_servisi import VeriHatasi

_CONN_ANAHTAR = "_sinav_db_baglantisi"
_YOL_ANAHTAR = "_sinav_db_yolu"
_ARAYUZ_SECENEKLERI: dict[str, str] = {
    **ALGORITMA_ADLAR,
    ALGORITMA_KARSILASTIR: "Üçünü Karşılaştır (Yapıcı + Tavlama + Tabu)",
}


class OturumDurumu(Protocol):
    """Hem `st.session_state` (`SessionStateProxy`) hem testteki düz `dict` bu yapısal arayüzü sağlar."""

    def get(self, key: str, /) -> Any: ...
    def __setitem__(self, key: str, value: Any, /) -> None: ...


def oturum_baglantisi(durum: OturumDurumu, yol: str | Path = VARSAYILAN_DB) -> sqlite3.Connection:
    """Kullanıcı oturumu (`st.session_state`) başına ayrı SQLite bağlantısı verir (paylaşılan bağlantı yok)."""
    hedef = str(Path(yol).resolve()) if str(yol) != ":memory:" else ":memory:"
    mevcut: sqlite3.Connection | None = durum.get(_CONN_ANAHTAR)
    if mevcut is not None and durum.get(_YOL_ANAHTAR) == hedef:
        return mevcut
    if mevcut is not None:
        mevcut.close()
    yeni = veritabani_baglantisi(hedef)
    durum[_CONN_ANAHTAR] = yeni
    durum[_YOL_ANAHTAR] = hedef
    return yeni


def _sonucu_goster(sonuc: TakvimSonucu) -> None:
    pr = sonuc.problem
    ust = st.columns(6)
    ust[0].metric("Algoritma", ALGORITMA_ADLAR.get(sonuc.algoritma, sonuc.algoritma))
    ust[1].metric("Yerleşen sınav", f"{pr.E - len(sonuc.cozum.yerlesmemis())} / {pr.E}")
    ust[2].metric("Sert ihlal", f"{sonuc.ceza.sert:g}")
    ust[3].metric("Yumuşak ceza", f"{sonuc.ceza.yumusak:.4f}")
    iyil_metin = f"%{sonuc.iyilesme_orani * 100:.1f}" if sonuc.iyilesme_orani is not None else "Referans"
    ust[4].metric("Yapıcıya göre iyileşme", iyil_metin)
    ust[5].metric("Doğrulayıcı", "Geçerli" if sonuc.dogrulama.gecerli else "İhlal var")

    if not sonuc.dogrulama.gecerli:
        st.error("Bağımsız doğrulayıcı sert kural ihlali buldu:")
        for h in sonuc.dogrulama.hatalar[:20]:
            st.write(f"- **{h.kod}**: {h.mesaj}")
    for uyari in sonuc.uyarilar:
        st.warning(uyari)

    if sonuc.algoritma != ALGORITMA_YAPICI and len(sonuc.gecmis) >= 2:
        with st.expander("Yakınsama eğrisi (saniye → en iyi yumuşak ceza)", expanded=True):
            st.line_chart(
                {
                    "Saniye": [nokta[0] for nokta in sonuc.gecmis],
                    "Mevcut ceza": [nokta[1] for nokta in sonuc.gecmis],
                    "En iyi ceza": [nokta[2] for nokta in sonuc.gecmis],
                },
                x="Saniye",
                y=["Mevcut ceza", "En iyi ceza"],
            )

    st.subheader("Takvim Tablosu (Gün × Oturum)")
    izgara = takvim_izgarasi(pr, sonuc.cozum)
    st.dataframe(izgara.metin_tablosu(), width="stretch", hide_index=True)
    with st.expander("Sınav ve derslik atamaları (ayrıntılı liste)"):
        st.dataframe(sinav_listesi(pr, sonuc.cozum), width="stretch", hide_index=True)

    st.subheader("Kısıt Raporu")
    st.dataframe(kisit_satirlari(sonuc.kisit_raporu), width="stretch", hide_index=True)
    if sonuc.referans:
        olcek_metni = ", ".join(
            f"{k}={v:.4g} ({sonuc.referans_kaynagi.get(k, '?')})" for k, v in sonuc.referans.items()
        )
        st.caption(f"Referans ölçekleri (doğal değer): {olcek_metni}")

    st.subheader("Adalet Özeti (Çift Başına Kişisel Ceza)")
    sol, sag = st.columns(2)
    with sol:
        st.dataframe(
            [{"Ölçüt": ad, "Değer": deger} for ad, deger in adalet_satirlari(sonuc.adalet)],
            width="stretch",
            hide_index=True,
        )
    with sag:
        kohort_tablo = [
            {
                "Bölüm": k.bolum_kod,
                "Sınıf": k.sinif,
                "Öğrenci": k.ogrenci,
                "Ortalama ceza": round(k.ortalama_ceza, 4),
            }
            for k in sonuc.adalet.kohortlar
        ]
        st.dataframe(kohort_tablo, width="stretch", hide_index=True)


def calistir(db_yolu: str | Path | None = None) -> None:
    st.set_page_config(page_title="Sınav Takvimi Optimizasyonu", layout="wide")
    st.title("Sınav Takvimi Optimizasyon Sistemi")

    yol = db_yolu or os.environ.get("SINAV_TAKVIMI_DB") or VARSAYILAN_DB
    try:
        conn = oturum_baglantisi(st.session_state, yol)
    except SemaSurumHatasi as hata:
        st.error(str(hata))
        return

    servis = TakvimServisi(conn)
    donemler = servis.donemler()
    if not donemler:
        st.info(
            "Veritabanında henüz sınav dönemi yok. Önce komut satırından "
            "`python -m sinav_takvimi veri-uret` ya da `csv-yukle` çalıştırın."
        )
        return

    secenekler = {d.id: f"{d.ad} ({d.tur}, {d.baslangic} – {d.bitis})" for d in donemler}
    donem_id = st.selectbox("Sınav dönemi", options=list(secenekler), format_func=lambda x: secenekler[x])
    assert donem_id is not None

    st.subheader("Veri Özeti")
    ozet = servis.veri_ozeti(donem_id)
    sutunlar = st.columns(4)
    for i, (ad, sayi) in enumerate(ozet.items()):
        sutunlar[i % 4].metric(ad, sayi)

    ayar_sutun = st.columns(3)
    alg_anahtarlar = [*GECERLI_ALGORITMALAR, ALGORITMA_KARSILASTIR]
    varsayilan_alg_indeks = alg_anahtarlar.index(VARSAYILAN_ALGORITMA)
    with ayar_sutun[0]:
        secili_alg = st.selectbox(
            "Çözüm algoritması",
            options=alg_anahtarlar,
            index=varsayilan_alg_indeks,
            format_func=lambda k: _ARAYUZ_SECENEKLERI[k],
        )
    with ayar_sutun[1]:
        varsayilan_sure = (
            servis.ayarlar.tabu.sure_sn if secili_alg == ALGORITMA_TABU else servis.ayarlar.tavlama.sure_sn
        )
        sure_sn = float(
            st.slider(
                "Metasezgisel süre bütçesi (saniye)",
                min_value=1,
                max_value=60,
                value=int(varsayilan_sure),
                disabled=(secili_alg == ALGORITMA_YAPICI),
            )
        )
    with ayar_sutun[2]:
        tohum = int(st.number_input("Rastgelelik tohumu", min_value=0, max_value=99999, value=0, step=1))

    yeni_sonuc: TakvimSonucu | None = None
    olustur_tiklandi = st.button("Takvim Oluştur", type="primary")
    if olustur_tiklandi:
        try:
            with st.spinner(f"{_ARAYUZ_SECENEKLERI[secili_alg]} çalıştırılıyor..."):
                if secili_alg == ALGORITMA_KARSILASTIR:
                    karsilastirma = servis.karsilastir(donem_id=donem_id, tohum=tohum, sure_sn=sure_sn)
                    yeni_sonuc = min(karsilastirma, key=lambda x: x.ceza)
                else:
                    yeni_sonuc = servis.olustur(
                        donem_id=donem_id, tohum=tohum, algoritma=secili_alg, sure_sn=sure_sn
                    )
            st.session_state["secili_calistirma_id"] = yeni_sonuc.kayit_id
            st.success(
                f"Takvim oluşturuldu ve kaydedildi ({ALGORITMA_ADLAR.get(yeni_sonuc.algoritma, yeni_sonuc.algoritma)}, "
                f"kayıt no: {yeni_sonuc.kayit_id})."
            )
        except TakvimUretilemedi as hata:
            st.error(str(hata))
            for y in hata.yerlesmeyenler:
                st.write(f"- **{y.ders_kod}** ({y.ogrenci} öğrenci): {y.neden}")
            return
        except VeriHatasi as hata:
            st.error("Veri doğrulama hatası:")
            for mesaj in hata.hatalar:
                st.write(f"- {mesaj}")
            return

    kayitlar = servis.calistirmalar(donem_id)
    if not kayitlar:
        st.caption("Henüz oluşturulmuş bir takvim yok. Üretmek için **Takvim Oluştur** butonuna basın.")
        return

    etiketler = {
        int(k["id"]): (
            f"#{k['id']} · {k['zaman']} · {ALGORITMA_ADLAR.get(k['algoritma'], k['algoritma'])} · "
            f"sert={k['sert_ihlal']}, yumuşak={k['toplam_ceza']:.4f} ({k['sure_sn']:.1f} sn)"
        )
        for k in kayitlar
    }
    varsayilan_id = st.session_state.get("secili_calistirma_id")
    indeks = list(etiketler).index(varsayilan_id) if varsayilan_id in etiketler else 0
    secili_id = st.selectbox(
        "Kayıtlı çalıştırma", options=list(etiketler), index=indeks, format_func=lambda x: etiketler[x]
    )
    assert secili_id is not None
    st.session_state["secili_calistirma_id"] = secili_id
    ayni_yeni = yeni_sonuc is not None and yeni_sonuc.kayit_id == secili_id
    try:
        gosterilecek = yeni_sonuc if ayni_yeni and yeni_sonuc is not None else servis.yukle(secili_id)
    except KayitHatasi as hata:
        st.error(f"Seçili çalıştırma bu veriyle yüklenemedi: {hata}")
        return
    _sonucu_goster(gosterilecek)


if __name__ == "__main__":
    calistir()
