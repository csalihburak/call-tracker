"""Ortam değişkenlerinden ayarlar.

Hassas değerler (OpenAI anahtarı, backend secret) koda gömülmez; `.env` veya
gerçek ortam değişkenlerinden okunur. `.env` varsa ve python-dotenv kuruluysa
otomatik yüklenir; yoksa yalnızca os.environ kullanılır.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Proje kökü: bu dosyanın bir üstü (call-tracker/)
PROJE_KOKU = Path(__file__).resolve().parent.parent


def _dotenv_yukle() -> None:
    """`.env` dosyasını (varsa) ortama yükler. python-dotenv opsiyoneldir."""
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    env_yolu = PROJE_KOKU / ".env"
    if env_yolu.exists():
        load_dotenv(env_yolu)


def _str(anahtar: str, varsayilan: str = "") -> str:
    return os.environ.get(anahtar, varsayilan).strip()


def _int(anahtar: str, varsayilan: int) -> int:
    ham = os.environ.get(anahtar)
    if ham is None or ham.strip() == "":
        return varsayilan
    try:
        return int(ham)
    except ValueError:
        return varsayilan


def _float(anahtar: str, varsayilan: float) -> float:
    ham = os.environ.get(anahtar)
    if ham is None or ham.strip() == "":
        return varsayilan
    try:
        return float(ham)
    except ValueError:
        return varsayilan


def _liste(anahtar: str, varsayilan: list[str]) -> list[str]:
    ham = os.environ.get(anahtar)
    if not ham:
        return list(varsayilan)
    return [parca.strip() for parca in ham.split(",") if parca.strip()]


# Platform başına direkt DM başlangıç kotası (saatlik, günlük) — spec 4.4.
# Instagram'ınki PacingAyarlari varsayılanlarıdır.
PLATFORM_DM_KOTA = {"tiktok": (8, 40), "facebook": (8, 30)}

# Keşif için varsayılan hedefler — şimdilik SADECE halı yıkama
VARSAYILAN_HASHTAGLER = [
    "haliyikama",
    "haliyıkama",
    "haliyikamaci",
    "profesyonelhaliyikama",
]

VARSAYILAN_SEHIRLER = [
    "istanbul",
    "ankara",
    "izmir",
    "bursa",
    "konya",
    "kayseri",
    "antalya",
    "adana",
]


@dataclass
class GptAyarlari:
    api_anahtari: str = ""
    model: str = "gpt-4o"
    sicaklik: float = 0.7
    max_token: int = 500


@dataclass
class SheetsAyarlari:
    # Servis hesabı credentials JSON yolu (Google Cloud'dan indirilen)
    credentials_yolu: str = ""
    # Hedef Google Sheet kimliği (URL'deki /d/<ID>/ kısmı)
    sheet_id: str = ""
    etkin: bool = False


@dataclass
class BackendAyarlari:
    # Sıcak lead bildirimi için backend endpoint tabanı, ör. https://api.temizify.com
    taban_url: str = ""
    # /internal/sales-alerts için paylaşılan secret (backend guard'ıyla eşleşir)
    paylasilan_secret: str = ""
    zaman_asimi_sn: float = 15.0

    @property
    def etkin(self) -> bool:
        return bool(self.taban_url and self.paylasilan_secret)


@dataclass
class PacingAyarlari:
    """Anti-ban hız sınırı ve warmup parametreleri."""

    # Hikaye-yanıtı (açılış) tavanları. 0 = sınırsız.
    acilis_saatlik: int = 100  # son 60 dakikada en fazla
    acilis_gunluk: int = 0  # bugün en fazla

    dm_max_gunluk: int = 80  # gönderilen DM yanıtı günlük tavanı
    kesif_max_gunluk: int = 150  # bir günde kuyruğa eklenecek yeni lead tavanı

    calisma_baslangic_saat: int = 10  # 10:00
    calisma_bitis_saat: int = 21  # 21:00 (dahil değil)

    # Hikaye tepsisini yeniden gezmeden önce beklenecek süre (saniye)
    hikaye_turu_cooldown_sn: int = 600

    # Takip listesinden direkt DM açılışı (hikaye yanıtından AYRI tavan). 0 = sınırsız.
    dm_acilis_saatlik: int = 15
    dm_acilis_gunluk: int = 80
    # Direkt DM turunu yeniden başlatmadan önce beklenecek süre (saniye)
    dm_turu_cooldown_sn: int = 1800

    # Aksiyonlar arası insan benzeri bekleme (saniye)
    aksiyon_bekleme_min: float = 45.0
    aksiyon_bekleme_max: float = 180.0
    # Yazma simülasyonu: karakter başına saniye aralığı
    yazma_min_kar_sn: float = 0.04
    yazma_max_kar_sn: float = 0.12


@dataclass
class Ayarlar:
    # Bu ayarların ait olduğu platform; canlı ayar anahtarlarının önekini belirler
    platform: str = "instagram"
    veritabani_yolu: str = str(PROJE_KOKU / "sales.db")
    # Playwright kalıcı profil dizini (IG oturumu burada saklanır)
    tarayici_profil_dizini: str = str(PROJE_KOKU / ".ig_profile")
    headless: bool = False  # IG için daima headful önerilir

    hashtagler: list[str] = field(default_factory=lambda: list(VARSAYILAN_HASHTAGLER))
    sehirler: list[str] = field(default_factory=lambda: list(VARSAYILAN_SEHIRLER))

    # WhatsApp yönlendirme için işletme numarası / linki
    whatsapp_numarasi: str = ""
    whatsapp_link: str = ""

    # Bu kadar gün içinde mesajlaştığımız hesaba yeniden açılış YAPMA.
    # 0 = süre sınırı yok: bir kez yazılan hesaba bir daha asla açılış yapılmaz.
    yeniden_iletisim_gun: int = 0

    # Açılış metni: "gpt" → her hikayeye GPT ile çeşitlendirilmiş metin,
    # "sabit" → `acilis_metinleri` satırlarından rastgele biri
    acilis_modu: str = "gpt"
    acilis_metinleri: str = ""

    # Kendi IG kullanıcı adımız (takip listesi için). Boşsa sayfadan bulunur.
    kendi_kullanici_adi: str = ""

    gpt: GptAyarlari = field(default_factory=GptAyarlari)
    sheets: SheetsAyarlari = field(default_factory=SheetsAyarlari)
    backend: BackendAyarlari = field(default_factory=BackendAyarlari)
    pacing: PacingAyarlari = field(default_factory=PacingAyarlari)


def ayarlari_yukle(platform: str = "instagram") -> Ayarlar:
    """Ortamdan tam ayar nesnesini üretir (`platform` için uyarlanmış)."""
    _dotenv_yukle()

    ayarlar = Ayarlar(
        veritabani_yolu=_str("IG_DB_YOLU", str(PROJE_KOKU / "sales.db")),
        tarayici_profil_dizini=_str(
            "IG_PROFIL_DIZINI", str(PROJE_KOKU / ".ig_profile")
        ),
        headless=_str("IG_HEADLESS", "0") in ("1", "true", "True"),
        hashtagler=_liste("IG_HASHTAGLER", VARSAYILAN_HASHTAGLER),
        sehirler=_liste("IG_SEHIRLER", VARSAYILAN_SEHIRLER),
        whatsapp_numarasi=_str("IG_WHATSAPP_NUMARASI"),
        whatsapp_link=_str("IG_WHATSAPP_LINK"),
        yeniden_iletisim_gun=_int("IG_YENIDEN_ILETISIM_GUN", 0),
        acilis_modu=_str("IG_ACILIS_MODU", "gpt"),
        kendi_kullanici_adi=_str("IG_KULLANICI_ADI"),
        gpt=GptAyarlari(
            api_anahtari=_str("OPENAI_API_KEY"),
            model=_str("IG_GPT_MODEL", "gpt-4o"),
            sicaklik=_float("IG_GPT_SICAKLIK", 0.7),
            max_token=_int("IG_GPT_MAX_TOKEN", 500),
        ),
        sheets=SheetsAyarlari(
            credentials_yolu=_str("IG_SHEETS_CREDENTIALS"),
            sheet_id=_str("IG_SHEETS_ID"),
            etkin=_str("IG_SHEETS_ETKIN", "0") in ("1", "true", "True"),
        ),
        backend=BackendAyarlari(
            taban_url=_str("IG_BACKEND_URL"),
            paylasilan_secret=_str("IG_BACKEND_SECRET"),
            zaman_asimi_sn=_float("IG_BACKEND_ZAMAN_ASIMI", 15.0),
        ),
        pacing=PacingAyarlari(
            acilis_saatlik=_int("IG_ACILIS_SAATLIK", 100),
            acilis_gunluk=_int("IG_ACILIS_GUNLUK", 0),
            dm_max_gunluk=_int("IG_DM_MAX", 80),
            kesif_max_gunluk=_int("IG_KESIF_MAX", 150),
            calisma_baslangic_saat=_int("IG_CALISMA_BASLANGIC", 10),
            calisma_bitis_saat=_int("IG_CALISMA_BITIS", 21),
            hikaye_turu_cooldown_sn=_int("IG_HIKAYE_COOLDOWN_SN", 600),
            dm_acilis_saatlik=_int("IG_DM_ACILIS_SAATLIK", 15),
            dm_acilis_gunluk=_int("IG_DM_ACILIS_GUNLUK", 80),
            dm_turu_cooldown_sn=_int("IG_DM_TURU_COOLDOWN_SN", 1800),
            aksiyon_bekleme_min=_float("IG_BEKLEME_MIN", 45.0),
            aksiyon_bekleme_max=_float("IG_BEKLEME_MAX", 180.0),
        ),
    )
    if platform != "instagram":
        _platforma_uyarla(ayarlar, platform)
    return ayarlar


def _platforma_uyarla(ayarlar: Ayarlar, platform: str) -> None:
    """IG varsayılanlarını başka bir platform için değiştirir: ayrı tarayıcı
    profili, kendi kullanıcı adı ve direkt DM kotası (`TIKTOK_*` ortam değişkenleri)."""
    if platform not in PLATFORM_DM_KOTA:
        raise ValueError(f"bilinmeyen platform: {platform}")
    on = platform.upper()
    ayarlar.platform = platform
    ayarlar.tarayici_profil_dizini = _str(
        f"{on}_PROFIL_DIZINI", str(PROJE_KOKU / f".{platform}_profile")
    )
    ayarlar.kendi_kullanici_adi = _str(f"{on}_KULLANICI_ADI")
    saatlik, gunluk = PLATFORM_DM_KOTA[platform]
    ayarlar.pacing.dm_acilis_saatlik = _int(f"{on}_DM_ACILIS_SAATLIK", saatlik)
    ayarlar.pacing.dm_acilis_gunluk = _int(f"{on}_DM_ACILIS_GUNLUK", gunluk)
