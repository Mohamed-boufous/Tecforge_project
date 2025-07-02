import requests
import json
import time
import sqlite3
import os
from dotenv import load_dotenv
from datetime import datetime
load_dotenv()

email = os.getenv("EMAIL")
password = os.getenv("PASSWORD")     
base_url = "https://app.safakate.com/api/allcons/consultations"


def login(email, password):
    login_url = "https://app.safakate.com/api/authentication/login"
    payload = {
        "email": email,
        "password": password
    }

    try:
        response = requests.post(login_url, json=payload)
        response.raise_for_status()

        cookies = response.cookies
        auth_cookie = cookies.get("Authentication")
        refresh_cookie = cookies.get("Refresh")

        if not auth_cookie or not refresh_cookie:
            print("Cookies d'authentification non trouvés.")
            return None

        return {
            "Authentication": auth_cookie,
            "Refresh": refresh_cookie
        }

    except requests.RequestException as e:
        print(f"Erreur d'authentification : {e}")
        return None

def build_headers(cookies):
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://app.safakate.com/appelsdoffres",
        "Origin": "https://app.safakate.com",
        "Cookie": f"Authentication={cookies['Authentication']}; Refresh={cookies['Refresh']}"
    }

# === INITIALISATION DES HEADERS ===
cookies = login(email, password)
if not cookies:
    print("Échec de la connexion. Script arrêté.")
    exit(1)
headers = build_headers(cookies)

# === FONCTION DE REQUÊTE API ===
def get_results(offset, limit):
    global headers

    params = {
        "offset": offset,
        "limit": limit,
        "searchObjet": "",
        "mosearch": "",
        "dateLimitStart": datetime.now().strftime("%Y-%m-%dT09:00:00.000Z"),
        "sort": "publishedDate",
        "sortDirection": "DESC",
        "state": "En cours",
        "minCaution": 0,
        "maxCaution": 0,
        "minEstimation": 0,
        "maxEstimation": 0
    }

    print(f"Tentative de récupération offset={offset}...")
    try:
        response = requests.get(base_url, headers=headers, params=params, timeout=10)

        if response.status_code == 401:
            print("Session expirée. Tentative de reconnexion...")
            new_cookies = login(email, password)
            if new_cookies:
                headers = build_headers(new_cookies)
                response = requests.get(base_url, headers=headers, params=params, timeout=10)
            else:
                print("Impossible de réauthentifier.")
                return [], 0

        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            total_count = int(data.get("total", 0))
            print(f"Offset {offset} récupéré. {len(data['data'])} résultats sur cette page. Total attendu: {total_count}")
            return data["data"], total_count
        else:
            print(f"Réponse API inattendue pour offset={offset}: {data}")
            return [], 0

    except Exception as e:
        print(f"Erreur lors de la récupération offset={offset}: {e}")
        return [], 0

# === BASE DE DONNÉES ===
conn = sqlite3.connect("consultations.db")
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS consultations (
    consId INTEGER PRIMARY KEY,
    org TEXT,
    detailsUrl TEXT,
    reference TEXT,
    acheteur TEXT,
    AchAbr TEXT,
    procedureType TEXT,
    administratifName TEXT,
    administratifEmail TEXT,
    administratifTel TEXT,
    administratifFax TEXT,
    consDAO TEXT,
    reponseType TEXT,
    provinces TEXT,
    isConsCancelled BOOLEAN,
    publishedDate TEXT,
    endDate TEXT,
    createdAt TEXT,
    avertissements TEXT,
    avis TEXT,
    lots TEXT,
    domains TEXT,
    isFavoris TEXT
)
""")
conn.commit()

# === COLLECTE DES DONNÉES ===
all_results = []
seen_ids = set()
offset = 0
limit = 16
total = None

while True:
    results_on_page, total_count = get_results(offset, limit)

    if total is None:
        total = total_count

    if not results_on_page:
        break

    new_items_added = 0
    for item in results_on_page:
        if 'consId' in item and item['consId'] not in seen_ids:
            all_results.append(item)
            seen_ids.add(item['consId'])
            new_items_added += 1
            cur.execute("""
                INSERT OR IGNORE INTO consultations (
                    consId, org, detailsUrl, reference, acheteur, AchAbr, procedureType,
                    administratifName, administratifEmail, administratifTel, administratifFax,
                    consDAO, reponseType, provinces, isConsCancelled, publishedDate, endDate,
                    createdAt, avertissements, avis, lots, domains, isFavoris
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.get("consId"),
                item.get("org"),
                item.get("detailsUrl"),
                item.get("reference"),
                item.get("acheteur"),
                item.get("AchAbr"),
                item.get("procedureType"),
                item.get("administratifName"),
                item.get("administratifEmail"),
                item.get("administratifTel"),
                item.get("administratifFax"),
                item.get("consDAO"),
                item.get("reponseType"),
                json.dumps(item.get("provinces", []), ensure_ascii=False),
                item.get("isConsCancelled"),
                item.get("publishedDate"),
                item.get("endDate"),
                item.get("createdAt"),
                json.dumps(item.get("avertissements", []), ensure_ascii=False),
                json.dumps(item.get("avis", []), ensure_ascii=False),
                json.dumps(item.get("lots", []), ensure_ascii=False),
                json.dumps(item.get("domains", []), ensure_ascii=False),
                str(item.get("isFavoris"))
            ))
    conn.commit()

    print(f"Traitement offset {offset} : {len(all_results)}/{total} éléments collectés")

    if len(all_results) >= total:
        break

    offset += 1
    time.sleep(0.5)

# === ENREGISTREMENT DES RÉSULTATS ===
output_filename = "resultats_uniques.json"
with open(output_filename, "w", encoding="utf-8") as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)

print(f"Processus terminé. {len(all_results)} résultats uniques enregistrés dans {output_filename}")

conn.close()
