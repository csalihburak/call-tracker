"""Ortak test fixture'ları."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def sayfa():
    """Gerçek DOM testleri için headless Chromium sayfası (Chromium yoksa atlanır)."""
    pw_api = pytest.importorskip("playwright.sync_api")
    try:
        pw = pw_api.sync_playwright().start()
        tarayici = pw.chromium.launch(headless=True)
    except Exception as hata:
        pytest.skip(f"chromium yok: {hata}")
    s = tarayici.new_page()
    yield s
    tarayici.close()
    pw.stop()
