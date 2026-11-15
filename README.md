# Sınav Takvimi Optimizasyon Sistemi

Endüstri Mühendisliği 1. sınıf **Bilgisayar Programlama** dersi projesi.

Üniversite bir **hizmet işletmesi** olarak ele alınmıştır: kısıtlı kaynaklar (derslik, gözetmen, zaman dilimi)
kullanılarak final sınav takvimi oluşturulur. Amaç, hiçbir sert kuralı çiğnemeden öğrencilerin, öğretim
elemanlarının ve idarenin memnuniyetini en yüksek düzeye çıkarmaktır. Problem, graf renklendirme ailesinden
NP-zor bir problemdir (Uluslararası Zaman Çizelgeleme Yarışması, ITC 2007).

## Çalıştırma

### Hazır program (.exe)
`SinavTakvimi_Program.zip` dosyasını bir klasöre çıkarın ve `SinavTakvimi\SinavTakvimi.exe` dosyasını çalıştırın.
Kurulum gerekmez. `SinavTakvimi.exe` dosyası yanındaki `_internal` klasöründen ayrılmamalıdır.

1. **⚡ Hızlı Fakülte Üret** ile sentetik bir fakülte verisi oluşturun (veya **📥 İçe Aktar** ile Excel/CSV yükleyin).
2. Algoritmayı, süreyi ve tohumu seçip takvimi çözün.
3. Sonuçları takvim, bölüm/sınıf, öğrenci ve öğretim elemanı programı olarak inceleyin; **📤 Dışa Aktar** ile Excel'e alın.

### Kaynak koddan (Python 3.12+)
```
python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\python -m sinav_takvimi veri-uret        # sentetik veri → data/sinav.db
.venv\Scripts\python -m sinav_takvimi coz              # takvimi üret (--algoritma, --sure)
.venv\Scripts\python -m sinav_takvimi.arayuz.masaustu  # masaüstü uygulaması
.venv\Scripts\streamlit run src\sinav_takvimi\arayuz\streamlit_app.py   # web arayüzü (ayrıntılı rapor)```
Windows konsolunda Türkçe karakterler için `set PYTHONIOENCODING=utf-8` gerekebilir.

## Model

### Sert kurallar (asla çiğnenmez)
| Kod | Kural |
|---|---|
| H1 | Bir öğrencinin aynı oturumda iki sınavı olamaz |
| H2 | Derslik kapasitesi aşılamaz |
| H4 | Bir öğretim elemanının aynı oturumda iki sınavı olamaz |
| H7 | Bir oturumdaki gözetmen ihtiyacı mevcut personeli aşamaz |
| H8 | Sınav süresi oturuma sığmalıdır |
| H9 | Sabit / yasak oturum kuralları |
| H10 | Özel gereksinimli öğrenciler uygun dersliğe yerleşir |
| H11 | Öğrenci başına günlük sınav sınırı |

### Yumuşak kriterler (en aza indirilir)
| Kod | Kriter | Kod | Kriter |
|---|---|---|---|
| S1 | Arka arkaya sınav | S6 | Derslik kapasitesi israfı |
| S2 | Aynı gün iki sınav | S7 | Bir günde üç sınav |
| S3 | Sınavlar arası hazırlık süresi | S9 | Öğrenciler arası adalet |
| S4 | Büyük sınavların geç oturuma kalması | S10 | Sınıflar (kohortlar) arası adalet |
| S5 | Bir sınavın birden fazla salona bölünmesi | S11 | Öğretim elemanının müsait olmadığı oturum |

S8 (Carter yakınlık cezası) yalnızca literatürle karşılaştırma için raporlanır. Her kriter, ham değerin sabit bir
paydaya bölünmesiyle elde edilen doğal bir orandır.

### Kriter ağırlıkları: AHP
Ağırlıklar keyfi seçilmez; paydaşlardan (öğrenci, öğretim elemanı, idari personel) **Analitik Hiyerarşi Süreci (AHP)**
anketiyle toplanır. Tutarlılık oranı CR ≤ 0,10 (Saaty) koşulu denetlenir. Anket yoksa tüm kriterler eşit ağırlıklıdır.
```
.venv\Scripts\python -m sinav_takvimi ahp-sablon anket.toml   # boş anket
.venv\Scripts\python -m sinav_takvimi ahp-ekle anket.toml     # doldurulmuş anketi ekle
.venv\Scripts\python -m sinav_takvimi agirliklar              # hesaplanan ağırlıklar
```

## Algoritmalar
1. **DSatur (yapıcı):** "En zor sınav önce" ilkesiyle, hiçbir sert kuralı çiğnemeyen bir başlangıç takvimi kurar.
2. **Tabu Arama (varsayılan)** ve **Benzetimli Tavlama:** başlangıç takvimini Kempe zinciri ve ikili takas
   hamleleriyle iyileştirir. Ceza artımlı (delta) hesaplanır, böylece her hamle hızlı değerlendirilir.

5 tohum × 15 saniyelik deneylerde her iki metasezgisel, DSatur başlangıcının toplam cezasını (0,917) yaklaşık
**%30 azaltmış** (Tabu 0,641, Tavlama 0,641), arka arkaya sınavları yaklaşık %80 düşürmüş ve "günde üç sınav"
durumunu sıfırlamıştır.

## Mimari
```
arayuz (PySide6, Streamlit) → uygulama (servisler) → domain + cozuculer ← altyapi (SQLite, CSV, Excel)
```
| Klasör | İçerik |
|---|---|
| `src/sinav_takvimi/domain/` | Modeller, kısıtlar, değerlendirici, doğrulayıcı, AHP; veritabanı ve arayüzden bağımsız |
| `src/sinav_takvimi/cozuculer/` | DSatur, Tabu Arama, Benzetimli Tavlama |
| `src/sinav_takvimi/altyapi/` | SQLite, CSV ve Excel aktarımı (tüm SQL burada, parametreli) |
| `src/sinav_takvimi/uygulama/` | Servisler: yükle → çöz → doğrula → kaydet |
| `src/sinav_takvimi/arayuz/` | Masaüstü (PySide6) ve web (Streamlit) arayüzleri |
| `src/sinav_takvimi/araclar/` | Tekrarlanabilir sentetik fakülte verisi üreticisi |
| `config/` | Algoritma parametreleri, AHP anket şablonu |## Durum ve kapsam
- Tamamlandı: veri katmanı, sert ve yumuşak kurallar, adalet ölçütleri, AHP, DSatur, Tabu Arama, Benzetimli Tavlama,
  masaüstü uygulaması, Excel/CSV aktarımı.
- Yapılmadı: gözetmenlerin tek tek kişilere atanması (şu an yalnızca oturum başına gözetmen kapasitesi H7 ile
  denetlenir).
- Bilinçli basitleştirmeler: ortak ders şubeleri tek sınav sayılır; bina/yürüme mesafesi ve öğretim elemanı
  saat tercihleri kapsam dışıdır.
