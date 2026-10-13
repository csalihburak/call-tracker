"""TikTok web otomasyonu (Playwright, headful, kalıcı profil `.tiktok_profile`).

Yalnızca açılış: takip ettiğimiz hesapları "Takip edilen" penceresinden toplar,
her birine profildeki "Mesaj" düğmesiyle ilk mesajı yazar. Gelen kutusu okuma
ve yanıt bu istemcide YOK (spec: kapsam dışı).

ÖNEMLİ: TikTok DOM'u sık değişir. Tüm seçiciler aşağıdaki `S` sınıfındadır —
kırılırsa yalnızca orayı güncelle. ✔ işaretliler 2026-10-13'te herkese açık bir
profilde doğrulandı; diğerleri ilk canlı turda doğrulanmalı.

CAPTCHA / doğrulama ÇÖZÜLMEZ: algılanınca `checkpoint_var_mi()` True döner ve
üst katman yalnızca TikTok botunu duraklatır; kullanıcı tarayıcıdan çözer.

İlk çalıştırmada TARAYICI AÇILIR ve SEN GİRİŞ YAPARSIN. Oturum kalıcı profilde
saklanır. İstemci DB'ye dokunmaz; sonuçları `GonderimSonucu` ile döner.
"""

from __future__ import annotations

import re
import time
from typing import Optional

from .platformlar import GonderimSonucu, Hedef
from .tarayici import TarayiciIstemci

TIKTOK_TABAN = "https://www.tiktok.com"

# Profil bağlantısı: /@kullanici (ardından isteğe bağlı ?lang=…). Video vb. alt
# yollar (/@x/video/1) eşleşmez. TikTok kullanıcı adı: harf, rakam, _ ve . (2–24).
_KULLANICI_YOLU = re.compile(r"^/@([A-Za-z0-9._]{2,24})/?(?:\?.*)?$")


class S:
    """Merkezî seçiciler (TikTok değişince burayı güncelle)."""

    # "İşlem engellendi" türü uyarıların arandığı kapsayıcılar (TikTok çoğunlukla
    # toast gösterir) ve metinleri (küçük harfle aranır)
    DIALOG = 'div[role="dialog"], div[role="alert"], [data-e2e*="toast"]'
    ENGEL_METIN = ["çok hızlı", "too fast", "çok fazla istek", "too many requests",
                   "try again later", "daha sonra tekrar dene", "maximum number of attempts"]

    # Doğrulama: URL'de bunlar varsa ya da CAPTCHA öğesi/metni görünürse checkpoint
    CHECKPOINT_YOLLARI = ("/login", "/verify", "/captcha")
    CAPTCHA = ('#captcha-verify-image, #captcha_container, .captcha_verify_container, '
               '[class*="captcha-verify"], [id^="captcha"], iframe[src*="captcha"]')
    CAPTCHA_METIN = ["bulmacayı tamamla", "kaydırıcıyı sürükle", "drag the slider",
                     "fit the puzzle", "verify to continue"]

    # Giriş yapılmamışsa üst çubukta "Oturum aç" düğmesi olur ✔
    GIRIS_DUGMESI = '[data-e2e="top-login-button"], #header-login-button, #top-right-login-button'
    # Sol menüdeki "Profil" bağlantısı ✔ (çıkışta href="/@?lang=…")
    PROFIL_NAV_LINK = '[data-e2e="nav-profile"]'

    # Profil sayfası ✔
    PROFIL_YUKLENDI = '[data-e2e="user-title"], [data-e2e="user-subtitle"]'
    TAKIP_EDILEN_SAYISI = '[data-e2e="following-count"], [data-e2e="following"]'
    MESAJ_DUGMESI = ['[data-e2e="message-button"]', 'button:text-is("Mesaj")',
                     'button:text-is("Message")']

    # "Takip edilen" penceresi
    TAKIP_PENCERESI = '[data-e2e="follow-info-popup"], div[role="dialog"]'

    # Sohbet sayfası
    MESAJ_KUTUSU = ('[data-e2e="message-input-area"] [contenteditable="true"], '
                    'div[contenteditable="true"][role="textbox"], '
                    '.public-DraftEditor-content, div[contenteditable="true"]')
    MESAJ_OGESI = '[data-e2e="chat-item"]'
    # TikTok'un açık "bu hesaba mesaj gönderilemez" metinleri (küçük harfle aranır)
    DM_KAPALI_METIN = ["mesaj gönderemezsiniz", "mesaj gönderemezsin", "mesaj gönderilemiyor",
                       "can't send messages", "cannot send messages", "can't message",
                       "isn't accepting messages", "mesaj almıyor"]


class TikTokClient(TarayiciIstemci):
    platform = "tiktok"
    LOG_ONEK = "tiktok"
    S = S
    # "Mesaj"a tıkladıktan sonra sohbet kutusunun gelmesi için en fazla bekleme
    KUTU_BEKLEME_MS = 12_000

    def __init__(self, ayarlar):
        super().__init__(ayarlar)
        # Profilinde "Mesaj" düğmesi görünmeyen hesaplar bu süreç boyunca atlanır
        # (tur her seferinde aynı hesaplarda tıkanmasın). DNC'ye yazılmaz: seçici
        # kırılması kalıcı iz bırakmasın; süreç yeniden başlayınca tekrar denenir.
        self._dugmesiz: set[str] = set()

    # ------------------------------------------------------------------ #
    # Durum tespiti
    # ------------------------------------------------------------------ #
    def giris_yapildi_mi(self) -> bool:
        # Yalnızca TikTok'ta değilsek ana sayfaya git: giriş beklenirken her
        # kontrolde sayfayı yenilemek kullanıcının yazdığı formu / CAPTCHA'yı siler
        if not (self._page.url or "").startswith(TIKTOK_TABAN):
            self._git(TIKTOK_TABAN)
        if self.checkpoint_var_mi():
            return False
        return self._page.query_selector(S.GIRIS_DUGMESI) is None

    def _checkpoint_ekrani_var(self) -> bool:
        """Kaydırmalı bulmaca / doğrulama ekranı (URL değişmeden çıkar). Yalnızca
        GÖRÜNÜR öğe sayılır: önceden yüklenmiş gizli kapsayıcı botu duraklatmasın."""
        try:
            for el in self._page.query_selector_all(S.CAPTCHA):
                kutu = el.bounding_box() if el.is_visible() else None
                if kutu and kutu["width"] > 0 and kutu["height"] > 0:
                    return True
        except Exception:
            pass
        return self._sayfada_metin_var(S.CAPTCHA_METIN)

    # ------------------------------------------------------------------ #
    # Takip listesi
    # ------------------------------------------------------------------ #
    def kendi_kullanici_adi(self) -> str:
        """Ayarda verilmişse o; yoksa sol menüdeki "Profil" bağlantısından."""
        ayarli = (getattr(self._ayarlar, "kendi_kullanici_adi", "") or "").strip().lstrip("@")
        if ayarli:
            return ayarli
        try:
            self._git(TIKTOK_TABAN)
            el = self._page.query_selector(S.PROFIL_NAV_LINK)
            if el:
                eslesme = _KULLANICI_YOLU.match(el.get_attribute("href") or "")
                if eslesme:
                    return eslesme.group(1)
        except Exception:
            pass
        return ""

    def takip_listesi_topla(self) -> list[str]:
        """Önbellekli takip listesi; bu süreçte düğmesiz görülen hesaplar hariç."""
        return [h for h in super().takip_listesi_topla() if h not in self._dugmesiz]

    def _takip_listesini_kazi(self, max_hesap: int = 5000) -> list[str]:
        """Kendi profilimizde "Takip edilen" penceresini sonuna kadar kaydırıp
        kullanıcı adlarını toplar. 4 kaydırmada yeni hesap gelmezse liste bitmiştir."""
        kendi = self.kendi_kullanici_adi()
        if not kendi:
            print("[tiktok] ⚠️ kendi kullanıcı adı bulunamadı — panelden girin")
            return []
        toplanan: list[str] = []
        try:
            self._git(f"{TIKTOK_TABAN}/@{kendi}", bekle=3.0)
            sayi = self._page.query_selector(S.TAKIP_EDILEN_SAYISI)
            if sayi is None:
                print("[tiktok] ⚠️ 'Takip edilen' bulunamadı — S.TAKIP_EDILEN_SAYISI ayarlanmalı")
                return []
            sayi.click()
            time.sleep(self._rng.uniform(2.0, 3.5))
            gorulen: set[str] = set()
            bos_kaydirma = 0
            while len(toplanan) < max_hesap and bos_kaydirma < 4:
                if self.checkpoint_var_mi():
                    break
                pencere = self._page.query_selector(S.TAKIP_PENCERESI)
                if pencere is None:
                    break
                yeni = 0
                for h in self._pencere_kullanicilari(pencere):
                    if h.lower() == kendi.lower() or h in gorulen:
                        continue
                    gorulen.add(h)
                    toplanan.append(h)
                    yeni += 1
                bos_kaydirma = 0 if yeni else bos_kaydirma + 1
                self._diyalogu_kaydir(pencere)
                time.sleep(self._rng.uniform(1.2, 2.5))
        except Exception:
            pass
        finally:
            try:
                self._page.keyboard.press("Escape")
            except Exception:
                pass
        return toplanan[:max_hesap]

    @staticmethod
    def _pencere_kullanicilari(pencere) -> list[str]:
        """Penceredeki profil bağlantılarının kullanıcı adları (DOM sırasıyla)."""
        hrefler = pencere.evaluate(
            "p => [...p.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))"
        )
        sonuc = []
        for href in hrefler:
            eslesme = _KULLANICI_YOLU.match((href or "").removeprefix(TIKTOK_TABAN))
            if eslesme:
                sonuc.append(eslesme.group(1))
        return sonuc

    def _hedef_uygun_mu(self, handle: str) -> bool:
        """Tempo beklemesinden ÖNCE profile bakar. "Mesaj" düğmesi yoksa (ve açık
        "mesaj gönderilemez" metni de yoksa) hesap bu süreç boyunca atlanır —
        tempo, sonuç bildirimi ve art arda başarısız sayacı harcanmaz."""
        if self._mesaj_dugmesi_var_mi(handle) is False and not self._dm_kapali_uyarisi():
            self._dugmesiz.add(handle)
            time.sleep(self._rng.uniform(2.0, 5.0))  # profilleri art arda hızla gezme
            return False
        return True

    def _hedef(self, handle: str) -> Hedef:
        return Hedef(handle=handle, profile_url=f"{TIKTOK_TABAN}/@{handle}", kaynak="takip_listesi")

    # ------------------------------------------------------------------ #
    # DM
    # ------------------------------------------------------------------ #
    def _dm_gonder_sonuc(self, handle: str, metin: str) -> GonderimSonucu:
        """Profildeki "Mesaj" düğmesiyle sohbet açıp yazar.

        DM_KAPALI yalnızca sayfada açık bir "mesaj gönderilemez" metni varsa
        döner; düğme/kutu bulunamaması BASARISIZ'dır (yanlışlıkla toplu DNC olmasın).
        """
        try:
            acildi = self._profilden_mesaj_ac(handle)
            if not acildi:
                if acildi is False:
                    self._dugmesiz.add(handle)
                return GonderimSonucu.DM_KAPALI if self._dm_kapali_uyarisi() \
                    else GonderimSonucu.BASARISIZ
            if self._sohbette_mesaj_var():
                return GonderimSonucu.ONCEKI_SOHBET  # telefondan/elle yazışılmış
            return self._mesaj_yaz(metin)
        except Exception:
            return GonderimSonucu.BASARISIZ

    def _profile_git(self, handle: str) -> None:
        """Profil sayfasına git (zaten oradaysak — ön kontrolden kalma — yenileme)."""
        yol = (self._page.url or "").removeprefix(TIKTOK_TABAN).split("?")[0].rstrip("/")
        if yol != f"/@{handle}":
            self._git(f"{TIKTOK_TABAN}/@{handle}", bekle=1.5)

    def _mesaj_dugmesi(self):
        for secici in S.MESAJ_DUGMESI:
            btn = self._page.query_selector(secici)
            if btn:
                return btn
        return None

    def _mesaj_dugmesi_var_mi(self, handle: str) -> Optional[bool]:
        """True: düğme var · False: profil yüklendi, düğme yok · None: belirsiz."""
        try:
            self._profile_git(handle)
            if self._mesaj_dugmesi() is not None:
                return True
            return False if self._page.query_selector(S.PROFIL_YUKLENDI) is not None else None
        except Exception:
            return None

    def _profilden_mesaj_ac(self, handle: str) -> Optional[bool]:
        """True: mesaj kutusu açıldı · False: profil yüklendi ama "Mesaj" düğmesi
        yok · None: profil yüklenmedi ya da düğme kutuyu açmadı (geçici sayılır)."""
        try:
            self._profile_git(handle)
            btn = self._mesaj_dugmesi()
            if btn is None:
                return False if self._page.query_selector(S.PROFIL_YUKLENDI) is not None else None
            btn.click()
            try:
                # Sohbet sayfası ağır yüklenebilir; kutu gelene kadar bekle
                self._page.wait_for_selector(S.MESAJ_KUTUSU, state="attached",
                                             timeout=self.KUTU_BEKLEME_MS)
            except Exception:
                return None
            time.sleep(self._rng.uniform(1.0, 2.0))
            return True
        except Exception:
            return None

    def _mesaj_yaz(self, metin: str) -> GonderimSonucu:
        kutu = self._page.query_selector(S.MESAJ_KUTUSU)
        if not kutu:
            return GonderimSonucu.BASARISIZ
        kutu.click()
        self._insan_yaz(kutu, metin)
        self._page.keyboard.press("Enter")
        time.sleep(self._rng.uniform(0.8, 1.8))
        if self._engel_kontrol():
            return GonderimSonucu.BASARISIZ
        if self._dm_kapali_uyarisi():
            return GonderimSonucu.DM_KAPALI
        return GonderimSonucu.GONDERILDI

    def _sohbette_mesaj_var(self) -> bool:
        """Açılan sohbette metinli bir mesaj var mı (önceden yazışılmış mı)?"""
        try:
            for el in self._page.query_selector_all(S.MESAJ_OGESI):
                if (el.inner_text() or "").strip():
                    return True
        except Exception:
            pass
        return False

    def _dm_kapali_uyarisi(self) -> bool:
        return self._sayfada_metin_var(S.DM_KAPALI_METIN)
