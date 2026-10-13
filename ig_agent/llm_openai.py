"""OpenAI tabanlı LLMIstemci implementasyonu.

brain.LLMIstemci protokolünü uygular. openai>=1.0 SDK gerekir. Ayrıca zamanlayıcı
için opsiyonel `acilis_uret` (açılış metni çeşitlendirme) sağlar.
"""

from __future__ import annotations

import json
from typing import Sequence

from . import brain
from .config import Ayarlar

VARSAYILAN_ACILIS = (
    "Merhabalar, kolay gelsin! İşlerinizin takibini yapmak için "
    "herhangi bir program kullanıyor musunuz?"
)

# Açılışın nereye gittiğine göre sistem talimatının başı
ACILIS_BAGLAMI = {
    "hikaye": "Bir halı yıkama işletmesinin Instagram hikayesine yanıt olarak gidecek",
    "dm": (
        "Bir halı yıkama işletmesine Instagram'dan doğrudan mesaj (DM) olarak gidecek; "
        "hikayelerine atıf yapma, bizi tanımıyorlar"
    ),
    "tiktok_dm": (
        "Bir halı yıkama işletmesine TikTok'tan doğrudan mesaj olarak gidecek; "
        "videolarına atıf yapma, bizi tanımıyorlar"
    ),
}


class OpenAIIstemci:
    def __init__(self, ayarlar: Ayarlar):
        from openai import OpenAI  # gecikmeli import: dep yoksa yalnız burada patlar

        if not ayarlar.gpt.api_anahtari:
            raise RuntimeError("OPENAI_API_KEY tanımlı değil.")
        self._client = OpenAI(api_key=ayarlar.gpt.api_anahtari)
        self._ayarlar = ayarlar

    def arac_secimi(
        self, system: str, messages: Sequence[dict], tools: Sequence[dict]
    ) -> dict:
        g = self._ayarlar.gpt
        resp = self._client.chat.completions.create(
            model=g.model,
            messages=[{"role": "system", "content": system}, *messages],
            tools=list(tools),
            tool_choice="required",
            temperature=g.sicaklik,
            max_tokens=g.max_token,
        )
        mesaj = resp.choices[0].message
        cagrilar = getattr(mesaj, "tool_calls", None) or []
        if not cagrilar:
            # Model araç çağırmadıysa içeriği düz yanıt olarak ele al
            return {"name": brain.YAZ, "arguments": {"text": (mesaj.content or "").strip()}}
        fn = cagrilar[0].function
        try:
            args = json.loads(fn.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        return {"name": fn.name, "arguments": args}

    def acilis_uret(self, ayarlar: Ayarlar, lead, baglam: str = "hikaye") -> str:
        """Kısa, çeşitlendirilmiş bir açılış metni üretir."""
        try:
            isim = lead["business_name"] if lead["business_name"] else ""
        except (KeyError, IndexError, TypeError):
            isim = ""
        try:
            resp = self._client.chat.completions.create(
                model=ayarlar.gpt.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"{ACILIS_BAGLAMI.get(baglam, ACILIS_BAGLAMI['hikaye'])} "
                            "KISA, samimi bir açılış mesajı yaz. "
                            "Amaç: iş takibi için program kullanıp kullanmadıklarını sormak. "
                            "Tek cümle, esnaf diline uygun, satış yapma, sadece nazik soru. "
                            "Robotik/şablon durma; her seferinde biraz farklı ifade et."
                        ),
                    },
                    {"role": "user", "content": f"İşletme: {isim or 'bilinmiyor'}"},
                ],
                temperature=0.9,
                max_tokens=80,
            )
            metin = (resp.choices[0].message.content or "").strip()
            return metin or VARSAYILAN_ACILIS
        except Exception:
            return VARSAYILAN_ACILIS
