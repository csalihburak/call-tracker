import requests
import json
import time
import os

USER_ID = "82a2135c-c8c8-4b37-8331-1e79e83dba77"
VER = "1.10.32"
BASE = "https://www.halipratik.com/supplier/Design/Android"
HEADERS = {
    "user-agent": f"HaliPratik/{VER} (com.bilgipark.halipratik; build:150; iOS 18.6.2) Alamofire/5.9.1",
    "accept-language": "en-TR;q=1.0, tr-TR;q=0.9",
    "accept": "*/*",
}

PROXY_URL = "http://splzbjxxf3:4xhi4dQQqrlNFw3_x5@tr.decodo.com:40000"
PROXIES = {
    "http": PROXY_URL,
    "https": PROXY_URL
}

def search_customer(mno):
    try:
        r = requests.get(f"{BASE}/SearchCustomer.aspx", params={
            "type": "mno", "value": mno, "userid": USER_ID, "ver": VER
        }, headers=HEADERS, proxies=PROXIES, timeout=10, allow_redirects=False)
        
        if r.status_code != 200:
            print(f"  [HATA] SearchCustomer #{mno} HTTP {r.status_code} dondurdu. Yanit: {r.text[:100]}...")
            return None
            
        try:
            data = r.json()
        except ValueError:
            print(f"  [HATA] SearchCustomer #{mno} JSON donmedi. Yanit: {r.text[:100]}...")
            return None
            
        if data and data.get("bilgi"):
            return data["bilgi"][0]
        return None
    except Exception as e:
        print(f"  [HATA] SearchCustomer #{mno}: {e}")
        return None

def get_orders(customer_id):
    try:
        r = requests.get(f"{BASE}/GetOrders.aspx", params={
            "cusid": customer_id, "ver": VER
        }, headers=HEADERS, proxies=PROXIES, timeout=10, allow_redirects=False)
        
        if r.status_code != 200:
            return []
            
        try:
            return r.json().get("detail", [])
        except ValueError:
            return []
    except Exception as e:
        print(f"  [HATA] GetOrders {customer_id}: {e}")
        return []

if os.path.exists("customers-757c54d1-9a00-f1d5-51be-3a0c37e92cb5.json"):
    with open("customers-757c54d1-9a00-f1d5-51be-3a0c37e92cb5.json", encoding="utf-8") as f:
        results = json.load(f)
    done_mnos = {str(r["customer"]["musno"]) for r in results}
    print(f"{len(done_mnos)} musteri zaten cekilmis, kalidigi yerden devam ediliyor...")
else:
    results = []
    done_mnos = set()
    print("Yeni cekim basliyor...")

total = 10
for mno in range(1, total + 1):
    if str(mno) in done_mnos:
        continue

    customer = search_customer(mno)
    if customer:
        orders = get_orders(customer["customerid"])
        results.append({"customer": customer, "orders": orders})
        print(f"[{mno}/{total}] ✓ {customer['musadi']} -> {len(orders)} siparis")
    else:
        print(f"[{mno}/{total}] - bulunamadi")

    if mno % 50 == 0:
        with open("customers-757c54d1-9a00-f1d5-51be-3a0c37e92cb5.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"  [KAYIT] {len(results)} musteri kaydedildi")

    time.sleep(0.2)

with open("customers.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\nTamamlandi. Toplam {len(results)} musteri customers.json dosyasina kaydedildi.")