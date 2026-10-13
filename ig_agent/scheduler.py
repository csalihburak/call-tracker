"""Zamanlayıcı: tek tarayıcı oturumunu insan-tempolu sürer + kararları uygular.

İki test edilebilir saf parça buradadır:
  - `sonraki_gorev`  : kotalara/kuyruklara bakıp hangi işin yapılacağını seçer
  - `karari_uygula`  : bir AjanKarari'yi DB + gönderim + bildirime dönüştürür
Tarayıcıya bağlı orkestrasyon (`tek_tur`) bunları enjekte edilen istemcilerle
birleştirir; ana döngü `run.py`'dedir.
"""

from __future__ import annotations

import random
import sqlite3
import time
from datetime import datetime
from typing import Callable, Optional, Protocol

from . import brain, pacing, repository as repo
from .config import Ayarlar
from .platformlar import TURU_BITIR, GonderimSonucu, Hedef

# Görev türleri (pacing kotalarıyla aynı adlar)
RESPOND = "respond"
OPENER = "opener"
DISCOVER = "discover"


# --------------------------------------------------------------------------- #
# Enjekte edilen bağımlılıklar (protokoller)
# --------------------------------------------------------------------------- #
class IGClient(Protocol):
    def dm_gonder(self, handle: str, metin: str) -> bool: ...
    def hikaye_yaniti_gonder(self, handle: str, metin: str) -> bool: ...


class BildirimClient(Protocol):
    def sicak_lead_bildir(self, lead, karar: "brain.AjanKarari") -> bool: ...


# --------------------------------------------------------------------------- #
# Saf: hangi görev?
# --------------------------------------------------------------------------- #
def sonraki_gorev(
    izinli: list[str], yanit_var: bool, acilis_var: bool
) -> Optional[str]:
    """Öncelik: bekleyen yanıt > açılış > keşif. Kota + kuyruk birlikte gerekir."""
    if RESPOND in izinli and yanit_var:
        return RESPOND
    if OPENER in izinli and acilis_var:
        return OPENER
    if DISCOVER in izinli:
        return DISCOVER
    return None


# Hikaye tepsisini yeniden gezmeden önce beklenecek varsayılan süre
HIKAYE_TURU_COOLDOWN_SN = 600

# Tavan 0 (sınırsız) iken "kalan" için kullanılan büyük sayı
SINIRSIZ = 10**6


def acilis_kalan(conn: sqlite3.Connection, ayarlar: Ayarlar) -> int:
    """Şu an gönderilebilecek hikaye-yanıtı sayısı (saatlik ve günlük tavanın küçüğü)."""
    p = ayarlar.pacing
    kalan = SINIRSIZ
    if p.acilis_saatlik > 0:
        kalan = min(kalan, max(0, p.acilis_saatlik - repo.son_saat_acilis_sayisi(conn)))
    if p.acilis_gunluk > 0:
        kalan = min(kalan, max(0, p.acilis_gunluk - repo.bugun_acilis_sayisi(conn)))
    return kalan


def acilis_araligi_sn(ayarlar: Ayarlar, rng: random.Random) -> float:
    """İki hikaye-yanıtı arası hedef süre: saatlik tavanı saate yayar (±%30)."""
    saatlik = ayarlar.pacing.acilis_saatlik
    if saatlik <= 0:
        return rng.uniform(8.0, 20.0)
    return (3600.0 / saatlik) * rng.uniform(0.7, 1.3)


def uyku(conn: sqlite3.Connection, sn: float, adim: float = 5.0) -> bool:
    """Parça parça uyur ve nabız atar. Duraklatılırsa erken döner (False)."""
    bitis = time.monotonic() + max(0.0, sn)
    while True:
        if repo.bayrak_getir(conn, "master_paused", True):
            return False
        repo.nabiz_at(conn)
        kalan = bitis - time.monotonic()
        if kalan <= 0:
            return True
        time.sleep(min(adim, kalan))


def kota_durumlari(conn: sqlite3.Connection, ayarlar: Ayarlar) -> list[pacing.KotaDurumu]:
    """Anlık kota fotoğrafı. Açılış: yapılan = son 60 dk, tavan = yapılan + kalan."""
    p = ayarlar.pacing
    son_saat = repo.son_saat_acilis_sayisi(conn)
    # Hashtag keşfi varsayılan KAPALI (story-tepsisi birincil açılış kaynağı).
    kesif_aktif = repo.bayrak_getir(conn, "kesif_aktif", False)
    kesif_tavan = p.kesif_max_gunluk if kesif_aktif else 0
    return [
        pacing.KotaDurumu(RESPOND, repo.bugun_yanit_sayisi(conn), p.dm_max_gunluk),
        pacing.KotaDurumu(OPENER, son_saat, son_saat + acilis_kalan(conn, ayarlar)),
        pacing.KotaDurumu(DISCOVER, repo.bugun_kesif_sayisi(conn), kesif_tavan),
    ]


def _hikaye_turu_zamani(
    conn: sqlite3.Connection, cooldown: int = HIKAYE_TURU_COOLDOWN_SN
) -> bool:
    """Son hikaye turundan bu yana yeterince zaman geçti mi?"""
    son = repo.durum_getir(conn, "son_hikaye_turu", "")
    if not son:
        return True
    try:
        gecen = (datetime.now() - datetime.fromisoformat(son)).total_seconds()
        return gecen >= cooldown
    except ValueError:
        return True


def hikaye_turu_yap(
    conn,
    ayarlar,
    ig,
    beyin_istemci,
    rng: Optional[random.Random] = None,
    uyku_fn: Optional[Callable[[float], bool]] = None,
    simdi_fn: Callable[[], datetime] = datetime.now,
) -> int:
    """Hikaye tepsisini sonuna kadar gezip yeni hedeflere açılış yanıtı gönderir.

    Daha önce yazışılmış (`yeniden_iletisim_gun` 0 ise hiç, değilse son N gün) veya do-not-contact hesaplar
    atlanır. Her gönderim anında DB'ye yazılır; gönderimler saatlik tavana göre
    zamana yayılır. Duraklatma, kota dolması veya çalışma saatinin bitmesi turu
    hemen bitirir. Gönderilen açılış sayısını döner.
    """
    rng = rng or random.Random()
    uyku_fn = uyku_fn or (lambda sn: uyku(conn, sn))
    p = ayarlar.pacing

    if acilis_kalan(conn, ayarlar) <= 0:
        repo.durum_ayarla(conn, "son_hikaye_turu", datetime.now().isoformat())
        print("[opener] açılış kotası dolu — tur atlandı")
        return 0

    gun = getattr(ayarlar, "yeniden_iletisim_gun", 0)
    istatistik = {"secildi": 0, "gonderildi": 0, "atlandi_yakin": 0, "atlandi_dnc": 0, "gorulen": 0}

    def karar_fn(handle: str):
        istatistik["gorulen"] += 1
        repo.nabiz_at(conn, f"hikaye turu · @{handle} · gönderilen {istatistik['gonderildi']}")
        if repo.bayrak_getir(conn, "master_paused", False):
            return TURU_BITIR
        if not pacing.calisma_saatinde_mi(simdi_fn(), p.calisma_baslangic_saat, p.calisma_bitis_saat):
            return TURU_BITIR
        if acilis_kalan(conn, ayarlar) <= 0:
            return TURU_BITIR
        h = (handle or "").strip().lstrip("@")
        if not h:
            return None
        if repo.dnc_handle_mi(conn, h):
            istatistik["atlandi_dnc"] += 1
            return None
        if repo.yakin_zamanda_iletisim(conn, h, gun):
            istatistik["atlandi_yakin"] += 1  # daha önce (son `gun` günde) yazışmışız
            return None
        lead = repo.lead_getir_handle(conn, h)
        istatistik["secildi"] += 1
        return _acilis_metni(beyin_istemci, ayarlar, lead, rng)

    def yazmadan_once() -> bool:
        """Bir önceki açılıştan bu yana hedef aralık dolmadıysa bekle."""
        bekle = acilis_araligi_sn(ayarlar, rng)
        son = repo.son_acilis_zamani(conn)
        if son:
            try:
                bekle -= (datetime.now() - datetime.fromisoformat(son)).total_seconds()
            except ValueError:
                pass
        if bekle > 0:
            repo.nabiz_at(conn, f"hikaye turu · tempo beklemesi {int(bekle)} sn")
        return uyku_fn(max(0.0, bekle))

    def sonuc_fn(handle: str, metin: str) -> None:
        h = (handle or "").strip().lstrip("@")
        lead_id = repo.ig_lead_upsert(conn, ig_handle=h, business_name=h)
        repo.mesaj_ekle(conn, lead_id, "story_reply", metin, ai_generated=True)
        istatistik["gonderildi"] += 1

    ig.hikayeleri_yanitla(karar_fn, sonuc_fn=sonuc_fn, yazmadan_once=yazmadan_once)

    gonderilen = istatistik["gonderildi"]
    repo.durum_ayarla(conn, "son_hikaye_turu", datetime.now().isoformat())
    print(
        f"[opener] hikaye turu: gezilen={istatistik['gorulen']} "
        f"seçildi={istatistik['secildi']} gönderildi={gonderilen} "
        f"atlandı(önceden yazılmış{f', son {gun}g' if gun > 0 else ''})={istatistik['atlandi_yakin']} "
        f"atlandı(dnc)={istatistik['atlandi_dnc']} "
        f"son 1 saat={repo.son_saat_acilis_sayisi(conn)}"
    )
    basarisiz = istatistik["secildi"] - gonderilen
    if basarisiz > 0 and not getattr(ig, "engel_algilandi", False):
        print(f"[opener] ⚠️ {basarisiz} hikayede yanıt gönderilemedi — "
              f"S.HIKAYE_YANIT_KUTUSU seçicisi ayarlanmalı olabilir")
    return gonderilen


# --------------------------------------------------------------------------- #
# Saf(ça): kararı uygula
# --------------------------------------------------------------------------- #
def _etiketleri_uygula(conn, lead_id: int, karar: brain.AjanKarari) -> None:
    if karar.stage:
        repo.asama_guncelle(conn, lead_id, karar.stage)
    if karar.outcome:
        repo.sonuc_guncelle(conn, lead_id, karar.outcome)
    if karar.objection:
        repo.olay_ekle(conn, lead_id, "objection", detail=karar.objection)


def karari_uygula(
    conn: sqlite3.Connection,
    ayarlar: Ayarlar,
    lead: sqlite3.Row,
    karar: brain.AjanKarari,
    ig: IGClient,
    bildirim: BildirimClient,
) -> bool:
    """Bir kararı gerçekleştirir. Gönderim başarısızsa DB'ye yazmaz (False döner)."""
    lead_id = int(lead["id"])
    handle = lead["ig_handle"]
    a = karar.action

    def _yaz(metin: str) -> bool:
        if not metin:
            return True
        gonderildi = ig.dm_gonder(handle, metin)
        if gonderildi:
            repo.mesaj_ekle(conn, lead_id, "outbound", metin, ai_generated=True)
        return gonderildi

    if a == brain.YAZ:
        if not _yaz(karar.text):
            return False
        _etiketleri_uygula(conn, lead_id, karar)
        return True

    if a == brain.WHATSAPP:
        if not _yaz(karar.text):
            return False
        repo.olay_ekle(conn, lead_id, "redirected_whatsapp", detail=karar.text)
        _etiketleri_uygula(conn, lead_id, karar)
        return True

    if a == brain.DENEME:
        if not _yaz(karar.text):
            return False
        repo.asama_guncelle(conn, lead_id, karar.stage or "deneme")
        repo.olay_ekle(
            conn, lead_id, "trial_proposed",
            detail=karar.text, phone=karar.phone or "",
        )
        if karar.outcome:
            repo.sonuc_guncelle(conn, lead_id, karar.outcome)
        try:
            bildirim.sicak_lead_bildir(lead, karar)
        except Exception:
            # Bildirim başarısızlığı satışı bozmasın; operatör panelde de görecek
            pass
        return True

    if a == brain.DEVRET:
        _yaz(karar.text)  # opsiyonel kısa mesaj; başarısızlığı devri engellemesin
        repo.olay_ekle(conn, lead_id, "handoff", detail=karar.reason or "")
        repo.ai_durumu_ayarla(conn, lead_id, False)  # bu thread'de AI durur
        try:
            bildirim.sicak_lead_bildir(lead, karar)
        except Exception:
            pass
        return True

    if a == brain.KES:
        repo.olay_ekle(conn, lead_id, "lost", detail=karar.reason or "")
        repo.do_not_contact_isaretle(conn, lead_id, reason=karar.reason or "")
        repo.asama_guncelle(conn, lead_id, "kayip")
        if karar.outcome:
            repo.sonuc_guncelle(conn, lead_id, karar.outcome)
        return True

    if a == brain.TAKIP:
        _yaz(karar.text)
        repo.olay_ekle(conn, lead_id, "followup", detail=karar.follow_up or "")
        repo.sonuc_guncelle(conn, lead_id, karar.outcome or "tekrar_ara")
        if karar.stage:
            repo.asama_guncelle(conn, lead_id, karar.stage)
        return True

    return False


# --------------------------------------------------------------------------- #
# Tarayıcıya bağlı orkestrasyon
# --------------------------------------------------------------------------- #
def durum_ozeti(conn: sqlite3.Connection, ayarlar: Ayarlar) -> dict:
    """Kontrol paneli / log için anlık durum."""
    an = datetime.now()
    kotalar = kota_durumlari(conn, ayarlar)
    master = repo.bayrak_getir(conn, "master_paused", True)
    checkpoint = repo.bayrak_getir(conn, "checkpoint_detected", False)
    engel = repo.bayrak_getir(conn, "action_block", False)
    izinli = pacing.izin_verilen_aksiyonlar(
        an,
        ayarlar.pacing.calisma_baslangic_saat,
        ayarlar.pacing.calisma_bitis_saat,
        kotalar,
        master_duraklatildi=master,
        checkpoint_var=checkpoint or engel,
    )
    return {
        "an": an.isoformat(timespec="seconds"),
        "master_paused": master,
        "checkpoint": checkpoint,
        "action_block": engel,
        "acilis_son_saat": repo.son_saat_acilis_sayisi(conn),
        "acilis_bugun": repo.bugun_acilis_sayisi(conn),
        "kotalar": {k.tur: {"yapilan": k.yapilan, "tavan": k.tavan, "kalan": k.kalan} for k in kotalar},
        "izinli_aksiyonlar": izinli,
    }


def engel_isaretle(conn: sqlite3.Connection, ig) -> bool:
    """IG action-block gösterdiyse botu duraklat. İşaretlendiyse True döner."""
    if not getattr(ig, "engel_algilandi", False):
        return False
    ig.engel_algilandi = False  # panelden temizlenince yeniden başlayabilsin
    repo.durum_ayarla(conn, "action_block", "1")
    repo.durum_ayarla(conn, "master_paused", "1")
    repo.hata_kaydet(conn, "Instagram 'işlem engellendi' uyarısı gösterdi — bot duraklatıldı")
    print("[bot] ⛔ ACTION BLOCK algılandı — bot duraklatıldı. Limitleri düşürüp "
          "birkaç saat bekledikten sonra panelden temizleyip başlatın.")
    return True


def tek_tur(
    conn: sqlite3.Connection,
    ayarlar: Ayarlar,
    ig,
    beyin_istemci,
    bildirim,
    rng,
) -> Optional[str]:
    """Bir zamanlayıcı adımı: görevi seç, uygula, insan beklemesi kadar bekle.

    Döndürdüğü: yapılan görev türü ya da None (yapılacak iş yok / duraklatıldı).
    """
    an = datetime.now()
    kotalar = kota_durumlari(conn, ayarlar)
    izinli = pacing.izin_verilen_aksiyonlar(
        an,
        ayarlar.pacing.calisma_baslangic_saat,
        ayarlar.pacing.calisma_bitis_saat,
        kotalar,
        master_duraklatildi=repo.bayrak_getir(conn, "master_paused", True),
        checkpoint_var=(
            repo.bayrak_getir(conn, "checkpoint_detected", False)
            or repo.bayrak_getir(conn, "action_block", False)
        ),
    )
    yanitlar = repo.yanit_bekleyen_threadler(conn, limit=1)
    yanit_var = bool(yanitlar)
    # Açılış kaynağı artık hikaye tepsisi; soğuma süresi geçtiyse tur yapılabilir
    acilis_var = _hikaye_turu_zamani(conn, ayarlar.pacing.hikaye_turu_cooldown_sn)
    gorev = sonraki_gorev(izinli, yanit_var, acilis_var)
    if gorev is None:
        return None

    if gorev == RESPOND:
        lead = yanitlar[0]
        lead_id = int(lead["id"])
        repo.nabiz_at(conn, f"yanıt yazılıyor · @{lead['ig_handle']}")
        thread = repo.thread_mesajlari(conn, lead_id)
        try:
            karar = brain.karar_ver(beyin_istemci, ayarlar, lead, thread)
            basarili = karari_uygula(conn, ayarlar, lead, karar, ig, bildirim)
        finally:
            # Hata/başarısızlıkta da bu gelen mesajı işlenmiş say: aynı mesaja
            # sonsuza kadar GPT çağrısı + sayfa gezintisi yapılmasın.
            repo.islendi_isaretle(conn, lead_id)
        if not basarili:
            repo.olay_ekle(conn, lead_id, "send_failed", detail=karar.action)
    elif gorev == OPENER:
        repo.nabiz_at(conn, "hikaye turu başlıyor")
        hikaye_turu_yap(conn, ayarlar, ig, beyin_istemci, rng)
    elif gorev == DISCOVER:
        repo.nabiz_at(conn, "hashtag keşfi")
        _kesif_turu(conn, ayarlar, ig)

    if engel_isaretle(conn, ig):
        return gorev
    repo.nabiz_at(conn, f"{gorev} bitti · insan beklemesi")
    _bekle(conn, rng, ayarlar)
    return gorev


def _acilis_metni(
    beyin_istemci, ayarlar, lead, rng: Optional[random.Random] = None, baglam: str = "hikaye"
) -> str:
    """Açılış metni (`baglam`: "hikaye" = hikaye yanıtı, "dm" = direkt DM).

    "sabit" modda panelde girilen satırlardan rastgele biri; aksi halde beyin
    varsa GPT ile çeşitlendirilmiş metin, yoksa güvenli sabit.
    """
    if getattr(ayarlar, "acilis_modu", "gpt") == "sabit":
        satirlar = [x.strip() for x in (ayarlar.acilis_metinleri or "").splitlines() if x.strip()]
        if satirlar:
            return (rng or random).choice(satirlar)
    try:
        if hasattr(beyin_istemci, "acilis_uret"):
            return beyin_istemci.acilis_uret(ayarlar, lead, baglam=baglam)
    except Exception:
        pass
    return "Merhabalar, kolay gelsin! İşlerinizin takibini yapmak için herhangi bir program kullanıyor musunuz?"


def _kesif_turu(conn, ayarlar, ig) -> None:
    """Bir hashtag/şehir için keşif turu; bulunanları lead olarak ekler."""
    if not hasattr(ig, "hashtag_kesfet"):
        return
    tag = random.choice(ayarlar.hashtagler) if ayarlar.hashtagler else "haliyikama"
    sehir = random.choice(ayarlar.sehirler) if ayarlar.sehirler else ""
    for aday in ig.hashtag_kesfet(tag, sehir):
        handle = aday.get("handle")
        if not handle or repo.dnc_handle_mi(conn, handle):
            continue
        repo.ig_lead_upsert(
            conn,
            ig_handle=handle,
            business_name=aday.get("business_name", handle),
            ig_profile_url=aday.get("profile_url", ""),
            ig_followers=aday.get("followers"),
            city=aday.get("city", sehir),
            discovery_hashtag=tag,
            discovery_city=sehir,
        )


def _bekle(conn, rng, ayarlar) -> None:
    sn = pacing.insan_beklemesi_sn(
        rng, ayarlar.pacing.aksiyon_bekleme_min, ayarlar.pacing.aksiyon_bekleme_max
    )
    uyku(conn, sn)
