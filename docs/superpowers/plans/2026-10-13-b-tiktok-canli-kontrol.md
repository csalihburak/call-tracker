# Parça B — TikTok canlı kontrol listesi

Otomatik testler TikTok DOM'unu **varsayılan** bir yapıyla (headless Chromium
`set_content`) doğruluyor. Gerçek TikTok sayfasıyla ilk karşılaşma aşağıdaki
sırayla, **senin gözetiminde** yapılır. Hiçbir adım onayın olmadan gerçek mesaj
göndermez: direkt DM bayrağı varsayılan kapalıdır.

Seçicilerin hepsi `ig_agent/tiktok.py` → `class S` içinde. ✔ işaretliler
2026-10-13'te herkese açık bir profilde (çıkış yapılmış hâlde) görüldü.

## 0. Hazırlık

- [ ] Instagram botu bu adımlardan etkilenmez; çalışıyorsa bırak.
- [ ] Panel yeni kodla açılsın: `./baslat.sh` (panel açılınca `sales.db` göçü
      çalışır — Parça A'nın `platform/handle` kolonları ve `dnc` tablosu henüz
      canlı DB'de yok; ilk açılışta eklenir, mevcut veriye dokunmaz).
- [ ] Panelde **Platform → TikTok**. Durum satırında "TikTok kapalı" görünmeli.
- [ ] Ayarlar → **TikTok kullanıcı adımız** alanına hesabı yaz (ör. `temizify`),
      **DM saatlik tavan = 1**, **DM günlük tavan = 2**, Kaydet.
- [ ] "TikTok'ta takip edilenlere direkt DM'i aç" **kapalı** kalsın.

## 1. Giriş ve tarayıcı

- [ ] **Başlat** → yeni bir Chromium penceresi açılır (`.tiktok_profile/`).
- [ ] TikTok'a elle giriş yap. Panelde "TikTok girişi bekleniyor" → "hazır"
      olmalı (`tiktok_agent.log`: `[tiktok] giriş tamam.`).
      Giriş yapıldığı hâlde beklemede kalırsa: `S.GIRIS_DUGMESI` (✔
      `data-e2e="top-login-button"`) giriş sonrası hâlâ görünüyor demektir.
- [ ] Bot "boşta — direkt DM kapalı — panelden açın" demeli.

## 2. Seçici doğrulama (mesaj göndermeden, tarayıcının geliştirici konsolunda)

Bot penceresinde kendi profilini aç (`tiktok.com/@<kullanıcı adı>`) ve konsolda:

- [ ] `document.querySelector('[data-e2e="nav-profile"]').getAttribute('href')`
      → `/@<kullanıcı adın>…` ✔
- [ ] `document.querySelector('[data-e2e="following-count"]')` var ✔ → tıkla;
      açılan pencere için `document.querySelector('[data-e2e="follow-info-popup"], div[role="dialog"]')`
      **null olmamalı** (`S.TAKIP_PENCERESI`). İçinde `a[href^="/@"]` bağlantıları olmalı.
      Pencerede "Takip edilen" sekmesinin seçili olduğunu gör.
- [ ] Takip ettiğin bir işletmenin profilinde `[data-e2e="message-button"]` ✔
      var mı? Tıkla → sohbet açılınca
      `document.querySelector('[data-e2e="message-input-area"] [contenteditable="true"], div[contenteditable="true"][role="textbox"], .public-DraftEditor-content, div[contenteditable="true"]')`
      **null olmamalı** (`S.MESAJ_KUTUSU`). Mesaj düğmesi yeni sekme açıyorsa not et
      (istemci aynı sekmede açılmasını bekliyor).
- [ ] Daha önce yazıştığın bir sohbette `document.querySelectorAll('[data-e2e="chat-item"]').length > 0`
      olmalı (`S.MESAJ_OGESI`; "önceden yazışılmış" tespiti). Boş yeni sohbette 0.
- [ ] DM'i kapalı bir hesap biliyorsan: ekrandaki uyarı metni `S.DM_KAPALI_METIN`
      listesindeki bir ifadeyi içermeli; içermiyorsa tam metni listeye ekle.
- [ ] Herhangi bir seçici tutmazsa `tiktok.py` → `S`'yi düzelt, botu kapat/başlat.

## 3. İlk tur (1 mesaj)

- [ ] Ayarlar → "TikTok'ta takip edilenlere direkt DM'i aç" **aç** → *DM turu şimdi*.
- [ ] Log'da `[tiktok] takip listesi toplandı: N hesap` (N ≈ takip sayın) ve
      `[dm] direkt DM turu: … gönderildi=1` görülmeli; saatlik tavan 1 olduğu için
      tur 1 mesajdan sonra durur.
- [ ] Mesajın karşıya ulaştığını **ikinci bir hesaptan** (ya da alıcının
      "mesaj istekleri"nden) doğrula. Panel → Konuşmalar (TikTok) altında hesap
      ve "direkt DM" satırı görünmeli.
- [ ] *DM turu şimdi* ile ikinci tur: aynı hesaba **tekrar yazılmamalı**
      (`atlandı(önceden yazılmış)=1`).
- [ ] Instagram'ın durum satırı ve sayaçları değişmemiş olmalı.

## 4. Hata davranışları

- [ ] CAPTCHA/bulmaca çıkarsa: TikTok botu duraklar, panelde "TikTok doğrulama
      (checkpoint / CAPTCHA) istedi". Bulmacayı **sen** çöz → *Uyarıyı temizle* →
      *Başlat*. Instagram botu çalışmaya devam etmeli.
- [ ] Log'da `hiç DM gönderilemedi — S.MESAJ_KUTUSU …` uyarısı görürsen 2. adıma dön.
- [ ] `önceki_sohbet` sayısı beklenmedik derecede yüksekse `S.MESAJ_OGESI` yanlış
      pozitif veriyordur; düzelttikten sonra
      `DELETE FROM dnc WHERE platform='tiktok' AND reason='onceki_sohbet'`.

## 5. Kotayı açma

- [ ] İlk gün sorunsuz geçerse saatlik/günlük tavanı varsayılana (8 / 40) çıkar.
      TikTok yeni/az etkileşimli hesaplardan gelen DM'leri sıkı sınırlar;
      engel uyarısı görülürse tavanı düşür.
