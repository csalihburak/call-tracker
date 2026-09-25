"""sales.db bağlantısı ve şema göçü.

Şema tamamen *additive*'dir: mevcut call-tracker `leads`/`calls` tablolarına
dokunmaz, sadece yeni nullable kolonlar ve yeni tablolar ekler. Böylece mevcut
telefon-arama CRM'i olduğu gibi çalışmaya devam eder.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable

from .config import Ayarlar, ayarlari_yukle

# leads tablosuna eklenecek IG kolonları: (kolon_adi, sql_tanimi)
LEADS_EK_KOLONLAR: list[tuple[str, str]] = [
    ("ig_handle", "TEXT"),
    ("ig_user_id", "TEXT"),
    ("ig_profile_url", "TEXT"),
    ("ig_followers", "INTEGER"),
    ("last_story_reply_at", "TEXT"),
    ("last_inbound_at", "TEXT"),
    ("last_outbound_at", "TEXT"),
    ("discovery_hashtag", "TEXT"),
    ("discovery_city", "TEXT"),
    ("ai_enabled", "INTEGER DEFAULT 1"),
    ("do_not_contact", "INTEGER DEFAULT 0"),
    ("outcome", "TEXT"),
    ("sheet_dirty", "INTEGER DEFAULT 1"),
    # AI'nin ele aldığı son gelen mesaj id'si — aynı mesaja tekrar tekrar
    # karar üretilmesini (sonsuz döngüyü) önler
    ("ai_son_islenen_mesaj_id", "INTEGER"),
]


def baglanti_al(
    ayarlar: Ayarlar | None = None, check_same_thread: bool = True
) -> sqlite3.Connection:
    ayarlar = ayarlar or ayarlari_yukle()
    baglanti = sqlite3.connect(
        ayarlar.veritabani_yolu, check_same_thread=check_same_thread
    )
    baglanti.row_factory = sqlite3.Row
    baglanti.execute("PRAGMA foreign_keys = ON")
    baglanti.execute("PRAGMA journal_mode = WAL")
    return baglanti


def _mevcut_kolonlar(baglanti: sqlite3.Connection, tablo: str) -> set[str]:
    imlec = baglanti.execute(f"PRAGMA table_info({tablo})")
    return {satir["name"] for satir in imlec.fetchall()}


def _tablo_var_mi(baglanti: sqlite3.Connection, tablo: str) -> bool:
    satir = baglanti.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone()
    return satir is not None


def _leads_tablosunu_garantile(baglanti: sqlite3.Connection) -> None:
    """call-tracker olmadan (temiz sales.db) da çalışabilmek için leads/calls'ı kurar."""
    baglanti.executescript(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name TEXT NOT NULL,
            contact_name  TEXT,
            phone         TEXT,
            city          TEXT,
            district      TEXT,
            notes         TEXT,
            stage         TEXT DEFAULT 'yeni',
            source        TEXT,
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS calls (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id        INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            call_date      TEXT DEFAULT (datetime('now','localtime')),
            result         TEXT,
            objections     TEXT,
            notes          TEXT,
            audio_path     TEXT,
            follow_up_date TEXT,
            transcript     TEXT
        );
        """
    )


def gocu_uygula(baglanti: sqlite3.Connection) -> None:
    """Şemayı idempotent şekilde günceller. Tekrar çağrılması güvenlidir."""
    with baglanti:
        _leads_tablosunu_garantile(baglanti)

        mevcut = _mevcut_kolonlar(baglanti, "leads")
        for kolon_adi, sql_tanimi in LEADS_EK_KOLONLAR:
            if kolon_adi not in mevcut:
                baglanti.execute(
                    f"ALTER TABLE leads ADD COLUMN {kolon_adi} {sql_tanimi}"
                )

        # IG DM / hikaye-yanıtı transkripti
        baglanti.execute(
            """
            CREATE TABLE IF NOT EXISTS ig_messages (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id        INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                direction      TEXT NOT NULL,     -- inbound | outbound | story_reply
                body           TEXT,
                ai_generated   INTEGER DEFAULT 0,
                sent_at        TEXT DEFAULT (datetime('now','localtime')),
                synced_to_sheet INTEGER DEFAULT 0,
                meta_json      TEXT
            )
            """
        )

        # Satış/devir olayları (sıcak lead, deneme önerildi, dönüştü, kayıp...)
        baglanti.execute(
            """
            CREATE TABLE IF NOT EXISTS sales_events (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id        INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                type           TEXT NOT NULL,     -- trial_proposed | redirected_whatsapp | handoff | converted | lost
                detail         TEXT,
                phone          TEXT,
                created_at     TEXT DEFAULT (datetime('now','localtime')),
                synced_to_sheet INTEGER DEFAULT 0
            )
            """
        )

        # Operatör kontrol bayrakları / warmup durumu (anahtar-değer)
        baglanti.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_state (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )

        # Handle bazlı do-not-contact (henüz lead olmayanlar için de)
        baglanti.execute(
            """
            CREATE TABLE IF NOT EXISTS dnc_handles (
                handle     TEXT PRIMARY KEY,
                reason     TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
            """
        )

        # Keşifte aynı hesabı iki kez lead yapmamak için kısmi tekil indeks
        baglanti.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_ig_handle "
            "ON leads(ig_handle) WHERE ig_handle IS NOT NULL"
        )
        baglanti.execute(
            "CREATE INDEX IF NOT EXISTS idx_ig_messages_lead ON ig_messages(lead_id)"
        )
        baglanti.execute(
            "CREATE INDEX IF NOT EXISTS idx_ig_messages_sync "
            "ON ig_messages(synced_to_sheet)"
        )
        baglanti.execute(
            "CREATE INDEX IF NOT EXISTS idx_sales_events_sync "
            "ON sales_events(synced_to_sheet)"
        )


def hazirla(
    ayarlar: Ayarlar | None = None, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Bağlantı açar ve göçü uygular — uygulama başlangıcı için tek giriş."""
    baglanti = baglanti_al(ayarlar, check_same_thread=check_same_thread)
    gocu_uygula(baglanti)
    return baglanti


def tablo_adlari(baglanti: sqlite3.Connection) -> Iterable[str]:
    imlec = baglanti.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [satir["name"] for satir in imlec.fetchall()]
