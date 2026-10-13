"""Kontrol paneli geçici bir DB ile hatasız çiziliyor mu (Streamlit AppTest)."""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

PANEL = str(Path(__file__).resolve().parent.parent / "ig_agent" / "control_panel.py")


@pytest.fixture(autouse=True)
def _onbellegi_temizle():
    # cache_resource aynı süreçteki AppTest'ler arasında kalır (DB bağlantısı);
    # her test kendi geçici DB'sini görsün
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def test_panel_cizilir_ve_dm_alanlari_var(tmp_path, monkeypatch):
    monkeypatch.setenv("IG_DB_YOLU", str(tmp_path / "panel.db"))
    at = AppTest.from_file(PANEL, default_timeout=30).run()
    assert not at.exception
    etiketler = [m.label for m in at.metric]
    assert "Direkt DM · son 1 saat" in etiketler
    assert "Direkt DM · bugün" in etiketler
    assert any(t.label.startswith("Takip edilenlere direkt DM") for t in at.toggle)


def test_panel_tiktok_secilince(tmp_path, monkeypatch):
    from ig_agent import db, repository as repo
    from ig_agent.config import Ayarlar

    db_yolu = tmp_path / "panel.db"
    monkeypatch.setenv("IG_DB_YOLU", str(db_yolu))
    at = AppTest.from_file(PANEL, default_timeout=30).run()
    assert at.segmented_control(key="platform").value == "instagram"
    at.segmented_control(key="platform").set_value("tiktok").run()
    assert not at.exception

    etiketler = [m.label for m in at.metric]
    assert "Direkt DM · bugün" in etiketler
    assert not any(e.startswith("Hikaye") for e in etiketler)
    assert not any(b.label.startswith("Hikaye turu") for b in at.button)
    durum = " ".join(c.value for c in at.caption)
    assert "Instagram" in durum and "TikTok" in durum

    # TikTok DM aç/kapa yalnız tiktok: anahtarına yazar; IG değerleri değişmez
    dm = next(t for t in at.toggle if t.label.startswith("TikTok'ta takip edilenlere direkt DM"))
    dm.set_value(True).run()
    assert not at.exception
    c = db.hazirla(Ayarlar(veritabani_yolu=str(db_yolu)))
    try:
        assert repo.bayrak_getir(c, "dm_acilis_aktif", platform="tiktok")
        assert not repo.bayrak_getir(c, "dm_acilis_aktif")
    finally:
        c.close()
