"""Backend'e sıcak-lead bildirimi (POST /internal/sales-alerts).

Bot ayrı süreç olduğu için, backend'de mevcut admin-bildirim altyapısını
(AlertDispatchService) tetikleyen ince bir korumalı endpoint'e HTTP ile bağlanır.
`post_fn` enjekte edilebilir (test için).
"""

from __future__ import annotations

from typing import Callable, Optional

from . import brain
from .config import Ayarlar


def _guvenli_str(satir, anahtar: str) -> str:
    try:
        deger = satir[anahtar]
    except (KeyError, IndexError, TypeError):
        return ""
    return "" if deger is None else str(deger)


class AlertClient:
    def __init__(self, ayarlar: Ayarlar, post_fn: Optional[Callable] = None):
        self._ayarlar = ayarlar
        self._post = post_fn

    def _post_fn(self) -> Callable:
        if self._post is not None:
            return self._post
        import requests  # gecikmeli import

        return requests.post

    def sicak_lead_bildir(self, lead, karar: brain.AjanKarari) -> bool:
        b = self._ayarlar.backend
        if not b.etkin:
            return False  # backend yapılandırılmamış → sessiz geç (panelde görünür)

        yuk = {
            "kind": karar.action,  # deneme_oner | insana_devret | ...
            "igHandle": _guvenli_str(lead, "ig_handle"),
            "businessName": _guvenli_str(lead, "business_name"),
            "city": _guvenli_str(lead, "city"),
            "profileUrl": _guvenli_str(lead, "ig_profile_url"),
            "phone": karar.phone or "",
            "stage": karar.stage or _guvenli_str(lead, "stage"),
            "reason": karar.reason or "",
            "messagePreview": (karar.text or "")[:280],
        }
        try:
            yanit = self._post_fn()(
                f"{b.taban_url.rstrip('/')}/internal/sales-alerts",
                json=yuk,
                headers={"x-sales-secret": b.paylasilan_secret},
                timeout=b.zaman_asimi_sn,
            )
            durum = getattr(yanit, "status_code", 0)
            return 200 <= int(durum) < 300
        except Exception:
            return False
