"""Satış ajanı giriş noktası — her platform ayrı bir süreç.

Çalıştırma (genelde kontrol panelindeki "Başlat" butonu bunu yapar):
    .venv/bin/python3.12 -m ig_agent.run                      # Instagram
    .venv/bin/python3.12 -m ig_agent.run --platform tiktok    # TikTok

İlk çalıştırmada tarayıcı açılır; platforma SEN giriş yaparsın (2FA dahil).
Oturum platformun kalıcı profilinde saklanır. Bot her döngüde `bot_nabiz`/
`bot_durum` yazar (Instagram öneksiz, TikTok `tiktok:` önekli); panel bunlardan
botun ayakta olup olmadığını ve ne yaptığını gösterir.

Instagram süreci: gelen kutusu + yanıt + hikaye turu + direkt DM (+ Sheets).
TikTok süreci: yalnızca takip edilenlere direkt DM.
"""

from __future__ import annotations

import argparse
import os
import random
import signal
import time
import traceback
from datetime import datetime

from . import canli_ayarlar, db, inbox_ingest, pacing, repository as repo, scheduler as sch
from .alerts import AlertClient
from .config import ayarlari_yukle
from .llm_openai import OpenAIIstemci
from .platformlar import PLATFORM_ADI, PLATFORMLAR, istemci_olustur

INBOX_ARALIK_SN = 180  # inbox tarama sıklığı
SHEETS_ARALIK_SN = 120  # Sheets flush sıklığı
MAX_HATA_BEKLEME_SN = 300  # art arda hatalarda bekleme tavanı


def _sigterm(_signum, _frame):
    # Panelin "Botu kapat" butonu SIGTERM gönderir → tarayıcıyı düzgün kapat
    raise KeyboardInterrupt


def _sheets_yazici(ayarlar):
    if not ayarlar.sheets.etkin:
        return None
    try:
        from .sheets import GspreadYazici

        return GspreadYazici(ayarlar)
    except Exception as hata:
        print(f"[sheets] devre dışı ({hata})")
        return None


def arg_coz(argv=None) -> argparse.Namespace:
    ayristirici = argparse.ArgumentParser(prog="ig_agent.run", description="Satış ajanı botu")
    ayristirici.add_argument("--platform", choices=PLATFORMLAR, default="instagram",
                             help="bu süreç hangi platformda çalışır (varsayılan: instagram)")
    return ayristirici.parse_args(argv)


def _girisi_bekle(istemci, conn, platform: str) -> None:
    ad = PLATFORM_ADI[platform]
    onek = f"[{istemci.LOG_ONEK}]"
    if istemci.giris_yapildi_mi():
        print(f"{onek} giriş algılandı.")
        return
    print(f"{onek} Lütfen açılan tarayıcıda {ad}'a giriş yapın (2FA dahil).")
    while not istemci.giris_yapildi_mi():
        repo.nabiz_at(conn, f"{ad} girişi bekleniyor — açılan tarayıcıdan giriş yapın",
                      platform=platform)
        time.sleep(15)
    print(f"{onek} giriş tamam.")


def _bosta_nedeni(ozet: dict, ayarlar) -> str:
    p = ayarlar.pacing
    if ozet["action_block"]:
        return "action block — panelden temizleyin"
    if not pacing.calisma_saatinde_mi(datetime.now(), p.calisma_baslangic_saat, p.calisma_bitis_saat):
        return f"çalışma saati dışı ({p.calisma_baslangic_saat}:00–{p.calisma_bitis_saat}:00)"
    if ozet.get("platform", "instagram") != "instagram" and not ozet["dm_aktif"]:
        return "direkt DM kapalı — panelden açın"
    if not ozet["izinli_aksiyonlar"]:
        return "kotalar dolu"
    if ozet.get("platform", "instagram") != "instagram":
        return "DM turu soğumada"
    return "bekleyen yanıt yok, hikaye/DM turları soğumada"


def main(argv=None) -> None:
    signal.signal(signal.SIGTERM, _sigterm)
    platform = arg_coz(argv).platform
    ad = PLATFORM_ADI[platform]
    temel = ayarlari_yukle(platform)
    conn = db.hazirla(temel)
    repo.durum_ayarla(conn, "bot_pid", os.getpid(), platform=platform)
    repo.nabiz_at(conn, "başlatılıyor", platform=platform)

    ig = None
    try:
        beyin = OpenAIIstemci(temel)
        bildirim = AlertClient(temel)
        # Sheets senkronu tek süreçten (Instagram) yapılır: Pipeline yalnız IG lead'leri,
        # mesaj/olay logları tüm platformlar ("tiktok:kullanici")
        sheets_yazici = _sheets_yazici(temel) if platform == "instagram" else None
        rng = random.Random()

        repo.nabiz_at(conn, "tarayıcı açılıyor", platform=platform)
        ig = istemci_olustur(platform, temel).baslat()
        _girisi_bekle(ig, conn, platform)
        repo.durum_ayarla(conn, "checkpoint_detected", "0", platform=platform)
        print(f"[bot] {ad} hazır. Panelden ▶️ Başlat'a basılınca çalışır.")

        son_inbox = 0.0
        son_sheets = 0.0
        hata_sayisi = 0

        while True:
            ayarlar = canli_ayarlar.uygula(conn, temel)

            # Duraklatma: tarayıcıya hiç dokunma
            if repo.bayrak_getir(conn, "master_paused", True, platform=platform):
                repo.nabiz_at(conn, "⏸ duraklatılmış", platform=platform)
                time.sleep(5)
                continue

            try:
                if ig.checkpoint_var_mi():
                    # Yalnızca bu platformun botu durur (TikTok CAPTCHA'sı dahil; çözülmez)
                    repo.durum_ayarla(conn, "checkpoint_detected", "1", platform=platform)
                    repo.durum_ayarla(conn, "master_paused", "1", platform=platform)
                    repo.hata_kaydet(conn, f"{ad} checkpoint/doğrulama istedi — bot duraklatıldı",
                                     platform=platform)
                    print("[bot] CHECKPOINT algılandı — durduruldu. Tarayıcıdan çözün, "
                          "sonra panelden tekrar başlatın.")
                    continue

                simdi = time.time()
                p = ayarlar.pacing
                calisma_saati = pacing.calisma_saatinde_mi(
                    datetime.now(), p.calisma_baslangic_saat, p.calisma_bitis_saat
                )

                # 1) Inbox alımı (yalnız Instagram; çalışma saatinde, aralıkla)
                if hasattr(ig, "gelen_mesajlari_oku") and calisma_saati \
                        and simdi - son_inbox > INBOX_ARALIK_SN:
                    repo.nabiz_at(conn, "gelen kutusu taranıyor")
                    gelenler = ig.gelen_mesajlari_oku()
                    eklendi = inbox_ingest.toplu_al(conn, gelenler)
                    if eklendi:
                        print(f"[inbox] {eklendi} yeni gelen mesaj alındı.")
                    son_inbox = simdi
                    sch.engel_isaretle(conn, ig)

                # 2) Bir zamanlayıcı adımı (respond > opener > discover)
                gorev = sch.tek_tur(conn, ayarlar, ig, beyin, bildirim, rng)
                if gorev:
                    print(f"[bot] görev: {gorev} @ {datetime.now():%H:%M:%S}")
                else:
                    ozet = sch.durum_ozeti(conn, ayarlar, platform)
                    repo.nabiz_at(conn, f"boşta — {_bosta_nedeni(ozet, ayarlar)}", platform=platform)
                    sch.uyku(conn, 20, platform=platform)

                # 3) Sheets flush (aralıkla)
                if sheets_yazici and simdi - son_sheets > SHEETS_ARALIK_SN:
                    try:
                        from .sheets import flush

                        sayac = flush(conn, sheets_yazici)
                        if any(sayac.values()):
                            print(f"[sheets] senkron: {sayac}")
                    except Exception as hata:
                        print(f"[sheets] flush hatası: {hata}")
                    son_sheets = simdi

                hata_sayisi = 0
            except KeyboardInterrupt:
                raise
            except Exception as hata:
                # Tek adımın hatası (OpenAI, zaman aşımı, DOM) botu öldürmesin
                hata_sayisi += 1
                repo.hata_kaydet(conn, f"{type(hata).__name__}: {hata}", platform=platform)
                traceback.print_exc()
                bekleme = min(MAX_HATA_BEKLEME_SN, 15 * hata_sayisi)
                repo.nabiz_at(conn, f"hata sonrası bekleme ({bekleme} sn, art arda {hata_sayisi})",
                              platform=platform)
                sch.uyku(conn, bekleme, platform=platform)

    except KeyboardInterrupt:
        print("\n[bot] durduruluyor...")
    except Exception as hata:
        repo.hata_kaydet(conn, f"bot başlatılamadı — {type(hata).__name__}: {hata}",
                         platform=platform)
        traceback.print_exc()
    finally:
        if ig is not None:
            try:
                ig.kapat()
            except Exception:
                pass
        repo.durum_ayarla(conn, "bot_pid", "", platform=platform)
        repo.nabiz_at(conn, "kapalı", platform=platform)
        conn.close()


if __name__ == "__main__":
    main()
