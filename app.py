import sqlite3
import time
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
from audio_recorder_streamlit import audio_recorder
from faster_whisper import WhisperModel
from wordcloud import WordCloud
import matplotlib.pyplot as plt

VERITABANI_YOLU = "sales.db"
SES_KLASORU = Path("audio_recordings")
ANA_RENK = "#4F46E5"
GUNLUK_HEDEF = 30

SEHIRLER = [
    "İstanbul", "Ankara", "İzmir", "Bursa", "Antalya", "Adana",
    "Konya", "Gaziantep", "Mersin", "Kayseri", "Diyarbakır",
    "Eskişehir", "Samsun", "Denizli", "Diğer"
]

ASAMALAR = ["yeni", "ilk_temas", "demo_atildi", "deneme", "musteri", "kayip"]

ASAMA_ETIKETLERI = {
    "yeni": "Yeni",
    "ilk_temas": "İlk Temas",
    "demo_atildi": "Demo Atıldı",
    "deneme": "Deneme",
    "musteri": "Müşteri",
    "kayip": "Kayıp",
}

ARAMA_SONUCLARI = [
    "ilgili",
    "demo_attim",
    "deneme_basladi",
    "odeme_yapti",
    "ilgisiz",
    "tekrar_ara",
    "mesgul",
]

ARAMA_SONUC_ETIKETLERI = {
    "ilgili": "İlgili",
    "demo_attim": "Demo Attım",
    "deneme_basladi": "Deneme Başladı",
    "odeme_yapti": "Ödeme Yaptı",
    "ilgisiz": "İlgisiz",
    "tekrar_ara": "Tekrar Ara",
    "mesgul": "Meşgul",
}

ITIRAZLAR = [
    "Fiyat çok yüksek",
    "Şu an bütçe yok",
    "Zaten başka firma kullanıyoruz",
    "İhtiyaç duymuyoruz",
    "Karar verici ben değilim",
    "Tekrar arayın",
    "Müşterilerim talep etmiyor",
    "Deneme yapmak istemiyorum",
    "Memnunum şu an",
]

SONUCTAN_ASAMAYA = {
    "ilgili": "ilk_temas",
    "demo_attim": "demo_atildi",
    "deneme_basladi": "deneme",
    "odeme_yapti": "musteri",
    "ilgisiz": "kayip",
}

KAYNAK_SECENEKLERI = [
    "Soğuk Arama",
    "Referans",
    "Google Haritalar",
    "Fuar",
    "Instagram",
    "Diğer",
]

TR_STOPWORDS = {
    "ve", "bir", "bu", "ile", "için", "da", "de", "mi", "mu", "mı", "mü", 
    "ama", "fakat", "o", "ne", "çok", "kadar", "daha", "en", "gibi", "ben", 
    "sen", "biz", "siz", "onlar", "evet", "hayır", "tamam", "olur", "yok", 
    "var", "merhaba", "iyi", "günler", "şey", "sonra", "diye", "göre"
}


@st.cache_resource
def fwhisper_modelini_getir():
    return WhisperModel("small", device="cpu", compute_type="int8")


def sesi_yaziya_cevir(dosya_yolu: str) -> str:
    model = fwhisper_modelini_getir()
    segmentler, bilgi = model.transcribe(dosya_yolu, language="tr")
    metin = " ".join([segment.text for segment in segmentler])
    return metin.strip()


def baglanti_al() -> sqlite3.Connection:
    baglanti = sqlite3.connect(VERITABANI_YOLU)
    baglanti.row_factory = sqlite3.Row
    baglanti.execute("PRAGMA foreign_keys = ON")
    return baglanti


def veritabani_olustur():
    baglanti = baglanti_al()
    with baglanti:
        baglanti.executescript("""
            CREATE TABLE IF NOT EXISTS leads (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                business_name TEXT NOT NULL,
                contact_name  TEXT,
                phone         TEXT,
                city          TEXT,
                district      TEXT,
                notes         TEXT,
                stage         TEXT DEFAULT 'yeni',
                source        TEXT,
                created_at    TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS calls (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id        INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                call_date      TEXT DEFAULT (datetime('now','localtime')),
                result         TEXT,
                objections     TEXT,
                notes          TEXT,
                audio_path     TEXT,
                follow_up_date TEXT,
                transcript     TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_calls_lead_id    ON calls(lead_id);
            CREATE INDEX IF NOT EXISTS idx_calls_call_date  ON calls(call_date);
            CREATE INDEX IF NOT EXISTS idx_leads_stage      ON leads(stage);
            CREATE INDEX IF NOT EXISTS idx_calls_follow_up  ON calls(follow_up_date);
        """)
        try:
            baglanti.execute("ALTER TABLE calls ADD COLUMN transcript TEXT")
        except sqlite3.OperationalError:
            pass
    baglanti.close()


def tum_adaylari_getir(sehir: str = None, asama: str = None, arama: str = "") -> pd.DataFrame:
    baglanti = baglanti_al()
    sorgu = "SELECT * FROM leads WHERE 1=1"
    parametreler = []
    
    if sehir and sehir != "Tümü":
        sorgu += " AND city = ?"
        parametreler.append(sehir)
    if asama and asama != "Tümü":
        sorgu += " AND stage = ?"
        parametreler.append(asama)
    if arama:
        sorgu += " AND (business_name LIKE ? OR contact_name LIKE ? OR phone LIKE ?)"
        benzer = f"%{arama}%"
        parametreler.extend([benzer, benzer, benzer])
        
    sorgu += " ORDER BY created_at DESC"
    df = pd.read_sql_query(sorgu, baglanti, params=parametreler)
    baglanti.close()
    return df


def aday_getir_id(aday_id: int) -> sqlite3.Row:
    baglanti = baglanti_al()
    satir = baglanti.execute("SELECT * FROM leads WHERE id = ?", (aday_id,)).fetchone()
    baglanti.close()
    return satir


def aday_ekle(isletme_adi, iletisim_kisi, telefon, sehir, ilce, notlar, kaynak) -> int:
    baglanti = baglanti_al()
    with baglanti:
        imlec = baglanti.execute(
            """INSERT INTO leads (business_name, contact_name, phone, city, district, notes, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (isletme_adi, iletisim_kisi, telefon, sehir, ilce, notlar, kaynak),
        )
    aday_id = imlec.lastrowid
    baglanti.close()
    return aday_id


def aday_asamasi_guncelle(aday_id: int, asama: str):
    baglanti = baglanti_al()
    with baglanti:
        baglanti.execute("UPDATE leads SET stage = ? WHERE id = ?", (asama, aday_id))
    baglanti.close()


def adayin_aramalarini_getir(aday_id: int) -> pd.DataFrame:
    baglanti = baglanti_al()
    df = pd.read_sql_query(
        "SELECT * FROM calls WHERE lead_id = ? ORDER BY call_date DESC",
        baglanti,
        params=(aday_id,),
    )
    baglanti.close()
    return df


def arama_kaydet(aday_id, sonuc, itirazlar, notlar, ses_yolu, takip_tarihi) -> int:
    baglanti = baglanti_al()
    itiraz_metni = ",".join(itirazlar) if itirazlar else ""
    takip_metni = takip_tarihi.isoformat() if takip_tarihi else None
    
    with baglanti:
        imlec = baglanti.execute(
            """INSERT INTO calls (lead_id, result, objections, notes, audio_path, follow_up_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (aday_id, sonuc, itiraz_metni, notlar, ses_yolu, takip_metni),
        )
    arama_id = imlec.lastrowid
    baglanti.close()
    return arama_id


def arama_transkript_guncelle(arama_id: int, transkript: str):
    baglanti = baglanti_al()
    with baglanti:
        baglanti.execute("UPDATE calls SET transcript = ? WHERE id = ?", (transkript, arama_id))
    baglanti.close()


def ozet_verileri_getir() -> dict:
    baglanti = baglanti_al()
    satir = baglanti.execute("""
        SELECT
            (SELECT COUNT(*) FROM leads) AS toplam_aday,
            (SELECT COUNT(*) FROM calls WHERE date(call_date) = date('now','localtime')) AS bugunku_arama,
            (SELECT COUNT(*) FROM calls
             WHERE date(call_date) >= date('now','localtime','-6 days')
             ) AS haftalik_arama,
            (SELECT COUNT(*) FROM leads WHERE stage = 'musteri') AS toplam_musteri,
            (SELECT ROUND(
                100.0 * SUM(CASE WHEN stage IN ('musteri','deneme','demo_atildi') THEN 1 ELSE 0 END)
                / NULLIF(COUNT(*), 0), 1)
             FROM leads) AS donusum_orani
    """).fetchone()
    sonuc = dict(satir) if satir else {}
    baglanti.close()
    return sonuc


def son_30_gunluk_aramalar() -> pd.DataFrame:
    baglanti = baglanti_al()
    df = pd.read_sql_query(
        """
        SELECT date(call_date) AS tarih, COUNT(*) AS adet
        FROM calls
        WHERE date(call_date) >= date('now','localtime','-29 days')
        GROUP BY date(call_date)
        ORDER BY tarih
        """,
        baglanti,
    )
    baglanti.close()
    return df


def sonuc_dagilimi() -> pd.DataFrame:
    baglanti = baglanti_al()
    df = pd.read_sql_query(
        "SELECT result AS sonuc, COUNT(*) AS adet FROM calls GROUP BY result ORDER BY adet DESC",
        baglanti,
    )
    baglanti.close()
    return df


def bugunku_takipler() -> pd.DataFrame:
    baglanti = baglanti_al()
    df = pd.read_sql_query(
        """
        SELECT c.id, c.follow_up_date, c.result, c.notes,
               l.business_name, l.contact_name, l.phone, l.city
        FROM calls c
        JOIN leads l ON l.id = c.lead_id
        WHERE date(c.follow_up_date) = date('now','localtime')
        ORDER BY c.follow_up_date
        """,
        baglanti,
    )
    baglanti.close()
    return df


def geciken_ve_bugunku_takipler() -> pd.DataFrame:
    baglanti = baglanti_al()
    df = pd.read_sql_query(
        """
        SELECT c.id, c.follow_up_date, c.result, c.notes,
               l.id AS lead_id, l.business_name, l.contact_name, l.phone, l.city, l.stage
        FROM calls c
        JOIN leads l ON l.id = c.lead_id
        WHERE date(c.follow_up_date) <= date('now','localtime')
          AND l.stage NOT IN ('musteri','kayip')
        ORDER BY c.follow_up_date
        """,
        baglanti,
    )
    baglanti.close()
    return df


def hic_aranmamis_adaylar(limit: int = 30) -> pd.DataFrame:
    baglanti = baglanti_al()
    df = pd.read_sql_query(
        """
        SELECT l.*
        FROM leads l
        WHERE NOT EXISTS (SELECT 1 FROM calls c WHERE c.lead_id = l.id)
          AND l.stage NOT IN ('musteri','kayip')
        ORDER BY l.created_at
        LIMIT ?
        """,
        baglanti,
        params=(limit,),
    )
    baglanti.close()
    return df


def haftalik_aramalar() -> pd.DataFrame:
    baglanti = baglanti_al()
    df = pd.read_sql_query(
        """
        SELECT strftime('%Y-W%W', call_date) AS hafta, result AS sonuc, COUNT(*) AS adet
        FROM calls
        WHERE date(call_date) >= date('now','localtime','-90 days')
        GROUP BY hafta, result
        ORDER BY hafta
        """,
        baglanti,
    )
    baglanti.close()
    return df


def itiraz_sayilari() -> pd.DataFrame:
    baglanti = baglanti_al()
    df = pd.read_sql_query(
        "SELECT objections FROM calls WHERE objections IS NOT NULL AND objections != ''",
        baglanti,
    )
    baglanti.close()
    if df.empty:
        return pd.DataFrame(columns=["itiraz", "adet"])
    df = df["objections"].str.split(",").explode().str.strip()
    df = df[df != ""].value_counts().reset_index()
    df.columns = ["itiraz", "adet"]
    return df


def sehir_performansi() -> pd.DataFrame:
    baglanti = baglanti_al()
    df = pd.read_sql_query(
        """
        SELECT l.city AS sehir, c.result AS sonuc, COUNT(*) AS adet
        FROM calls c
        JOIN leads l ON l.id = c.lead_id
        WHERE l.city IS NOT NULL
        GROUP BY l.city, c.result
        ORDER BY l.city, adet DESC
        """,
        baglanti,
    )
    baglanti.close()
    return df


def asama_sayilari() -> pd.DataFrame:
    baglanti = baglanti_al()
    df = pd.read_sql_query(
        "SELECT stage AS asama, COUNT(*) AS adet FROM leads GROUP BY stage",
        baglanti,
    )
    baglanti.close()
    return df


def tum_transkriptleri_getir() -> pd.DataFrame:
    baglanti = baglanti_al()
    df = pd.read_sql_query("SELECT transcript FROM calls WHERE transcript IS NOT NULL AND transcript != ''", baglanti)
    baglanti.close()
    return df


def css_yukle():
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-color: #f8fafc;
        }}
        section[data-testid="stSidebar"] {{
            background-color: #0f172a;
            border-right: 1px solid #1e293b;
        }}
        section[data-testid="stSidebar"] * {{
            color: #f1f5f9 !important;
        }}
        section[data-testid="stSidebar"] .stRadio label {{
            font-size: 1rem;
            padding: 0.5rem 0;
            font-weight: 500;
        }}
        div[data-testid="metric-container"] {{
            background-color: white;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
            border: 1px solid #e2e8f0;
        }}
        [data-testid="stMetricLabel"] {{
            font-size: 0.9rem;
            color: #64748b;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        [data-testid="stMetricValue"] {{
            font-size: 2.2rem;
            font-weight: 800;
            color: {ANA_RENK};
        }}
        div.stButton > button:first-child {{
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.2s ease-in-out;
        }}
        div.stButton > button:first-child:hover {{
            transform: translateY(-1px);
            box-shadow: 0 4px 6px -1px rgba(79, 70, 229, 0.2);
        }}
        .stDataFrame {{
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
        }}
        .css-1y4p8pa {{
            padding-top: 2rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def ozet_karti(etiket: str, deger, degisim=None):
    st.metric(label=etiket, value=deger, delta=degisim)


def asama_belirle(sonuc: str, mevcut_asama: str) -> str | None:
    yeni_asama = SONUCTAN_ASAMAYA.get(sonuc)
    if yeni_asama is None:
        return None
    if yeni_asama == "kayip":
        return "kayip"
    mevcut_indeks = ASAMALAR.index(mevcut_asama) if mevcut_asama in ASAMALAR else 0
    yeni_indeks = ASAMALAR.index(yeni_asama)
    if yeni_indeks > mevcut_indeks:
        return yeni_asama
    return None


def ses_kaydet(ses_verisi: bytes, aday_id: int) -> str:
    SES_KLASORU.mkdir(exist_ok=True)
    dosya_adi = f"aday_{aday_id}_{int(time.time())}.wav"
    yol = SES_KLASORU / dosya_adi
    yol.write_bytes(ses_verisi)
    return str(yol)


def sayfa_kontrol_paneli():
    st.title("📊 Kontrol Paneli")
    st.markdown("Günlük satış ve operasyon metrikleri")

    veriler = ozet_verileri_getir()
    toplam_aday = veriler.get("toplam_aday", 0)
    bugunku_arama = veriler.get("bugunku_arama", 0)
    haftalik_arama = veriler.get("haftalik_arama", 0)
    toplam_musteri = veriler.get("toplam_musteri", 0)
    donusum_orani = veriler.get("donusum_orani") or 0.0

    kolon1, kolon2, kolon3, kolon4, kolon5 = st.columns(5)
    with kolon1:
        ozet_karti("Toplam Aday", toplam_aday)
    with kolon2:
        ozet_karti(f"Bugünkü Aramalar", f"{bugunku_arama} / {GUNLUK_HEDEF}")
    with kolon3:
        ozet_karti("Bu Hafta Aramalar", haftalik_arama)
    with kolon4:
        ozet_karti("Dönüşüm Oranı", f"%{donusum_orani}")
    with kolon5:
        ozet_karti("Toplam Müşteri", toplam_musteri)

    st.markdown("<br>", unsafe_allow_html=True)

    sol_kolon, sag_kolon = st.columns(2, gap="large")

    with sol_kolon:
        st.subheader("📈 Son 30 Günlük Aramalar")
        gunluk_df = son_30_gunluk_aramalar()
        if not gunluk_df.empty:
            grafik = go.Figure()
            grafik.add_trace(go.Bar(
                x=gunluk_df["tarih"],
                y=gunluk_df["adet"],
                name="Aramalar",
                marker_color=ANA_RENK,
                marker_line_color=ANA_RENK,
                marker_line_width=1,
                opacity=0.8
            ))
            grafik.add_hline(
                y=GUNLUK_HEDEF,
                line_dash="dash",
                line_color="#ef4444",
                annotation_text=f"Günlük Hedef ({GUNLUK_HEDEF})",
                annotation_position="top right",
                annotation_font_color="#ef4444"
            )
            grafik.update_layout(
                xaxis_title="Tarih",
                yaxis_title="Arama Sayısı",
                showlegend=False,
                height=350,
                margin=dict(l=0, r=0, t=30, b=0)
            )
            st.plotly_chart(grafik, use_container_width=True)
        else:
            st.info("Henüz arama kaydı yok.")

    with sag_kolon:
        st.subheader("🎯 Arama Sonuç Dağılımı")
        sonuc_df = sonuc_dagilimi()
        if not sonuc_df.empty:
            sonuc_df["etiket"] = sonuc_df["sonuc"].map(ARAMA_SONUC_ETIKETLERI).fillna(sonuc_df["sonuc"])
            pasta_grafik = px.pie(
                sonuc_df,
                values="adet",
                names="etiket",
                hole=0.45,
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            pasta_grafik.update_layout(
                height=350,
                margin=dict(l=0, r=0, t=30, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5)
            )
            st.plotly_chart(pasta_grafik, use_container_width=True)
        else:
            st.info("Henüz arama kaydı yok.")

    st.markdown("---")
    st.subheader("📅 Bugünkü Planlanmış Takipler")
    bugunku_df = bugunku_takipler()
    if not bugunku_df.empty:
        gosterim = bugunku_df[["business_name", "contact_name", "phone", "city", "follow_up_date", "notes"]].copy()
        gosterim.columns = ["İşletme Adı", "İletişim Kişisi", "Telefon", "Şehir", "Takip Tarihi", "Notlar"]
        st.dataframe(gosterim, use_container_width=True, hide_index=True)
    else:
        st.success("Harika! Bugün için bekleyen takip yok.")


def sayfa_aday_yonetimi():
    st.title("👥 Müşteri Adayı Yönetimi")

    sekme1, sekme2, sekme3 = st.tabs(["📋 Aday Listesi", "➕ Tekli Ekle", "📂 Excel / CSV İle Toplu Yükle"])

    with sekme1:
        st.subheader("Filtreleme ve Arama")
        with st.container(border=True):
            filtre_kolon1, filtre_kolon2, filtre_kolon3 = st.columns(3)
            with filtre_kolon1:
                secilen_sehir = st.selectbox("Şehir Filtresi", ["Tümü"] + SEHIRLER)
            with filtre_kolon2:
                secilen_asama = st.selectbox(
                    "Aşama Filtresi",
                    ["Tümü"] + ASAMALAR,
                    format_func=lambda s: "Tümü" if s == "Tümü" else ASAMA_ETIKETLERI.get(s, s)
                )
            with filtre_kolon3:
                arama_metni = st.text_input("Arama (İsim veya Telefon)")

        df = tum_adaylari_getir(
            sehir=secilen_sehir if secilen_sehir != "Tümü" else None,
            asama=secilen_asama if secilen_asama != "Tümü" else None,
            arama=arama_metni,
        )

        if df.empty:
            st.info("Eşleşen müşteri adayı bulunamadı. Yeni bir kayıt ekleyerek başlayabilirsiniz.")
        else:
            gosterim = df[["id", "business_name", "contact_name", "phone", "city", "stage", "source", "created_at"]].copy()
            gosterim["stage"] = gosterim["stage"].map(ASAMA_ETIKETLERI).fillna(gosterim["stage"])
            gosterim.columns = ["ID", "İşletme Adı", "İletişim Kişisi", "Telefon", "Şehir", "Aşama", "Kaynak", "Kayıt Tarihi"]
            st.dataframe(gosterim, use_container_width=True, hide_index=True, height=500)
            st.caption(f"Toplam {len(df)} kayıt listeleniyor.")

    with sekme2:
        st.subheader("Yeni Müşteri Adayı Oluştur")
        with st.container(border=True):
            with st.form("aday_ekleme_formu", clear_on_submit=True):
                form_kolon1, form_kolon2 = st.columns(2)
                with form_kolon1:
                    isletme_adi = st.text_input("İşletme Adı *", placeholder="Örn: Temizify A.Ş.")
                    iletisim_kisi = st.text_input("İletişim Kişisi", placeholder="Örn: Ahmet Yılmaz")
                    telefon = st.text_input("Telefon", placeholder="0555 555 55 55")
                    sehir = st.selectbox("Şehir", SEHIRLER)
                with form_kolon2:
                    ilce = st.text_input("İlçe")
                    kaynak = st.selectbox("Müşteri Kaynağı", KAYNAK_SECENEKLERI)
                    notlar = st.text_area("Notlar", placeholder="Müşteri hakkında ek bilgiler...")

                st.markdown("<br>", unsafe_allow_html=True)
                gonderildi = st.form_submit_button("Sisteme Kaydet", type="primary", use_container_width=True)
                if gonderildi:
                    if not isletme_adi:
                        st.error("İşletme adı zorunludur.")
                    else:
                        aday_ekle(isletme_adi, iletisim_kisi, telefon, sehir, ilce, notlar, kaynak)
                        st.success(f"'{isletme_adi}' başarıyla eklendi.")

    with sekme3:
        st.subheader("Dosyadan Toplu İçeri Aktarım")
        with st.container(border=True):
            st.info("""
                Yükleyeceğiniz Excel veya CSV dosyasındaki sütun başlıkları tam olarak şu şekilde olmalıdır:
                **business_name** (Zorunlu), **contact_name**, **phone**, **city**, **district**, **notes**, **source**
            """)
            yuklenen_dosya = st.file_uploader("Excel veya CSV dosyanızı seçin", type=["csv", "xlsx"])
            
            if yuklenen_dosya is not None:
                if st.button("Dosyayı İçeri Aktar", type="primary"):
                    try:
                        if yuklenen_dosya.name.endswith(".csv"):
                            icerik_df = pd.read_csv(yuklenen_dosya)
                        else:
                            icerik_df = pd.read_excel(yuklenen_dosya)

                        basarili_kayit_sayisi = 0
                        for _, satir in icerik_df.iterrows():
                            firma_adi = str(satir.get("business_name", "")).strip()
                            if firma_adi and firma_adi != "nan":
                                aday_ekle(
                                    isletme_adi=firma_adi,
                                    iletisim_kisi=str(satir.get("contact_name", "")).strip() if "contact_name" in icerik_df.columns else "",
                                    telefon=str(satir.get("phone", "")).strip() if "phone" in icerik_df.columns else "",
                                    sehir=str(satir.get("city", "")).strip() if "city" in icerik_df.columns else "Diğer",
                                    ilce=str(satir.get("district", "")).strip() if "district" in icerik_df.columns else "",
                                    notlar=str(satir.get("notes", "")).strip() if "notes" in icerik_df.columns else "",
                                    kaynak=str(satir.get("source", "")).strip() if "source" in icerik_df.columns else "Diğer"
                                )
                                basarili_kayit_sayisi += 1
                        
                        st.success(f"İşlem tamamlandı: {basarili_kayit_sayisi} adet yeni müşteri sisteme aktarıldı!")
                        st.balloons()
                    except Exception as hata:
                        st.error(f"Dosya işlenirken bir hata oluştu: {str(hata)}")


def sayfa_arama_masasi():
    st.title("🎧 Arama Masası")

    df = tum_adaylari_getir()
    aktif_adaylar = df[~df["stage"].isin(["musteri", "kayip"])]

    if aktif_adaylar.empty:
        st.warning("Aranacak aktif müşteri adayı bulunamadı.")
        return

    aday_secenekleri = {satir["id"]: f"{satir['business_name']} — {satir['city'] or ''}" for _, satir in aktif_adaylar.iterrows()}
    
    secim_kolonu, _ = st.columns([2, 1])
    with secim_kolonu:
        secilen_aday_id = st.selectbox(
            "Aranacak Müşteriyi Seçin",
            options=list(aday_secenekleri.keys()),
            format_func=lambda x: aday_secenekleri[x],
        )

    # --- FIX: Müşteri değiştiğinde eski ses verisini ve form state'ini temizle ---
    if "onceki_aday_id" not in st.session_state:
        st.session_state["onceki_aday_id"] = secilen_aday_id

    if st.session_state["onceki_aday_id"] != secilen_aday_id:
        st.session_state.pop("bekleyen_ses", None)
        st.session_state["onceki_aday_id"] = secilen_aday_id
    # --- FIX SONU ---

    aday = aday_getir_id(secilen_aday_id)
    if not aday:
        st.error("Müşteri adayı bulunamadı.")
        return

    with st.container(border=True):
        st.markdown(f"### {aday['business_name']}")
        bilgi_kolon1, bilgi_kolon2, bilgi_kolon3 = st.columns(3)
        bilgi_kolon1.metric("İletişim Kişisi", aday["contact_name"] or "—")
        bilgi_kolon2.metric("Telefon", aday["phone"] or "—")
        bilgi_kolon3.metric("Şehir / İlçe", f"{aday['city'] or '—'} / {aday['district'] or '—'}")
        
        bilgi_kolon4, bilgi_kolon5, bilgi_kolon6 = st.columns(3)
        bilgi_kolon4.metric("Mevcut Aşama", ASAMA_ETIKETLERI.get(aday["stage"], aday["stage"]))
        bilgi_kolon5.metric("Müşteri Kaynağı", aday["source"] or "—")
        bilgi_kolon6.metric("Genel Notlar", aday["notes"] or "—")

    form_kolonu, gecmis_kolonu = st.columns([1.5, 1], gap="large")

    with form_kolonu:
        st.subheader("Yeni Arama Kaydet")
        # --- FIX: Dinamik form key'i ile müşteri değiştiğinde form sıfırlanır ---
        with st.form(f"arama_kayit_formu_{secilen_aday_id}", clear_on_submit=True):
            arama_sonucu = st.selectbox(
                "Arama Sonucu",
                ARAMA_SONUCLARI,
                format_func=lambda r: ARAMA_SONUC_ETIKETLERI.get(r, r),
            )
            alinan_itirazlar = st.multiselect("Görüşmede Alınan İtirazlar", ITIRAZLAR)
            planlanan_takip = st.date_input("Bir Sonraki Takip Tarihi", value=None)
            gorusme_notlari = st.text_area("Görüşme Notları", height=100)
            kaydet_butonu = st.form_submit_button("Görüşmeyi Kaydet", type="primary", use_container_width=True)

        st.markdown("##### 🎙️ Sesli Görüşme Notu")
        with st.container(border=True):
            ses_verisi = audio_recorder(
                text="Sesli not kaydetmek için tıklayın",
                recording_color="#ef4444",
                neutral_color="#64748b",
                pause_threshold=9999.0,
                sample_rate=44100,
            )
            if ses_verisi:
                st.session_state["bekleyen_ses"] = ses_verisi
                st.audio(ses_verisi, format="audio/wav")
            elif "bekleyen_ses" in st.session_state:
                st.audio(st.session_state["bekleyen_ses"], format="audio/wav")
                st.caption("Kayıt hazır — Formu gönderebilirsiniz.")

            with st.expander("Veya bilgisayardan ses dosyası yükle"):
                yuklenen_ses_dosyasi = st.file_uploader(
                    "Desteklenen formatlar: WAV, MP3, M4A", type=["wav", "mp3", "m4a", "ogg", "webm"],
                )
                if yuklenen_ses_dosyasi:
                    st.session_state["bekleyen_ses"] = yuklenen_ses_dosyasi.read()
                    st.audio(st.session_state["bekleyen_ses"])

        if kaydet_butonu:
            kayit_yolu = None
            bekleyen = st.session_state.pop("bekleyen_ses", None)
            if bekleyen:
                kayit_yolu = ses_kaydet(bekleyen, secilen_aday_id)

            arama_kaydet(secilen_aday_id, arama_sonucu, alinan_itirazlar, gorusme_notlari, kayit_yolu, planlanan_takip)

            yeni_asama = asama_belirle(arama_sonucu, aday["stage"])
            if yeni_asama:
                aday_asamasi_guncelle(secilen_aday_id, yeni_asama)
                st.toast(f"Aşama güncellendi: {ASAMA_ETIKETLERI.get(yeni_asama, yeni_asama)}", icon="✅")
            
            st.success("Görüşme başarıyla kaydedildi.")
            st.rerun()

    with gecmis_kolonu:
        st.subheader("Görüşme Geçmişi")
        gecmis_df = adayin_aramalarini_getir(secilen_aday_id)
        if gecmis_df.empty:
            st.info("Bu müşteri için daha önce arama yapılmamış.")
        else:
            for _, kayit in gecmis_df.iterrows():
                with st.container(border=True):
                    st.markdown(f"**{kayit['call_date']}**")
                    st.markdown(f"🏷️ **Sonuç:** {ARAMA_SONUC_ETIKETLERI.get(kayit['result'], kayit['result'])}")
                    if kayit["notes"]:
                        st.markdown(f"📝 {kayit['notes']}")
                    if kayit["objections"]:
                        st.caption(f"⚠️ İtirazlar: {kayit['objections']}")
                    if kayit["follow_up_date"]:
                        st.caption(f"📅 Takip Planı: {kayit['follow_up_date']}")
                    if isinstance(kayit["audio_path"], str) and kayit["audio_path"].strip() and Path(kayit["audio_path"]).exists():
                        st.audio(kayit["audio_path"])
                        
                        if kayit.get("transcript"):
                            st.markdown(f"💬 **Transkript:** {kayit['transcript']}")
                        else:
                            if st.button("Yazıya Çevir", key=f"transcribe_{kayit['id']}"):
                                with st.spinner("Ses dosyası yazıya çevriliyor, lütfen bekleyin..."):
                                    try:
                                        metin = sesi_yaziya_cevir(kayit["audio_path"])
                                        arama_transkript_guncelle(kayit["id"], metin)
                                        st.success("Yazıya çevirme başarılı!")
                                        time.sleep(1)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Bir hata oluştu: {str(e)}")


def sayfa_gunluk_gorevler():
    st.title("🎯 Günlük Görevler")

    sekme1, sekme2 = st.tabs(["⏰ Takip Bekleyenler", "🆕 İlk Kez Aranacaklar"])

    with sekme1:
        st.subheader("Tarihi Gelen veya Geciken Takipler")
        df = geciken_ve_bugunku_takipler()
        if df.empty:
            st.success("Harika! Bekleyen takip göreviniz bulunmuyor.")
        else:
            gosterim = df[["business_name", "contact_name", "phone", "city", "follow_up_date", "stage", "notes"]].copy()
            gosterim["stage"] = gosterim["stage"].map(ASAMA_ETIKETLERI).fillna(gosterim["stage"])
            gosterim.columns = ["İşletme Adı", "İletişim Kişisi", "Telefon", "Şehir", "Planlanan Tarih", "Mevcut Aşama", "Görüşme Notları"]
            st.dataframe(gosterim, use_container_width=True, hide_index=True)
            st.caption(f"Toplam {len(df)} adet takip görevi var.")

    with sekme2:
        st.subheader("Henüz Hiç Aranmamış Müşteriler (İlk 30 Kayıt)")
        df2 = hic_aranmamis_adaylar(limit=30)
        if df2.empty:
            st.success("Tebrikler! Sistemdeki tüm aktif müşteri adayları en az bir kez arandı.")
        else:
            gosterim2 = df2[["business_name", "contact_name", "phone", "city", "stage", "source", "created_at"]].copy()
            gosterim2["stage"] = gosterim2["stage"].map(ASAMA_ETIKETLERI).fillna(gosterim2["stage"])
            gosterim2.columns = ["İşletme Adı", "İletişim Kişisi", "Telefon", "Şehir", "Aşama", "Kaynak", "Sisteme Giriş Tarihi"]
            st.dataframe(gosterim2, use_container_width=True, hide_index=True)
            st.caption(f"Toplam {len(df2)} adet ilk kez aranacak kayıt gösteriliyor.")


def sayfa_analizler():
    st.title("📈 Detaylı Analizler")

    sekme1, sekme2, sekme3, sekme4 = st.tabs(["📊 Haftalık Trendler", "⚠️ İtiraz Analizi", "🗺️ Bölgesel Performans", "🗣️ Transkript Analizi"])

    with sekme1:
        trend_kolonu, huni_kolonu = st.columns(2, gap="large")
        
        with trend_kolonu:
            st.subheader("Son 90 Günlük Arama Trendi")
            haftalik_df = haftalik_aramalar()
            if not haftalik_df.empty:
                pivot_tablo = haftalik_df.pivot_table(index="hafta", columns="sonuc", values="adet", aggfunc="sum", fill_value=0).reset_index()
                pivot_tablo["toplam"] = pivot_tablo.drop(columns="hafta").sum(axis=1)

                gosterilecek_kolonlar = ["hafta", "toplam"]
                for k in ["ilgili", "demo_attim"]:
                    if k in pivot_tablo.columns:
                        gosterilecek_kolonlar.append(k)

                erimis_df = pivot_tablo[gosterilecek_kolonlar].melt(id_vars="hafta", var_name="Seri", value_name="Sayı")
                etiket_haritasi = {"toplam": "Toplam Görüşme", "ilgili": "İlgilenenler", "demo_attim": "Demo Gönderilenler"}
                erimis_df["Seri"] = erimis_df["Seri"].map(etiket_haritasi).fillna(erimis_df["Seri"])

                grafik1 = px.bar(
                    erimis_df,
                    x="hafta",
                    y="Sayı",
                    color="Seri",
                    barmode="group",
                    color_discrete_sequence=[ANA_RENK, "#10b981", "#f59e0b"],
                )
                grafik1.update_layout(xaxis_title="Haftalar", yaxis_title="İşlem Sayısı", legend_title=None)
                st.plotly_chart(grafik1, use_container_width=True)
            else:
                st.info("Trend oluşturmak için yeterli arama verisi yok.")

        with huni_kolonu:
            st.subheader("Güncel Satış Hunisi")
            asama_df = asama_sayilari()
            if not asama_df.empty:
                asama_df = asama_df[asama_df["asama"].isin(ASAMALAR)].copy()
                asama_df["sira"] = asama_df["asama"].apply(lambda s: ASAMALAR.index(s) if s in ASAMALAR else 99)
                asama_df = asama_df.sort_values("sira")
                asama_df["etiket"] = asama_df["asama"].map(ASAMA_ETIKETLERI).fillna(asama_df["asama"])

                grafik2 = go.Figure(go.Funnel(
                    y=asama_df["etiket"].tolist(),
                    x=asama_df["adet"].tolist(),
                    textinfo="value+percent initial",
                    marker={"color": [ANA_RENK, "#6366f1", "#818cf8", "#a5b4fc", "#10b981", "#ef4444"]},
                ))
                st.plotly_chart(grafik2, use_container_width=True)
            else:
                st.info("Huni oluşturmak için yeterli müşteri verisi yok.")

    with sekme2:
        itiraz_kolonu, donusum_kolonu = st.columns(2, gap="large")
        with itiraz_kolonu:
            st.subheader("En Sık Karşılaşılan İtirazlar")
            itiraz_df = itiraz_sayilari()
            if not itiraz_df.empty:
                grafik3 = px.bar(
                    itiraz_df.sort_values("adet"),
                    x="adet",
                    y="itiraz",
                    orientation="h",
                    color_discrete_sequence=[ANA_RENK],
                )
                grafik3.update_layout(
                    yaxis={"categoryorder": "total ascending"},
                    xaxis_title="Karşılaşma Sayısı",
                    yaxis_title="",
                )
                st.plotly_chart(grafik3, use_container_width=True)
            else:
                st.info("Sisteme henüz bir itiraz kaydedilmemiş.")

        with donusum_kolonu:
            st.subheader("Çağrı Sonucu Dönüşüm Oranları")
            sonuc_df = sonuc_dagilimi()
            if not sonuc_df.empty:
                sonuc_df["Görüşme Sonucu"] = sonuc_df["sonuc"].map(ARAMA_SONUC_ETIKETLERI).fillna(sonuc_df["sonuc"])
                toplam = sonuc_df["adet"].sum()
                sonuc_df["Genel Oran %"] = (sonuc_df["adet"] / toplam * 100).round(1)
                gosterim = sonuc_df[["Görüşme Sonucu", "adet", "Genel Oran %"]].copy()
                gosterim.columns = ["Görüşme Sonucu", "Toplam Adet", "Genel Oran %"]
                st.dataframe(gosterim, use_container_width=True, hide_index=True)

    with sekme3:
        st.subheader("Şehirlere Göre Başarı Performansı")
        sehir_df = sehir_performansi()
        if not sehir_df.empty:
            grafik4 = px.bar(
                sehir_df,
                x="sehir",
                y="adet",
                color="sonuc",
                barmode="group",
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            grafik4.update_layout(xaxis_title="Şehir", yaxis_title="İşlem Sayısı", legend_title="Görüşme Sonucu")
            st.plotly_chart(grafik4, use_container_width=True)

            st.markdown("<br>", unsafe_allow_html=True)
            pivot_sehir = sehir_df.pivot_table(
                index="sehir",
                columns="sonuc",
                values="adet",
                aggfunc="sum",
                fill_value=0,
            )
            pivot_sehir.columns = [ARAMA_SONUC_ETIKETLERI.get(c, c) for c in pivot_sehir.columns]
            pivot_sehir.index.name = "Şehir Adı"
            st.dataframe(pivot_sehir, use_container_width=True)
        else:
            st.info("Bölgesel veri bulunmuyor.")

    with sekme4:
        st.subheader("Görüşmelerde En Çok Geçen Kelimeler")
        transkript_df = tum_transkriptleri_getir()
        if not transkript_df.empty:
            tum_metin = " ".join(transkript_df["transcript"].tolist())
            kelime_bulutu = WordCloud(
                width=1000, 
                height=500, 
                background_color="white", 
                stopwords=TR_STOPWORDS,
                colormap="inferno"
            ).generate(tum_metin)
            
            fig, ax = plt.subplots(figsize=(12, 6))
            ax.imshow(kelime_bulutu, interpolation='bilinear')
            ax.axis("off")
            st.pyplot(fig)
        else:
            st.info("Henüz analiz edilecek bir transkript bulunmuyor.")


def sayfa_satis_sureci():
    st.title("🗂️ Satış Süreci (Kanban)")

    df = tum_adaylari_getir()
    if df.empty:
        st.info("Henüz sisteme müşteri adayı eklenmemiş.")
        return

    asama_kolonlari = st.columns(len(ASAMALAR))

    for kolon, asama in zip(asama_kolonlari, ASAMALAR):
        asama_adaylari = df[df["stage"] == asama]
        with kolon:
            st.markdown(
                f"<div style='text-align:center; padding:10px; background-color:#e2e8f0; border-radius:8px; margin-bottom:10px;'>"
                f"<strong style='color:#0f172a;'>{ASAMA_ETIKETLERI[asama]}</strong><br>"
                f"<span style='background:{ANA_RENK};color:white;padding:2px 10px;"
                f"border-radius:12px;font-size:0.8rem; font-weight:bold;'>{len(asama_adaylari)}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            for _, aday in asama_adaylari.iterrows():
                with st.container(border=True):
                    st.markdown(f"<strong style='color:{ANA_RENK};'>{aday['business_name']}</strong>", unsafe_allow_html=True)
                    st.caption(f"{aday['city'] or ''} · {aday['phone'] or ''}")
                    yeni_asama = st.selectbox(
                        "Aşamayı Güncelle",
                        ASAMALAR,
                        index=ASAMALAR.index(aday["stage"]) if aday["stage"] in ASAMALAR else 0,
                        format_func=lambda s: ASAMA_ETIKETLERI.get(s, s),
                        key=f"kanban_asama_{aday['id']}",
                        label_visibility="collapsed",
                    )
                    if yeni_asama != aday["stage"]:
                        aday_asamasi_guncelle(int(aday["id"]), yeni_asama)
                        st.rerun()


def main():
    st.set_page_config(
        page_title="Temizify Satış Paneli",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    css_yukle()

    temizify_sablonu = go.layout.Template(
        layout=go.Layout(
            font={"family": "system-ui, -apple-system, sans-serif"},
            colorway=[ANA_RENK, "#38bdf8", "#34d399", "#fbbf24", "#f87171", "#818cf8"],
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
    )
    pio.templates["temizify"] = temizify_sablonu
    pio.templates.default = "plotly_white+temizify"

    veritabani_olustur()
    SES_KLASORU.mkdir(exist_ok=True)

    sayfalar = {
        "📊 Kontrol Paneli": sayfa_kontrol_paneli,
        "👥 Aday Yönetimi": sayfa_aday_yonetimi,
        "🎧 Arama Masası": sayfa_arama_masasi,
        "🎯 Günlük Görevler": sayfa_gunluk_gorevler,
        "🗂️ Satış Süreci": sayfa_satis_sureci,
        "📈 Analizler": sayfa_analizler,
    }

    with st.sidebar:
        st.markdown("<h2 style='text-align: center; color: white;'>⚡ Temizify Satış</h2>", unsafe_allow_html=True)
        st.markdown("---")
        secim = st.radio("Menü", list(sayfalar.keys()), label_visibility="collapsed")
        st.markdown("---")

        veriler = ozet_verileri_getir()
        bugunku_arama = veriler.get("bugunku_arama", 0)
        st.markdown(
            f"<div style='color: #94a3b8; font-size: 0.9rem;'>Günlük Hedef: <strong>{bugunku_arama} / {GUNLUK_HEDEF}</strong></div>",
            unsafe_allow_html=True
        )
        ilerleme = min(bugunku_arama / GUNLUK_HEDEF, 1.0)
        st.progress(ilerleme)

    calisacak_sayfa = sayfalar.get(secim)
    if calisacak_sayfa:
        calisacak_sayfa()


if __name__ == "__main__":
    main()