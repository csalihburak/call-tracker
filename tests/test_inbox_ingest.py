"""inbox_ingest.py testleri."""

from __future__ import annotations

import pytest

from ig_agent import db, inbox_ingest, repository as repo
from ig_agent.config import Ayarlar


@pytest.fixture
def conn(tmp_path):
    c = db.hazirla(Ayarlar(veritabani_yolu=str(tmp_path / "i.db")))
    yield c
    c.close()


def test_yeni_lead_ve_mesaj_olusturur(conn):
    lid = inbox_ingest.gelen_kaydet(conn, "yeni_koltuk", "Merhaba fiyat nedir?")
    assert lid is not None
    lead = repo.lead_getir(conn, lid)
    assert lead["ig_handle"] == "yeni_koltuk"
    assert lead["source"] == "Instagram"
    msgs = repo.thread_mesajlari(conn, lid)
    assert msgs[-1]["direction"] == "inbound"


def test_at_isareti_ve_bosluk_temizlenir(conn):
    lid = inbox_ingest.gelen_kaydet(conn, "  @soz  ", "  selam  ")
    assert repo.lead_getir(conn, lid)["ig_handle"] == "soz"
    assert repo.thread_mesajlari(conn, lid)[-1]["body"] == "selam"


def test_ayni_gelen_tekrar_yazilmaz(conn):
    lid1 = inbox_ingest.gelen_kaydet(conn, "a", "aynı mesaj")
    lid2 = inbox_ingest.gelen_kaydet(conn, "a", "aynı mesaj")
    assert lid1 is not None and lid2 is None
    assert len(repo.thread_mesajlari(conn, lid1)) == 1


def test_farkli_gelen_eklenir(conn):
    lid = inbox_ingest.gelen_kaydet(conn, "a", "birinci")
    inbox_ingest.gelen_kaydet(conn, "a", "ikinci")
    assert len(repo.thread_mesajlari(conn, lid)) == 2


def test_dnc_handle_atlanir(conn):
    lid = repo.ig_lead_upsert(conn, ig_handle="kes", business_name="K")
    repo.do_not_contact_isaretle(conn, lid, reason="opt-out")
    assert inbox_ingest.gelen_kaydet(conn, "kes", "tekrar yazdı") is None


def test_bos_girdi_yok_sayilir(conn):
    assert inbox_ingest.gelen_kaydet(conn, "", "x") is None
    assert inbox_ingest.gelen_kaydet(conn, "a", "") is None


def test_toplu_al_sayar(conn):
    gelenler = [
        {"handle": "a", "text": "1"},
        {"handle": "b", "text": "2"},
        {"handle": "a", "text": "1"},  # dup
    ]
    assert inbox_ingest.toplu_al(conn, gelenler) == 2


def test_kendi_mesajimiz_gelen_sayilmaz(conn):
    """DOM yanlışlıkla bizim balonumuzu okursa bot kendine cevap vermemeli."""
    lid = repo.ig_lead_upsert(conn, ig_handle="soz", business_name="S")
    repo.mesaj_ekle(conn, lid, "story_reply", "Kolay gelsin, program kullanıyor musunuz?")
    assert inbox_ingest.gelen_kaydet(conn, "soz", "Kolay gelsin, program kullanıyor musunuz?") is None
    repo.mesaj_ekle(conn, lid, "outbound", "Size kısaca anlatayım")
    assert inbox_ingest.gelen_kaydet(conn, "soz", "Size kısaca anlatayım") is None
    assert inbox_ingest.gelen_kaydet(conn, "soz", "Anlatın bakalım") == lid
