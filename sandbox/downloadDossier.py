import os
import json
import requests
import zipfile
import io
import time

# 1. Charger les données JSON depuis le fichier
json_path = "resultats_uniques.json"
try:
    with open(json_path, "r", encoding="utf-8") as f:
        appels_offres = json.load(f)
except Exception as e:
    print(f"Erreur lors de la lecture du fichier {json_path}: {e}")
    exit(1)

# 2. Créer le dossier principal
dossier_global = "TousDossiers"
os.makedirs(dossier_global, exist_ok=True)

# Compteurs pour suivre les réussites et les échecs
dossiers_telecharges_succes = 0
dossiers_echoues = 0

# 3. Boucle sur chaque appel d'offres
for ao in appels_offres:
    reference = ao.get("reference") or ao.get("refConsultation") or ao.get("consId") or "SansReference"
    url_dossier = ao.get("urldossierDirect")

    if not url_dossier:
        print(f"Attention: URL manquante pour l'élément {ao}. On passe au suivant.")
        continue

    print(f"--- Traitement de la référence : {reference} ---")

    # Nettoyer le nom du dossier
    nom_sous_dossier = str(reference).replace('/', '_').replace('\\', '_')
    chemin_sous_dossier = os.path.join(dossier_global, nom_sous_dossier)
    os.makedirs(chemin_sous_dossier, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/zip,application/octet-stream,application/x-zip-compressed,*/*",
        "Referer": "https://www.marchespublics.gov.ma/",
        "Origin": "https://www.marchespublics.gov.ma",
        "Connection": "keep-alive"
    }

    response = None
    max_retries = 10  # Augmenter le nombre de tentatives à 10
    for attempt in range(max_retries):
        try:
            print(f"📥 Téléchargement du fichier depuis {url_dossier}... (tentative {attempt+1})")
            response = requests.get(url_dossier, headers=headers, timeout=60)
            response.raise_for_status()
            dossiers_telecharges_succes += 1
            break  # Succès, on sort de la boucle
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur de téléchargement pour {reference}: {e}")
            if attempt < max_retries - 1:
                print("Nouvelle tentative dans 5 secondes...")
                time.sleep(5)
            else:
                print("Abandon du téléchargement pour ce dossier.")
                dossiers_echoues += 1
                response = None

    if response is None:
        continue

    content_type = response.headers.get("Content-Type", "")
    is_zip = ("zip" in content_type) or (response.content[:4] == b'PK\x03\x04')

    if is_zip:
        fichier_zip = io.BytesIO(response.content)
        print(f"📦 Décompression des fichiers dans {chemin_sous_dossier}...")
        try:
            with zipfile.ZipFile(fichier_zip, 'r') as zip_ref:
                zip_ref.extractall(chemin_sous_dossier)
            print(f"✅ Succès pour la référence {reference} !")
        except zipfile.BadZipFile:
            print(f"❌ Erreur: Le fichier téléchargé pour {reference} n'est pas un fichier ZIP valide.")
            dossiers_echoues += 1
    else:
        # Sauvegarde pour inspection
        with open(os.path.join(chemin_sous_dossier, "downloaded_file_unknown.bin"), "wb") as file:
            file.write(response.content)
        print(f"❌ Le fichier téléchargé pour {reference} n'est pas un ZIP valide (Content-Type: {content_type}). Fichier sauvegardé pour inspection.")
        dossiers_echoues += 1

    # Afficher le nombre de dossiers réussis et échoués à chaque tentative
    print(f"📊 Résultats jusqu'à maintenant : {dossiers_telecharges_succes} dossiers téléchargés avec succès, {dossiers_echoues} dossiers échoués.")

# Afficher le total à la fin du script
print("\n--- Script terminé. ---")
print(f"📊 Résultats finaux : {dossiers_telecharges_succes} dossiers téléchargés avec succès, {dossiers_echoues} dossiers échoués.")
