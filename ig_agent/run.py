"""Instagram satış ajanı giriş noktası.

Çalıştırma (genelde kontrol panelindeki "Botu başlat" butonu bunu yapar):
    .venv/bin/python3.12 -m ig_agent.run

İlk çalıştırmada tarayıcı açılır; Instagram'a SEN giriş yaparsın (2FA dahil).
Oturum kalıcı profilde saklanır. Bot her döngüde `bot_nabiz`/`bot_durum`
yazar; panel bunlardan botun ayakta olup olmadığını ve ne yaptığını gösterir.
"""

from __future__ import annotations

import os
import random
import signal
import time
import traceback
from datetime import datetime

from . import canli_ayarlar, db, inbox_ingest, pacing, repository as repo, scheduler as sch
from .alerts import AlertClient
from .config import ayarlari_yukle
from .instagram import InstagramClient
from .llm_openai import OpenAIIstemci

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


def _girisi_bekle(ig: InstagramClient, conn) -> None:
    if ig.giris_yapildi_mi():
        print("[ig] giriş algılandı.")
        return
    print("[ig] Lütfen açılan tarayıcıda Instagram'a giriş yapın (2FA dahil).")
    while not ig.giris_yapildi_mi():
        repo.nabiz_at(conn, "Instagram girişi bekleniyor — açılan tarayıcıdan giriş yapın")
        time.sleep(15)
    print("[ig] giriş tamam.")


def _bosta_nedeni(ozet: dict, ayarlar) -> str:
    p = ayarlar.pacing
    if ozet["action_block"]:
        return "action block — panelden temizleyin"
    if not pacing.calisma_saatinde_mi(datetime.now(), p.calisma_baslangic_saat, p.calisma_bitis_saat):
        return f"çalışma saati dışı ({p.calisma_baslangic_saat}:00–{p.calisma_bitis_saat}:00)"
    if not ozet["izinli_aksiyonlar"]:
        return "kotalar dolu"
    return "bekleyen yanıt yok, hikaye turu soğumada"


def main() -> None:
    signal.signal(signal.SIGTERM, _sigterm)
    temel = ayarlari_yukle()
    conn = db.hazirla(temel)
    repo.durum_ayarla(conn, "bot_pid", os.getpid())
    repo.nabiz_at(conn, "başlatılıyor")

    ig = None
    try:
        beyin = OpenAIIstemci(temel)
        bildirim = AlertClient(temel)
        sheets_yazici = _sheets_yazici(temel)
        rng = random.Random()

        repo.nabiz_at(conn, "tarayıcı açılıyor")
        ig = InstagramClient(temel).baslat()
        _girisi_bekle(ig, conn)
        repo.durum_ayarla(conn, "checkpoint_detected", "0")
        print("[bot] hazır. Panelden ▶️ Başlat'a basılınca çalışır.")

        son_inbox = 0.0
        son_sheets = 0.0
        hata_sayisi = 0

        while True:
            ayarlar = canli_ayarlar.uygula(conn, temel)

            # Duraklatma: tarayıcıya hiç dokunma
            if repo.bayrak_getir(conn, "master_paused", True):
                repo.nabiz_at(conn, "⏸ duraklatılmış")
                time.sleep(5)
                continue

            try:
                if ig.checkpoint_var_mi():
                    repo.durum_ayarla(conn, "checkpoint_detected", "1")
                    repo.durum_ayarla(conn, "master_paused", "1")
                    repo.hata_kaydet(conn, "Instagram checkpoint/doğrulama istedi — bot duraklatıldı")
                    print("[bot] CHECKPOINT algılandı — durduruldu. Tarayıcıdan çözün, "
                          "sonra panelden tekrar başlatın.")
                    continue

                simdi = time.time()
                p = ayarlar.pacing
                calisma_saati = pacing.calisma_saatinde_mi(
                    datetime.now(), p.calisma_baslangic_saat, p.calisma_bitis_saat
                )

                # 1) Inbox alımı (yalnız çalışma saatinde, aralıkla)
                if calisma_saati and simdi - son_inbox > INBOX_ARALIK_SN:
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
                    ozet = sch.durum_ozeti(conn, ayarlar)
                    repo.nabiz_at(conn, f"boşta — {_bosta_nedeni(ozet, ayarlar)}")
                    sch.uyku(conn, 20)

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
                repo.hata_kaydet(conn, f"{type(hata).__name__}: {hata}")
                traceback.print_exc()
                bekleme = min(MAX_HATA_BEKLEME_SN, 15 * hata_sayisi)
                repo.nabiz_at(conn, f"hata sonrası bekleme ({bekleme} sn, art arda {hata_sayisi})")
                sch.uyku(conn, bekleme)

    except KeyboardInterrupt:
        print("\n[bot] durduruluyor...")
    except Exception as hata:
        repo.hata_kaydet(conn, f"bot başlatılamadı — {type(hata).__name__}: {hata}")
        traceback.print_exc()
    finally:
        if ig is not None:
            try:
                ig.kapat()
            except Exception:
                pass
        repo.durum_ayarla(conn, "bot_pid", "")
        repo.nabiz_at(conn, "kapalı")
        conn.close()


if __name__ == "__main__":
    main()
