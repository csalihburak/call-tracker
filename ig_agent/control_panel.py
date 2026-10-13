"""Satış ajanı — kontrol paneli (Streamlit).

Üstteki seçiciyle platform (Instagram / TikTok) seçilir; her platformun botu
ayrı bir süreçtir ve buradan ayrı başlatılır/kapatılır. Canlı durum her 5
saniyede yenilenir. Ayarlar sekmesindeki değişiklikler bot yeniden
başlatılmadan bir sonraki turda uygulanır.

Çalıştırma:
    ./baslat.sh
    (ya da: .venv/bin/python3.12 -m streamlit run ig_agent/control_panel.py)
"""

from __future__ import annotations

import os
import sys

import streamlit as st

# `streamlit run ig_agent/control_panel.py` sys.path'e ig_agent/ klasörünü ekler,
# üst dizini değil. `import ig_agent`in çalışması için kökü (call-tracker/) ekle.
_KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _KOK not in sys.path:
    sys.path.insert(0, _KOK)

from ig_agent import canli_ayarlar, db, repository as repo, scheduler as sch, surec  # noqa: E402
from ig_agent.config import ayarlari_yukle  # noqa: E402
from ig_agent.platformlar import DESTEKLENEN_PLATFORMLAR, PLATFORM_ADI  # noqa: E402

st.set_page_config(page_title="Satış ajanı — kontrol", page_icon=":material/smartphone:", layout="wide")


@st.cache_resource
def _kaynaklar():
    temel = ayarlari_yukle()
    # Streamlit rerun'ları farklı thread'lerde çalışır; cache'lenen bağlantı
    # thread'ler arası kullanılacağından check_same_thread=False gerekir.
    conn = db.hazirla(temel, check_same_thread=False)
    return temel, conn


@st.cache_resource
def _temel_ayarlar(platform: str):
    """Platformun `.env` tabanlı ayarları (canlı ayarlar bunun üstüne bindirilir)."""
    return ayarlari_yukle(platform)


_, conn = _kaynaklar()


def _ayarlar(platform: str):
    return canli_ayarlar.uygula(conn, _temel_ayarlar(platform))


def _bayrak_yaz(anahtar: str, deger: bool, platform: str) -> None:
    repo.durum_ayarla(conn, anahtar, "1" if deger else "0", platform=platform)


# --------------------------------------------------------------------------- #
# Buton geri çağrıları (durum, fragment yeniden çizilmeden önce yazılır)
# --------------------------------------------------------------------------- #
def _baslat(platform: str) -> None:
    _bayrak_yaz("master_paused", False, platform)
    surec.baslat(conn, platform=platform)


def _duraklat(platform: str) -> None:
    _bayrak_yaz("master_paused", True, platform)


def _kapat(platform: str) -> None:
    _bayrak_yaz("master_paused", True, platform)
    surec.durdur(conn, platform=platform)


def _hikaye_turu_simdi() -> None:
    repo.durum_ayarla(conn, "son_hikaye_turu", "")


def _dm_turu_simdi(platform: str) -> None:
    repo.durum_ayarla(conn, "son_dm_turu", "", platform=platform)


def _engeli_temizle(platform: str) -> None:
    _bayrak_yaz("action_block", False, platform)
    _bayrak_yaz("checkpoint_detected", False, platform)


def _sure_metni(sn) -> str:
    if sn is None:
        return "hiç"
    sn = int(sn)
    if sn < 60:
        return f"{sn} sn önce"
    if sn < 3600:
        return f"{sn // 60} dk önce"
    return f"{sn // 3600} sa önce"


def _bugun_acilis(platform: str) -> int:
    """Bugün gönderilen açılış: IG'de hikaye yanıtı + direkt DM, diğerlerinde direkt DM."""
    n = repo.bugun_dm_acilis_sayisi(conn, platform)
    return n + repo.bugun_acilis_sayisi(conn) if platform == "instagram" else n


def _platform_ozet_satiri() -> str:
    """Tüm platformların tek satırlık durumu (açık/duraklatılmış/kapalı + bugünkü açılış)."""
    parcalar = []
    for p in DESTEKLENEN_PLATFORMLAR:
        s = surec.durum(conn, platform=p)
        if not s["surec_var"]:
            hal = ":material/power_off: kapalı"
        elif repo.bayrak_getir(conn, "master_paused", True, platform=p):
            hal = ":material/pause_circle: duraklatılmış"
        else:
            hal = ":material/play_circle: çalışıyor"
        parcalar.append(f"**{PLATFORM_ADI[p]}** {hal} · bugün {_bugun_acilis(p)} açılış")
    return "  |  ".join(parcalar)


# --------------------------------------------------------------------------- #
# Platform seçici + canlı durum (5 sn'de bir kendini yeniler)
# --------------------------------------------------------------------------- #
st.title("Satış ajanı")
platform = st.segmented_control(
    "Platform", options=list(DESTEKLENEN_PLATFORMLAR), format_func=PLATFORM_ADI.get,
    default="instagram", required=True, key="platform",
)
AD = PLATFORM_ADI[platform]
IG = platform == "instagram"


@st.fragment(run_every="5s")
def canli_durum(platform: str) -> None:
    st.caption(_platform_ozet_satiri())
    ayarlar = _ayarlar(platform)
    ozet = sch.durum_ozeti(conn, ayarlar, platform)
    s = surec.durum(conn, platform=platform)
    duraklatildi = ozet["master_paused"]

    with st.container(border=True):
        sol, sag = st.columns([3, 2])
        with sol:
            if not s["surec_var"]:
                st.error(f"**{AD} botu kapalı.** Çalıştırmak için *Başlat*'a basın.",
                         icon=":material/power_off:")
            elif not s["canli"]:
                st.warning(
                    f"**Bot yanıt vermiyor** (son sinyal {_sure_metni(s['nabiz_yasi_sn'])}). "
                    "Uzun süren bir sayfa yüklemesi olabilir; düzelmezse *Botu kapat* → *Başlat*.",
                    icon=":material/hourglass_empty:",
                )
            elif duraklatildi:
                st.info("**Bot açık, duraklatılmış.**", icon=":material/pause_circle:")
            else:
                st.success("**Bot çalışıyor.**", icon=":material/play_circle:")
            if s["etkinlik"]:
                st.caption(f"Şu an: {s['etkinlik']} · son sinyal {_sure_metni(s['nabiz_yasi_sn'])}"
                           + (f" · PID {s['pid']}" if s["pid"] else ""))

        with sag:
            with st.container(horizontal=True):
                if duraklatildi or not s["surec_var"]:
                    st.button("Başlat", icon=":material/play_arrow:", type="primary",
                              on_click=_baslat, args=(platform,), key="btn_baslat")
                else:
                    st.button("Duraklat", icon=":material/pause:", on_click=_duraklat,
                              args=(platform,), key="btn_duraklat")
                st.button("Botu kapat", icon=":material/stop:", on_click=_kapat, args=(platform,),
                          disabled=not s["surec_var"], key="btn_kapat",
                          help="Tarayıcıyı kapatır ve bot sürecini sonlandırır.")
                if IG:
                    st.button("Hikaye turu şimdi", icon=":material/history:", on_click=_hikaye_turu_simdi,
                              key="btn_tur", help="Soğuma süresini sıfırlar; bot sıradaki adımda tura başlar.")
                st.button("DM turu şimdi", icon=":material/send:", on_click=_dm_turu_simdi,
                          args=(platform,), key="btn_dm_tur", disabled=not ozet["dm_aktif"],
                          help="Direkt DM soğumasını sıfırlar; bot sıradaki adımda takip listesi turuna başlar.")

    if ozet["action_block"] or ozet["checkpoint"]:
        neden = f"{AD} 'işlem engellendi' uyarısı verdi" if ozet["action_block"] else \
            f"{AD} doğrulama (checkpoint / CAPTCHA) istedi"
        with st.container(border=True):
            st.error(f"**{neden}; bot duraklatıldı.** Tarayıcıdan durumu kontrol edin. Action block'ta "
                     "birkaç saat bekleyip saatlik limiti düşürmeniz önerilir.", icon=":material/block:")
            st.button("Uyarıyı temizle", on_click=_engeli_temizle, args=(platform,), key="btn_engel")

    p = ayarlar.pacing
    saatlik = p.acilis_saatlik or "∞"
    gunluk = p.acilis_gunluk or "∞"
    k = ozet["kotalar"]
    dm_saatlik = p.dm_acilis_saatlik or "∞"
    dm_gunluk = p.dm_acilis_gunluk or "∞"
    with st.container(horizontal=True):
        if IG:
            st.metric("Hikaye yanıtı · son 1 saat", f"{ozet['acilis_son_saat']} / {saatlik}", border=True)
            st.metric("Hikaye yanıtı · bugün", f"{ozet['acilis_bugun']} / {gunluk}", border=True)
        st.metric("Direkt DM · son 1 saat",
                  f"{ozet['dm_son_saat']} / {dm_saatlik}" if ozet["dm_aktif"] else "kapalı", border=True)
        st.metric("Direkt DM · bugün", f"{ozet['dm_bugun']} / {dm_gunluk}", border=True)
        if IG:
            st.metric("DM yanıtı · bugün", f"{k['respond']['yapilan']} / {k['respond']['tavan']}", border=True)
        st.metric("Çalışma saati", f"{p.calisma_baslangic_saat}:00–{p.calisma_bitis_saat}:00", border=True)

    son_hata = repo.durum_getir(conn, "son_hata", "", platform)
    if son_hata:
        st.caption(f":material/error: Son hata: {son_hata}")


canli_durum(platform)

# --------------------------------------------------------------------------- #
# Sekmeler
# --------------------------------------------------------------------------- #
sek_konusma, sek_ayar, sek_dnc, sek_log = st.tabs(
    [":material/forum: Konuşmalar", ":material/tune: Ayarlar",
     ":material/block: Do-not-contact", ":material/terminal: Log"]
)

# ---- Konuşmalar ------------------------------------------------------------ #
with sek_konusma:
    st.subheader("Onay / devir kuyruğu")
    olaylar = conn.execute(
        """
        SELECT e.id, e.type, e.detail, e.phone, e.created_at,
               l.id AS lead_id, l.business_name, l.city, l.ai_enabled,
               COALESCE(l.handle, l.ig_handle) AS handle,
               COALESCE(NULLIF(l.profile_url, ''), l.ig_profile_url) AS profile_url
        FROM sales_events e JOIN leads l ON l.id = e.lead_id
        WHERE e.type IN ('trial_proposed','handoff') AND l.platform = ?
        ORDER BY e.id DESC LIMIT 50
        """,
        (platform,),
    ).fetchall()

    if not olaylar:
        st.info("Bekleyen sıcak lead / devir yok.")
    for e in olaylar:
        rozet = ":green-badge[Deneme]" if e["type"] == "trial_proposed" else ":orange-badge[Devir]"
        with st.container(border=True):
            c1, c2, c3 = st.columns([2.5, 2, 1.2])
            with c1:
                st.markdown(f"{rozet} **{e['business_name'] or e['handle']}**")
                st.caption(f"@{e['handle']} · {e['city'] or '—'} · {e['created_at']}")
                if e["phone"]:
                    st.markdown(f":material/call: **{e['phone']}**")
                if e["detail"]:
                    st.caption(e["detail"][:200])
            with c2:
                if e["profile_url"]:
                    st.markdown(f"[Profili aç]({e['profile_url']})")
                st.caption(f"AI: {'açık' if e['ai_enabled'] else 'kapalı'}")
            with c3:
                if not e["ai_enabled"]:
                    if st.button("AI'yı aç", key=f"aiac_{e['id']}"):
                        repo.ai_durumu_ayarla(conn, int(e["lead_id"]), True)
                        st.rerun()

    st.subheader("Konuşmalar")
    arama = st.text_input("Hesap ara", placeholder="kullanıcı adı veya işletme", key="konusma_ara")
    desen = f"%{arama.strip().lstrip('@')}%"
    threadler = conn.execute(
        """
        SELECT l.id, l.business_name, COALESCE(l.handle, l.ig_handle) AS handle,
               l.stage, l.ai_enabled, l.do_not_contact,
               MAX(m.sent_at) AS son,
               SUM(m.direction = 'inbound') AS gelen
        FROM leads l JOIN ig_messages m ON m.lead_id = l.id
        WHERE l.platform = ? AND (COALESCE(l.handle, l.ig_handle) LIKE ? OR l.business_name LIKE ?)
        GROUP BY l.id ORDER BY gelen > 0 DESC, son DESC LIMIT 50
        """,
        (platform, desen, desen),
    ).fetchall()

    if not threadler:
        st.info("Henüz konuşma yok.")
    for t in threadler:
        cevap = " · :green-badge[cevap verdi]" if t["gelen"] else ""
        baslik = f"@{t['handle']} · aşama: {t['stage']} · {t['son']}{cevap}"
        with st.expander(baslik):
            c1, c2 = st.columns(2)
            with c1:
                yeni = st.toggle("AI açık", value=bool(t["ai_enabled"]), key=f"ai_{t['id']}")
                if yeni != bool(t["ai_enabled"]):
                    repo.ai_durumu_ayarla(conn, int(t["id"]), yeni)
                    st.rerun()
            with c2:
                if not t["do_not_contact"]:
                    if st.button("İletişimi kes (DNC)", key=f"dnc_{t['id']}"):
                        repo.do_not_contact_isaretle(conn, int(t["id"]), reason="panelden")
                        st.rerun()
                else:
                    st.caption(":material/block: do-not-contact")

            for m in repo.thread_mesajlari(conn, int(t["id"])):
                yon = m["direction"]
                if yon == "inbound":
                    st.markdown(f":material/arrow_back: **onlar:** {m['body']}")
                elif yon == "story_reply":
                    st.markdown(f":material/arrow_forward: *hikaye yanıtı:* {m['body']}")
                elif yon == "dm_opener":
                    st.markdown(f":material/arrow_forward: *direkt DM:* {m['body']}")
                else:
                    etik = "AI" if m["ai_generated"] else "elle"
                    st.markdown(f":material/arrow_forward: **biz ({etik}):** {m['body']}")

# ---- Ayarlar --------------------------------------------------------------- #
with sek_ayar:
    a = _ayarlar(platform)
    p = a.pacing
    st.caption(f"{AD} ayarları. Kaydedilen ayarlar botu yeniden başlatmadan bir sonraki turda "
               "uygulanır. 0 = sınırsız.")
    with st.form("ayarlar"):
        if IG:
            st.markdown("**Hikaye yanıtları**")
            c1, c2, c3 = st.columns(3)
            saatlik = c1.number_input("Saatlik tavan", min_value=0, max_value=1000, value=int(p.acilis_saatlik),
                                      help="Son 60 dakikada en fazla. Gönderimler saate eşit yayılır.")
            gunluk = c2.number_input("Günlük tavan", min_value=0, max_value=10000, value=int(p.acilis_gunluk))
            tekrar_gun = c3.number_input("Aynı hesaba tekrar yazma (gün sonra)", min_value=0, max_value=365,
                                         value=int(a.yeniden_iletisim_gun),
                                         help="0 = asla: bir kez yazılan hesaba bir daha açılış yapılmaz.")
            cooldown_dk = st.number_input("Tepsi turları arası bekleme (dk)", min_value=1, max_value=240,
                                          value=max(1, int(p.hikaye_turu_cooldown_sn) // 60),
                                          help="Bir tur bittikten sonra yeni hikayeler için tepsiyi yeniden "
                                               "gezmeden önce.")

        modlar = {"gpt": "GPT ile çeşitlendir", "sabit": "Kendi metinlerim"}
        mod = st.segmented_control("Açılış mesajı", options=list(modlar), format_func=modlar.get,
                                   default=a.acilis_modu if a.acilis_modu in modlar else "gpt")
        metinler = st.text_area(
            "Kendi açılış metinlerim (her satır bir seçenek, rastgele seçilir)",
            value=a.acilis_metinleri, height=120,
            placeholder="Merhabalar, kolay gelsin! İşlerinizi takip için bir program kullanıyor musunuz?",
        )

        st.markdown("**Takip edilenlere direkt DM**")
        c1, c2, c3 = st.columns(3)
        dm_saatlik_in = c1.number_input("DM saatlik tavan", min_value=0, max_value=200,
                                        value=int(p.dm_acilis_saatlik),
                                        help="Hikaye yanıtı tavanından ayrıdır. 0 = sınırsız." if IG
                                        else "0 = sınırsız.")
        dm_gunluk_in = c2.number_input("DM günlük tavan", min_value=0, max_value=2000,
                                       value=int(p.dm_acilis_gunluk))
        dm_cooldown_dk = c3.number_input("DM turları arası bekleme (dk)", min_value=1, max_value=720,
                                         value=max(1, int(p.dm_turu_cooldown_sn) // 60))
        c1, c2 = st.columns(2)
        kendi_ad = c1.text_input(f"{AD} kullanıcı adımız",
                                 value=a.kendi_kullanici_adi,
                                 placeholder="boş bırakılırsa sayfadan bulunur",
                                 help="Takip listesi /<kullanıcı adı>/following/ sayfasından okunur." if IG
                                 else "Takip edilen listesi tiktok.com/@<kullanıcı adı> profilinden okunur.")
        if not IG:
            tekrar_gun = c2.number_input("Aynı hesaba tekrar yazma (gün sonra)", min_value=0, max_value=365,
                                         value=int(a.yeniden_iletisim_gun),
                                         help=f"0 = asla: {AD}'ta bir kez yazılan hesaba bir daha açılış "
                                              "yapılmaz (Instagram'dakinden bağımsız).")

        st.markdown("**Genel**")
        c1, c2, c3 = st.columns(3)
        if IG:
            dm_max = c1.number_input("Günlük DM yanıtı tavanı", min_value=0, max_value=2000,
                                     value=int(p.dm_max_gunluk))
        bas = c2.number_input("Çalışma başlangıcı (saat)", min_value=0, max_value=23,
                              value=int(p.calisma_baslangic_saat))
        bit = c3.number_input("Çalışma bitişi (saat, hariç)", min_value=1, max_value=24,
                              value=int(p.calisma_bitis_saat))
        c1, c2 = st.columns(2)
        bek_min = c1.number_input("Görevler arası bekleme min (sn)", min_value=0.0, max_value=3600.0,
                                  value=float(p.aksiyon_bekleme_min))
        bek_max = c2.number_input("Görevler arası bekleme max (sn)", min_value=0.0, max_value=3600.0,
                                  value=float(p.aksiyon_bekleme_max))

        if st.form_submit_button("Kaydet", type="primary", icon=":material/save:"):
            if bas >= bit:
                st.error("Çalışma başlangıcı bitişten önce olmalı.")
            elif mod == "sabit" and not metinler.strip():
                st.error("Kendi metinlerim seçiliyken en az bir satır metin girin.")
            else:
                degerler = {
                    "yeniden_iletisim_gun": int(tekrar_gun),
                    "acilis_modu": mod or "gpt",
                    "acilis_metinleri": metinler.strip(),
                    "dm_acilis_saatlik": int(dm_saatlik_in),
                    "dm_acilis_gunluk": int(dm_gunluk_in),
                    "dm_turu_cooldown_sn": int(dm_cooldown_dk) * 60,
                    "kendi_kullanici_adi": kendi_ad.strip().lstrip("@"),
                    "calisma_baslangic_saat": int(bas),
                    "calisma_bitis_saat": int(bit),
                    "aksiyon_bekleme_min": float(min(bek_min, bek_max)),
                    "aksiyon_bekleme_max": float(max(bek_min, bek_max)),
                }
                if IG:
                    degerler.update({
                        "acilis_saatlik": int(saatlik),
                        "acilis_gunluk": int(gunluk),
                        "hikaye_turu_cooldown_sn": int(cooldown_dk) * 60,
                        "dm_max_gunluk": int(dm_max),
                    })
                canli_ayarlar.kaydet(conn, degerler, platform=platform)
                st.toast(f"{AD} ayarları kaydedildi.", icon=":material/check:")

    if IG and (int(p.acilis_saatlik) == 0 or int(p.acilis_saatlik) > 60):
        st.warning("Saatlik tavan yüksek. Instagram yüksek hacimde hikaye yanıtını 'işlem engellendi' ile "
                   "kısıtlayabilir; bot bunu algılarsa otomatik duraklar.", icon=":material/warning:")

    dm_uyari_esigi = 20 if IG else 10
    if int(p.dm_acilis_saatlik) == 0 or int(p.dm_acilis_saatlik) > dm_uyari_esigi:
        st.warning(f"DM saatlik tavanı yüksek. Takip etmeyenlere giden DM'ler 'mesaj istekleri'ne düşer ve "
                   f"{AD} bunları sıkı sınırlar; bot engel/CAPTCHA görürse otomatik duraklar.",
                   icon=":material/warning:")

    st.markdown("**Takip edilenlere direkt DM**")
    dm_aktif = repo.bayrak_getir(conn, "dm_acilis_aktif", False, platform=platform)
    dm_etiket = "Takip edilenlere direkt DM'i aç (hikaye turundan sonra çalışır)" if IG else \
        f"{AD}'ta takip edilenlere direkt DM'i aç"
    yeni_dm = st.toggle(dm_etiket, value=dm_aktif, key=f"dm_aktif_{platform}")
    if yeni_dm != dm_aktif:
        repo.durum_ayarla(conn, "dm_acilis_aktif", "1" if yeni_dm else "0", platform=platform)
        st.rerun()

    if IG:
        st.markdown("**Hashtag keşfi**")
        kesif = repo.bayrak_getir(conn, "kesif_aktif", False)
        yeni_kesif = st.toggle("Hashtag keşfini de aç (birincil kaynak hikaye tepsisidir)", value=kesif)
        if yeni_kesif != kesif:
            repo.durum_ayarla(conn, "kesif_aktif", "1" if yeni_kesif else "0")
            st.rerun()
        st.caption(f"Hashtag'ler: {', '.join(a.hashtagler) or '—'} · "
                   f"Şehirler: {', '.join(a.sehirler) or '—'} (.env)")

# ---- Do-not-contact -------------------------------------------------------- #
with sek_dnc:
    with st.form("dnc_ekle", clear_on_submit=True):
        handle = st.text_input(f"{AD} kullanıcı adı ekle (bu hesaba asla yazılmaz)", placeholder="ornek_hesap")
        if st.form_submit_button("Ekle") and handle.strip():
            repo.dnc_ekle(conn, handle.strip().lstrip("@"), "panelden elle", platform=platform)
            st.success(f"@{handle.strip().lstrip('@')} eklendi.")

    dnc = repo.dnc_listesi(conn, platform)
    if dnc:
        st.dataframe(
            [{"handle": d["handle"], "sebep": d["reason"], "tarih": d["created_at"]} for d in dnc],
            hide_index=True,
        )
    else:
        st.info("Liste boş.")

# ---- Log ------------------------------------------------------------------- #
with sek_log:
    st.caption(f"{AD} bot çıktısı: `{surec.log_yolu(platform)}`")
    if st.button("Yenile", icon=":material/refresh:", key="log_yenile"):
        st.rerun()
    st.code(surec.log_son_satirlar(80, platform=platform) or "Henüz log yok.", language=None)
