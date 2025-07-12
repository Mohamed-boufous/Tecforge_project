import os
import requests
import time
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne # MODIFIÉ: On importe le client MongoDB et l'opération de mise à jour

# --- Configuration initiale ---
load_dotenv()

# On récupère les 3 secrets depuis les variables d'environnement
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
MONGO_URI = os.getenv("MONGO_URI") # MODIFIÉ: Ajout de la variable pour la connexion à MongoDB

BASE_URL = "https://app.safakate.com/api/allcons/consultations"

# --- Fonctions API (inchangées) ---

def login(email, password):
    """Se connecte et récupère les cookies d'authentification."""
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
    """Construit les en-têtes pour les requêtes API."""
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Cookie": f"Authentication={cookies['Authentication']}; Refresh={cookies['Refresh']}"
    }

def generer_liens(lien_initial):
    """Génère l'URL de téléchargement direct."""
    if not lien_initial: return ""
    return lien_initial.replace(
        "entreprise.EntrepriseDetailsConsultation", "entreprise.EntrepriseDownloadCompleteDce"
    ).replace(
        "refConsultation=", "reference="
    ).replace(
        "orgAcronyme=", "orgAcronym="
    )

# --- NOUVELLE FONCTION POUR SAUVEGARDER DANS MONGODB ---

def save_to_mongodb(data_list):
    """
    Se connecte à MongoDB et sauvegarde la liste des consultations.
    Ceci remplace la sauvegarde en base de données SQLite et en fichier JSON.
    """
    print(f"Connexion à MongoDB pour sauvegarder {len(data_list)} consultations...")
    
    # Étape 1 : Connexion au cluster
    # Le script utilise la variable MONGO_URI que vous avez mise sur Render.
    client = MongoClient(MONGO_URI)
    
    # Étape 2 : Sélection de la base de données et de la collection
    # Vous pouvez changer ces noms si vous le souhaitez.
    db = client.safakate_db 
    collection = db.consultations

    # Étape 3 : Préparation des opérations d'écriture
    # On utilise une méthode optimisée (bulk_write) pour tout insérer/mettre à jour d'un coup.
    operations = []
    for item in data_list:
        # Pour chaque consultation, on crée une opération "UpdateOne".
        # Le filtre {"_id": item.get("consId")} cherche un document avec cet ID.
        # L'opérateur "$set" met à jour le document avec les nouvelles données.
        # "upsert=True" est la clé : si le document n'existe pas, il sera créé.
        op = UpdateOne(
            {"_id": item.get("consId")}, 
            {"$set": item},             
            upsert=True                 
        )
        operations.append(op)

    # Étape 4 : Exécution des opérations
    if not operations:
        print("Aucune donnée à sauvegarder.")
        return

    try:
        result = collection.bulk_write(operations)
        print("Sauvegarde dans MongoDB terminée.")
        print(f"  - Consultations créées : {result.upserted_count}")
        print(f"  - Consultations mises à jour : {result.modified_count}")
    except Exception as e:
        print(f"Une erreur est survenue lors de la sauvegarde dans MongoDB : {e}")
    finally:
        client.close() # On ferme la connexion

# --- SCRIPT PRINCIPAL ---

def main():
    """Fonction principale qui orchestre tout le processus."""
    cookies = login(EMAIL, PASSWORD)
    if not cookies:
        print("Échec de la connexion. Arrêt du script.")
        return

    headers = build_headers(cookies)
    all_results = []
    seen_ids = set()
    offset = 0
    limit = 20 # On peut prendre des pages plus grandes
    total_count = None

    while True:
        # ... (la logique de récupération des données reste la même)
        params = {
            "offset": offset, "limit": limit, "sort": "publishedDate",
            "sortDirection": "DESC", "state": "En cours",
            "dateLimitStart": datetime.now().strftime("%Y-%m-%dT00:00:00.000Z"),
        }
        try:
            response = requests.get(BASE_URL, headers=headers, params=params, timeout=20)
            if response.status_code == 401:
                print("Session expirée, reconnexion...")
                cookies = login(EMAIL, PASSWORD)
                if not cookies: break
                headers = build_headers(cookies)
                response = requests.get(BASE_URL, headers=headers, params=params, timeout=20)
            
            response.raise_for_status()
            data = response.json()
            
            results_on_page = data.get("data", [])
            if total_count is None:
                total_count = data.get("total", 0)
                print(f"Total des consultations à traiter : {total_count}")

            if not results_on_page:
                print("Fin de la récupération des données de l'API.")
                break

            for item in results_on_page:
                cons_id = item.get("consId")
                if cons_id and cons_id not in seen_ids:
                    item["urldossierDirect"] = generer_liens(item.get("detailsUrl"))
                    all_results.append(item)
                    seen_ids.add(cons_id)
            
            print(f"Progression : {len(all_results)} / {total_count} consultations collectées.")
            
            if len(all_results) >= total_count:
                break
            
            offset += limit # CORRIGÉ: On incrémente par la taille de la page, pas par 1
            time.sleep(0.5)

        except Exception as e:
            print(f"Une erreur est survenue pendant la récupération : {e}")
            break

    # MODIFIÉ : Au lieu d'écrire dans un fichier, on appelle la fonction de sauvegarde MongoDB
    if all_results:
        save_to_mongodb(all_results)

    print("Processus terminé.")

if __name__ == "__main__":
    main()
