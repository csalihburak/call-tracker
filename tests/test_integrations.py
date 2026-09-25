"""alerts.py ve sheets.flush için enjekte-edilebilir testler."""

from __future__ import annotations

import pytest

from ig_agent import brain, db, repository as repo, sheets
from ig_agent.alerts import AlertClient
from ig_agent.config import Ayarlar, BackendAyarlari


# --------------------------------------------------------------------------- #
# AlertClient
# --------------------------------------------------------------------------- #
class SahteYanit:
    def __init__(self, kod=200):
        self.status_code = kod


def test_alert_backend_kapali_ise_gonderilmez():
    ayarlar = Ayarlar()  # backend boş
    cagrildi = []
    client = AlertClient(ayarlar, post_fn=lambda *a, **k: cagrildi.append(1) or SahteYanit())
    lead = {"ig_handle": "x", "business_name": "X", "city": "", "ig_profile_url": "", "stage": "deneme"}
    karar = brain.AjanKarari(action=brain.DENEME, text="aç", phone="0543")
    assert client.sicak_lead_bildir(lead, karar) is False
    assert cagrildi == []


def test_alert_payload_ve_secret():
    ayarlar = Ayarlar(backend=BackendAyarlari(taban_url="https://api.temizify.com", paylasilan_secret="gizli"))
    yakalanan = {}

    def sahte_post(url, json, headers, timeout):
        yakalanan["url"] = url
        yakalanan["json"] = json
        yakalanan["headers"] = headers
        return SahteYanit(200)

    client = AlertClient(ayarlar, post_fn=sahte_post)
    lead = {"ig_handle": "soz", "business_name": "Sözeri", "city": "Konya", "ig_profile_url": "u", "stage": "ilk_temas"}
    karar = brain.AjanKarari(action=brain.DENEME, text="kaydınızı açalım", phone="0543609")
    assert client.sicak_lead_bildir(lead, karar) is True
    assert yakalanan["url"] == "https://api.temizify.com/internal/sales-alerts"
    assert yakalanan["headers"]["x-sales-secret"] == "gizli"
    assert yakalanan["json"]["igHandle"] == "soz"
    assert yakalanan["json"]["phone"] == "0543609"
    assert yakalanan["json"]["kind"] == brain.DENEME


def test_alert_hata_yutulur():
    ayarlar = Ayarlar(backend=BackendAyarlari(taban_url="https://x", paylasilan_secret="s"))

    def patlayan_post(*a, **k):
        raise RuntimeError("ağ hatası")

    client = AlertClient(ayarlar, post_fn=patlayan_post)
    assert client.sicak_lead_bildir({"ig_handle": "a"}, brain.AjanKarari(action=brain.DEVRET, reason="x")) is False


# --------------------------------------------------------------------------- #
# sheets.flush
# --------------------------------------------------------------------------- #
class SahteYazici:
    def __init__(self):
        self.pipeline = []
        self.mesaj = []
        self.olay = []

    def pipeline_upsert(self, satir):
        self.pipeline.append(satir)

    def mesaj_append(self, satir):
        self.mesaj.append(satir)

    def olay_append(self, satir):
        self.olay.append(satir)


@pytest.fixture
def conn(tmp_path):
    c = db.hazirla(Ayarlar(veritabani_yolu=str(tmp_path / "s.db")))
    yield c
    c.close()


def test_flush_kirli_ve_senkronsuzlari_yazar(conn):
    lid = repo.ig_lead_upsert(conn, ig_handle="soz", business_name="Sözeri", city="Konya")
    repo.mesaj_ekle(conn, lid, "story_reply", "kolay gelsin")
    repo.mesaj_ekle(conn, lid, "inbound", "olur")
    repo.olay_ekle(conn, lid, "trial_proposed", detail="numara verdi", phone="0543")

    yazici = SahteYazici()
    sayac = sheets.flush(conn, yazici)
    assert sayac == {"pipeline": 1, "mesaj": 2, "olay": 1}
    assert yazici.pipeline[0]["ig_handle"] == "soz"
    assert {m["direction"] for m in yazici.mesaj} == {"story_reply", "inbound"}
    assert yazici.olay[0]["type"] == "trial_proposed"


def test_flush_idempotent_ikinci_kez_bos(conn):
    lid = repo.ig_lead_upsert(conn, ig_handle="a", business_name="A")
    repo.mesaj_ekle(conn, lid, "inbound", "x")
    yazici = SahteYazici()
    sheets.flush(conn, yazici)
    # ikinci flush: yeni kirli/senkronsuz yok
    yazici2 = SahteYazici()
    sayac = sheets.flush(conn, yazici2)
    assert sayac == {"pipeline": 0, "mesaj": 0, "olay": 0}


def test_flush_yeni_degisiklik_tekrar_kirletir(conn):
    lid = repo.ig_lead_upsert(conn, ig_handle="a", business_name="A")
    sheets.flush(conn, SahteYazici())
    repo.asama_guncelle(conn, lid, "deneme")  # sheet_dirty=1 yapar
    yazici = SahteYazici()
    sayac = sheets.flush(conn, yazici)
    assert sayac["pipeline"] == 1
    assert yazici.pipeline[0]["stage"] == "deneme"
