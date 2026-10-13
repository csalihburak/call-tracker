"""Panelden değiştirilebilen canlı ayarlar.

`.env` başlangıç değerlerini verir; panelden kaydedilen değerler `bot_state`
tablosunda `ayar.<ad>` (Instagram) / `tiktok:ayar.<ad>` anahtarıyla durur ve bot her turda bunları `.env`'in
üstüne bindirir. Böylece ayar değişikliği için botu yeniden başlatmak gerekmez.
"""

from __future__ import annotations

import copy
import sqlite3

from . import repository as repo
from .config import Ayarlar
from .platformlar import anahtar

ONEK = "ayar."

# ad → (hedef nesne, tip). hedef "pacing" ise Ayarlar.pacing, None ise Ayarlar.
ALANLAR: dict[str, tuple[str | None, type]] = {
    "acilis_saatlik": ("pacing", int),
    "acilis_gunluk": ("pacing", int),
    "dm_max_gunluk": ("pacing", int),
    "calisma_baslangic_saat": ("pacing", int),
    "calisma_bitis_saat": ("pacing", int),
    "aksiyon_bekleme_min": ("pacing", float),
    "aksiyon_bekleme_max": ("pacing", float),
    "hikaye_turu_cooldown_sn": ("pacing", int),
    "dm_acilis_saatlik": ("pacing", int),
    "dm_acilis_gunluk": ("pacing", int),
    "dm_turu_cooldown_sn": ("pacing", int),
    "kendi_kullanici_adi": (None, str),
    "yeniden_iletisim_gun": (None, int),
    "acilis_modu": (None, str),
    "acilis_metinleri": (None, str),
}


def oku(conn: sqlite3.Connection, platform: str = "instagram") -> dict[str, str]:
    """Platformun DB'de kayıtlı ham ayar değerleri (yalnız tanınan alanlar)."""
    onek = anahtar(platform, ONEK)
    satirlar = conn.execute(
        "SELECT key, value FROM bot_state WHERE substr(key, 1, ?) = ?", (len(onek), onek)
    ).fetchall()
    sonuc = {}
    for s in satirlar:
        ad = s["key"][len(onek):]
        if ad in ALANLAR:
            sonuc[ad] = s["value"]
    return sonuc


def uygula(conn: sqlite3.Connection, temel: Ayarlar) -> Ayarlar:
    """`temel` ayarların kopyasına DB'deki canlı değerleri bindirir."""
    ayarlar = copy.deepcopy(temel)
    for ad, ham in oku(conn, temel.platform).items():
        hedef, tip = ALANLAR[ad]
        try:
            deger = tip(ham)
        except (TypeError, ValueError):
            continue  # bozuk değer → .env değeri geçerli kalır
        setattr(ayarlar.pacing if hedef == "pacing" else ayarlar, ad, deger)
    return ayarlar


def kaydet(conn: sqlite3.Connection, degerler: dict, platform: str = "instagram") -> None:
    """Panelden gelen değerleri kaydeder. Bilinmeyen alan ValueError fırlatır."""
    for ad in degerler:
        if ad not in ALANLAR:
            raise ValueError(f"bilinmeyen ayar: {ad}")
    for ad, deger in degerler.items():
        repo.durum_ayarla(conn, ONEK + ad, deger, platform=platform)
