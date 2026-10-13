# Parça A — Instagram takip edilenlere direkt DM · Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bot, hikaye turundan sonra Instagram'da takip ettiğimiz ama hiç yazışmadığımız hesaplara ayrı kotayla direkt DM açılışı atsın; veri modeli TikTok/Facebook'a hazır (platformlu) olsun.

**Architecture:** `sales.db` şeması additive olarak platformlu hale gelir (`leads.platform/handle`, `dnc` tablosu, `dm_opener` mesaj yönü). Yeni `platformlar.py` ortak tipleri (`Hedef`, `GonderimSonucu`, `TURU_BITIR`) taşır. `scheduler.direkt_dm_turu_yap` hikaye turunun kalıbını izler ve istemcinin `acilis_turu(karar_fn, sonuc_fn, yazmadan_once)` metodunu sürer; `InstagramClient.acilis_turu` takip listesini toplayıp profil → DM gönderir. Panelde aç/kapa, kota ve sayaçlar.

**Tech Stack:** Python 3.12, SQLite (WAL), Playwright (sync), Streamlit, pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-cok-platformlu-dm-design.md` (bölüm 2, 3, 4.1, 4.4, 5, 6, 7; parça A)

**Bu parçada bilinçli olarak YOK (spec'te var, B'ye kalır):** `bot_state` platform önekleri (spec 2.5 — A'da tek platform var), `istemci_olustur` fabrikası, `tarayici.py`, `run.py --platform`, panelde platform seçici. Spec 3.1'deki `dm_gonder → GonderimSonucu` yerine IG'de `dm_gonder` bool kalır (RESPOND akışı `if gonderildi` ile kullanıyor; `str` Enum'un `BASARISIZ` değeri truthy olurdu) ve üç durumlu sonuç `_dm_gonder_sonuc`'tan gelir.

## Global Constraints

- Python: her komut `.venv/bin/python3.12` ile (Task 1'de kurulur).
- Şema **yalnızca additive**: hiçbir tablo/kolon silinmez veya yeniden adlandırılmaz; call-tracker `app.py` etkilenmez.
- Instagram `bot_state` anahtarları **öneksiz** kalır (`master_paused`, `ayar.yeniden_iletisim_gun`, …).
- Tekrar kuralı platform bazında; `yeniden_iletisim_gun <= 0` → o platformda o hesapla herhangi bir yönde mesaj varsa asla açılış yok.
- Direkt DM başlangıç kotaları: saatlik **15**, günlük **80** (0 = sınırsız); hikaye yanıtı tavanları (100/saat) aynen kalır ve birbirinden bağımsızdır.
- Direkt DM açılışı varsayılan **kapalı** (`bot_state.dm_acilis_aktif = 0`); panelden açılır (hashtag keşfiyle aynı desen).
- `DM_KAPALI` yalnızca sayfada **açık bir "mesaj gönderilemez" metni** görülünce döner; seçici bulunamaması `BASARISIZ`'dır (seçici kırılması hesapları toplu DNC'ye atmasın).
- Gelen mesaja cevap (RESPOND) akışı değişmez.
- Kod dili/isimlendirme Türkçe, mevcut dosyaların yorum yoğunluğu ve deyimleri izlenir.
- Mevcut testlerin hepsi yeşil kalır.
- Commit'lerde dosyalar **açıkça** eklenir (`git add <yol>`); `git add -A` / `git commit -a` kullanılmaz (repoda ilgisiz `.ig_profile` değişiklikleri var). Commit mesajı sonu: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Seçici kırılması (profilde "Mesaj gönder" yok, yeni-mesaj akışı da açılmıyor, uyarı metni yok) → `BASARISIZ`, DNC'ye **eklenmez** — Task 5 testi.
2. Takip listesi boş döner (kullanıcı adı bulunamadı / pencere açılmadı) → tur 0 gönderir, `son_dm_turu` damgalanır (sıcak döngü yok) — Task 4 testi.
3. Bir hesaba DM atıldıktan sonra hikaye tepsisinde görünürse hikaye yanıtı da atılmaz (ve tersi) — Task 4 testi.
4. Tur ortasında durup yeniden başlama: o ana kadar gönderilenler DB'de, ikinci turda tekrar gönderilmez — Task 4 testi.
5. Hikaye kotası dolu iken DM sürer; DM kotası dolu iken hikaye sürer — Task 4 testi.

---

## Dosya yapısı

| Dosya | Durum | Sorumluluk |
|---|---|---|
| `ig_agent/db.py` | Değişir | Platform kolonları, geriye dönük doldurma, `(platform, handle)` indeksi, `dnc` tablosu |
| `ig_agent/repository.py` | Değişir | `lead_upsert`, `lead_getir_platform`, platformlu `yakin_zamanda_iletisim`, `dnc_*`, `dm_opener` sayaçları |
| `ig_agent/platformlar.py` | **Yeni** | `TURU_BITIR`, `GonderimSonucu`, `Hedef`, `PlatformIstemci` protokolü |
| `ig_agent/config.py` | Değişir | `dm_acilis_saatlik/gunluk`, `dm_turu_cooldown_sn`, `kendi_kullanici_adi` |
| `ig_agent/canli_ayarlar.py` | Değişir | Yeni panel alanları |
| `ig_agent/llm_openai.py` | Değişir | `acilis_uret(..., baglam)` |
| `ig_agent/scheduler.py` | Değişir | `DIRECT_DM` görevi, `direkt_dm_turu_yap`, kota |
| `ig_agent/instagram.py` | Değişir | `takip_listesi_topla`, `_dm_gonder_sonuc`, `acilis_turu` |
| `ig_agent/run.py` | Değişir | Boşta nedeni metni |
| `ig_agent/control_panel.py` | Değişir | DM aç/kapa, ayarlar, sayaçlar, "DM turu şimdi", `dnc` sekmesi |
| `ig_agent/README.md` | Değişir | Direkt DM bölümü |
| `tests/test_repository.py`, `tests/test_scheduler.py`, `tests/test_canli_ayarlar.py` | Değişir | Yeni testler |
| `tests/test_goc_gercek_db.py`, `tests/test_instagram_acilis.py`, `tests/test_panel_smoke.py` | **Yeni** | Gerçek DB göçü, IG tur döngüsü, panel duman testi |

---

### Task 1: Ortam + platformlu şema göçü

**Files:**
- Modify: `ig_agent/db.py` (`LEADS_EK_KOLONLAR`, `gocu_uygula`)
- Test: `tests/test_repository.py`, Create: `tests/test_goc_gercek_db.py`

**Interfaces:**
- Produces: `leads.platform`, `leads.handle`, `leads.profile_url`, `leads.discovery_source` kolonları; indeks `idx_leads_platform_handle`; tablo `dnc(platform, handle, reason, created_at)`.

- [ ] **Step 0: Sanal ortamı yeniden kur** (`.venv` silinmiş; `baslat.sh` buna bağlı)

```bash
cd /Users/salihburakcoskun/Desktop/call-tracker
python3.12 -m venv .venv
.venv/bin/python3.12 -m pip install -r ig_agent/requirements.txt
.venv/bin/python3.12 -m playwright install chromium
.venv/bin/python3.12 -m pytest tests/ -q
```
Expected: tüm mevcut testler PASS (≈80). Geçmeyen varsa dur ve raporla.

- [ ] **Step 1: Failing testleri yaz** — `tests/test_repository.py` sonuna:

```python
def test_goc_platform_kolonlari_ve_dnc_tablosu(baglanti):
    kolonlar = {s["name"] for s in baglanti.execute("PRAGMA table_info(leads)")}
    assert {"platform", "handle", "profile_url", "discovery_source"} <= kolonlar
    assert "dnc" in set(db.tablo_adlari(baglanti))


def test_goc_mevcut_ig_leadlerini_ve_dnc_yi_doldurur(baglanti):
    # Eski kod gibi: yalnız ig_handle'lı lead + dnc_handles satırı
    baglanti.execute(
        "INSERT INTO leads (business_name, source, ig_handle, ig_profile_url) "
        "VALUES ('Eski', 'Instagram', 'eski_hesap', 'https://www.instagram.com/eski_hesap/')"
    )
    baglanti.execute(
        "INSERT INTO dnc_handles (handle, reason) VALUES ('kotu_hesap', 'rahatsız etmeyin')"
    )
    baglanti.commit()

    db.gocu_uygula(baglanti)
    db.gocu_uygula(baglanti)  # idempotent

    l = baglanti.execute("SELECT * FROM leads WHERE ig_handle='eski_hesap'").fetchone()
    assert l["platform"] == "instagram" and l["handle"] == "eski_hesap"
    assert l["profile_url"] == "https://www.instagram.com/eski_hesap/"
    d = baglanti.execute("SELECT * FROM dnc WHERE handle='kotu_hesap'").fetchall()
    assert len(d) == 1 and d[0]["platform"] == "instagram" and d[0]["reason"] == "rahatsız etmeyin"


def test_platform_handle_tekil(baglanti):
    baglanti.execute("INSERT INTO leads (business_name, platform, handle) VALUES ('a','tiktok','x')")
    with pytest.raises(sqlite3.IntegrityError):
        baglanti.execute("INSERT INTO leads (business_name, platform, handle) VALUES ('b','tiktok','x')")
    # Aynı handle başka platformda serbest
    baglanti.execute("INSERT INTO leads (business_name, platform, handle) VALUES ('c','facebook','x')")
```

`tests/test_goc_gercek_db.py`:

```python
"""Göçü gerçek sales.db'nin bir kopyası üzerinde dener (varsa)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ig_agent import db

GERCEK = Path(__file__).resolve().parent.parent / "sales.db"


@pytest.mark.skipif(not GERCEK.exists(), reason="sales.db yok")
def test_gercek_db_kopyasinda_goc(tmp_path):
    kopya = tmp_path / "kopya.db"
    kaynak = sqlite3.connect(str(GERCEK))  # yalnız okunur; backup yazmaz
    hedef = sqlite3.connect(kopya)
    kaynak.backup(hedef)  # WAL içeriği dahil tutarlı kopya
    kaynak.close()
    hedef.row_factory = sqlite3.Row

    once_lead = hedef.execute("SELECT COUNT(*) n FROM leads").fetchone()["n"]
    once_ig = hedef.execute("SELECT COUNT(*) n FROM leads WHERE ig_handle IS NOT NULL").fetchone()["n"]
    once_msj = hedef.execute("SELECT COUNT(*) n FROM ig_messages").fetchone()["n"]

    db.gocu_uygula(hedef)

    assert hedef.execute("SELECT COUNT(*) n FROM leads").fetchone()["n"] == once_lead
    assert hedef.execute("SELECT COUNT(*) n FROM ig_messages").fetchone()["n"] == once_msj
    dolu = hedef.execute(
        "SELECT COUNT(*) n FROM leads WHERE platform='instagram' AND handle = ig_handle"
    ).fetchone()["n"]
    assert dolu == once_ig
    hedef.close()
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu gör**

Run: `.venv/bin/python3.12 -m pytest tests/test_repository.py tests/test_goc_gercek_db.py -q`
Expected: yeni 4 test FAIL (`platform` kolonu / `dnc` tablosu yok).

- [ ] **Step 3: Uygula** — `ig_agent/db.py`

`LEADS_EK_KOLONLAR` listesinin sonuna (`ai_son_islenen_mesaj_id`'den sonra):

```python
    # Platformlu kimlik (instagram | tiktok | facebook). IG lead'lerinde
    # ig_handle de dolmaya devam eder (Sheets/panel uyumu).
    ("platform", "TEXT"),
    ("handle", "TEXT"),
    ("profile_url", "TEXT"),
    # Açılış kaynağı: hikaye | takip_listesi | FB grup id'si
    ("discovery_source", "TEXT"),
```

`gocu_uygula` içinde, kolon ekleme döngüsünden hemen sonra:

```python
        # Mevcut IG lead'lerini platformlu kimliğe geriye dönük doldur
        baglanti.execute(
            "UPDATE leads SET platform = 'instagram', handle = ig_handle, "
            "profile_url = COALESCE(profile_url, ig_profile_url) "
            "WHERE ig_handle IS NOT NULL AND handle IS NULL"
        )
```

`dnc_handles` tablosu oluşturulduktan hemen sonra:

```python
        # Platform bazlı do-not-contact. dnc_handles eski kayıtlar için
        # kopyalanır; artık okunmaz ama silinmez.
        baglanti.execute(
            """
            CREATE TABLE IF NOT EXISTS dnc (
                platform   TEXT NOT NULL,
                handle     TEXT NOT NULL,
                reason     TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (platform, handle)
            )
            """
        )
        baglanti.execute(
            "INSERT OR IGNORE INTO dnc (platform, handle, reason, created_at) "
            "SELECT 'instagram', handle, reason, created_at FROM dnc_handles"
        )
```

`idx_leads_ig_handle` indeksinden sonra:

```python
        baglanti.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_platform_handle "
            "ON leads(platform, handle) WHERE handle IS NOT NULL"
        )
```

- [ ] **Step 4: Testleri çalıştır**

Run: `.venv/bin/python3.12 -m pytest tests/ -q`
Expected: hepsi PASS.

- [ ] **Step 5: Commit**

```bash
git add ig_agent/db.py tests/test_repository.py tests/test_goc_gercek_db.py
git commit -m "feat(db): platformlu lead kimliği ve dnc tablosu

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Platformlu repository

**Files:**
- Modify: `ig_agent/repository.py`
- Test: `tests/test_repository.py`

**Interfaces:**
- Consumes: Task 1 kolonları ve `dnc` tablosu.
- Produces:
  - `PLATFORM_KAYNAK: dict[str, str]` = `{"instagram": "Instagram", "tiktok": "TikTok", "facebook": "Facebook"}`
  - `lead_upsert(conn, *, platform: str, handle: str, business_name: str = "", profile_url: str = "", discovery_source: str = "") -> int`
  - `lead_getir_platform(conn, platform: str, handle: str) -> Optional[Row]`
  - `yakin_zamanda_iletisim(conn, ig_handle: str, gun: int, platform: str = "instagram") -> bool`
  - `dnc_mi(conn, handle: str, platform: str = "instagram") -> bool`
  - `dnc_ekle(conn, handle: str, reason: str = "", platform: str = "instagram") -> None`
  - `dnc_listesi(conn, platform: str = "instagram", limit: int = 100) -> list[Row]`
  - `mesaj_ekle(..., direction="dm_opener", ...)` desteği
  - `son_saat_dm_acilis_sayisi(conn, platform="instagram") -> int`, `bugun_dm_acilis_sayisi(conn, platform="instagram") -> int`, `son_dm_acilis_zamani(conn, platform="instagram") -> Optional[str]`
  - `dnc_handle_mi(conn, ig_handle)` korunur (artık `dnc`'ye bakar).

- [ ] **Step 1: Failing testleri yaz** — `tests/test_repository.py` sonuna:

```python
def test_lead_upsert_platform_bazinda(baglanti):
    a = repo.lead_upsert(baglanti, platform="tiktok", handle="halici", business_name="Halıcı")
    b = repo.lead_upsert(baglanti, platform="tiktok", handle="halici")
    c = repo.lead_upsert(baglanti, platform="instagram", handle="halici", discovery_source="takip_listesi")
    assert a == b and a != c
    t = repo.lead_getir(baglanti, a)
    assert t["source"] == "TikTok" and t["ig_handle"] is None and t["stage"] == "yeni"
    i = repo.lead_getir(baglanti, c)
    assert i["source"] == "Instagram" and i["ig_handle"] == "halici"
    assert i["discovery_source"] == "takip_listesi"
    assert repo.lead_getir_platform(baglanti, "instagram", "halici")["id"] == c


def test_ig_lead_upsert_platform_alanlarini_doldurur(baglanti):
    lid = repo.ig_lead_upsert(baglanti, ig_handle="yeni_ig", business_name="Y")
    l = repo.lead_getir(baglanti, lid)
    assert l["platform"] == "instagram" and l["handle"] == "yeni_ig"
    # lead_upsert aynı lead'i bulur
    assert repo.lead_upsert(baglanti, platform="instagram", handle="yeni_ig") == lid


def test_yakin_zamanda_iletisim_platform_ayrimi(baglanti):
    lid = repo.lead_upsert(baglanti, platform="instagram", handle="ortak")
    repo.mesaj_ekle(baglanti, lid, "story_reply", "selam")
    assert repo.yakin_zamanda_iletisim(baglanti, "ortak", 0) is True
    assert repo.yakin_zamanda_iletisim(baglanti, "ortak", 0, platform="tiktok") is False


def test_dnc_platform_bazinda(baglanti):
    repo.dnc_ekle(baglanti, "kapali_hesap", "dm_kapali", platform="tiktok")
    repo.dnc_ekle(baglanti, "kapali_hesap", "tekrar", platform="tiktok")  # INSERT OR IGNORE
    assert repo.dnc_mi(baglanti, "kapali_hesap", platform="tiktok")
    assert not repo.dnc_mi(baglanti, "kapali_hesap")  # instagram'da değil
    satirlar = repo.dnc_listesi(baglanti, platform="tiktok")
    assert len(satirlar) == 1 and satirlar[0]["reason"] == "dm_kapali"


def test_do_not_contact_isaretle_dnc_tablosuna_yazar(baglanti):
    lid = repo.ig_lead_upsert(baglanti, ig_handle="red_eden", business_name="R")
    repo.do_not_contact_isaretle(baglanti, lid, reason="istemiyor")
    assert repo.dnc_mi(baglanti, "red_eden") and repo.dnc_handle_mi(baglanti, "red_eden")


def test_dm_opener_mesaji_ve_sayaclar(baglanti):
    lid = repo.lead_upsert(baglanti, platform="instagram", handle="dmli")
    hid = repo.lead_upsert(baglanti, platform="instagram", handle="hikayeli")
    repo.mesaj_ekle(baglanti, lid, "dm_opener", "Merhaba")
    repo.mesaj_ekle(baglanti, hid, "story_reply", "Kolay gelsin")
    l = repo.lead_getir(baglanti, lid)
    assert l["stage"] == "ilk_temas" and l["last_outbound_at"] is not None
    assert l["last_story_reply_at"] is None
    assert repo.son_saat_dm_acilis_sayisi(baglanti) == 1
    assert repo.bugun_dm_acilis_sayisi(baglanti) == 1
    assert repo.son_dm_acilis_zamani(baglanti) is not None
    assert repo.son_saat_dm_acilis_sayisi(baglanti, platform="tiktok") == 0
    # hikaye sayaçları DM'i saymaz
    assert repo.son_saat_acilis_sayisi(baglanti) == 1
```

- [ ] **Step 2: Çalıştır**

Run: `.venv/bin/python3.12 -m pytest tests/test_repository.py -q`
Expected: yeni testler FAIL (`lead_upsert` / `dnc_ekle` tanımlı değil).

- [ ] **Step 3: Uygula** — `ig_agent/repository.py`

`KAPALI_ASAMALAR`'dan sonra:

```python
# platform → leads.source (call-tracker'daki kaynak filtresiyle uyumlu)
PLATFORM_KAYNAK = {"instagram": "Instagram", "tiktok": "TikTok", "facebook": "Facebook"}
```

`ig_lead_upsert` içindeki INSERT'i platform alanlarını da dolduracak şekilde değiştir:

```python
            INSERT INTO leads
                (business_name, city, notes, stage, source,
                 ig_handle, ig_profile_url, ig_followers,
                 discovery_hashtag, discovery_city, sheet_dirty,
                 platform, handle, profile_url)
            VALUES (?, ?, ?, 'yeni', ?, ?, ?, ?, ?, ?, 1, 'instagram', ?, ?)
```
parametre demetinin sonuna `ig_handle, ig_profile_url` ekle.

`ig_lead_upsert`'ten sonra:

```python
def lead_upsert(
    baglanti: sqlite3.Connection,
    *,
    platform: str,
    handle: str,
    business_name: str = "",
    profile_url: str = "",
    discovery_source: str = "",
) -> int:
    """(platform, handle)'a göre lead ekler; varsa mevcut id'yi döner (dedupe)."""
    mevcut = lead_getir_platform(baglanti, platform, handle)
    if mevcut:
        return int(mevcut["id"])
    ig_handle = handle if platform == "instagram" else None
    with baglanti:
        imlec = baglanti.execute(
            """
            INSERT INTO leads
                (business_name, stage, source, platform, handle, profile_url,
                 discovery_source, ig_handle, ig_profile_url, sheet_dirty)
            VALUES (?, 'yeni', ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                business_name or handle,
                PLATFORM_KAYNAK[platform],
                platform,
                handle,
                profile_url,
                discovery_source,
                ig_handle,
                profile_url if ig_handle else None,
            ),
        )
    return int(imlec.lastrowid)


def lead_getir_platform(
    baglanti: sqlite3.Connection, platform: str, handle: str
) -> Optional[sqlite3.Row]:
    return baglanti.execute(
        "SELECT * FROM leads WHERE platform = ? AND handle = ?", (platform, handle)
    ).fetchone()
```

`do_not_contact_isaretle` içindeki handle sorgusu ve INSERT'i değiştir:

```python
        satir = baglanti.execute(
            "SELECT platform, handle FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()
        if satir and satir["handle"]:
            baglanti.execute(
                "INSERT OR IGNORE INTO dnc (platform, handle, reason) VALUES (?, ?, ?)",
                (satir["platform"] or "instagram", satir["handle"], reason),
            )
```

`dnc_handle_mi`'yi şu blokla değiştir:

```python
def dnc_mi(
    baglanti: sqlite3.Connection, handle: str, platform: str = "instagram"
) -> bool:
    satir = baglanti.execute(
        "SELECT 1 FROM dnc WHERE platform = ? AND handle = ?", (platform, handle)
    ).fetchone()
    return satir is not None


def dnc_handle_mi(baglanti: sqlite3.Connection, ig_handle: str) -> bool:
    return dnc_mi(baglanti, ig_handle, "instagram")


def dnc_ekle(
    baglanti: sqlite3.Connection,
    handle: str,
    reason: str = "",
    platform: str = "instagram",
) -> None:
    """Hesabı o platformda bir daha yazılmayacaklara ekler (varsa dokunmaz)."""
    with baglanti:
        baglanti.execute(
            "INSERT OR IGNORE INTO dnc (platform, handle, reason) VALUES (?, ?, ?)",
            (platform, handle, reason),
        )


def dnc_listesi(
    baglanti: sqlite3.Connection, platform: str = "instagram", limit: int = 100
) -> list[sqlite3.Row]:
    return baglanti.execute(
        "SELECT handle, reason, created_at FROM dnc WHERE platform = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (platform, limit),
    ).fetchall()
```

`yakin_zamanda_iletisim` imzasını `(baglanti, ig_handle: str, gun: int, platform: str = "instagram")` yap; docstring'e "Platform bazındadır: başka platformdaki yazışma sayılmaz." ekle; sorguda `WHERE l.ig_handle = ?` yerine `WHERE l.platform = ? AND l.handle = ?`, parametreler:

```python
    parametreler: tuple = (platform, ig_handle)
    if gun > 0:
        sure_kosulu = "AND julianday('now','localtime') - julianday(m.sent_at) < ?"
        parametreler = (platform, ig_handle, gun)
```

`mesaj_ekle` içinde `elif direction == "story_reply":` bloğundan sonra, `else:`'ten önce:

```python
        elif direction == "dm_opener":
            baglanti.execute(
                "UPDATE leads SET last_outbound_at = datetime('now','localtime'), "
                "stage = CASE WHEN stage = 'yeni' THEN 'ilk_temas' ELSE stage END, "
                "sheet_dirty = 1 WHERE id = ?",
                (lead_id,),
            )
```

"Günlük sayaçlar" bölümüne, `son_acilis_zamani`'ndan sonra:

```python
def _dm_acilis_sorgu(
    baglanti: sqlite3.Connection, secim: str, platform: str, kosul: str
) -> sqlite3.Row:
    return baglanti.execute(
        f"SELECT {secim} FROM ig_messages m JOIN leads l ON l.id = m.lead_id "
        f"WHERE m.direction = 'dm_opener' AND l.platform = ? {kosul}",
        (platform,),
    ).fetchone()


def son_saat_dm_acilis_sayisi(
    baglanti: sqlite3.Connection, platform: str = "instagram"
) -> int:
    """Son 60 dakikada gönderilen direkt DM açılışı (saatlik tavan için)."""
    satir = _dm_acilis_sorgu(
        baglanti, "COUNT(*) AS n", platform,
        "AND m.sent_at >= datetime('now','localtime','-1 hour')",
    )
    return int(satir["n"]) if satir else 0


def bugun_dm_acilis_sayisi(
    baglanti: sqlite3.Connection, platform: str = "instagram"
) -> int:
    satir = _dm_acilis_sorgu(
        baglanti, "COUNT(*) AS n", platform,
        "AND date(m.sent_at) = date('now','localtime')",
    )
    return int(satir["n"]) if satir else 0


def son_dm_acilis_zamani(
    baglanti: sqlite3.Connection, platform: str = "instagram"
) -> Optional[str]:
    satir = _dm_acilis_sorgu(baglanti, "MAX(m.sent_at) AS t", platform, "")
    return satir["t"] if satir else None
```

- [ ] **Step 4: Testleri çalıştır**

Run: `.venv/bin/python3.12 -m pytest tests/ -q`
Expected: hepsi PASS.

- [ ] **Step 5: Commit**

```bash
git add ig_agent/repository.py tests/test_repository.py
git commit -m "feat(repo): platformlu lead/dnc ve dm_opener sayaçları

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Platform tipleri, ayarlar ve DM açılış metni

**Files:**
- Create: `ig_agent/platformlar.py`
- Modify: `ig_agent/instagram.py:24-28` (`TURU_BITIR` taşınır), `ig_agent/config.py`, `ig_agent/canli_ayarlar.py`, `ig_agent/llm_openai.py`, `ig_agent/scheduler.py` (`_acilis_metni`, import)
- Test: `tests/test_canli_ayarlar.py`, `tests/test_scheduler.py`

**Interfaces:**
- Produces:
  - `platformlar.TURU_BITIR: str` (`instagram.TURU_BITIR` aynı nesneyi yeniden dışa verir)
  - `platformlar.GonderimSonucu` (`str, Enum`): `GONDERILDI="gonderildi"`, `BASARISIZ="basarisiz"`, `DM_KAPALI="dm_kapali"`
  - `platformlar.Hedef` (frozen dataclass): `handle: str`, `ad: str = ""`, `profile_url: str = ""`, `kaynak: str = ""`
  - `platformlar.PlatformIstemci` protokolü: `platform: str`, `engel_algilandi: bool`, `acilis_turu(karar_fn, sonuc_fn, yazmadan_once) -> None`
  - `PacingAyarlari.dm_acilis_saatlik: int = 15`, `dm_acilis_gunluk: int = 80`, `dm_turu_cooldown_sn: int = 1800`
  - `Ayarlar.kendi_kullanici_adi: str = ""`
  - `scheduler._acilis_metni(beyin_istemci, ayarlar, lead, rng=None, baglam: str = "hikaye") -> str`
  - `OpenAIIstemci.acilis_uret(ayarlar, lead, baglam: str = "hikaye") -> str`

- [ ] **Step 1: Failing testleri yaz**

`tests/test_canli_ayarlar.py` sonuna:

```python
def test_dm_ayarlari_bindirilir(ortam):
    conn, temel = ortam
    assert temel.pacing.dm_acilis_saatlik == 15 and temel.pacing.dm_acilis_gunluk == 80
    canli_ayarlar.kaydet(conn, {
        "dm_acilis_saatlik": 5, "dm_acilis_gunluk": 20,
        "dm_turu_cooldown_sn": 900, "kendi_kullanici_adi": "temizify.app",
    })
    a = canli_ayarlar.uygula(conn, temel)
    assert a.pacing.dm_acilis_saatlik == 5 and a.pacing.dm_acilis_gunluk == 20
    assert a.pacing.dm_turu_cooldown_sn == 900
    assert a.kendi_kullanici_adi == "temizify.app"
```

`tests/test_scheduler.py` sonuna:

```python
def test_acilis_metni_baglami_beyne_iletir(ortam):
    conn, ayarlar, lead = ortam

    class SahteBeyin:
        def __init__(self):
            self.baglamlar = []

        def acilis_uret(self, ayarlar, lead, baglam="hikaye"):
            self.baglamlar.append(baglam)
            return f"metin-{baglam}"

    beyin = SahteBeyin()
    assert sch._acilis_metni(beyin, ayarlar, None) == "metin-hikaye"
    assert sch._acilis_metni(beyin, ayarlar, None, baglam="dm") == "metin-dm"
    assert beyin.baglamlar == ["hikaye", "dm"]


def test_turu_bitir_tek_kaynak():
    from ig_agent import instagram, platformlar

    assert instagram.TURU_BITIR is platformlar.TURU_BITIR
```

- [ ] **Step 2: Çalıştır**

Run: `.venv/bin/python3.12 -m pytest tests/test_canli_ayarlar.py tests/test_scheduler.py -q`
Expected: yeni 3 test FAIL.

- [ ] **Step 3: Uygula**

`ig_agent/platformlar.py`:

```python
"""Platform istemcilerinin (Instagram, ileride TikTok/Facebook) ortak tipleri.

Zamanlayıcı yalnızca bu arayüzü görür: istemci hedefleri gezer, her hedef için
`karar_fn` ile ne yazılacağını sorar, gönderir ve sonucu `sonuc_fn` ile bildirir.
İstemci DB'ye dokunmaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Protocol

# karar_fn bunu dönerse tur hemen biter (duraklatıldı, kota doldu, saat bitti)
TURU_BITIR = "__TURU_BITIR__"


class GonderimSonucu(str, Enum):
    GONDERILDI = "gonderildi"
    # Geçici/teknik hata ya da seçici bulunamadı — sonraki turda tekrar denenir
    BASARISIZ = "basarisiz"
    # Platform açıkça "bu hesaba mesaj gönderilemez" dedi — bir daha denenmez
    DM_KAPALI = "dm_kapali"


@dataclass(frozen=True)
class Hedef:
    handle: str
    ad: str = ""
    profile_url: str = ""
    kaynak: str = ""  # takip_listesi | FB grup id'si


KararFn = Callable[[Hedef], Optional[str]]
SonucFn = Callable[[Hedef, str, GonderimSonucu], None]


class PlatformIstemci(Protocol):
    platform: str
    engel_algilandi: bool

    def acilis_turu(
        self, karar_fn: KararFn, sonuc_fn: SonucFn, yazmadan_once: Callable[[], bool]
    ) -> None: ...
```

`ig_agent/instagram.py`: `TURU_BITIR = "__TURU_BITIR__"` satırını ve üstündeki iki yorum satırını sil; importlara ekle:

```python
from .platformlar import TURU_BITIR, GonderimSonucu, Hedef  # noqa: F401 — TURU_BITIR dışa verilir
```

`ig_agent/scheduler.py`: `from .instagram import TURU_BITIR` → `from .platformlar import TURU_BITIR, GonderimSonucu, Hedef`.

`ig_agent/config.py` — `PacingAyarlari` içinde `hikaye_turu_cooldown_sn`'den sonra:

```python
    # Takip listesinden direkt DM açılışı (hikaye yanıtından AYRI tavan). 0 = sınırsız.
    dm_acilis_saatlik: int = 15
    dm_acilis_gunluk: int = 80
    # Direkt DM turunu yeniden başlatmadan önce beklenecek süre (saniye)
    dm_turu_cooldown_sn: int = 1800
```

`Ayarlar` içinde `acilis_metinleri`'nden sonra:

```python
    # Kendi IG kullanıcı adımız (takip listesi için). Boşsa sayfadan bulunur.
    kendi_kullanici_adi: str = ""
```

`ayarlari_yukle` içinde `acilis_modu=...` satırından sonra `kendi_kullanici_adi=_str("IG_KULLANICI_ADI"),`; `PacingAyarlari(...)` içinde `hikaye_turu_cooldown_sn=...`'den sonra:

```python
            dm_acilis_saatlik=_int("IG_DM_ACILIS_SAATLIK", 15),
            dm_acilis_gunluk=_int("IG_DM_ACILIS_GUNLUK", 80),
            dm_turu_cooldown_sn=_int("IG_DM_TURU_COOLDOWN_SN", 1800),
```

`ig_agent/canli_ayarlar.py` — `ALANLAR` sözlüğüne:

```python
    "dm_acilis_saatlik": ("pacing", int),
    "dm_acilis_gunluk": ("pacing", int),
    "dm_turu_cooldown_sn": ("pacing", int),
    "kendi_kullanici_adi": (None, str),
```

`ig_agent/scheduler.py` — `_acilis_metni`'yi değiştir:

```python
def _acilis_metni(
    beyin_istemci, ayarlar, lead, rng: Optional[random.Random] = None, baglam: str = "hikaye"
) -> str:
    """Açılış metni (`baglam`: "hikaye" = hikaye yanıtı, "dm" = direkt DM).

    "sabit" modda panelde girilen satırlardan rastgele biri; aksi halde beyin
    varsa GPT ile çeşitlendirilmiş metin, yoksa güvenli sabit.
    """
    if getattr(ayarlar, "acilis_modu", "gpt") == "sabit":
        satirlar = [x.strip() for x in (ayarlar.acilis_metinleri or "").splitlines() if x.strip()]
        if satirlar:
            return (rng or random).choice(satirlar)
    try:
        if hasattr(beyin_istemci, "acilis_uret"):
            return beyin_istemci.acilis_uret(ayarlar, lead, baglam=baglam)
    except Exception:
        pass
    return "Merhabalar, kolay gelsin! İşlerinizin takibini yapmak için herhangi bir program kullanıyor musunuz?"
```

`ig_agent/llm_openai.py` — `VARSAYILAN_ACILIS`'ten sonra:

```python
# Açılışın nereye gittiğine göre sistem talimatının başı
ACILIS_BAGLAMI = {
    "hikaye": "Bir halı yıkama işletmesinin Instagram hikayesine yanıt olarak gidecek",
    "dm": (
        "Bir halı yıkama işletmesine Instagram'dan doğrudan mesaj (DM) olarak gidecek; "
        "hikayelerine atıf yapma, bizi tanımıyorlar"
    ),
}
```

`acilis_uret` imzası `def acilis_uret(self, ayarlar: Ayarlar, lead, baglam: str = "hikaye") -> str:`; docstring "Kısa, çeşitlendirilmiş bir açılış metni üretir."; system içeriğinin ilk satırı:

```python
                        "content": (
                            f"{ACILIS_BAGLAMI.get(baglam, ACILIS_BAGLAMI['hikaye'])} "
                            "KISA, samimi bir açılış mesajı yaz. "
                            "Amaç: iş takibi için program kullanıp kullanmadıklarını sormak. "
```
(kalan satırlar aynen). Modül docstring'indeki "(hikaye-yanıtı metni çeşitlendirme)" → "(açılış metni çeşitlendirme)".

- [ ] **Step 4: Testleri çalıştır**

Run: `.venv/bin/python3.12 -m pytest tests/ -q`
Expected: hepsi PASS.

- [ ] **Step 5: Commit**

```bash
git add ig_agent/platformlar.py ig_agent/instagram.py ig_agent/scheduler.py ig_agent/config.py ig_agent/canli_ayarlar.py ig_agent/llm_openai.py tests/test_canli_ayarlar.py tests/test_scheduler.py
git commit -m "feat: platform tipleri, direkt DM ayarları ve DM açılış bağlamı

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Zamanlayıcıda direkt DM turu

**Files:**
- Modify: `ig_agent/scheduler.py`, `ig_agent/run.py` (`_bosta_nedeni`)
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: Task 2 repository fonksiyonları; Task 3 `Hedef`, `GonderimSonucu`, `TURU_BITIR`, `_acilis_metni(..., baglam)`, `PacingAyarlari.dm_*`.
- Produces:
  - `DIRECT_DM = "direct_dm"`
  - `sonraki_gorev(izinli, yanit_var, acilis_var, dm_var: bool = False) -> Optional[str]` — öncelik RESPOND > OPENER > DIRECT_DM > DISCOVER
  - `dm_acilis_kalan(conn, ayarlar) -> int`, `dm_acilis_araligi_sn(ayarlar, rng) -> float`
  - `direkt_dm_turu_yap(conn, ayarlar, istemci, beyin_istemci, rng=None, uyku_fn=None, simdi_fn=datetime.now) -> int` (gönderilen sayısı)
  - `kota_durumlari` artık `DIRECT_DM` içerir (tavan, `bot_state.dm_acilis_aktif` kapalıysa 0)
  - `durum_ozeti` ek anahtarlar: `dm_aktif: bool`, `dm_son_saat: int`, `dm_bugun: int`
  - `bot_state.son_dm_turu` (ISO zaman) soğuma damgası

- [ ] **Step 1: Failing testleri yaz**

`tests/test_scheduler.py` içinde `test_kota_durumlari_turleri`'ndeki beklenen kümeyi güncelle:

```python
    assert kotalar == {sch.RESPOND, sch.OPENER, sch.DIRECT_DM, sch.DISCOVER}
```

`TestSonrakiGorev` sınıfına:

```python
    def test_hikaye_dm_den_once(self):
        izinli = [sch.OPENER, sch.DIRECT_DM, sch.DISCOVER]
        assert sch.sonraki_gorev(izinli, False, acilis_var=True, dm_var=True) == sch.OPENER

    def test_hikaye_soğumadaysa_dm(self):
        izinli = [sch.OPENER, sch.DIRECT_DM, sch.DISCOVER]
        assert sch.sonraki_gorev(izinli, False, acilis_var=False, dm_var=True) == sch.DIRECT_DM

    def test_dm_kesiften_once(self):
        assert sch.sonraki_gorev([sch.DIRECT_DM, sch.DISCOVER], False, False, True) == sch.DIRECT_DM
```

Dosya sonuna:

```python
# --------------------------------------------------------------------------- #
# direkt_dm_turu_yap (takip listesinden DM açılışı)
# --------------------------------------------------------------------------- #
from ig_agent.platformlar import GonderimSonucu, Hedef  # noqa: E402


class SahteDMIstemci:
    """Hedef listesini gezer; sonuçlar handle bazında ayarlanabilir."""

    platform = "instagram"

    def __init__(self, handles, sonuclar=None, engel_sonra=None):
        self.hedefler = [Hedef(handle=h, kaynak="takip_listesi") for h in handles]
        self.sonuclar = sonuclar or {}
        self.engel_sonra = engel_sonra
        self.engel_algilandi = False
        self.gonderilen = []

    def acilis_turu(self, karar_fn, sonuc_fn, yazmadan_once):
        for hedef in self.hedefler:
            metin = karar_fn(hedef)
            if metin == TURU_BITIR:
                break
            if not metin:
                continue
            if not yazmadan_once():
                break
            sonuc = self.sonuclar.get(hedef.handle, GonderimSonucu.GONDERILDI)
            if sonuc == GonderimSonucu.GONDERILDI:
                self.gonderilen.append(hedef.handle)
            sonuc_fn(hedef, metin, sonuc)
            if self.engel_sonra is not None and len(self.gonderilen) >= self.engel_sonra:
                self.engel_algilandi = True
                break


def _dm_turu(conn, ayarlar, istemci, **kw):
    kw.setdefault("uyku_fn", lambda sn: True)
    kw.setdefault("simdi_fn", OGLEN)
    return sch.direkt_dm_turu_yap(conn, ayarlar, istemci, object(), **kw)


def test_dm_turu_yeni_hedeflere_yazar(ortam):
    conn, ayarlar, lead = ortam
    hik = repo.ig_lead_upsert(conn, ig_handle="hikayeli", business_name="H")
    repo.mesaj_ekle(conn, hik, "story_reply", "önceki")
    repo.dnc_ekle(conn, "dncli", "x")

    ist = SahteDMIstemci(["yeni1", "hikayeli", "dncli", "@yeni2 "])
    assert _dm_turu(conn, ayarlar, ist) == 2
    for h in ("yeni1", "yeni2"):
        l = repo.lead_getir_platform(conn, "instagram", h)
        assert l["discovery_source"] == "takip_listesi" and l["stage"] == "ilk_temas"
        msjlar = repo.thread_mesajlari(conn, int(l["id"]))
        assert [m["direction"] for m in msjlar] == ["dm_opener"]
    assert repo.durum_getir(conn, "son_dm_turu")  # soğuma başladı


def test_dm_kapali_dnc_ye_eklenir_ve_tekrar_denenmez(ortam):
    conn, ayarlar, lead = ortam
    ist = SahteDMIstemci(["kapali"], sonuclar={"kapali": GonderimSonucu.DM_KAPALI})
    assert _dm_turu(conn, ayarlar, ist) == 0
    assert repo.dnc_mi(conn, "kapali")
    assert repo.dnc_listesi(conn)[0]["reason"] == "dm_kapali"
    assert repo.lead_getir_platform(conn, "instagram", "kapali") is None

    secilen = []
    ist2 = SahteDMIstemci(["kapali"])
    ist2.acilis_turu = lambda k, s, y: secilen.append(k(ist2.hedefler[0]))
    _dm_turu(conn, ayarlar, ist2)
    assert secilen == [None]


def test_dm_basarisiz_kayit_birakmaz_sonra_tekrar_denenir(ortam):
    conn, ayarlar, lead = ortam
    ist = SahteDMIstemci(["gecici"], sonuclar={"gecici": GonderimSonucu.BASARISIZ})
    assert _dm_turu(conn, ayarlar, ist) == 0
    assert not repo.dnc_mi(conn, "gecici")
    assert repo.lead_getir_platform(conn, "instagram", "gecici") is None
    assert _dm_turu(conn, ayarlar, SahteDMIstemci(["gecici"])) == 1


def test_dm_turu_saatlik_tavanda_durur_ve_kaldigi_yerden_devam(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.pacing.dm_acilis_saatlik = 2
    assert _dm_turu(conn, ayarlar, SahteDMIstemci(["a", "b", "c"])) == 2
    assert sch.dm_acilis_kalan(conn, ayarlar) == 0
    ayarlar.pacing.dm_acilis_saatlik = 10
    ist = SahteDMIstemci(["a", "b", "c"])
    assert _dm_turu(conn, ayarlar, ist) == 1
    assert ist.gonderilen == ["c"]


def test_dm_ve_hikaye_kotalari_bagimsiz(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.pacing.acilis_saatlik = 1
    ayarlar.pacing.dm_acilis_saatlik = 1
    assert _tur(conn, ayarlar, SahteHikayeIG(["h1"])) == 1
    assert sch.acilis_kalan(conn, ayarlar) == 0
    assert _dm_turu(conn, ayarlar, SahteDMIstemci(["d1"])) == 1  # hikaye kotası DM'i durdurmaz
    assert sch.dm_acilis_kalan(conn, ayarlar) == 0
    ayarlar.pacing.acilis_saatlik = 5
    assert _tur(conn, ayarlar, SahteHikayeIG(["h2"])) == 1  # DM kotası hikayeyi durdurmaz


def test_dm_atilan_hesaba_hikaye_yaniti_atilmaz_ve_tersi(ortam):
    conn, ayarlar, lead = ortam
    _dm_turu(conn, ayarlar, SahteDMIstemci(["ortak1"]))
    hik = SahteHikayeIG(["ortak1"])
    assert _tur(conn, ayarlar, hik) == 0
    _tur(conn, ayarlar, SahteHikayeIG(["ortak2"]))
    ist = SahteDMIstemci(["ortak2"])
    assert _dm_turu(conn, ayarlar, ist) == 0 and ist.gonderilen == []


def test_dm_turu_bos_liste_soguma_baslatir(ortam):
    conn, ayarlar, lead = ortam
    assert _dm_turu(conn, ayarlar, SahteDMIstemci([])) == 0
    assert not sch._tur_zamani(conn, "son_dm_turu", 3600)


def test_dm_turu_duraklatilinca_ve_mesai_disinda_biter(ortam):
    conn, ayarlar, lead = ortam
    repo.durum_ayarla(conn, "master_paused", "1")
    assert _dm_turu(conn, ayarlar, SahteDMIstemci(["a1"])) == 0
    repo.durum_ayarla(conn, "master_paused", "0")
    gece = lambda: datetime(2026, 9, 24, 23, 0)  # noqa: E731
    assert _dm_turu(conn, ayarlar, SahteDMIstemci(["a1"]), simdi_fn=gece) == 0


def test_dm_tempo_beklemesi_saatlik_tavana_gore(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.pacing.dm_acilis_saatlik = 10  # ~360 sn ± %30
    beklemeler = []
    _dm_turu(conn, ayarlar, SahteDMIstemci(["a1"]),
             uyku_fn=lambda sn: beklemeler.append(sn) or True)
    assert len(beklemeler) == 1 and 252 <= beklemeler[0] <= 468


def test_dm_kotasi_bayrak_kapaliyken_sifir(ortam):
    conn, ayarlar, lead = ortam
    k = {x.tur: x for x in sch.kota_durumlari(conn, ayarlar)}
    assert k[sch.DIRECT_DM].tavan == 0
    repo.durum_ayarla(conn, "dm_acilis_aktif", "1")
    k = {x.tur: x for x in sch.kota_durumlari(conn, ayarlar)}
    assert k[sch.DIRECT_DM].musait
```

- [ ] **Step 2: Çalıştır**

Run: `.venv/bin/python3.12 -m pytest tests/test_scheduler.py -q`
Expected: yeni testler FAIL (`DIRECT_DM` / `direkt_dm_turu_yap` yok).

- [ ] **Step 3: Uygula** — `ig_agent/scheduler.py`

Görev türlerine:

```python
DIRECT_DM = "direct_dm"
```

`sonraki_gorev`:

```python
def sonraki_gorev(
    izinli: list[str], yanit_var: bool, acilis_var: bool, dm_var: bool = False
) -> Optional[str]:
    """Öncelik: yanıt > hikaye açılışı > direkt DM > keşif. Kota + kuyruk birlikte gerekir."""
    if RESPOND in izinli and yanit_var:
        return RESPOND
    if OPENER in izinli and acilis_var:
        return OPENER
    if DIRECT_DM in izinli and dm_var:
        return DIRECT_DM
    if DISCOVER in izinli:
        return DISCOVER
    return None
```

`acilis_araligi_sn`'yi ortak yardımcıya bağla ve DM karşılıklarını ekle:

```python
def _aralik_sn(saatlik: int, rng: random.Random) -> float:
    """Saatlik tavanı saate yayan hedef aralık (±%30); tavan 0 ise kısa rastgele."""
    if saatlik <= 0:
        return rng.uniform(8.0, 20.0)
    return (3600.0 / saatlik) * rng.uniform(0.7, 1.3)


def acilis_araligi_sn(ayarlar: Ayarlar, rng: random.Random) -> float:
    """İki hikaye-yanıtı arası hedef süre."""
    return _aralik_sn(ayarlar.pacing.acilis_saatlik, rng)


def dm_acilis_kalan(conn: sqlite3.Connection, ayarlar: Ayarlar) -> int:
    """Şu an gönderilebilecek direkt DM açılışı (saatlik ve günlük tavanın küçüğü)."""
    p = ayarlar.pacing
    kalan = SINIRSIZ
    if p.dm_acilis_saatlik > 0:
        kalan = min(kalan, max(0, p.dm_acilis_saatlik - repo.son_saat_dm_acilis_sayisi(conn)))
    if p.dm_acilis_gunluk > 0:
        kalan = min(kalan, max(0, p.dm_acilis_gunluk - repo.bugun_dm_acilis_sayisi(conn)))
    return kalan


def dm_acilis_araligi_sn(ayarlar: Ayarlar, rng: random.Random) -> float:
    """İki direkt DM arası hedef süre."""
    return _aralik_sn(ayarlar.pacing.dm_acilis_saatlik, rng)
```

`kota_durumlari` dönüş listesine, OPENER'dan sonra:

```python
    # Direkt DM varsayılan KAPALI; panelden açılır.
    dm_aktif = repo.bayrak_getir(conn, "dm_acilis_aktif", False)
    son_saat_dm = repo.son_saat_dm_acilis_sayisi(conn)
    dm_tavan = son_saat_dm + dm_acilis_kalan(conn, ayarlar) if dm_aktif else 0
```
ve listeye `pacing.KotaDurumu(DIRECT_DM, son_saat_dm, dm_tavan),` (OPENER ile DISCOVER arasına).

`_hikaye_turu_zamani`'yi genelleştir:

```python
def _tur_zamani(conn: sqlite3.Connection, anahtar: str, cooldown: int) -> bool:
    """`anahtar`daki son tur damgasından bu yana `cooldown` sn geçti mi?"""
    son = repo.durum_getir(conn, anahtar, "")
    if not son:
        return True
    try:
        gecen = (datetime.now() - datetime.fromisoformat(son)).total_seconds()
        return gecen >= cooldown
    except ValueError:
        return True


def _hikaye_turu_zamani(
    conn: sqlite3.Connection, cooldown: int = HIKAYE_TURU_COOLDOWN_SN
) -> bool:
    """Son hikaye turundan bu yana yeterince zaman geçti mi?"""
    return _tur_zamani(conn, "son_hikaye_turu", cooldown)
```

`hikaye_turu_yap`'tan sonra:

```python
def direkt_dm_turu_yap(
    conn,
    ayarlar,
    istemci,
    beyin_istemci,
    rng: Optional[random.Random] = None,
    uyku_fn: Optional[Callable[[float], bool]] = None,
    simdi_fn: Callable[[], datetime] = datetime.now,
) -> int:
    """İstemcinin hedef listesini (IG: takip edilenler) gezip yeni hedeflere DM atar.

    Hikaye turuyla aynı kurallar: daha önce yazışılmış (o platformda, herhangi
    bir yönde) veya do-not-contact hesaplar atlanır; her gönderim anında DB'ye
    yazılır; gönderimler DM saatlik tavanına göre zamana yayılır; duraklatma,
    kota veya çalışma saati turu bitirir. DM kutusu kapalı hesaplar `dnc`'ye
    `dm_kapali` ile eklenir. Gönderilen DM sayısını döner.
    """
    rng = rng or random.Random()
    uyku_fn = uyku_fn or (lambda sn: uyku(conn, sn))
    p = ayarlar.pacing
    platform = getattr(istemci, "platform", "instagram")

    if dm_acilis_kalan(conn, ayarlar) <= 0:
        repo.durum_ayarla(conn, "son_dm_turu", datetime.now().isoformat())
        print("[dm] direkt DM kotası dolu — tur atlandı")
        return 0

    gun = getattr(ayarlar, "yeniden_iletisim_gun", 0)
    ist = {"gorulen": 0, "secildi": 0, "gonderildi": 0, "kapali": 0,
           "basarisiz": 0, "atlandi_yakin": 0, "atlandi_dnc": 0}

    def karar_fn(hedef: Hedef):
        ist["gorulen"] += 1
        repo.nabiz_at(conn, f"DM turu · @{hedef.handle} · gönderilen {ist['gonderildi']}")
        if repo.bayrak_getir(conn, "master_paused", False):
            return TURU_BITIR
        if not pacing.calisma_saatinde_mi(simdi_fn(), p.calisma_baslangic_saat, p.calisma_bitis_saat):
            return TURU_BITIR
        if dm_acilis_kalan(conn, ayarlar) <= 0:
            return TURU_BITIR
        h = (hedef.handle or "").strip().lstrip("@")
        if not h:
            return None
        if repo.dnc_mi(conn, h, platform):
            ist["atlandi_dnc"] += 1
            return None
        if repo.yakin_zamanda_iletisim(conn, h, gun, platform=platform):
            ist["atlandi_yakin"] += 1
            return None
        lead = repo.lead_getir_platform(conn, platform, h)
        ist["secildi"] += 1
        return _acilis_metni(beyin_istemci, ayarlar, lead, rng, baglam="dm")

    def yazmadan_once() -> bool:
        """Bir önceki DM'den bu yana hedef aralık dolmadıysa bekle."""
        bekle = dm_acilis_araligi_sn(ayarlar, rng)
        son = repo.son_dm_acilis_zamani(conn, platform)
        if son:
            try:
                bekle -= (datetime.now() - datetime.fromisoformat(son)).total_seconds()
            except ValueError:
                pass
        if bekle > 0:
            repo.nabiz_at(conn, f"DM turu · tempo beklemesi {int(bekle)} sn")
        return uyku_fn(max(0.0, bekle))

    def sonuc_fn(hedef: Hedef, metin: str, sonuc: GonderimSonucu) -> None:
        h = (hedef.handle or "").strip().lstrip("@")
        if sonuc == GonderimSonucu.GONDERILDI:
            lead_id = repo.lead_upsert(
                conn, platform=platform, handle=h, business_name=hedef.ad or h,
                profile_url=hedef.profile_url, discovery_source=hedef.kaynak,
            )
            repo.mesaj_ekle(conn, lead_id, "dm_opener", metin, ai_generated=True)
            ist["gonderildi"] += 1
        elif sonuc == GonderimSonucu.DM_KAPALI:
            repo.dnc_ekle(conn, h, "dm_kapali", platform=platform)
            ist["kapali"] += 1
        else:
            ist["basarisiz"] += 1

    istemci.acilis_turu(karar_fn, sonuc_fn, yazmadan_once)

    repo.durum_ayarla(conn, "son_dm_turu", datetime.now().isoformat())
    print(
        f"[dm] direkt DM turu: gezilen={ist['gorulen']} seçildi={ist['secildi']} "
        f"gönderildi={ist['gonderildi']} dm_kapalı={ist['kapali']} "
        f"başarısız={ist['basarisiz']} "
        f"atlandı(önceden yazılmış)={ist['atlandi_yakin']} atlandı(dnc)={ist['atlandi_dnc']} "
        f"son 1 saat={repo.son_saat_dm_acilis_sayisi(conn, platform)}"
    )
    if ist["gorulen"] == 0:
        print("[dm] ⚠️ takip listesi boş geldi — kullanıcı adı ya da liste seçicileri kontrol edilmeli")
    elif ist["gonderildi"] == 0 and (ist["basarisiz"] + ist["kapali"]) >= 3 \
            and not getattr(istemci, "engel_algilandi", False):
        print("[dm] ⚠️ hiç DM gönderilemedi — S.MESAJ_KUTUSU / yeni mesaj seçicileri ayarlanmalı olabilir")
    return ist["gonderildi"]
```

`durum_ozeti` dönüş sözlüğüne:

```python
        "dm_aktif": repo.bayrak_getir(conn, "dm_acilis_aktif", False),
        "dm_son_saat": repo.son_saat_dm_acilis_sayisi(conn),
        "dm_bugun": repo.bugun_dm_acilis_sayisi(conn),
```

`tek_tur` içinde `acilis_var = ...` satırından sonra:

```python
    dm_var = hasattr(ig, "acilis_turu") and _tur_zamani(
        conn, "son_dm_turu", ayarlar.pacing.dm_turu_cooldown_sn
    )
    gorev = sonraki_gorev(izinli, yanit_var, acilis_var, dm_var)
```
(eski `gorev = sonraki_gorev(izinli, yanit_var, acilis_var)` satırını sil) ve `elif gorev == OPENER:` bloğundan sonra:

```python
    elif gorev == DIRECT_DM:
        repo.nabiz_at(conn, "direkt DM turu başlıyor")
        direkt_dm_turu_yap(conn, ayarlar, ig, beyin_istemci, rng)
```

`ig_agent/run.py` — `_bosta_nedeni` son satırı:

```python
    return "bekleyen yanıt yok, hikaye/DM turları soğumada"
```

- [ ] **Step 4: Testleri çalıştır**

Run: `.venv/bin/python3.12 -m pytest tests/ -q`
Expected: hepsi PASS.

- [ ] **Step 5: Commit**

```bash
git add ig_agent/scheduler.py ig_agent/run.py tests/test_scheduler.py
git commit -m "feat(scheduler): takip listesinden direkt DM turu (ayrı kota)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Instagram istemcisi — takip listesi ve DM gönderimi

**Files:**
- Modify: `ig_agent/instagram.py` (`S` sınıfı, `InstagramClient`)
- Create: `tests/test_instagram_acilis.py`

**Interfaces:**
- Consumes: Task 3 `Hedef`, `GonderimSonucu`, `TURU_BITIR`, `Ayarlar.kendi_kullanici_adi`.
- Produces:
  - `InstagramClient.platform = "instagram"`
  - `InstagramClient.kendi_kullanici_adi() -> str`
  - `InstagramClient.takip_listesi_topla(max_hesap: int = 5000) -> list[str]`
  - `InstagramClient._dm_gonder_sonuc(handle: str, metin: str) -> GonderimSonucu`
  - `InstagramClient.acilis_turu(karar_fn, sonuc_fn, yazmadan_once) -> None` (`Hedef.kaynak = "takip_listesi"`)
  - `dm_gonder(handle, metin) -> bool` **değişmez** (RESPOND akışı kullanıyor).

- [ ] **Step 1: Failing testleri yaz** — `tests/test_instagram_acilis.py`:

```python
"""InstagramClient.acilis_turu döngüsü ve DM sonuç sınıflandırması (tarayıcısız)."""

from __future__ import annotations

import pytest

from ig_agent.config import Ayarlar
from ig_agent.instagram import InstagramClient
from ig_agent.platformlar import TURU_BITIR, GonderimSonucu


@pytest.fixture
def ig(monkeypatch):
    istemci = InstagramClient(Ayarlar())  # tarayıcı başlatılmaz
    monkeypatch.setattr(istemci, "checkpoint_var_mi", lambda: False)
    return istemci


def _sonuclari_topla():
    olaylar = []
    return olaylar, lambda hedef, metin, sonuc: olaylar.append((hedef, metin, sonuc))


def test_acilis_turu_karar_ve_gonderim(ig, monkeypatch):
    monkeypatch.setattr(ig, "takip_listesi_topla", lambda: ["a", "b", "c"])
    gonderilen = []
    monkeypatch.setattr(ig, "_dm_gonder_sonuc",
                        lambda h, m: gonderilen.append((h, m)) or GonderimSonucu.GONDERILDI)
    olaylar, sonuc_fn = _sonuclari_topla()

    ig.acilis_turu(lambda h: None if h.handle == "b" else f"selam {h.handle}",
                   sonuc_fn, lambda: True)

    assert gonderilen == [("a", "selam a"), ("c", "selam c")]
    assert [o[0].handle for o in olaylar] == ["a", "c"]
    assert olaylar[0][0].kaynak == "takip_listesi"
    assert olaylar[0][0].profile_url == "https://www.instagram.com/a/"


def test_acilis_turu_turu_bitir_ve_tempo_durdurma(ig, monkeypatch):
    monkeypatch.setattr(ig, "takip_listesi_topla", lambda: ["a", "b"])
    gonderilen = []
    monkeypatch.setattr(ig, "_dm_gonder_sonuc",
                        lambda h, m: gonderilen.append(h) or GonderimSonucu.GONDERILDI)
    olaylar, sonuc_fn = _sonuclari_topla()

    ig.acilis_turu(lambda h: TURU_BITIR, sonuc_fn, lambda: True)
    assert gonderilen == []

    ig.acilis_turu(lambda h: "x", sonuc_fn, lambda: False)  # tempo beklemesi durdurdu
    assert gonderilen == [] and olaylar == []


def test_acilis_turu_engelde_biter(ig, monkeypatch):
    monkeypatch.setattr(ig, "takip_listesi_topla", lambda: ["a", "b"])

    def gonder(h, m):
        ig.engel_algilandi = True
        return GonderimSonucu.BASARISIZ

    monkeypatch.setattr(ig, "_dm_gonder_sonuc", gonder)
    olaylar, sonuc_fn = _sonuclari_topla()
    ig.acilis_turu(lambda h: "x", sonuc_fn, lambda: True)
    assert len(olaylar) == 1


def test_secici_kirilmasi_dm_kapali_sayilmaz(ig, monkeypatch):
    # Profilde düğme yok, yeni-mesaj akışı da açılmadı, sayfada uyarı metni yok
    monkeypatch.setattr(ig, "_profilden_mesaj_ac", lambda h: False)
    monkeypatch.setattr(ig, "_yeni_mesajdan_ac", lambda h: False)
    monkeypatch.setattr(ig, "_dm_kapali_uyarisi", lambda: False)
    assert ig._dm_gonder_sonuc("x", "selam") == GonderimSonucu.BASARISIZ


def test_acik_uyari_varsa_dm_kapali(ig, monkeypatch):
    monkeypatch.setattr(ig, "_profilden_mesaj_ac", lambda h: False)
    monkeypatch.setattr(ig, "_yeni_mesajdan_ac", lambda h: False)
    monkeypatch.setattr(ig, "_dm_kapali_uyarisi", lambda: True)
    assert ig._dm_gonder_sonuc("x", "selam") == GonderimSonucu.DM_KAPALI


def test_kendi_kullanici_adi_ayardan(ig):
    ig._ayarlar.kendi_kullanici_adi = "@temizify.app "
    assert ig.kendi_kullanici_adi() == "temizify.app"
```

- [ ] **Step 2: Çalıştır**

Run: `.venv/bin/python3.12 -m pytest tests/test_instagram_acilis.py -q`
Expected: FAIL (`acilis_turu` / `_dm_gonder_sonuc` yok).

- [ ] **Step 3: Uygula** — `ig_agent/instagram.py`

`S` sınıfında "Keşif" bölümünden önce:

```python
    # Takip listesi (kendi profil → "Takip" penceresi)
    def takip_url(kullanici: str) -> str:  # type: ignore[misc]
        return f"{IG_TABAN}/{kullanici}/following/"

    PROFIL_NAV_LINK = ['a[role="link"]:has-text("Profil")', 'a[role="link"]:has-text("Profile")']

    # Profilde "Mesaj gönder" yoksa: /direct/new/ akışı
    YENI_MESAJ_URL = f"{IG_TABAN}/direct/new/"
    YENI_MESAJ_ARAMA = ('input[name="queryBox"], div[role="dialog"] input[placeholder*="Ara"], '
                        'div[role="dialog"] input[placeholder*="Search"]')
    YENI_MESAJ_SOHBET_METIN = ["Sohbet", "Chat", "İleri", "Next"]
    # Instagram'ın açık "bu hesaba mesaj gönderilemez" metinleri (küçük harfle aranır)
    DM_KAPALI_METIN = ["mesaj gönderemezsin", "mesaj gönderemezsiniz",
                       "can't message", "cannot message", "isn't accepting messages"]
```

`InstagramClient` sınıfının başına (docstring/`__init__`'ten önce):

```python
    platform = "instagram"
```

"DM okuma / gönderme" bölümünden önce yeni bölüm:

```python
    # ------------------------------------------------------------------ #
    # Takip listesi turu (takip ettiklerimize direkt DM)
    # ------------------------------------------------------------------ #
    def kendi_kullanici_adi(self) -> str:
        """Ayarda verilmişse o; yoksa sol menüdeki "Profil" bağlantısından."""
        ayarli = (getattr(self._ayarlar, "kendi_kullanici_adi", "") or "").strip().lstrip("@")
        if ayarli:
            return ayarli
        try:
            self._git(IG_TABAN)
            for secici in S.PROFIL_NAV_LINK:
                el = self._page.query_selector(secici)
                if not el:
                    continue
                eslesme = _PROFIL_YOLU.match(el.get_attribute("href") or "")
                if eslesme and eslesme.group(1).lower() not in _AYRILMIS_YOLLAR:
                    return eslesme.group(1)
        except Exception:
            pass
        return ""

    def takip_listesi_topla(self, max_hesap: int = 5000) -> list[str]:
        """Kendi "Takip" penceremizi sonuna kadar kaydırıp kullanıcı adlarını toplar.

        Profil açılınca pencere kapandığından liste gönderimden ÖNCE tamamen
        toplanır. 4 kaydırmada yeni hesap gelmezse liste bitmiş sayılır.
        """
        kendi = self.kendi_kullanici_adi()
        if not kendi:
            print("[ig] ⚠️ kendi kullanıcı adı bulunamadı — panelden girin")
            return []
        toplanan: list[str] = []
        try:
            self._git(S.takip_url(kendi), bekle=3.0)
            gorulen: set[str] = set()
            bos_kaydirma = 0
            while len(toplanan) < max_hesap and bos_kaydirma < 4:
                dialog = self._page.query_selector(S.DIALOG)
                if dialog is None:
                    break
                yeni = 0
                for a in dialog.query_selector_all('a[href^="/"]'):
                    eslesme = _PROFIL_YOLU.match(a.get_attribute("href") or "")
                    if not eslesme:
                        continue
                    h = eslesme.group(1)
                    if h.lower() in _AYRILMIS_YOLLAR or h == kendi or h in gorulen:
                        continue
                    gorulen.add(h)
                    toplanan.append(h)
                    yeni += 1
                bos_kaydirma = 0 if yeni else bos_kaydirma + 1
                self._diyalogu_kaydir(dialog)
                time.sleep(self._rng.uniform(1.2, 2.5))
        except Exception:
            pass
        finally:
            try:
                self._page.keyboard.press("Escape")
            except Exception:
                pass
        return toplanan[:max_hesap]

    @staticmethod
    def _diyalogu_kaydir(dialog) -> None:
        """Penceredeki kaydırılabilir öğeyi en alta kaydırır (tembel yükleme)."""
        dialog.evaluate(
            """d => {
                const k = [d, ...d.querySelectorAll('*')].find(e =>
                    e.scrollHeight > e.clientHeight + 10 &&
                    getComputedStyle(e).overflowY !== 'visible');
                if (k) k.scrollTop = k.scrollHeight;
            }"""
        )

    def acilis_turu(self, karar_fn, sonuc_fn, yazmadan_once) -> None:
        """Takip listesindeki her hesap için karar → tempo → DM → sonuç bildirimi.

        `karar_fn(Hedef)`: metin → gönder, None → atla, TURU_BITIR → bitir.
        `yazmadan_once()` profil açılmadan önce çağrılır (tempo beklemesi);
        False dönerse tur biter.
        """
        for handle in self.takip_listesi_topla():
            if self.checkpoint_var_mi():
                break
            hedef = Hedef(handle=handle, profile_url=f"{IG_TABAN}/{handle}/",
                          kaynak="takip_listesi")
            metin = karar_fn(hedef)
            if metin == TURU_BITIR:
                break
            if not metin:
                continue
            if not yazmadan_once():
                break
            sonuc_fn(hedef, metin, self._dm_gonder_sonuc(handle, metin))
            if self.engel_algilandi:
                break

    def _dm_gonder_sonuc(self, handle: str, metin: str) -> GonderimSonucu:
        """Profil (yoksa /direct/new/) üzerinden sohbet açıp yazar.

        DM_KAPALI yalnızca sayfada açık bir "mesaj gönderilemez" metni varsa
        döner; seçici bulunamaması BASARISIZ'dır (yanlışlıkla toplu DNC olmasın).
        """
        try:
            if not (self._profilden_mesaj_ac(handle) or self._yeni_mesajdan_ac(handle)):
                return GonderimSonucu.DM_KAPALI if self._dm_kapali_uyarisi() \
                    else GonderimSonucu.BASARISIZ
            kutu = self._page.query_selector(S.MESAJ_KUTUSU)
            if not kutu:
                return GonderimSonucu.BASARISIZ
            kutu.click()
            self._insan_yaz(kutu, metin)
            self._page.keyboard.press("Enter")
            time.sleep(self._rng.uniform(0.8, 1.8))
            if self._engel_kontrol():
                return GonderimSonucu.BASARISIZ
            if self._dm_kapali_uyarisi():
                return GonderimSonucu.DM_KAPALI
            return GonderimSonucu.GONDERILDI
        except Exception:
            return GonderimSonucu.BASARISIZ

    def _yeni_mesajdan_ac(self, handle: str) -> bool:
        """/direct/new/ → kullanıcı adını ara → sonucu seç → "Sohbet"."""
        try:
            self._git(S.YENI_MESAJ_URL, bekle=2.0)
            ara = self._page.query_selector(S.YENI_MESAJ_ARAMA)
            if not ara:
                return False
            ara.click()
            self._insan_yaz(ara, handle)
            time.sleep(self._rng.uniform(2.0, 3.5))
            secim = self._page.query_selector(f'{S.DIALOG} :text-is("{handle}")')
            if not secim:
                return False
            secim.click()
            time.sleep(self._rng.uniform(0.8, 1.5))
            for etiket in S.YENI_MESAJ_SOHBET_METIN:
                btn = self._page.query_selector(f'{S.DIALOG} div[role="button"]:has-text("{etiket}")')
                if btn:
                    btn.click()
                    time.sleep(self._rng.uniform(1.5, 3.0))
                    break
            return self._page.query_selector(S.MESAJ_KUTUSU) is not None
        except Exception:
            return False

    def _dm_kapali_uyarisi(self) -> bool:
        try:
            metin = (self._page.inner_text("body") or "").lower()
            return any(k in metin for k in S.DM_KAPALI_METIN)
        except Exception:
            return False
```

- [ ] **Step 4: Testleri çalıştır**

Run: `.venv/bin/python3.12 -m pytest tests/ -q`
Expected: hepsi PASS.

- [ ] **Step 5: Commit**

```bash
git add ig_agent/instagram.py tests/test_instagram_acilis.py
git commit -m "feat(ig): takip listesi turu ve DM sonuç sınıflandırması

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Kontrol paneli — direkt DM

**Files:**
- Modify: `ig_agent/control_panel.py`
- Create: `tests/test_panel_smoke.py`

**Interfaces:**
- Consumes: `durum_ozeti` `dm_aktif/dm_son_saat/dm_bugun`; `canli_ayarlar` DM alanları; `repo.dnc_ekle`, `repo.dnc_listesi`; `bot_state` `dm_acilis_aktif`, `son_dm_turu`.

- [ ] **Step 1: Failing duman testi** — `tests/test_panel_smoke.py`:

```python
"""Kontrol paneli geçici bir DB ile hatasız çiziliyor mu (Streamlit AppTest)."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

PANEL = str(Path(__file__).resolve().parent.parent / "ig_agent" / "control_panel.py")


def test_panel_cizilir_ve_dm_alanlari_var(tmp_path, monkeypatch):
    monkeypatch.setenv("IG_DB_YOLU", str(tmp_path / "panel.db"))
    at = AppTest.from_file(PANEL, default_timeout=30).run()
    assert not at.exception
    etiketler = [m.label for m in at.metric]
    assert "Direkt DM · son 1 saat" in etiketler
    assert "Direkt DM · bugün" in etiketler
    assert any(t.label.startswith("Takip edilenlere direkt DM") for t in at.toggle)
```

- [ ] **Step 2: Çalıştır**

Run: `.venv/bin/python3.12 -m pytest tests/test_panel_smoke.py -q`
Expected: FAIL (metrik etiketleri yok). Hata "IG_DB_YOLU yok sayıldı" ise `.env`'de `IG_DB_YOLU` tanımlı olabilir — `load_dotenv` mevcut env'i ezmez, bu yüzden beklenmez; olursa dur ve raporla.

- [ ] **Step 3: Uygula** — `ig_agent/control_panel.py`

Geri çağrılara (`_hikaye_turu_simdi`'den sonra):

```python
def _dm_turu_simdi() -> None:
    repo.durum_ayarla(conn, "son_dm_turu", "")
```

`canli_durum` içindeki buton satırına, "Hikaye turu şimdi"den sonra:

```python
                st.button("DM turu şimdi", icon=":material/send:", on_click=_dm_turu_simdi,
                          key="btn_dm_tur", disabled=not ozet["dm_aktif"],
                          help="Direkt DM soğumasını sıfırlar; bot sıradaki adımda takip listesi turuna başlar.")
```

Metrik satırını (`with st.container(horizontal=True):` içindeki dört `st.metric`) şununla değiştir:

```python
    dm_saatlik = p.dm_acilis_saatlik or "∞"
    dm_gunluk = p.dm_acilis_gunluk or "∞"
    with st.container(horizontal=True):
        st.metric("Hikaye yanıtı · son 1 saat", f"{ozet['acilis_son_saat']} / {saatlik}", border=True)
        st.metric("Hikaye yanıtı · bugün", f"{ozet['acilis_bugun']} / {gunluk}", border=True)
        st.metric("Direkt DM · son 1 saat",
                  f"{ozet['dm_son_saat']} / {dm_saatlik}" if ozet["dm_aktif"] else "kapalı", border=True)
        st.metric("Direkt DM · bugün", f"{ozet['dm_bugun']} / {dm_gunluk}", border=True)
        st.metric("DM yanıtı · bugün", f"{k['respond']['yapilan']} / {k['respond']['tavan']}", border=True)
        st.metric("Çalışma saati", f"{p.calisma_baslangic_saat}:00–{p.calisma_bitis_saat}:00", border=True)
```

Konuşmalar döngüsünde `elif yon == "story_reply":` dalından sonra:

```python
                elif yon == "dm_opener":
                    st.markdown(f":material/arrow_forward: *direkt DM:* {m['body']}")
```

Ayarlar formunda, "**Genel**" başlığından önce:

```python
        st.markdown("**Takip edilenlere direkt DM**")
        c1, c2, c3 = st.columns(3)
        dm_saatlik_in = c1.number_input("DM saatlik tavan", min_value=0, max_value=200,
                                        value=int(p.dm_acilis_saatlik),
                                        help="Hikaye yanıtı tavanından ayrıdır. 0 = sınırsız.")
        dm_gunluk_in = c2.number_input("DM günlük tavan", min_value=0, max_value=2000,
                                       value=int(p.dm_acilis_gunluk))
        dm_cooldown_dk = c3.number_input("DM turları arası bekleme (dk)", min_value=1, max_value=720,
                                         value=max(1, int(p.dm_turu_cooldown_sn) // 60))
        kendi_ad = st.text_input("Instagram kullanıcı adımız",
                                 value=a.kendi_kullanici_adi,
                                 placeholder="boş bırakılırsa sayfadan bulunur",
                                 help="Takip listesi /<kullanıcı adı>/following/ sayfasından okunur.")
```

`canli_ayarlar.kaydet(conn, {...})` sözlüğüne:

```python
                    "dm_acilis_saatlik": int(dm_saatlik_in),
                    "dm_acilis_gunluk": int(dm_gunluk_in),
                    "dm_turu_cooldown_sn": int(dm_cooldown_dk) * 60,
                    "kendi_kullanici_adi": kendi_ad.strip().lstrip("@"),
```

Hikaye saatlik uyarısından sonra:

```python
    if int(p.dm_acilis_saatlik) == 0 or int(p.dm_acilis_saatlik) > 20:
        st.warning("DM saatlik tavanı yüksek. Takip etmeyenlere giden DM'ler 'mesaj istekleri'ne düşer ve "
                   "Instagram bunları hikaye yanıtından daha sıkı sınırlar.", icon=":material/warning:")

    st.markdown("**Takip edilenlere direkt DM**")
    dm_aktif = repo.bayrak_getir(conn, "dm_acilis_aktif", False)
    yeni_dm = st.toggle("Takip edilenlere direkt DM'i aç (hikaye turundan sonra çalışır)", value=dm_aktif)
    if yeni_dm != dm_aktif:
        repo.durum_ayarla(conn, "dm_acilis_aktif", "1" if yeni_dm else "0")
        st.rerun()
```

Do-not-contact sekmesindeki ham SQL'leri değiştir:

```python
        if st.form_submit_button("Ekle") and handle.strip():
            repo.dnc_ekle(conn, handle.strip().lstrip("@"), "panelden elle")
            st.success(f"@{handle.strip().lstrip('@')} eklendi.")

    dnc = repo.dnc_listesi(conn)
```

Modül docstring'i ve `st.title` aynı kalır.

- [ ] **Step 4: Testleri çalıştır + paneli gözle kontrol**

Run: `.venv/bin/python3.12 -m pytest tests/ -q` → hepsi PASS.
Sonra `./baslat.sh` ile paneli aç (http://localhost:8501): direkt DM metrikleri, "DM turu şimdi" (toggle kapalıyken pasif), Ayarlar'da DM alanları ve toggle görünür; Kaydet hata vermez. **Botu başlatma.**

- [ ] **Step 5: Commit**

```bash
git add ig_agent/control_panel.py tests/test_panel_smoke.py
git commit -m "feat(panel): direkt DM aç/kapa, kota ayarları ve sayaçlar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: README + canlı doğrulama

**Files:**
- Modify: `ig_agent/README.md`

- [ ] **Step 1: README** — "Hikaye turu nasıl çalışır" bölümünden sonra ekle:

```markdown
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
```

Tablodaki modül listesine: `| \`platformlar.py\` | Platform istemcilerinin ortak tipleri (Hedef, GonderimSonucu) |`.
"Kurulum" bölümünde `python -m venv .venv` satırını `python3.12 -m venv .venv` yap.

- [ ] **Step 2: Commit**

```bash
git add ig_agent/README.md
git commit -m "docs(ig_agent): takip edilenlere direkt DM

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 3: Canlı doğrulama (KULLANICI ONAYIYLA — gerçek mesaj gönderir)**

1. Panel → Ayarlar: DM saatlik **1**, günlük **2**, kullanıcı adını gir, Kaydet; toggle'ı aç.
2. Başlat → "DM turu şimdi". Log sekmesinde `[dm] direkt DM turu: gezilen=… gönderildi=…` satırını bekle.
3. `gezilen=0` ise: `S.PROFIL_NAV_LINK` / takip penceresi seçicilerini tarayıcıda incele, düzelt.
4. Gönderilen hesabı Instagram'da aç, mesajın gittiğini gör. DB kontrolü:

```bash
sqlite3 sales.db "SELECT l.handle, m.sent_at, m.body FROM ig_messages m JOIN leads l ON l.id=m.lead_id WHERE m.direction='dm_opener' ORDER BY m.id DESC LIMIT 5;"
```

5. Sonuç doğruysa kotaları hedef değerlere (15/80) çek; değilse seçicileri düzeltip ayrı commit at.
```
