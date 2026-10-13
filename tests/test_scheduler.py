"""scheduler.py saf/enjekte-edilebilir mantık testleri."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from ig_agent import brain, db, repository as repo, scheduler as sch
from ig_agent.config import Ayarlar
from ig_agent.instagram import TURU_BITIR


# --------------------------------------------------------------------------- #
# sonraki_gorev önceliği
# --------------------------------------------------------------------------- #
class TestSonrakiGorev:
    def test_yanit_oncelikli(self):
        izinli = [sch.RESPOND, sch.OPENER, sch.DISCOVER]
        assert sch.sonraki_gorev(izinli, yanit_var=True, acilis_var=True) == sch.RESPOND

    def test_yanit_yoksa_acilis(self):
        izinli = [sch.RESPOND, sch.OPENER, sch.DISCOVER]
        assert sch.sonraki_gorev(izinli, yanit_var=False, acilis_var=True) == sch.OPENER

    def test_sadece_kesif(self):
        assert sch.sonraki_gorev([sch.DISCOVER], False, False) == sch.DISCOVER

    def test_kota_yoksa_gorev_yok(self):
        # respond izinli değil (kota dolu) ve açılış izinli değil → keşfe düşer yoksa None
        assert sch.sonraki_gorev([], True, True) is None

    def test_respond_kota_dolu_acilisa_gecer(self):
        assert sch.sonraki_gorev([sch.OPENER], yanit_var=True, acilis_var=True) == sch.OPENER

    def test_hikaye_dm_den_once(self):
        izinli = [sch.OPENER, sch.DIRECT_DM, sch.DISCOVER]
        assert sch.sonraki_gorev(izinli, False, acilis_var=True, dm_var=True) == sch.OPENER

    def test_hikaye_sogumadaysa_dm(self):
        izinli = [sch.OPENER, sch.DIRECT_DM, sch.DISCOVER]
        assert sch.sonraki_gorev(izinli, False, acilis_var=False, dm_var=True) == sch.DIRECT_DM

    def test_dm_kesiften_once(self):
        assert sch.sonraki_gorev([sch.DIRECT_DM, sch.DISCOVER], False, False, True) == sch.DIRECT_DM


# --------------------------------------------------------------------------- #
# karari_uygula
# --------------------------------------------------------------------------- #
class SahteIG:
    def __init__(self, basarili=True):
        self.basarili = basarili
        self.gonderilen = []

    def dm_gonder(self, handle, metin):
        self.gonderilen.append((handle, metin))
        return self.basarili

    def hikaye_yaniti_gonder(self, handle, metin):
        self.gonderilen.append(("story:" + handle, metin))
        return self.basarili


class SahteBildirim:
    def __init__(self):
        self.cagrilar = []

    def sicak_lead_bildir(self, lead, karar):
        self.cagrilar.append((int(lead["id"]), karar.action))
        return True


@pytest.fixture
def ortam(tmp_path):
    ayarlar = Ayarlar(veritabani_yolu=str(tmp_path / "t.db"))
    conn = db.hazirla(ayarlar)
    lid = repo.ig_lead_upsert(conn, ig_handle="soz", business_name="Sözeri")
    repo.mesaj_ekle(conn, lid, "inbound", "olur bakalım")
    lead = repo.lead_getir(conn, lid)
    yield conn, ayarlar, lead
    conn.close()


def test_yaz_basarili(ortam):
    conn, ayarlar, lead = ortam
    ig, bildirim = SahteIG(), SahteBildirim()
    karar = brain.AjanKarari(action=brain.YAZ, text="Kısaca anlatayım", stage="demo_atildi")
    assert sch.karari_uygula(conn, ayarlar, lead, karar, ig, bildirim) is True
    assert ig.gonderilen == [("soz", "Kısaca anlatayım")]
    msgs = repo.thread_mesajlari(conn, int(lead["id"]))
    assert msgs[-1]["direction"] == "outbound" and msgs[-1]["ai_generated"] == 1
    assert repo.lead_getir(conn, int(lead["id"]))["stage"] == "demo_atildi"


def test_yaz_gonderim_basarisiz_db_yazmaz(ortam):
    conn, ayarlar, lead = ortam
    ig, bildirim = SahteIG(basarili=False), SahteBildirim()
    karar = brain.AjanKarari(action=brain.YAZ, text="deneme")
    assert sch.karari_uygula(conn, ayarlar, lead, karar, ig, bildirim) is False
    # outbound mesaj yazılmamalı (sadece ilk inbound var)
    msgs = repo.thread_mesajlari(conn, int(lead["id"]))
    assert all(m["direction"] != "outbound" for m in msgs)


def test_deneme_bildirim_ve_asama(ortam):
    conn, ayarlar, lead = ortam
    ig, bildirim = SahteIG(), SahteBildirim()
    karar = brain.AjanKarari(action=brain.DENEME, text="kaydınızı açalım", phone="0543609...")
    assert sch.karari_uygula(conn, ayarlar, lead, karar, ig, bildirim) is True
    assert bildirim.cagrilar == [(int(lead["id"]), brain.DENEME)]
    assert repo.lead_getir(conn, int(lead["id"]))["stage"] == "deneme"
    olaylar = conn.execute("SELECT * FROM sales_events WHERE type='trial_proposed'").fetchall()
    assert len(olaylar) == 1 and olaylar[0]["phone"] == "0543609..."


def test_devret_ai_kapatir(ortam):
    conn, ayarlar, lead = ortam
    ig, bildirim = SahteIG(), SahteBildirim()
    karar = brain.AjanKarari(action=brain.DEVRET, reason="fiyat pazarlığı", text="Hemen ilgili arkadaşa aktarıyorum")
    assert sch.karari_uygula(conn, ayarlar, lead, karar, ig, bildirim) is True
    assert repo.lead_getir(conn, int(lead["id"]))["ai_enabled"] == 0
    assert repo.yanit_bekleyen_threadler(conn) == []  # artık AI cevaplamaz
    assert bildirim.cagrilar and bildirim.cagrilar[0][1] == brain.DEVRET


def test_kes_dnc_ve_kayip(ortam):
    conn, ayarlar, lead = ortam
    ig, bildirim = SahteIG(), SahteBildirim()
    karar = brain.AjanKarari(action=brain.KES, reason="rahatsız etmeyin dedi", outcome="ilgisiz")
    assert sch.karari_uygula(conn, ayarlar, lead, karar, ig, bildirim) is True
    l = repo.lead_getir(conn, int(lead["id"]))
    assert l["stage"] == "kayip" and l["do_not_contact"] == 1
    assert repo.dnc_handle_mi(conn, "soz")


def test_whatsapp_yonlendirme_olayi(ortam):
    conn, ayarlar, lead = ortam
    ig, bildirim = SahteIG(), SahteBildirim()
    karar = brain.AjanKarari(action=brain.WHATSAPP, text="WhatsApp: 0555...")
    assert sch.karari_uygula(conn, ayarlar, lead, karar, ig, bildirim) is True
    olaylar = conn.execute("SELECT * FROM sales_events WHERE type='redirected_whatsapp'").fetchall()
    assert len(olaylar) == 1


def test_takip(ortam):
    conn, ayarlar, lead = ortam
    ig, bildirim = SahteIG(), SahteBildirim()
    karar = brain.AjanKarari(action=brain.TAKIP, follow_up="öğleden sonra", text="Tabii, sonra yazayım")
    assert sch.karari_uygula(conn, ayarlar, lead, karar, ig, bildirim) is True
    assert repo.lead_getir(conn, int(lead["id"]))["outcome"] == "tekrar_ara"


# --------------------------------------------------------------------------- #
# kota
# --------------------------------------------------------------------------- #
def test_kota_durumlari_turleri(ortam):
    conn, ayarlar, lead = ortam
    kotalar = {k.tur for k in sch.kota_durumlari(conn, ayarlar)}
    assert kotalar == {sch.RESPOND, sch.OPENER, sch.DIRECT_DM, sch.DISCOVER}


def test_kesif_varsayilan_kapali_tavan_sifir(ortam):
    conn, ayarlar, lead = ortam
    kotalar = {k.tur: k for k in sch.kota_durumlari(conn, ayarlar)}
    assert kotalar[sch.DISCOVER].tavan == 0  # kesif_aktif=False → keşif kapalı
    repo.durum_ayarla(conn, "kesif_aktif", "1")
    kotalar2 = {k.tur: k for k in sch.kota_durumlari(conn, ayarlar)}
    assert kotalar2[sch.DISCOVER].tavan > 0


# --------------------------------------------------------------------------- #
# hikaye_turu_yap (story tepsisi açılışı)
# --------------------------------------------------------------------------- #
class SahteHikayeIG:
    """Tepsideki her handle için karar_fn'i çağırır; metin dönerse gönderir."""

    def __init__(self, tray, engel_sonra=None):
        self.tray = tray
        self.engel_sonra = engel_sonra  # bu kadar gönderimden sonra action block
        self.engel_algilandi = False
        self.gonderilen = []

    def hikayeleri_yanitla(self, karar_fn, sonuc_fn=None, yazmadan_once=None, max_adim=5000):
        sonuc = []
        for h in self.tray:
            metin = karar_fn(h)
            if metin == TURU_BITIR:
                break
            if not metin:
                continue
            if yazmadan_once and not yazmadan_once():
                break
            self.gonderilen.append(h)
            sonuc.append({"handle": h, "sent": metin})
            if sonuc_fn:
                sonuc_fn(h, metin)
            if self.engel_sonra is not None and len(self.gonderilen) >= self.engel_sonra:
                self.engel_algilandi = True
                break
        return sonuc


OGLEN = lambda: datetime(2026, 9, 24, 12, 0)  # noqa: E731 — çalışma saati içi


def _tur(conn, ayarlar, ig, **kw):
    kw.setdefault("uyku_fn", lambda sn: True)
    kw.setdefault("simdi_fn", OGLEN)
    return sch.hikaye_turu_yap(conn, ayarlar, ig, object(), **kw)  # object → sabit açılış


def test_hikaye_turu_yeni_hedeflere_acilis(ortam):
    conn, ayarlar, lead = ortam

    # 'zaten' hesabına daha önce açılış yapılmış → atlanmalı
    lid = repo.ig_lead_upsert(conn, ig_handle="zaten", business_name="Z")
    repo.mesaj_ekle(conn, lid, "story_reply", "önceki açılış")

    # 'dncli' do-not-contact → atlanmalı
    dlid = repo.ig_lead_upsert(conn, ig_handle="dncli", business_name="D")
    repo.do_not_contact_isaretle(conn, dlid, reason="x")

    ig = SahteHikayeIG(tray=["yeni1", "zaten", "dncli", "yeni2"])
    assert _tur(conn, ayarlar, ig) == 2
    assert ig.gonderilen == ["yeni1", "yeni2"]
    for h in ("yeni1", "yeni2"):
        l = repo.lead_getir_handle(conn, h)
        assert l is not None and l["last_story_reply_at"] is not None
    # son_hikaye_turu damgası set edildi → cooldown başladı
    assert not sch._hikaye_turu_zamani(conn, cooldown=3600)


def test_hikaye_turu_tum_tepsiyi_gezer(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.pacing.acilis_saatlik = 0  # sınırsız
    tray = [f"h{i}" for i in range(150)]
    assert _tur(conn, ayarlar, SahteHikayeIG(tray)) == 150


def test_hikaye_turu_saatlik_tavanda_durur(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.pacing.acilis_saatlik = 3
    assert _tur(conn, ayarlar, SahteHikayeIG(["a1", "a2", "a3", "a4", "a5"])) == 3
    assert sch.acilis_kalan(conn, ayarlar) == 0
    # kota doluyken yeni tur hiç gezmez
    assert _tur(conn, ayarlar, SahteHikayeIG(["b1"])) == 0


def test_hikaye_turu_gunluk_tavan(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.pacing.acilis_saatlik = 100
    ayarlar.pacing.acilis_gunluk = 2
    assert _tur(conn, ayarlar, SahteHikayeIG(["a1", "a2", "a3"])) == 2


def test_hikaye_turu_duraklatilinca_biter(ortam):
    conn, ayarlar, lead = ortam
    repo.durum_ayarla(conn, "master_paused", "1")
    ig = SahteHikayeIG(["a1", "a2"])
    assert _tur(conn, ayarlar, ig) == 0 and ig.gonderilen == []


def test_hikaye_turu_calisma_saati_disinda_biter(ortam):
    conn, ayarlar, lead = ortam
    ig = SahteHikayeIG(["a1"])
    assert _tur(conn, ayarlar, ig, simdi_fn=lambda: datetime(2026, 9, 24, 23, 0)) == 0


def test_tempo_beklemesi_durdurursa_gondermez(ortam):
    conn, ayarlar, lead = ortam
    ig = SahteHikayeIG(["a1", "a2"])
    assert _tur(conn, ayarlar, ig, uyku_fn=lambda sn: False) == 0


def test_tempo_beklemesi_saatlik_tavana_gore(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.pacing.acilis_saatlik = 60  # dakikada bir
    beklemeler = []
    _tur(conn, ayarlar, SahteHikayeIG(["a1", "a2"]),
         uyku_fn=lambda sn: beklemeler.append(sn) or True)
    # ikinci gönderim, birinciden hemen sonra → ~60 sn (±%30) beklemeli
    assert 40 <= beklemeler[1] <= 80


def test_action_block_duraklatir(ortam):
    conn, ayarlar, lead = ortam
    ig = SahteHikayeIG(["a1", "a2", "a3"], engel_sonra=1)
    assert _tur(conn, ayarlar, ig) == 1
    assert sch.engel_isaretle(conn, ig) is True
    assert repo.bayrak_getir(conn, "master_paused") is True
    assert repo.bayrak_getir(conn, "action_block") is True
    assert ig.engel_algilandi is False  # bir sonraki başlatma için sıfırlandı
    assert sch.durum_ozeti(conn, ayarlar)["izinli_aksiyonlar"] == []


def test_sabit_acilis_metinleri(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.acilis_modu = "sabit"
    ayarlar.acilis_metinleri = "Selam A\n\nSelam B\n"
    for _ in range(10):
        assert sch._acilis_metni(object(), ayarlar, None) in ("Selam A", "Selam B")


# --------------------------------------------------------------------------- #
# yanıt kuyruğu: aynı gelen mesaja sonsuz döngü olmamalı
# --------------------------------------------------------------------------- #
def test_islenen_mesaj_tekrar_kuyruga_girmez(ortam):
    conn, ayarlar, lead = ortam
    lid = int(lead["id"])
    assert [r["id"] for r in repo.yanit_bekleyen_threadler(conn)] == [lid]
    repo.islendi_isaretle(conn, lid)  # ör. metinsiz takip / gönderim başarısız
    assert repo.yanit_bekleyen_threadler(conn) == []
    repo.mesaj_ekle(conn, lid, "inbound", "yeni soru")
    assert [r["id"] for r in repo.yanit_bekleyen_threadler(conn)] == [lid]


def test_sifir_gun_eski_iletisime_asla_tekrar_yazmaz(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.yeniden_iletisim_gun = 0
    eski = repo.ig_lead_upsert(conn, ig_handle="eski", business_name="E")
    repo.mesaj_ekle(conn, eski, "story_reply", "Kolay gelsin")
    conn.execute("UPDATE ig_messages SET sent_at = '2025-01-01 10:00:00' WHERE lead_id = ?", (eski,))
    conn.commit()
    ig = SahteHikayeIG(["eski", "yepyeni"])
    assert _tur(conn, ayarlar, ig) == 1 and ig.gonderilen == ["yepyeni"]


def test_gun_verilirse_sure_dolunca_tekrar_yazar(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.yeniden_iletisim_gun = 30
    eski = repo.ig_lead_upsert(conn, ig_handle="eski", business_name="E")
    repo.mesaj_ekle(conn, eski, "story_reply", "Kolay gelsin")
    conn.execute("UPDATE ig_messages SET sent_at = '2025-01-01 10:00:00' WHERE lead_id = ?", (eski,))
    conn.commit()
    assert _tur(conn, ayarlar, SahteHikayeIG(["eski"])) == 1


def test_bize_yazmis_hesaba_acilis_yapilmaz(ortam):
    conn, ayarlar, lead = ortam
    # fixture'daki 'soz' hesabı bize yazmış (inbound) ama biz hiç yazmamışız
    ig = SahteHikayeIG(["soz"])
    assert _tur(conn, ayarlar, ig) == 0


def test_acilis_metni_baglami_beyne_iletir(ortam):
    conn, ayarlar, lead = ortam

    class SahteBeyin:
        def __init__(self):
            self.baglamlar = []

        def acilis_uret(self, ayarlar, lead, baglam="hikaye"):
            self.baglamlar.append(baglam)
            return f"metin-{baglam}"

    beyin = SahteBeyin()
    assert sch._acilis_metni(beyin, ayarlar, None) == "metin-hikaye"
    assert sch._acilis_metni(beyin, ayarlar, None, baglam="dm") == "metin-dm"
    assert beyin.baglamlar == ["hikaye", "dm"]


def test_turu_bitir_tek_kaynak():
    from ig_agent import instagram, platformlar

    assert instagram.TURU_BITIR is platformlar.TURU_BITIR


# --------------------------------------------------------------------------- #
# direkt_dm_turu_yap (takip listesinden DM açılışı)
# --------------------------------------------------------------------------- #
from ig_agent.platformlar import GonderimSonucu, Hedef  # noqa: E402


class SahteDMIstemci:
    """Hedef listesini gezer; sonuçlar handle bazında ayarlanabilir."""

    platform = "instagram"

    def __init__(self, handles, sonuclar=None, engel_sonra=None):
        self.hedefler = [Hedef(handle=h, kaynak="takip_listesi") for h in handles]
        self.sonuclar = sonuclar or {}
        self.engel_sonra = engel_sonra
        self.engel_algilandi = False
        self.gonderilen = []

    def acilis_turu(self, karar_fn, sonuc_fn, yazmadan_once):
        for hedef in self.hedefler:
            metin = karar_fn(hedef)
            if metin == TURU_BITIR:
                break
            if not metin:
                continue
            if not yazmadan_once():
                break
            sonuc = self.sonuclar.get(hedef.handle, GonderimSonucu.GONDERILDI)
            if sonuc == GonderimSonucu.GONDERILDI:
                self.gonderilen.append(hedef.handle)
            sonuc_fn(hedef, metin, sonuc)
            if self.engel_sonra is not None and len(self.gonderilen) >= self.engel_sonra:
                self.engel_algilandi = True
                break


def _dm_turu(conn, ayarlar, istemci, **kw):
    kw.setdefault("uyku_fn", lambda sn: True)
    kw.setdefault("simdi_fn", OGLEN)
    return sch.direkt_dm_turu_yap(conn, ayarlar, istemci, object(), **kw)


def test_dm_turu_yeni_hedeflere_yazar(ortam):
    conn, ayarlar, lead = ortam
    hik = repo.ig_lead_upsert(conn, ig_handle="hikayeli", business_name="H")
    repo.mesaj_ekle(conn, hik, "story_reply", "önceki")
    repo.dnc_ekle(conn, "dncli", "x")

    ist = SahteDMIstemci(["yeni1", "hikayeli", "dncli", "@yeni2 "])
    assert _dm_turu(conn, ayarlar, ist) == 2
    for h in ("yeni1", "yeni2"):
        l = repo.lead_getir_platform(conn, "instagram", h)
        assert l["discovery_source"] == "takip_listesi" and l["stage"] == "ilk_temas"
        msjlar = repo.thread_mesajlari(conn, int(l["id"]))
        assert [m["direction"] for m in msjlar] == ["dm_opener"]
    assert repo.durum_getir(conn, "son_dm_turu")  # soğuma başladı


def test_dm_kapali_dnc_ye_eklenir_ve_tekrar_denenmez(ortam):
    conn, ayarlar, lead = ortam
    ist = SahteDMIstemci(["kapali"], sonuclar={"kapali": GonderimSonucu.DM_KAPALI})
    assert _dm_turu(conn, ayarlar, ist) == 0
    assert repo.dnc_mi(conn, "kapali")
    assert repo.dnc_listesi(conn)[0]["reason"] == "dm_kapali"
    assert repo.lead_getir_platform(conn, "instagram", "kapali") is None

    secilen = []
    ist2 = SahteDMIstemci(["kapali"])
    ist2.acilis_turu = lambda k, s, y: secilen.append(k(ist2.hedefler[0]))
    _dm_turu(conn, ayarlar, ist2)
    assert secilen == [None]


def test_dm_basarisiz_kayit_birakmaz_sonra_tekrar_denenir(ortam):
    conn, ayarlar, lead = ortam
    ist = SahteDMIstemci(["gecici"], sonuclar={"gecici": GonderimSonucu.BASARISIZ})
    assert _dm_turu(conn, ayarlar, ist) == 0
    assert not repo.dnc_mi(conn, "gecici")
    assert repo.lead_getir_platform(conn, "instagram", "gecici") is None
    assert _dm_turu(conn, ayarlar, SahteDMIstemci(["gecici"])) == 1


def test_dm_turu_saatlik_tavanda_durur_ve_kaldigi_yerden_devam(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.pacing.dm_acilis_saatlik = 2
    assert _dm_turu(conn, ayarlar, SahteDMIstemci(["a", "b", "c"])) == 2
    assert sch.dm_acilis_kalan(conn, ayarlar) == 0
    ayarlar.pacing.dm_acilis_saatlik = 10
    ist = SahteDMIstemci(["a", "b", "c"])
    assert _dm_turu(conn, ayarlar, ist) == 1
    assert ist.gonderilen == ["c"]


def test_dm_ve_hikaye_kotalari_bagimsiz(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.pacing.acilis_saatlik = 1
    ayarlar.pacing.dm_acilis_saatlik = 1
    assert _tur(conn, ayarlar, SahteHikayeIG(["h1"])) == 1
    assert sch.acilis_kalan(conn, ayarlar) == 0
    assert _dm_turu(conn, ayarlar, SahteDMIstemci(["d1"])) == 1  # hikaye kotası DM'i durdurmaz
    assert sch.dm_acilis_kalan(conn, ayarlar) == 0
    ayarlar.pacing.acilis_saatlik = 5
    assert _tur(conn, ayarlar, SahteHikayeIG(["h2"])) == 1  # DM kotası hikayeyi durdurmaz


def test_dm_atilan_hesaba_hikaye_yaniti_atilmaz_ve_tersi(ortam):
    conn, ayarlar, lead = ortam
    _dm_turu(conn, ayarlar, SahteDMIstemci(["ortak1"]))
    hik = SahteHikayeIG(["ortak1"])
    assert _tur(conn, ayarlar, hik) == 0
    _tur(conn, ayarlar, SahteHikayeIG(["ortak2"]))
    ist = SahteDMIstemci(["ortak2"])
    assert _dm_turu(conn, ayarlar, ist) == 0 and ist.gonderilen == []


def test_dm_turu_bos_liste_soguma_baslatir(ortam):
    conn, ayarlar, lead = ortam
    assert _dm_turu(conn, ayarlar, SahteDMIstemci([])) == 0
    assert not sch._tur_zamani(conn, "son_dm_turu", 3600)


def test_dm_turu_duraklatilinca_ve_mesai_disinda_biter(ortam):
    conn, ayarlar, lead = ortam
    repo.durum_ayarla(conn, "master_paused", "1")
    assert _dm_turu(conn, ayarlar, SahteDMIstemci(["a1"])) == 0
    repo.durum_ayarla(conn, "master_paused", "0")
    gece = lambda: datetime(2026, 9, 24, 23, 0)  # noqa: E731
    assert _dm_turu(conn, ayarlar, SahteDMIstemci(["a1"]), simdi_fn=gece) == 0


def test_dm_tempo_beklemesi_saatlik_tavana_gore(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.pacing.dm_acilis_saatlik = 10  # ~360 sn ± %30
    beklemeler = []
    _dm_turu(conn, ayarlar, SahteDMIstemci(["a1"]),
             uyku_fn=lambda sn: beklemeler.append(sn) or True)
    assert len(beklemeler) == 1 and 252 <= beklemeler[0] <= 468


def test_dm_kotasi_bayrak_kapaliyken_sifir(ortam):
    conn, ayarlar, lead = ortam
    k = {x.tur: x for x in sch.kota_durumlari(conn, ayarlar)}
    assert k[sch.DIRECT_DM].tavan == 0
    repo.durum_ayarla(conn, "dm_acilis_aktif", "1")
    k = {x.tur: x for x in sch.kota_durumlari(conn, ayarlar)}
    assert k[sch.DIRECT_DM].musait


# --- final inceleme düzeltmeleri ------------------------------------------- #
def test_basarisiz_denemeler_de_tempolanir_ve_art_arda_5te_durur(ortam):
    conn, ayarlar, lead = ortam
    ayarlar.pacing.dm_acilis_saatlik = 10
    # 2 saat önceki başarılı DM: tempo artık ona göre sıfır olmamalı
    eski = repo.lead_upsert(conn, platform="instagram", handle="eski")
    repo.mesaj_ekle(conn, eski, "dm_opener", "eski")
    conn.execute("UPDATE ig_messages SET sent_at = datetime('now','localtime','-2 hours')")
    conn.commit()
    hedefler = [f"k{i}" for i in range(20)]
    ist = SahteDMIstemci(hedefler, sonuclar={h: GonderimSonucu.BASARISIZ for h in hedefler})
    denemeler = []
    orijinal = ist.acilis_turu

    def say(karar_fn, sonuc_fn, yazmadan_once):
        def sonuc_say(h, m, s):
            denemeler.append(h.handle)
            sonuc_fn(h, m, s)
        orijinal(karar_fn, sonuc_say, yazmadan_once)

    ist.acilis_turu = say
    beklemeler = []
    _dm_turu(conn, ayarlar, ist, uyku_fn=lambda sn: beklemeler.append(sn) or True)
    assert len(denemeler) == 5  # art arda 5 BASARISIZ → tur biter
    assert all(b > 0 for b in beklemeler[1:])  # başarısızlar arasında da tempo var


def test_dm_turu_zaman_kutusunda_ara_verir_ve_hemen_devam_edilebilir(ortam):
    conn, ayarlar, lead = ortam
    saatler = iter([datetime(2026, 9, 24, 12, 0) + __import__("datetime").timedelta(minutes=6 * i)
                    for i in range(50)])
    ist = SahteDMIstemci(["a", "b", "c", "d"])
    assert _dm_turu(conn, ayarlar, ist, simdi_fn=lambda: next(saatler)) == 2
    # Ara verildi (bitmedi) → DM turu soğumasız tekrar başlayabilir
    assert sch._tur_zamani(conn, "son_dm_turu", ayarlar.pacing.dm_turu_cooldown_sn)


def test_dm_turu_hata_verse_de_soguma_damgalanir(ortam, monkeypatch):
    conn, ayarlar, lead = ortam

    def patla(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(repo, "lead_upsert", patla)
    with pytest.raises(sqlite3.OperationalError):
        _dm_turu(conn, ayarlar, SahteDMIstemci(["a"]))
    assert not sch._tur_zamani(conn, "son_dm_turu", 3600)


def test_onceki_sohbet_dnc_ye_eklenir_gonderilmis_sayilmaz(ortam):
    conn, ayarlar, lead = ortam
    ist = SahteDMIstemci(["musteri", "yeni"], sonuclar={"musteri": GonderimSonucu.ONCEKI_SOHBET})
    assert _dm_turu(conn, ayarlar, ist) == 1
    assert repo.dnc_mi(conn, "musteri")
    assert {d["handle"]: d["reason"] for d in repo.dnc_listesi(conn)}["musteri"] == "onceki_sohbet"
