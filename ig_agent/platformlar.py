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
    # Sohbette zaten yazışma var (elle/telefondan) — soğuk açılış atılmaz
    ONCEKI_SOHBET = "onceki_sohbet"


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
