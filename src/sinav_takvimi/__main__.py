"""Komut satırı: `python -m sinav_takvimi <komut>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sinav_takvimi.altyapi.db import (
    SEMA_SURUMU,
    VARSAYILAN_DB,
    SemaSurumHatasi,
    anketleri_koruyarak_yenile,
    baglan,
    sema_surumu,
)
from sinav_takvimi.araclar.sentetik_veri import SentetikAyarlar
from sinav_takvimi.domain.ahp import CR_SINIRI, GRUP_ADLARI, AhpSonucu
from sinav_takvimi.uygulama.agirlik_servisi import AgirlikServisi, AnketHatasi, anket_dosyasi_oku, sablon_metni
from sinav_takvimi.uygulama.raporlar import adalet_satirlari, kisit_satirlari, takvim_izgarasi
from sinav_takvimi.uygulama.takvim_servisi import (
    ALGORITMA_ADLAR,
    ALGORITMA_KARSILASTIR,
    GECERLI_ALGORITMALAR,
    VARSAYILAN_ALGORITMA,
    TakvimServisi,
    TakvimSonucu,
    TakvimUretilemedi,
)
from sinav_takvimi.uygulama.veri_servisi import VeriHatasi, VeriServisi


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows konsolunda Türkçe karakterler
    ap = argparse.ArgumentParser(prog="sinav_takvimi", description="Sınav takvimi optimizasyon sistemi")
    ap.add_argument("--db", default=str(VARSAYILAN_DB), help="SQLite dosyası")
    alt = ap.add_subparsers(dest="komut", required=True)

    p = alt.add_parser("veri-uret", help="Sentetik fakülte verisi üret ve kaydet (mevcut verinin yerine)")
    p.add_argument("--tohum", type=int, default=42)
    p.add_argument("--ogrenci", type=int, default=125, help="bölüm-sınıf başına öğrenci")
    alt.add_parser("ozet", help="Veritabanındaki dönem(ler)in özeti")
    p = alt.add_parser("csv-aktar", help="Dönem verisini CSV klasörüne yaz")
    p.add_argument("klasor")
    p = alt.add_parser("csv-yukle", help="CSV klasöründen veriyi yükle (mevcut verinin yerine)")
    p.add_argument("klasor")
    p = alt.add_parser("ahp-sablon", help="Boş AHP anket şablonu (TOML) yaz")
    p.add_argument("dosya")
    p = alt.add_parser("ahp-ekle", help="Doldurulmuş bir AHP anketini kaydet")
    p.add_argument("dosya")
    alt.add_parser("agirliklar", help="Anketlerden hesaplanan kriter ağırlıklarını göster")
    p = alt.add_parser("coz", help="Takvim üret, iyileştir, doğrula ve kaydet; kısıt ve adalet raporunu yaz")
    p.add_argument("--donem", type=int, default=None, help="dönem numarası (varsayılan: en yeni dönem)")
    p.add_argument(
        "--algoritma",
        choices=(*GECERLI_ALGORITMALAR, ALGORITMA_KARSILASTIR),
        default=VARSAYILAN_ALGORITMA,
        help=f"çözüm algoritması (varsayılan: {VARSAYILAN_ALGORITMA})",
    )
    p.add_argument(
        "--sure",
        type=float,
        default=None,
        help="metasezgisel iyileştirme süre bütçesi, saniye (varsayılan: config/agirliklar.toml → 15 sn)",
    )
    p.add_argument("--tohum", type=int, default=0, help="rastgele sayı üreteci tohumu")
    p.add_argument("--tablo", action="store_true", help="takvim tablosunu (gün × oturum) da yaz")
    p = alt.add_parser("yenile", help="Veritabanını yeni şemayla kur (AHP anketleri korunur, eskisi yedeklenir)")
    p.add_argument("--zorla", action="store_true", help="şema güncel olsa bile yeniden kur")

    args = ap.parse_args(argv)
    if args.komut == "yenile":
        if sema_surumu(args.db) == SEMA_SURUMU and not args.zorla:
            print(f"Şema zaten güncel (sürüm {SEMA_SURUMU}); yenilemeye gerek yok. Yine de istiyorsanız: --zorla")
            return 0
        adet = anketleri_koruyarak_yenile(args.db)
        print(f"Veritabanı yeniden oluşturuldu ({adet} AHP katılımcısı taşındı). Şimdi `veri-uret` ya da `csv-yukle`.")
        return 0
    if args.komut == "ahp-sablon":  # veritabanı gerekmez
        Path(args.dosya).write_text(sablon_metni(), encoding="utf-8")
        print(f"Şablon yazıldı: {args.dosya}")
        return 0
    try:
        conn = baglan(args.db)
    except SemaSurumHatasi as hata:
        print(f"✗ {hata}")
        return 1
    servis = VeriServisi(conn)
    agirlik = AgirlikServisi(conn)

    try:
        if args.komut == "veri-uret":
            veri, uyarilar = servis.sentetik_uret(SentetikAyarlar(tohum=args.tohum, ogrenci_per_sinif=args.ogrenci))
            print(f"Sentetik veri üretildi → {args.db}")
            _ozet_yaz(veri.ozet())
            _uyarilari_yaz(uyarilar)
        elif args.komut == "csv-yukle":
            veri, uyarilar = servis.csv_den_yukle(args.klasor)
            print(f"CSV yüklendi: {args.klasor}")
            _ozet_yaz(veri.ozet())
            _uyarilari_yaz(uyarilar)
        elif args.komut == "csv-aktar":
            donem = _tek_donem(servis)
            servis.csv_ye_aktar(donem, args.klasor)
            print(f"CSV dosyaları yazıldı: {args.klasor}")
        elif args.komut == "ozet":
            for d in servis.donemler():
                print(f"[{d.id}] {d.ad} ({d.tur}, {d.baslangic} – {d.bitis})")
                _ozet_yaz(servis.ozet(d.id))
        elif args.komut == "ahp-ekle":
            k = anket_dosyasi_oku(args.dosya)
            kid = agirlik.katilimci_ekle(k)
            print(f"Anket kaydedildi: [{kid}] {k.ad} ({k.rol})")
            for matris, cr in agirlik.tutarlilik(k).items():
                isaret = "✓" if cr <= CR_SINIRI else "⚠ gözden geçirin"
                print(f"  {matris:<20} CR = {cr:.3f} {isaret}")
        elif args.komut == "agirliklar":
            for k in agirlik.katilimcilar():
                oranlar = agirlik.tutarlilik(k)
                kotu = [m for m, v in oranlar.items() if v > CR_SINIRI]
                durum = f"⚠ CR > {CR_SINIRI:.2f}: {', '.join(kotu)}" if kotu else "✓ tutarlı"
                print(f"  [{k.id}] {k.ad} ({k.rol}) — en yüksek CR = {max(oranlar.values()):.3f} {durum}")
            _agirlik_yaz(agirlik.hesapla())
        elif args.komut == "coz":
            takvim_servisi = TakvimServisi(conn)
            if args.algoritma == ALGORITMA_KARSILASTIR:
                sonuclar = takvim_servisi.karsilastir(args.donem, tohum=args.tohum, sure_sn=args.sure)
                _karsilastirma_yaz(sonuclar)
                en_iyi = min(sonuclar, key=lambda x: x.ceza)
                print(f"\nEn iyi çözüm ayrıntısı ({ALGORITMA_ADLAR.get(en_iyi.algoritma, en_iyi.algoritma)}):")
                _coz_yaz(en_iyi, args.tablo)
            else:
                sonuc = takvim_servisi.olustur(
                    args.donem, tohum=args.tohum, algoritma=args.algoritma, sure_sn=args.sure
                )
                _coz_yaz(sonuc, args.tablo)
    except TakvimUretilemedi as hata:
        print(f"✗ {hata}")
        for y in hata.yerlesmeyenler:
            print(f"  ✗ {y.ders_kod} ({y.ogrenci} öğrenci): {y.neden}")
        print("  Takvim kaydedilmedi; referans belirlenmedi (yerleşmemiş sınav varken referans alınamaz).")
        return 1
    except ValueError as hata:
        print(f"✗ {hata}")
        return 1
    except LookupError as hata:
        print(f"✗ {hata}")
        return 1
    except VeriHatasi as hata:
        print("Veri hataları:")
        for h in hata.hatalar:
            print(f"  ✗ {h}")
        return 1
    except AnketHatasi as hata:
        print(f"✗ Anket hatası: {hata}")
        return 1
    finally:
        conn.close()
    return 0


def _agirlik_yaz(s: AhpSonucu) -> None:
    if not s.katilimci_sayisi:
        kaynak = "anket yok → eşit ağırlık"
    elif len(s.roller) > 1:
        kaynak = f"{s.katilimci_sayisi} katılımcı, {len(s.roller)} rol (rol içi geometrik ort., roller eşit paylı)"
    else:
        kaynak = f"{s.katilimci_sayisi} katılımcı (geometrik ortalama)"
    print(f"Kriter ağırlıkları — {kaynak}")
    for rol, r in s.roller.items():
        print(f"  rol {rol:<16} {r.katilimci_sayisi} kişi · " + " ".join(f"{k}={w:.3f}" for k, w in r.kuresel.items()))
    for i, (grup, m) in enumerate(s.gruplar.items()):
        print(f"  {GRUP_ADLARI[grup]:<20} {s.ust.agirliklar[i]:.3f}   (grup içi CR = {m.cr:.3f})")
        for kod, w in zip(m.kriterler, m.agirliklar, strict=True):
            print(f"      {kod:<4} yerel {w:.3f}   küresel {s.kuresel[kod]:.3f}")
    print(f"  Gruplar arası CR = {s.ust.cr:.3f}  {'✓ tutarlı' if s.tutarli else '⚠ CR > 0.10 olan matris var'}")


def _karsilastirma_yaz(sonuclar: list[TakvimSonucu]) -> None:
    print("Algoritma karşılaştırması (aynı DSatur referans ölçeğinde)")
    print(
        f"  {'Algoritma':<22} {'Sert':>6} {'Yumuşak':>10} {'İyileşme':>10} "
        f"{'Gini':>8} {'Jain':>8} {'Süre':>8} {'Kayıt':>7}"
    )
    for s in sonuclar:
        ad = ALGORITMA_ADLAR.get(s.algoritma, s.algoritma)
        iyil = f"%{s.iyilesme_orani * 100:.1f}" if s.iyilesme_orani is not None else "referans"
        print(
            f"  {ad:<22} {s.ceza.sert:>6g} {s.ceza.yumusak:>10.4f} {iyil:>10} "
            f"{s.adalet.gini:>8.4f} {s.adalet.jain:>8.4f} {s.sure_sn:>7.2f}s #{s.kayit_id}"
        )


def _coz_yaz(s: TakvimSonucu, tablo: bool) -> None:
    pr = s.problem
    ad = ALGORITMA_ADLAR.get(s.algoritma, s.algoritma)
    print(
        f"Takvim üretildi ({ad}): {pr.E} sınav, {pr.P} oturum, "
        f"{s.sure_sn:.2f} sn · kayıt no {s.kayit_id}"
    )
    if s.iyilesme_orani is not None and s.baslangic_ceza is not None:
        print(
            f"Ceza: {s.ceza}  (yapıcı başlangıç: {s.baslangic_ceza.yumusak:.4f} → "
            f"%{s.iyilesme_orani * 100:.1f} iyileşme)"
        )
    else:
        print(f"Ceza: {s.ceza}")
    if s.dogrulama.gecerli:
        print("✓ Bağımsız doğrulayıcı: sert ihlal yok")
    else:
        print("✗ Bağımsız doğrulayıcı sert ihlal buldu:")
        for h in s.dogrulama.hatalar[:20]:
            print(f"  {h.kod}: {h.mesaj}")
    for u in s.uyarilar:
        print(f"  ⚠ {u}")

    print("\nKısıt raporu (sert: etkilenen kişi; yumuşak: referansa göre normalize değer × AHP ağırlığı)")
    print(f"  {'Kod':<4} {'Kısıt':<52} {'Ham':>10} {'Normalize':>10} {'Ağırlık':>8} {'Ceza':>8}")
    for satir in kisit_satirlari(s.kisit_raporu):
        print(f"  {satir['Kod']!s:<4} {satir['Kısıt']!s:<52} {satir['Ham ihlal']:>10g} {satir['Normalize']:>10g} "
              f"{satir['Ağırlık']:>8g} {satir['Ceza']:>8g}")
    print("  Referans ölçekleri (kriterin referans takvimdeki doğal değeri): " + ", ".join(
        f"{k}={v:.4g} ({s.referans_kaynagi.get(k, '?')})" for k, v in s.referans.items()))

    print("\nAdalet özeti (çift başına kişisel ceza)")
    for ad_satir, deger in adalet_satirlari(s.adalet):
        print(f"  {ad_satir:<30}{deger:>12}")
    for k in s.adalet.kohortlar:
        print(f"  kohort {k.bolum_kod}-{k.sinif}. sınıf  {k.ogrenci:>4} öğrenci  ortalama ceza {k.ortalama_ceza:.4f}")

    if tablo:
        izgara = takvim_izgarasi(pr, s.cozum)
        print("\nTakvim")
        for g, gun in enumerate(izgara.satirlar):
            print(f"  {gun}")
            for o, oturum in enumerate(izgara.sutunlar):
                if izgara.hucreler[g][o]:
                    print(f"      {oturum}: {', '.join(izgara.hucreler[g][o])}")


def _tek_donem(servis: VeriServisi) -> int:
    donemler = servis.donemler()
    if not donemler:
        raise SystemExit("Veritabanında dönem yok. Önce `veri-uret` veya `csv-yukle` çalıştırın.")
    return donemler[0].id


def _ozet_yaz(ozet: dict[str, int]) -> None:
    for ad, sayi in ozet.items():
        print(f"  {ad:<28}{sayi:>8}")


def _uyarilari_yaz(uyarilar: list[str]) -> None:
    for u in uyarilar:
        print(f"  ⚠ {u}")


if __name__ == "__main__":
    sys.exit(main())
