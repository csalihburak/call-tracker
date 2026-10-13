"""Google Sheets aynası — SQLite'tan tek yönlü senkron.

SQLite operasyonel kaynaktır; burası yalnızca aşağı akışta rapor üretir. Yazma
işi `SheetYazici` protokolü ardına gizlenir: üretim `GspreadYazici`, testler sahte
yazıcı kullanır. `flush` hangi satırların kirli/senkronsuz olduğunu SQLite'tan
bulur, yazar ve bayrakları temizler — kotaya takılırsa bir sonraki turda kalınan
yerden devam eder.
"""

from __future__ import annotations

import sqlite3
from typing import Protocol

from .config import Ayarlar

PIPELINE_BASLIK = [
    "id", "ig_handle", "business_name", "city", "stage", "outcome",
    "source", "created_at", "last_inbound_at", "last_outbound_at",
]
MESAJ_BASLIK = ["id", "sent_at", "ig_handle", "direction", "ai_generated", "body"]
OLAY_BASLIK = ["id", "created_at", "ig_handle", "type", "phone", "detail"]


class SheetYazici(Protocol):
    def pipeline_upsert(self, satir: dict) -> None: ...
    def mesaj_append(self, satir: dict) -> None: ...
    def olay_append(self, satir: dict) -> None: ...


# Mesaj/olay loglarındaki hesap sütunu: Instagram'da kullanıcı adı (eskisi gibi),
# diğer platformlarda "tiktok:kullanici" (TikTok lead'inde ig_handle boştur)
_HANDLE_SQL = ("CASE WHEN COALESCE(l.platform, 'instagram') = 'instagram' THEN l.ig_handle "
               "ELSE l.platform || ':' || l.handle END")


def flush(conn: sqlite3.Connection, yazici: SheetYazici, limit: int = 200) -> dict:
    """Kirli/senkronsuz satırları Sheets'e yazar, bayrakları temizler.

    Döndürdüğü: {'pipeline': n, 'mesaj': n, 'olay': n} yazılan satır sayıları.
    """
    sayac = {"pipeline": 0, "mesaj": 0, "olay": 0}

    # 1) Pipeline (leads) — upsert
    leadler = conn.execute(
        "SELECT * FROM leads WHERE COALESCE(sheet_dirty,0)=1 "
        "AND source='Instagram' ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    for l in leadler:
        yazici.pipeline_upsert({k: l[k] for k in PIPELINE_BASLIK if _var(l, k)})
        conn.execute("UPDATE leads SET sheet_dirty=0 WHERE id=?", (l["id"],))
        sayac["pipeline"] += 1

    # 2) Mesajlar — append
    mesajlar = conn.execute(
        f"SELECT m.*, {_HANDLE_SQL} AS ig_handle FROM ig_messages m "
        "JOIN leads l ON l.id=m.lead_id "
        "WHERE COALESCE(m.synced_to_sheet,0)=0 ORDER BY m.id LIMIT ?",
        (limit,),
    ).fetchall()
    for m in mesajlar:
        yazici.mesaj_append({
            "id": m["id"], "sent_at": m["sent_at"], "ig_handle": m["ig_handle"],
            "direction": m["direction"], "ai_generated": m["ai_generated"],
            "body": m["body"],
        })
        conn.execute("UPDATE ig_messages SET synced_to_sheet=1 WHERE id=?", (m["id"],))
        sayac["mesaj"] += 1

    # 3) Olaylar — append
    olaylar = conn.execute(
        f"SELECT e.*, {_HANDLE_SQL} AS ig_handle FROM sales_events e "
        "JOIN leads l ON l.id=e.lead_id "
        "WHERE COALESCE(e.synced_to_sheet,0)=0 ORDER BY e.id LIMIT ?",
        (limit,),
    ).fetchall()
    for e in olaylar:
        yazici.olay_append({
            "id": e["id"], "created_at": e["created_at"], "ig_handle": e["ig_handle"],
            "type": e["type"], "phone": e["phone"], "detail": e["detail"],
        })
        conn.execute("UPDATE sales_events SET synced_to_sheet=1 WHERE id=?", (e["id"],))
        sayac["olay"] += 1

    conn.commit()
    return sayac


def _var(satir, anahtar: str) -> bool:
    try:
        satir[anahtar]
        return True
    except (KeyError, IndexError):
        return False


# --------------------------------------------------------------------------- #
# Gerçek gspread yazıcısı
# --------------------------------------------------------------------------- #
class GspreadYazici:
    """gspread + google-auth ile Google Sheet'e yazar. Üç sekmeyi garanti eder."""

    def __init__(self, ayarlar: Ayarlar):
        import gspread  # gecikmeli import

        if not (ayarlar.sheets.credentials_yolu and ayarlar.sheets.sheet_id):
            raise RuntimeError("Sheets credentials/sheet_id eksik.")
        self._gc = gspread.service_account(filename=ayarlar.sheets.credentials_yolu)
        self._ss = self._gc.open_by_key(ayarlar.sheets.sheet_id)
        self._ws_pipeline = self._sekme_garantile("Pipeline", PIPELINE_BASLIK)
        self._ws_mesaj = self._sekme_garantile("Mesaj Logu", MESAJ_BASLIK)
        self._ws_olay = self._sekme_garantile("Satis Devir", OLAY_BASLIK)
        self._pipeline_handle_satiri: dict[str, int] = self._handle_indeksle()

    def _sekme_garantile(self, ad: str, baslik: list[str]):
        try:
            ws = self._ss.worksheet(ad)
        except Exception:
            ws = self._ss.add_worksheet(title=ad, rows=1000, cols=max(10, len(baslik)))
            ws.append_row(baslik)
            return ws
        # Başlık boşsa ekle
        try:
            if not ws.row_values(1):
                ws.append_row(baslik)
        except Exception:
            pass
        return ws

    def _handle_indeksle(self) -> dict[str, int]:
        """ig_handle → satır no (upsert için). Başlık satırı 1'dir."""
        try:
            handleler = self._ws_pipeline.col_values(2)  # ig_handle sütunu
        except Exception:
            return {}
        return {h: i + 1 for i, h in enumerate(handleler) if i > 0 and h}

    def pipeline_upsert(self, satir: dict) -> None:
        deger = [str(satir.get(k, "")) for k in PIPELINE_BASLIK]
        handle = str(satir.get("ig_handle", ""))
        satir_no = self._pipeline_handle_satiri.get(handle)
        if satir_no:
            self._ws_pipeline.update(f"A{satir_no}", [deger])
        else:
            self._ws_pipeline.append_row(deger)
            self._pipeline_handle_satiri[handle] = len(self._pipeline_handle_satiri) + 2

    def mesaj_append(self, satir: dict) -> None:
        self._ws_mesaj.append_row([str(satir.get(k, "")) for k in MESAJ_BASLIK])

    def olay_append(self, satir: dict) -> None:
        self._ws_olay.append_row([str(satir.get(k, "")) for k in OLAY_BASLIK])
