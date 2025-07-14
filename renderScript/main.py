import os
import requests
import time
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne
import certifi

# --- Configuration initiale ---
load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
MONGO_URI = os.getenv("MONGO_URI")

BASE_URL = "https://app.safakate.com/api/allcons/consultations"

# --- Fonctions API ---
def login(email, password):
    login_url = "https://app.safakate.com/api/authentication/login"
    payload = {"email": email, "password": password}
    try:
        response = requests.post(login_url, json=payload)
        response.raise_for_status()
        cookies = response.cookies
        print("Connexion à Safakate réussie.")
        return {"Authentication": cookies.get("Authentication"), "Refresh": cookies.get("Refresh")}
    except requests.RequestException as e:
        print(f"Erreur d'authentification : {e}")
        return None

def build_headers(cookies):
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Cookie": f"Authentication={cookies['Authentication']}; Refresh={cookies['Refresh']}"
    }

def generer_liens(lien_initial):
    if not lien_initial: return ""
    return lien_initial.replace(
        "entreprise.EntrepriseDetailsConsultation", "entreprise.EntrepriseDownloadCompleteDce"
    ).replace(
        "refConsultation=", "reference="
    ).replace(
        "orgAcronyme=", "orgAcronym="
    )

# --- Fonction de sauvegarde dans MongoDB (MODIFIÉE) ---
# L'intérêt de cette fonction modifiée est d'ajouter une étape de suppression.
# Après avoir mis à jour la base de données avec les dernières données de l'API,
# elle supprime toutes les consultations qui ne sont plus présentes dans l'API,
# assurant ainsi une synchronisation parfaite.
def save_to_mongodb(data_list, current_ids):
    print(f"Connexion à MongoDB pour synchroniser {len(data_list)} consultations...")
    client = None
    try:
        client = MongoClient(
            MONGO_URI,
            tls=True,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=60000
        )
        client.admin.command('ping')
        print("Connexion MongoDB établie.")
        
        db = client.safakate_db 
        collection = db.consultations

        # --- Étape 1: Mettre à jour et insérer les consultations actuelles (comme avant) ---
        if data_list:
            operations = []
            for item in data_list:
                op = UpdateOne(
                    {"_id": item.get("consId")}, 
                    {"$set": item},             
                    upsert=True                 
                )
                operations.append(op)
            
            result_upsert = collection.bulk_write(operations)
            print("Sauvegarde (Ajout/Mise à jour) dans MongoDB terminée.")
            print(f"  - Consultations créées : {result_upsert.upserted_count}")
            print(f"  - Consultations mises à jour : {result_upsert.modified_count}")
        else:
            print("Aucune nouvelle donnée à ajouter ou mettre à jour.")

        # --- Étape 2: Supprimer les anciennes consultations qui n'existent plus dans l'API ---
        # MODIFICATION: On ajoute une opération de suppression pour nettoyer la base de données.
        print("Début de la suppression des anciennes consultations...")
        
        # Le filtre sélectionne les documents où le champ '_id' n'est PAS ($nin) dans la liste des ID actuels.
        delete_filter = {"_id": {"$nin": list(current_ids)}}
        result_delete = collection.delete_many(delete_filter)
        
        print("Suppression terminée.")
        print(f"  - Consultations obsolètes supprimées : {result_delete.deleted_count}")
        
    except Exception as e:
        print(f"Une erreur est survenue avec MongoDB : {e}")
    finally:
        if client:
            client.close()

# --- Script principal ---
def main():
    cookies = login(EMAIL, PASSWORD)
    if not cookies:
        print("Échec de la connexion. Arrêt du script.")
        return

    headers = build_headers(cookies)
    all_results = []
    seen_ids = set()
    
    page = 0
    limit = 20
    total_count = None
    
    max_retries = 3
    retry_count = 0

    while True:
        params = {
            "offset": page,
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
        try:
            response = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
            if response.status_code == 401:
                print("Session expirée, reconnexion...")
                cookies = login(EMAIL, PASSWORD)
                if not cookies: break
                headers = build_headers(cookies)
                response = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
            
            response.raise_for_status()
            data = response.json()
            
            results_on_page = data.get("data", [])
            if total_count is None:
                total_count = data.get("total", 0)
                print(f"Total des consultations à traiter : {total_count}")

            if not results_on_page and page > 0: 
                print("Fin de la récupération des données de l'API (page vide).")
                break

            for item in results_on_page:
                cons_id = item.get("consId")
                if cons_id and cons_id not in seen_ids:
                    item["urldossierDirect"] = generer_liens(item.get("detailsUrl"))
                    all_results.append(item)
                    seen_ids.add(cons_id)
            
            print(f"Progression : {len(all_results)} / {total_count} consultations collectées.")
            
            retry_count = 0
            
            if total_count is not None and len(all_results) >= total_count:
                print("Toutes les consultations ont été collectées.")
                break
            
            page += 1
            time.sleep(0.5)

        except Exception as e:
            retry_count += 1
            print(f"Une erreur est survenue pendant la récupération (tentative {retry_count}/{max_retries}): {e}")
            if retry_count >= max_retries:
                print("Nombre maximum de tentatives atteint. Arrêt de la récupération.")
                break
            
            print("Nouvelle tentative dans 5 secondes...")
            time.sleep(5)

    if all_results:
        # MODIFICATION: On crée un ensemble de tous les ID de consultation actuels à partir des résultats de l'API.
        current_ids = {item.get("consId") for item in all_results if item.get("consId")}
        
        # MODIFICATION: On passe cet ensemble d'IDs à la fonction de sauvegarde pour qu'elle puisse nettoyer la base de données.
        save_to_mongodb(all_results, current_ids)
    else:
        # MODIFICATION: Si aucune donnée n'est collectée, on appelle quand même la fonction pour supprimer les anciennes données de la DB.
        print("Aucune donnée n'a été collectée. Nettoyage de la base de données...")
        save_to_mongodb([], set()) # On passe une liste vide et un ensemble vide.

    print("Processus terminé.")

if __name__ == "__main__":
    main()
