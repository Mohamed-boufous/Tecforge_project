import json
import time
import os
import certifi
import hashlib
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import Select
from pymongo import MongoClient, InsertOne
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()
MONGO_URI = os.getenv("MONGO2_URI") 
URL = "https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseAdvancedSearch&AllCons&EnCours"
BASE_URL_SITE = "https://www.marchespublics.gov.ma/"

def generer_liens(lien_initial: str):
    """
    Transforme le lien des détails en lien de téléchargement de dossier.
    """
    if not lien_initial or 'N/A' in lien_initial:
        return 'N/A'
    
    lien_complet = lien_initial
    if lien_complet.startswith('?page='):
       lien_complet = "https://www.marchespublics.gov.ma/index.php" + lien_complet
       
    lien_final = lien_complet.replace("entreprise.EntrepriseDetailsConsultation", "entreprise.EntrepriseDownloadCompleteDce")
    lien_final = lien_final.replace("refConsultation=", "reference=")
    lien_final = lien_final.replace("orgAcronyme=", "orgAcronym=")
    return lien_final

def parse_html(html_content):
    if not html_content: return []
    soup = BeautifulSoup(html_content, 'html.parser')
    offres = []
    
    tableau_resultats = soup.find('table', class_='table-results')
    if not tableau_resultats or not tableau_resultats.find('tbody'):
        print("Le tableau des résultats n'a pas été trouvé.")
        return []
    
    lignes = tableau_resultats.find('tbody').find_all('tr')
    print(f"-> {len(lignes)} offres trouvées sur cette page.")

    for ligne in lignes:
        cellules = ligne.find_all('td')
        if len(cellules) < 5: continue
        try:
            # On cible la première cellule visible pour la procédure, le domaine et la date
            cell_ref = cellules[1]
            type_procedure_div = cell_ref.find('div', id=lambda x: x and x.endswith('_type_procedure'))
            type_procedure = type_procedure_div.text.strip() if type_procedure_div else 'N/A'
            
            domaine_div = cell_ref.find('div', id=lambda x: x and x.endswith('_panelBlocCategorie'))
            domaine = domaine_div.text.strip() if domaine_div else 'N/A'
            
            # La date est le dernier div sans id/classe spécifique dans cette cellule
            divs_in_cell = cell_ref.find_all('div', recursive=False)
            date_publication = divs_in_cell[-1].text.strip() if divs_in_cell else 'N/A'
            
            # Données des autres cellules
            cell_objet = cellules[2]
            reference = cell_objet.find('span', class_='ref').text.strip()
            objet_div = cell_objet.find('div', id=lambda x: x and x.endswith('_panelBlocObjet'))
            objet = objet_div.find('strong').next_sibling.strip()
            acheteur_div = cell_objet.find('div', id=lambda x: x and x.endswith('_panelBlocDenomination'))
            acheteur = acheteur_div.find('strong').next_sibling.strip()
            lieu = cellules[3].get_text(separator=', ', strip=True)
            date_limite = cellules[4].find('div', class_='cloture-line').get_text(separator=' ', strip=True)
            
            # On cible le lien de consultation par son contenu textuel 'EntrepriseDetailConsultation'
            lien_complet = 'N/A'
            cellule_actions = cellules[-1]
            tag_a = cellule_actions.find('a')
            if tag_a and tag_a.has_attr('href'):
                lien_relatif = tag_a['href']
                lien_complet = BASE_URL_SITE + lien_relatif if lien_relatif.startswith('?') else lien_relatif

            # Génération du lien de dossier direct
            lien_dossier = generer_liens(lien_complet)

            offre = {
                "type_procedure": type_procedure,
                "domaine": domaine,
                "date_publication": date_publication,
                "reference": reference,
                "objet": objet,
                "acheteur_public": acheteur,
                "lieu_execution": lieu,
                "date_limite_remise_plis": date_limite,
                "lien_details": lien_complet,
                "lien_dossier_direct": lien_dossier
            }
            offres.append(offre)
        except (AttributeError, IndexError):
            continue
            
    return offres

def save_to_mongodb(data_list):
    if not MONGO_URI:
        print("Erreur: MONGO_URI n'est pas configuré.")
        return
    if not data_list:
        print("Aucune donnée à sauvegarder dans MongoDB.")
        return

    print(f"\nConnexion à MongoDB Atlas pour insérer {len(data_list)} offres...")
    client = None
    try:
        client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
        db = client.marchespublics_db
        collection = db.consultations
        
        collection.delete_many({})
        print("Ancienne collection vidée.")

        operations = [InsertOne(item) for item in data_list]
        
        if operations:
            result = collection.bulk_write(operations)
            print("Sauvegarde dans MongoDB terminée.")
            print(f"  - {result.inserted_count} offres insérées.")
        
    except Exception as e:
        print(f"Une erreur est survenue avec MongoDB : {e}")
    finally:
        if client:
            client.close()

# def save_to_json(data, filename="offres_marchespublics_complet.json"):
#     with open(filename, 'w', encoding='utf-8') as f:
#         json.dump(data, f, indent=4, ensure_ascii=False)
#     print(f"--- {len(data)} offres sauvegardées dans le fichier local '{filename}' ---")

# --- Script principal avec pagination ---
if __name__ == "__main__":
    all_offres = []
    page_actuelle = 1
    
    print("Démarrage du navigateur avec Selenium...")
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    # options.add_argument('window-size=1920x1080')
    options.add_argument('--disable-gpu')
    options.add_argument('--remote-debugging-port=9222')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-plugins')
    options.add_argument('--disable-images')
    # chrome_options.add_argument('--disable-javascript')  # Only if we don't need JS
    options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36')

    # Memory optimization
    options.add_argument('--memory-pressure-off')
    options.add_argument('--max_old_space_size=4096')
    
    # Set binary location if needed
    options.binary_location = '/snap/bin/chromium'
    
    #driver = webdriver.Chrome(options=chrome_options)
  
    driver = None

    try:
        service = Service('/usr/local/bin/chromedriver')
        driver = webdriver.Chrome(service=service, options=options)
        driver.get(URL)
        
        try:
            print("Changement pour afficher 500 résultats par page...")
            select_element = driver.find_element(By.ID, 'ctl0_CONTENU_PAGE_resultSearch_listePageSizeBottom')
            Select(select_element).select_by_value('500')
            print("Attente du rechargement de la page...")
            time.sleep(5)
        except NoSuchElementException:
            print("Le menu déroulant n'a pas été trouvé.")

        while True:
            print(f"\nTraitement de la page {page_actuelle}...")
            time.sleep(3)
            html = driver.page_source
            offres_de_la_page = parse_html(html)
            
            if offres_de_la_page:
                all_offres.extend(offres_de_la_page)
            else:
                if page_actuelle == 1: print("Aucune offre trouvée. Arrêt.")
                break

            try:
                bouton_suivant = driver.find_element(By.CSS_SELECTOR, 'a[id*="PagerBottom_ctl2"]')
                print("Bouton 'Suivant' trouvé, passage à la page suivante...")
                driver.execute_script("arguments[0].click();", bouton_suivant)
                page_actuelle += 1
            except NoSuchElementException:
                print("C'est la dernière page. Fin du scraping.")
                break
    except Exception as e:
        print(f"Une erreur générale est survenue : {e}")
    finally:
        if driver:
            driver.quit()

    if all_offres:
        # On sauvegarde d'abord en local dans un fichier JSON
        # save_to_json(all_offres)
        # Puis on sauvegarde dans la base de données MongoDB Atlas
        save_to_mongodb(all_offres)
    else:
        print("Aucune offre n'a pu être extraite au total.")
