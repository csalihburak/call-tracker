"""pacing.py saf mantık testleri."""

from __future__ import annotations

import random
from datetime import datetime

import pytest

from ig_agent import pacing



class TestCalismaSaati:
    def test_aralik_ici(self):
        assert pacing.calisma_saatinde_mi(datetime(2026, 9, 15, 10, 0), 10, 21)
        assert pacing.calisma_saatinde_mi(datetime(2026, 9, 15, 20, 59), 10, 21)

    def test_baslangic_dahil_bitis_haric(self):
        assert pacing.calisma_saatinde_mi(datetime(2026, 9, 15, 10, 0), 10, 21)
        assert not pacing.calisma_saatinde_mi(datetime(2026, 9, 15, 21, 0), 10, 21)

    def test_aralik_disi(self):
        assert not pacing.calisma_saatinde_mi(datetime(2026, 9, 15, 9, 59), 10, 21)
        assert not pacing.calisma_saatinde_mi(datetime(2026, 9, 15, 3, 0), 10, 21)


class TestKota:
    def test_kalan_kota(self):
        assert pacing.kalan_kota(0, 40) == 40
        assert pacing.kalan_kota(38, 40) == 2
        assert pacing.kalan_kota(40, 40) == 0

    def test_asim_negatif_olmaz(self):
        assert pacing.kalan_kota(45, 40) == 0

    def test_kota_var_mi(self):
        assert pacing.kota_var_mi(39, 40)
        assert not pacing.kota_var_mi(40, 40)


class TestBeklemeler:
    def test_insan_beklemesi_aralikta(self):
        rng = random.Random(42)
        for _ in range(100):
            s = pacing.insan_beklemesi_sn(rng, 45.0, 180.0)
            assert 45.0 <= s <= 180.0

    def test_ters_aralik_duzeltilir(self):
        rng = random.Random(1)
        s = pacing.insan_beklemesi_sn(rng, 180.0, 45.0)
        assert 45.0 <= s <= 180.0

    def test_yazma_suresi_uzunlukla_artar(self):
        rng = random.Random(7)
        kisa = pacing.yazma_suresi_sn(random.Random(7), "ok", 0.04, 0.12)
        uzun = pacing.yazma_suresi_sn(random.Random(7), "ok" * 50, 0.04, 0.12)
        assert uzun > kisa


class TestIzinVerilenAksiyonlar:
    def _kotalar(self):
        return [
            pacing.KotaDurumu("opener", 5, 40),
            pacing.KotaDurumu("respond", 80, 80),  # dolu
            pacing.KotaDurumu("discover", 0, 150),
        ]

    def test_normal_durum_musait_olanlar(self):
        an = datetime(2026, 9, 15, 12, 0)
        sonuc = pacing.izin_verilen_aksiyonlar(an, 10, 21, self._kotalar())
        assert "opener" in sonuc
        assert "discover" in sonuc
        assert "respond" not in sonuc  # kota dolu

    def test_master_duraklatma_hersey_durur(self):
        an = datetime(2026, 9, 15, 12, 0)
        sonuc = pacing.izin_verilen_aksiyonlar(
            an, 10, 21, self._kotalar(), master_duraklatildi=True
        )
        assert sonuc == []

    def test_checkpoint_hersey_durur(self):
        an = datetime(2026, 9, 15, 12, 0)
        sonuc = pacing.izin_verilen_aksiyonlar(
            an, 10, 21, self._kotalar(), checkpoint_var=True
        )
        assert sonuc == []

    def test_calisma_saati_disinda_hersey_durur(self):
        an = datetime(2026, 9, 15, 23, 0)
        sonuc = pacing.izin_verilen_aksiyonlar(an, 10, 21, self._kotalar())
        assert sonuc == []
