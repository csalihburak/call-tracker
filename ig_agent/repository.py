"""Veri erişim katmanı — sales.db üzerinde IG ajanı işlemleri.

Tüm SQL burada toplanır; üst katmanlar (zamanlayıcı, beyin, sheets senkronu)
yalnızca bu fonksiyonları çağırır. Aşama sözlüğü call-tracker ile aynıdır:
yeni → ilk_temas → demo_atildi → deneme → musteri → kayip
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Optional

INSTAGRAM_KAYNAK = "Instagram"
KAPALI_ASAMALAR = ("musteri", "kayip")


# --------------------------------------------------------------------------- #
# Lead işlemleri
# --------------------------------------------------------------------------- #
def ig_lead_upsert(
    baglanti: sqlite3.Connection,
    *,
    ig_handle: str,
    business_name: str,
    ig_profile_url: str = "",
    ig_followers: Optional[int] = None,
    city: str = "",
    discovery_hashtag: str = "",
    discovery_city: str = "",
    notes: str = "",
) -> int:
    """Handle'a göre lead ekler; zaten varsa mevcut id'yi döner (dedupe)."""
    mevcut = baglanti.execute(
        "SELECT id FROM leads WHERE ig_handle = ?", (ig_handle,)
    ).fetchone()
    if mevcut:
        return int(mevcut["id"])

    with baglanti:
        imlec = baglanti.execute(
            """
            INSERT INTO leads
                (business_name, city, notes, stage, source,
                 ig_handle, ig_profile_url, ig_followers,
                 discovery_hashtag, discovery_city, sheet_dirty)
            VALUES (?, ?, ?, 'yeni', ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                business_name or ig_handle,
                city,
                notes,
                INSTAGRAM_KAYNAK,
                ig_handle,
                ig_profile_url,
                ig_followers,
                discovery_hashtag,
                discovery_city,
            ),
        )
    return int(imlec.lastrowid)


def lead_getir(baglanti: sqlite3.Connection, lead_id: int) -> Optional[sqlite3.Row]:
    return baglanti.execute(
        "SELECT * FROM leads WHERE id = ?", (lead_id,)
    ).fetchone()


def lead_getir_handle(
    baglanti: sqlite3.Connection, ig_handle: str
) -> Optional[sqlite3.Row]:
    return baglanti.execute(
        "SELECT * FROM leads WHERE ig_handle = ?", (ig_handle,)
    ).fetchone()


def asama_guncelle(baglanti: sqlite3.Connection, lead_id: int, asama: str) -> None:
    with baglanti:
        baglanti.execute(
            "UPDATE leads SET stage = ?, sheet_dirty = 1 WHERE id = ?",
            (asama, lead_id),
        )


def sonuc_guncelle(
    baglanti: sqlite3.Connection, lead_id: int, outcome: str
) -> None:
    with baglanti:
        baglanti.execute(
            "UPDATE leads SET outcome = ?, sheet_dirty = 1 WHERE id = ?",
            (outcome, lead_id),
        )


def ai_durumu_ayarla(
    baglanti: sqlite3.Connection, lead_id: int, etkin: bool
) -> None:
    with baglanti:
        baglanti.execute(
            "UPDATE leads SET ai_enabled = ?, sheet_dirty = 1 WHERE id = ?",
            (1 if etkin else 0, lead_id),
        )


def do_not_contact_isaretle(
    baglanti: sqlite3.Connection, lead_id: int, reason: str = ""
) -> None:
    with baglanti:
        baglanti.execute(
            "UPDATE leads SET do_not_contact = 1, ai_enabled = 0, sheet_dirty = 1 "
            "WHERE id = ?",
            (lead_id,),
        )
        satir = baglanti.execute(
            "SELECT ig_handle FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()
        if satir and satir["ig_handle"]:
            baglanti.execute(
                "INSERT OR IGNORE INTO dnc_handles (handle, reason) VALUES (?, ?)",
                (satir["ig_handle"], reason),
            )


def dnc_handle_mi(baglanti: sqlite3.Connection, ig_handle: str) -> bool:
    satir = baglanti.execute(
        "SELECT 1 FROM dnc_handles WHERE handle = ?", (ig_handle,)
    ).fetchone()
    return satir is not None


def yakin_zamanda_iletisim(
    baglanti: sqlite3.Connection, ig_handle: str, gun: int
) -> bool:
    """Son `gun` gün içinde bu hesaba giden (outbound/story_reply) mesaj var mı?

    Manuel değil, botun DB'sindeki geçmişe bakar; açılış tekrarını önlemek için.
    """
    satir = baglanti.execute(
        """
        SELECT 1
        FROM ig_messages m
        JOIN leads l ON l.id = m.lead_id
        WHERE l.ig_handle = ?
          AND m.direction IN ('outbound', 'story_reply')
          AND julianday('now','localtime') - julianday(m.sent_at) < ?
        LIMIT 1
        """,
        (ig_handle, gun),
    ).fetchone()
    return satir is not None


# --------------------------------------------------------------------------- #
# Kuyruklar (zamanlayıcının seçtiği işler)
# --------------------------------------------------------------------------- #
def acilis_bekleyen_leadler(
    baglanti: sqlite3.Connection, limit: int = 25
) -> list[sqlite3.Row]:
    """Hikaye-yanıtı açılışı bekleyen (henüz açılış yapılmamış) leadler."""
    return baglanti.execute(
        """
        SELECT * FROM leads
        WHERE source = ?
          AND ig_handle IS NOT NULL
          AND stage = 'yeni'
          AND last_story_reply_at IS NULL
          AND COALESCE(ai_enabled, 1) = 1
          AND COALESCE(do_not_contact, 0) = 0
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (INSTAGRAM_KAYNAK, limit),
    ).fetchall()


def yanit_bekleyen_threadler(
    baglanti: sqlite3.Connection, limit: int = 25
) -> list[sqlite3.Row]:
    """Son mesajı gelen (inbound) olan, AI açık, kapatılmamış konuşmalar."""
    return baglanti.execute(
        """
        SELECT l.*
        FROM leads l
        JOIN (
            SELECT lead_id, MAX(id) AS max_id
            FROM ig_messages GROUP BY lead_id
        ) son ON son.lead_id = l.id
        JOIN ig_messages m ON m.id = son.max_id
        WHERE m.direction = 'inbound'
          AND COALESCE(l.ai_enabled, 1) = 1
          AND COALESCE(l.do_not_contact, 0) = 0
          AND l.stage NOT IN ('musteri', 'kayip')
          AND COALESCE(l.ai_son_islenen_mesaj_id, 0) < son.max_id
        ORDER BY m.sent_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def islendi_isaretle(baglanti: sqlite3.Connection, lead_id: int) -> None:
    """Lead'in şu anki son mesajını AI tarafından ele alınmış say.

    Karar mesaj göndermese bile (ör. gönderim başarısız, metinsiz takip) aynı
    gelen mesaj bir daha kuyruğa girmez; yeni bir gelen mesaj gelince girer.
    """
    with baglanti:
        baglanti.execute(
            "UPDATE leads SET ai_son_islenen_mesaj_id = "
            "(SELECT MAX(id) FROM ig_messages WHERE lead_id = ?) WHERE id = ?",
            (lead_id, lead_id),
        )


# --------------------------------------------------------------------------- #
# Mesajlar
# --------------------------------------------------------------------------- #
def mesaj_ekle(
    baglanti: sqlite3.Connection,
    lead_id: int,
    direction: str,
    body: str,
    *,
    ai_generated: bool = False,
    meta: Optional[dict] = None,
) -> int:
    """Bir DM/hikaye-yanıtı mesajı kaydeder ve lead zaman damgalarını günceller."""
    meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
    with baglanti:
        imlec = baglanti.execute(
            """
            INSERT INTO ig_messages
                (lead_id, direction, body, ai_generated, meta_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (lead_id, direction, body, 1 if ai_generated else 0, meta_json),
        )
        if direction == "inbound":
            baglanti.execute(
                "UPDATE leads SET last_inbound_at = datetime('now','localtime'), "
                "sheet_dirty = 1 WHERE id = ?",
                (lead_id,),
            )
        elif direction == "story_reply":
            baglanti.execute(
                "UPDATE leads SET last_story_reply_at = datetime('now','localtime'), "
                "last_outbound_at = datetime('now','localtime'), "
                "stage = CASE WHEN stage = 'yeni' THEN 'ilk_temas' ELSE stage END, "
                "sheet_dirty = 1 WHERE id = ?",
                (lead_id,),
            )
        else:  # outbound
            baglanti.execute(
                "UPDATE leads SET last_outbound_at = datetime('now','localtime'), "
                "sheet_dirty = 1 WHERE id = ?",
                (lead_id,),
            )
    return int(imlec.lastrowid)


def thread_mesajlari(
    baglanti: sqlite3.Connection, lead_id: int
) -> list[sqlite3.Row]:
    return baglanti.execute(
        "SELECT * FROM ig_messages WHERE lead_id = ? ORDER BY id ASC",
        (lead_id,),
    ).fetchall()


# --------------------------------------------------------------------------- #
# Satış olayları
# --------------------------------------------------------------------------- #
def olay_ekle(
    baglanti: sqlite3.Connection,
    lead_id: int,
    tip: str,
    *,
    detail: str = "",
    phone: str = "",
) -> int:
    with baglanti:
        imlec = baglanti.execute(
            "INSERT INTO sales_events (lead_id, type, detail, phone) "
            "VALUES (?, ?, ?, ?)",
            (lead_id, tip, detail, phone),
        )
    return int(imlec.lastrowid)


# --------------------------------------------------------------------------- #
# Günlük sayaçlar (kota için)
# --------------------------------------------------------------------------- #
def bugun_acilis_sayisi(baglanti: sqlite3.Connection) -> int:
    satir = baglanti.execute(
        "SELECT COUNT(*) AS n FROM ig_messages "
        "WHERE direction = 'story_reply' "
        "AND date(sent_at) = date('now','localtime')"
    ).fetchone()
    return int(satir["n"]) if satir else 0


def son_saat_acilis_sayisi(baglanti: sqlite3.Connection) -> int:
    """Son 60 dakikada gönderilen hikaye-yanıtı sayısı (saatlik tavan için)."""
    satir = baglanti.execute(
        "SELECT COUNT(*) AS n FROM ig_messages "
        "WHERE direction = 'story_reply' "
        "AND sent_at >= datetime('now','localtime','-1 hour')"
    ).fetchone()
    return int(satir["n"]) if satir else 0


def son_acilis_zamani(baglanti: sqlite3.Connection) -> Optional[str]:
    """En son hikaye-yanıtının zamanı ('YYYY-MM-DD HH:MM:SS', yerel) ya da None."""
    satir = baglanti.execute(
        "SELECT MAX(sent_at) AS t FROM ig_messages WHERE direction = 'story_reply'"
    ).fetchone()
    return satir["t"] if satir else None


def bugun_yanit_sayisi(baglanti: sqlite3.Connection) -> int:
    satir = baglanti.execute(
        "SELECT COUNT(*) AS n FROM ig_messages "
        "WHERE direction = 'outbound' "
        "AND date(sent_at) = date('now','localtime')"
    ).fetchone()
    return int(satir["n"]) if satir else 0


def bugun_kesif_sayisi(baglanti: sqlite3.Connection) -> int:
    satir = baglanti.execute(
        "SELECT COUNT(*) AS n FROM leads "
        "WHERE source = ? AND date(created_at) = date('now','localtime')",
        (INSTAGRAM_KAYNAK,),
    ).fetchone()
    return int(satir["n"]) if satir else 0


# --------------------------------------------------------------------------- #
# Bot durumu (anahtar-değer) — operatör kontrolü + warmup
# --------------------------------------------------------------------------- #
def durum_getir(
    baglanti: sqlite3.Connection, anahtar: str, varsayilan: str = ""
) -> str:
    satir = baglanti.execute(
        "SELECT value FROM bot_state WHERE key = ?", (anahtar,)
    ).fetchone()
    return satir["value"] if satir else varsayilan


def durum_ayarla(baglanti: sqlite3.Connection, anahtar: str, deger: Any) -> None:
    with baglanti:
        baglanti.execute(
            "INSERT INTO bot_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (anahtar, str(deger)),
        )


def bayrak_getir(
    baglanti: sqlite3.Connection, anahtar: str, varsayilan: bool = False
) -> bool:
    return durum_getir(baglanti, anahtar, "1" if varsayilan else "0") in (
        "1",
        "true",
        "True",
    )


def nabiz_at(baglanti: sqlite3.Connection, durum: Optional[str] = None) -> None:
    """Botun ayakta olduğunu (ve istenirse o an ne yaptığını) panele bildirir."""
    with baglanti:
        baglanti.execute(
            "INSERT INTO bot_state (key, value) VALUES ('bot_nabiz', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        if durum is not None:
            baglanti.execute(
                "INSERT INTO bot_state (key, value) VALUES ('bot_durum', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (durum,),
            )


def hata_kaydet(baglanti: sqlite3.Connection, hata: Any) -> None:
    durum_ayarla(baglanti, "son_hata", f"{datetime.now():%Y-%m-%d %H:%M:%S} · {hata}")
