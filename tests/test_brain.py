"""brain.py saf mantık testleri (OpenAI olmadan)."""

from __future__ import annotations

from ig_agent import brain
from ig_agent.config import Ayarlar


def _lead(**kw):
    taban = {"business_name": "Sözeri Koltuk", "city": "Konya", "stage": "ilk_temas"}
    taban.update(kw)
    return taban


def test_sistem_prompt_deger_onerileri_ve_fiyat_icerir():
    p = brain.sistem_prompt(Ayarlar(), _lead())
    assert "Temizify" in p
    assert "ücretsiz" in p.lower()
    assert "600 TL" in p
    assert "Sözeri Koltuk" in p  # lead bağlamı
    assert "Konya" in p


def test_sistem_prompt_whatsapp_bilgisi():
    ayarlar = Ayarlar(whatsapp_numarasi="0555 555 55 55")
    p = brain.sistem_prompt(ayarlar, _lead())
    assert "0555 555 55 55" in p


def test_mesajlari_hazirla_rol_eslemesi():
    class Satir(dict):
        pass

    thread = [
        Satir(direction="story_reply", body="Kolay gelsin, program kullanıyor musunuz?"),
        Satir(direction="inbound", body="Hayır kullanmıyoruz"),
        Satir(direction="outbound", body="Anladım, kısaca anlatayım"),
        Satir(direction="inbound", body=""),  # boş → atlanmalı
    ]
    msgs = brain.mesajlari_hazirla(thread)
    assert msgs == [
        {"role": "assistant", "content": "Kolay gelsin, program kullanıyor musunuz?"},
        {"role": "user", "content": "Hayır kullanmıyoruz"},
        {"role": "assistant", "content": "Anladım, kısaca anlatayım"},
    ]


def test_arac_tanimlari_gecerli_semalar():
    araclar = brain.arac_tanimlari()
    adlar = {a["function"]["name"] for a in araclar}
    assert adlar == {
        brain.YAZ, brain.WHATSAPP, brain.DENEME,
        brain.DEVRET, brain.KES, brain.TAKIP,
    }
    for a in araclar:
        fn = a["function"]
        assert a["type"] == "function"
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"


def test_karari_coz_temel():
    k = brain.karari_coz(brain.YAZ, {"text": "  merhaba  ", "stage": "demo_atildi"})
    assert k.action == brain.YAZ
    assert k.text == "merhaba"  # trim
    assert k.stage == "demo_atildi"


def test_karari_coz_string_json_argumanlar():
    k = brain.karari_coz(brain.DENEME, '{"text":"harika","phone":"0543..."}')
    assert k.action == brain.DENEME
    assert k.text == "harika"
    assert k.phone == "0543..."


def test_karari_coz_gecersiz_asama_yok_sayilir():
    k = brain.karari_coz(brain.YAZ, {"text": "x", "stage": "uçan_asama"})
    assert k.stage is None


def test_karari_coz_bozuk_json():
    k = brain.karari_coz(brain.YAZ, "{bozuk")
    assert k.action == brain.YAZ
    assert k.text == ""


def test_karar_ver_sahte_istemci():
    class SahteIstemci:
        def __init__(self):
            self.gorulen = None

        def arac_secimi(self, system, messages, tools):
            self.gorulen = (system, messages, tools)
            return {"name": brain.DENEME, "arguments": {"text": "kaydınızı açalım", "phone": "0543"}}

    istemci = SahteIstemci()
    thread = [type("R", (dict,), {})(direction="inbound", body="olur deneyelim")]
    karar = brain.karar_ver(istemci, Ayarlar(), _lead(), thread)
    assert karar.action == brain.DENEME
    assert karar.phone == "0543"
    # sistem promptu ve araçlar istemciye geçti mi
    assert "Temizify" in istemci.gorulen[0]
    assert len(istemci.gorulen[2]) == 6
