"""Instagram web otomasyonu (Playwright, headful, kalıcı profil).

ÖNEMLİ: Instagram DOM'u sık değişir. Tüm CSS/metin seçicileri aşağıdaki
`S` sınıfında toplanmıştır — kırılırsa yalnızca orayı güncelle. İstemci DB'ye
dokunmaz; veri/boolean döner, DB işini üst katman (run/scheduler) yapar.

Anti-ban: insan-benzeri karakter-karakter yazma, aksiyonlar arası bekleme
(zamanlayıcıda), checkpoint/challenge tespitinde otomatik durma.

İlk çalıştırmada TARAYICI AÇILIR ve SEN GİRİŞ YAPARSIN (2FA dahil). Oturum
kalıcı profilde saklanır; sonraki çalıştırmalar girişi hatırlar.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .config import Ayarlar

IG_TABAN = "https://www.instagram.com"

# hikayeleri_yanitla'daki karar_fn bunu dönerse tur hemen biter
# (duraklatıldı, kota doldu, çalışma saati bitti vb.)
TURU_BITIR = "__TURU_BITIR__"

# Profil linki olamayacak tek parçalı IG yolları
_AYRILMIS_YOLLAR = {
    "", "direct", "explore", "reels", "reel", "accounts", "stories", "p",
    "about", "legal", "developer", "web", "emails", "challenge",
}
_PROFIL_YOLU = re.compile(r"^/([A-Za-z0-9._]{1,30})/?$")


class S:
    """Merkezî seçiciler (IG değişince burayı güncelle)."""

    # Giriş / durum
    GIRIS_FORMU = 'input[name="username"]'
    CHECKPOINT_METIN = ["challenge", "checkpoint", "We suspect", "unusual activity",
                        "olağan dışı", "doğrula", "hesabını koru"]

    # Instagram'ın "işlem engellendi" uyarıları (küçük harfle aranır)
    ENGEL_METIN = [
        "try again later", "daha sonra tekrar dene", "action blocked",
        "we restrict certain activity", "belirli etkinlikleri kısıtlıyoruz",
        "bazı etkinlikleri kısıtlıyoruz", "işlem engellendi",
    ]
    DIALOG = 'div[role="dialog"]'

    # DM kutusu
    INBOX_URL = f"{IG_TABAN}/direct/inbox/"
    # Sohbet sayfasında ana içerik (soldaki gezinme menüsü hariç)
    THREAD_ANA = 'div[role="main"], main'
    # Tek mesaj satırı ve içindeki metin
    MESAJ_SATIRI = 'div[role="row"]'
    MESAJ_METNI = 'div[dir="auto"], span[dir="auto"]'

    THREAD_LISTE = 'div[role="listitem"], div[aria-label*="Sohbet"], a[href^="/direct/t/"]'
    MESAJ_KUTUSU = 'div[aria-label*="Mesaj"][contenteditable="true"], textarea[placeholder*="Mesaj"], div[contenteditable="true"][role="textbox"]'
    GONDERI_BUTON_METIN = ["Gönder", "Send"]

    # Profil / hikaye
    HIKAYE_HALKASI = 'canvas'  # profil avatarındaki hikaye halkası (kaba)
    HIKAYE_YANIT_KUTUSU = 'textarea[placeholder*="yanıt"], textarea[placeholder*="Reply"], div[contenteditable="true"][aria-label*="yanıt"]'
    # Ana sayfadaki hikaye tepsisinin ilk halkası (takip ettiklerimizin hikayeleri)
    HIKAYE_TEPSISI_ILK = 'button canvas, div[role="button"] canvas, canvas'
    # Hikaye görüntüleyicide "sonraki" için olası etiketler
    HIKAYE_ILERI_ETIKETLERI = ['İleri', 'Sonraki', 'Next']

    # Keşif
    def tag_url(tag: str) -> str:  # type: ignore[misc]
        return f"{IG_TABAN}/explore/tags/{tag}/"

    GONDERI_LINK = 'a[href^="/p/"]'
    GONDERI_YAZAR = 'header a[role="link"], a[href^="/"][role="link"]'


@dataclass
class AdayHesap:
    handle: str
    business_name: str = ""
    profile_url: str = ""
    followers: Optional[int] = None
    city: str = ""

    def as_dict(self) -> dict:
        return {
            "handle": self.handle,
            "business_name": self.business_name or self.handle,
            "profile_url": self.profile_url or f"{IG_TABAN}/{self.handle}/",
            "followers": self.followers,
            "city": self.city,
        }


class InstagramClient:
    def __init__(self, ayarlar: Ayarlar):
        self._ayarlar = ayarlar
        self._pw = None
        self._ctx = None
        self._page = None
        self._rng = random.Random()
        # Instagram "işlem engellendi" uyarısı gösterdiyse True olur; üst katman
        # bunu görüp botu duraklatır ve bayrağı sıfırlar.
        self.engel_algilandi = False

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

    def giris_yapildi_mi(self) -> bool:
        self._git(IG_TABAN)
        url = (self._page.url or "").lower()
        # Çıkışta IG /accounts/login'e yönlendirir
        if "/accounts/login" in url or "/accounts/emailsignup" in url:
            return False
        if self.checkpoint_var_mi():
            return False
        # Giriş formu (kullanıcı adı input'u) görünüyorsa henüz giriş yok.
        # Login URL'inde değiliz + kullanıcı adı input'u yok → giriş yapılmış.
        return self._page.query_selector(S.GIRIS_FORMU) is None

    def checkpoint_var_mi(self) -> bool:
        # Yalnızca URL'e bak — sayfa metnini taramak ("doğrula", "challenge" gibi
        # kelimeler normal IG sayfasında da geçer) yanlış pozitif üretir.
        try:
            url = (self._page.url or "").lower()
            return any(yol in url for yol in ("/challenge", "/checkpoint", "/accounts/suspended"))
        except Exception:
            return False

    def _engel_kontrol(self) -> bool:
        """Ekranda action-block uyarısı var mı? Varsa `engel_algilandi`'yi kurar."""
        try:
            for dialog in self._page.query_selector_all(S.DIALOG):
                metin = (dialog.inner_text() or "").lower()
                if any(k in metin for k in S.ENGEL_METIN):
                    self.engel_algilandi = True
                    return True
        except Exception:
            pass
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

    # ------------------------------------------------------------------ #
    # Keşif
    # ------------------------------------------------------------------ #
    def hashtag_kesfet(self, tag: str, sehir: str = "", limit: int = 12) -> list[dict]:
        """Bir hashtag sayfasından işletme hesabı adaylarını toplar (best-effort)."""
        adaylar: dict[str, AdayHesap] = {}
        try:
            self._git(S.tag_url(tag))
            self._page.mouse.wheel(0, 2000)
            time.sleep(self._rng.uniform(1.5, 3.0))
            linkler = self._page.query_selector_all(S.GONDERI_LINK)[: limit * 2]
            gonderi_yollari = []
            for a in linkler:
                href = a.get_attribute("href") or ""
                if href.startswith("/p/"):
                    gonderi_yollari.append(href)
            for yol in gonderi_yollari[:limit]:
                if self.checkpoint_var_mi():
                    break
                handle = self._gonderi_yazarini_al(yol)
                if handle and handle not in adaylar:
                    adaylar[handle] = AdayHesap(
                        handle=handle, city=sehir,
                        profile_url=f"{IG_TABAN}/{handle}/",
                    )
                time.sleep(self._rng.uniform(1.0, 2.5))
        except Exception:
            pass
        return [a.as_dict() for a in adaylar.values()]

    def _gonderi_yazarini_al(self, gonderi_yolu: str) -> Optional[str]:
        try:
            self._git(f"{IG_TABAN}{gonderi_yolu}", bekle=1.5)
            el = self._page.query_selector(S.GONDERI_YAZAR)
            if not el:
                return None
            href = el.get_attribute("href") or ""
            handle = href.strip("/").split("/")[0]
            return handle or None
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Hikaye-yanıtı açılışı
    # ------------------------------------------------------------------ #
    def hikaye_yaniti_gonder(self, handle: str, metin: str) -> bool:
        """Profilin aktif hikayesine yanıt gönderir. Hikaye yoksa False."""
        try:
            self._git(f"{IG_TABAN}/{handle}/")
            if self.checkpoint_var_mi():
                return False
            halka = self._page.query_selector(S.HIKAYE_HALKASI)
            if not halka:
                return False  # aktif hikaye yok
            halka.click()
            time.sleep(self._rng.uniform(1.5, 3.0))
            kutu = self._page.query_selector(S.HIKAYE_YANIT_KUTUSU)
            if not kutu:
                self._page.keyboard.press("Escape")
                return False
            kutu.click()
            self._insan_yaz(kutu, metin)
            self._page.keyboard.press("Enter")
            time.sleep(self._rng.uniform(1.0, 2.0))
            self._page.keyboard.press("Escape")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Hikaye tepsisi turu (takip ettiklerimizin hikayelerine yanıt)
    # ------------------------------------------------------------------ #
    def hikayeleri_yanitla(
        self,
        karar_fn: Callable[[str], Optional[str]],
        sonuc_fn: Optional[Callable[[str, str], None]] = None,
        yazmadan_once: Optional[Callable[[], bool]] = None,
        max_adim: int = 5000,
    ) -> list[dict]:
        """Ana sayfadaki hikaye tepsisini SONUNA KADAR gezer.

        Her yeni hesap için `karar_fn(handle)` çağrılır:
          - metin dönerse hikayeye yanıt olarak gönderilir,
          - None dönerse hesap atlanır,
          - TURU_BITIR dönerse tur hemen biter.
        `yazmadan_once()` yanıt kutusu tıklandıktan (hikaye durakladıktan) sonra,
        yazmaya başlamadan çağrılır; tempo beklemesi burada yapılır. False dönerse
        tur biter. Başarılı her gönderimde `sonuc_fn(handle, metin)` çağrılır.

        Döndürdüğü: [{'handle': str, 'sent': str|None}]. Handle, görüntüleyicinin
        `/stories/<handle>/...` URL'inden okunur (locale'den bağımsız, sağlam).
        """
        sonuclar: list[dict] = []
        try:
            self._git(IG_TABAN, bekle=3.0)
            ilk = self._page.query_selector(S.HIKAYE_TEPSISI_ILK)
            if not ilk:
                return sonuclar
            ilk.click()
            time.sleep(self._rng.uniform(2.0, 3.5))

            gorulen: set[str] = set()
            son_url, ayni_url = "", 0
            for _ in range(max_adim):
                handle = self._stories_url_handle()
                if not handle:
                    break  # görüntüleyici kapandı → tepsinin sonu
                url = self._page.url or ""
                ayni_url = ayni_url + 1 if url == son_url else 0
                son_url = url
                if ayni_url >= 5:
                    break  # ilerleyemiyoruz (takıldı)
                if handle not in gorulen:
                    gorulen.add(handle)
                    metin = karar_fn(handle)
                    if metin == TURU_BITIR:
                        break
                    if metin:
                        gonderildi = self._hikaye_yanit_yaz(metin, yazmadan_once)
                        if gonderildi is None:
                            break  # yazmadan_once turu durdurdu
                        sonuclar.append({"handle": handle, "sent": metin if gonderildi else None})
                        if gonderildi and sonuc_fn:
                            sonuc_fn(handle, metin)
                        if self.engel_algilandi:
                            break
                if not self._hikaye_ilerle():
                    break
                time.sleep(self._rng.uniform(1.2, 2.6))
        except Exception:
            pass
        finally:
            try:
                self._page.keyboard.press("Escape")
            except Exception:
                pass
        return sonuclar

    def _stories_url_handle(self) -> Optional[str]:
        try:
            url = self._page.url or ""
            if "/stories/" in url:
                handle = url.split("/stories/")[1].split("/")[0].split("?")[0]
                return handle or None
        except Exception:
            pass
        return None

    def _hikaye_yanit_yaz(
        self, metin: str, yazmadan_once: Optional[Callable[[], bool]] = None
    ) -> Optional[bool]:
        """True: gönderildi, False: gönderilemedi, None: yazmadan_once durdurdu."""
        try:
            kutu = self._page.query_selector(S.HIKAYE_YANIT_KUTUSU)
            if not kutu:
                return False
            kutu.click()  # kutu odaktayken hikaye duraklar
            if yazmadan_once and not yazmadan_once():
                return None
            self._insan_yaz(kutu, metin)
            self._page.keyboard.press("Enter")
            time.sleep(self._rng.uniform(1.0, 2.0))
            return not self._engel_kontrol()
        except Exception:
            return False

    def _hikaye_ilerle(self) -> bool:
        """Sonraki hikayeye geç. Önce 'İleri' butonu, olmazsa sağ ok."""
        try:
            for lbl in S.HIKAYE_ILERI_ETIKETLERI:
                btn = self._page.query_selector(f'svg[aria-label="{lbl}"]')
                if btn:
                    btn.click()
                    return True
            self._page.keyboard.press("ArrowRight")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # DM okuma / gönderme
    # ------------------------------------------------------------------ #
    def dm_gonder(self, handle: str, metin: str) -> bool:
        try:
            self._git(f"{IG_TABAN}/direct/t/{handle}/", bekle=2.0)
            # handle bir thread id olmayabilir; güvenli yol: profilden mesaj başlat
            if self._page.query_selector(S.MESAJ_KUTUSU) is None:
                if not self._profilden_mesaj_ac(handle):
                    return False
            kutu = self._page.query_selector(S.MESAJ_KUTUSU)
            if not kutu:
                return False
            kutu.click()
            self._insan_yaz(kutu, metin)
            self._page.keyboard.press("Enter")
            time.sleep(self._rng.uniform(0.8, 1.8))
            return not self._engel_kontrol()
        except Exception:
            return False

    def _profilden_mesaj_ac(self, handle: str) -> bool:
        try:
            self._git(f"{IG_TABAN}/{handle}/", bekle=1.5)
            for metin in ("Mesaj gönder", "Message", "Mesaj"):
                btn = self._page.query_selector(f'text="{metin}"')
                if btn:
                    btn.click()
                    time.sleep(self._rng.uniform(1.5, 3.0))
                    return self._page.query_selector(S.MESAJ_KUTUSU) is not None
            return False
        except Exception:
            return False

    def gelen_mesajlari_oku(self, limit: int = 10) -> list[dict]:
        """Inbox'taki en son `limit` thread'in son mesajını, karşıdan geldiyse döner.

        Döndürdüğü: [{'handle': str, 'text': str}]. IG DOM'una bağlı; kırılırsa
        S.THREAD_LISTE / seçicileri güncelle.
        """
        sonuc: list[dict] = []
        try:
            self._git(S.INBOX_URL, bekle=3.0)
            if self.checkpoint_var_mi():
                return []
            threadler = self._page.query_selector_all('a[href^="/direct/t/"]')[:limit]
            hedefler = []
            for t in threadler:
                href = t.get_attribute("href") or ""
                if href:
                    hedefler.append(href)
            for href in hedefler:
                if self.checkpoint_var_mi():
                    break
                veri = self._thread_son_geleni(href)
                if veri:
                    sonuc.append(veri)
                time.sleep(self._rng.uniform(0.8, 2.0))
        except Exception:
            pass
        return sonuc

    def _thread_son_geleni(self, thread_href: str) -> Optional[dict]:
        """Thread'in son mesajı KARŞI TARAFTAN geldiyse {'handle','text'} döner.

        Son mesaj bizimse (sağa hizalı balon) None döner — aksi halde bot kendi
        mesajını gelen sanıp kendine cevap yazar.
        """
        try:
            self._git(f"{IG_TABAN}{thread_href}", bekle=2.0)
            ana = self._page.query_selector(S.THREAD_ANA)
            if ana is None:
                return None
            handle = self._thread_handle(ana)
            if not handle:
                return None
            satirlar = ana.query_selector_all(S.MESAJ_SATIRI)
            for satir in reversed(satirlar[-5:]):
                metinler = satir.query_selector_all(S.MESAJ_METNI)
                if not metinler:
                    continue  # tarih ayırıcı / görsel vb.
                balon = metinler[-1]
                metin = (balon.inner_text() or "").strip()
                if not metin:
                    continue
                if self._bizim_balon_mu(satir, balon):
                    return None
                return {"handle": handle, "text": metin}
        except Exception:
            return None
        return None

    @staticmethod
    def _thread_handle(ana) -> str:
        """Sohbet başlığındaki profil linkinden karşı tarafın handle'ı."""
        for a in ana.query_selector_all('a[href^="/"]'):
            eslesme = _PROFIL_YOLU.match(a.get_attribute("href") or "")
            if eslesme and eslesme.group(1).lower() not in _AYRILMIS_YOLLAR:
                return eslesme.group(1)
        return ""

    @staticmethod
    def _bizim_balon_mu(satir, balon) -> bool:
        """Balon satırın sağ yarısındaysa mesaj bizimdir (IG gönderileni sağa hizalar)."""
        s_kutu = satir.bounding_box()
        b_kutu = balon.bounding_box()
        if not s_kutu or not b_kutu:
            return True  # emin değilsek gelen sayma (kendine cevap riskinden iyidir)
        satir_orta = s_kutu["x"] + s_kutu["width"] / 2
        balon_orta = b_kutu["x"] + b_kutu["width"] / 2
        return balon_orta > satir_orta
