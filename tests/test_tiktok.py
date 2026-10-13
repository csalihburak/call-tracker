"""TikTokClient: DOM ayrıştırma (headless Chromium) ve tur/sınıflandırma (tarayıcısız)."""

from __future__ import annotations

import pytest

from ig_agent.config import ayarlari_yukle
from ig_agent.platformlar import GonderimSonucu
from ig_agent.tiktok import TikTokClient


@pytest.fixture
def tt(monkeypatch):
    istemci = TikTokClient(ayarlari_yukle("tiktok"))  # tarayıcı başlatılmaz
    monkeypatch.setattr(istemci, "checkpoint_var_mi", lambda: False)
    return istemci


def test_acilis_turu_hedefleri(tt, monkeypatch):
    monkeypatch.setattr(tt, "_takip_listesini_kazi", lambda: ["a", "b"])
    monkeypatch.setattr(tt, "_dm_gonder_sonuc", lambda h, m: GonderimSonucu.GONDERILDI)
    olaylar = []
    tt.acilis_turu(lambda h: "selam", lambda h, m, s: olaylar.append((h, s)), lambda: True)
    assert [h.handle for h, _ in olaylar] == ["a", "b"]
    assert olaylar[0][0].profile_url == "https://www.tiktok.com/@a"
    assert olaylar[0][0].kaynak == "takip_listesi"


def test_mesaj_dugmesi_yoksa_basarisiz_ve_surec_boyunca_atlanir(tt, monkeypatch):
    monkeypatch.setattr(tt, "_takip_listesini_kazi", lambda: ["dugmesiz", "b"])
    monkeypatch.setattr(tt, "_profilden_mesaj_ac", lambda h: False if h == "dugmesiz" else True)
    monkeypatch.setattr(tt, "_dm_kapali_uyarisi", lambda: False)
    # Düğme yok + açık uyarı yok → BASARISIZ (DNC'ye gitmez), ama bu süreçte
    # tekrar denenip turu aynı hesaplarda kilitlemez
    assert tt._dm_gonder_sonuc("dugmesiz", "x") == GonderimSonucu.BASARISIZ
    assert tt.takip_listesi_topla() == ["b"]


def test_uyari_metni_varsa_dm_kapali(tt, monkeypatch):
    monkeypatch.setattr(tt, "_profilden_mesaj_ac", lambda h: False)
    monkeypatch.setattr(tt, "_dm_kapali_uyarisi", lambda: True)
    assert tt._dm_gonder_sonuc("x", "selam") == GonderimSonucu.DM_KAPALI


def test_kutu_acilmadiysa_basarisiz(tt, monkeypatch):
    monkeypatch.setattr(tt, "_profilden_mesaj_ac", lambda h: None)
    monkeypatch.setattr(tt, "_dm_kapali_uyarisi", lambda: False)
    assert tt._dm_gonder_sonuc("x", "selam") == GonderimSonucu.BASARISIZ
    # düğme vardı (kutu açılmadı): atlananlara eklenmez, sonraki turda denenir
    monkeypatch.setattr(tt, "_takip_listesini_kazi", lambda: ["x"])
    assert tt.takip_listesi_topla() == ["x"]


def test_onceki_sohbet(tt, monkeypatch):
    monkeypatch.setattr(tt, "_profilden_mesaj_ac", lambda h: True)
    monkeypatch.setattr(tt, "_sohbette_mesaj_var", lambda: True)
    monkeypatch.setattr(tt, "_mesaj_yaz", lambda m: pytest.fail("yazılmamalı"))
    assert tt._dm_gonder_sonuc("x", "selam") == GonderimSonucu.ONCEKI_SOHBET


def test_gonderim(tt, monkeypatch):
    monkeypatch.setattr(tt, "_profilden_mesaj_ac", lambda h: True)
    monkeypatch.setattr(tt, "_sohbette_mesaj_var", lambda: False)
    yazilan = []
    monkeypatch.setattr(tt, "_mesaj_yaz", lambda m: yazilan.append(m) or GonderimSonucu.GONDERILDI)
    assert tt._dm_gonder_sonuc("x", "selam") == GonderimSonucu.GONDERILDI
    assert yazilan == ["selam"]


def test_kendi_kullanici_adi_ayardan(tt):
    tt._ayarlar.kendi_kullanici_adi = "@temizify "
    assert tt.kendi_kullanici_adi() == "temizify"


# --- headless DOM (`sayfa` fixture'ı tests/conftest.py'de) --- #
def _tt(sayfa):
    t = TikTokClient(ayarlari_yukle("tiktok"))
    t._page = sayfa
    return t


def test_captcha_algilanir(sayfa):
    t = _tt(sayfa)
    sayfa.set_content('<div id="captcha_container"><div>Doğrula</div></div>')
    assert t.checkpoint_var_mi()
    sayfa.set_content('<div class="x"><span>Bulmacayı tamamlamak için kaydırıcıyı sürükleyin</span></div>')
    assert t.checkpoint_var_mi()
    sayfa.set_content('<h1 data-e2e="user-title">Halıcı</h1><button data-e2e="message-button">Mesaj</button>')
    assert not t.checkpoint_var_mi()


def test_takip_penceresi_kullanicilari(sayfa):
    sayfa.set_content("""<div role="dialog">
        <a href="/@temizify?lang=tr-TR">biz</a>
        <li><a href="/@hali_1">Halı 1</a></li>
        <li><a href="/@hali.2?lang=tr-TR">Halı 2</a></li>
        <a href="/@hali_1">tekrar</a>
        <a href="/music/abc">müzik</a><a href="/@hali_3/video/123">video</a>
      </div>""")
    d = sayfa.query_selector('div[role="dialog"]')
    assert TikTokClient._pencere_kullanicilari(d) == ["temizify", "hali_1", "hali.2", "hali_1"]


def test_sohbet_ve_dm_kapali_metinleri(sayfa):
    t = _tt(sayfa)
    sayfa.set_content('<div contenteditable="true" role="textbox"></div>')
    assert not t._sohbette_mesaj_var() and not t._dm_kapali_uyarisi()
    sayfa.set_content('<div data-e2e="chat-item"><p>Merhaba</p></div>')
    assert t._sohbette_mesaj_var()
    sayfa.set_content('<p>Bu kullanıcıya mesaj gönderemezsiniz</p>')
    assert t._dm_kapali_uyarisi()


def test_giris_dugmesi_varsa_giris_yok(sayfa, monkeypatch):
    t = _tt(sayfa)
    monkeypatch.setattr(t, "_git", lambda url, bekle=2.5: None)
    sayfa.set_content('<button id="header-login-button" data-e2e="top-login-button">Oturum aç</button>')
    assert not t.giris_yapildi_mi()
    sayfa.set_content('<a data-e2e="nav-profile" href="/@temizify">Profil</a>')
    assert t.giris_yapildi_mi()


def test_profil_linkinden_kendi_adimiz(sayfa, monkeypatch):
    t = _tt(sayfa)
    t._ayarlar.kendi_kullanici_adi = ""
    monkeypatch.setattr(t, "_git", lambda url, bekle=2.5: None)
    sayfa.set_content('<a data-e2e="nav-profile" href="/@temizify.app?lang=tr-TR">Profil</a>')
    assert t.kendi_kullanici_adi() == "temizify.app"
    sayfa.set_content('<a data-e2e="nav-profile" href="/@?lang=tr-TR">Profil</a>')  # çıkış yapılmış
    assert t.kendi_kullanici_adi() == ""


def test_profilden_mesaj_ac_dugme_yok_ve_var(sayfa, monkeypatch):
    t = _tt(sayfa)
    monkeypatch.setattr(t, "_git", lambda url, bekle=2.5: None)
    monkeypatch.setattr("ig_agent.tiktok.time.sleep", lambda sn: None)
    sayfa.set_content('<h1 data-e2e="user-title">Halıcı</h1><button data-e2e="follow-button">Takip et</button>')
    assert t._profilden_mesaj_ac("halici") is False
    sayfa.set_content("""<h1 data-e2e="user-title">Halıcı</h1>
        <button data-e2e="message-button"
          onclick="document.body.insertAdjacentHTML('beforeend','<div contenteditable=true role=textbox></div>')">Mesaj</button>""")
    assert t._profilden_mesaj_ac("halici") is True
    t.KUTU_BEKLEME_MS = 300  # testte tam zaman aşımını bekleme
    sayfa.set_content('<h1 data-e2e="user-title">Halıcı</h1><button data-e2e="message-button">Mesaj</button>')
    assert t._profilden_mesaj_ac("halici") is None  # düğme var, kutu açılmadı


# --- final inceleme düzeltmeleri --- #
def test_dugmesiz_hesap_tempo_harcamadan_atlanir(tt, monkeypatch):
    # #1: düğmesiz hesap tempo beklemesi / sonuç / art arda başarısız sayacı harcamaz
    monkeypatch.setattr(tt, "_takip_listesini_kazi", lambda: ["dugmesiz", "b"])
    monkeypatch.setattr(tt, "_mesaj_dugmesi_var_mi", lambda h: h != "dugmesiz")
    monkeypatch.setattr(tt, "_dm_kapali_uyarisi", lambda: False)
    monkeypatch.setattr("ig_agent.tiktok.time.sleep", lambda sn: None)
    monkeypatch.setattr(tt, "_dm_gonder_sonuc", lambda h, m: GonderimSonucu.GONDERILDI)
    tempo, olaylar = [], []
    tt.acilis_turu(lambda h: "selam", lambda h, m, s: olaylar.append(h.handle),
                   lambda: tempo.append(1) or True)
    assert olaylar == ["b"] and len(tempo) == 1
    assert tt.takip_listesi_topla() == ["b"]


def test_dugmesiz_ama_acik_uyari_varsa_gonderim_akisina_girer(tt, monkeypatch):
    # Açık "mesaj gönderemezsiniz" metni varsa atlanmaz → DM_KAPALI ile DNC'ye gider
    monkeypatch.setattr(tt, "_takip_listesini_kazi", lambda: ["kapali"])
    monkeypatch.setattr(tt, "_mesaj_dugmesi_var_mi", lambda h: False)
    monkeypatch.setattr(tt, "_dm_kapali_uyarisi", lambda: True)
    monkeypatch.setattr(tt, "_dm_gonder_sonuc", lambda h, m: GonderimSonucu.DM_KAPALI)
    olaylar = []
    tt.acilis_turu(lambda h: "selam", lambda h, m, s: olaylar.append(s), lambda: True)
    assert olaylar == [GonderimSonucu.DM_KAPALI]


class _SahteSayfa:
    def __init__(self, url):
        self.url = url

    def query_selector(self, secici):
        return None

    def query_selector_all(self, secici):
        return []

    def inner_text(self, secici):
        return ""


def test_giris_beklerken_sayfa_yenilenmez(monkeypatch):
    # #2: giriş beklerken her kontrolde ana sayfaya gidilirse giriş formu/CAPTCHA silinir
    from ig_agent.tiktok import TIKTOK_TABAN

    t = TikTokClient(ayarlari_yukle("tiktok"))
    gidilen = []
    monkeypatch.setattr(t, "_git", lambda url, bekle=2.5: gidilen.append(url))
    t._page = _SahteSayfa("about:blank")
    t.giris_yapildi_mi()
    assert gidilen == [TIKTOK_TABAN]
    t._page = _SahteSayfa("https://www.tiktok.com/login/phone-or-email/email")
    assert not t.giris_yapildi_mi()
    t._page = _SahteSayfa("https://www.tiktok.com/foryou?lang=tr-TR")
    assert t.giris_yapildi_mi()
    assert gidilen == [TIKTOK_TABAN]


def test_gizli_captcha_kapsayicisi_checkpoint_sayilmaz(sayfa):
    # #3: SDK'nın önceden yüklediği gizli kapsayıcı normal sayfada botu duraklatmamalı
    t = _tt(sayfa)
    sayfa.set_content('<div id="captcha_container" style="display:none"></div>'
                      '<h1 data-e2e="user-title">Halıcı</h1>')
    assert not t.checkpoint_var_mi()


def test_sohbet_kutusu_gec_yuklenirse_beklenir(sayfa, monkeypatch):
    # #5: /messages yavaş açılınca kutu birkaç sn sonra gelir — hemen "açılmadı" denmemeli
    t = _tt(sayfa)
    monkeypatch.setattr(t, "_git", lambda url, bekle=2.5: None)
    monkeypatch.setattr("ig_agent.tiktok.time.sleep", lambda sn: None)
    sayfa.set_content("""<h1 data-e2e="user-title">Halıcı</h1>
        <button data-e2e="message-button" onclick="setTimeout(() => document.body.insertAdjacentHTML(
          'beforeend','<div contenteditable=true role=textbox></div>'), 800)">Mesaj</button>""")
    assert t._profilden_mesaj_ac("halici") is True
