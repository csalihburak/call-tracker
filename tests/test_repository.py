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


def test_goc_platform_kolonlari_ve_dnc_tablosu(baglanti):
    kolonlar = {s["name"] for s in baglanti.execute("PRAGMA table_info(leads)")}
    assert {"platform", "handle", "profile_url", "discovery_source"} <= kolonlar
    assert "dnc" in set(db.tablo_adlari(baglanti))


def test_goc_mevcut_ig_leadlerini_ve_dnc_yi_doldurur(baglanti):
    # Eski kod gibi: yalnız ig_handle'lı lead + dnc_handles satırı
    baglanti.execute(
        "INSERT INTO leads (business_name, source, ig_handle, ig_profile_url) "
        "VALUES ('Eski', 'Instagram', 'eski_hesap', 'https://www.instagram.com/eski_hesap/')"
    )
    baglanti.execute(
        "INSERT INTO dnc_handles (handle, reason) VALUES ('kotu_hesap', 'rahatsız etmeyin')"
    )
    baglanti.commit()

    db.gocu_uygula(baglanti)
    db.gocu_uygula(baglanti)  # idempotent

    l = baglanti.execute("SELECT * FROM leads WHERE ig_handle='eski_hesap'").fetchone()
    assert l["platform"] == "instagram" and l["handle"] == "eski_hesap"
    assert l["profile_url"] == "https://www.instagram.com/eski_hesap/"
    d = baglanti.execute("SELECT * FROM dnc WHERE handle='kotu_hesap'").fetchall()
    assert len(d) == 1 and d[0]["platform"] == "instagram" and d[0]["reason"] == "rahatsız etmeyin"


def test_platform_handle_tekil(baglanti):
    baglanti.execute("INSERT INTO leads (business_name, platform, handle) VALUES ('a','tiktok','x')")
    with pytest.raises(sqlite3.IntegrityError):
        baglanti.execute("INSERT INTO leads (business_name, platform, handle) VALUES ('b','tiktok','x')")
    # Aynı handle başka platformda serbest
    baglanti.execute("INSERT INTO leads (business_name, platform, handle) VALUES ('c','facebook','x')")


def test_lead_upsert_platform_bazinda(baglanti):
    a = repo.lead_upsert(baglanti, platform="tiktok", handle="halici", business_name="Halıcı")
    b = repo.lead_upsert(baglanti, platform="tiktok", handle="halici")
    c = repo.lead_upsert(baglanti, platform="instagram", handle="halici", discovery_source="takip_listesi")
    assert a == b and a != c
    t = repo.lead_getir(baglanti, a)
    assert t["source"] == "TikTok" and t["ig_handle"] is None and t["stage"] == "yeni"
    i = repo.lead_getir(baglanti, c)
    assert i["source"] == "Instagram" and i["ig_handle"] == "halici"
    assert i["discovery_source"] == "takip_listesi"
    assert repo.lead_getir_platform(baglanti, "instagram", "halici")["id"] == c


def test_ig_lead_upsert_platform_alanlarini_doldurur(baglanti):
    lid = repo.ig_lead_upsert(baglanti, ig_handle="yeni_ig", business_name="Y")
    l = repo.lead_getir(baglanti, lid)
    assert l["platform"] == "instagram" and l["handle"] == "yeni_ig"
    # lead_upsert aynı lead'i bulur
    assert repo.lead_upsert(baglanti, platform="instagram", handle="yeni_ig") == lid


def test_yakin_zamanda_iletisim_platform_ayrimi(baglanti):
    lid = repo.lead_upsert(baglanti, platform="instagram", handle="ortak")
    repo.mesaj_ekle(baglanti, lid, "story_reply", "selam")
    assert repo.yakin_zamanda_iletisim(baglanti, "ortak", 0) is True
    assert repo.yakin_zamanda_iletisim(baglanti, "ortak", 0, platform="tiktok") is False


def test_dnc_platform_bazinda(baglanti):
    repo.dnc_ekle(baglanti, "kapali_hesap", "dm_kapali", platform="tiktok")
    repo.dnc_ekle(baglanti, "kapali_hesap", "tekrar", platform="tiktok")  # INSERT OR IGNORE
    assert repo.dnc_mi(baglanti, "kapali_hesap", platform="tiktok")
    assert not repo.dnc_mi(baglanti, "kapali_hesap")  # instagram'da değil
    satirlar = repo.dnc_listesi(baglanti, platform="tiktok")
    assert len(satirlar) == 1 and satirlar[0]["reason"] == "dm_kapali"


def test_do_not_contact_isaretle_dnc_tablosuna_yazar(baglanti):
    lid = repo.ig_lead_upsert(baglanti, ig_handle="red_eden", business_name="R")
    repo.do_not_contact_isaretle(baglanti, lid, reason="istemiyor")
    assert repo.dnc_mi(baglanti, "red_eden") and repo.dnc_handle_mi(baglanti, "red_eden")


def test_dm_opener_mesaji_ve_sayaclar(baglanti):
    lid = repo.lead_upsert(baglanti, platform="instagram", handle="dmli")
    hid = repo.lead_upsert(baglanti, platform="instagram", handle="hikayeli")
    repo.mesaj_ekle(baglanti, lid, "dm_opener", "Merhaba")
    repo.mesaj_ekle(baglanti, hid, "story_reply", "Kolay gelsin")
    l = repo.lead_getir(baglanti, lid)
    assert l["stage"] == "ilk_temas" and l["last_outbound_at"] is not None
    assert l["last_story_reply_at"] is None
    assert repo.son_saat_dm_acilis_sayisi(baglanti) == 1
    assert repo.bugun_dm_acilis_sayisi(baglanti) == 1
    assert repo.son_dm_acilis_zamani(baglanti) is not None
    assert repo.son_saat_dm_acilis_sayisi(baglanti, platform="tiktok") == 0
    # hikaye sayaçları DM'i saymaz
    assert repo.son_saat_acilis_sayisi(baglanti) == 1
