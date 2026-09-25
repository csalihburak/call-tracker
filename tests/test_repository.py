"""db göçü + repository entegrasyon testleri (geçici DB üzerinde)."""

from __future__ import annotations

import sqlite3

import pytest

from ig_agent import db, repository as repo
from ig_agent.config import Ayarlar


@pytest.fixture
def baglanti(tmp_path):
    ayarlar = Ayarlar(veritabani_yolu=str(tmp_path / "test.db"))
    conn = db.hazirla(ayarlar)
    yield conn
    conn.close()


def test_goc_idempotent(baglanti):
    # İki kez uygulamak hata vermemeli
    db.gocu_uygula(baglanti)
    db.gocu_uygula(baglanti)
    tablolar = set(db.tablo_adlari(baglanti))
    assert {"leads", "calls", "ig_messages", "sales_events", "bot_state",
            "dnc_handles"} <= tablolar


def test_leads_ek_kolonlar_eklendi(baglanti):
    kolonlar = {s["name"] for s in baglanti.execute("PRAGMA table_info(leads)")}
    for ad, _ in db.LEADS_EK_KOLONLAR:
        assert ad in kolonlar


def test_ig_lead_upsert_dedupe(baglanti):
    id1 = repo.ig_lead_upsert(
        baglanti, ig_handle="soz_koltuk", business_name="Sözeri Koltuk"
    )
    id2 = repo.ig_lead_upsert(
        baglanti, ig_handle="soz_koltuk", business_name="Sözeri Koltuk Yıkama"
    )
    assert id1 == id2  # aynı handle → tek lead
    n = baglanti.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
    assert n == 1


def test_acilis_bekleyenler_ve_story_reply_akisi(baglanti):
    lid = repo.ig_lead_upsert(
        baglanti, ig_handle="derin_koltuk", business_name="Derin Koltuk"
    )
    bekleyenler = repo.acilis_bekleyen_leadler(baglanti)
    assert len(bekleyenler) == 1

    # Hikaye-yanıtı gönderilince açılış kuyruğundan çıkmalı, ilk_temas'a geçmeli
    repo.mesaj_ekle(baglanti, lid, "story_reply", "Kolay gelsin, program kullanıyor musunuz?")
    assert repo.acilis_bekleyen_leadler(baglanti) == []
    lead = repo.lead_getir(baglanti, lid)
    assert lead["stage"] == "ilk_temas"
    assert lead["last_story_reply_at"] is not None


def test_yanit_bekleyen_threadler(baglanti):
    lid = repo.ig_lead_upsert(baglanti, ig_handle="a_koltuk", business_name="A")
    repo.mesaj_ekle(baglanti, lid, "story_reply", "Kolay gelsin")
    # Henüz gelen yok → yanıt bekleyen yok
    assert repo.yanit_bekleyen_threadler(baglanti) == []

    repo.mesaj_ekle(baglanti, lid, "inbound", "Hayır kullanmıyoruz")
    bekleyen = repo.yanit_bekleyen_threadler(baglanti)
    assert len(bekleyen) == 1 and bekleyen[0]["id"] == lid

    # Cevap verilince (outbound) tekrar beklemede olmamalı
    repo.mesaj_ekle(baglanti, lid, "outbound", "Anladım, size kısaca anlatayım", ai_generated=True)
    assert repo.yanit_bekleyen_threadler(baglanti) == []


def test_ai_kapaliysa_yanit_beklemez(baglanti):
    lid = repo.ig_lead_upsert(baglanti, ig_handle="b_koltuk", business_name="B")
    repo.mesaj_ekle(baglanti, lid, "inbound", "merhaba")
    repo.ai_durumu_ayarla(baglanti, lid, False)
    assert repo.yanit_bekleyen_threadler(baglanti) == []


def test_do_not_contact(baglanti):
    lid = repo.ig_lead_upsert(baglanti, ig_handle="c_koltuk", business_name="C")
    repo.mesaj_ekle(baglanti, lid, "inbound", "rahatsız etmeyin")
    repo.do_not_contact_isaretle(baglanti, lid, reason="opt-out")
    assert repo.yanit_bekleyen_threadler(baglanti) == []
    assert repo.dnc_handle_mi(baglanti, "c_koltuk")


def test_gunluk_sayaclar(baglanti):
    lid = repo.ig_lead_upsert(baglanti, ig_handle="d_koltuk", business_name="D")
    repo.mesaj_ekle(baglanti, lid, "story_reply", "x")
    repo.mesaj_ekle(baglanti, lid, "inbound", "y")
    repo.mesaj_ekle(baglanti, lid, "outbound", "z", ai_generated=True)
    assert repo.bugun_acilis_sayisi(baglanti) == 1
    assert repo.bugun_yanit_sayisi(baglanti) == 1
    assert repo.bugun_kesif_sayisi(baglanti) == 1


def test_bot_durumu(baglanti):
    assert repo.bayrak_getir(baglanti, "master_paused", True) is True
    repo.durum_ayarla(baglanti, "master_paused", "0")
    assert repo.bayrak_getir(baglanti, "master_paused") is False
    repo.durum_ayarla(baglanti, "warmup_start", "2026-09-15")
    assert repo.durum_getir(baglanti, "warmup_start") == "2026-09-15"


def test_olay_ekle(baglanti):
    lid = repo.ig_lead_upsert(baglanti, ig_handle="e_koltuk", business_name="E")
    eid = repo.olay_ekle(baglanti, lid, "trial_proposed", detail="numara verdi", phone="0543...")
    assert eid > 0
    n = baglanti.execute("SELECT COUNT(*) AS n FROM sales_events").fetchone()["n"]
    assert n == 1
