"""IG inbox'tan gelen mesajları DB'ye alma (dedupe'li).

Instagram web'de mesaj kimliği güvenilir çekilemediği için tekilleştirme
sezgiseldir: bir thread'in son mesajı zaten aynı gövdeli bir inbound ise tekrar
yazılmaz. Bu, aynı okunmamış thread'in art arda taranmasında çift kaydı önler.
Ayrıca bizim son gönderdiğimiz mesajlardan biriyle aynı metin gelen sayılmaz.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from . import repository as repo

# Gelen metin, bizim son bu kadar mesajımızdan biriyle aynıysa yok sayılır
KENDI_MESAJ_PENCERESI = 5


def gelen_kaydet(
    conn: sqlite3.Connection,
    handle: str,
    text: str,
    business_name: str = "",
) -> Optional[int]:
    """Gelen bir DM'i uygun lead altına yazar. Yeni satır yazıldıysa lead_id döner."""
    handle = (handle or "").strip().lstrip("@")
    text = (text or "").strip()
    if not handle or not text:
        return None
    if repo.dnc_handle_mi(conn, handle):
        return None

    lead = repo.lead_getir_handle(conn, handle)
    if lead is None:
        lead_id = repo.ig_lead_upsert(
            conn, ig_handle=handle, business_name=business_name or handle
        )
    else:
        lead_id = int(lead["id"])

    mesajlar = repo.thread_mesajlari(conn, lead_id)
    if mesajlar:
        son = mesajlar[-1]
        if son["direction"] == "inbound" and (son["body"] or "").strip() == text:
            return None  # aynı gelen tekrar → atla
    # Güvenlik ağı: DOM'dan yanlışlıkla KENDİ mesajımız okunduysa gelen sayma.
    # Aksi halde bot kendi mesajına cevap verip kendi kendine yazışır.
    bizimkiler = [m for m in mesajlar if m["direction"] != "inbound"][-KENDI_MESAJ_PENCERESI:]
    if any((m["body"] or "").strip() == text for m in bizimkiler):
        return None

    repo.mesaj_ekle(conn, lead_id, "inbound", text)
    return lead_id


def toplu_al(conn: sqlite3.Connection, gelenler: list[dict]) -> int:
    """[{'handle','text'}] listesini işler, yeni kaydedilen mesaj sayısını döner."""
    n = 0
    for g in gelenler:
        if gelen_kaydet(conn, g.get("handle", ""), g.get("text", "")) is not None:
            n += 1
    return n
