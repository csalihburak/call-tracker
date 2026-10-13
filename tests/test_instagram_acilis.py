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
