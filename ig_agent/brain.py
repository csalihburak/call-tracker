"""GPT satış beyni — bir DM thread'i için sıradaki aksiyonu üretir.

Tasarım: model her tur *tam olarak bir* araç çağırır. Aracın kendisi hem
müşteriye yazılacak metni hem de yan etkileri (aşama/itiraz etiketi, deneme
önerisi, insana devir, iletişim kesme) taşır. Böylece çok turlu ajan döngüsüne
gerek kalmaz; karar tek, deterministik ve test edilebilir olur.

LLM çağrısı `LLMIstemci` protokolü ardına gizlenir; testler sahte istemci
enjekte eder, üretim `OpenAIIstemci` kullanır.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Sequence

# Aksiyon türleri
YAZ = "musteriye_yaz"
WHATSAPP = "whatsappa_yonlendir"
DENEME = "deneme_oner"
DEVRET = "insana_devret"
KES = "iletisimi_kes"
TAKIP = "bekle_takip"

GECERLI_ASAMALAR = ("yeni", "ilk_temas", "demo_atildi", "deneme", "musteri", "kayip")


# --------------------------------------------------------------------------- #
# Karar modeli
# --------------------------------------------------------------------------- #
@dataclass
class AjanKarari:
    action: str
    text: str = ""  # müşteriye gönderilecek DM (varsa)
    stage: Optional[str] = None  # aşama etiketi güncellemesi
    outcome: Optional[str] = None  # sonuç etiketi (ilgili/ilgisiz/...)
    objection: Optional[str] = None  # kaydedilecek itiraz
    phone: Optional[str] = None  # deneme için alınan telefon
    reason: Optional[str] = None  # devir/kesme sebebi
    follow_up: Optional[str] = None  # takip zamanı/notu
    ham: dict = field(default_factory=dict)  # ham argümanlar (denetim için)


class LLMIstemci(Protocol):
    def arac_secimi(
        self,
        system: str,
        messages: Sequence[dict],
        tools: Sequence[dict],
    ) -> dict:
        """{'name': str, 'arguments': dict} döner (modelin seçtiği tek araç)."""
        ...


# --------------------------------------------------------------------------- #
# Playbook / sistem promptu
# --------------------------------------------------------------------------- #
DEGER_ONERILERI = (
    "Temizify, halı yıkama işletmeleri için tek ekrandan yönetim sunar: "
    "sahada telefondan sipariş/müşteri kaydı, tek tık etiket çıktısı, müşteriye "
    "otomatik WhatsApp bilgilendirmesi, anlık gelir-gider/ciro takibi ve daha çok "
    "Google yorumu toplama."
)

FIYAT_NOTU = (
    "Lansmana özel aylık kullanım 600 TL (KDV dahil), tüm özellikler dahil. "
    "Ama önce her zaman TAMAMEN ÜCRETSİZ deneme hesabı öneriyoruz — risk yok."
)

ITIRAZ_REHBERI = """İtiraz kütüphanesi:
- "İhtiyacım yok / şu an kullanmıyorum": Nazik ol, ısrar etme. Sadece günlük işleri
  dijitalde tutmanın ve 'bugün ne kazandık'ı tek tıkla görmenin faydasını hatırlat,
  kapıyı açık bırak, ücretsiz deneme öner.
- "Zaten başka firma/program kullanıyoruz": Saygı göster; farkı (WhatsApp otomasyonu,
  saha kullanımı, yorum toplama) ve ücretsiz deneme ile kıyas fırsatını vurgula.
- "Karmaşık/fazla görünüyor": Sadeleştir — sadece iş kaydı + günlük ciro gibi temel
  özelliklerle risksiz başlanabileceğini söyle.
- "Fiyat yüksek": Önce ücretsiz denemeyi öne çıkar; sonra lansman fiyatını belirt."""

HEDEF_AKIS = """Amaç: Önce nitelendir (takip için program kullanıyorlar mı?). Sonra
değeri kısaca anlat, itirazları karşıla ve ÜCRETSİZ DENEME hesabına ikna et. Kişi
kabul edince / telefon numarasını verince `deneme_oner` aracını çağır (metinde
'kaydınızı oluşturup 1 aylık ücretsiz denemeyi tanımlayalım' de) ve varsa numarayı
`phone` ile ilet — hesabı operatör açacak. WhatsApp'tan devam etmek isterlerse veya
detay/görsel gerekiyorsa `whatsappa_yonlendir` kullan."""

USLUP = """Üslup: Türkçe, samimi ve esnafa uygun; kısa tut (1-3 cümle, WhatsApp/DM
dili). Ölçülü emoji. Asla ısrarcı/agresif olma; net 'hayır'a saygı göster. Spam
gibi durma, robotik tekrar etme. Kişinin son mesajına gerçekten cevap ver."""


def sistem_prompt(ayarlar, lead=None) -> str:
    """Satış playbook'unu içeren sistem promptunu üretir."""
    wa = ""
    if getattr(ayarlar, "whatsapp_numarasi", "") or getattr(ayarlar, "whatsapp_link", ""):
        wa = (
            f"\n\nWhatsApp iletişim: numara={ayarlar.whatsapp_numarasi or '-'} "
            f"link={ayarlar.whatsapp_link or '-'}"
        )
    lead_baglam = ""
    if lead is not None:
        isim = lead["business_name"] if _has(lead, "business_name") else ""
        sehir = lead["city"] if _has(lead, "city") else ""
        asama = lead["stage"] if _has(lead, "stage") else ""
        lead_baglam = (
            f"\n\nHedef işletme: {isim or '-'} "
            f"(şehir: {sehir or '-'}, mevcut aşama: {asama or '-'})."
        )

    return (
        "Sen Temizify'ın Instagram üzerinden çalışan Türkçe satış temsilcisisin. "
        "Halı yıkama işletmelerine uygulamayı tanıtıp ücretsiz denemeye "
        "ikna ediyorsun.\n\n"
        f"{DEGER_ONERILERI}\n\n{FIYAT_NOTU}\n\n{HEDEF_AKIS}\n\n{ITIRAZ_REHBERI}\n\n"
        f"{USLUP}"
        f"{wa}{lead_baglam}\n\n"
        "Her yanıtında MUTLAKA araçlardan tam olarak birini çağır."
    )


def _has(satir, anahtar: str) -> bool:
    try:
        return satir[anahtar] is not None
    except (KeyError, IndexError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# Konuşma geçmişi → LLM mesajları
# --------------------------------------------------------------------------- #
def mesajlari_hazirla(thread_mesajlari: Sequence) -> list[dict]:
    """ig_messages satırlarını OpenAI chat mesaj formatına çevirir.

    Bizim gönderdiğimiz (outbound/story_reply) → assistant, karşıdan gelen
    (inbound) → user.
    """
    sonuc: list[dict] = []
    for m in thread_mesajlari:
        yon = m["direction"]
        govde = (m["body"] or "").strip()
        if not govde:
            continue
        rol = "user" if yon == "inbound" else "assistant"
        sonuc.append({"role": rol, "content": govde})
    return sonuc


# --------------------------------------------------------------------------- #
# Araç tanımları (OpenAI function-calling şeması)
# --------------------------------------------------------------------------- #
def _fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_ORTAK_ETIKET = {
    "stage": {
        "type": "string",
        "enum": list(GECERLI_ASAMALAR),
        "description": "Konuşmanın vardığı aşama (opsiyonel güncelleme).",
    },
    "outcome": {
        "type": "string",
        "description": "Sonuç etiketi: ilgili/ilgisiz/tekrar_ara vb. (opsiyonel).",
    },
    "objection": {
        "type": "string",
        "description": "Kişinin dile getirdiği itiraz (varsa).",
    },
}


def arac_tanimlari() -> list[dict]:
    return [
        _fn(
            YAZ,
            "Müşteriye normal bir DM cevabı gönder. Sohbeti sürdürmek, nitelendirmek "
            "veya itiraz karşılamak için varsayılan araç.",
            {
                "text": {"type": "string", "description": "Gönderilecek DM metni."},
                **_ORTAK_ETIKET,
            },
            ["text"],
        ),
        _fn(
            WHATSAPP,
            "Kişiyi WhatsApp'a yönlendir (detay/görsel istediklerinde veya oradan "
            "devam etmek istediklerinde). Metinde WhatsApp bilgisini ver.",
            {"text": {"type": "string"}, **_ORTAK_ETIKET},
            ["text"],
        ),
        _fn(
            DENEME,
            "Kişi ücretsiz denemeyi kabul etti / telefon verdi. Operatöre bildirim "
            "gider, hesabı insan açar. Onaylayıcı bir mesaj yaz ve numarayı ilet.",
            {
                "text": {"type": "string"},
                "phone": {"type": "string", "description": "Alınan telefon (varsa)."},
                **_ORTAK_ETIKET,
            },
            ["text"],
        ),
        _fn(
            DEVRET,
            "Konuşmayı bir insana devret (fiyat pazarlığı, şikayet/kızgınlık, "
            "'insanla konuşayım' talebi veya emin olamadığın durum). AI bu thread'de "
            "durur.",
            {
                "reason": {"type": "string"},
                "text": {"type": "string", "description": "Devirden önce isteğe bağlı kısa mesaj."},
            },
            ["reason"],
        ),
        _fn(
            KES,
            "İletişimi kes (net 'ilgilenmiyorum', 'rahatsız etmeyin', engelleme "
            "sinyali, opt-out). Bu kişiye bir daha yazılmaz.",
            {"reason": {"type": "string"}, "outcome": {"type": "string"}},
            ["reason"],
        ),
        _fn(
            TAKIP,
            "Şimdi uygun değil ama sonra ('şu an meşgulüm', 'sonra yazın'). İsteğe "
            "bağlı kısa mesaj yaz ve takip zamanını/notunu belirt.",
            {
                "text": {"type": "string"},
                "follow_up": {"type": "string", "description": "Ne zaman/not."},
                **_ORTAK_ETIKET,
            },
            ["follow_up"],
        ),
    ]


# --------------------------------------------------------------------------- #
# Karar çözme
# --------------------------------------------------------------------------- #
def karari_coz(name: str, arguments: Any) -> AjanKarari:
    """Modelin döndürdüğü araç adı + argümanları AjanKarari'ye çevirir."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}

    stage = arguments.get("stage")
    if stage is not None and stage not in GECERLI_ASAMALAR:
        stage = None  # geçersiz aşamayı yok say

    return AjanKarari(
        action=name,
        text=(arguments.get("text") or "").strip(),
        stage=stage,
        outcome=arguments.get("outcome"),
        objection=arguments.get("objection"),
        phone=arguments.get("phone"),
        reason=arguments.get("reason"),
        follow_up=arguments.get("follow_up"),
        ham=arguments,
    )


def karar_ver(istemci: LLMIstemci, ayarlar, lead, thread) -> AjanKarari:
    """Bir thread için LLM'e danışıp AjanKarari üretir (üst katman için tek giriş)."""
    system = sistem_prompt(ayarlar, lead)
    messages = mesajlari_hazirla(thread)
    tools = arac_tanimlari()
    secim = istemci.arac_secimi(system, messages, tools)
    return karari_coz(secim.get("name", YAZ), secim.get("arguments", {}))
