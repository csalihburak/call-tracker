"""TikTok web otomasyonu (Playwright, headful, kalıcı profil `.tiktok_profile`).

Yalnızca açılış: takip ettiğimiz hesapları "Takip edilen" penceresinden toplar,
her birine profildeki "Mesaj" düğmesiyle ilk mesajı yazar. Gelen kutusu okuma
ve yanıt bu istemcide YOK (spec: kapsam dışı).

ÖNEMLİ: TikTok DOM'u sık değişir. Tüm seçiciler aşağıdaki `S` sınıfındadır —
kırılırsa yalnızca orayı güncelle. ✔ işaretliler 2026-10-13'te temizify
oturumunda canlı doğrulandı.

İşletme hesabında "Mesaj" düğmesi Business Suite'e (`/business-suite/messages?u=<uid>`)
gider; sohbet orada bir iframe içindedir (`/messages?scene=business&u=<uid>`).
Sohbet kutusu hangi çerçevedeyse (iframe ya da ana sayfa) işlemler orada yapılır.
Yazmadan önce sohbet başlığındaki kullanıcı adının hedefle aynı olduğu doğrulanır.

CAPTCHA / doğrulama ÇÖZÜLMEZ: algılanınca `checkpoint_var_mi()` True döner ve
üst katman yalnızca TikTok botunu duraklatır; kullanıcı tarayıcıdan çözer.

İlk çalıştırmada TARAYICI AÇILIR ve SEN GİRİŞ YAPARSIN. Oturum kalıcı profilde
saklanır. İstemci DB'ye dokunmaz; sonuçları `GonderimSonucu` ile döner.
"""

from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import parse_qs, urlparse

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
    # ✔ Yalnızca bu: genel `div[role="dialog"]` DOM'da önce duran gizli
    # Bildirimler penceresini yakalıyordu (bizi beğenen/takip edenler)
    TAKIP_PENCERESI = '[data-e2e="follow-info-popup"]'

    # Sohbet (Business Suite'te iframe içinde) ✔
    MESAJ_KUTUSU = ('[data-e2e="message-input-area"] [contenteditable="true"], '
                    'div[contenteditable="true"][role="textbox"], '
                    '.public-DraftEditor-content, div[contenteditable="true"]')
    # Sohbet başlığındaki karşı tarafın kullanıcı adı ✔
    SOHBET_KIMLIGI = '[data-e2e="chat-uniqueid"]'
    # Sohbetteki herhangi bir mesaj (metinsiz çıkartma/video dahil) ✔
    MESAJ_OGESI = ('[data-e2e="dm-new-chat-item"], [data-e2e="dm-new-time-separator"], '
                   '[data-e2e="chat-item"]')
    # Sol sohbet listesindeki konuşma; id'si iki tarafın uid'ini içerir ✔
    KONUSMA_OGESI = '[data-e2e="dm-new-conversation-item"]'
    # Sohbet içi uyarı / alt bölüm ("mesaj gönderemezsiniz" burada aranır)
    SOHBET_UYARI = '[data-e2e="dm-warning"], [data-e2e="dm-new-chat-bottom"]'
    # TikTok'un açık "bu hesaba mesaj gönderilemez" metinleri (küçük harfle aranır)
    DM_KAPALI_METIN = ["mesaj gönderemezsiniz", "mesaj gönderemezsin", "mesaj gönderilemiyor",
                       "can't send messages", "cannot send messages", "can't message",
                       "isn't accepting messages", "mesaj almıyor"]


class TikTokClient(TarayiciIstemci):
    platform = "tiktok"
    LOG_ONEK = "tiktok"
    S = S
    # "Mesaj"a tıkladıktan sonra sohbet kutusunun gelmesi için en fazla bekleme
    KUTU_BEKLEME_MS = 20_000
    # Profil sayfasının (kullanıcı adı başlığı) yüklenmesi için en fazla bekleme
    PROFIL_BEKLEME_MS = 15_000

    def __init__(self, ayarlar):
        super().__init__(ayarlar)
        # Açık sohbetin çerçevesi (Business Suite'te iframe); yoksa None
        self._sohbet = None
        # Takip penceresinde görülen görünen adlar (kullanıcı adı → ad); açılış
        # metnini işletmeye göre seçmek için Hedef.ad'a taşınır
        self._adlar: dict[str, str] = {}
        # Profilinde "Mesaj" düğmesi görünmeyen hesaplar bu süreç boyunca atlanır
        # (tur her seferinde aynı hesaplarda tıkanmasın). DNC'ye yazılmaz: seçici
        # kırılması kalıcı iz bırakmasın; süreç yeniden başlayınca tekrar denenir.
        self._dugmesiz: set[str] = set()

    # ------------------------------------------------------------------ #
    # Durum tespiti
    # ------------------------------------------------------------------ #
    def _git(self, url: str, bekle: float = 2.5):
        """Kalıcı profil açılışta son sayfayı geri yükler; ilk geçiş `ERR_ABORTED`
        ile kesilebilir (canlıda görüldü) — bir kez daha dene."""
        try:
            super()._git(url, bekle)
        except Exception as hata:
            if "ERR_ABORTED" not in str(hata):
                raise
            time.sleep(self._rng.uniform(2.0, 4.0))
            super()._git(url, bekle)

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
                self._adlar.update(self._pencere_adlari(pencere))
                yeni = 0
                for h in self._pencere_kullanicilari(pencere):
                    if h.lower() == kendi.lower() or h in gorulen:
                        continue
                    gorulen.add(h)
                    toplanan.append(h)
                    yeni += 1
                bos_kaydirma = 0 if yeni else bos_kaydirma + 1
                self._pencereyi_kaydir(pencere)
                time.sleep(self._rng.uniform(2.0, 3.5))  # sonraki parti yüklensin
        except Exception:
            pass
        finally:
            try:
                self._page.keyboard.press("Escape")
            except Exception:
                pass
        return toplanan[:max_hesap]

    @staticmethod
    def _pencereyi_kaydir(pencere) -> None:
        """Listedeki son hesabı görünür alana getirir ve onu içeren ilk kaydırılabilir
        kapsayıcıyı (pencerenin içinde ya da dışında) sona kaydırır — tembel yükleme
        tetiklensin. Canlıda pencere kaydırılınca yalnızca ilk 30 hesap gelmişti."""
        pencere.evaluate(
            """p => {
                const linkler = p.querySelectorAll('a[href^="/@"]');
                const son = linkler[linkler.length - 1];
                if (!son) return;
                son.scrollIntoView({block: 'end'});
                // Kapsayıcı pencerenin içinde ya da dışında (üst öğe) olabilir
                for (let e = son.parentElement; e && e !== document.documentElement; e = e.parentElement) {
                    if (e.scrollHeight > e.clientHeight + 10 && getComputedStyle(e).overflowY !== 'visible') {
                        e.scrollTop = e.scrollHeight;
                        break;
                    }
                }
            }"""
        )

    @staticmethod
    def _pencere_adlari(pencere) -> dict[str, str]:
        """Penceredeki hesapların görünen adları: bağlantı metninde kullanıcı
        adından önceki satır (ör. "DAMLA HALİ&KOLTUK YIKAMA"). Adı olmayan atlanır."""
        bilgiler = pencere.evaluate(
            "p => [...p.querySelectorAll('a[href]')].map(a => [a.getAttribute('href'), a.innerText || ''])"
        )
        adlar: dict[str, str] = {}
        for href, metin in bilgiler:
            eslesme = _KULLANICI_YOLU.match((href or "").removeprefix(TIKTOK_TABAN))
            if not eslesme or eslesme.group(1) in adlar:
                continue
            h = eslesme.group(1)
            satirlar = [s.strip() for s in metin.splitlines() if s.strip()]
            ad = next((s for s in satirlar if s.lower() != h.lower()), "")
            if ad:
                adlar[h] = ad
        return adlar

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
        return Hedef(handle=handle, ad=self._adlar.get(handle, ""),
                     profile_url=f"{TIKTOK_TABAN}/@{handle}", kaynak="takip_listesi")

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
            if not self._sohbet_kimligi_dogru(handle):
                # u= tutmazsa listedeki başka bir sohbet açık olabilir — asla yazma
                print(f"[tiktok] ⚠️ @{handle}: açılan sohbet başka birine ait / kimlik okunamadı")
                return GonderimSonucu.BASARISIZ
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

    def _profil_yuklenmesini_bekle(self) -> None:
        try:
            self._page.wait_for_selector(S.PROFIL_YUKLENDI, state="attached",
                                         timeout=self.PROFIL_BEKLEME_MS)
        except Exception:
            pass  # yüklenmediyse çağıran None (belirsiz) döner

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
            self._profil_yuklenmesini_bekle()
            if self._mesaj_dugmesi() is not None:
                return True
            return False if self._page.query_selector(S.PROFIL_YUKLENDI) is not None else None
        except Exception:
            return None

    def _profilden_mesaj_ac(self, handle: str) -> Optional[bool]:
        """True: mesaj kutusu açıldı · False: profil yüklendi ama "Mesaj" düğmesi
        yok · None: profil yüklenmedi ya da düğme kutuyu açmadı (geçici sayılır)."""
        self._sohbet = None
        try:
            self._profile_git(handle)
            self._profil_yuklenmesini_bekle()
            btn = self._mesaj_dugmesi()
            if btn is None:
                return False if self._page.query_selector(S.PROFIL_YUKLENDI) is not None else None
            btn.click()
            # Sohbet sayfası (Business Suite + iframe) ağır yüklenir; kutu gelene kadar bekle
            self._sohbet = self._sohbet_cercevesini_bekle()
            if self._sohbet is None:
                return None
            # Geçmiş mesajlar kutudan sonra çizilir; kontrol etmeden önce bekle
            time.sleep(self._rng.uniform(2.0, 3.5))
            return True
        except Exception:
            return None

    def _sohbet_cercevesini_bekle(self):
        """Mesaj kutusunu içeren çerçeve (Business Suite'te iframe, değilse ana sayfa)."""
        bitis = time.monotonic() + self.KUTU_BEKLEME_MS / 1000
        while True:
            for cerceve in self._page.frames:
                try:
                    if cerceve.query_selector(S.MESAJ_KUTUSU) is not None:
                        return cerceve
                except Exception:
                    continue  # yüklenirken ayrılan iframe
            if time.monotonic() >= bitis:
                return None
            self._page.wait_for_timeout(300)

    def _sohbet_kimligi_dogru(self, handle: str) -> bool:
        """Sohbet başlığındaki kullanıcı adı hedefle aynı mı? Okunamazsa False."""
        try:
            el = self._sohbet.wait_for_selector(S.SOHBET_KIMLIGI, state="attached", timeout=5000)
            return (el.inner_text() or "").strip().lstrip("@").lower() == handle.lower()
        except Exception:
            return False

    def _sohbet_uid(self) -> str:
        """Açık sohbetin karşı taraf uid'i (iframe / sayfa adresindeki `u=`)."""
        for url in (getattr(self._sohbet, "url", ""), self._page.url):
            uid = parse_qs(urlparse(url or "").query).get("u", [""])[0]
            if uid.isdigit():
                return uid
        return ""

    def _mesaj_yaz(self, metin: str) -> GonderimSonucu:
        kutu = (self._sohbet or self._page).query_selector(S.MESAJ_KUTUSU)
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
        """Bu kişiyle önceden yazışılmış mı? İki sinyal: sohbette herhangi bir mesaj
        (metinsiz olanlar dahil) ya da sol listede hedefin uid'ini içeren konuşma.
        Okuma hatası yükselir → çağıran BASARISIZ sayar (DNC'ye yazılmaz)."""
        cerceve = self._sohbet or self._page
        if cerceve.query_selector(S.MESAJ_OGESI) is not None:
            return True
        uid = self._sohbet_uid()
        return bool(uid) and cerceve.query_selector(f'{S.KONUSMA_OGESI}[id*="{uid}"]') is not None

    def _dm_kapali_uyarisi(self) -> bool:
        """Sayfada ya da sohbetin uyarı/alt bölümünde açık "mesaj gönderilemez" metni.
        Sohbet çerçevesinin tamamı taranmaz: soldaki listede başka sohbetlerin
        önizlemeleri var."""
        if self._sayfada_metin_var(S.DM_KAPALI_METIN):
            return True
        if self._sohbet is None:
            return False
        try:
            metin = " ".join((el.inner_text() or "")
                             for el in self._sohbet.query_selector_all(S.SOHBET_UYARI)).lower()
            return any(k in metin for k in S.DM_KAPALI_METIN)
        except Exception:
            return False
