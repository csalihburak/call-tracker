"""Kontrol paneli geçici bir DB ile hatasız çiziliyor mu (Streamlit AppTest)."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

PANEL = str(Path(__file__).resolve().parent.parent / "ig_agent" / "control_panel.py")


def test_panel_cizilir_ve_dm_alanlari_var(tmp_path, monkeypatch):
    monkeypatch.setenv("IG_DB_YOLU", str(tmp_path / "panel.db"))
    at = AppTest.from_file(PANEL, default_timeout=30).run()
    assert not at.exception
    etiketler = [m.label for m in at.metric]
    assert "Direkt DM · son 1 saat" in etiketler
    assert "Direkt DM · bugün" in etiketler
    assert any(t.label.startswith("Takip edilenlere direkt DM") for t in at.toggle)
