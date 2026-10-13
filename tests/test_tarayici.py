"""TarayiciIstemci ortak davranışı (tarayıcısız + headless DOM)."""

from __future__ import annotations

import pytest

from ig_agent.config import Ayarlar
from ig_agent.instagram import InstagramClient
from ig_agent.tarayici import TarayiciIstemci


class _Sayfa:
    def __init__(self, url):
        self.url = url


def test_instagram_temel_siniftan_turer():
    assert issubclass(InstagramClient, TarayiciIstemci)
    assert InstagramClient.platform == "instagram"


@pytest.mark.parametrize("url,beklenen", [
    ("https://www.instagram.com/challenge/123/", True),
    ("https://www.instagram.com/accounts/suspended/", True),
    ("https://www.instagram.com/halici/", False),
])
def test_ig_checkpoint_urlden(url, beklenen):
    ig = InstagramClient(Ayarlar())
    ig._page = _Sayfa(url)
    assert ig.checkpoint_var_mi() is beklenen


def test_takip_listesi_onbellegi(monkeypatch):
    ig = InstagramClient(Ayarlar())
    cagri = []
    monkeypatch.setattr(ig, "_takip_listesini_kazi", lambda: cagri.append(1) or ["a", "b"])
    assert ig.takip_listesi_topla() == ["a", "b"]
    assert ig.takip_listesi_topla() == ["a", "b"]
    assert len(cagri) == 1


def test_bos_takip_listesi_onbelleklenmez(monkeypatch):
    ig = InstagramClient(Ayarlar())
    cagri = []
    monkeypatch.setattr(ig, "_takip_listesini_kazi", lambda: cagri.append(1) or [])
    ig.takip_listesi_topla()
    ig.takip_listesi_topla()
    assert len(cagri) == 2


def test_engel_kontrol_dialog_metni(sayfa):
    ig = InstagramClient(Ayarlar())
    ig._page = sayfa
    sayfa.set_content('<div role="dialog">Try Again Later — we restrict certain activity</div>')
    assert ig._engel_kontrol() and ig.engel_algilandi
    ig.engel_algilandi = False
    sayfa.set_content('<div role="dialog">Mesaj gönder</div>')
    assert not ig._engel_kontrol() and not ig.engel_algilandi
