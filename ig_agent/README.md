# Instagram Satış Ajanı (ig_agent)

Yerel, tek makinede koşan Instagram satış botu. Halı/koltuk/oto yıkama işletme
hesaplarını keşfeder, hikaye-yanıtı ile açılış yapar, DM'de GPT ile satış
konuşması yürütür, sıcak lead'de Temizify backend'i üzerinden operatöre bildirim
atar. Verileri call-tracker ile ortak `sales.db`'ye yazar; izleme Google Sheets'te,
kontrol ayrı bir Streamlit panelinde.

## Mimari

Tek tarayıcı oturumunu **sırayla** süren bir zamanlayıcı (aynı anda çoklu IG
aksiyonu ban riskini artırdığı için paralel değil):

```
keşif → açılış(hikaye-yanıtı) → inbox okuma → GPT yanıtı ──► sıcaksa → backend bildirimi
                     hepsi sales.db · Sheets = ayna · Streamlit = kontrol
```

| Modül | Sorumluluk |
|---|---|
| `config.py` | Ortam değişkenlerinden ayarlar |
| `canli_ayarlar.py` | Panelden değiştirilen ayarları `.env`'in üstüne bindirir |
| `surec.py` | Bot sürecini başlat/durdur, nabız ile canlılık tespiti |
| `db.py` | sales.db bağlantısı + additive şema göçü |
| `repository.py` | Tüm SQL (lead, mesaj, olay, durum, kuyruklar) |
| `pacing.py` | Saf anti-ban: warmup, çalışma saati, kota |
| `brain.py` | GPT satış beyni (playbook + araçlar + karar) |
| `llm_openai.py` | OpenAI tabanlı LLM istemcisi |
| `platformlar.py` | Ortak tipler (Hedef, GonderimSonucu), `anahtar()` (bot_state önekleri), `istemci_olustur()` |
| `tarayici.py` | Ortak Playwright temeli (kalıcı profil, yazma, checkpoint/engel, açılış turu döngüsü) |
| `instagram.py` | Instagram otomasyonu (seçiciler `S` sınıfında) |
| `tiktok.py` | TikTok otomasyonu — takip edilenlere DM (seçiciler `S` sınıfında) |
| `inbox_ingest.py` | Gelen DM'leri DB'ye alma (dedupe) |
| `scheduler.py` | Görev seçimi + karar uygulama + ana döngü |
| `alerts.py` | Backend `/internal/sales-alerts` bildirimi |
| `sheets.py` | Google Sheets aynası (tek yönlü senkron) |
| `run.py` | Giriş noktası (`--platform instagram\|tiktok`; her platform ayrı süreç) |
| `control_panel.py` | Streamlit kontrol paneli |

## Kurulum

```bash
cd call-tracker
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r ig_agent/requirements.txt
python -m playwright install chromium
cp ig_agent/.env.example .env   # doldurun
```

## Çalıştırma

```bash
./baslat.sh        # kontrol panelini açar (http://localhost:8501)
```

Panelde **Başlat**'a basınca bot arka planda ayrı süreç olarak açılır (panel
kapansa da çalışmaya devam eder). İlk seferde tarayıcı açılır, Instagram'a
**siz** giriş yaparsınız; oturum `.ig_profile/`'da saklanır. Bot çıktısı
`ig_agent.log`'a yazılır ve panelin **Log** sekmesinde görünür.

Panel:
- **Canlı durum** (5 sn'de bir yenilenir): bot açık mı, şu an ne yapıyor, son
  sinyal, son 1 saat / bugün hikaye yanıtı sayısı, son hata.
- **Başlat / Duraklat / Botu kapat / Hikaye turu şimdi**.
- **Ayarlar**: saatlik/günlük hikaye yanıtı tavanı (0 = sınırsız), tur arası
  bekleme, açılış mesajı (GPT ya da kendi metinleriniz), çalışma saatleri,
  bekleme süreleri. Kaydedilen ayarlar botu yeniden başlatmadan uygulanır.
- **Konuşmalar**, **Do-not-contact**, **Log** sekmeleri.

> `.venv/bin/python` Python 3.14'ü gösteriyor ama paketler 3.12'ye kurulu; bu
> yüzden her yerde `.venv/bin/python3.12` kullanılır (`baslat.sh` bunu yapar).
> Bot elle: `.venv/bin/python3.12 -m ig_agent.run` (TikTok: `... -m ig_agent.run --platform tiktok`)

## Hikaye turu nasıl çalışır

Bot ana sayfadaki hikaye tepsisini **sonuna kadar** gezer; daha önce hiç
yazışılmamış ve do-not-contact olmayan her hesabın hikayesine yanıt verir
(panelde "Aynı hesaba tekrar yazma" 0 = asla; N verilirse N gün sonra tekrar yazar).
Gönderimler saatlik tavana göre saate yayılır (100/saat ≈ her ~36 sn'de bir),
her gönderim anında DB'ye yazılır. Tur; duraklatma, kota dolması, çalışma
saatinin bitmesi veya Instagram'ın "işlem engellendi" uyarısıyla hemen biter.
Tepsi bitince *tur arası bekleme* kadar sonra yeni hikayeler için tekrar gezer.

## Takip edilenlere direkt DM

Panelde **Ayarlar → "Takip edilenlere direkt DM'i aç"** ile açılır (varsayılan
kapalı). Bot hikaye turundan sonra kendi "Takip" listemizi
(`/<kullanıcı adı>/following/`) sonuna kadar toplar; daha önce hiç yazışılmamış
(hikaye yanıtı dahil, herhangi bir yönde) ve do-not-contact olmayan her hesaba
profilindeki "Mesaj gönder" ile (yoksa `/direct/new/` üzerinden) açılış DM'i
atar. Kotası hikaye yanıtından ayrıdır (varsayılan 15/saat, 80/gün); turlar
arası bekleme varsayılan 30 dk. Instagram "bu hesaba mesaj gönderemezsin"
derse hesap do-not-contact'a `dm_kapali` nedeniyle eklenir ve bir daha
denenmez. Takip etmeyenlere giden DM'ler karşı tarafta "mesaj istekleri"ne düşer.

Kullanıcı adı panelden girilebilir; boşsa sol menüdeki Profil bağlantısından bulunur.

Sohbet açıldığında içinde zaten mesaj varsa (telefondan/elle yazışılmış) yazılmaz;
hesap do-not-contact'a `onceki_sohbet` nedeniyle eklenir. Takip penceresinin
altındaki "Önerilenler" hesapları listeye alınmaz. Tur en fazla 15 dk sürer, sonra
yanıt/hikaye turu araya girebilsin diye ara verir; art arda 5 gönderim başarısız
olursa tur durur (seçiciler kırılmış olabilir). Takip listesi 3 saat önbellekte tutulur.

## TikTok — takip edilenlere DM

Panelin üstündeki **Platform** seçicisinden **TikTok** seçilir; TikTok botu
Instagram'dan **ayrı bir süreçtir** (`run.py --platform tiktok`), ayrı başlatılır,
duraklatılır ve kapatılır. Başlığın altındaki satır tüm platformların durumunu
(çalışıyor / duraklatılmış / kapalı + bugünkü açılış sayısı) gösterir.

- İlk başlatmada ayrı bir tarayıcı açılır; TikTok'a **siz** giriş yaparsınız.
  Oturum `.tiktok_profile/`'da saklanır. Çıktı `tiktok_agent.log`'a yazılır.
- Yalnızca açılış yapar: "Takip edilen" listemizi toplar, daha önce **TikTok'ta**
  hiç yazışılmamış ve TikTok do-not-contact'ında olmayan her hesaba profildeki
  **Mesaj** düğmesiyle ilk mesajı yazar. Instagram'da yazışılmış bir işletmeye
  TikTok'tan ayrıca yazılabilir. Gelen mesajlar TikTok uygulamasından elle yanıtlanır.
- Kota Instagram'dan bağımsız: varsayılan **8/saat, 40/gün**; panelden değişir.
  Direkt DM varsayılan **kapalı**: Ayarlar → "TikTok'ta takip edilenlere direkt DM'i aç".
- TikTok "mesaj gönderemezsiniz" derse hesap TikTok do-not-contact'ına `dm_kapali`
  ile eklenir. Profilinde Mesaj düğmesi görünmeyen hesaplar o süreç boyunca
  atlanır (do-not-contact'a yazılmaz; bot yeniden başlayınca tekrar denenir).
- Kaydırmalı bulmaca / doğrulama (CAPTCHA) görülürse **çözülmez**: yalnızca TikTok
  botu duraklar, panelde uyarı çıkar. Tarayıcıdan çözüp *Uyarıyı temizle* → *Başlat*.
- Ayarlar `bot_state`'te `tiktok:` önekiyle durur (`tiktok:master_paused`,
  `tiktok:ayar.dm_acilis_saatlik` …); Instagram anahtarları öneksizdir.
- `.env`: `TIKTOK_KULLANICI_ADI`, `TIKTOK_PROFIL_DIZINI`, `TIKTOK_DM_ACILIS_SAATLIK`,
  `TIKTOK_DM_ACILIS_GUNLUK` (hepsi isteğe bağlı).
- Seçiciler `tiktok.py` → `S`'de; ilk canlı kontrol listesi:
  `docs/superpowers/plans/2026-10-13-b-tiktok-canli-kontrol.md`.

## Güvenlik / anti-ban notları

- **Instagram otomasyonu Meta ToS'a aykırıdır**; action-block/ban riski gerçektir.
  Saatlik tavan panelden ayarlanır (varsayılan 100); yüksek hacim action-block
  riskini artırır. Instagram "işlem engellendi" uyarısı verirse bot **otomatik
  duraklar**; birkaç saat bekleyip tavanı düşürerek panelden yeniden başlatın.
- **Residential IP** kullanın (datacenter IP'ler blok yer). Bot sizin makinenizde,
  sizin girişinizle çalışır.
- Checkpoint/challenge algılanınca bot **otomatik durur**; tarayıcıdan çözüp
  panelden yeniden başlatın.
- "rahatsız etmeyin / çıkar" gibi net retler `iletisimi_kes` ile onurlandırılır ve
  hesap do-not-contact listesine eklenir.

## Backend bağlantısı

Sıcak lead bildirimi için temizify-backend'e eklenen uç:
`POST /internal/sales-alerts` (header `x-sales-secret`). Backend tarafında
`SALES_ALERT_SECRET` env'i bot'taki `IG_BACKEND_SECRET` ile aynı olmalı. Bildirim
mevcut admin-bildirim zincirini (WhatsApp şablonu → metin → e-posta) kullanır.

## Test

```bash
.venv/bin/python3.12 -m pytest tests/ -q
```

Saf/enjekte-edilebilir mantık (pacing, repository, brain, scheduler kararları,
alerts, sheets, inbox) test kapsamındadır. Tarayıcıya bağlı `instagram.py` canlı
ortamda elle ayarlanır (IG DOM değişince `S` sınıfındaki seçiciler güncellenir).
```
