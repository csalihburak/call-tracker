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
from datetime import datetime, timedelta
from typing import Callable, Optional, Protocol

from . import brain, pacing, repository as repo
from .config import Ayarlar
from .platformlar import PLATFORM_ADI, TURU_BITIR, GonderimSonucu, Hedef, anahtar

# Görev türleri (pacing kotalarıyla aynı adlar)
RESPOND = "respond"
OPENER = "opener"
DISCOVER = "discover"
DIRECT_DM = "direct_dm"


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
    izinli: list[str], yanit_var: bool, acilis_var: bool, dm_var: bool = False
) -> Optional[str]:
    """Öncelik: yanıt > hikaye açılışı > direkt DM > keşif. Kota + kuyruk birlikte gerekir."""
    if RESPOND in izinli and yanit_var:
        return RESPOND
    if OPENER in izinli and acilis_var:
        return OPENER
    if DIRECT_DM in izinli and dm_var:
        return DIRECT_DM
    if DISCOVER in izinli:
        return DISCOVER
    return None


# Hikaye tepsisini yeniden gezmeden önce beklenecek varsayılan süre
HIKAYE_TURU_COOLDOWN_SN = 600

# Tavan 0 (sınırsız) iken "kalan" için kullanılan büyük sayı
SINIRSIZ = 10**6

# Direkt DM turu tek seferde en fazla bu kadar sürer; sonra ara verilir ki
# yanıt / hikaye turu araya girebilsin (ara verilen tur soğuma beklemez)
DM_TURU_ZAMAN_KUTUSU_SN = 15 * 60
# Art arda bu kadar gönderim BASARISIZ olursa tur biter (seçici kırılması)
DM_ARDISIK_BASARISIZ_TAVAN = 5


def acilis_kalan(conn: sqlite3.Connection, ayarlar: Ayarlar) -> int:
    """Şu an gönderilebilecek hikaye-yanıtı sayısı (saatlik ve günlük tavanın küçüğü)."""
    p = ayarlar.pacing
    kalan = SINIRSIZ
    if p.acilis_saatlik > 0:
        kalan = min(kalan, max(0, p.acilis_saatlik - repo.son_saat_acilis_sayisi(conn)))
    if p.acilis_gunluk > 0:
        kalan = min(kalan, max(0, p.acilis_gunluk - repo.bugun_acilis_sayisi(conn)))
    return kalan


def _aralik_sn(saatlik: int, rng: random.Random) -> float:
    """Saatlik tavanı saate yayan hedef aralık (±%30); tavan 0 ise kısa rastgele."""
    if saatlik <= 0:
        return rng.uniform(8.0, 20.0)
    return (3600.0 / saatlik) * rng.uniform(0.7, 1.3)


def acilis_araligi_sn(ayarlar: Ayarlar, rng: random.Random) -> float:
    """İki hikaye-yanıtı arası hedef süre."""
    return _aralik_sn(ayarlar.pacing.acilis_saatlik, rng)


def dm_acilis_kalan(
    conn: sqlite3.Connection, ayarlar: Ayarlar, platform: str = "instagram"
) -> int:
    """Şu an gönderilebilecek direkt DM açılışı (saatlik ve günlük tavanın küçüğü)."""
    p = ayarlar.pacing
    kalan = SINIRSIZ
    if p.dm_acilis_saatlik > 0:
        kalan = min(kalan, max(0, p.dm_acilis_saatlik - repo.son_saat_dm_acilis_sayisi(conn, platform)))
    if p.dm_acilis_gunluk > 0:
        kalan = min(kalan, max(0, p.dm_acilis_gunluk - repo.bugun_dm_acilis_sayisi(conn, platform)))
    return kalan


def dm_acilis_araligi_sn(ayarlar: Ayarlar, rng: random.Random) -> float:
    """İki direkt DM arası hedef süre."""
    return _aralik_sn(ayarlar.pacing.dm_acilis_saatlik, rng)


def uyku(
    conn: sqlite3.Connection, sn: float, adim: float = 5.0, platform: str = "instagram"
) -> bool:
    """Parça parça uyur ve nabız atar. Duraklatılırsa erken döner (False)."""
    bitis = time.monotonic() + max(0.0, sn)
    while True:
        if repo.bayrak_getir(conn, "master_paused", True, platform=platform):
            return False
        repo.nabiz_at(conn, platform=platform)
        kalan = bitis - time.monotonic()
        if kalan <= 0:
            return True
        time.sleep(min(adim, kalan))


def kota_durumlari(
    conn: sqlite3.Connection, ayarlar: Ayarlar, platform: str = "instagram"
) -> list[pacing.KotaDurumu]:
    """Anlık kota fotoğrafı. Açılış: yapılan = son 60 dk, tavan = yapılan + kalan.

    Instagram dışındaki platformlarda yalnızca direkt DM açılışı vardır (yanıt,
    hikaye turu ve keşif yok).
    """
    p = ayarlar.pacing
    # Direkt DM varsayılan KAPALI; panelden (platform başına) açılır.
    dm_aktif = repo.bayrak_getir(conn, "dm_acilis_aktif", False, platform=platform)
    son_saat_dm = repo.son_saat_dm_acilis_sayisi(conn, platform)
    dm_tavan = son_saat_dm + dm_acilis_kalan(conn, ayarlar, platform) if dm_aktif else 0
    dm_kotasi = pacing.KotaDurumu(DIRECT_DM, son_saat_dm, dm_tavan)
    if platform != "instagram":
        return [dm_kotasi]
    son_saat = repo.son_saat_acilis_sayisi(conn)
    # Hashtag keşfi varsayılan KAPALI (story-tepsisi birincil açılış kaynağı).
    kesif_aktif = repo.bayrak_getir(conn, "kesif_aktif", False)
    kesif_tavan = p.kesif_max_gunluk if kesif_aktif else 0
    return [
        pacing.KotaDurumu(RESPOND, repo.bugun_yanit_sayisi(conn), p.dm_max_gunluk),
        pacing.KotaDurumu(OPENER, son_saat, son_saat + acilis_kalan(conn, ayarlar)),
        dm_kotasi,
        pacing.KotaDurumu(DISCOVER, repo.bugun_kesif_sayisi(conn), kesif_tavan),
    ]


def _tur_zamani(conn: sqlite3.Connection, anahtar: str, cooldown: int) -> bool:
    """`anahtar`daki son tur damgasından bu yana `cooldown` sn geçti mi?"""
    son = repo.durum_getir(conn, anahtar, "")
    if not son:
        return True
    try:
        gecen = (datetime.now() - datetime.fromisoformat(son)).total_seconds()
        return gecen >= cooldown
    except ValueError:
        return True


def _hikaye_turu_zamani(
    conn: sqlite3.Connection, cooldown: int = HIKAYE_TURU_COOLDOWN_SN
) -> bool:
    """Son hikaye turundan bu yana yeterince zaman geçti mi?"""
    return _tur_zamani(conn, "son_hikaye_turu", cooldown)


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


def direkt_dm_turu_yap(
    conn,
    ayarlar,
    istemci,
    beyin_istemci,
    rng: Optional[random.Random] = None,
    uyku_fn: Optional[Callable[[float], bool]] = None,
    simdi_fn: Callable[[], datetime] = datetime.now,
) -> int:
    """İstemcinin hedef listesini (IG: takip edilenler) gezip yeni hedeflere DM atar.

    Hikaye turuyla aynı kurallar: daha önce yazışılmış (o platformda, herhangi
    bir yönde) veya do-not-contact hesaplar atlanır; her gönderim anında DB'ye
    yazılır; gönderimler DM saatlik tavanına göre zamana yayılır; duraklatma,
    kota veya çalışma saati turu bitirir. DM kutusu kapalı hesaplar `dnc`'ye
    `dm_kapali` ile eklenir. Gönderilen DM sayısını döner.
    """
    rng = rng or random.Random()
    p = ayarlar.pacing
    platform = getattr(istemci, "platform", "instagram")
    uyku_fn = uyku_fn or (lambda sn: uyku(conn, sn, platform=platform))
    # Açılış metninin bağlamı: IG "dm", diğerleri "tiktok_dm" gibi
    baglam = "dm" if platform == "instagram" else f"{platform}_dm"

    if dm_acilis_kalan(conn, ayarlar, platform) <= 0:
        repo.durum_ayarla(conn, "son_dm_turu", datetime.now().isoformat(), platform=platform)
        print("[dm] direkt DM kotası dolu — tur atlandı")
        return 0

    gun = getattr(ayarlar, "yeniden_iletisim_gun", 0)
    ist = {"gorulen": 0, "secildi": 0, "gonderildi": 0, "kapali": 0, "onceki": 0,
           "basarisiz": 0, "atlandi_yakin": 0, "atlandi_dnc": 0}
    # son_deneme: başarısız denemeler de tempoya girsin; ara: zaman kutusu doldu
    durum = {"son_deneme": None, "ardisik_basarisiz": 0, "ara": False}
    baslangic = simdi_fn()

    def karar_fn(hedef: Hedef):
        ist["gorulen"] += 1
        repo.nabiz_at(conn, f"DM turu · @{hedef.handle} · gönderilen {ist['gonderildi']}",
                      platform=platform)
        if repo.bayrak_getir(conn, "master_paused", False, platform=platform):
            return TURU_BITIR
        an = simdi_fn()
        if not pacing.calisma_saatinde_mi(an, p.calisma_baslangic_saat, p.calisma_bitis_saat):
            return TURU_BITIR
        if dm_acilis_kalan(conn, ayarlar, platform) <= 0:
            return TURU_BITIR
        if durum["ardisik_basarisiz"] >= DM_ARDISIK_BASARISIZ_TAVAN:
            return TURU_BITIR
        if (an - baslangic).total_seconds() >= DM_TURU_ZAMAN_KUTUSU_SN:
            durum["ara"] = True
            return TURU_BITIR
        h = (hedef.handle or "").strip().lstrip("@")
        if not h:
            return None
        if repo.dnc_mi(conn, h, platform):
            ist["atlandi_dnc"] += 1
            return None
        if repo.yakin_zamanda_iletisim(conn, h, gun, platform=platform):
            ist["atlandi_yakin"] += 1
            return None
        lead = repo.lead_getir_platform(conn, platform, h)
        ist["secildi"] += 1
        return _acilis_metni(beyin_istemci, ayarlar, lead, rng, baglam=baglam,
                             hedef_adi=f"{hedef.ad} {h}", an=an)

    def yazmadan_once() -> bool:
        """Bir önceki DM'den (ya da başarısız denemeden) bu yana hedef aralık dolmadıysa bekle."""
        bekle = dm_acilis_araligi_sn(ayarlar, rng)
        referans = durum["son_deneme"]
        son = repo.son_dm_acilis_zamani(conn, platform)
        if son:
            try:
                basarili = datetime.fromisoformat(son)
                referans = max(referans, basarili) if referans else basarili
            except ValueError:
                pass
        if referans:
            bekle -= (datetime.now() - referans).total_seconds()
        if bekle > 0:
            repo.nabiz_at(conn, f"DM turu · tempo beklemesi {int(bekle)} sn", platform=platform)
        return uyku_fn(max(0.0, bekle))

    def sonuc_fn(hedef: Hedef, metin: str, sonuc: GonderimSonucu) -> None:
        h = (hedef.handle or "").strip().lstrip("@")
        durum["son_deneme"] = datetime.now()
        durum["ardisik_basarisiz"] = durum["ardisik_basarisiz"] + 1 \
            if sonuc == GonderimSonucu.BASARISIZ else 0
        if sonuc == GonderimSonucu.GONDERILDI:
            lead_id = repo.lead_upsert(
                conn, platform=platform, handle=h, business_name=hedef.ad or h,
                profile_url=hedef.profile_url, discovery_source=hedef.kaynak,
            )
            repo.mesaj_ekle(conn, lead_id, "dm_opener", metin, ai_generated=True)
            ist["gonderildi"] += 1
        elif sonuc == GonderimSonucu.DM_KAPALI:
            repo.dnc_ekle(conn, h, "dm_kapali", platform=platform)
            ist["kapali"] += 1
        elif sonuc == GonderimSonucu.ONCEKI_SOHBET:
            repo.dnc_ekle(conn, h, "onceki_sohbet", platform=platform)
            ist["onceki"] += 1
        else:
            ist["basarisiz"] += 1

    try:
        istemci.acilis_turu(karar_fn, sonuc_fn, yazmadan_once)
    finally:
        # Hata olsa da damgala (sıcak döngü olmasın). Zaman kutusu yüzünden ara
        # verildiyse soğuma beklemeden devam edilebilsin.
        damga = datetime.now()
        if durum["ara"]:
            damga -= timedelta(seconds=p.dm_turu_cooldown_sn)
        repo.durum_ayarla(conn, "son_dm_turu", damga.isoformat(), platform=platform)

    print(
        f"[dm] direkt DM turu{' (ara verildi)' if durum['ara'] else ''}: "
        f"gezilen={ist['gorulen']} seçildi={ist['secildi']} "
        f"gönderildi={ist['gonderildi']} dm_kapalı={ist['kapali']} önceki_sohbet={ist['onceki']} "
        f"başarısız={ist['basarisiz']} "
        f"atlandı(önceden yazılmış)={ist['atlandi_yakin']} atlandı(dnc)={ist['atlandi_dnc']} "
        f"son 1 saat={repo.son_saat_dm_acilis_sayisi(conn, platform)}"
    )
    if ist["gorulen"] == 0:
        print("[dm] ⚠️ takip listesi boş geldi — kullanıcı adı ya da liste seçicileri kontrol edilmeli")
    elif ist["gonderildi"] == 0 and (ist["basarisiz"] + ist["kapali"]) >= 3 \
            and not getattr(istemci, "engel_algilandi", False):
        print("[dm] ⚠️ hiç DM gönderilemedi — S.MESAJ_KUTUSU / yeni mesaj seçicileri ayarlanmalı olabilir")
    if ist["onceki"] >= 5 and ist["gonderildi"] == 0:
        print("[dm] ⚠️ her sohbet 'önceki yazışma var' göründü — S.MESAJ_SATIRI yanlış pozitif olabilir; "
              "düzeltip DELETE FROM dnc WHERE reason='onceki_sohbet' ile geri alın")
    return ist["gonderildi"]


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
def durum_ozeti(
    conn: sqlite3.Connection, ayarlar: Ayarlar, platform: str = "instagram"
) -> dict:
    """Kontrol paneli / log için platformun anlık durumu."""
    an = datetime.now()
    kotalar = kota_durumlari(conn, ayarlar, platform)
    master = repo.bayrak_getir(conn, "master_paused", True, platform=platform)
    checkpoint = repo.bayrak_getir(conn, "checkpoint_detected", False, platform=platform)
    engel = repo.bayrak_getir(conn, "action_block", False, platform=platform)
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
        "platform": platform,
        "master_paused": master,
        "checkpoint": checkpoint,
        "action_block": engel,
        "acilis_son_saat": repo.son_saat_acilis_sayisi(conn),
        "acilis_bugun": repo.bugun_acilis_sayisi(conn),
        "dm_aktif": repo.bayrak_getir(conn, "dm_acilis_aktif", False, platform=platform),
        "dm_son_saat": repo.son_saat_dm_acilis_sayisi(conn, platform),
        "dm_bugun": repo.bugun_dm_acilis_sayisi(conn, platform),
        "kotalar": {k.tur: {"yapilan": k.yapilan, "tavan": k.tavan, "kalan": k.kalan} for k in kotalar},
        "izinli_aksiyonlar": izinli,
    }


def engel_isaretle(conn: sqlite3.Connection, ig) -> bool:
    """Platform action-block gösterdiyse YALNIZCA o platformun botunu duraklatır.
    İşaretlendiyse True döner."""
    if not getattr(ig, "engel_algilandi", False):
        return False
    platform = getattr(ig, "platform", "instagram")
    ig.engel_algilandi = False  # panelden temizlenince yeniden başlayabilsin
    repo.durum_ayarla(conn, "action_block", "1", platform=platform)
    repo.durum_ayarla(conn, "master_paused", "1", platform=platform)
    repo.hata_kaydet(conn, f"{PLATFORM_ADI.get(platform, platform)} 'işlem engellendi' "
                           "uyarısı gösterdi — bot duraklatıldı", platform=platform)
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
    Bayraklar, kotalar ve nabız istemcinin platformuna aittir; gelen mesaja
    yanıt (RESPOND) yalnızca Instagram'da, hikaye turu yalnızca hikaye
    yanıtlayabilen istemcide yapılır.
    """
    platform = getattr(ig, "platform", "instagram")
    an = datetime.now()
    kotalar = kota_durumlari(conn, ayarlar, platform)
    izinli = pacing.izin_verilen_aksiyonlar(
        an,
        ayarlar.pacing.calisma_baslangic_saat,
        ayarlar.pacing.calisma_bitis_saat,
        kotalar,
        master_duraklatildi=repo.bayrak_getir(conn, "master_paused", True, platform=platform),
        checkpoint_var=(
            repo.bayrak_getir(conn, "checkpoint_detected", False, platform=platform)
            or repo.bayrak_getir(conn, "action_block", False, platform=platform)
        ),
    )
    yanitlar = repo.yanit_bekleyen_threadler(conn, limit=1) if platform == "instagram" else []
    yanit_var = bool(yanitlar)
    # Açılış kaynağı artık hikaye tepsisi; soğuma süresi geçtiyse tur yapılabilir
    acilis_var = hasattr(ig, "hikayeleri_yanitla") and _hikaye_turu_zamani(
        conn, ayarlar.pacing.hikaye_turu_cooldown_sn
    )
    dm_var = hasattr(ig, "acilis_turu") and _tur_zamani(
        conn, anahtar(platform, "son_dm_turu"), ayarlar.pacing.dm_turu_cooldown_sn
    )
    gorev = sonraki_gorev(izinli, yanit_var, acilis_var, dm_var)
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
    elif gorev == DIRECT_DM:
        repo.nabiz_at(conn, "direkt DM turu başlıyor", platform=platform)
        direkt_dm_turu_yap(conn, ayarlar, ig, beyin_istemci, rng)
    elif gorev == DISCOVER:
        repo.nabiz_at(conn, "hashtag keşfi")
        _kesif_turu(conn, ayarlar, ig)

    if engel_isaretle(conn, ig):
        return gorev
    repo.nabiz_at(conn, f"{gorev} bitti · insan beklemesi", platform=platform)
    _bekle(conn, rng, ayarlar, platform)
    return gorev


# Sabit açılış metinlerini hedefe uydurma: bu kelimeleri içeren metin yalnızca adı /
# kullanıcı adı sektör kelimesi içeren işletmeye gider (ör. "Halı teslim…" → halıcıya)
SEKTOR_METIN_KELIMELERI = ("halı", "koltuk")
SEKTOR_HEDEF_KELIMELERI = ("hali", "halı", "koltuk", "yikama", "yıkama", "temizlik", "carpet")
# Selamlaşma → geçerli olduğu saat aralığı [başlangıç, bitiş)
SELAM_SAATLERI = {"günaydın": (0, 12), "iyi akşamlar": (17, 24), "iyi geceler": (21, 24)}


def _tr_kucuk(metin: str) -> str:
    """Türkçe küçük harf (İ→i, I→ı); str.lower 'İ'yi 'i̇' yapar."""
    return (metin or "").replace("İ", "i").replace("I", "ı").lower()


def uygun_acilis_metinleri(satirlar: list[str], hedef_adi: str, an: datetime) -> list[str]:
    """Hedefe ve saate uymayan sabit metinleri eler (GPT yokken "uygun olanı" seçmek için)."""
    hedef = _tr_kucuk(hedef_adi)
    sektorde = any(k in hedef for k in SEKTOR_HEDEF_KELIMELERI)
    uygun = []
    for satir in satirlar:
        kucuk = _tr_kucuk(satir)
        if not sektorde and any(k in kucuk for k in SEKTOR_METIN_KELIMELERI):
            continue
        if any(selam in kucuk and not (bas <= an.hour < bit)
               for selam, (bas, bit) in SELAM_SAATLERI.items()):
            continue
        uygun.append(satir)
    return uygun


def _acilis_metni(
    beyin_istemci,
    ayarlar,
    lead,
    rng: Optional[random.Random] = None,
    baglam: str = "hikaye",
    hedef_adi: str = "",
    an: Optional[datetime] = None,
) -> str:
    """Açılış metni (`baglam`: "hikaye" = hikaye yanıtı, "dm" / "tiktok_dm" = direkt DM).

    "sabit" modda panelde girilen satırlardan hedefe ve saate UYGUN olanlardan
    rastgele biri (bkz. `uygun_acilis_metinleri`); uygun satır yoksa ya da mod
    "gpt" ise beyin varsa GPT ile çeşitlendirilmiş metin, yoksa güvenli sabit.
    """
    if getattr(ayarlar, "acilis_modu", "gpt") == "sabit":
        satirlar = [x.strip() for x in (ayarlar.acilis_metinleri or "").splitlines() if x.strip()]
        if not hedef_adi and lead is not None:
            try:
                hedef_adi = f"{lead['business_name'] or ''} {lead['ig_handle'] or ''}"
            except (KeyError, IndexError, TypeError):
                pass
        uygun = uygun_acilis_metinleri(satirlar, hedef_adi, an or datetime.now())
        if uygun:
            return (rng or random).choice(uygun)
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


def _bekle(conn, rng, ayarlar, platform: str = "instagram") -> None:
    sn = pacing.insan_beklemesi_sn(
        rng, ayarlar.pacing.aksiyon_bekleme_min, ayarlar.pacing.aksiyon_bekleme_max
    )
    uyku(conn, sn, platform=platform)
