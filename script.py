import requests
import json
import time
import sqlite3

# URL de base de l'API, sans les paramètres qui vont changer
base_url = "https://app.safakate.com/api/allcons/consultations"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://app.safakate.com/appelsdoffres",
    "Origin": "https://app.safakate.com",
    # ATTENTION: Ce cookie a une date d'expiration (exp) et devra être mis à jour régulièrement.
    # Pour une utilisation à long terme, envisagez une méthode d'authentification plus robuste (ex: token d'API).
    "Cookie": "Authentication=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOjQyLCJpYXQiOjE3NTEzNTg1ODIsImV4cCI6MTc1MTM2MDk4Mn0.soARZGMKV5qSL7n-Ilv46gq5MAFIs108D6OXX4OyfjU; Refresh=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOjQyLCJpYXQiOjE3NTEzNTg1ODIsImV4cCI6MTc1MTk2MzM4Mn0.pkHJzOzMLGFPLYCeHcxD1qhM4Z6eADAbYurQ_2cdhVY"
}

def get_results(offset, limit):
    """
    Récupère les résultats d'une page spécifique de l'API.
    Gère les erreurs HTTP, de connexion et de décodage JSON.
    """
    params = {
        "offset": offset,
        "limit": limit,
        "searchObjet": "",
        "mosearch": "",
        "dateLimitStart": "2025-06-18T09:00:00.000Z",
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
        # Ajout d'un timeout pour éviter les blocages indéfinis
        response = requests.get(base_url, headers=headers, params=params, timeout=10)
        response.raise_for_status() # Lève une exception pour les codes d'erreur HTTP (4xx ou 5xx)
        
        data = response.json()
        # Vérifie si la réponse est un dictionnaire, contient 'data' et si 'data' est une liste
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            total_count = int(data.get("total", 0))
            print(f"Offset {offset} récupéré. {len(data['data'])} résultats sur cette page. Total attendu: {total_count}")
            return data["data"], total_count
        else:
            print(f"Réponse API inattendue pour offset={offset}: {data}")
            return [], 0
    except requests.exceptions.HTTPError as http_err:
        print(f"Erreur HTTP pour offset={offset}: {http_err} - Réponse: {response.text}")
        return [], 0
    except requests.exceptions.ConnectionError as conn_err:
        print(f"Erreur de connexion pour offset={offset}: {conn_err}")
        return [], 0
    except requests.exceptions.Timeout as timeout_err:
        print(f"Timeout de la requête pour offset={offset}: {timeout_err}")
        return [], 0
    except requests.exceptions.RequestException as req_err:
        print(f"Erreur générale de requête pour offset={offset}: {req_err}")
        return [], 0
    except json.JSONDecodeError as json_err:
        print(f"Erreur de décodage JSON pour offset={offset}: {json_err} - Contenu: {response.text[:200]}...")
        return [], 0
    except Exception as e:
        print(f"Une erreur inattendue s'est produite pour offset={offset}: {e}")
        return [], 0

# Connexion et création de la table principale
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

# Boucle de récupération
all_results = []
seen_ids = set() # Pour stocker les IDs uniques et éviter les doublons
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
            # Insertion dans la base SQLite
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
        elif 'consId' not in item:
            all_results.append(item)
    conn.commit()

    # Affiche uniquement la progression
    print(f"Traitement offset {offset} : {len(all_results)}/{total} éléments collectés")

    if len(all_results) >= total:
        break
    
    offset += 1
    time.sleep(0.5)

output_filename = "resultats_uniques.json"
with open(output_filename, "w", encoding="utf-8") as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)

print(f"Processus terminé. {len(all_results)} résultats uniques enregistrés dans {output_filename}")

conn.close()


