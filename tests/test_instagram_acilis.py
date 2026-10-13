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


# --- final inceleme düzeltmeleri: gerçek DOM üzerinde (headless Chromium) --- #
@pytest.fixture(scope="module")
def sayfa():
    pw_api = pytest.importorskip("playwright.sync_api")
    try:
        pw = pw_api.sync_playwright().start()
        tarayici = pw.chromium.launch(headless=True)
    except Exception as hata:  # Chromium kurulu değilse
        pytest.skip(f"chromium yok: {hata}")
    sayfa = tarayici.new_page()
    yield sayfa
    tarayici.close()
    pw.stop()


def test_takip_diyalogu_onerilenlerde_durur(sayfa):
    sayfa.set_content("""
      <div role="dialog">
        <div><a href="/halici1/">halici1</a><button>Takip ediliyor</button></div>
        <div><a href="/explore/">x</a><a href="/halici2/">halici2</a></div>
        <h4><span>Senin İçin Önerilenler</span></h4>
        <div><a href="/yabanci/">yabanci</a><button>Takip et</button></div>
      </div>""")
    dialog = sayfa.query_selector('div[role="dialog"]')
    assert InstagramClient._diyalog_profil_yollari(dialog) == ["/halici1/", "/explore/", "/halici2/"]


def test_takip_diyalogu_baslik_yoksa_hepsi(sayfa):
    sayfa.set_content('<div role="dialog"><a href="/a/">a</a><a href="/b/">b</a></div>')
    dialog = sayfa.query_selector('div[role="dialog"]')
    assert InstagramClient._diyalog_profil_yollari(dialog) == ["/a/", "/b/"]


def test_sohbette_onceki_mesaj_tespiti(ig, sayfa):
    ig._page = sayfa
    sayfa.set_content('<div role="main"><div role="row"><div dir="auto">Merhaba usta</div></div></div>')
    assert ig._sohbette_mesaj_var() is True
    sayfa.set_content('<div role="main"><div role="row"></div><textarea></textarea></div>')
    assert ig._sohbette_mesaj_var() is False


class _SahteKutu:
    def __init__(self):
        self.yazilan = []

    def click(self):
        pass

    def type(self, kar, delay=0):
        self.yazilan.append(kar)


class _SahteSayfa:
    def __init__(self, kutu):
        self.kutu = kutu
        self.keyboard = self

    def query_selector(self, secici):
        return self.kutu

    def press(self, tus):
        pass


def test_onceki_sohbet_varsa_yazmadan_doner(ig, monkeypatch):
    kutu = _SahteKutu()
    ig._page = _SahteSayfa(kutu)
    monkeypatch.setattr(ig, "_profilden_mesaj_ac", lambda h: True)
    monkeypatch.setattr(ig, "_sohbette_mesaj_var", lambda: True)
    assert ig._dm_gonder_sonuc("musteri", "selam") == GonderimSonucu.ONCEKI_SOHBET
    assert kutu.yazilan == []


def test_takip_listesi_onbellekten_gelir(ig, monkeypatch):
    kazima = []
    monkeypatch.setattr(ig, "_takip_listesini_kazi", lambda: kazima.append(1) or ["a", "b"])
    assert ig.takip_listesi_topla() == ["a", "b"]
    assert ig.takip_listesi_topla() == ["a", "b"]
    assert len(kazima) == 1
