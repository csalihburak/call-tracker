# Çok platformlu soğuk DM açılışı (Instagram takip listesi, TikTok, Facebook grupları) — Tasarım

Tarih: 2026-10-13 · Durum: onaylandı (bölüm bölüm), spec incelemesi bekliyor

## 1. Amaç ve kapsam

**Amaç:** Bugün bot yalnızca Instagram hikaye tepsisindeki, daha önce hiç
yazışmadığımız hesaplara hikaye yanıtı atıyor (`sales.db`: 862 `story_reply`).
Açılış kaynağını genişletmek:

1. **Instagram:** takip ettiğimiz ama hiç yazışmadığımız hesaplara — hikayesi
   olmasa da — direkt DM.
2. **TikTok:** takip ettiğimiz, hiç yazışmadığımız hesaplara DM.
3. **Facebook:** üye olduğumuz gruplarda gönderi paylaşan kişilere Messenger'dan DM.

**Kapsamda:** açılış (ilk mesaj) akışları, platformlu veri modeli, platform
başına bot süreci, panelde platform seçici.

**Kapsam dışı:**
- **Gelen mesajlara cevap.** Instagram için 2026-10-12 spec'indeki Graph API +
  Claude Code (`/ig-dm`) yolu geçerlidir (App Review bekliyor). TikTok/Facebook
  cevapları şimdilik uygulamalardan elle verilir. TikTok/FB için gelen kutusu
  okuma ve otomatik yanıt ileride ayrı bir spec konusudur.
- Instagram hikaye turunun davranışı (değişmez).
- Hesap keşfi / otomatik takip (TikTok/IG'de yalnızca mevcut takip listesi kullanılır).
- Farklı platformlardaki hesapları aynı işletme olarak eşleştirme.
- CAPTCHA çözme (algılanınca bot durur, kullanıcı çözer).

**Kararlar (kullanıcıyla):**
- "Daha önce mesaj atmadık" kuralı **platform bazında**: IG'de yazılan hesaba
  TikTok/FB'de ayrıca yazılabilir.
- IG'de **önce hikaye turu, sonra takip edilenlere direkt DM**; direkt DM'in
  **ayrı** saatlik/günlük tavanı vardır.
- Facebook'ta hedef: **grupta gönderi paylaşanlar** (yorumcular ve tüm üyeler değil).
- TikTok'ta hedef: **takip ettiklerimiz**; DM kutusu kapalıysa atlanır, bir daha denenmez.
- Mimari: **platform başına ayrı süreç**, tek kod tabanı, ortak `sales.db`.

**Riskler:**
- Üç platformun otomasyonu da kullanım koşullarına aykırıdır; action-block /
  ban riski bilinen ve kabul edilmiş bir durumdur.
- Arkadaş/takipçi olmayanlara giden mesajlar "mesaj istekleri"ne düşer; görülme
  oranı düşük olabilir.
- Başlangıç kotaları tahmindir; ilk haftanın verisiyle ayarlanır.

## 2. Veri modeli (additive göç, `db.py`)

Hiçbir tablo/kolon silinmez; call-tracker `app.py` etkilenmez.

### 2.1 `leads`

| Yeni kolon | Açıklama |
|---|---|
| `platform TEXT` | `instagram` \| `tiktok` \| `facebook` |
| `handle TEXT` | Platformdaki kimlik. IG/TikTok: kullanıcı adı. FB: sayısal kullanıcı id'si (`/groups/<gid>/user/<uid>/` linkinden). |
| `profile_url TEXT` | Profil bağlantısı |
| `discovery_source TEXT` | Açılış kaynağı: `hikaye`, `takip_listesi`, FB'de grup id'si |

- Göçte mevcut satırlar: `ig_handle IS NOT NULL` olanlara `platform='instagram'`,
  `handle=ig_handle`, `profile_url=ig_profile_url` yazılır (idempotent).
- Yeni tekil indeks: `(platform, handle) WHERE handle IS NOT NULL`.
- IG lead'lerinde `ig_handle` doldurulmaya devam eder (Sheets / panel uyumu).
- `source`: `Instagram` / `TikTok` / `Facebook`.
- FB lead'lerinde `business_name` = gönderi yazarının görünen adı.
- 2026-10-12 spec'indeki `leads.kanal` önerisi bu `platform` kolonuyla
  birleştirilir; o spec uygulanırken `kanal` yerine `platform` kullanılır.

### 2.2 `ig_messages`

- Tablo adı değişmez.
- Yeni `direction` değeri **`dm_opener`**: takip listesi / grup kaynaklı soğuk
  ilk DM. `story_reply`'dan ayrı sayılır (ayrı kota).
- `mesaj_ekle`'de `dm_opener` → `last_outbound_at` güncellenir, aşama
  `yeni → ilk_temas` (story_reply ile aynı).
- Platform kolonu yok; platform lead'den gelir, kota sorguları `leads` ile join'lenir.

### 2.3 Tekrar kuralı

`yakin_zamanda_iletisim(conn, platform, handle, gun)` — o platformda o hesapla
herhangi bir yönde mesaj kaydı varsa True (`gun <= 0` → süre sınırı yok, bugünkü
semantik). Mevcut imzayı kullanan çağrılar için `platform` varsayılanı `instagram`.

### 2.4 Do-not-contact

- Yeni tablo `dnc (platform TEXT, handle TEXT, reason TEXT, created_at TEXT,
  PRIMARY KEY (platform, handle))`.
- Göçte `dnc_handles` satırları `platform='instagram'` ile kopyalanır
  (`INSERT OR IGNORE`). `dnc_handles` okunmaz hale gelir ama silinmez.
- `dnc_mi(conn, platform, handle)`, `dnc_ekle(conn, platform, handle, reason)`.
- Yeni neden **`dm_kapali`**: mesaj kutusu açılamayan hesap bir daha denenmez.

### 2.5 `bot_state`

- Anahtarlar platforma göre ayrılır: `tiktok:master_paused`, `facebook:action_block`, …
- **Instagram anahtarları öneksizdir** — canlı DB'deki `master_paused`,
  `ayar.yeniden_iletisim_gun=0` vb. olduğu gibi geçerli kalır.
- Yardımcı: `anahtar(platform, ad)` → `ad` (instagram) | `f"{platform}:{ad}"`.

## 3. Bileşenler

`ig_agent` paketi ve mevcut dosya adları korunur.

| Dosya | Değişiklik |
|---|---|
| `tarayici.py` (yeni) | `InstagramClient`'teki ortak Playwright kodu: kalıcı profil başlat/kapat, `_git`, `_insan_yaz`, `engel_algilandi`, checkpoint/engel kontrol iskeleti. |
| `platformlar.py` (yeni) | `PlatformIstemci` protokolü, `GonderimSonucu` (`GONDERILDI` \| `BASARISIZ` \| `DM_KAPALI`), `istemci_olustur(platform, ayarlar)`. |
| `instagram.py` | `tarayici.py` temeline taşınır, davranış aynı. Yeni: `takip_listesi_topla()`, `acilis_turu(...)`, `dm_gonder` → `GonderimSonucu`. |
| `tiktok.py` (yeni) | Giriş kontrolü, CAPTCHA/doğrulama tespiti, takip listesi, profil "Mesaj" düğmesiyle DM. Seçiciler `S` sınıfında. |
| `facebook.py` (yeni) | Giriş kontrolü, grup listesi, grup akışından gönderi yazarları, Messenger DM, şifreleme PIN ekranı tespiti. Seçiciler `S` sınıfında. |
| `config.py` | `PlatformAyarlari` (profil dizini, direkt DM saatlik/günlük tavan, tur soğuması, açılış modu/metinleri); FB için grup linkleri. |
| `canli_ayarlar.py` | Platform önekli `ayar.*` anahtarları. |
| `repository.py` | `platform` parametresi (varsayılan `instagram`); `dm_opener` sayaçları; `dnc` fonksiyonları. |
| `scheduler.py` | Platform bağımsız; yeni `direkt_dm_turu_yap`. |
| `run.py` | `--platform` argümanı (varsayılan `instagram`); log dosyası `ig_agent.log` / `tiktok_agent.log` / `facebook_agent.log`; `bot_pid` platform anahtarlı. |
| `surec.py` | Platform başına başlat/durdur/canlılık. |
| `control_panel.py` | Platform seçici + platform başına kontroller/ayarlar. |

### 3.1 Platform arayüzü

```
giris_yapildi_mi() -> bool
checkpoint_var_mi() -> bool          # TikTok CAPTCHA, FB PIN ekranı dahil
engel_algilandi: bool
dm_gonder(handle, metin) -> GonderimSonucu
acilis_turu(karar_fn, sonuc_fn, yazmadan_once) -> None
hikayeleri_yanitla(...)              # yalnızca Instagram
```

`acilis_turu` hedefleri sırayla gezer; her hedef için `karar_fn(hedef)` çağırır
(`hedef = {handle, ad, profile_url, kaynak}`). Dönüş: metin → `dm_gonder`;
`None` → atla; `TURU_BITIR` → tur biter. Gönderimden önce `yazmadan_once()`
(tempo beklemesi; False → tur biter). Sonuç `sonuc_fn(hedef, metin, sonuc)` ile
bildirilir. İstemci DB'ye dokunmaz.

### 3.2 Zamanlayıcı görev sırası (her süreç kendi platformu için)

1. **Hikaye turu** — yalnızca IG; mevcut akış aynen.
2. **Direkt DM turu** — IG'de hikaye turundan sonra; TikTok/FB'de tek açılış.
   Kendi tavanı ve soğuması (`son_dm_turu` durum anahtarı).
3. **Hashtag keşfi** — yalnızca IG, varsayılan kapalı (değişmez).

Mevcut IG `RESPOND` görevi bu spec'te değiştirilmez (2026-10-12 spec'i ele alır).
TikTok/FB süreçlerinde `RESPOND` görevi yoktur.

`direkt_dm_turu_yap` `karar_fn` kontrolleri (sırayla): duraklatıldı mı → çalışma
saati → kota → `dnc_mi` → `yakin_zamanda_iletisim` → açılış metni üret.
`sonuc_fn`:
- `GONDERILDI` → lead upsert (`platform`, `handle`, `discovery_source`) +
  `mesaj_ekle(..., "dm_opener", ...)`.
- `DM_KAPALI` → `dnc_ekle(platform, handle, "dm_kapali")`.
- `BASARISIZ` → yalnızca sayaç (sonraki turda tekrar denenebilir).

Tempo: iki direkt DM arası `3600 / saatlik_tavan × U(0.7, 1.3)` sn (hikaye
turundaki `acilis_araligi_sn` mantığı, `dm_opener` son zamanına göre).

### 3.3 Açılış metni

Mevcut `_acilis_metni`: platform başına "gpt" veya "sabit" mod. GPT modunda
`acilis_uret`'e platform bilgisi verilir (ör. "Facebook grubunda paylaşım
yapan bir işletmeye Messenger'dan ilk mesaj").

## 4. Platform akışları

### 4.1 Instagram — takip edilenler

1. Kendi profil adı ana sayfadaki profil bağlantısından okunur.
2. `/<kendi_adı>/following/` penceresi sonuna kadar kaydırılır, tüm kullanıcı
   adları toplanır (profil açılınca pencere kapandığından gönderimden **önce**).
3. Her hedef: profil "Mesaj gönder" düğmesi (`_profilden_mesaj_ac`); yoksa
   `/direct/new/` üzerinden kullanıcı adı aratılır; ikisi de olmazsa `DM_KAPALI`.

### 4.2 TikTok — takip edilenler

1. Profil → "Takip edilen" penceresi kaydırılarak liste toplanır.
2. Her hedef: profil "Mesaj" düğmesi → sohbet → yaz. Düğme yoksa / sohbet
   yazmaya kapalıysa `DM_KAPALI`.
3. Kaydırmalı CAPTCHA / doğrulama → `checkpoint_var_mi()` True → süreç durur.

### 4.3 Facebook — grup gönderi yazarları

1. Grup listesi: panelde girilen grup linkleri; boşsa `/groups/joins/`'daki tüm gruplar.
2. Her grup akışında son ~30 gönderi taranır; yazar linkinden kullanıcı id'si ve
   görünen ad alınır. Kendi gönderilerimiz ve aynı turda tekrar edenler atlanır.
   `discovery_source` = grup id'si.
3. DM: `facebook.com/messages/t/<uid>` → yaz. "Bu kişiye mesaj gönderemezsiniz"
   → `DM_KAPALI`.
4. Messenger uçtan uca şifreleme PIN / "geçmişi geri yükle" ekranı ilk girişte
   kullanıcı tarafından geçilir; tekrar çıkarsa checkpoint sayılır.

### 4.4 Başlangıç kotaları (direkt DM, panelden değişir)

| Platform | Saatlik | Günlük |
|---|---|---|
| Instagram | 15 | 80 (hikaye yanıtı tavanından ayrı) |
| TikTok | 8 | 40 |
| Facebook | 8 | 30 |

Çalışma saatleri ve aksiyon beklemeleri platform başına, varsayılanları IG ile aynı.

## 5. Kontrol paneli

- Üstte platform seçici (Instagram / TikTok / Facebook); mevcut sekmeler seçili
  platforma göre çalışır.
- Üst bilgi satırı: üç platformun açık/kapalı durumu + bugün gönderilen açılış.
- Canlı durum: IG'de hikaye yanıtı + direkt DM sayaçları ayrı; TikTok/FB'de direkt DM.
- Platform başına Başlat / Duraklat / Botu kapat / "Tur şimdi" (IG'de hikaye ve
  DM turu ayrı düğme).
- Ayarlar platform başına; FB'de ek olarak grup linkleri (satır başına bir link).
- Do-not-contact sekmesi seçili platformun `dnc` kayıtlarını gösterir (neden dahil).

## 6. Hata yönetimi

| Durum | Davranış |
|---|---|
| Checkpoint / CAPTCHA / FB PIN ekranı | Yalnızca o platform duraklar (`<platform>:checkpoint_detected`, `master_paused`); panelde hata. |
| "İşlem engellendi" uyarısı | Yalnızca o platform duraklar (`action_block`). |
| Tek adım hatası (DOM, zaman aşımı, OpenAI) | Hata kaydı + artan bekleme, döngü sürer (bugünkü `run.py` davranışı). |
| Turda gönderimlerin çoğu başarısız | Log'da "S seçicileri güncellenmeli olabilir" uyarısı. |
| Mesaj kutusu kapalı | `dnc` + `dm_kapali`, bir daha denenmez. |
| Eşzamanlı DB yazımı (3 süreç) | SQLite WAL; kısa işlemler; her süreç kendi bağlantısı. |

## 7. Test

- **Birim (pytest):** `tests/` altında
  - göç: geçici DB'de geriye dönük doldurma, `dnc_handles → dnc` kopyası,
    idempotentlik; gerçek `sales.db` kopyasında 862 IG kaydının korunduğu.
  - repository: platformlu upsert/tekil indeks, `yakin_zamanda_iletisim`
    platform ayrımı, `dm_opener` sayaçları, `dnc` fonksiyonları, `bot_state` önekleri.
  - scheduler: `direkt_dm_turu_yap` sahte istemciyle (DNC/yazışılmış atlama,
    kota/saat/duraklatma ile tur bitişi, `DM_KAPALI` → dnc, tempo beklemesi).
  - IG hikaye turu testleri değişmeden geçer.
- Mevcut 80 test yeşil kalır.
- **Canlı (elle):** her platformda saatlik tavan 1–2 ile ilk tur; mesajın
  karşıya ulaştığı ikinci bir hesaptan doğrulanır, sonra kota açılır.

## 8. Uygulama sırası

Her parça ayrı uygulama planıyla:

- **A — Instagram:** veri modeli (bölüm 2), `platformlar.py` + `GonderimSonucu`,
  `direkt_dm_turu_yap`, IG takip listesi turu, panelde IG direkt DM ayar/sayaçları.
- **B — TikTok:** `tarayici.py` temeli (IG'nin taşınması), `tiktok.py`,
  `run.py --platform`, `surec.py`, panelde platform seçici.
- **C — Facebook:** `facebook.py`, grup listesi ayarı.
