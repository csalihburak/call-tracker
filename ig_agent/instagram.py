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

import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .platformlar import TURU_BITIR, GonderimSonucu, Hedef  # noqa: F401 — TURU_BITIR dışa verilir
from .tarayici import TAKIP_ONBELLEK_SN, TarayiciIstemci  # noqa: F401 — dışa verilir

IG_TABAN = "https://www.instagram.com"

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
    # Checkpoint yalnızca URL'den anlaşılır — sayfa metnini taramak ("doğrula",
    # "challenge" gibi kelimeler normal IG sayfasında da geçer) yanlış pozitif üretir.
    CHECKPOINT_YOLLARI = ("/challenge", "/checkpoint", "/accounts/suspended")

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

    # Takip listesi (kendi profil → "Takip" penceresi)
    def takip_url(kullanici: str) -> str:  # type: ignore[misc]
        return f"{IG_TABAN}/{kullanici}/following/"

    PROFIL_NAV_LINK = ['a[role="link"]:has-text("Profil")', 'a[role="link"]:has-text("Profile")']
    # Takip penceresinin altındaki öneri bölümü başlıkları (küçük harf, tr-TR) —
    # buradan sonrası takip ETMEDİĞİMİZ hesaplardır
    ONERILEN_BASLIK = ["önerilenler", "senin için önerilenler", "suggested for you",
                       "suggestions for you"]

    # Profilde "Mesaj gönder" yoksa: /direct/new/ akışı
    YENI_MESAJ_URL = f"{IG_TABAN}/direct/new/"
    YENI_MESAJ_ARAMA = ('input[name="queryBox"], div[role="dialog"] input[placeholder*="Ara"], '
                        'div[role="dialog"] input[placeholder*="Search"]')
    YENI_MESAJ_SOHBET_METIN = ["Sohbet", "Chat", "İleri", "Next"]
    # Instagram'ın açık "bu hesaba mesaj gönderilemez" metinleri (küçük harfle aranır)
    DM_KAPALI_METIN = ["mesaj gönderemezsin", "mesaj gönderemezsiniz",
                       "can't message", "cannot message", "isn't accepting messages"]

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


class InstagramClient(TarayiciIstemci):
    """Yaşam döngüsü, `_git`, `_insan_yaz`, checkpoint/engel tespiti, takip
    listesi önbelleği ve `acilis_turu` döngüsü `TarayiciIstemci`'dedir."""

    platform = "instagram"
    LOG_ONEK = "ig"
    S = S

    # ------------------------------------------------------------------ #
    # Durum tespiti
    # ------------------------------------------------------------------ #
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
    # Takip listesi turu (takip ettiklerimize direkt DM)
    # ------------------------------------------------------------------ #
    def kendi_kullanici_adi(self) -> str:
        """Ayarda verilmişse o; yoksa sol menüdeki "Profil" bağlantısından."""
        ayarli = (getattr(self._ayarlar, "kendi_kullanici_adi", "") or "").strip().lstrip("@")
        if ayarli:
            return ayarli
        try:
            self._git(IG_TABAN)
            for secici in S.PROFIL_NAV_LINK:
                el = self._page.query_selector(secici)
                if not el:
                    continue
                eslesme = _PROFIL_YOLU.match(el.get_attribute("href") or "")
                if eslesme and eslesme.group(1).lower() not in _AYRILMIS_YOLLAR:
                    return eslesme.group(1)
        except Exception:
            pass
        return ""

    def _takip_listesini_kazi(self, max_hesap: int = 5000) -> list[str]:
        """Kendi "Takip" penceremizi sonuna kadar kaydırıp kullanıcı adlarını toplar.

        Profil açılınca pencere kapandığından liste gönderimden ÖNCE tamamen
        toplanır. 4 kaydırmada yeni hesap gelmezse liste bitmiş sayılır.
        """
        kendi = self.kendi_kullanici_adi()
        if not kendi:
            print("[ig] ⚠️ kendi kullanıcı adı bulunamadı — panelden girin")
            return []
        toplanan: list[str] = []
        try:
            self._git(S.takip_url(kendi), bekle=3.0)
            gorulen: set[str] = set()
            bos_kaydirma = 0
            while len(toplanan) < max_hesap and bos_kaydirma < 4:
                dialog = self._page.query_selector(S.DIALOG)
                if dialog is None:
                    break
                yeni = 0
                for yol in self._diyalog_profil_yollari(dialog):
                    eslesme = _PROFIL_YOLU.match(yol)
                    if not eslesme:
                        continue
                    h = eslesme.group(1)
                    if h.lower() in _AYRILMIS_YOLLAR or h == kendi or h in gorulen:
                        continue
                    gorulen.add(h)
                    toplanan.append(h)
                    yeni += 1
                bos_kaydirma = 0 if yeni else bos_kaydirma + 1
                self._diyalogu_kaydir(dialog)
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
    def _diyalog_profil_yollari(dialog) -> list[str]:
        """Penceredeki `/…` bağlantılarını DOM sırasıyla döner.

        "Önerilenler / Suggested for you" başlığına gelince durur: oradan
        sonrası takip etmediğimiz öneri hesaplarıdır.
        """
        return dialog.evaluate(
            """(d, basliklar) => {
                const yollar = [];
                const gez = document.createTreeWalker(d, NodeFilter.SHOW_ELEMENT);
                for (let e = gez.currentNode; e; e = gez.nextNode()) {
                    if (e.children.length === 0) {
                        const t = (e.textContent || '').trim().toLocaleLowerCase('tr-TR');
                        if (basliklar.includes(t)) break;
                    }
                    if (e.tagName === 'A') {
                        const h = e.getAttribute('href') || '';
                        if (h.startsWith('/')) yollar.push(h);
                    }
                }
                return yollar;
            }""",
            S.ONERILEN_BASLIK,
        )

    def _hedef(self, handle: str) -> Hedef:
        return Hedef(handle=handle, profile_url=f"{IG_TABAN}/{handle}/", kaynak="takip_listesi")

    def _dm_gonder_sonuc(self, handle: str, metin: str) -> GonderimSonucu:
        """Profil (yoksa /direct/new/) üzerinden sohbet açıp yazar.

        DM_KAPALI yalnızca sayfada açık bir "mesaj gönderilemez" metni varsa
        döner; seçici bulunamaması BASARISIZ'dır (yanlışlıkla toplu DNC olmasın).
        """
        try:
            if not (self._profilden_mesaj_ac(handle) or self._yeni_mesajdan_ac(handle)):
                return GonderimSonucu.DM_KAPALI if self._dm_kapali_uyarisi() \
                    else GonderimSonucu.BASARISIZ
            kutu = self._page.query_selector(S.MESAJ_KUTUSU)
            if not kutu:
                return GonderimSonucu.BASARISIZ
            if self._sohbette_mesaj_var():
                return GonderimSonucu.ONCEKI_SOHBET  # telefondan/elle yazışılmış
            kutu.click()
            self._insan_yaz(kutu, metin)
            self._page.keyboard.press("Enter")
            time.sleep(self._rng.uniform(0.8, 1.8))
            if self._engel_kontrol():
                return GonderimSonucu.BASARISIZ
            if self._dm_kapali_uyarisi():
                return GonderimSonucu.DM_KAPALI
            return GonderimSonucu.GONDERILDI
        except Exception:
            return GonderimSonucu.BASARISIZ

    def _yeni_mesajdan_ac(self, handle: str) -> bool:
        """/direct/new/ → kullanıcı adını ara → sonucu seç → "Sohbet"."""
        try:
            self._git(S.YENI_MESAJ_URL, bekle=2.0)
            ara = self._page.query_selector(S.YENI_MESAJ_ARAMA)
            if not ara:
                return False
            ara.click()
            self._insan_yaz(ara, handle)
            time.sleep(self._rng.uniform(2.0, 3.5))
            secim = self._page.query_selector(f'{S.DIALOG} :text-is("{handle}")')
            if not secim:
                return False
            secim.click()
            time.sleep(self._rng.uniform(0.8, 1.5))
            for etiket in S.YENI_MESAJ_SOHBET_METIN:
                btn = self._page.query_selector(f'{S.DIALOG} div[role="button"]:has-text("{etiket}")')
                if btn:
                    btn.click()
                    time.sleep(self._rng.uniform(1.5, 3.0))
                    break
            return self._page.query_selector(S.MESAJ_KUTUSU) is not None
        except Exception:
            return False

    def _sohbette_mesaj_var(self) -> bool:
        """Açılan sohbette metinli bir mesaj satırı var mı (önceden yazışılmış mı)?"""
        try:
            ana = self._page.query_selector(S.THREAD_ANA)
            if ana is None:
                return False
            for satir in ana.query_selector_all(S.MESAJ_SATIRI):
                for el in satir.query_selector_all(S.MESAJ_METNI):
                    if (el.inner_text() or "").strip():
                        return True
        except Exception:
            pass
        return False

    def _dm_kapali_uyarisi(self) -> bool:
        return self._sayfada_metin_var(S.DM_KAPALI_METIN)

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
