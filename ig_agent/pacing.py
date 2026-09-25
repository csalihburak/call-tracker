"""Anti-ban hız-sınırı ve çalışma-saati mantığı.

Bu modül bilinçli olarak *saftır* (I/O yok, yan etki yok, rastgelelik enjekte
edilir) — böylece davranış deterministik olarak test edilebilir. Zamanlayıcı bu
fonksiyonlara bakarak "şu an ne yapabilirim?" kararını verir.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime


def calisma_saatinde_mi(
    an: datetime, baslangic_saat: int, bitis_saat: int
) -> bool:
    """[baslangic, bitis) yarı-açık aralığı. Örn. 10–21 → 10:00–20:59 çalışır."""
    return baslangic_saat <= an.hour < bitis_saat


def kalan_kota(bugun_yapilan: int, tavan: int) -> int:
    """Bugün için kalan aksiyon hakkı (negatif olmaz)."""
    return max(0, tavan - bugun_yapilan)


def kota_var_mi(bugun_yapilan: int, tavan: int) -> bool:
    return kalan_kota(bugun_yapilan, tavan) > 0


def insan_beklemesi_sn(
    rng: random.Random, minimum: float, maksimum: float
) -> float:
    """Aksiyonlar arası insan-benzeri bekleme süresi (saniye)."""
    if maksimum < minimum:
        minimum, maksimum = maksimum, minimum
    return rng.uniform(minimum, maksimum)


def yazma_suresi_sn(
    rng: random.Random, metin: str, min_kar: float, max_kar: float
) -> float:
    """Bir metni 'yazmanın' insan-benzeri toplam süresi (saniye)."""
    karakter_basi = rng.uniform(min_kar, max_kar)
    return len(metin) * karakter_basi


@dataclass
class KotaDurumu:
    """Bir aksiyon türü için anlık kota fotoğrafı."""

    tur: str
    yapilan: int
    tavan: int

    @property
    def kalan(self) -> int:
        return kalan_kota(self.yapilan, self.tavan)

    @property
    def musait(self) -> bool:
        return self.kalan > 0


def izin_verilen_aksiyonlar(
    an: datetime,
    baslangic_saat: int,
    bitis_saat: int,
    kotalar: list[KotaDurumu],
    master_duraklatildi: bool = False,
    checkpoint_var: bool = False,
) -> list[str]:
    """Şu an gerçekleştirilebilecek aksiyon türlerini döner.

    Master duraklatma veya checkpoint algılandıysa hiçbir aksiyon yapılmaz.
    Çalışma saati dışında da (ban güvenliği) aksiyon yapılmaz.
    """
    if master_duraklatildi or checkpoint_var:
        return []
    if not calisma_saatinde_mi(an, baslangic_saat, bitis_saat):
        return []
    return [k.tur for k in kotalar if k.musait]
