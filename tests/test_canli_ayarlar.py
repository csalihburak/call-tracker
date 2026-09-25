"""canli_ayarlar.py ve surec.py (saf kısımlar) testleri."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ig_agent import canli_ayarlar, db, repository as repo, surec
from ig_agent.config import Ayarlar


@pytest.fixture
def ortam(tmp_path):
    temel = Ayarlar(veritabani_yolu=str(tmp_path / "c.db"))
    conn = db.hazirla(temel)
    yield conn, temel
    conn.close()


def test_kayit_yoksa_env_degerleri(ortam):
    conn, temel = ortam
    a = canli_ayarlar.uygula(conn, temel)
    assert a.pacing.acilis_saatlik == temel.pacing.acilis_saatlik
    assert a is not temel


def test_kaydedilen_degerler_bindirilir(ortam):
    conn, temel = ortam
    canli_ayarlar.kaydet(conn, {
        "acilis_saatlik": 25, "aksiyon_bekleme_min": 12.5,
        "acilis_modu": "sabit", "yeniden_iletisim_gun": 7,
    })
    a = canli_ayarlar.uygula(conn, temel)
    assert a.pacing.acilis_saatlik == 25
    assert a.pacing.aksiyon_bekleme_min == 12.5
    assert a.acilis_modu == "sabit" and a.yeniden_iletisim_gun == 7
    assert temel.pacing.acilis_saatlik == 100  # temel değişmedi


def test_bozuk_deger_yok_sayilir(ortam):
    conn, temel = ortam
    repo.durum_ayarla(conn, "ayar.acilis_saatlik", "abc")
    assert canli_ayarlar.uygula(conn, temel).pacing.acilis_saatlik == 100


def test_bilinmeyen_ayar_reddedilir(ortam):
    conn, _ = ortam
    with pytest.raises(ValueError):
        canli_ayarlar.kaydet(conn, {"olmayan": 1})


def test_surec_durumu_nabiz(ortam):
    conn, _ = ortam
    import os

    repo.durum_ayarla(conn, "bot_pid", os.getpid())  # yaşayan bir PID
    repo.nabiz_at(conn, "hikaye turu")
    d = surec.durum(conn)
    assert d["surec_var"] and d["canli"] and d["etkinlik"] == "hikaye turu"
    # nabız eskiyse canlı sayılmaz
    d2 = surec.durum(conn, simdi=datetime.now() + timedelta(seconds=surec.NABIZ_ZAMAN_ASIMI_SN + 5))
    assert d2["surec_var"] and not d2["canli"]


def test_surec_yoksa_kapali(ortam):
    conn, _ = ortam
    assert surec.durum(conn)["surec_var"] is False
    assert surec.durdur(conn) is False
