"""Göçü gerçek sales.db'nin bir kopyası üzerinde dener (varsa)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ig_agent import db

GERCEK = Path(__file__).resolve().parent.parent / "sales.db"


@pytest.mark.skipif(not GERCEK.exists(), reason="sales.db yok")
def test_gercek_db_kopyasinda_goc(tmp_path):
    kopya = tmp_path / "kopya.db"
    kaynak = sqlite3.connect(str(GERCEK))  # yalnız okunur; backup yazmaz
    hedef = sqlite3.connect(kopya)
    kaynak.backup(hedef)  # WAL içeriği dahil tutarlı kopya
    kaynak.close()
    hedef.row_factory = sqlite3.Row

    once_lead = hedef.execute("SELECT COUNT(*) n FROM leads").fetchone()["n"]
    once_ig = hedef.execute("SELECT COUNT(*) n FROM leads WHERE ig_handle IS NOT NULL").fetchone()["n"]
    once_msj = hedef.execute("SELECT COUNT(*) n FROM ig_messages").fetchone()["n"]

    db.gocu_uygula(hedef)

    assert hedef.execute("SELECT COUNT(*) n FROM leads").fetchone()["n"] == once_lead
    assert hedef.execute("SELECT COUNT(*) n FROM ig_messages").fetchone()["n"] == once_msj
    dolu = hedef.execute(
        "SELECT COUNT(*) n FROM leads WHERE platform='instagram' AND handle = ig_handle"
    ).fetchone()["n"]
    assert dolu == once_ig
    hedef.close()
