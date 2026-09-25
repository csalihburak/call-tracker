# Temizify Sales — Call Tracker

B2B soğuk arama takip uygulaması. Halı yıkama sektörü için tasarlanmıştır.

## Gereksinimler

- Python 3.9+

## Kurulum

```bash
pip install -r requirements.txt
```

## Çalıştırma

```bash
streamlit run app.py
```

Tarayıcı otomatik olarak http://localhost:8501 adresinde açılır.

## Sayfalar

| Sayfa | Açıklama |
|---|---|
| Dashboard | KPI kartları, grafik ve bugünkü takipler |
| Arama Listesi | Lead ekleme ve filtreleme |
| Arama Yap | Arama kayıt formu + ses notu |
| Bugün Ara | Takip zamanı gelmiş ve hiç aranmamış leadler |
| Analizler | Haftalık trendler, itirazlar, şehir bazlı performans |
| Pipeline | Kanban-stili aşama görünümü |

## Veri

- `sales.db` — SQLite veritabanı (otomatik oluşturulur)
- `audio_recordings/` — Ses kayıtları (otomatik oluşturulur)
