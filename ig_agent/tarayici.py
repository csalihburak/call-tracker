"""Platform istemcilerinin ortak Playwright temeli (headful, kalıcı profil).

Instagram ve TikTok istemcileri bundan türer. Burada platformdan bağımsız
olanlar durur: tarayıcıyı kalıcı profille açıp kapatma, sayfaya gitme,
insan-benzeri yazma, checkpoint / "işlem engellendi" tespit iskeleti, takip
listesi önbelleği ve açılış turu döngüsü. Seçiciler alt sınıfın `S` sınıfında
durur (`DIALOG`, `ENGEL_METIN`, `CHECKPOINT_YOLLARI` burada kullanılır).

Alt sınıf şunları sağlar: `giris_yapildi_mi()`, `_hedef(handle)`,
`_takip_listesini_kazi()`, `_dm_gonder_sonuc(handle, metin)`; gerekirse
`_checkpoint_ekrani_var()` (ör. TikTok CAPTCHA'sı). İstemci DB'ye dokunmaz.
"""

from __future__ import annotations

import random
import time
from typing import Optional

from .config import Ayarlar
from .platformlar import TURU_BITIR, GonderimSonucu, Hedef

# Takip listesi bu kadar saniye önbellekte tutulur (her turda baştan kaydırılmasın)
TAKIP_ONBELLEK_SN = 3 * 3600


class TarayiciIstemci:
    platform = ""
    # Log satırlarının öneki, ör. "[ig] takip listesi toplandı"
    LOG_ONEK = ""
    S: type  # alt sınıfın seçici sınıfı

    def __init__(self, ayarlar: Ayarlar):
        self._ayarlar = ayarlar
        self._pw = None
        self._ctx = None
        self._page = None
        self._rng = random.Random()
        # Platform "işlem engellendi" uyarısı gösterdiyse True olur; üst katman
        # bunu görüp botu duraklatır ve bayrağı sıfırlar.
        self.engel_algilandi = False
        self._takip_onbellek: Optional[tuple[float, list[str]]] = None

    # ------------------------------------------------------------------ #
    # Yaşam döngüsü
    # ------------------------------------------------------------------ #
    def baslat(self):
        from playwright.sync_api import sync_playwright  # gecikmeli import

        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=self._ayarlar.tarayici_profil_dizini,
            headless=self._ayarlar.headless,
            viewport={"width": 1280, "height": 900},
            locale="tr-TR",
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def kapat(self):
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    def __enter__(self):
        return self.baslat()

    def __exit__(self, *a):
        self.kapat()

    # ------------------------------------------------------------------ #
    # Durum tespiti
    # ------------------------------------------------------------------ #
    def _git(self, url: str, bekle: float = 2.5):
        self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(bekle + self._rng.uniform(0.5, 2.0))

    def checkpoint_var_mi(self) -> bool:
        """URL bir doğrulama sayfasıysa ya da sayfada doğrulama ekranı varsa True."""
        try:
            url = (self._page.url or "").lower()
            if any(yol in url for yol in self.S.CHECKPOINT_YOLLARI):
                return True
        except Exception:
            return False
        return self._checkpoint_ekrani_var()

    def _checkpoint_ekrani_var(self) -> bool:
        """URL değişmeden çıkan doğrulama ekranı (alt sınıf; varsayılan yok)."""
        return False

    def _engel_kontrol(self) -> bool:
        """Ekranda action-block uyarısı var mı? Varsa `engel_algilandi`'yi kurar."""
        try:
            for dialog in self._page.query_selector_all(self.S.DIALOG):
                metin = (dialog.inner_text() or "").lower()
                if any(k in metin for k in self.S.ENGEL_METIN):
                    self.engel_algilandi = True
                    return True
        except Exception:
            pass
        return False

    def _sayfada_metin_var(self, kelimeler: list[str]) -> bool:
        """Sayfa metninde (küçük harfle) kelimelerden biri geçiyor mu?"""
        try:
            metin = (self._page.inner_text("body") or "").lower()
            return any(k in metin for k in kelimeler)
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # İnsan-benzeri yazma
    # ------------------------------------------------------------------ #
    def _insan_yaz(self, element, metin: str):
        p = self._ayarlar.pacing
        for kar in metin:
            element.type(kar, delay=self._rng.uniform(
                p.yazma_min_kar_sn * 1000, p.yazma_max_kar_sn * 1000
            ))
        time.sleep(self._rng.uniform(0.4, 1.2))

    @staticmethod
    def _diyalogu_kaydir(dialog) -> None:
        """Penceredeki kaydırılabilir öğeyi en alta kaydırır (tembel yükleme)."""
        dialog.evaluate(
            """d => {
                const k = [d, ...d.querySelectorAll('*')].find(e =>
                    e.scrollHeight > e.clientHeight + 10 &&
                    getComputedStyle(e).overflowY !== 'visible');
                if (k) k.scrollTop = k.scrollHeight;
            }"""
        )

    # ------------------------------------------------------------------ #
    # Takip listesi turu (takip ettiklerimize direkt DM)
    # ------------------------------------------------------------------ #
    def takip_listesi_topla(self) -> list[str]:
        """Takip listesi; TAKIP_ONBELLEK_SN boyunca önbellekten (boş liste saklanmaz)."""
        if self._takip_onbellek and time.monotonic() - self._takip_onbellek[0] < TAKIP_ONBELLEK_SN:
            return list(self._takip_onbellek[1])
        liste = self._takip_listesini_kazi()
        print(f"[{self.LOG_ONEK}] takip listesi toplandı: {len(liste)} hesap")
        if liste:
            self._takip_onbellek = (time.monotonic(), list(liste))
        return liste

    def acilis_turu(self, karar_fn, sonuc_fn, yazmadan_once) -> None:
        """Takip listesindeki her hesap için karar → tempo → DM → sonuç bildirimi.

        `karar_fn(Hedef)`: metin → gönder, None → atla, TURU_BITIR → bitir.
        `yazmadan_once()` profil açılmadan önce çağrılır (tempo beklemesi);
        False dönerse tur biter.
        """
        for handle in self.takip_listesi_topla():
            if self.checkpoint_var_mi():
                break
            hedef = self._hedef(handle)
            metin = karar_fn(hedef)
            if metin == TURU_BITIR:
                break
            if not metin:
                continue
            if not yazmadan_once():
                break
            sonuc_fn(hedef, metin, self._dm_gonder_sonuc(handle, metin))
            if self.engel_algilandi:
                break

    # Alt sınıfın sağladıkları
    def giris_yapildi_mi(self) -> bool:
        raise NotImplementedError

    def _hedef(self, handle: str) -> Hedef:
        raise NotImplementedError

    def _takip_listesini_kazi(self) -> list[str]:
        raise NotImplementedError

    def _dm_gonder_sonuc(self, handle: str, metin: str) -> GonderimSonucu:
        raise NotImplementedError
