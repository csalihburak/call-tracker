"""Platform istemcilerinin (Instagram, TikTok, ileride Facebook) ortak tipleri.

Zamanlayıcı yalnızca bu arayüzü görür: istemci hedefleri gezer, her hedef için
`karar_fn` ile ne yazılacağını sorar, gönderir ve sonucu `sonuc_fn` ile bildirir.
İstemci DB'ye dokunmaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Protocol

PLATFORMLAR = ("instagram", "tiktok", "facebook")
# Bot süreci çalıştırılabilen (istemcisi yazılmış) platformlar
DESTEKLENEN_PLATFORMLAR = ("instagram", "tiktok")
PLATFORM_ADI = {"instagram": "Instagram", "tiktok": "TikTok", "facebook": "Facebook"}


def anahtar(platform: str, ad: str) -> str:
    """`bot_state` anahtarı. Instagram öneksizdir (canlı DB'deki `master_paused`,
    `ayar.*` vb. olduğu gibi geçerli kalsın); diğerleri `platform:ad`."""
    return ad if platform == "instagram" else f"{platform}:{ad}"


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


def istemci_olustur(platform: str, ayarlar) -> PlatformIstemci:
    """Platformun tarayıcı istemcisini üretir (tarayıcı henüz açılmaz).

    İçe aktarmalar gecikmelidir: istemci modülleri bu modülü içe aktarır.
    """
    if platform == "instagram":
        from .instagram import InstagramClient

        return InstagramClient(ayarlar)
    if platform == "tiktok":
        from .tiktok import TikTokClient

        return TikTokClient(ayarlar)
    if platform == "facebook":
        raise ValueError("Facebook istemcisi henüz yok (parça C)")
    raise ValueError(f"bilinmeyen platform: {platform}")
