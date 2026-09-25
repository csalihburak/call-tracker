"""Instagram satış ajanı — Temizify.

Yerel, tek makinede koşan; hedef IG işletme hesaplarını keşfeder, hikaye-yanıtı
açılışı gönderir, DM'de GPT ile satış konuşması yürütür ve sıcak lead'de backend
üzerinden operatöre bildirim atar.

Katmanlar:
- config      : ortam değişkenlerinden ayarlar
- db          : sales.db bağlantısı + şema göçü (call-tracker ile paylaşımlı)
- repository  : veri erişimi (lead, mesaj, olay, bot durumu)
- pacing      : saf hız-sınırı / warmup / çalışma saati mantığı (anti-ban)
"""

__all__ = ["config", "db", "repository", "pacing"]
